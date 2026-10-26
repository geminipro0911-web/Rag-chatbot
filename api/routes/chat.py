"""
FastAPI Route for Enterprise Chat & Multi-Engine Dispatch.
Orchestrates:
- Session history retrieval (last N=6 turns).
- RBAC candidate catalog pre-filtering.
- Intent classification and query rewriting via Router.
- Execution dispatch (TABULAR, DOCUMENT, HYBRID, CLARIFY, CHITCHAT, OUT_OF_SCOPE).
- Output formatting and references generation.
- Session and message persistence into PostgreSQL.
- Admin-only debug diagnostics filtering.
"""

from __future__ import annotations

import inspect
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from config import settings
from infrastructure.database.session import get_db
from infrastructure.database.models import (
    AuditLogModel,
    ChatMessageModel,
    ChatSessionModel,
    DocumentModel,
    FewShotExampleModel,
    TableCatalogModel,
    utc_now,
)
from api.dependencies.auth import AuthContext, get_current_user
from api.dependencies.services import (
    get_entity_linker,
    get_embedder,
    get_hybrid_engine,
    get_llm_client,
    get_rag_engine,
    get_router,
    get_tabular_executor,
)
from api.routes.upload import ensure_user_and_department_exist
from application.interfaces.llm_client import LLMClient
from application.interfaces.embedder import Embedder
from application.prompts.prompts import TABULAR_EXPLANATION_PROMPT
from application.services.entity_linker import EntityLinker
from application.services.hybrid_engine import HybridEngine
from application.services.output_formatter import (
    ChatResponse,
    DebugInfo,
    OutputFormatter,
    SourceCitation,
    TableResultDTO,
)
from application.services.rag_engine import RAGEngine
from application.services.router import Router, cosine_similarity
from application.services.tabular_executor import TabularExecutor

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Chat"])


class ChatRequest(BaseModel):
    message: str = Field(..., description="Nội dung câu hỏi của người dùng")
    session_id: Optional[str] = Field(default=None, description="ID phiên trò chuyện (nếu có)")
    is_public_only: bool = Field(default=False, description="Chỉ tìm kiếm trong dữ liệu công khai")


class ChatApiResponse(ChatResponse):
    session_id: str = Field(..., description="ID phiên hội thoại")
    message_id: str = Field(..., description="ID tin nhắn của trợ lý")


