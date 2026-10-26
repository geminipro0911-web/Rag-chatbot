"""
Hybrid Execution Engine Service.
Implements Module 3.3:
- Consumes sub_questions from Router (tabular + document).
- Parallel execution using asyncio.gather (Tabular in process pool/executor, Document RAG).
- Structured branch results: {engine, status, data/markdown, sources}.
- Cross-engine fallback (exactly once if primary engine returns 0 results).
- Synthesis prompt unifying tabular markdown numbers and document [n] references.
- Handles partial branch failures gracefully with explicit disclaimer notices.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from typing import Any, Dict, List, Optional

import pandas as pd
from pydantic import BaseModel, Field

from application.interfaces.llm_client import LLMClient
from application.prompts.prompts import (
    CITATION_CORRECTION_SYSTEM_PROMPT,
    HYBRID_SYNTHESIS_SYSTEM_PROMPT,
)
from application.services.output_formatter import (
    ChatResponse,
    DebugInfo,
    OutputFormatter,
    SourceCitation,
    TableResultDTO,
    format_dataframe_for_display,
)
from application.services.rag_engine import RAGEngine, RAGExecutionResult
from application.services.tabular_executor import (
    TabularExecutionResult,
    TabularExecutor,
)
from domain.entities.entity_link import EntityLinkResult
from domain.entities.query_intent import SubQuestion

logger = logging.getLogger(__name__)


class HybridBranchResult(BaseModel):
    """Execution status and data payload from a single hybrid branch."""
    engine: str = Field(..., description="'TABULAR' or 'DOCUMENT'")
    status: str = Field(..., description="'success' | 'empty' | 'error' | 'threshold_rejected'")
    markdown: str = Field(default="", description="Rendered text or table markdown")
    data: Optional[List[Dict[str, Any]]] = Field(default=None, description="Raw rows if tabular")
    columns: List[str] = Field(default_factory=list, description="Columns if tabular")
    sources: List[SourceCitation] = Field(default_factory=list, description="Citations if document")
    table_dto: Optional[TableResultDTO] = Field(default=None, description="Tabular metadata")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    raw_chunks: List[Dict[str, Any]] = Field(default_factory=list, description="Raw chunk payloads")


class HybridEngine:
    """
    Coordinates simultaneous execution of Tabular and Document engines,
    manages cross-engine single fallback, and synthesizes cohesive responses.
    """

    def __init__(
        self,
        tabular_executor: TabularExecutor,
        rag_engine: RAGEngine,
        llm_client: LLMClient,
    ):
        self.tabular_executor = tabular_executor
        self.rag_engine = rag_engine
        self.llm_client = llm_client

    async def execute_hybrid(
        self,
        query: str,
        department_id: str,
        user_id: str,
        is_admin: bool = False,
        sub_questions: Optional[List[SubQuestion]] = None,
        candidate_tables: Optional[List[Dict[str, Any]]] = None,
        entity_links: Optional[List[EntityLinkResult]] = None,
        fewshot_examples: Optional[List[Dict[str, Any]]] = None,
        is_public_only: bool = False,
    ) -> ChatResponse:
        """
        Executes parallel hybrid workflow with cross-engine fallback and synthesis.
        """
        start_time = time.time()
        sub_questions = sub_questions or []
        candidate_tables = candidate_tables or []
        entity_links = entity_links or []
        fewshot_examples = fewshot_examples or []

        # 1. Resolve sub-questions from router or fallback to main query
        q_tabular: str = query
        q_document: str = query

        for sq in sub_questions:
            engine_type = sq.engine.strip().upper()
            if engine_type == "TABULAR":
                q_tabular = sq.q
            elif engine_type == "DOCUMENT":
                q_document = sq.q

        logger.info(
            f"Hybrid dispatch: Tabular Sub-Q: '{q_tabular}' | Document Sub-Q: '{q_document}'"
        )

        # 2. Parallel Branch Execution (asyncio.gather)
        async def run_tabular_branch(q: str) -> HybridBranchResult:
            if not candidate_tables:
                return HybridBranchResult(
                    engine="TABULAR",
                    status="empty",
                    markdown="*Không có bảng dữ liệu phù hợp để thực thi truy vấn.*",
                )
            try:
                res: TabularExecutionResult = await self.tabular_executor.execute_query(
                    query=q,
                    candidate_tables=candidate_tables,
                    entity_links=entity_links,
                    fewshot_examples=fewshot_examples,
                )
                if not res.success or res.data is None:
                    return HybridBranchResult(
                        engine="TABULAR",
                        status="empty" if res.row_count == 0 else "error",
                        error=res.error,
                        markdown=f"*{res.error}*" if (is_admin and res.error) else "*Không có dữ liệu khớp điều kiện.*",
                    )

                df = pd.DataFrame(res.data)
                table_md, summary_md = format_dataframe_for_display(df)
                full_md = table_md
                if summary_md:
                    full_md += f"\n\n{summary_md}"

                actual_tbl = candidate_tables[0]
                if res.code:
                    for tbl in candidate_tables:
                        alias = tbl.get("table_alias") or tbl.get("table_name")
                        if alias and alias.lower() in res.code.lower():
                            actual_tbl = tbl
                            break
                t_name = actual_tbl.get("table_alias") or actual_tbl.get("table_name", "Bảng dữ liệu")
                f_name = actual_tbl.get("file_name")
                s_name = actual_tbl.get("sheet_name")

                full_md += f"\n\n📊 Nguồn dữ liệu: File [{f_name or t_name}] - Sheet [{s_name or 'Sheet1'}]"

                table_dto = TableResultDTO(
                    table_name=t_name,
                    file_name=f_name,
                    sheet_name=s_name,
                    total_rows=res.row_count,
                    displayed_rows=min(res.row_count, 20) if res.row_count > 50 else res.row_count,
                    columns=res.columns,
                )

                return HybridBranchResult(
                    engine="TABULAR",
                    status="success",
                    markdown=full_md,
                    data=res.data,
                    columns=res.columns,
                    table_dto=table_dto,
                )
            except Exception as e:
                logger.error(f"Tabular branch failed: {e}")
                return HybridBranchResult(
                    engine="TABULAR",
                    status="error",
                    error=str(e),
                    markdown=f"*Lỗi thực thi dữ liệu bảng: {e}*" if is_admin else "*Không thể trích xuất số liệu bảng phù hợp.*",
                )

        async def run_document_branch(q: str) -> HybridBranchResult:
            try:
                res: RAGExecutionResult = await self.rag_engine.answer_query(
                    query=q,
                    department_id=department_id,
                    user_id=user_id,
                    is_admin=is_admin,
                    is_public_only=is_public_only,
                )
                return HybridBranchResult(
                    engine="DOCUMENT",
                    status=res.status,
                    markdown=res.answer_markdown,
                    sources=res.sources,
                    raw_chunks=res.raw_chunks,
                )
            except Exception as e:
                logger.error(f"Document branch failed: {e}")
                return HybridBranchResult(
                    engine="DOCUMENT",
                    status="error",
                    error=str(e),
                    markdown=f"*Lỗi truy vấn tài liệu: {e}*",
                )

        tabular_task = run_tabular_branch(q_tabular)
        document_task = run_document_branch(q_document)

        tab_res, doc_res = await asyncio.gather(tabular_task, document_task)

        # 3. Cross-Engine Single Fallback
        # If Tabular returned 0 results or error, try Document RAG for tabular sub-question exactly once
        fallback_attempted = False
        if tab_res.status in ("empty", "error") and q_tabular != q_document and not fallback_attempted:
            logger.info("Tabular branch returned empty/error. Attempting single fallback to Document RAG...")
            fallback_attempted = True
            try:
                fallback_rag: RAGExecutionResult = await self.rag_engine.answer_query(
                    query=q_tabular,
                    department_id=department_id,
                    user_id=user_id,
                    is_admin=is_admin,
                    is_public_only=is_public_only,
                )
                if fallback_rag.status == "success" and fallback_rag.sources:
                    # Merge fallback documents into document branch
                    doc_res.sources.extend(fallback_rag.sources)
                    doc_res.raw_chunks.extend(fallback_rag.raw_chunks)
                    doc_res.markdown += f"\n\n**Bổ sung thông tin từ tài liệu:**\n{fallback_rag.answer_markdown}"
                    doc_res.status = "success"
            except Exception as e:
                logger.warning(f"Fallback to Document RAG failed: {e}")

        # If Document returned empty/threshold_rejected, and Tabular succeeded, try Tabular fallback for doc query if candidate tables exist
        elif doc_res.status in ("empty", "threshold_rejected") and q_document != q_tabular and not fallback_attempted:
            if candidate_tables:
                logger.info("Document branch returned empty. Attempting single fallback to Tabular...")
                fallback_attempted = True
                try:
                    fallback_tab = await run_tabular_branch(q_document)
                    if fallback_tab.status == "success":
                        tab_res = fallback_tab
                except Exception as e:
                    logger.warning(f"Fallback to Tabular failed: {e}")

        # 4. Synthesize Cohesive Response via LLM
        synthesis_markdown = await self._synthesize_response(
            original_query=query,
            tab_res=tab_res,
            doc_res=doc_res,
        )

        latency_ms = round((time.time() - start_time) * 1000, 2)

        debug_info = DebugInfo(
            rewritten_query=query,
            language="hybrid (duckdb+rag)",
            attempts=1,
            latency_ms=latency_ms,
        )

        tables_list = [tab_res.table_dto] if tab_res.table_dto else []

        return ChatResponse(
            answer_markdown=synthesis_markdown,
            route="HYBRID",
            sources=doc_res.sources,
            tables=tables_list,
            debug=debug_info,
        )

    async def _synthesize_response(
        self,
        original_query: str,
        tab_res: HybridBranchResult,
        doc_res: HybridBranchResult,
    ) -> str:
        """
        Synthesizes both branches into a structured executive report.
        """
        # Prepare context blocks
        tab_section = ""
        if tab_res.status == "success":
            tab_section = f"DỮ LIỆU BẢNG & SỐ LIỆU:\n{tab_res.markdown}"
        else:
            tab_section = (
                "DỮ LIỆU BẢNG: [Không có dữ liệu số liệu hoặc truy vấn không trả về kết quả. "
                f"Lý do: {tab_res.error or 'Không khớp điều kiện'}]"
            )

        doc_section = ""
        if doc_res.status == "success":
            doc_section = f"QUY ĐỊNH, CHÍNH SÁCH & VĂN BẢN TRÍCH DẪN:\n{doc_res.markdown}"
        else:
            doc_section = (
                "QUY ĐỊNH & VĂN BẢN: [Không tìm thấy văn bản hoặc quy định liên quan "
                "trong các tài liệu được cấp quyền]"
            )

        synthesis_user_prompt = (
            f"CÂU HỎI BAN ĐẦU CỦA NGƯỜI DÙNG: {original_query}\n\n"
            f"{tab_section}\n\n"
            f"{doc_section}\n\n"
            "Hãy tổng hợp thành một câu trả lời hoàn chỉnh, mạch lạc và chính xác theo đúng hướng dẫn hệ thống."
        )

        try:
            llm_res = self.llm_client.chat_completion(
                messages=[
                    {"role": "system", "content": HYBRID_SYNTHESIS_SYSTEM_PROMPT},
                    {"role": "user", "content": synthesis_user_prompt},
                ],
                temperature=0.1,
            )
            if inspect.isawaitable(llm_res):
                raw_synthesis = await llm_res
            else:
                raw_synthesis = llm_res
        except Exception as e:
            logger.error(f"Synthesis LLM call failed: {e}")
            # Fallback deterministic assembly
            parts = []
            if tab_res.status == "success":
                parts.append(f"### 📊 Dữ liệu số liệu:\n{tab_res.markdown}")
            else:
                parts.append("⚠️ Lưu ý: Không tìm thấy dữ liệu số liệu tương ứng trong các bảng bạn được cấp quyền.")

            if doc_res.status == "success":
                parts.append(f"### 📋 Quy định & Văn bản:\n{doc_res.markdown}")
            else:
                parts.append("⚠️ Lưu ý: Không tìm thấy văn bản quy định liên quan.")

            return "\n\n".join(parts)

        # Audit synthesis citations if document sources were present
        if doc_res.raw_chunks:
            is_valid, error_reason, _ = OutputFormatter.audit_citations(
                text=raw_synthesis,
                source_chunks=doc_res.raw_chunks,
                fuzzy_threshold=90.0,
            )
            if not is_valid:
                logger.warning(f"Hybrid synthesis citation audit failed ({error_reason}). Retrying...")
                try:
                    corr_res = self.llm_client.chat_completion(
                        messages=[
                            {"role": "system", "content": HYBRID_SYNTHESIS_SYSTEM_PROMPT},
                            {"role": "user", "content": synthesis_user_prompt},
                            {"role": "assistant", "content": raw_synthesis},
                            {
                                "role": "user",
                                "content": CITATION_CORRECTION_SYSTEM_PROMPT.format(
                                    citation_error_reason=error_reason
                                ),
                            },
                        ],
                        temperature=0.1,
                    )
                    if inspect.isawaitable(corr_res):
                        retry_synthesis = await corr_res
                    else:
                        retry_synthesis = corr_res
                    raw_synthesis = OutputFormatter.sanitize_citations(
                        retry_synthesis, max_valid_index=len(doc_res.raw_chunks)
                    )
                except Exception as ex:
                    logger.error(f"Synthesis retry failed: {ex}")
                    raw_synthesis = OutputFormatter.sanitize_citations(
                        raw_synthesis, max_valid_index=len(doc_res.raw_chunks)
                    )

        # If References section is missing but sources exist, append references block
        if doc_res.sources and "### 📚 Chỉ mục nguồn trích dẫn" not in raw_synthesis and "Chỉ mục nguồn trích dẫn" not in raw_synthesis:
            ref_block = OutputFormatter.render_references_block(doc_res.sources)
            if ref_block:
                raw_synthesis = f"{raw_synthesis.strip()}\n\n{ref_block}"

        return raw_synthesis.strip()
