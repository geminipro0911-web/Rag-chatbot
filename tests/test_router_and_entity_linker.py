"""
Unit tests for Module 2: Router & Entity Linker.
Covers:
- Query rewriting with 6-turn dialogue context.
- Intent routing with confidence policies (>= 0.75, [0.5, 0.75) -> HYBRID, < 0.5 -> CLARIFY).
- Max 1 consecutive clarification constraint.
- Table selection combining embedding similarity and keyword overlap.
- Entity linking multi-tier pipeline:
  * Tier 2 Normalization
  * Tier 3 Alias dictionary exact match (HN -> Hà Nội, HCM -> Hồ Chí Minh, Q1 -> Quý 1)
  * Tier 4 RapidFuzz fuzzy matching (score >= 90)
  * Tier 5 LLM candidate disambiguation strictly from candidate list
  * Unlinked entity handling (score < 70)
"""

import pytest
from typing import Any, Dict, List, Optional
from pydantic import BaseModel

from application.interfaces.llm_client import LLMClient
from application.interfaces.embedder import Embedder
from application.services.entity_linker import (
    EntityLinker,
    DistinctValueEntry,
    normalize_entity_text,
    DEFAULT_ENTITY_ALIASES,
)
from application.services.router import Router, cosine_similarity
from domain.entities.query_intent import QueryIntent, SubQuestion
from domain.entities.entity_link import EntityMention, EntityLinkResult


# ---------------------------------------------------------------------------
# Test Mocks
# ---------------------------------------------------------------------------

class MockLLMClient(LLMClient):
    """Mock LLM client with configurable responses for testing."""

    def __init__(self, rewrite_response: str = "", structured_response: Any = None):
        self.rewrite_response = rewrite_response
        self.structured_response = structured_response

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        stop: Optional[List[str]] = None,
    ) -> str:
        if self.rewrite_response:
            return self.rewrite_response
        return "Doanh thu quý 2 của chi nhánh Hà Nội là bao nhiêu?"

    async def structured_output(
        self,
        prompt: str,
        response_model: type[BaseModel],
        system_prompt: Optional[str] = None,
        temperature: float = 0.0,
    ) -> BaseModel:
        if self.structured_response is not None:
            if isinstance(self.structured_response, response_model):
                return self.structured_response
            if isinstance(self.structured_response, dict):
                return response_model(**self.structured_response)

        # Default fallback instantiations
        if response_model.__name__ == "QueryIntent":
            return QueryIntent(
                route="TABULAR",
                confidence=0.88,
                candidate_table_ids=["tbl_sales_2023"],
                candidate_doc_ids=[],
                sub_questions=[],
                clarify_question=None,
                reason="Câu hỏi yêu cầu dữ liệu bảng biểu doanh thu.",
            )
        elif response_model.__name__ == "EntityExtractionOutput":
            from application.services.entity_linker import EntityExtractionOutput, EntityMentionItem
            return EntityExtractionOutput(
                mentions=[
                    EntityMentionItem(mention="HN", column="chi_nhanh"),
                    EntityMentionItem(mention="quý 2", column="quy"),
                ]
            )
        elif response_model.__name__ == "EntityDisambiguationOutput":
            from application.services.entity_linker import EntityDisambiguationOutput
            return EntityDisambiguationOutput(selected_value="Hợp đồng Lao động KTH-01")

        return response_model()


class MockEmbedder(Embedder):
    """Deterministic mock embedder generating orthogonal/correlated vectors."""

    def embed_query(self, text: str) -> List[float]:
        norm = normalize_entity_text(text)
        vec = [0.0] * 8
        if "doanh thu" in norm or "sales" in norm:
            vec[0] = 1.0
        if "ha noi" in norm or "hn" in norm:
            vec[1] = 1.0
        if "quy che" in norm or "chinh sach" in norm:
            vec[2] = 1.0
        if "nhan su" in norm:
            vec[3] = 1.0
        # Normalize vector
        s = sum(x * x for x in vec)
        if s > 0:
            norm_factor = s ** 0.5
            return [x / norm_factor for x in vec]
        return [0.125] * 8

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self.embed_query(t) for t in texts]


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_normalization_tier2():
    """Verify tier 2 normalization: lowercase, unidecode, strip punctuation, collapse whitespace."""
    raw = "  Đà Nẵng - Chi Nhánh (Số 1)!  "
    norm = normalize_entity_text(raw)
    assert norm == "da nang chi nhanh so 1"

    assert normalize_entity_text("TP. HỒ CHÍ MINH") == "tp ho chi minh"
    assert normalize_entity_text("") == ""
    assert normalize_entity_text(None) == ""