@router.post("/chat", response_model=ChatApiResponse)
async def chat_endpoint(
    req: ChatRequest,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
    router_svc: Router = Depends(get_router),
    tabular_svc: TabularExecutor = Depends(get_tabular_executor),
    rag_svc: RAGEngine = Depends(get_rag_engine),
    hybrid_svc: HybridEngine = Depends(get_hybrid_engine),
    entity_linker_svc: EntityLinker = Depends(get_entity_linker),
    embedder_svc: Embedder = Depends(get_embedder),
    llm: LLMClient = Depends(get_llm_client),
) -> ChatApiResponse:
    """
    Main conversational endpoint. Routes user query, dispatches to execution engine,
    formats tables & citations, enforces RBAC, and stores chat turn history.
    """
    start_time = time.perf_counter()
    ensure_user_and_department_exist(db, auth)

    user_query = req.message.strip()
    if not user_query:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nội dung câu hỏi không được để trống."
        )

    # 1. Manage Chat Session
    session_id = req.session_id
    if session_id:
        chat_session = db.query(ChatSessionModel).filter_by(id=session_id).first()
        if chat_session:
            if not auth.is_admin and chat_session.user_id != auth.user_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Không có quyền truy cập phiên hội thoại của người dùng khác.",
                )
        else:
            chat_session = ChatSessionModel(
                id=session_id,
                user_id=auth.user_id,
                title=user_query[:50],
            )
            db.add(chat_session)
            db.commit()
    else:
        session_id = str(uuid.uuid4())
        chat_session = ChatSessionModel(
            id=session_id,
            user_id=auth.user_id,
            title=user_query[:50],
        )
        db.add(chat_session)
        db.commit()

    # 2. Retrieve last N=6 turns for contextual rewriting
    past_messages = (
        db.query(ChatMessageModel)
        .filter_by(session_id=session_id)
        .order_by(ChatMessageModel.created_at.asc())
        .all()
    )
    history = [
        {"role": msg.role, "content": msg.content}
        for msg in past_messages[-6:]
    ]

    # Calculate consecutive clarification turns
    consecutive_clarifications = 0
    for msg in reversed(past_messages):
        if msg.role == "assistant":
            if msg.route == "CLARIFY":
                consecutive_clarifications += 1
            else:
                break

    # 3. Retrieve RBAC-filtered candidate catalogs
    table_query = db.query(TableCatalogModel)
    if req.is_public_only:
        table_query = table_query.filter(TableCatalogModel.is_public == True)
    elif not auth.is_admin:
        table_query = table_query.filter(
            or_(
                TableCatalogModel.department_id == auth.department_id,
                TableCatalogModel.is_public == True,
                TableCatalogModel.owner_user_id == auth.user_id,
            )
        )
    candidate_table_models = table_query.all()
    candidate_tables: List[Dict[str, Any]] = []
    for t in candidate_table_models:
        f_name = t.file.file_name if t.file else "BaoCao.xlsx"
        f_stem = re.sub(r"[^a-zA-Z0-9_]", "_", Path(f_name).stem).strip("_")
        s_stem = re.sub(r"[^a-zA-Z0-9_]", "_", t.sheet_name).strip("_")
        unique_alias = f"{f_stem}_{s_stem}" if f_stem else s_stem
        candidate_tables.append({
            "id": t.id,
            "table_name": t.sheet_name,
            "sheet_name": t.sheet_name,
            "table_alias": unique_alias,
            "file_name": f_name,
            "description": t.table_description or "",
            "keywords": t.business_keywords or [],
            "business_keywords": t.business_keywords or [],
            "parquet_path": t.parquet_path,
            "columns": [
                {
                    "name": c.column_alias,
                    "column_alias": c.column_alias,
                    "column_name": c.original_name,
                    "type": c.data_type,
                    "dtype": c.data_type,
                    "sample_values": c.sample_values,
                    "min_val": c.min_val,
                    "max_val": c.max_val,
                }
                for c in t.columns
            ] if t.columns else [],
        })

    doc_query = db.query(DocumentModel)
    if req.is_public_only:
        doc_query = doc_query.filter(DocumentModel.is_public == True)
    elif not auth.is_admin:
        doc_query = doc_query.filter(
            or_(
                DocumentModel.department_id == auth.department_id,
                DocumentModel.is_public == True,
                DocumentModel.owner_user_id == auth.user_id,
            )
        )
    candidate_doc_models = doc_query.all()
    candidate_docs: List[Dict[str, Any]] = [
        {
            "id": d.id,
            "title": d.title,
            "summary": str(d.doc_metadata or {}),
        }
        for d in candidate_doc_models
    ]

    # 4. Route query via Router (Query rewriting + Intent classification)
    rewritten_query = await router_svc.rewrite_query(
        query=user_query,
        chat_history=history,
    )
    routing_result = await router_svc.route_query(
        rewritten_query=rewritten_query,
        candidate_tables=candidate_tables,
        candidate_docs=candidate_docs,
        consecutive_clarifications=consecutive_clarifications,
    )

    route = routing_result.route

    # Prepare response placeholders
    answer_markdown = ""
    sources: List[SourceCitation] = []
    tables: List[TableResultDTO] = []
    debug_info = DebugInfo(
        rewritten_query=rewritten_query,
        language="none",
        code=None,
        attempts=1,
    )

    # Prepare fewshot examples filtered strictly by candidate tables within RBAC scope
    target_table_ids = (
        routing_result.candidate_table_ids
        if routing_result.candidate_table_ids
        else [t.get("id") for t in candidate_tables if t.get("id")]
    )
    if target_table_ids:
        fewshot_models = (
            db.query(FewShotExampleModel)
            .filter(
                FewShotExampleModel.is_active == True,
                FewShotExampleModel.table_id.in_(target_table_ids),
            )
            .all()
        )
    else:
        fewshot_models = []

    query_dense = None
    if embedder_svc:
        try:
            q_emb = embedder_svc.embed_query(rewritten_query)
            if inspect.isawaitable(q_emb):
                q_emb = await q_emb
            query_dense = q_emb.get("dense") if isinstance(q_emb, dict) else q_emb
        except Exception:
            pass

    scored_fewshots = []
    for f in fewshot_models:
        sim = 0.0
        if query_dense and f.embedding:
            try:
                sim = cosine_similarity(query_dense, f.embedding)
            except Exception:
                sim = 0.0
        if f.source == "verified":
            sim += 1.0
        scored_fewshots.append((f, sim))

    scored_fewshots.sort(key=lambda x: x[1], reverse=True)
    top_fewshot_models = [item[0] for item in scored_fewshots[:3]] if scored_fewshots else fewshot_models[:3]

    fewshot_dicts = [
        {
            "id": f.id,
            "table_id": f.table_id,
            "question": f.question,
            "code": f.sql_query,
            "sql_query": f.sql_query,
            "language": f.language or "sql",
            "source": f.source,
            "embedding": f.embedding,
        }
        for f in top_fewshot_models
    ]

    # 5. Dispatch based on route
    if route == "TABULAR":
        target_tables = candidate_tables
        if routing_result.candidate_table_ids:
            target_tables = [
                t for t in candidate_tables if t.get("id") in routing_result.candidate_table_ids
            ] or candidate_tables

        if not target_tables:
            answer_markdown = "Không tìm thấy bảng tính phù hợp trong cơ sở dữ liệu được phân quyền để thực hiện truy vấn."
        else:
            entity_links = await entity_linker_svc.link_entities(
                query=rewritten_query,
                candidate_tables=target_tables,
            )
            exec_res = await tabular_svc.execute_query(
                query=rewritten_query,
                candidate_tables=target_tables,
                fewshot_examples=fewshot_dicts,
                entity_links=entity_links,
            )

            debug_info.language = exec_res.language
            debug_info.code = exec_res.code
            debug_info.attempts = exec_res.retries_used + 1

            if exec_res.success:
                df = pd.DataFrame(exec_res.data, columns=exec_res.columns) if exec_res.data else pd.DataFrame(columns=exec_res.columns)
                target_tbl = target_tables[0]
                if exec_res.code:
                    for tbl in target_tables:
                        alias = tbl.get("table_alias") or tbl.get("table_name")
                        if alias and alias.lower() in exec_res.code.lower():
                            target_tbl = tbl
                            break
                sheet_name = target_tbl.get("sheet_name") or target_tbl.get("table_name", "Sheet1")
                source_file = target_tbl.get("file_name", "BaoCao.xlsx")

                # Generate 2-4 sentence executive summary via LLM
                try:
                    summary_df_md = OutputFormatter.format_dataframe_for_display(df, max_rows=10, preview_rows=10)
                    comment_prompt = (
                        f"Câu hỏi: {rewritten_query}\n\n"
                        f"Bảng số liệu kết quả:\n{summary_df_md}\n\n"
                        f"Hãy viết nhận xét tóm tắt từ 2 đến 4 câu theo yêu cầu."
                    )
                    comment_res = await llm.chat_completion(
                        messages=[
                            {"role": "system", "content": TABULAR_EXPLANATION_PROMPT},
                            {"role": "user", "content": comment_prompt},
                        ],
                        temperature=0.2,
                    )
                    executive_summary = comment_res.strip()
                except Exception as exc:
                    logger.warning(f"Failed to generate tabular summary comment: {exc}")
                    executive_summary = f"Dưới đây là kết quả trích xuất từ bảng {sheet_name} ({len(df)} dòng)."

                answer_markdown = OutputFormatter.render_tabular_section(
                    explanation=executive_summary,
                    df=df,
                    file_name=source_file,
                    sheet_name=sheet_name,
                )
                tables.append(
                    TableResultDTO(
                        table_name=f"{source_file} - {sheet_name}",
                        file_name=source_file,
                        sheet_name=sheet_name,
                        total_rows=len(df),
                        displayed_rows=min(20, len(df)),
                        columns=list(df.columns),
                    )
                )
            else:
                # 1-time fallback to DOCUMENT route if tabular failed
                rag_res = await rag_svc.answer_query(
                    query=rewritten_query,
                    department_id=auth.department_id,
                    user_id=auth.user_id,
                    is_admin=auth.is_admin,
                    is_public_only=req.is_public_only,
                )
                if rag_res.sources and rag_res.fallback_reason not in ("empty", "threshold_rejected"):
                    logger.info("Tabular failed; 1-time fallback to DOCUMENT succeeded.")
                    route = "DOCUMENT"
                    answer_markdown = rag_res.answer_markdown
                    sources = rag_res.sources
                    debug_info.rerank_scores = [c.score for c in rag_res.sources if c.score is not None]
                else:
                    if auth.is_admin:
                        answer_markdown = (
                            f"Rất tiếc, hệ thống không thể thực hiện truy vấn số liệu thành công sau các lần tự sửa lỗi.\n\n"
                            f"**Lỗi gặp phải:** `{exec_res.error}`\n\n"
                            f"**Truy vấn đã thử nghiệm:**\n```{exec_res.language or 'sql'}\n{exec_res.code or ''}\n```\n\n"
                            f"💡 *Gợi ý:* Bạn hãy thử diễn đạt lại câu hỏi, chỉ định rõ tên cột cần lọc hoặc kiểm tra lại điều kiện."
                        )
                    else:
                        answer_markdown = (
                            "Rất tiếc, hệ thống không thể thực hiện truy vấn số liệu phù hợp với câu hỏi của bạn.\n\n"
                            "💡 *Gợi ý:* Bạn hãy thử diễn đạt lại câu hỏi cụ thể hơn hoặc chỉ định rõ bảng dữ liệu cần tra cứu."
                        )

    elif route == "DOCUMENT":
        rag_res = await rag_svc.answer_query(
            query=rewritten_query,
            department_id=auth.department_id,
            user_id=auth.user_id,
            is_admin=auth.is_admin,
            is_public_only=req.is_public_only,
        )
        # Check if 1-time fallback to TABULAR is needed
        if (not rag_res.sources or rag_res.fallback_reason in ("empty", "threshold_rejected")) and candidate_tables:
            logger.info("DOCUMENT search yielded empty/rejected; attempting 1-time fallback to TABULAR.")
            entity_links = await entity_linker_svc.link_entities(
                query=rewritten_query,
                candidate_tables=candidate_tables,
            )
            exec_res = await tabular_svc.execute_query(
                query=rewritten_query,
                candidate_tables=candidate_tables,
                fewshot_examples=fewshot_dicts,
                entity_links=entity_links,
            )
            if exec_res.success:
                route = "TABULAR"
                debug_info.language = exec_res.language
                debug_info.code = exec_res.code
                debug_info.attempts = exec_res.retries_used + 1
                df = pd.DataFrame(exec_res.data, columns=exec_res.columns) if exec_res.data else pd.DataFrame(columns=exec_res.columns)
                target_tbl = candidate_tables[0]
                if exec_res.code:
                    for tbl in candidate_tables:
                        alias = tbl.get("table_alias") or tbl.get("table_name")
                        if alias and alias.lower() in exec_res.code.lower():
                            target_tbl = tbl
                            break
                sheet_name = target_tbl.get("sheet_name") or target_tbl.get("table_name", "Sheet1")
                source_file = target_tbl.get("file_name", "BaoCao.xlsx")

                answer_markdown = OutputFormatter.render_tabular_section(
                    explanation=f"Dưới đây là kết quả tra cứu từ bảng {sheet_name} ({len(df)} dòng):",
                    df=df,
                    file_name=source_file,
                    sheet_name=sheet_name,
                )
                tables.append(
                    TableResultDTO(
                        table_name=f"{source_file} - {sheet_name}",
                        file_name=source_file,
                        sheet_name=sheet_name,
                        total_rows=len(df),
                        displayed_rows=min(20, len(df)),
                        columns=list(df.columns),
                    )
                )
            else:
                answer_markdown = rag_res.answer_markdown
                sources = rag_res.sources
                debug_info.rerank_scores = [c.score for c in rag_res.sources if c.score is not None]
        else:
            answer_markdown = rag_res.answer_markdown
            sources = rag_res.sources
            debug_info.rerank_scores = [c.score for c in rag_res.sources if c.score is not None]
        sources = rag_res.sources
        debug_info.rerank_scores = [c.score for c in rag_res.sources if c.score is not None]

    elif route == "HYBRID":
        target_tables = candidate_tables
        if routing_result.candidate_table_ids:
            target_tables = [
                t for t in candidate_tables if t.get("id") in routing_result.candidate_table_ids
            ] or candidate_tables
        entity_links = await entity_linker_svc.link_entities(
            query=rewritten_query,
            candidate_tables=target_tables,
        )
        hybrid_res = await hybrid_svc.execute_hybrid(
            query=rewritten_query,
            department_id=auth.department_id,
            user_id=auth.user_id,
            is_admin=auth.is_admin,
            sub_questions=routing_result.sub_questions,
            candidate_tables=target_tables,
            fewshot_examples=fewshot_dicts,
            entity_links=entity_links,
            is_public_only=req.is_public_only,
        )
        answer_markdown = hybrid_res.answer_markdown
        sources = hybrid_res.sources
        tables = hybrid_res.tables
        if hybrid_res.debug:
            debug_info.language = hybrid_res.debug.language

    elif route == "CLARIFY":
        answer_markdown = (
            routing_result.clarify_question
            or "Câu hỏi của bạn cần thêm thông tin để hệ thống có thể hỗ trợ chính xác. Vui lòng nói rõ hơn về bảng số liệu hoặc tài liệu bạn muốn tra cứu."
        )

    elif route == "CHITCHAT":
        answer_markdown = (
            "Xin chào! Tôi là Trợ lý AI Hỏi đáp Dữ liệu Doanh nghiệp. "
            "Tôi có thể hỗ trợ bạn tra cứu, tính toán số liệu trên bảng tính Excel "
            "hoặc trích dẫn thông tin từ các tài liệu quy định, chính sách, hướng dẫn nội bộ. "
            "Bạn cần tôi hỗ trợ thông tin gì hôm nay?"
        )

    else:  # OUT_OF_SCOPE
        answer_markdown = (
            "Xin lỗi, câu hỏi này nằm ngoài phạm vi dữ liệu hoặc tài liệu nội bộ của hệ thống. "
            "Tôi chỉ có thể hỗ trợ trả lời các nghiệp vụ và dữ liệu nằm trong tài liệu/bảng tính được phân quyền truy cập."
        )

    # 6. Latency & Diagnostics
    latency_ms = float((time.perf_counter() - start_time) * 1000)
    debug_info.latency_ms = round(latency_ms, 2)

    # 7. Persist chat turn to DB
    user_msg_id = str(uuid.uuid4())
    assistant_msg_id = str(uuid.uuid4())

    user_msg_record = ChatMessageModel(
        id=user_msg_id,
        session_id=session_id,
        role="user",
        content=user_query,
        latency_ms=0,
    )
    db.add(user_msg_record)

    assistant_msg_record = ChatMessageModel(
        id=assistant_msg_id,
        session_id=session_id,
        role="assistant",
        rewritten_query=rewritten_query,
        route=route,
        content=answer_markdown,
        structured_response={
            "route": route,
            "sources": [s.model_dump() for s in sources],
            "tables": [t.model_dump() for t in tables],
            "debug": debug_info.model_dump(),
        },
        latency_ms=int(latency_ms),
    )
    # Update session updated_at timestamp
    chat_session.updated_at = utc_now()
    db.add(chat_session)
    db.add(assistant_msg_record)

    # Record Audit Log for query execution
    chat_audit = AuditLogModel(
        id=str(uuid.uuid4()),
        user_id=auth.user_id,
        department_id=auth.department_id,
        action="CHAT_QUERY",
        details={
            "session_id": session_id,
            "message_id": assistant_msg_id,
            "route": route,
            "rewritten_query": rewritten_query,
            "executed_code": debug_info.code if debug_info else None,
            "latency_ms": latency_ms,
        },
        status="SUCCESS",
    )
    db.add(chat_audit)
    db.commit()

    # 8. RBAC Debug Filter: only admin gets debug object
    final_debug = debug_info if auth.is_admin else None

    return ChatApiResponse(
        session_id=session_id,
        message_id=assistant_msg_id,
        answer_markdown=answer_markdown,
        route=route,
        sources=sources,
        tables=tables,
        debug=final_debug,
    )


