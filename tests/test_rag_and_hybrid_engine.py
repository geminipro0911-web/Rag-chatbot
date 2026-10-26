"""
Unit and Integration Tests for Phase 7:
- Output Formatter & Citation Enforcer (VN number/date formatting, >50 rows truncation & summary, citation audit).
- BGE Reranker (ranking and deterministic fallback).
- Document RAG Engine (RBAC filtering, hybrid search, rerank threshold rejection, citation self-correction).
- Hybrid Engine (sub-question dispatch, parallel execution, cross-engine fallback, synthesis).
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd
import pytest
from pydantic import BaseModel

from application.interfaces.code_executor import CodeExecutor
from application.interfaces.embedder import Embedder
from application.interfaces.llm_client import LLMClient
from application.interfaces.reranker import Reranker
from application.interfaces.vector_store import VectorStore
from application.services.hybrid_engine import HybridBranchResult, HybridEngine
from application.services.output_formatter import (
    ChatResponse,
    OutputFormatter,
    SourceCitation,
    TableResultDTO,
    format_dataframe_for_display,
    format_vn_date,
    format_vn_number,
)
from application.services.rag_engine import RAGEngine, RAGExecutionResult
from application.services.tabular_executor import (
    GeneratedCodeOutput,
    TabularExecutionResult,
    TabularExecutor,
)
from domain.entities.query_intent import SubQuestion
from infrastructure.models.bge_reranker import BGEReranker


# ---------------------------------------------------------------------------
# Mock Implementations for Deterministic Testing
# ---------------------------------------------------------------------------

class MockEmbedder(Embedder):
    """Deterministic mock embedder."""
    def embed_query(self, query: str) -> Dict[str, Any]:
        return {
            "dense": [0.1] * 1024,
            "sparse_indices": [10, 20, 30],
            "sparse_values": [1.0, 0.8, 0.5],
        }

    def embed_documents(self, documents: List[str]) -> List[Dict[str, Any]]:
        return [self.embed_query(doc) for doc in documents]


class MockVectorStore(VectorStore):
    """Mock vector store recording search parameters and returning test chunks."""
    def __init__(self, canned_results: Optional[List[Dict[str, Any]]] = None):
        self.canned_results = canned_results or []
        self.last_query_dense = None
        self.last_department_id = None
        self.last_user_id = None
        self.last_is_admin = None

    def init_collection(self) -> None:
        pass

    def health_check(self) -> bool:
        return True

    def upsert_chunks(self, chunks: List[Dict[str, Any]]) -> bool:
        return True

    def hybrid_search(
        self,
        query_dense: List[float],
        query_sparse_indices: List[int],
        query_sparse_values: List[float],
        department_id: str,
        user_id: str,
        is_admin: bool = False,
        limit: int = 20,
        is_public_only: bool = False,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        self.last_query_dense = query_dense
        self.last_department_id = department_id
        self.last_user_id = user_id
        self.last_is_admin = is_admin
        self.last_is_public_only = is_public_only
        return self.canned_results

    def delete_by_file_id(self, file_id: str) -> bool:
        return True

    def count(self) -> int:
        return len(self.canned_results)


class MockLLMClient(LLMClient):
    """Mock LLM Client returning predetermined or dynamic responses."""
    def __init__(self, canned_responses: Optional[List[str]] = None):
        self.canned_responses = list(canned_responses) if canned_responses else []
        self.call_history: List[List[Dict[str, str]]] = []

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> str:
        self.call_history.append(messages)
        if self.canned_responses:
            return self.canned_responses.pop(0)
        return "Mô hình trả lời dựa trên tài liệu tham khảo [1]."

    def structured_output(
        self,
        messages: List[Dict[str, str]],
        response_model: type[BaseModel],
        temperature: float = 0.0,
        timeout: Optional[float] = None,
    ) -> BaseModel:
        # For tabular mock
        if response_model == GeneratedCodeOutput:
            return GeneratedCodeOutput(
                language="sql",
                code='SELECT * FROM "sales"',
                explanation="Truy vấn dữ liệu bảng bán hàng.",
            )
        return response_model()


class MockCodeExecutor(CodeExecutor):
    """Mock code executor returning DataFrame rows."""
    def __init__(self, df: Optional[pd.DataFrame] = None):
        self.df = df if df is not None else pd.DataFrame({"id": [1], "doanh_thu": [1000000]})

    def execute_sql(
        self,
        query: str,
        table_parquet_mapping: Dict[str, str],
        max_rows: int = 10000,
    ) -> Tuple[bool, Optional[pd.DataFrame], Optional[str]]:
        return True, self.df, None

    def execute_pandas(
        self,
        code: str,
        dataframes: Dict[str, pd.DataFrame],
        timeout_seconds: int = 15,
        max_ram_mb: int = 512,
    ) -> Tuple[bool, Optional[pd.DataFrame], Optional[str]]:
        return True, self.df, None


# ---------------------------------------------------------------------------
# Test Cases: Output Formatter & Citation Enforcer
# ---------------------------------------------------------------------------

def test_format_vn_number():
    """Verify Vietnamese number formatting (dot for thousands, comma for decimals)."""
    assert format_vn_number(1234567) == "1.234.567"
    assert format_vn_number(1234567.89) == "1.234.567,89"
    assert format_vn_number(500.0) == "500"
    assert format_vn_number(0) == "0"
    assert format_vn_number(None) == ""


def test_format_vn_date():
    """Verify Vietnamese date formatting into dd/mm/yyyy."""
    dt = datetime.datetime(2025, 3, 15, 10, 30)
    d = datetime.date(2025, 12, 31)
    ts = pd.Timestamp("2025-01-05")

    assert format_vn_date(dt) == "15/03/2025"
    assert format_vn_date(d) == "31/12/2025"
    assert format_vn_date(ts) == "05/01/2025"
    assert format_vn_date(None) == ""


def test_format_dataframe_under_50_rows():
    """Verify dataframe formatting under 50 rows renders full table with VN formats."""
    df = pd.DataFrame({
        "ngay": [datetime.date(2025, 1, 1), datetime.date(2025, 1, 2)],
        "doanh_thu": [1500000, 2750000],
    })
    table_md, summary_md = format_dataframe_for_display(df, max_rows=50)

    assert "1.500.000" in table_md
    assert "2.750.000" in table_md
    assert "01/01/2025" in table_md
    assert summary_md is None  # Under 50 rows, no summary table


def test_format_dataframe_over_50_rows_truncation_and_summary():
    """Verify dataframe > 50 rows displays first 20 rows and generates summary statistics."""
    rows = []
    for i in range(60):
        rows.append({
            "id": i + 1,
            "gia_tri": (i + 1) * 10000,
        })
    df = pd.DataFrame(rows)

    table_md, summary_md = format_dataframe_for_display(df, max_rows=50, head_rows=20)

    # Must contain pagination note
    assert "Đang hiển thị 20 / 60 dòng dữ liệu" in table_md
    # Summary statistics table must exist
    assert summary_md is not None
    assert "Thống kê tóm tắt các cột số" in summary_md
    assert "Số dòng (Count)" in summary_md
    assert "Tổng (Sum)" in summary_md
    assert "Trung bình (Mean)" in summary_md


def test_render_tabular_section():
    """Verify complete tabular section rendering with explanation and source line."""
    df = pd.DataFrame({"thang": ["T1", "T2"], "doanh_thu": [1000000, 2000000]})
    output = OutputFormatter.render_tabular_section(
        explanation="Doanh thu tăng trưởng mạnh mẽ trong tháng 2.",
        df=df,
        file_name="Bao_cao_kinh_doanh.xlsx",
        sheet_name="Q1_2025",
    )

    assert "Doanh thu tăng trưởng mạnh mẽ" in output
    assert "1.000.000" in output
    assert "📊 Nguồn dữ liệu: File [Bao_cao_kinh_doanh.xlsx] - Sheet [Q1_2025]" in output


def test_citation_audit_success():
    """Verify citation audit passes when quote matches chunk and index is valid."""
    text = (
        "Quy chế công ty quy định nhân viên được nghỉ phép 12 ngày một năm [1].\n\n"
        "### 📚 Chỉ mục nguồn trích dẫn (References)\n"
        '[1] Quy_che_noi_bo.pdf | Trang: 5 | Mục: Nghỉ phép — "nhân viên được nghỉ phép 12 ngày một năm"'
    )
    source_chunks = [
        {
            "payload": {
                "text": "Theo điều 15, nhân viên được nghỉ phép 12 ngày một năm có hưởng lương.",
                "file_name": "Quy_che_noi_bo.pdf",
            }
        }
    ]

    is_valid, reason, invalid = OutputFormatter.audit_citations(text, source_chunks)
    assert is_valid is True
    assert reason == ""
    assert len(invalid) == 0


def test_citation_audit_invalid_index():
    """Verify citation audit fails when citation index [2] exceeds 1 source."""
    text = (
        "Theo tài liệu quy định [2].\n\n"
        "### 📚 Chỉ mục nguồn trích dẫn (References)\n"
        '[2] File.pdf | Trang: 1 | Mục: Mục 1 — "Trích đoạn..."'
    )
    source_chunks = [{"payload": {"text": "Nội dung văn bản 1"}}]

    is_valid, reason, invalid = OutputFormatter.audit_citations(text, source_chunks)
    assert is_valid is False
    assert 2 in invalid
    assert "vượt quá số lượng tài liệu nguồn" in reason


def test_citation_audit_hallucinated_quote():
    """Verify citation audit fails when quote does not match source content."""
    text = (
        "Chính sách bảo hiểm chi trả 100% [1].\n\n"
        "### 📚 Chỉ mục nguồn trích dẫn (References)\n"
        '[1] File.pdf | Trang: 1 | Mục: Mục 1 — "công ty cam kết thưởng 5 tháng lương vào tết âm lịch"'
    )
    source_chunks = [{"payload": {"text": "Công ty hỗ trợ bảo hiểm y tế cơ bản cho nhân viên."}}]

    is_valid, reason, invalid = OutputFormatter.audit_citations(text, source_chunks)
    assert is_valid is False
    assert "không khớp với nội dung gốc" in reason


def test_sanitize_citations():
    """Verify sanitize citations replaces out-of-bound indices."""
    raw = "Luận điểm 1 [1], luận điểm 2 [2], luận điểm 3 [99]."
    sanitized = OutputFormatter.sanitize_citations(raw, max_valid_index=2)
    assert "[1]" in sanitized
    assert "[2]" in sanitized
    assert "⚠️[Trích dẫn chưa xác minh]" in sanitized
    assert "[99]" not in sanitized


# ---------------------------------------------------------------------------
# Test Cases: BGE Reranker
# ---------------------------------------------------------------------------

def test_bge_reranker_fallback():
    """Verify BGEReranker deterministic fallback scores relevant doc highest."""
    reranker = BGEReranker(model_name_or_path="non_existent_model_for_test")
    query = "chính sách nghỉ phép năm của nhân viên"
    docs = [
        "Quy định về bảo mật thông tin và mật khẩu máy tính của nhân viên.",
        "Chính sách nghỉ phép năm: Mỗi nhân viên có 12 ngày phép hàng năm.",
        "Quy trình thanh toán công tác phí và hóa đơn tiếp khách.",
    ]
    ranked = reranker.rerank(query, docs, top_k=2)

    assert len(ranked) == 2
    # Document 1 (index 1) is about "nghỉ phép năm" -> must rank #1
    assert ranked[0][0] == 1
    assert ranked[0][1] > ranked[1][1]


# ---------------------------------------------------------------------------
# Test Cases: RAG Engine
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rag_engine_success():
    """Verify end-to-end RAG answer flow with valid retrieval and references."""
    candidate_chunk = {
        "chunk_id": "c1",
        "score": 0.85,
        "payload": {
            "text": "Nhân viên làm việc đủ 12 tháng được nghỉ phép năm 12 ngày theo quy định.",
            "file_name": "Noi_quy_lao_dong.pdf",
            "page": 4,
            "section_title": "Chế độ nghỉ phép",
        },
    }
    vector_store = MockVectorStore(canned_results=[candidate_chunk])
    embedder = MockEmbedder()
    reranker = BGEReranker()
    llm = MockLLMClient(canned_responses=[
        (
            "Theo nội quy công ty, nhân viên làm việc đủ 12 tháng được nghỉ 12 ngày phép [1].\n\n"
            "### 📚 Chỉ mục nguồn trích dẫn (References)\n"
            '[1] Noi_quy_lao_dong.pdf | Trang: 4 | Mục: Chế độ nghỉ phép — "nhân viên làm việc đủ 12 tháng được nghỉ phép năm 12 ngày"'
        )
    ])

    rag = RAGEngine(
        vector_store=vector_store,
        embedder=embedder,
        reranker=reranker,
        llm_client=llm,
        reranker_threshold=0.3,
    )

    res = await rag.answer_query(
        query="Chế độ nghỉ phép năm của nhân viên như thế nào?",
        department_id="HR",
        user_id="U100",
        is_admin=False,
    )

    assert res.status == "success"
    assert res.audit_passed is True
    assert len(res.sources) == 1
    assert res.sources[0].file_name == "Noi_quy_lao_dong.pdf"
    assert res.sources[0].page == 4
    assert "12 ngày phép" in res.answer_markdown
    # Verify RBAC parameters passed to vector store
    assert vector_store.last_department_id == "HR"
    assert vector_store.last_user_id == "U100"


@pytest.mark.asyncio
async def test_rag_engine_threshold_rejection():
    """Verify RAG Engine rejects answers when top rerank score < threshold."""
    candidate_chunk = {
        "chunk_id": "c1",
        "score": 0.1,
        "payload": {
            "text": "Báo cáo tiến độ xây dựng hạ tầng trung tâm dữ liệu.",
            "file_name": "Bao_cao_ha_tang.pdf",
            "page": 1,
            "section_title": "Hạ tầng",
        },
    }
    vector_store = MockVectorStore(canned_results=[candidate_chunk])
    embedder = MockEmbedder()
    reranker = BGEReranker()
    llm = MockLLMClient()

    rag = RAGEngine(
        vector_store=vector_store,
        embedder=embedder,
        reranker=reranker,
        llm_client=llm,
        reranker_threshold=0.8,  # High threshold
    )

    res = await rag.answer_query(
        query="Hỏi về bảng lương tháng 12",
        department_id="FIN",
        user_id="U200",
    )

    assert res.status == "threshold_rejected"
    assert "Không tìm thấy thông tin trong các tài liệu bạn được phép truy cập." in res.answer_markdown
    assert len(llm.call_history) == 0  # LLM should not even be called


@pytest.mark.asyncio
async def test_rag_engine_citation_self_correction_retry():
    """Verify RAG Engine triggers retry when citation audit initially fails."""
    candidate_chunk = {
        "chunk_id": "c1",
        "score": 0.85,
        "payload": {
            "text": "Quy chế bảo mật: Tuyệt đối không chia sẻ mật khẩu máy tính với bất kỳ ai.",
            "file_name": "Bao_mat.pdf",
            "page": 2,
            "section_title": "Mật khẩu",
        },
    }
    vector_store = MockVectorStore(canned_results=[candidate_chunk])
    embedder = MockEmbedder()
    reranker = BGEReranker()

    # Response 1 has invalid index [5] -> fails audit
    # Response 2 corrects to index [1] -> passes audit
    llm = MockLLMClient(canned_responses=[
        "Tuyệt đối không chia sẻ mật khẩu [5].",
        (
            "Tuyệt đối không chia sẻ mật khẩu máy tính [1].\n\n"
            "### 📚 Chỉ mục nguồn trích dẫn (References)\n"
            '[1] Bao_mat.pdf | Trang: 2 | Mục: Mật khẩu — "Tuyệt đối không chia sẻ mật khẩu máy tính với bất kỳ ai"'
        ),
    ])

    rag = RAGEngine(
        vector_store=vector_store,
        embedder=embedder,
        reranker=reranker,
        llm_client=llm,
        reranker_threshold=0.3,
    )

    res = await rag.answer_query(
        query="Quy định về mật khẩu",
        department_id="IT",
        user_id="U300",
    )

    assert res.status == "success"
    assert res.retries_used == 1
    assert res.audit_passed is True
    assert len(llm.call_history) == 2  # Proves self-correction loop triggered


# ---------------------------------------------------------------------------
# Test Cases: Hybrid Engine
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hybrid_engine_parallel_execution():
    """Verify Hybrid Engine dispatches sub-questions to Tabular and RAG in parallel."""
    # Setup Tabular
    tabular_df = pd.DataFrame({"phong_ban": ["Kinh doanh", "Kỹ thuật"], "tong_chi": [50000000, 30000000]})
    code_executor = MockCodeExecutor(df=tabular_df)
    tabular_llm = MockLLMClient()
    tabular_executor = TabularExecutor(llm_client=tabular_llm, code_executor=code_executor)

    # Setup RAG
    chunk = {
        "chunk_id": "c1",
        "score": 0.9,
        "payload": {
            "text": "Chính sách ngân sách: Mức chi phí tối đa cho phòng Kinh doanh là 60 triệu.",
            "file_name": "Chinh_sach_ngan_sach.pdf",
            "page": 3,
            "section_title": "Hạn mức",
        },
    }
    vector_store = MockVectorStore(canned_results=[chunk])
    rag_engine = RAGEngine(
        vector_store=vector_store,
        embedder=MockEmbedder(),
        reranker=BGEReranker(),
        llm_client=MockLLMClient(canned_responses=[
            (
                "Mức chi phí tối đa của phòng Kinh doanh là 60 triệu [1].\n\n"
                "### 📚 Chỉ mục nguồn trích dẫn (References)\n"
                '[1] Chinh_sach_ngan_sach.pdf | Trang: 3 | Mục: Hạn mức — "Mức chi phí tối đa cho phòng Kinh doanh là 60 triệu"'
            )
        ]),
        reranker_threshold=0.3,
    )

    # Setup Hybrid Synthesis LLM
    synthesis_llm = MockLLMClient(canned_responses=[
        (
            "Tổng chi phí phòng Kinh doanh là 50.000.000 VNĐ, vẫn nằm trong hạn mức 60.000.000 VNĐ theo quy định [1].\n\n"
            "| phong_ban | tong_chi |\n| :--- | :--- |\n| Kinh doanh | 50.000.000 |\n| Kỹ thuật | 30.000.000 |\n\n"
            "📊 Nguồn dữ liệu: File [Ngan_sach.xlsx] - Sheet [Chi_phi]\n\n"
            "### 📚 Chỉ mục nguồn trích dẫn (References)\n"
            '[1] Chinh_sach_ngan_sach.pdf | Trang: 3 | Mục: Hạn mức — "Mức chi phí tối đa cho phòng Kinh doanh là 60 triệu"'
        )
    ])

    hybrid = HybridEngine(
        tabular_executor=tabular_executor,
        rag_engine=rag_engine,
        llm_client=synthesis_llm,
    )

    sub_questions = [
        SubQuestion(q="Tổng chi phí của các phòng ban là bao nhiêu?", engine="TABULAR"),
        SubQuestion(q="Hạn mức chi phí của phòng Kinh doanh theo quy định?", engine="DOCUMENT"),
    ]

    candidate_tables = [{
        "table_alias": "ngan_sach_tbl",
        "file_name": "Ngan_sach.xlsx",
        "sheet_name": "Chi_phi",
        "parquet_path": "data/parquet/ngan_sach.parquet",
        "columns": [
            {"column_alias": "phong_ban", "data_type": "string", "sample_values": ["Kinh doanh"]},
            {"column_alias": "tong_chi", "data_type": "numeric", "sample_values": [50000000]},
        ],
    }]

    response: ChatResponse = await hybrid.execute_hybrid(
        query="Chi phí các phòng ban và hạn mức quy định của phòng Kinh doanh?",
        department_id="FIN",
        user_id="U500",
        sub_questions=sub_questions,
        candidate_tables=candidate_tables,
    )

    assert response.route == "HYBRID"
    assert "50.000.000" in response.answer_markdown
    assert "Chinh_sach_ngan_sach.pdf" in response.answer_markdown
    assert len(response.tables) == 1
    assert response.tables[0].table_name == "ngan_sach_tbl"
    assert len(response.sources) >= 1


@pytest.mark.asyncio
async def test_hybrid_engine_cross_engine_fallback():
    """Verify single cross-engine fallback when Tabular branch returns no candidate tables."""
    # Setup Tabular with empty candidate tables -> tabular branch will return empty
    tabular_executor = TabularExecutor(llm_client=MockLLMClient(), code_executor=MockCodeExecutor())

    chunk = {
        "chunk_id": "c1",
        "score": 0.88,
        "payload": {
            "text": "Báo cáo quý 3: Doanh thu chi nhánh Đà Nẵng ghi nhận đạt 15 tỷ đồng.",
            "file_name": "Bao_cao_Q3.pdf",
            "page": 1,
            "section_title": "Doanh thu",
        },
    }
    vector_store = MockVectorStore(canned_results=[chunk])
    rag_engine = RAGEngine(
        vector_store=vector_store,
        embedder=MockEmbedder(),
        reranker=BGEReranker(),
        llm_client=MockLLMClient(canned_responses=[
            "Theo báo cáo quý 3, doanh thu Đà Nẵng đạt 15 tỷ đồng [1].",
            "Theo báo cáo quý 3, doanh thu đạt 15 tỷ đồng [1].",
        ]),
        reranker_threshold=0.3,
    )

    synthesis_llm = MockLLMClient(canned_responses=[
        "Doanh thu chi nhánh Đà Nẵng được ghi nhận trong văn bản báo cáo là 15 tỷ đồng [1]."
    ])

    hybrid = HybridEngine(
        tabular_executor=tabular_executor,
        rag_engine=rag_engine,
        llm_client=synthesis_llm,
    )

    sub_questions = [
        SubQuestion(q="Doanh thu chi nhánh Đà Nẵng trong bảng số liệu?", engine="TABULAR"),
        SubQuestion(q="Quy định báo cáo doanh thu?", engine="DOCUMENT"),
    ]

    response: ChatResponse = await hybrid.execute_hybrid(
        query="Doanh thu chi nhánh Đà Nẵng?",
        department_id="SALES",
        user_id="U600",
        sub_questions=sub_questions,
        candidate_tables=[],  # No tables -> triggers fallback to Document RAG
    )

    assert response.route == "HYBRID"
    assert "15 tỷ đồng" in response.answer_markdown
