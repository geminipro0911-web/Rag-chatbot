"""
Comprehensive Integration Tests for Phase 8 FastAPI Application.
Tests:
- GET /health: System, PostgreSQL, and Qdrant readiness check.
- POST /upload: Multipart file uploads, extension checks, size validation, deduplication.
- GET /upload/{job_id}: Asynchronous ingestion job tracking.
- DELETE /files/{file_id}: RBAC ownership and Admin permission verification.
- POST /chat: Intent routing (CHITCHAT, CLARIFY, OUT_OF_SCOPE, TABULAR),
  session history retention, and admin-only debug diagnostics filter.
- POST /feedback: User ratings (👍/👎), audit logging, and promotion of verified SQL to few-shot catalog.
"""

import io
import os
import uuid
import pytest
import pandas as pd
import openpyxl
from typing import Dict, Any, List, Optional
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from api.main import app
from config import settings
from infrastructure.database.models import (
    Base,
    DepartmentModel,
    UserModel,
    FileModel,
    IngestionJobModel,
    TableCatalogModel,
    ColumnCatalogModel,
    FewShotExampleModel,
    ChatMessageModel,
    ChatSessionModel,
    AuditLogModel,
)
from infrastructure.database.session import get_db
import infrastructure.database.session as db_session_module
from api.dependencies.services import (
    get_llm_client,
    get_vector_store,
    get_embedder,
    get_reranker,
    get_router,
    get_tabular_executor,
)
from application.interfaces.llm_client import LLMClient
from application.interfaces.vector_store import VectorStore
from application.interfaces.embedder import Embedder
from application.interfaces.reranker import Reranker
from domain.entities.query_intent import QueryIntent, SubQuestion
from application.services.router import Router
from application.services.tabular_executor import TabularExecutionResult, TabularExecutor
from application.services.output_formatter import OutputFormatter


# ---------------------------------------------------------------------------
# Test Fixtures & Mocks
# ---------------------------------------------------------------------------

class MockVectorStore(VectorStore):
    def __init__(self):
        self.deleted_files = []

    def init_collection(self) -> None:
        pass

    def upsert_chunks(self, chunks: List[Any]) -> bool:
        return True

    def hybrid_search(self, *args, **kwargs) -> List[Dict[str, Any]]:
        return []

    def delete_by_file_id(self, file_id: str) -> bool:
        self.deleted_files.append(file_id)
        return True

    def health_check(self) -> bool:
        return True


class MockEmbedder(Embedder):
    def embed_query(self, query: str) -> Dict[str, Any]:
        return {
            "dense": [0.1] * 1024,
            "sparse_indices": [10, 20],
            "sparse_values": [0.5, 0.8],
        }

    def embed_documents(self, documents: List[str]) -> List[Dict[str, Any]]:
        return [
            {
                "dense": [0.1] * 1024,
                "sparse_indices": [10, 20],
                "sparse_values": [0.5, 0.8],
            }
            for _ in documents
        ]


class MockReranker(Reranker):
    def rerank(self, query: str, documents: List[str], top_k: int = 5) -> List[Dict[str, Any]]:
        return [{"index": i, "score": 0.9 - i * 0.1} for i in range(min(len(documents), top_k))]


class MockLLMClient(LLMClient):
    def __init__(self):
        self.last_prompt = None

    async def chat_completion(self, messages: Optional[List[Dict[str, str]]] = None, prompt: Optional[str] = None, **kwargs) -> str:
        if messages:
            self.last_prompt = messages[-1]["content"]
        elif prompt:
            self.last_prompt = prompt
        return "Tóm tắt: Bảng số liệu cho thấy doanh thu các quý tăng trưởng tích cực."

    async def structured_output(self, *args, **kwargs) -> Any:
        response_model = kwargs.get("response_model")
        messages = kwargs.get("messages")
        for a in args:
            if isinstance(a, type) and issubclass(a, BaseModel):
                response_model = a
            elif isinstance(a, list):
                messages = a

        prompt = kwargs.get("prompt")
        prompt_content = prompt or (messages[-1]["content"] if messages else "")
        prompt_lower = prompt_content.lower()

        if response_model == QueryIntent:
            if "chào" in prompt_lower or "bạn là ai" in prompt_lower:
                return QueryIntent(
                    route="CHITCHAT",
                    confidence=1.0,
                    reason="Chit chat xã giao",
                )
            elif "mơ hồ" in prompt_lower or "clarify" in prompt_lower:
                return QueryIntent(
                    route="CLARIFY",
                    confidence=0.8,
                    clarify_question="Bạn muốn tra cứu số liệu doanh thu của quý nào cụ thể?",
                    reason="Câu hỏi thiếu thông tin",
                )
            elif "thời tiết" in prompt_lower or "bóng đá" in prompt_lower:
                return QueryIntent(
                    route="OUT_OF_SCOPE",
                    confidence=0.9,
                    reason="Ngoài phạm vi doanh nghiệp",
                )
            else:
                return QueryIntent(
                    route="TABULAR",
                    confidence=0.95,
                    candidate_table_ids=["tbl_test_01"],
                    reason="Cần tra cứu số liệu từ bảng tính",
                )

        if response_model is not None:
            if response_model.__name__ == "TableDescriptionKeywordsOutput":
                return response_model(description="Bảng doanh thu", keywords=["doanh thu", "ban hang"])
            if response_model.__name__ == "SyntheticFewShotOutput":
                return response_model(examples=[])
            return response_model()
        return None


