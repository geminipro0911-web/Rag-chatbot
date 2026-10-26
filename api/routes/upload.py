"""
FastAPI Routes for File Upload, Ingestion Status, and File Deletion.
Covers:
- POST /upload: Multipart file upload, deduplication, background ingestion dispatch.
- GET /upload/{job_id}: Ingestion job progress polling.
- DELETE /files/{file_id}: RBAC-verified deletion of files, Parquet tables, and Qdrant vectors.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from config import settings
from infrastructure.database.session import SessionLocal, get_db
from infrastructure.database.models import (
    DepartmentModel,
    DocumentModel,
    FileModel,
    IngestionJobModel,
    TableCatalogModel,
    UserModel,
    AuditLogModel,
    utc_now,
)
from sqlalchemy import or_
from api.dependencies.auth import AuthContext, get_current_user
from api.dependencies.services import (
    get_catalog_service,
    get_document_ingestor,
    get_excel_preprocessor,
    get_vector_store,
    get_llm_client,
    get_embedder,
    get_ocr_engine,
)
from application.services.catalog_service import CatalogService
from application.services.doc_ingestor import DocumentIngestor
from application.services.excel_preprocessor import ExcelPreprocessor
from application.interfaces.vector_store import VectorStore

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Files & Ingestion"])

SUPPORTED_TABULAR = {".xlsx", ".csv"}
SUPPORTED_DOCUMENTS = {".pdf", ".docx", ".md", ".txt"}


def ensure_user_and_department_exist(db: Session, auth: AuthContext) -> None:
    """Ensures department and user records exist to maintain foreign key integrity."""
    dept = db.query(DepartmentModel).filter_by(id=auth.department_id).first()
    if not dept:
        dept = DepartmentModel(
            id=auth.department_id,
            name=f"Phòng ban {auth.department_id}",
            code=auth.department_id,
        )
        db.add(dept)
        try:
            db.commit()
        except Exception:
            db.rollback()
            dept = db.query(DepartmentModel).filter_by(id=auth.department_id).first()

    user = db.query(UserModel).filter_by(id=auth.user_id).first()
    if not user:
        user = UserModel(
            id=auth.user_id,
            username=auth.user_id,
            full_name=auth.full_name or auth.user_id,
            role=auth.role,
            department_id=auth.department_id,
        )
        db.add(user)
        try:
            db.commit()
        except Exception:
            db.rollback()
            user = db.query(UserModel).filter_by(id=auth.user_id).first()


async def run_file_ingestion_job(
    job_id: str,
    file_id: str,
    file_path: str,
    ext: str,
    department_id: str,
    user_id: str,
    is_public: bool,
    llm_client: Optional[LLMClient] = None,
    embedder: Optional[Embedder] = None,
    vector_store: Optional[VectorStore] = None,
) -> None:
    """Background task orchestrating tabular or document ingestion."""
    db: Session = SessionLocal()
    try:
        job = db.query(IngestionJobModel).filter_by(id=job_id).first()
        if not job:
            logger.error(f"Job {job_id} not found in DB.")
            return

        job.status = "PROCESSING"
        job.progress_pct = 20
        db.commit()

        effective_llm = llm_client or get_llm_client()
        effective_embedder = embedder or get_embedder()

        if ext in SUPPORTED_TABULAR:
            preprocessor = ExcelPreprocessor(output_dir=settings.data_parquet_dir)
            catalog_service = CatalogService(
                llm_client=effective_llm,
                embedder=effective_embedder,
                enable_synthetic_fewshot=settings.enable_synthetic_fewshot,
            )

            process_result = await asyncio.to_thread(
                preprocessor.process_file,
                file_path=file_path,
                file_id=file_id,
                department_id=department_id,
                owner_user_id=user_id,
                is_public=is_public,
            )
            processed_sheets = process_result.sheets

            job.progress_pct = 60
            db.commit()

            # Process all sheets into memory before adding to DB for strict atomicity
            all_orm_entities = []
            for sheet in processed_sheets:
                desc, kws = await catalog_service.generate_table_description_and_keywords(sheet)
                fewshots = await catalog_service.generate_and_validate_fewshots(sheet)
                tbl_orm, cols_orm, vals_orm, shots_orm = catalog_service.build_orm_entities(
                    sheet, desc, kws, fewshots
                )
                all_orm_entities.append(tbl_orm)
                all_orm_entities.extend(cols_orm)
                all_orm_entities.extend(vals_orm)
                all_orm_entities.extend(shots_orm)

            # Atomic database insertion for all sheets
            for entity in all_orm_entities:
                db.add(entity)

            db.commit()

        elif ext in SUPPORTED_DOCUMENTS:
            effective_vs = vector_store or get_vector_store()
            embedder = effective_embedder
            ocr = get_ocr_engine()
            ingestor = DocumentIngestor(embedder=embedder, vector_store=effective_vs, ocr_engine=ocr)

            res = await ingestor.ingest_file(
                file_path=file_path,
                file_id=file_id,
                department_id=department_id,
                owner_user_id=user_id,
                is_public=is_public,
            )

            doc_model = DocumentModel(
                id=res.doc_id,
                file_id=file_id,
                title=res.title,
                doc_metadata={"file_name": res.title},
                total_pages=res.total_pages,
                total_chunks=res.total_chunks,
                owner_user_id=user_id,
                department_id=department_id,
                is_public=is_public,
            )
            db.add(doc_model)
            db.commit()

        job.status = "SUCCESS"
        job.progress_pct = 100
        job.finished_at = utc_now()
        db.commit()
        logger.info(f"Ingestion job {job_id} for file {file_id} completed successfully.")

    except Exception as exc:
        logger.exception(f"Ingestion job {job_id} failed: {exc}")
        db.rollback()
        job = db.query(IngestionJobModel).filter_by(id=job_id).first()
        if job:
            job.status = "FAILED"
            job.error_message = str(exc)
            job.finished_at = utc_now()
            db.commit()
    finally:
        db.close()


@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    is_public: bool = Form(settings.is_public_default),
    department_id: Optional[str] = Form(None),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
    llm_client: LLMClient = Depends(get_llm_client),
    embedder: Embedder = Depends(get_embedder),
    vector_store: VectorStore = Depends(get_vector_store),
) -> Dict[str, Any]:
    """
    Accepts file upload (.xlsx, .xls, .pdf, .docx, .md, .txt), verifies size & hash,
    persists raw file, and queues asynchronous background ingestion.
    """
    settings.ensure_directories()
    ensure_user_and_department_exist(db, auth)

    filename = file.filename or "uploaded_file"
    ext = Path(filename).suffix.lower()

    if ext not in (SUPPORTED_TABULAR | SUPPORTED_DOCUMENTS):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Định dạng tệp không được hỗ trợ: '{ext}'. Hệ thống chỉ hỗ trợ .xlsx, .csv, .pdf, .docx, .md, .txt."
        )

    # Read content in chunks & validate size to prevent memory exhaustion (DoS)
    max_bytes = settings.max_file_size_mb * 1024 * 1024
    chunk_size = 1024 * 1024
    hasher = hashlib.sha256()
    file_size = 0
    chunks = []
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        file_size += len(chunk)
        if file_size > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Kích thước tệp vượt quá giới hạn tối đa ({settings.max_file_size_mb}MB)."
            )
        hasher.update(chunk)
        chunks.append(chunk)
    content = b"".join(chunks)
    sha256_hash = hasher.hexdigest()

    # Effective department & RBAC validation
    if department_id and department_id.strip() != auth.department_id and not auth.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền tải tệp lên phòng ban khác ngoài phòng ban của mình."
        )

    effective_dept = (department_id or auth.department_id).strip()
    if not re.match(r"^[a-zA-Z0-9_-]{1,64}$", effective_dept):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mã phòng ban không hợp lệ."
        )

    # Check RBAC-scoped deduplication
    existing_file = db.query(FileModel).filter(
        FileModel.sha256_hash == sha256_hash,
        or_(
            FileModel.department_id == effective_dept,
            FileModel.is_public == True,
            FileModel.owner_user_id == auth.user_id,
        )
    ).first()
    if existing_file:
        # File already exists
        return {
            "status": "DUPLICATE",
            "file_id": existing_file.id,
            "message": f"Tệp '{filename}' với mã hash tương tự đã tồn tại trong hệ thống (ID: {existing_file.id}).",
        }

    # Save raw file locally
    dept_raw_dir = Path(settings.data_raw_dir) / effective_dept
    dept_raw_dir.mkdir(parents=True, exist_ok=True)
    file_id = str(uuid.uuid4())
    stored_filename = f"{file_id}_{Path(filename).name}"
    raw_storage_path = str(dept_raw_dir / stored_filename)

    with open(raw_storage_path, "wb") as f:
        f.write(content)

    # Register File entity
    file_record = FileModel(
        id=file_id,
        file_name=filename,
        file_type=ext.lstrip("."),
        file_size_bytes=file_size,
        sha256_hash=sha256_hash,
        storage_path=raw_storage_path,
        owner_user_id=auth.user_id,
        department_id=effective_dept,
        is_public=is_public,
    )
    db.add(file_record)

    # Register Audit Log
    upload_audit = AuditLogModel(
        id=str(uuid.uuid4()),
        user_id=auth.user_id,
        department_id=effective_dept,
        action="UPLOAD_FILE",
        details={
            "file_id": file_id,
            "file_name": filename,
            "file_size": file_size,
            "file_type": ext.lstrip("."),
            "is_public": is_public,
        },
        status="SUCCESS",
    )
    db.add(upload_audit)

    # Register Ingestion Job
    job_id = str(uuid.uuid4())
    job_type = "TABULAR" if ext in SUPPORTED_TABULAR else "DOCUMENT"
    job_record = IngestionJobModel(
        id=job_id,
        file_id=file_id,
        job_type=job_type,
        status="PENDING",
        progress_pct=0,
    )
    db.add(job_record)
    try:
        db.commit()
    except Exception as commit_err:
        db.rollback()
        if os.path.exists(raw_storage_path):
            try:
                os.remove(raw_storage_path)
            except OSError:
                pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Không thể lưu thông tin tệp vào cơ sở dữ liệu: {commit_err}"
        )

    # Dispatch background worker
    background_tasks.add_task(
        run_file_ingestion_job,
        job_id=job_id,
        file_id=file_id,
        file_path=raw_storage_path,
        ext=ext,
        department_id=effective_dept,
        user_id=auth.user_id,
        is_public=is_public,
        llm_client=llm_client,
        embedder=embedder,
        vector_store=vector_store,
    )

    return {
        "status": "PENDING",
        "job_id": job_id,
        "file_id": file_id,
        "job_type": job_type,
        "message": f"Tải tệp '{filename}' lên thành công. Tác vụ trích xuất và chỉ mục đang được xử lý trong nền.",
    }


@router.get("/upload/{job_id}")
def get_upload_status(
    job_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Polls ingestion job status, progress percentage, and error messages."""
    job = db.query(IngestionJobModel).filter_by(id=job_id).first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy tác vụ xử lý với ID: '{job_id}'."
        )

    if job.file:
        f = job.file
        if not auth.is_admin and not f.is_public and f.department_id != auth.department_id and f.owner_user_id != auth.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Truy cập bị từ chối: Bạn không có quyền xem thông tin tác vụ xử lý tệp của người dùng khác."
            )

    return {
        "job_id": job.id,
        "file_id": job.file_id,
        "job_type": job.job_type,
        "status": job.status,
        "progress_pct": job.progress_pct,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


@router.get("/files")
def list_files(
    department_id: Optional[str] = None,
    is_public_only: bool = False,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """
    Lists files accessible to the current user according to RBAC.
    - Admin: can view all files (optional filtering by department_id or is_public_only).
    - Regular user: can view files where department_id == auth.department_id OR is_public == True OR owner_user_id == auth.user_id.
    Returns files with latest ingestion job status, tables/documents summaries, and can_delete flag.
    """
    ensure_user_and_department_exist(db, auth)

    query = db.query(FileModel)

    if auth.is_admin:
        if department_id:
            query = query.filter(FileModel.department_id == department_id.strip())
        if is_public_only:
            query = query.filter(FileModel.is_public == True)
    else:
        rbac_condition = or_(
            FileModel.department_id == auth.department_id,
            FileModel.is_public == True,
            FileModel.owner_user_id == auth.user_id,
        )
        if is_public_only:
            query = query.filter(FileModel.is_public == True, rbac_condition)
        else:
            query = query.filter(rbac_condition)

    files = query.order_by(FileModel.created_at.desc()).all()

    result = []
    for f in files:
        latest_job = (
            db.query(IngestionJobModel)
            .filter_by(file_id=f.id)
            .order_by(IngestionJobModel.created_at.desc())
            .first()
        )
        job_info = None
        if latest_job:
            job_info = {
                "job_id": latest_job.id,
                "job_type": latest_job.job_type,
                "status": latest_job.status,
                "progress_pct": latest_job.progress_pct,
                "error_message": latest_job.error_message,
                "created_at": latest_job.created_at.isoformat() if latest_job.created_at else None,
                "finished_at": latest_job.finished_at.isoformat() if latest_job.finished_at else None,
            }

        tables = [
            {
                "id": t.id,
                "sheet_name": t.sheet_name,
                "row_count": t.row_count,
                "table_description": t.table_description,
                "business_keywords": t.business_keywords or [],
            }
            for t in (f.tables or [])
        ]

        docs = [
            {
                "id": d.id,
                "title": d.title,
                "total_pages": d.total_pages,
                "total_chunks": d.total_chunks,
            }
            for d in (f.documents or [])
        ]

        can_delete = bool(auth.is_admin or f.owner_user_id == auth.user_id)

        result.append({
            "id": f.id,
            "file_name": f.file_name,
            "file_type": f.file_type,
            "file_size_bytes": f.file_size_bytes,
            "sha256_hash": f.sha256_hash,
            "department_id": f.department_id,
            "owner_user_id": f.owner_user_id,
            "is_public": f.is_public,
            "created_at": f.created_at.isoformat() if f.created_at else None,
            "updated_at": f.updated_at.isoformat() if f.updated_at else None,
            "latest_job": job_info,
            "tables_catalog": tables,
            "documents": docs,
            "can_delete": can_delete,
        })

    return result


@router.delete("/files/{file_id}")
def delete_file(
    file_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
    vector_store: VectorStore = Depends(get_vector_store),
) -> Dict[str, Any]:
    """
    Deletes a file, associated Parquet tables, and Qdrant vector chunks.
    Enforces RBAC: only file owner or administrators can perform deletion.
    """
    file_record = db.query(FileModel).filter_by(id=file_id).first()
    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy tệp với ID: '{file_id}'."
        )

    # RBAC Ownership / Admin verification
    if not auth.is_admin and file_record.owner_user_id != auth.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Truy cập bị từ chối: Bạn không có quyền xóa tệp của người dùng khác."
        )

    # 1. Clean up Parquet files for tabular data
    tabular_tables = db.query(TableCatalogModel).filter_by(file_id=file_id).all()
    for table in tabular_tables:
        if table.parquet_path and os.path.exists(table.parquet_path):
            try:
                os.remove(table.parquet_path)
            except OSError as err:
                logger.warning(f"Could not remove Parquet file {table.parquet_path}: {err}")

    # 2. Clean up Qdrant vector store points
    vector_store.delete_by_file_id(file_id)

    # 3. Clean up raw storage file
    if file_record.storage_path and os.path.exists(file_record.storage_path):
        try:
            os.remove(file_record.storage_path)
        except OSError as err:
            logger.warning(f"Could not remove raw file {file_record.storage_path}: {err}")

    file_name = file_record.file_name

    # 4. Remove file entity from DB (cascades to related catalog/doc/job records)
    db.delete(file_record)

    # 5. Audit log entry
    audit = AuditLogModel(
        id=str(uuid.uuid4()),
        user_id=auth.user_id,
        department_id=auth.department_id,
        action="DELETE_FILE",
        details={"file_id": file_id, "file_name": file_name},
        status="SUCCESS",
    )
    db.add(audit)
    db.commit()

    return {
        "status": "SUCCESS",
        "file_id": file_id,
        "message": f"Đã xóa thành công tệp '{file_name}' và toàn bộ chỉ mục dữ liệu liên quan.",
    }
