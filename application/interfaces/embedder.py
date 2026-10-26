"""
Embedder Interface.
Defines abstract contracts for dense and sparse lexical vector generation (BGE-M3).
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any


class Embedder(ABC):
    """Abstract interface for dense (1024d) and sparse lexical embedding generation."""

    @abstractmethod
    def embed_query(self, query: str) -> Dict[str, Any]:
        """
        Embed a single search query.
        
        Returns:
            Dict containing:
                - "dense": List[float] (1024 dimensions)
                - "sparse_indices": List[int]
                - "sparse_values": List[float]
        """
        pass

    @abstractmethod
    def embed_documents(self, documents: List[str]) -> List[Dict[str, Any]]:
        """
        Embed a list of text document chunks.
        
        Returns:
            List of dicts, each containing:
                - "dense": List[float]
                - "sparse_indices": List[int]
                - "sparse_values": List[float]
        """
        pass