from sqlalchemy import event
from sqlalchemy.engine import Engine


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Enforces SQLite Foreign Key constraints in unit tests (TST-12)."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture(scope="module")
def test_db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db_session_module.SessionLocal.configure(bind=engine)

    # Pre-seed test departments and users to satisfy Foreign Key constraints
    Session = sessionmaker(bind=engine)
    with Session() as s:
        depts = [
            "DEP_FINANCE", "DEP_SALES", "DEP_HR", "DEP_IT",
            "DEP_MARKETING", "FINANCE", "GENERAL", "DEP_GENERAL"
        ]
        for d in depts:
            if not s.query(DepartmentModel).filter_by(id=d).first():
                s.add(DepartmentModel(id=d, name=f"Dept {d}", code=d))
        s.commit()

        users = [
            ("user_dupe", "DEP_SALES", "user"),
            ("user_owner", "DEP_FINANCE", "user"),
            ("user_intruder", "DEP_HR", "user"),
            ("user_legit_owner", "DEP_FINANCE", "user"),
            ("user_victim", "DEP_IT", "user"),
            ("admin_sys", "DEP_IT", "admin"),
            ("regular_user", "DEP_MARKETING", "user"),
            ("user_chat", "GENERAL", "user"),
            ("user_tabular", "DEP_FINANCE", "user"),
            ("user_regular", "DEP_FINANCE", "user"),
            ("test_admin_user", "DEP_FINANCE", "admin"),
            ("user_admin", "DEP_FINANCE", "admin"),
            ("user_fb", "DEP_FINANCE", "user"),
            ("user_original", "GENERAL", "user"),
            ("user_alpha", "GENERAL", "user"),
            ("admin_user", "GENERAL", "admin"),
            ("nv_001", "FINANCE", "user"),
            ("user_pub", "GENERAL", "user"),
            ("user_it_lead", "DEP_IT", "user"),
            ("user_hr", "DEP_HR", "user"),
            ("user_it_dev", "DEP_IT", "user"),
            ("admin_super", "GENERAL", "admin"),
            ("user_chat_test", "GENERAL", "user"),
            ("user_bump_test", "GENERAL", "user"),
            ("admin_test_user", "GENERAL", "admin"),
        ]
        for uid, dept, role in users:
            if not s.query(UserModel).filter_by(id=uid).first():
                s.add(UserModel(id=uid, username=uid, full_name=uid, role=role, department_id=dept))
        s.commit()

    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture
def db_session(test_db_engine):
    Session = sessionmaker(bind=test_db_engine, autocommit=False, autoflush=False)
    session = Session()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client(test_db_engine, db_session):
    def override_get_db():
        Session = sessionmaker(bind=test_db_engine, autocommit=False, autoflush=False)
        db = Session()
        try:
            yield db
        finally:
            db.close()

    mock_vs = MockVectorStore()
    mock_llm = MockLLMClient()
    mock_embed = MockEmbedder()
    mock_rerank = MockReranker()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_vector_store] = lambda: mock_vs
    app.dependency_overrides[get_llm_client] = lambda: mock_llm
    app.dependency_overrides[get_embedder] = lambda: mock_embed
    app.dependency_overrides[get_reranker] = lambda: mock_rerank

    import api.dependencies.services as deps
    orig_llm = deps._llm_client
    orig_embed = deps._embedder
    deps._llm_client = mock_llm
    deps._embedder = mock_embed

    with TestClient(app) as test_client:
        test_client.mock_vs = mock_vs
        test_client.mock_llm = mock_llm
        yield test_client

    deps._llm_client = orig_llm
    deps._embedder = orig_embed
    app.dependency_overrides.clear()


