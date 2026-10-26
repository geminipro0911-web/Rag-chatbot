"""
Reranker Interface.
Defines abstract contracts for cross-encoder reranking of candidate documents.
"""

from abc import ABC, abstractmethod
from typing import List, Tuple


class Reranker(ABC):
    """Abstract interface for cross-encoder reranking."""

    @abstractmethod
    def rerank(
        self,
        query: str,
        documents: List[str],
        top_k: int = 5
    ) -> List[Tuple[int, float]]:
        """
        Rerank a list of candidate documents against a query.

        Args:
            query: User's query text.
            documents: List of candidate chunk text strings.
            top_k: Number of highest-ranked results to return.

        Returns:
            List of tuples `(original_index, score)` sorted descending by score.
        """
        pass
