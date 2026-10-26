"""
FastAPI Route for User Feedback & Few-Shot Learning Verification.
Handles:
- POST /feedback: Records user ratings (thumbs up/down).
- Auto-promotes verified successful tabular SQL queries to fewshot_examples (source='verified').
- Records audit logs for governance and compliance.
"""

from __future__ import annotations

import inspect
import logging
import os
import re
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from infrastructure.database.session import get_db
from infrastructure.database.models import (
    AuditLogModel,
    ChatMessageModel,
    FewShotExampleModel,
    FileModel,
    TableCatalogModel,
    utc_now,
)
from infrastructure.sandbox.secure_code_executor import validate_duckdb_sql, SecureCodeExecutor
from application.interfaces.embedder import Embedder
from api.dependencies.auth import AuthContext, get_current_user
from api.dependencies.services import get_embedder
from api.routes.upload import ensure_user_and_department_exist

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Feedback & Audit"])


class FeedbackRequest(BaseModel):
    message_id: str = Field(..., description="ID của tin nhắn trợ lý cần đánh giá")
    feedback_type: str = Field(..., description="Loại phản hồi: 'positive', 'negative', 'thumbs_up', 'thumbs_down'")
    comment: Optional[str] = Field(default=None, description="Nhận xét chi tiết của người dùng")
    suggested_sql: Optional[str] = Field(default=None, description="Câu lệnh SQL chuẩn xác được người dùng chỉnh sửa (nếu có)")