# Helper to generate test Excel files in-memory
def create_sample_excel_bytes() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "DoanhThu"
    ws.append(["Mã SP", "Tên SP", "Doanh Thu", "Ngày Bán"])
    ws.append(["SP01", "Máy tính Dell", 15000000, "2026-03-15"])
    ws.append(["SP02", "Chuột Logitech", 500000, "2026-03-16"])
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_health_check_endpoint(client):
    """GET /health returns healthy status when DB and vector store are reachable."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("healthy", "degraded")
    assert data["database"] == "connected"
    assert data["vector_store"] == "ready"
    assert data["timezone"] == "Asia/Ho_Chi_Minh"


def test_upload_rejected_invalid_extension(client):
    """POST /upload rejects unsupported file formats with 415 Unsupported Media Type."""
    response = client.post(
        "/upload",
        files={"file": ("malicious.exe", b"binarycontent", "application/octet-stream")},
        headers={"X-User-Id": "test_user", "X-Department-Id": "DEP_IT"},
    )
    assert response.status_code == 415
    assert "không được hỗ trợ" in response.json()["detail"]


def test_upload_csv_success_and_poll_status(client, db_session):
    """POST /upload accepts .csv file, converts to Parquet, and GET /upload/{job_id} tracks it."""
    csv_bytes = b"Ma SP,Ten SP,Doanh Thu\nSP01,May tinh Dell,15000000\nSP02,Chuot Logitech,500000\n"
    response = client.post(
        "/upload",
        files={"file": ("doanh_thu_q1.csv", csv_bytes, "text/csv")},
        data={"is_public": "true", "department_id": "DEP_FINANCE"},
        headers={"X-User-Id": "user_finance", "X-Department-Id": "DEP_FINANCE", "X-User-Role": "user"},
    )
    assert response.status_code == 202
    res_data = response.json()
    assert res_data["status"] == "PENDING"
    assert res_data["job_type"] == "TABULAR"
    job_id = res_data["job_id"]

    poll_res = client.get(
        f"/upload/{job_id}",
        headers={"X-User-Id": "user_finance", "X-Department-Id": "DEP_FINANCE"},
    )
    assert poll_res.status_code == 200
    assert poll_res.json()["job_id"] == job_id
    assert poll_res.json()["status"] == "SUCCESS"


def test_upload_excel_success_and_poll_status(client, db_session):
    """POST /upload accepts .xlsx file, persists file entity, and GET /upload/{job_id} tracks it."""
    excel_bytes = create_sample_excel_bytes()
    response = client.post(
        "/upload",
        files={"file": ("doanh_thu_q1.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"is_public": "true", "department_id": "DEP_FINANCE"},
        headers={"X-User-Id": "user_finance", "X-Department-Id": "DEP_FINANCE", "X-User-Role": "user"},
    )
    assert response.status_code == 202
    res_data = response.json()
    assert res_data["status"] == "PENDING"
    assert res_data["job_type"] == "TABULAR"
    job_id = res_data["job_id"]
    file_id = res_data["file_id"]
    assert job_id is not None
    assert file_id is not None

    # Poll status
    poll_res = client.get(
        f"/upload/{job_id}",
        headers={"X-User-Id": "user_finance", "X-Department-Id": "DEP_FINANCE"},
    )
    assert poll_res.status_code == 200
    poll_data = poll_res.json()
    assert poll_data["job_id"] == job_id
    assert poll_data["file_id"] == file_id
    assert poll_data["job_type"] == "TABULAR"
    assert poll_data["status"] in ("PENDING", "PROCESSING", "SUCCESS")


def test_upload_duplicate_detection(client):
    """POST /upload recognizes duplicate file uploads via sha256 hash."""
    excel_bytes = create_sample_excel_bytes()
    # First upload
    res1 = client.post(
        "/upload",
        files={"file": ("doanh_thu_dupe.xlsx", excel_bytes, "application/octet-stream")},
        headers={"X-User-Id": "user_dupe", "X-Department-Id": "DEP_SALES"},
    )
    # Second upload with identical bytes
    res2 = client.post(
        "/upload",
        files={"file": ("doanh_thu_dupe_copy.xlsx", excel_bytes, "application/octet-stream")},
        headers={"X-User-Id": "user_dupe", "X-Department-Id": "DEP_SALES"},
    )
    assert res2.status_code == 202
    dupe_data = res2.json()
    assert dupe_data["status"] == "DUPLICATE"
    assert "đã tồn tại trong hệ thống" in dupe_data["message"]


def test_delete_file_rbac_forbidden_for_non_owner(client, db_session):
    """DELETE /files/{file_id} returns 403 Forbidden when a user attempts to delete someone else's file."""
    # Create file owned by user_owner
    file_record = FileModel(
        id=str(uuid.uuid4()),
        file_name="secret_finance.xlsx",
        file_type="xlsx",
        file_size_bytes=1024,
        sha256_hash="hash_secret_123",
        storage_path="./data/raw/secret.xlsx",
        owner_user_id="user_owner",
        department_id="DEP_FINANCE",
        is_public=False,
    )
    db_session.add(file_record)
    db_session.commit()

    # User_intruder attempts deletion
    response = client.delete(
        f"/files/{file_record.id}",
        headers={"X-User-Id": "user_intruder", "X-Department-Id": "DEP_HR", "X-User-Role": "user"},
    )
    assert response.status_code == 403
    assert "Truy cập bị từ chối" in response.json()["detail"]