@pytest.mark.asyncio
async def test_query_rewriting_with_history():
    """Verify query rewriting resolves pronouns and ellipses using 6-turn history."""
    llm = MockLLMClient(rewrite_response="Doanh thu quý 2 của chi nhánh Hà Nội là bao nhiêu?")
    router = Router(llm_client=llm)

    history = [
        {"role": "user", "content": "Doanh thu quý 1 của chi nhánh Hà Nội là bao nhiêu?"},
        {"role": "assistant", "content": "Doanh thu Q1 chi nhánh Hà Nội là 15 tỷ VNĐ."},
    ]
    current_q = "Còn quý 2 thì sao?"

    rewritten = await router.rewrite_query(current_q, history)
    assert rewritten == "Doanh thu quý 2 của chi nhánh Hà Nội là bao nhiêu?"

    # Empty history returns original query unchanged
    standalone = await router.rewrite_query("Chính sách nghỉ phép của công ty", [])
    assert standalone == "Chính sách nghỉ phép của công ty"


@pytest.mark.asyncio
async def test_entity_linking_alias_and_fuzzy():
    """Verify Tier 3 (alias dictionary) and Tier 4 (RapidFuzz >= 90) matching."""
    linker = EntityLinker(llm_client=None)

    table_values = [
        DistinctValueEntry(table_id="tbl_1", column_name="chi_nhanh", original_value="Hà Nội"),
        DistinctValueEntry(table_id="tbl_1", column_name="chi_nhanh", original_value="Hồ Chí Minh"),
        DistinctValueEntry(table_id="tbl_1", column_name="chi_nhanh", original_value="Đà Nẵng"),
        DistinctValueEntry(table_id="tbl_1", column_name="quy", original_value="Quý 1"),
        DistinctValueEntry(table_id="tbl_1", column_name="phong_ban", original_value="Phòng Kinh Doanh Toàn Quốc"),
    ]

    # Pre-extracted mentions for deterministic test
    mentions = [
        EntityMention(mention="HN", column="chi_nhanh"),
        EntityMention(mention="Q1", column="quy"),
        EntityMention(mention="Phong Kinh Doanh Toan Quoc", column="phong_ban"),
        EntityMention(mention="Chi Nhanh Khong Co That XYZ", column="chi_nhanh"),
    ]

    results = await linker.link_entities(
        query="Doanh thu HN Q1 của Phong Kinh Doanh Toan Quoc",
        table_values=table_values,
        extracted_mentions=mentions,
    )

    assert len(results) == 4

    # 1. HN -> Hà Nội via alias (score 1.0)
    hn_res = results[0]
    assert hn_res.mention == "HN"
    assert hn_res.value == "Hà Nội"
    assert hn_res.method == "alias"
    assert hn_res.score == 1.0
    assert hn_res.column == "chi_nhanh"

    # 2. Q1 -> Quý 1 via alias (score 1.0)
    q1_res = results[1]
    assert q1_res.mention == "Q1"
    assert q1_res.value == "Quý 1"
    assert q1_res.method == "alias"
    assert q1_res.score == 1.0

    # 3. Phong Kinh Doanh Toan Quoc -> Phòng Kinh Doanh Toàn Quốc via fuzzy (>= 90)
    pkd_res = results[2]
    assert pkd_res.value == "Phòng Kinh Doanh Toàn Quốc"
    assert pkd_res.method == "fuzzy"
    assert pkd_res.score >= 0.90

    # 4. Unknown entity -> unlinked
    unlinked_res = results[3]
    assert unlinked_res.method == "unlinked"
    assert unlinked_res.score == 0.0


@pytest.mark.asyncio
async def test_entity_linking_llm_disambiguation():
    """Verify Tier 5 ambiguous candidate disambiguation strictly from candidate list."""
    llm = MockLLMClient()
    linker = EntityLinker(llm_client=llm)

    # Values in 70-89 fuzzy range with mention "Hợp đồng KTH"
    table_values = [
        DistinctValueEntry(table_id="tbl_docs", column_name="so_hd", original_value="Hợp đồng Lao động KTH-01"),
        DistinctValueEntry(table_id="tbl_docs", column_name="so_hd", original_value="Hợp đồng Dịch vụ KTH-02"),
    ]

    mentions = [EntityMention(mention="Hợp đồng KTH", column="so_hd")]

    results = await linker.link_entities(
        query="Tìm hợp đồng KTH",
        table_values=table_values,
        extracted_mentions=mentions,
    )

    assert len(results) == 1
    res = results[0]
    assert res.value == "Hợp đồng Lao động KTH-01"
    assert res.method == "llm"
    assert 0.70 <= res.score <= 1.0