@router.get("/sessions")
def list_chat_sessions(
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """
    Returns list of chat sessions belonging to auth.user_id, ordered by updated_at DESC.
    """
    ensure_user_and_department_exist(db, auth)
    sessions = (
        db.query(ChatSessionModel)
        .filter_by(user_id=auth.user_id)
        .order_by(ChatSessionModel.updated_at.desc())
        .all()
    )
    return [
        {
            "id": s.id,
            "title": s.title,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        }
        for s in sessions
    ]


@router.get("/sessions/{session_id}/messages")
def get_session_messages(
    session_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """
    Returns all messages for a session ordered by created_at ASC.
    Verifies that session belongs to auth.user_id or auth.is_admin.
    For assistant messages, unpacks structured_response and filters debug info by RBAC.
    """
    ensure_user_and_department_exist(db, auth)
    session = db.query(ChatSessionModel).filter_by(id=session_id).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy phiên hội thoại với ID: '{session_id}'."
        )

    if not auth.is_admin and session.user_id != auth.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Truy cập bị từ chối: Bạn không có quyền truy cập phiên hội thoại của người dùng khác."
        )

    messages = (
        db.query(ChatMessageModel)
        .filter_by(session_id=session_id)
        .order_by(ChatMessageModel.created_at.asc())
        .all()
    )

    output = []
    for msg in messages:
        item: Dict[str, Any] = {
            "id": msg.id,
            "session_id": msg.session_id,
            "role": msg.role,
            "content": msg.content,
            "latency_ms": msg.latency_ms,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
        }

        if msg.role == "assistant":
            struct = msg.structured_response or {}
            item["route"] = msg.route or struct.get("route")
            item["sources"] = struct.get("sources", [])
            item["tables"] = struct.get("tables", [])
            item["feedback"] = msg.feedback

            # Only admin sees debug diagnostics
            if auth.is_admin:
                item["debug"] = struct.get("debug")
            else:
                item["debug"] = None
        else:
            item["route"] = None
            item["sources"] = []
            item["tables"] = []
            item["debug"] = None
            item["feedback"] = None

        output.append(item)

    return output


@router.delete("/sessions/{session_id}")
def delete_chat_session(
    session_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Deletes a chat session and all associated messages.
    RBAC: Only the owner or an administrator can delete a session.
    """
    ensure_user_and_department_exist(db, auth)
    session = db.query(ChatSessionModel).filter_by(id=session_id).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy phiên hội thoại với ID: '{session_id}'."
        )

    if not auth.is_admin and session.user_id != auth.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Truy cập bị từ chối: Bạn không có quyền xóa phiên hội thoại của người dùng khác."
        )

    db.delete(session)

    audit = AuditLogModel(
        id=str(uuid.uuid4()),
        user_id=auth.user_id,
        department_id=auth.department_id,
        action="DELETE_CHAT_SESSION",
        details={"session_id": session_id},
        status="SUCCESS",
    )
    db.add(audit)
    db.commit()

    return {
        "status": "SUCCESS",
        "session_id": session_id,
        "message": "Đã xóa thành công cuộc trò chuyện.",
    }
