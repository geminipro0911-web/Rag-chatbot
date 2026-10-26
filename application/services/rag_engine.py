"""
Document RAG Engine Service.
Implements Module 3.2:
- Hybrid vector search (dense top-40 + sparse top-40 -> RRF fusion -> top-20) via Qdrant.
- Mandatory query-level RBAC filtering ((department_id == X) OR (is_public == true) OR (owner_user_id == U)).
- Cross-encoder reranking (BGE-Reranker-v2-m3 -> top-5).
- Threshold rejection (< reranker_threshold -> "Không tìm thấy thông tin...").
- Optional section context expansion.
- Structured contextual answering with in-text citations [n] and References footer.
- Post-generation citation audit & self-correction retry loop.
"""

from __future__ import annotations

import inspect
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from application.interfaces.embedder import Embedder
from application.interfaces.llm_client import LLMClient
from application.interfaces.reranker import Reranker
from application.interfaces.vector_store import VectorStore
from application.prompts.prompts import (
    CITATION_CORRECTION_SYSTEM_PROMPT,
    DOCUMENT_RAG_SYSTEM_PROMPT,
)
from application.services.output_formatter import (
    OutputFormatter,
    SourceCitation,
)
from config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# RAG Execution DTOs
# ---------------------------------------------------------------------------

class RAGExecutionResult(BaseModel):
    """Result returned by Document RAG Engine."""
    answer_markdown: str = Field(..., description="Generated markdown answer with citations")
    sources: List[SourceCitation] = Field(default_factory=list, description="Validated source citations")
    raw_chunks: List[Dict[str, Any]] = Field(default_factory=list, description="Retrieved chunk objects")
    rerank_scores: List[float] = Field(default_factory=list, description="Top rerank scores")
    audit_passed: bool = Field(default=True, description="True if citation audit passed")
    retries_used: int = Field(default=0, description="Number of citation self-correction retries")
    status: str = Field(default="success", description="'success' | 'empty' | 'threshold_rejected'")

    @property
    def citations(self) -> List[SourceCitation]:
        """Backward-compatibility alias for sources."""
        return self.sources


# ---------------------------------------------------------------------------
# RAG Engine Implementation
# ---------------------------------------------------------------------------

