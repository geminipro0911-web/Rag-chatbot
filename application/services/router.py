"""
Router Service.
Implements Module 2:
- 2.1 Query rewriting using last N=6 conversation turns.
- 2.2 Intent routing with structured output and policy enforcement.
- 2.3 Table selection combining embedding similarity and keyword matching.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from pydantic import BaseModel, Field

from application.interfaces.embedder import Embedder
from application.interfaces.llm_client import LLMClient
from application.services.entity_linker import normalize_entity_text
from domain.entities.query_intent import QueryIntent, SubQuestion

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper Mathematical Functions & Caching
# ---------------------------------------------------------------------------

_ROUTER_EMBEDDING_CACHE: Dict[str, List[float]] = {}
_MAX_CACHE_SIZE = 2048


def _get_or_compute_embeddings(embedder: Embedder, texts: List[str]) -> List[Optional[List[float]]]:
    """Retrieve embeddings from cache, batch computing and caching only cache misses."""
    if not texts:
        return []
    results: List[Optional[List[float]]] = [None] * len(texts)
    missing_indices: List[int] = []
    missing_texts: List[str] = []

    for i, t in enumerate(texts):
        if t in _ROUTER_EMBEDDING_CACHE:
            results[i] = _ROUTER_EMBEDDING_CACHE[t]
        else:
            missing_indices.append(i)
            missing_texts.append(t)

    if missing_texts:
        try:
            if hasattr(embedder, "embed_documents"):
                computed = embedder.embed_documents(missing_texts)
                computed_vecs = [v.get("dense") if isinstance(v, dict) else v for v in computed]
            else:
                computed_vecs = [embedder.embed_query(t) for t in missing_texts]

            for idx, vec in zip(missing_indices, computed_vecs):
                if vec is not None:
                    if len(_ROUTER_EMBEDDING_CACHE) >= _MAX_CACHE_SIZE:
                        keys_to_del = list(_ROUTER_EMBEDDING_CACHE.keys())[: _MAX_CACHE_SIZE // 2]
                        for k in keys_to_del:
                            _ROUTER_EMBEDDING_CACHE.pop(k, None)
                    _ROUTER_EMBEDDING_CACHE[texts[idx]] = vec
                results[idx] = vec
        except Exception as e:
            logger.warning("Error computing missing embeddings in router: %s", e)

    return results


def _extract_dense_vector(v: Any) -> List[float]:
    if isinstance(v, dict):
        return v.get("dense", [])
    if isinstance(v, (list, tuple, np.ndarray)):
        return list(v)
    return []


def cosine_similarity(v1: Any, v2: Any) -> float:
    """Computes cosine similarity between two float vectors or embedding dicts."""
    vec1 = _extract_dense_vector(v1)
    vec2 = _extract_dense_vector(v2)
    if not vec1 or not vec2:
        return 0.0
    a = np.array(vec1, dtype=np.float32)
    b = np.array(vec2, dtype=np.float32)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


# ---------------------------------------------------------------------------
# Router Implementation
# ---------------------------------------------------------------------------

class Router:
    """
    Intelligent router handling conversational query rewriting,
    intent classification (TABULAR, DOCUMENT, HYBRID, CLARIFY, CHITCHAT, OUT_OF_SCOPE),
    RBAC-compliant candidate pre-filtering, and hybrid table selection.
    """

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        embedder: Optional[Embedder] = None,
    ):
        self.llm_client = llm_client
        self.embedder = embedder

    # -----------------------------------------------------------------------
    # 2.1 Query Rewriting
    # -----------------------------------------------------------------------

    async def rewrite_query(
        self,
        query: str,
        chat_history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """
        Rewrites conversational follow-up questions into standalone queries
        using the last N=6 dialogue turns.

        Args:
            query: Current user question (e.g. 'còn quý 2 thì sao?').
            chat_history: List of previous turns [{'role': 'user'|'assistant', 'content': '...'}].

        Returns:
            Rewritten standalone question in Vietnamese.
        """
        clean_q = query.strip()
        if not chat_history:
            return clean_q

        # Take last N=6 turns
        recent_history = chat_history[-6:]
        if not recent_history:
            return clean_q

        # Format history string
        history_lines = []
        for turn in recent_history:
            role = "Người dùng" if turn.get("role") == "user" else "Trợ lý"
            content = turn.get("content", "").strip()
            if content:
                history_lines.append(f"{role}: {content}")

        if not history_lines:
            return clean_q

        history_text = "\n".join(history_lines)

        system_prompt = (
            "Bạn là trợ lý AI chuyên viết lại câu hỏi hội thoại thành câu hỏi độc lập, "
            "đầy đủ ngữ cảnh trong hệ thống RAG & phân tích bảng biểu doanh nghiệp.\n"
            "Nhiệm vụ: Dựa vào lịch sử hội thoại gần nhất, hãy phân giải các đại từ thay thế (nó, họ, đó, đơn vị này...), "
            "thời gian tương đối ('còn quý 2 thì sao?', 'thế năm ngoái?'), câu hỏi rút gọn để tạo thành "
            "MỘT câu hỏi tiếng Việt độc lập, rõ ràng, giữ nguyên ý định tra cứu ban đầu.\n"
            "Nếu câu hỏi hiện tại đã độc lập và đầy đủ nghĩa, giữ nguyên nội dung.\n"
            "QUY TẮC: CHỈ trả về câu hỏi đã viết lại, không thêm lời chào, lời dẫn hay giải thích."
        )

        user_prompt = (
            f"Lịch sử hội thoại gần nhất:\n{history_text}\n\n"
            f"Câu hỏi hiện tại của người dùng: \"{clean_q}\"\n\n"
            "Câu hỏi độc lập viết lại:"
        )

        if self.llm_client:
            try:
                rewritten = await self.llm_client.chat_completion(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.0,
                    max_tokens=256,
                )
                rewritten = rewritten.strip().strip('"').strip("'")
                if rewritten:
                    logger.info("Rewrote query: '%s' -> '%s'", clean_q, rewritten)
                    return rewritten
            except Exception as e:
                logger.warning("LLM query rewriting failed: %s, using original query", e)

        return clean_q

    # -----------------------------------------------------------------------
    # 2.2 Intent Routing
    # -----------------------------------------------------------------------

    async def route_query(
        self,
        rewritten_query: str,
        candidate_tables: List[Dict[str, Any]],
        candidate_docs: List[Dict[str, Any]],
        consecutive_clarifications: int = 0,
    ) -> QueryIntent:
        """
        Routes the rewritten query to the optimal execution engine with policy enforcement.

        Args:
            rewritten_query: Standalone query string.
            candidate_tables: RBAC-filtered list of tables [{'id': ..., 'name': ..., 'description': ...}].
            candidate_docs: RBAC-filtered list of documents [{'id': ..., 'title': ..., 'summary': ...}].
            consecutive_clarifications: Count of consecutive clarification turns in this session.

        Returns:
            QueryIntent structured entity.
        """
        # Pre-filtering if total candidates exceed 30 items
        filtered_tables = candidate_tables
        filtered_docs = candidate_docs

        if len(candidate_tables) + len(candidate_docs) > 30 and self.embedder:
            filtered_tables, filtered_docs = await self._prefilter_top_30_candidates(
                rewritten_query, candidate_tables, candidate_docs
            )

        # Build schema hints for LLM prompt
        table_hints = "\n".join([
            f"- Bảng ID '{t.get('id', '')}': {t.get('table_name', t.get('name', ''))} - {t.get('description', '')}"
            for t in filtered_tables[:20]
        ])
        doc_hints = "\n".join([
            f"- Tài liệu ID '{d.get('id', '')}': {d.get('title', '')} - {d.get('summary', '')}"
            for d in filtered_docs[:20]
        ])

        system_prompt = (
            "Bạn là bộ định tuyến ý định (Query Intent Router) cấp doanh nghiệp.\n"
            "Nhiệm vụ của bạn là phân tích câu hỏi người dùng và định tuyến chính xác vào một trong các nhánh:\n"
            "- TABULAR: Câu hỏi cần tính toán số liệu, tổng hợp, lọc dữ liệu bảng biểu, doanh thu, nhân sự, số liệu tài chính.\n"
            "- DOCUMENT: Câu hỏi tra cứu quy chế, chính sách, quy trình, tài liệu văn bản, điều khoản, định nghĩa.\n"
            "- HYBRID: Câu hỏi phức hợp cần kết hợp cả số liệu bảng biểu VÀ chính sách văn bản (ví dụ: số liệu doanh thu kèm quy định thưởng phạt).\n"
            "- CLARIFY: Câu hỏi mơ hồ, thiếu thông tin bắt buộc (mốc thời gian, đơn vị) hoặc confidence < 0.5 mà hệ thống không thể tự suy luận.\n"
            "- CHITCHAT: Chào hỏi, cảm ơn, hỏi thăm bot, xã giao thông thường.\n"
            "- OUT_OF_SCOPE: Câu hỏi hoàn toàn ngoài phạm vi doanh nghiệp (thời tiết, nấu ăn, chính trị, giải trí chung).\n\n"
            "Hãy trả về JSON theo đúng định dạng QueryIntent."
        )

        user_prompt = (
            f"Danh sách các bảng dữ liệu khả dụng (đã lọc quyền truy cập RBAC):\n"
            f"{table_hints if table_hints else '(Không có bảng nào)'}\n\n"
            f"Danh sách các tài liệu văn bản khả dụng (đã lọc quyền truy cập RBAC):\n"
            f"{doc_hints if doc_hints else '(Không có tài liệu nào)'}\n\n"
            f"Câu hỏi của người dùng: \"{rewritten_query}\"\n"
            f"Số lần đã yêu cầu làm rõ liên tiếp: {consecutive_clarifications}"
        )

        intent: Optional[QueryIntent] = None
        if self.llm_client:
            try:
                intent = await self.llm_client.structured_output(
                    prompt=user_prompt,
                    response_model=QueryIntent,
                    system_prompt=system_prompt,
                    temperature=0.0,
                )
            except Exception as e:
                logger.warning("LLM structured routing failed: %s, evaluating heuristics", e)

        # Fallback heuristic if LLM client is missing or returned error
        if intent is None:
            intent = self._heuristic_route(rewritten_query, filtered_tables, filtered_docs)

        # -------------------------------------------------------------------
        # Policy Enforcement (prompt.md specifications)
        # -------------------------------------------------------------------

        # Policy 1 & 2: 0.5 <= confidence < 0.75 between TABULAR and DOCUMENT -> HYBRID
        if 0.5 <= intent.confidence < 0.75 and intent.route in ("TABULAR", "DOCUMENT"):
            logger.info("Routing confidence %.2f in [0.5, 0.75) for %s -> forcing HYBRID", intent.confidence, intent.route)
            intent.route = "HYBRID"
            if not intent.sub_questions:
                intent.sub_questions = [
                    SubQuestion(q=rewritten_query, engine="TABULAR"),
                    SubQuestion(q=rewritten_query, engine="DOCUMENT"),
                ]

        # Policy 3: confidence < 0.5 or missing essential info -> CLARIFY
        if intent.confidence < 0.5 or intent.route == "CLARIFY":
            # Tối đa 1 lần CLARIFY liên tiếp; lần sau phải trả lời theo giả định hợp lý nhất
            if consecutive_clarifications >= 1:
                logger.info("Max consecutive clarifications reached (%d). Proceeding with best hypothesis.", consecutive_clarifications)
                # Pick best hypothesis route
                if intent.candidate_table_ids or filtered_tables:
                    intent.route = "TABULAR"
                    if not intent.candidate_table_ids and filtered_tables:
                        intent.candidate_table_ids = [filtered_tables[0].get("id", "")]
                elif intent.candidate_doc_ids or filtered_docs:
                    intent.route = "DOCUMENT"
                    if not intent.candidate_doc_ids and filtered_docs:
                        intent.candidate_doc_ids = [filtered_docs[0].get("id", "")]
                else:
                    intent.route = "TABULAR"

                intent.confidence = 0.75
                intent.clarify_question = None
                intent.reason = f"Tiến hành theo giả định hợp lý nhất do đã qua lần làm rõ: sử dụng dữ liệu khả dĩ nhất."
            else:
                intent.route = "CLARIFY"
                # Ensure 2-3 suggestions from catalog are provided in clarify_question
                if not intent.clarify_question or len(intent.clarify_question) < 10:
                    suggestions = []
                    for t in filtered_tables[:2]:
                        t_name = t.get("table_name", t.get("name", "Bảng dữ liệu"))
                        suggestions.append(f"bảng '{t_name}'")
                    for d in filtered_docs[:1]:
                        d_name = d.get("title", "Tài liệu quy chế")
                        suggestions.append(f"tài liệu '{d_name}'")
                    
                    sug_str = ", ".join(suggestions) if suggestions else "dữ liệu chi tiết hơn"
                    intent.clarify_question = (
                        f"Câu hỏi của bạn cần thêm thông tin cụ thể (thời gian, đối tượng hoặc bảng tra cứu). "
                        f"Gợi ý: bạn có muốn tra cứu theo {sug_str} không?"
                    )

        # Policy: Ensure valid candidate table/doc IDs if route is TABULAR or DOCUMENT
        if intent.route == "TABULAR" and not intent.candidate_table_ids and filtered_tables:
            top_selected = self.select_top_tables(rewritten_query, filtered_tables, top_k=2)
            intent.candidate_table_ids = [t["id"] for t in top_selected if t.get("id")]

        if intent.route == "DOCUMENT" and not intent.candidate_doc_ids and filtered_docs:
            intent.candidate_doc_ids = [filtered_docs[0].get("id", "")]

        if intent.route == "HYBRID" and not intent.sub_questions:
            intent.sub_questions = [
                SubQuestion(q=rewritten_query, engine="TABULAR"),
                SubQuestion(q=rewritten_query, engine="DOCUMENT"),
            ]

        return intent

    # -----------------------------------------------------------------------
    # 2.3 Table Selection (Embedding + Keyword overlap)
    # -----------------------------------------------------------------------

    def select_top_tables(
        self,
        query: str,
        candidate_tables: List[Dict[str, Any]],
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Selects top 1-3 candidate tables by combining embedding similarity
        (description + column names) and keyword overlap ratio.

        Score = 0.6 * embedding_similarity + 0.4 * keyword_score
        """
        if not candidate_tables:
            return []
        if len(candidate_tables) <= 1:
            return candidate_tables

        norm_q = normalize_entity_text(query)
        q_tokens = set(norm_q.split())

        query_embed: Optional[List[float]] = None
        if self.embedder:
            try:
                query_embed = self.embedder.embed_query(query)
            except Exception as e:
                logger.warning("Could not embed query for table selection: %s", e)

        # Batch embed tables if needed to avoid N+1 inference calls (cached)
        table_vecs: List[Optional[List[float]]] = [None] * len(candidate_tables)
        if query_embed and self.embedder and candidate_tables:
            reps = []
            for table in candidate_tables:
                t_name = table.get("table_alias") or table.get("table_name") or table.get("name", "")
                desc = table.get("description", "")
                parts = []
                for c in table.get("columns", []):
                    if isinstance(c, dict):
                        parts.append(c.get("column_name", ""))
                    elif isinstance(c, str):
                        parts.append(c)
                reps.append(f"{t_name}: {desc}. Cột: " + ", ".join(parts[:10]))
            try:
                table_vecs = _get_or_compute_embeddings(self.embedder, reps)
            except Exception as e:
                logger.warning("Batch embedding tables in select_top_tables failed: %s", e)

        scored_tables: List[Tuple[Dict[str, Any], float]] = []

        for idx, table in enumerate(candidate_tables):
            # 1. Keyword Score
            table_name = table.get("table_name", table.get("name", ""))
            description = table.get("description", "")
            business_keywords = table.get("business_keywords", [])
            columns = table.get("columns", [])

            pool_parts = [table_name, description]
            if isinstance(business_keywords, list):
                pool_parts.extend(business_keywords)
            for c in columns:
                if isinstance(c, dict):
                    pool_parts.append(c.get("column_name", ""))
                    pool_parts.append(c.get("column_alias", ""))
                elif isinstance(c, str):
                    pool_parts.append(c)

            pool_text = normalize_entity_text(" ".join(pool_parts))
            pool_tokens = set(pool_text.split())

            keyword_score = 0.0
            if q_tokens:
                overlap = q_tokens.intersection(pool_tokens)
                keyword_score = len(overlap) / len(q_tokens)

            # 2. Embedding Score (from precomputed batch)
            embed_score = 0.0
            t_vec = table_vecs[idx] if idx < len(table_vecs) else None
            if query_embed and t_vec:
                try:
                    embed_score = max(0.0, cosine_similarity(query_embed, t_vec))
                except Exception:
                    embed_score = 0.0

            # Combined weighted score
            if query_embed:
                final_score = 0.6 * embed_score + 0.4 * keyword_score
            else:
                final_score = keyword_score

            scored_tables.append((table, final_score))

        scored_tables.sort(key=lambda x: x[1], reverse=True)
        return [item[0] for item in scored_tables[:top_k]]

    # -----------------------------------------------------------------------
    # Helper: Pre-filter top-30 candidates using embedding
    # -----------------------------------------------------------------------

    async def _prefilter_top_30_candidates(
        self,
        query: str,
        candidate_tables: List[Dict[str, Any]],
        candidate_docs: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Pre-filters candidate tables and documents to top 30 using BGE-M3 embeddings."""
        if not self.embedder:
            return candidate_tables[:15], candidate_docs[:15]

        try:
            q_res = self.embedder.embed_query(query)
            q_vec = q_res.get("dense") if isinstance(q_res, dict) else q_res

            reps = []
            types_and_items = []
            for t in candidate_tables:
                rep = f"{t.get('table_name', t.get('name', ''))}: {t.get('description', '')}"
                reps.append(rep)
                types_and_items.append(("table", t))

            for d in candidate_docs:
                rep = f"{d.get('title', '')}: {d.get('summary', '')}"
                reps.append(rep)
                types_and_items.append(("doc", d))

            if not reps:
                return candidate_tables[:15], candidate_docs[:15]

            vecs = _get_or_compute_embeddings(self.embedder, reps)

            scored_items = []
            for (item_type, item), vec in zip(types_and_items, vecs):
                score = cosine_similarity(q_vec, vec) if vec else 0.0
                scored_items.append((item_type, item, score))

            scored_items.sort(key=lambda x: x[2], reverse=True)
            top_30 = scored_items[:30]

            out_tables = [item[1] for item in top_30 if item[0] == "table"]
            out_docs = [item[1] for item in top_30 if item[0] == "doc"]
            return out_tables, out_docs
        except Exception as e:
            logger.warning("Pre-filtering candidates failed: %s", e)
            return candidate_tables[:15], candidate_docs[:15]

    # -----------------------------------------------------------------------
    # Helper: Deterministic Heuristic Routing Fallback
    # -----------------------------------------------------------------------

    def _heuristic_route(
        self,
        query: str,
        candidate_tables: List[Dict[str, Any]],
        candidate_docs: List[Dict[str, Any]],
    ) -> QueryIntent:
        """Deterministic heuristic router used when LLM client is unavailable or errors."""
        norm_q = normalize_entity_text(query)

        # 1. Chitchat
        chitchat_patterns = ["xin chao", "chao ban", "hello", "hi", "cam on", "thanks", "ban la ai"]
        for p in chitchat_patterns:
            if p in norm_q and len(norm_q.split()) <= 4:
                return QueryIntent(
                    route="CHITCHAT",
                    confidence=0.95,
                    candidate_table_ids=[],
                    candidate_doc_ids=[],
                    sub_questions=[],
                    clarify_question=None,
                    reason="Câu chào hỏi giao tiếp thông thường.",
                )

        # 2. Out of scope
        oos_patterns = ["thoi tiet", "nau an", "cong thuc nau", "bong da", "tin tuc the gioi", "chinh tri"]
        for p in oos_patterns:
            if p in norm_q:
                return QueryIntent(
                    route="OUT_OF_SCOPE",
                    confidence=0.95,
                    candidate_table_ids=[],
                    candidate_doc_ids=[],
                    sub_questions=[],
                    clarify_question=None,
                    reason="Câu hỏi ngoài phạm vi nghiệp vụ và tài liệu doanh nghiệp.",
                )

        # Keywords inspection
        tabular_keywords = ["doanh thu", "chi phi", "tinh", "tong", "trung binh", "cao nhat", "thap nhat", "luong", "so luong", "bang"]
        doc_keywords = ["quy che", "quy dinh", "chinh sach", "quy trinh", "dieu khoan", "huong dan", "tai lieu"]

        has_tabular = any(kw in norm_q for kw in tabular_keywords)
        has_doc = any(kw in norm_q for kw in doc_keywords)

        table_ids = [t.get("id") for t in candidate_tables[:3] if t.get("id")]
        doc_ids = [d.get("id") for d in candidate_docs[:3] if d.get("id")]

        if has_tabular and has_doc:
            return QueryIntent(
                route="HYBRID",
                confidence=0.85,
                candidate_table_ids=table_ids,
                candidate_doc_ids=doc_ids,
                sub_questions=[
                    SubQuestion(q=query, engine="TABULAR"),
                    SubQuestion(q=query, engine="DOCUMENT"),
                ],
                clarify_question=None,
                reason="Câu hỏi yêu cầu kết hợp cả số liệu bảng biểu và tài liệu quy chế.",
            )

        if has_tabular and candidate_tables:
            return QueryIntent(
                route="TABULAR",
                confidence=0.85,
                candidate_table_ids=table_ids[:1],
                candidate_doc_ids=[],
                sub_questions=[],
                clarify_question=None,
                reason="Câu hỏi yêu cầu tính toán và trích xuất dữ liệu từ bảng biểu.",
            )

        if has_doc and candidate_docs:
            return QueryIntent(
                route="DOCUMENT",
                confidence=0.85,
                candidate_table_ids=[],
                candidate_doc_ids=doc_ids[:1],
                sub_questions=[],
                clarify_question=None,
                reason="Câu hỏi tra cứu tài liệu quy chế chính sách.",
            )

        # If ambiguous query
        return QueryIntent(
            route="CLARIFY",
            confidence=0.40,
            candidate_table_ids=table_ids,
            candidate_doc_ids=doc_ids,
            sub_questions=[],
            clarify_question="Bạn có thể nêu rõ hơn mốc thời gian hoặc bảng dữ liệu/quy chế cần tra cứu không?",
            reason="Ý định câu hỏi chưa đủ rõ ràng hoặc thiếu thông tin định danh.",
        )
