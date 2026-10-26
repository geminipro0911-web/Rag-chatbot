"""
Vector Store Interface.
Defines abstract contracts for collection lifecycle, indexing, and hybrid RBAC search.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional


class VectorStore(ABC):
    """Abstract interface for Vector Database interactions (Qdrant native binary / embedded)."""

    @abstractmethod
    def init_collection(self) -> None:
        """Initialize target collection with dense, sparse configurations and payload indexes."""
        pass

    @abstractmethod
    def upsert_chunks(self, chunks: List[Dict[str, Any]]) -> bool:
        """
        Upsert a batch of chunk objects into the vector database.
        Each chunk must contain:
            - chunk_id: str
            - dense_vector: List[float]
            - sparse_indices: List[int]
            - sparse_values: List[float]
            - payload: Dict[str, Any] (doc_id, file_id, department_id, is_public, owner_user_id, etc.)
        """
        pass

    @abstractmethod
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
    ) -> List[Dict[str, Any]]:
        """
        Execute Hybrid Search (dense + sparse with Reciprocal Rank Fusion).
        Enforces RBAC filter at database query level:
            ((department_id == dept) OR (is_public == true) OR (owner_user_id == user_id))
        """
        pass

    @abstractmethod
    def delete_by_file_id(self, file_id: str) -> bool:
        """Delete all vectors associated with a file_id."""
        pass

    @abstractmethod
    def health_check(self) -> bool:
        """Check vector store connectivity."""
        pass