class RAGEngine:
    """
    Orchestrates Document RAG retrieval, cross-encoder reranking,
    prompt assembly, LLM answering, and citation verification.
    """

    def __init__(
        self,
        vector_store: VectorStore,
        embedder: Embedder,
        reranker: Reranker,
        llm_client: LLMClient,
        reranker_threshold: Optional[float] = None,
        search_limit: int = 20,
        rerank_top_k: int = 5,
        enable_context_expansion: bool = True,
    ):
        self.vector_store = vector_store
        self.embedder = embedder
        self.reranker = reranker
        self.llm_client = llm_client
        self.reranker_threshold = (
            reranker_threshold if reranker_threshold is not None else settings.reranker_threshold
        )
        self.search_limit = search_limit
        self.rerank_top_k = rerank_top_k
        self.enable_context_expansion = enable_context_expansion

    async def answer_query(
        self,
        query: str,
        department_id: str,
        user_id: str,
        is_admin: bool = False,
        is_public_only: bool = False,
    ) -> RAGExecutionResult:
        """
        Executes end-to-end RAG pipeline for a user query under strict RBAC constraints.
        """
        clean_query = query.strip()
        if not clean_query:
            return RAGExecutionResult(
                answer_markdown="Vui lòng cung cấp câu hỏi hợp lệ.",
                status="empty",
            )

        # 1. Hybrid Embedding Generation (Dense 1024d + Sparse lexical)
        try:
            embedded = self.embedder.embed_query(clean_query)
            query_dense = embedded.get("dense", [])
            sparse_indices = embedded.get("sparse_indices", [])
            sparse_values = embedded.get("sparse_values", [])
        except Exception as exc:
            logger.error(f"Failed to generate query embeddings: {exc}")
            return RAGExecutionResult(
                answer_markdown="Lỗi hệ thống khi mã hóa câu hỏi tìm kiếm.",
                status="empty",
            )

        # 2. Hybrid Search in Qdrant (Dense 40 + Sparse 40 -> RRF -> top 20) with RBAC Filter
        try:
            candidate_chunks = self.vector_store.hybrid_search(
                query_dense=query_dense,
                query_sparse_indices=sparse_indices,
                query_sparse_values=sparse_values,
                department_id=department_id,
                user_id=user_id,
                is_admin=is_admin,
                limit=self.search_limit,
                is_public_only=is_public_only,
            )
        except Exception as exc:
            logger.error(f"Vector search failed: {exc}")
            return RAGExecutionResult(
                answer_markdown="Lỗi hệ thống khi tìm kiếm tài liệu trong kho lưu trữ.",
                status="empty",
            )

        if not candidate_chunks:
            logger.info("Hybrid search returned 0 candidates for query.")
            return RAGExecutionResult(
                answer_markdown="Không tìm thấy thông tin trong các tài liệu bạn được phép truy cập.",
                status="empty",
            )

        # 3. Cross-Encoder Reranking
        doc_texts = [
            chunk.get("payload", {}).get("content") or chunk.get("payload", {}).get("text", "") or chunk.get("content", "") or chunk.get("text", "")
            for chunk in candidate_chunks
        ]

        try:
            rerank_results = self.reranker.rerank(
                query=clean_query,
                documents=doc_texts,
                top_k=self.rerank_top_k,
            )
        except Exception as exc:
            logger.warning(f"Reranker failed ({exc}); falling back to original search order.")
            rerank_results = [(i, 1.0 / (i + 1)) for i in range(min(len(candidate_chunks), self.rerank_top_k))]

        if not rerank_results:
            return RAGExecutionResult(
                answer_markdown="Không tìm thấy thông tin trong các tài liệu bạn được phép truy cập.",
                status="empty",
            )

        # Check reranker score threshold
        top_score = rerank_results[0][1]
        logger.info(f"Top reranker score: {top_score:.4f} (threshold: {self.reranker_threshold})")

        if top_score < self.reranker_threshold:
            logger.info(
                f"Top rerank score {top_score:.4f} below threshold {self.reranker_threshold}. Rejecting."
            )
            return RAGExecutionResult(
                answer_markdown="Không tìm thấy thông tin trong các tài liệu bạn được phép truy cập.",
                status="threshold_rejected",
                rerank_scores=[score for _, score in rerank_results],
            )

        # Select top-k candidate chunks
        selected_chunks: List[Dict[str, Any]] = []
        selected_scores: List[float] = []

        for orig_idx, score in rerank_results:
            # We filter chunks below threshold
            if score >= self.reranker_threshold or not selected_chunks:
                import copy
                chunk_copy = copy.deepcopy(candidate_chunks[orig_idx])
                chunk_copy["rerank_score"] = float(score)
                selected_chunks.append(chunk_copy)
                selected_scores.append(float(score))

        # 4. Optional Context Expansion (stitch adjacent chunks in same section)
        if self.enable_context_expansion:
            selected_chunks = self._expand_context(selected_chunks, candidate_chunks)

        # 5. Build Source Citations and Prompt Context
        citations: List[SourceCitation] = []
        context_blocks: List[str] = []

        for i, ch in enumerate(selected_chunks):
            idx = i + 1
            payload = ch.get("payload", {})
            file_name = payload.get("file_name", "Tài liệu nội bộ")
            page = payload.get("page_number") or payload.get("page")
            section_title = payload.get("section_title") or payload.get("heading_path") or "Chung"
            text_content = payload.get("content") or payload.get("text", "") or ch.get("content", "") or ch.get("text", "")
            score = ch.get("rerank_score")

            # First ~15 words for default quote if needed
            words = text_content.strip().split()
            sample_quote = " ".join(words[:15]) + ("..." if len(words) > 15 else "")

            citation = SourceCitation(
                index=idx,
                file_name=file_name,
                page=page,
                section_title=section_title,
                quote=sample_quote,
                score=score,
            )
            citations.append(citation)

            block = (
                f"[{idx}] TÀI LIỆU: {file_name} | Trang: {page if page is not None else 'N/A'} | Mục: {section_title}\n"
                f"NỘI DUNG:\n{text_content}"
            )
            context_blocks.append(block)

        assembled_context = "\n\n---\n\n".join(context_blocks)
        user_prompt = (
            f"NGỮ CẢNH TÀI LIỆU:\n{assembled_context}\n\n"
            f"CÂU HỎI CỦA NGƯỜI DÙNG: {clean_query}\n\n"
            "Hãy trả lời câu hỏi dựa trên các tài liệu trên theo đúng quy tắc trích dẫn."
        )

        # 6. LLM Generation
        retries_used = 0
        raw_answer = ""
        try:
            llm_res = self.llm_client.chat_completion(
                messages=[
                    {"role": "system", "content": DOCUMENT_RAG_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
            )
            if inspect.isawaitable(llm_res):
                raw_answer = await llm_res
            else:
                raw_answer = llm_res
        except Exception as exc:
            logger.error(f"LLM generation failed: {exc}")
            return RAGExecutionResult(
                answer_markdown="Đã xảy ra lỗi khi tạo câu trả lời từ mô hình ngôn ngữ.",
                status="empty",
            )

        # 7. Post-Generation Citation Audit & Self-Correction
        is_valid, error_reason, _ = OutputFormatter.audit_citations(
            text=raw_answer,
            source_chunks=selected_chunks,
            fuzzy_threshold=90.0,
        )

        final_answer = raw_answer

        if not is_valid:
            logger.warning(f"Citation audit failed: {error_reason}. Triggering self-correction retry...")
            retries_used += 1

            correction_prompt = CITATION_CORRECTION_SYSTEM_PROMPT.format(
                citation_error_reason=error_reason
            )

            try:
                corr_res = self.llm_client.chat_completion(
                    messages=[
                        {"role": "system", "content": DOCUMENT_RAG_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                        {"role": "assistant", "content": raw_answer},
                        {"role": "user", "content": f"{correction_prompt}\n\nVui lòng viết lại câu trả lời:"},
                    ],
                    temperature=0.1,
                )
                if inspect.isawaitable(corr_res):
                    retry_answer = await corr_res
                else:
                    retry_answer = corr_res
                # Second audit check
                is_valid_2, error_reason_2, _ = OutputFormatter.audit_citations(
                    text=retry_answer,
                    source_chunks=selected_chunks,
                    fuzzy_threshold=90.0,
                )
                if is_valid_2:
                    final_answer = retry_answer
                    is_valid = True
                else:
                    logger.warning(f"Second citation audit failed ({error_reason_2}). Sanitizing citations.")
                    final_answer = OutputFormatter.sanitize_citations(
                        retry_answer, max_valid_index=len(selected_chunks)
                    )
            except Exception as e:
                logger.error(f"Citation self-correction call failed: {e}. Sanitizing original answer.")
                final_answer = OutputFormatter.sanitize_citations(
                    raw_answer, max_valid_index=len(selected_chunks)
                )

        # If references section is missing from answer, append standard references block
        if "### 📚 Chỉ mục nguồn trích dẫn" not in final_answer and "Chỉ mục nguồn trích dẫn" not in final_answer:
            ref_block = OutputFormatter.render_references_block(citations)
            if ref_block:
                final_answer = f"{final_answer.strip()}\n\n{ref_block}"

        return RAGExecutionResult(
            answer_markdown=final_answer.strip(),
            sources=citations,
            raw_chunks=selected_chunks,
            rerank_scores=selected_scores,
            audit_passed=is_valid,
            retries_used=retries_used,
            status="success",
        )

    def _expand_context(
        self,
        top_chunks: List[Dict[str, Any]],
        all_candidates: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Expands context by stitching adjacent chunks from the same document
        and section if they exist in the candidate pool.
        """
        seen_ids = set()
        expanded: List[Dict[str, Any]] = []

        for ch in top_chunks:
            c_id = ch.get("chunk_id")
            if c_id in seen_ids:
                continue
            seen_ids.add(c_id)
            expanded.append(ch)

            doc_id = ch.get("payload", {}).get("doc_id")
            sec_title = ch.get("payload", {}).get("section_title")
            p_payload = ch.get("payload", {})
            page = p_payload.get("page") if p_payload.get("page") is not None else p_payload.get("page_number")

            if not doc_id:
                continue

            # Look for adjacent chunk in candidates
            for cand in all_candidates:
                cand_id = cand.get("chunk_id")
                if cand_id in seen_ids:
                    continue
                c_payload = cand.get("payload", {})
                cand_doc = c_payload.get("doc_id")
                cand_sec = c_payload.get("section_title")
                cand_page = c_payload.get("page") if c_payload.get("page") is not None else c_payload.get("page_number")
                cand_idx = c_payload.get("chunk_index")
                ch_idx = p_payload.get("chunk_index")

                is_adjacent = False
                prepend = False
                if cand_doc == doc_id and cand_sec == sec_title:
                    if cand_idx is not None and ch_idx is not None:
                        if abs(cand_idx - ch_idx) == 1:
                            is_adjacent = True
                            prepend = (cand_idx < ch_idx)
                    elif abs((cand_page or 0) - (page or 0)) <= 1:
                        is_adjacent = True
                        prepend = ((cand_page or 0) < (page or 0))

                if is_adjacent:
                    # Stitch texts in document order
                    ch_text = p_payload.get("text") or p_payload.get("content") or ""
                    cand_text = c_payload.get("text") or c_payload.get("content") or ""
                    if cand_text and cand_text not in ch_text:
                        combined_text = f"{cand_text}\n\n{ch_text}" if prepend else f"{ch_text}\n\n{cand_text}"
                        ch["payload"]["text"] = combined_text
                        ch["payload"]["content"] = combined_text
                        seen_ids.add(cand_id)
                        break

        return expanded