@pytest.mark.asyncio
async def test_intent_routing_policies():
    """Verify routing policy enforcement: confidence thresholds and consecutive clarifications."""
    # 1. Normal TABULAR route (confidence >= 0.75)
    llm_tab = MockLLMClient(
        structured_response=QueryIntent(
            route="TABULAR",
            confidence=0.85,
            candidate_table_ids=["tbl_1"],
            candidate_doc_ids=[],
            sub_questions=[],
            clarify_question=None,
            reason="Tra cứu số liệu bảng biểu.",
        )
    )
    router_tab = Router(llm_client=llm_tab)
    intent_tab = await router_tab.route_query("Tổng doanh thu 2023", [{"id": "tbl_1", "name": "Doanh thu"}], [])
    assert intent_tab.route == "TABULAR"
    assert intent_tab.confidence >= 0.75

    # 2. Medium confidence (0.5 <= conf < 0.75) between TABULAR/DOCUMENT -> Forces HYBRID
    llm_med = MockLLMClient(
        structured_response=QueryIntent(
            route="TABULAR",
            confidence=0.65,
            candidate_table_ids=["tbl_1"],
            candidate_doc_ids=["doc_1"],
            sub_questions=[],
            clarify_question=None,
            reason="Phân vân giữa tra cứu doanh thu và quy chế.",
        )
    )
    router_med = Router(llm_client=llm_med)
    intent_med = await router_med.route_query(
        "Doanh thu kèm quy chế",
        [{"id": "tbl_1", "name": "Doanh thu"}],
        [{"id": "doc_1", "title": "Quy chế"}],
    )
    assert intent_med.route == "HYBRID"
    assert len(intent_med.sub_questions) >= 2

    # 3. Low confidence (conf < 0.5) with consecutive_clarifications = 0 -> CLARIFY with suggestions
    llm_low = MockLLMClient(
        structured_response=QueryIntent(
            route="CLARIFY",
            confidence=0.35,
            candidate_table_ids=["tbl_1"],
            candidate_doc_ids=[],
            sub_questions=[],
            clarify_question=None,
            reason="Thiếu thông tin thời gian.",
        )
    )
    router_low = Router(llm_client=llm_low)
    intent_low = await router_low.route_query(
        "Xem báo cáo",
        [{"id": "tbl_1", "name": "Báo cáo Q1"}],
        [],
        consecutive_clarifications=0,
    )
    assert intent_low.route == "CLARIFY"
    assert "Báo cáo Q1" in intent_low.clarify_question or "gợi ý" in intent_low.clarify_question.lower()

    # 4. Low confidence with consecutive_clarifications >= 1 -> Must proceed with best hypothesis
    intent_hypo = await router_low.route_query(
        "Xem báo cáo",
        [{"id": "tbl_1", "name": "Báo cáo Q1"}],
        [],
        consecutive_clarifications=1,
    )
    assert intent_hypo.route in ("TABULAR", "DOCUMENT")
    assert intent_hypo.confidence == 0.75
    assert "giả định hợp lý nhất" in intent_hypo.reason.lower()


def test_table_selection_hybrid_scoring():
    """Verify table selection combining embedding similarity and keyword overlap."""
    embedder = MockEmbedder()
    router = Router(embedder=embedder)

    candidate_tables = [
        {
            "id": "tbl_sales",
            "table_name": "Báo cáo doanh thu bán hàng",
            "description": "Chi tiết doanh thu theo chi nhánh và quý",
            "business_keywords": ["doanh thu", "sales", "chi nhánh"],
            "columns": ["chi_nhanh", "doanh_thu", "quy"],
        },
        {
            "id": "tbl_hr",
            "table_name": "Danh sách nhân sự",
            "description": "Thông tin nhân viên phòng ban chức vụ",
            "business_keywords": ["nhân sự", "nhân viên"],
            "columns": ["ma_nv", "ho_ten", "phong_ban"],
        },
    ]

    selected = router.select_top_tables(
        query="Doanh thu bán hàng của các chi nhánh",
        candidate_tables=candidate_tables,
        top_k=1,
    )
    assert len(selected) == 1
    assert selected[0]["id"] == "tbl_sales"