def test_delete_file_success_by_owner(client, db_session):
    """DELETE /files/{file_id} succeeds when called by the file owner."""
    file_id = str(uuid.uuid4())
    file_record = FileModel(
        id=file_id,
        file_name="owner_report.xlsx",
        file_type="xlsx",
        file_size_bytes=2048,
        sha256_hash="hash_owner_456",
        storage_path="./data/raw/owner_report.xlsx",
        owner_user_id="user_legit_owner",
        department_id="DEP_FINANCE",
        is_public=False,
    )
    db_session.add(file_record)
    db_session.commit()

    response = client.delete(
        f"/files/{file_id}",
        headers={"X-User-Id": "user_legit_owner", "X-Department-Id": "DEP_FINANCE", "X-User-Role": "user"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "SUCCESS"
    assert file_id in client.mock_vs.deleted_files

    # Verify deleted from DB
    check_db = db_session.query(FileModel).filter_by(id=file_id).first()
    assert check_db is None


def test_delete_file_success_by_admin(client, db_session):
    """DELETE /files/{file_id} succeeds when called by an Admin regardless of file owner."""
    file_id = str(uuid.uuid4())
    file_record = FileModel(
        id=file_id,
        file_name="regular_user_file.pdf",
        file_type="pdf",
        file_size_bytes=4096,
        sha256_hash="hash_admin_del_789",
        storage_path="./data/raw/regular_user_file.pdf",
        owner_user_id="regular_user",
        department_id="DEP_MARKETING",
        is_public=False,
    )
    db_session.add(file_record)
    db_session.commit()

    response = client.delete(
        f"/files/{file_id}",
        headers={"X-User-Id": "admin_sys", "X-Department-Id": "DEP_IT", "X-User-Role": "admin"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "SUCCESS"
    assert file_id in client.mock_vs.deleted_files


def test_chat_empty_query_rejected(client):
    """POST /chat rejects empty string messages with 400 Bad Request."""
    response = client.post(
        "/chat",
        json={"message": "   "},
        headers={"X-User-Id": "user_chat"},
    )
    assert response.status_code == 400


def test_chat_chitchat_routing(client):
    """POST /chat routes friendly greetings to CHITCHAT intent."""
    response = client.post(
        "/chat",
        json={"message": "Xin chào bạn, bạn là ai?"},
        headers={"X-User-Id": "user_chat"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["route"] == "CHITCHAT"
    assert "Trợ lý AI" in data["answer_markdown"]
    assert data["session_id"] is not None
    assert data["message_id"] is not None


def test_chat_clarify_routing(client):
    """POST /chat routes ambiguous queries to CLARIFY intent."""
    response = client.post(
        "/chat",
        json={"message": "Câu hỏi còn mơ hồ chưa rõ"},
        headers={"X-User-Id": "user_chat"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["route"] == "CLARIFY"
    assert "tra cứu" in data["answer_markdown"].lower() or "làm rõ" in data["answer_markdown"].lower()


def test_chat_out_of_scope_routing(client):
    """POST /chat routes off-topic queries to OUT_OF_SCOPE intent."""
    response = client.post(
        "/chat",
        json={"message": "Hôm nay dự báo thời tiết thế nào?"},
        headers={"X-User-Id": "user_chat"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["route"] == "OUT_OF_SCOPE"
    assert "ngoài phạm vi" in data["answer_markdown"]


def test_chat_tabular_routing_and_admin_debug_filter(client, db_session):
    """
    POST /chat executes tabular queries and verifies that 'debug' diagnostics
    are ONLY returned when user has the 'admin' role.
    """
    # Create test catalog table
    file_id = str(uuid.uuid4())
    tbl_id = "tbl_test_01"
    f_orm = FileModel(
        id=file_id,
        file_name="BaoCaoBanHang.xlsx",
        file_type="xlsx",
        file_size_bytes=1000,
        sha256_hash="hash_tab_chat_999",
        storage_path="./data/raw/BaoCaoBanHang.xlsx",
        owner_user_id="user_tabular",
        department_id="DEP_FINANCE",
        is_public=True,
    )
    tbl_orm = TableCatalogModel(
        id=tbl_id,
        file_id=file_id,
        sheet_name="ChiTiet",
        parquet_path="./data/parquet/test.parquet",
        owner_user_id="user_tabular",
        department_id="DEP_FINANCE",
        is_public=True,
        row_count=100,
        table_description="Bảng chi tiết doanh số bán hàng",
        business_keywords=["doanh số", "bán hàng"],
    )
    db_session.add(f_orm)
    db_session.add(tbl_orm)
    db_session.commit()

    # Mock TabularExecutor dependency to return deterministic successful result
    mock_tabular_exec = TabularExecutionResult(
        success=True,
        data=[
            {"San_Pham": "Laptop", "Doanh_Thu": 25000000},
            {"San_Pham": "Dien_Thoai", "Doanh_Thu": 15000000},
        ],
        columns=["San_Pham", "Doanh_Thu"],
        row_count=2,
        language="sql",
        code="SELECT San_Pham, Doanh_Thu FROM ChiTiet LIMIT 10",
        retries_used=0,
    )

    class MockTabService:
        async def execute_query(self, *args, **kwargs):
            return mock_tabular_exec

    app.dependency_overrides[get_tabular_executor] = lambda: MockTabService()

    # 1. Regular user call -> debug MUST be None
    res_user = client.post(
        "/chat",
        json={"message": "Tổng hợp doanh thu các sản phẩm bán chạy nhất?"},
        headers={"X-User-Id": "user_regular", "X-Department-Id": "DEP_FINANCE", "X-User-Role": "user"},
    )
    assert res_user.status_code == 200
    user_data = res_user.json()
    assert user_data["route"] == "TABULAR"
    assert len(user_data["tables"]) >= 1
    assert "Laptop" in user_data["answer_markdown"]
    assert user_data["debug"] is None, "Regular users must NOT receive debug diagnostics!"

    # 2. Admin user call -> debug MUST be populated
    res_admin = client.post(
        "/chat",
        json={"message": "Tổng hợp doanh thu các sản phẩm bán chạy nhất?"},
        headers={"X-User-Id": "admin_user", "X-Department-Id": "DEP_FINANCE", "X-User-Role": "admin"},
    )
    assert res_admin.status_code == 200
    admin_data = res_admin.json()
    assert admin_data["route"] == "TABULAR"
    assert admin_data["debug"] is not None, "Admin users MUST receive debug diagnostics!"
    assert admin_data["debug"]["language"] == "sql"
    assert "SELECT San_Pham" in admin_data["debug"]["code"]
    assert admin_data["debug"]["latency_ms"] is not None


def test_feedback_positive_promotes_verified_fewshot(client, db_session):
    """
    POST /feedback with positive rating (thumbs_up) stores feedback,
    promotes the executed SQL to fewshot_examples with source='verified',
    and logs an audit entry.
    """
    # Create test file and table catalog entry belonging to user_fb's department
    fb_file_id = str(uuid.uuid4())
    fb_table_id = str(uuid.uuid4())
    fb_file = FileModel(
        id=fb_file_id,
        file_name="DoanhThu2026.xlsx",
        file_type="xlsx",
        file_size_bytes=2048,
        sha256_hash="hash_fb_test",
        storage_path="./data/raw/DoanhThu2026.xlsx",
        owner_user_id="user_fb",
        department_id="DEP_FINANCE",
        is_public=False,
    )
    db_session.add(fb_file)

    fb_table = TableCatalogModel(
        id=fb_table_id,
        file_id=fb_file_id,
        sheet_name="ChiTiet",
        department_id="DEP_FINANCE",
        is_public=False,
        owner_user_id="user_fb",
        parquet_path=f"./data/parquet/DEP_FINANCE/{fb_table_id}.parquet",
    )
    db_session.add(fb_table)

    # Create test chat session and message
    session_id = str(uuid.uuid4())
    msg_id = str(uuid.uuid4())

    sess = ChatSessionModel(id=session_id, user_id="user_fb", title="Session Feedback")
    db_session.add(sess)

    msg = ChatMessageModel(
        id=msg_id,
        session_id=session_id,
        role="assistant",
        content="Đây là bảng doanh thu",
        rewritten_query="Top sản phẩm có doanh thu cao nhất năm 2026?",
        route="TABULAR",
        structured_response={
            "route": "TABULAR",
            "tables": [{"sheet_name": "ChiTiet", "table_name": "ChiTiet", "table_id": fb_table_id}],
            "debug": {
                "language": "sql",
                "code": "SELECT San_Pham, SUM(Doanh_Thu) FROM ChiTiet GROUP BY San_Pham ORDER BY 2 DESC",
                "attempts": 1,
            }
        },
    )
    db_session.add(msg)
    db_session.commit()

    # Submit thumbs up feedback
    response = client.post(
        "/feedback",
        json={
            "message_id": msg_id,
            "feedback_type": "thumbs_up",
            "comment": "Truy vấn rất chuẩn xác!",
        },
        headers={"X-User-Id": "user_fb", "X-Department-Id": "DEP_FINANCE"},
    )
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["status"] == "SUCCESS"
    assert res_data["promoted_fewshot"] is True

    # Verify message feedback updated
    updated_msg = db_session.query(ChatMessageModel).filter_by(id=msg_id).first()
    assert updated_msg.feedback == "thumbs_up"

    # Verify verified fewshot example was persisted
    fewshot = db_session.query(FewShotExampleModel).filter_by(
        source="verified",
        question="Top sản phẩm có doanh thu cao nhất năm 2026?",
    ).first()
    assert fewshot is not None
    assert "SELECT San_Pham" in fewshot.sql_query
    assert fewshot.is_active is True

    # Verify audit log recorded
    audit = db_session.query(AuditLogModel).filter_by(
        user_id="user_fb",
        action="USER_FEEDBACK",
    ).first()
    assert audit is not None
    assert audit.details["feedback"] == "thumbs_up"


def test_feedback_no_matching_table_skips_fewshot_cleanly(client, db_session):
    """
    POST /feedback when no valid table matches user's RBAC scope updates
    feedback & audit log, but does NOT create orphan fewshots or fake tables.
    """
    session_id = str(uuid.uuid4())
    msg_id = str(uuid.uuid4())

    sess = ChatSessionModel(id=session_id, user_id="user_chat", title="Isolated Session")
    db_session.add(sess)

    msg = ChatMessageModel(
        id=msg_id,
        session_id=session_id,
        role="assistant",
        content="Câu trả lời chung",
        route="CHITCHAT",
    )
    db_session.add(msg)
    db_session.commit()

    response = client.post(
        "/feedback",
        json={
            "message_id": msg_id,
            "feedback_type": "thumbs_up",
            "comment": "Rất tốt!",
        },
        headers={"X-User-Id": "user_chat", "X-Department-Id": "GENERAL"},
    )
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["status"] == "SUCCESS"
    assert res_data["promoted_fewshot"] is False

    # Feedback updated
    updated_msg = db_session.query(ChatMessageModel).filter_by(id=msg_id).first()
    assert updated_msg.feedback == "thumbs_up"

    # No placeholder file created
    fake_file = db_session.query(FileModel).filter_by(file_name="SystemData.xlsx").first()
    assert fake_file is None

    # No fewshot created
    isolated_fewshots = db_session.query(FewShotExampleModel).filter_by(question="Câu trả lời chung").all()
    assert len(isolated_fewshots) == 0


def test_chat_session_rbac_ownership_forbidden_for_other_user(client, db_session):
    """
    POST /chat with existing session_id of another user must return 403 Forbidden
    unless caller is admin.
    """
    session_id = str(uuid.uuid4())
    sess = ChatSessionModel(id=session_id, user_id="user_original", title="Secret Session")
    db_session.add(sess)
    db_session.commit()

    # User B tries to access User A's session
    resp = client.post(
        "/chat",
        json={
            "message": "Cho tôi xem dữ liệu nhạy cảm",
            "session_id": session_id,
        },
        headers={"X-User-Id": "user_intruder", "X-Department-Id": "DEP_SALES"},
    )
    assert resp.status_code == 403
    assert "Không có quyền truy cập phiên hội thoại của người dùng khác" in resp.json()["detail"]

    # Admin is allowed to access
    admin_resp = client.post(
        "/chat",
        json={
            "message": "Xin chào hệ thống",
            "session_id": session_id,
        },
        headers={"X-User-Id": "admin_user", "X-User-Role": "admin"},
    )
    assert admin_resp.status_code == 200


def test_get_me_endpoint(client):
    """
    GET /me returns user identity from ADSSO headers.
    """
    # 1. Regular user
    resp = client.get(
        "/me",
        headers={
            "X-User-Id": "nv_001",
            "X-Department-Id": "FINANCE",
            "X-User-Role": "user",
            "X-User-Name": "Nguyen Van A",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == "nv_001"
    assert data["department_id"] == "FINANCE"
    assert data["role"] == "user"
    assert data["full_name"] == "Nguyen Van A"
    assert data["is_admin"] is False

    # 2. Administrator
    resp_admin = client.get(
        "/me",
        headers={
            "X-User-Id": "admin_01",
            "X-Department-Id": "IT",
            "X-User-Role": "admin",
            "X-User-Name": "Admin User",
        },
    )
    assert resp_admin.status_code == 200
    admin_data = resp_admin.json()
    assert admin_data["user_id"] == "admin_01"
    assert admin_data["is_admin"] is True


def test_list_files_rbac_and_details(client, db_session):
    """
    GET /files enforces RBAC and returns latest job and catalog summaries.
    """
    # Create test files
    f_pub = FileModel(
        id=str(uuid.uuid4()),
        file_name="QuyChe_CongTy.pdf",
        file_type="pdf",
        file_size_bytes=1024,
        sha256_hash="hash_pub_" + str(uuid.uuid4())[:8],
        storage_path="/tmp/f_pub.pdf",
        owner_user_id="user_admin",
        department_id="GENERAL",
        is_public=True,
    )
    f_it = FileModel(
        id=str(uuid.uuid4()),
        file_name="IT_Inventory.xlsx",
        file_type="xlsx",
        file_size_bytes=2048,
        sha256_hash="hash_it_" + str(uuid.uuid4())[:8],
        storage_path="/tmp/f_it.xlsx",
        owner_user_id="user_it_lead",
        department_id="DEP_IT",
        is_public=False,
    )
    f_hr = FileModel(
        id=str(uuid.uuid4()),
        file_name="HR_Salaries.xlsx",
        file_type="xlsx",
        file_size_bytes=4096,
        sha256_hash="hash_hr_" + str(uuid.uuid4())[:8],
        storage_path="/tmp/f_hr.xlsx",
        owner_user_id="user_hr",
        department_id="DEP_HR",
        is_public=False,
    )
    db_session.add_all([f_pub, f_it, f_hr])
    db_session.commit()

    # Add a job and a table for f_it
    job_it = IngestionJobModel(
        id=str(uuid.uuid4()),
        file_id=f_it.id,
        job_type="TABULAR",
        status="SUCCESS",
        progress_pct=100,
    )
    tbl_it = TableCatalogModel(
        id=str(uuid.uuid4()),
        file_id=f_it.id,
        sheet_name="Devices",
        parquet_path="/tmp/devices.parquet",
        owner_user_id="user_it_lead",
        department_id="DEP_IT",
        is_public=False,
        row_count=42,
        table_description="Danh mục thiết bị CNTT",
    )
    db_session.add_all([job_it, tbl_it])
    db_session.commit()

    # User in DEP_IT calls /files
    resp_it = client.get(
        "/files",
        headers={"X-User-Id": "user_it_dev", "X-Department-Id": "DEP_IT", "X-User-Role": "user"},
    )
    assert resp_it.status_code == 200
    it_files = resp_it.json()
    file_ids = [f["id"] for f in it_files]
    assert f_pub.id in file_ids
    assert f_it.id in file_ids
    assert f_hr.id not in file_ids  # Hidden by RBAC

    # Verify IT file details
    matched_it = next(f for f in it_files if f["id"] == f_it.id)
    assert matched_it["latest_job"]["status"] == "SUCCESS"
    assert len(matched_it["tables_catalog"]) == 1
    assert matched_it["tables_catalog"][0]["sheet_name"] == "Devices"
    assert matched_it["can_delete"] is False  # user_it_dev is not owner

    # Public only filter
    resp_pub_only = client.get(
        "/files?is_public_only=true",
        headers={"X-User-Id": "user_it_dev", "X-Department-Id": "DEP_IT", "X-User-Role": "user"},
    )
    assert resp_pub_only.status_code == 200
    pub_ids = [f["id"] for f in resp_pub_only.json()]
    assert f_pub.id in pub_ids
    assert f_it.id not in pub_ids

    # Admin sees all files
    resp_admin = client.get(
        "/files",
        headers={"X-User-Id": "admin_super", "X-User-Role": "admin"},
    )
    assert resp_admin.status_code == 200
    admin_ids = [f["id"] for f in resp_admin.json()]
    assert f_pub.id in admin_ids
    assert f_it.id in admin_ids
    assert f_hr.id in admin_ids


def test_chat_sessions_and_messages_endpoints(client, db_session):
    """
    Tests GET /sessions, GET /sessions/{id}/messages, and DELETE /sessions/{id}.
    """
    user_id = "user_chat_test"
    sess_id = str(uuid.uuid4())
    sess = ChatSessionModel(
        id=sess_id,
        user_id=user_id,
        title="Test Session Finance",
    )
    db_session.add(sess)
    db_session.commit()

    # Add messages (user + assistant)
    msg_user = ChatMessageModel(
        id=str(uuid.uuid4()),
        session_id=sess_id,
        role="user",
        content="Doanh thu quy 1?",
    )
    msg_asst = ChatMessageModel(
        id=str(uuid.uuid4()),
        session_id=sess_id,
        role="assistant",
        content="Doanh thu quy 1 là 5 tỷ [1].",
        route="TABULAR",
        structured_response={
            "route": "TABULAR",
            "sources": [{"index": 1, "file_name": "DoanhThu.xlsx", "page": 1, "section_title": "Q1", "quote": "...", "score": 0.95}],
            "tables": [{"table_name": "DoanhThu", "file_name": "DoanhThu.xlsx", "sheet_name": "Sheet1", "total_rows": 10, "displayed_rows": 10, "columns": ["Q", "V"]}],
            "debug": {"rewritten_query": "Doanh thu quy 1", "code": "SELECT * FROM t", "latency_ms": 120.0},
        },
        latency_ms=120,
    )
    db_session.add_all([msg_user, msg_asst])
    db_session.commit()

    # 1. GET /sessions for owner
    resp = client.get(
        "/sessions",
        headers={"X-User-Id": user_id, "X-Department-Id": "FINANCE"},
    )
    assert resp.status_code == 200
    sessions = resp.json()
    assert len(sessions) >= 1
    assert any(s["id"] == sess_id for s in sessions)

    # 2. GET /sessions/{id}/messages as regular user (debug must be None)
    msg_resp = client.get(
        f"/sessions/{sess_id}/messages",
        headers={"X-User-Id": user_id, "X-Department-Id": "FINANCE", "X-User-Role": "user"},
    )
    assert msg_resp.status_code == 200
    messages = msg_resp.json()
    assert len(messages) == 2
    asst_msg = next(m for m in messages if m["role"] == "assistant")
    assert asst_msg["route"] == "TABULAR"
    assert len(asst_msg["sources"]) == 1
    assert len(asst_msg["tables"]) == 1
    assert asst_msg["debug"] is None  # Filtered out for regular user!

    # 3. GET /sessions/{id}/messages as Admin (debug must be present)
    msg_resp_admin = client.get(
        f"/sessions/{sess_id}/messages",
        headers={"X-User-Id": "admin_sys", "X-User-Role": "admin"},
    )
    assert msg_resp_admin.status_code == 200
    asst_msg_admin = next(m for m in msg_resp_admin.json() if m["role"] == "assistant")
    assert asst_msg_admin["debug"] is not None
    assert asst_msg_admin["debug"]["code"] == "SELECT * FROM t"

    # 4. GET /sessions/{id}/messages by other user -> 403 Forbidden
    forbidden_resp = client.get(
        f"/sessions/{sess_id}/messages",
        headers={"X-User-Id": "other_user", "X-Department-Id": "HR", "X-User-Role": "user"},
    )
    assert forbidden_resp.status_code == 403

    # 5. DELETE /sessions/{id} by other user -> 403 Forbidden
    del_forbidden = client.delete(
        f"/sessions/{sess_id}",
        headers={"X-User-Id": "other_user", "X-Department-Id": "HR", "X-User-Role": "user"},
    )
    assert del_forbidden.status_code == 403

    # 6. DELETE /sessions/{id} by owner -> 200 OK
    del_ok = client.delete(
        f"/sessions/{sess_id}",
        headers={"X-User-Id": user_id, "X-Department-Id": "FINANCE"},
    )
    assert del_ok.status_code == 200
    assert del_ok.json()["status"] == "SUCCESS"

    # Verify session is deleted
    assert db_session.query(ChatSessionModel).filter_by(id=sess_id).first() is None


def test_static_frontend_spa_serving(client):
    """
    Verifies that when frontend/dist exists, root / and client routes return 200 with index.html.
    """
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Mbot - Trợ lý AI Doanh nghiệp" in resp.text

    # Client route like /chat-history is served by SPA index.html
    resp_route = client.get("/chat-history")
    assert resp_route.status_code == 200
    assert "Mbot - Trợ lý AI Doanh nghiệp" in resp_route.text

    # Reserved API route without GET returns 404
    resp_reserved = client.get("/chat")
    assert resp_reserved.status_code == 404


def test_chat_session_updated_at_bumps_on_new_messages(client, db_session):
    """
    Verifies that sending a new message in an existing session updates its updated_at timestamp.
    """
    from datetime import datetime, timezone, timedelta
    past_time = datetime.now(timezone.utc) - timedelta(hours=2)

    sess_id = str(uuid.uuid4())
    sess = ChatSessionModel(
        id=sess_id,
        user_id="user_bump_test",
        title="Session Bump Test",
        created_at=past_time,
        updated_at=past_time,
    )
    db_session.add(sess)
    db_session.commit()

    resp = client.post(
        "/chat",
        json={"message": "Xin chào Mbot", "session_id": sess_id},
        headers={"X-User-Id": "user_bump_test", "X-Department-Id": "IT"},
    )
    assert resp.status_code == 200

    db_session.refresh(sess)
    compare_time = past_time if sess.updated_at.tzinfo is not None else past_time.replace(tzinfo=None)
    assert sess.updated_at > compare_time
