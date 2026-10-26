"""
Qdrant Collection Configuration & Schema Definition.
Configures dense (1024d Cosine) and sparse vectors with payload indices for RBAC.
"""

import os
from typing import Optional
from pydantic import BaseModel, Field


class QdrantSettings(BaseModel):
    mode: str = Field(default="binary", description="'binary' or 'embedded'")
    host: str = Field(default="localhost")
    port: int = Field(default=6333)
    grpc_port: int = Field(default=6334)
    api_key: Optional[str] = Field(default=None)
    local_path: str = Field(default="./data/qdrant_storage")
    collection_name: str = Field(default="enterprise_knowledge")
    dense_vector_name: str = Field(default="dense")
    dense_dim: int = Field(default=1024)
    sparse_vector_name: str = Field(default="sparse")

    @classmethod
    def from_env(cls) -> "QdrantSettings":
        from config import settings
        return cls(
            mode=settings.vector_store_mode.lower(),
            host=settings.qdrant_host,
            port=settings.qdrant_port,
            grpc_port=settings.qdrant_grpc_port,
            api_key=settings.qdrant_api_key,
            local_path=settings.qdrant_local_path,
            collection_name=settings.qdrant_collection_name,
        )
