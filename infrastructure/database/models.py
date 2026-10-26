"""
SQLAlchemy 2.0 Declarative ORM Models.
Covers all 13 core tables: departments, users, files, ingestion_jobs, tables_catalog,
columns_catalog, column_values, entity_aliases, fewshot_examples, documents,
chat_sessions, chat_messages, audit_logs.
"""

from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy import (
    String, Boolean, Integer, BigInteger, Float, Text,
    DateTime, ForeignKey, Index, text, JSON
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Dialect-agnostic JSON type that compiles to JSONB on PostgreSQL and JSON on SQLite
JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class DepartmentModel(Base):
    __tablename__ = "departments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    users: Mapped[List["UserModel"]] = relationship("UserModel", back_populates="department")


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    department_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("departments.id", ondelete="SET NULL"), nullable=True)
    role: Mapped[str] = mapped_column(String(64), default="user", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    department: Mapped[Optional["DepartmentModel"]] = relationship("DepartmentModel", back_populates="users")
    files: Mapped[List["FileModel"]] = relationship("FileModel", back_populates="owner")


class FileModel(Base):
    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(32), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False)
    department_id: Mapped[str] = mapped_column(String(64), ForeignKey("departments.id"), nullable=False)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    owner: Mapped["UserModel"] = relationship("UserModel", back_populates="files")
    tables: Mapped[List["TableCatalogModel"]] = relationship("TableCatalogModel", back_populates="file", cascade="all, delete-orphan")
    documents: Mapped[List["DocumentModel"]] = relationship("DocumentModel", back_populates="file", cascade="all, delete-orphan")
    jobs: Mapped[List["IngestionJobModel"]] = relationship("IngestionJobModel", back_populates="file", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_files_department_rbac", "department_id", "is_public", "owner_user_id"),
        Index("idx_files_sha256", "sha256_hash"),
    )


class IngestionJobModel(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    file_id: Mapped[str] = mapped_column(String(64), ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    job_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    progress_pct: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    file: Mapped["FileModel"] = relationship("FileModel", back_populates="jobs")

    __table_args__ = (
        Index("idx_ingestion_jobs_status", "status", "created_at"),
    )


class TableCatalogModel(Base):
    __tablename__ = "tables_catalog"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    file_id: Mapped[str] = mapped_column(String(64), ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    sheet_name: Mapped[str] = mapped_column(String(255), nullable=False)
    parquet_path: Mapped[str] = mapped_column(String(512), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False)
    department_id: Mapped[str] = mapped_column(String(64), ForeignKey("departments.id"), nullable=False)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    row_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    table_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    business_keywords: Mapped[List[str]] = mapped_column(JSON_TYPE, default=list)
    warnings: Mapped[List[str]] = mapped_column(JSON_TYPE, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    file: Mapped["FileModel"] = relationship("FileModel", back_populates="tables")
    columns: Mapped[List["ColumnCatalogModel"]] = relationship("ColumnCatalogModel", back_populates="table", cascade="all, delete-orphan")
    distinct_values: Mapped[List["ColumnValueModel"]] = relationship("ColumnValueModel", back_populates="table", cascade="all, delete-orphan")
    fewshots: Mapped[List["FewShotExampleModel"]] = relationship("FewShotExampleModel", back_populates="table", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_tables_catalog_rbac", "department_id", "is_public", "owner_user_id"),
        Index("idx_tables_catalog_file_id", "file_id"),
    )


class ColumnCatalogModel(Base):
    __tablename__ = "columns_catalog"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    table_id: Mapped[str] = mapped_column(String(64), ForeignKey("tables_catalog.id", ondelete="CASCADE"), nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    column_alias: Mapped[str] = mapped_column(String(255), nullable=False)
    data_type: Mapped[str] = mapped_column(String(64), nullable=False)
    sample_values: Mapped[List[Any]] = mapped_column(JSON_TYPE, default=list)
    min_val: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    max_val: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    null_ratio: Mapped[float] = mapped_column(Float, default=0.0)

    table: Mapped["TableCatalogModel"] = relationship("TableCatalogModel", back_populates="columns")

    __table_args__ = (
        Index("idx_columns_catalog_table_id", "table_id"),
    )


class ColumnValueModel(Base):
    __tablename__ = "column_values"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    table_id: Mapped[str] = mapped_column(String(64), ForeignKey("tables_catalog.id", ondelete="CASCADE"), nullable=False)
    column_name: Mapped[str] = mapped_column(String(255), nullable=False)
    original_value: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_value: Mapped[str] = mapped_column(Text, nullable=False)
    frequency: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    table: Mapped["TableCatalogModel"] = relationship("TableCatalogModel", back_populates="distinct_values")

    __table_args__ = (
        Index("idx_column_values_lookup", "table_id", "column_name", "normalized_value"),
    )


class EntityAliasModel(Base):
    __tablename__ = "entity_aliases"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    standard_name: Mapped[str] = mapped_column(String(255), nullable=False)
    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), default="custom", nullable=False)
    department_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("departments.id", ondelete="CASCADE"), nullable=True)

    __table_args__ = (
        Index("idx_entity_aliases_alias", "alias"),
    )


class FewShotExampleModel(Base):
    __tablename__ = "fewshot_examples"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    table_id: Mapped[str] = mapped_column(String(64), ForeignKey("tables_catalog.id", ondelete="CASCADE"), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    sql_query: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(32), default="sql", nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="synthetic", nullable=False)
    difficulty: Mapped[str] = mapped_column(String(32), default="medium", nullable=False)
    embedding: Mapped[Optional[List[float]]] = mapped_column(JSON_TYPE, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    table: Mapped["TableCatalogModel"] = relationship("TableCatalogModel", back_populates="fewshots")

    __table_args__ = (
        Index("idx_fewshot_table_source", "table_id", "source", "is_active"),
    )


class DocumentModel(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    file_id: Mapped[str] = mapped_column(String(64), ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    doc_metadata: Mapped[Dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    total_pages: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    total_chunks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False)
    department_id: Mapped[str] = mapped_column(String(64), ForeignKey("departments.id"), nullable=False)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    file: Mapped["FileModel"] = relationship("FileModel", back_populates="documents")

    __table_args__ = (
        Index("idx_documents_rbac", "department_id", "is_public", "owner_user_id"),
        Index("idx_documents_file_id", "file_id"),
    )


class ChatSessionModel(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), default="Cuộc trò chuyện mới", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    messages: Mapped[List["ChatMessageModel"]] = relationship("ChatMessageModel", back_populates="session", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_chat_sessions_user", "user_id", "updated_at"),
    )


class ChatMessageModel(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    rewritten_query: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    route: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    structured_response: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON_TYPE, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    feedback: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    session: Mapped["ChatSessionModel"] = relationship("ChatSessionModel", back_populates="messages")

    __table_args__ = (
        Index("idx_chat_messages_session", "session_id", "created_at"),
    )


class AuditLogModel(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    department_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    details: Mapped[Dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="SUCCESS", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        Index("idx_audit_logs_user_action", "user_id", "action", "created_at"),
    )
