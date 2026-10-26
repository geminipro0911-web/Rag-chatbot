"""
BGE-Reranker-v2-m3 Implementation.
Cross-encoder reranking using FlagEmbedding FlagReranker,
with deterministic lexical/token fallback for lightweight and test environments.
"""

from __future__ import annotations

import logging
import re
from typing import List, Tuple

from application.interfaces.reranker import Reranker

logger = logging.getLogger(__name__)


class BGEReranker(Reranker):
    """
    Cross-encoder reranker for fine-grained semantic relevance scoring
    using BAAI/bge-reranker-v2-m3 or local weights.
    """

    def __init__(
        self,
        model_name_or_path: Optional[str] = None,
        model_path: Optional[str] = None,
        device: str = "cpu",
        use_fp16: Optional[bool] = None,
    ):
        self.model_name_or_path = model_path or model_name_or_path or "BAAI/bge-reranker-v2-m3"
        self.device = device
        if use_fp16 is None:
            self.use_fp16 = True if device.startswith("cuda") else False
        else:
            self.use_fp16 = use_fp16
        self._model = None

        self._init_model()

    def _init_model(self) -> None:
        """Attempts to load FlagReranker from FlagEmbedding."""
        try:
            from FlagEmbedding import FlagReranker  # type: ignore

            logger.info(f"Loading FlagReranker from {self.model_name_or_path} on {self.device}...")
            self._model = FlagReranker(
                self.model_name_or_path,
                use_fp16=self.use_fp16,
                device=self.device,
            )
            logger.info("FlagReranker loaded successfully.")
        except Exception as exc:
            logger.warning(
                f"FlagReranker not loaded ({exc}). "
                "Operating in deterministic fallback mode."
            )
            self._model = None

    def rerank(
        self,
        query: str,
        documents: List[str],
        top_k: int = 5,
    ) -> List[Tuple[int, float]]:
        """
        Reranks a list of candidate documents against a query.

        Args:
            query: User's query text.
            documents: List of candidate chunk text strings.
            top_k: Number of highest-ranked results to return.

        Returns:
            List of tuples (original_index, score) sorted descending by score.
        """
        if not documents:
            return []

        if self._model is not None:
            try:
                pairs = [[query, doc] for doc in documents]
                scores = self._model.compute_score(pairs, normalize=True)
                if isinstance(scores, (int, float)):
                    score_list = [float(scores)]
                else:
                    score_list = [float(s) for s in scores]

                indexed_scores = list(enumerate(score_list))
                indexed_scores.sort(key=lambda x: x[1], reverse=True)
                return indexed_scores[:top_k]
            except Exception as e:
                logger.warning(f"Error during FlagReranker inference: {e}; falling back to lexical scoring.")

        return self._deterministic_fallback_rerank(query, documents, top_k)

    def _deterministic_fallback_rerank(
        self,
        query: str,
        documents: List[str],
        top_k: int = 5,
    ) -> List[Tuple[int, float]]:
        """
        Deterministic fuzzy/token matching fallback using RapidFuzz when neural
        cross-encoder weights are not loaded (e.g. testing or lightweight environments).
        """
        try:
            from rapidfuzz import fuzz

            scored: List[Tuple[int, float]] = []
            for idx, doc in enumerate(documents):
                w_ratio = fuzz.WRatio(query, doc)
                ts_ratio = fuzz.token_set_ratio(query, doc)
                # Weighted combination prioritizes token overlap while keeping fuzzy phrase matching
                composite_score = (0.6 * ts_ratio + 0.4 * w_ratio) / 100.0
                scored.append((idx, round(float(composite_score), 4)))

            scored.sort(key=lambda x: x[1], reverse=True)
            return scored[:top_k]
        except ImportError:
            def tokenize(text: str) -> set[str]:
                return set(re.findall(r"\w+", text.lower()))

            q_tokens = tokenize(query)
            if not q_tokens:
                return [(i, 0.0) for i in range(min(len(documents), top_k))]

            scored = []
            for idx, doc in enumerate(documents):
                d_tokens = tokenize(doc)
                if not d_tokens:
                    scored.append((idx, 0.0))
                    continue
                intersection = q_tokens.intersection(d_tokens)
                recall = len(intersection) / len(q_tokens)
                scored.append((idx, round(float(recall), 4)))

            scored.sort(key=lambda x: x[1], reverse=True)
            return scored[:top_k]