@router.post("/feedback")
async def submit_feedback(
    req: FeedbackRequest,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
    embedder: Embedder = Depends(get_embedder),
) -> Dict[str, Any]:
    """
    Submits user feedback for an assistant response.
    When a positive rating (👍) is given to a tabular query, the executed SQL
    is automatically promoted to the fewshot_examples catalog with source='verified'.
    """
    ensure_user_and_department_exist(db, auth)

    chat_msg = db.query(ChatMessageModel).filter_by(id=req.message_id).first()
    if not chat_msg:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy tin nhắn với ID: '{req.message_id}'."
        )

    # Verify message ownership
    if chat_msg.session and not auth.is_admin and chat_msg.session.user_id != auth.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Truy cập bị từ chối: Bạn không có quyền đánh giá tin nhắn của người dùng khác."
        )

    # 1. Update message feedback
    chat_msg.feedback = req.feedback_type.lower()

    promoted_fewshot = False
    is_positive = req.feedback_type.lower() in ("positive", "thumbs_up")

    # 2. Process suggested SQL / verified fewshot
    sql_to_save = req.suggested_sql
    if not sql_to_save and is_positive and chat_msg.structured_response:
        debug_data = chat_msg.structured_response.get("debug") or {}
        sql_to_save = debug_data.get("code")

    if sql_to_save and sql_to_save.strip():
        raw_sql = sql_to_save.strip()
        # Strip comments to prevent SQL-comment Stored Prompt Injection
        clean_sql = re.sub(r"--.*?$", "", raw_sql, flags=re.MULTILINE)
        clean_sql = re.sub(r"/\*.*?\*/", "", clean_sql, flags=re.DOTALL).strip()

        # Validate SQL syntax & sandbox prohibitions
        is_valid_sql, sql_err = validate_duckdb_sql(clean_sql)
        if not is_valid_sql:
            logger.warning(f"Rejected unverified suggested SQL during feedback: {sql_err}")
            clean_sql = None
        else:
            # Identify target table within user's RBAC scope
            table_id = None
            rbac_filter = (
                or_(
                    TableCatalogModel.department_id == auth.department_id,
                    TableCatalogModel.is_public == True,
                    TableCatalogModel.owner_user_id == auth.user_id,
                )
                if not auth.is_admin
                else True
            )

            if chat_msg.structured_response:
                tables_meta = chat_msg.structured_response.get("tables") or []
                if tables_meta:
                    first_table = tables_meta[0]
                    t_id = first_table.get("table_id") or first_table.get("id")
                    if t_id:
                        matched = db.query(TableCatalogModel).filter(
                            TableCatalogModel.id == t_id,
                            rbac_filter,
                        ).first()
                        if matched:
                            table_id = matched.id
                    if not table_id:
                        t_name = first_table.get("sheet_name") or first_table.get("table_name")
                        if t_name:
                            matched = db.query(TableCatalogModel).filter(
                                TableCatalogModel.sheet_name == t_name,
                                rbac_filter,
                            ).first()
                            if matched:
                                table_id = matched.id

            if not table_id and chat_msg.route in ("TABULAR", "HYBRID"):
                any_table = db.query(TableCatalogModel).filter(rbac_filter).first()
                if any_table:
                    table_id = any_table.id
                else:
                    logger.info(
                        "No table within user's RBAC scope found for message %s. Skipping few-shot persistence.",
                        req.message_id,
                    )

            if table_id:
                # Dry run verification: verify SQL executes if parquet file exists (SEC-05)
                target_table_obj = db.query(TableCatalogModel).filter_by(id=table_id).first()
                sql_dry_run_passed = True
                if target_table_obj and target_table_obj.parquet_path and os.path.exists(target_table_obj.parquet_path):
                    try:
                        executor = SecureCodeExecutor()
                        tbl_map = {target_table_obj.sheet_name: target_table_obj.parquet_path}
                        dry_success, dry_df, dry_err = executor.execute_sql(clean_sql, tbl_map, max_rows=1)
                        if not dry_success:
                            logger.warning(f"Suggested SQL dry-run failed on parquet: {dry_err}")
                            sql_dry_run_passed = False
                    except Exception as dry_ex:
                        logger.warning(f"Dry run exception: {dry_ex}")

                question = chat_msg.rewritten_query or "Verified Query"
                # If promoting assistant's own query on thumbs_up, mark verified;
                # for user-typed custom suggested SQL, require admin for verified, else user_suggested
                if not req.suggested_sql and is_positive and sql_dry_run_passed:
                    target_source = "verified"
                elif auth.is_admin and is_positive and sql_dry_run_passed:
                    target_source = "verified"
                else:
                    target_source = "user_suggested"

                # Check if already saved
                existing = db.query(FewShotExampleModel).filter_by(
                    table_id=table_id,
                    question=question,
                    source=target_source,
                ).first()
                if not existing:
                    emb_vec = None
                    if embedder:
                        try:
                            emb_res = embedder.embed_query(question)
                            if inspect.isawaitable(emb_res):
                                emb_res = await emb_res
                            emb_vec = emb_res.get("dense") if isinstance(emb_res, dict) else emb_res
                        except Exception as e:
                            logger.warning(f"Failed to embed question for few-shot feedback: {e}")
                            emb_vec = None

                    fewshot_record = FewShotExampleModel(
                        id=str(uuid.uuid4()),
                        table_id=table_id,
                        question=question,
                        sql_query=clean_sql,
                        language="sql",
                        source=target_source,
                        difficulty="medium",
                        embedding=emb_vec,
                        is_active=True,
                    )
                    db.add(fewshot_record)
                    if target_source == "verified":
                        promoted_fewshot = True
                    logger.info(f"Saved {target_source} SQL to few-shot catalog for table {table_id}: {question}")

    # 3. Write Audit Log
    audit = AuditLogModel(
        id=str(uuid.uuid4()),
        user_id=auth.user_id,
        department_id=auth.department_id,
        action="USER_FEEDBACK",
        details={
            "message_id": req.message_id,
            "feedback": req.feedback_type,
            "comment": req.comment,
            "suggested_sql": req.suggested_sql,
            "promoted_fewshot": promoted_fewshot,
        },
        status="SUCCESS",
    )
    db.add(audit)
    db.commit()

    return {
        "status": "SUCCESS",
        "message_id": req.message_id,
        "feedback": req.feedback_type,
        "promoted_fewshot": promoted_fewshot,
        "message": "Ghi nhận phản hồi thành công.",
    }
