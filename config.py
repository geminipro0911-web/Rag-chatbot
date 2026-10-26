"""
Enterprise RAG & Tabular Execution Harness - Global Configuration.
Loads validated settings from environment variables and .env file.
"""

import os
from pathlib import Path
from typing import Optional
from pydantic import Field
try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:
    from pydantic import BaseModel as BaseSettings
    SettingsConfigDict = None


class Settings(BaseSettings):
    if SettingsConfigDict is not None:
        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            extra="ignore"
        )
    else:
        model_config = {"extra": "ignore"}

    # Server & General
    app_name: str = Field(default="Enterprise RAG & Tabular Execution Harness")
    app_env: str = Field(default="production")
    debug: bool = Field(default=False)
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    timezone: str = Field(default="Asia/Ho_Chi_Minh")
    max_file_size_mb: int = Field(default=30)
    is_public_default: bool = Field(default=False)
    proxy_secret_key: Optional[str] = Field(default=None)

    # Storage Locations
    data_raw_dir: str = Field(default="./data/raw")
    data_parquet_dir: str = Field(default="./data/parquet")
    local_models_dir: str = Field(default="./models")

    # LLM (OpenAI-compatible local server)
    llm_base_url: str = Field(default="http://127.0.0.1:8000/v1")
    llm_api_key: str = Field(default="EMPTY")
    llm_model_name: str = Field(default="gpt-oss-120b")
    llm_temperature: float = Field(default=0.1)
    llm_max_tokens: int = Field(default=4096)
    llm_timeout_seconds: float = Field(default=60.0)
    llm_max_retries: int = Field(default=3)

    # Metadata DB: PostgreSQL 16
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/rag_enterprise"
    )
    db_pool_size: int = Field(default=20)
    db_max_overflow: int = Field(default=10)

    # Vector DB: Qdrant
    vector_store_mode: str = Field(default="binary")  # "binary" or "embedded"
    qdrant_host: str = Field(default="localhost")
    qdrant_port: int = Field(default=6333)
    qdrant_grpc_port: int = Field(default=6334)
    qdrant_api_key: Optional[str] = Field(default=None)
    qdrant_collection_name: str = Field(default="enterprise_knowledge")
    qdrant_local_path: str = Field(default="./data/qdrant_storage")

    # Local Model Weights (Air-Gapped Deployment)
    bge_m3_model_path: str = Field(default="./models/BAAI_bge-m3")
    bge_m3_device: str = Field(default="cuda:0")
    reranker_model_path: str = Field(default="./models/BAAI_bge-reranker-v2-m3")
    reranker_device: str = Field(default="cpu")
    reranker_threshold: float = Field(default=0.35)
    docling_models_path: str = Field(default="./models/docling")
    vietocr_weights_path: str = Field(default="./models/vietocr/vgg_seq2seq.pth")

    # Tabular Execution Sandbox & Few-Shot
    enable_synthetic_fewshot: bool = Field(default=True)
    synthetic_fewshot_count: int = Field(default=6)
    pandas_timeout_seconds: int = Field(default=15)
    pandas_max_ram_mb: int = Field(default=512)
    duckdb_max_memory: str = Field(default="2GB")
    duckdb_threads: int = Field(default=4)
    duckdb_max_output_rows: int = Field(default=10000)

    # Authentication & RBAC Headers
    auth_mode: str = Field(default="header")
    header_user_id: str = Field(default="X-User-Id")
    header_department_id: str = Field(default="X-Department-Id")
    header_user_role: str = Field(default="X-User-Role")

    def ensure_directories(self) -> None:
        """Ensure necessary storage directories exist locally."""
        Path(self.data_raw_dir).mkdir(parents=True, exist_ok=True)
        Path(self.data_parquet_dir).mkdir(parents=True, exist_ok=True)
        Path(self.local_models_dir).mkdir(parents=True, exist_ok=True)


# Singleton settings instance
settings = Settings()
