"""
Qdrant Vector Store Implementation.
Manages collection lifecycle, point upsert (dense 1024d + sparse lexical weights),
and hybrid search with Reciprocal Rank Fusion (RRF) and RBAC security filtering.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from qdrant_client import QdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse

from application.interfaces.vector_store import VectorStore
from infrastructure.vector_store.qdrant_config import QdrantSettings

logger = logging.getLogger(__name__)


class QdrantVectorStore(VectorStore):
    """Production implementation of VectorStore using Qdrant (binary native or embedded)."""

    def __init__(
        self,
        settings: Optional[QdrantSettings] = None,
        client: Optional[QdrantClient] = None,
    ):
        self.settings = settings or QdrantSettings.from_env()
        self.collection_name = self.settings.collection_name
        self.dense_dim = self.settings.dense_dim

        if client is not None:
            self.client = client
        else:
            if self.settings.mode == "binary":
                self.client = QdrantClient(
                    host=self.settings.host,
                    port=self.settings.port,
                    grpc_port=self.settings.grpc_port,
                    api_key=self.settings.api_key,
                    prefer_grpc=False,
                    timeout=2.0,
                    check_compatibility=False,
                )
            else:
                self.client = QdrantClient(path=self.settings.local_path)

    def init_collection(self) -> None:
        """Initializes target collection with dense (1024d Cosine), sparse vectors, and RBAC payload indexes."""
        try:
            if not self.client.collection_exists(self.collection_name):
                logger.info(f"Creating Qdrant collection: {self.collection_name}")
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config={
                        self.settings.dense_vector_name: models.VectorParams(
                            size=self.dense_dim,
                            distance=models.Distance.COSINE,
                        )
                    },
                    sparse_vectors_config={
                        self.settings.sparse_vector_name: models.SparseVectorParams(
                            index=models.SparseIndexParams(on_disk=False)
                        )
                    },
                )
            else:
                logger.info(f"Qdrant collection '{self.collection_name}' already exists.")

            # Create payload indices for fast RBAC and document lookups
            self._create_payload_indexes()

        except Exception as exc:
            logger.error(f"Failed to initialize Qdrant collection: {exc}")
            raise

    def _create_payload_indexes(self) -> None:
        """Creates keyword/bool indexes for fast filtering."""
        fields = [
            ("department_id", models.PayloadSchemaType.KEYWORD),
            ("is_public", models.PayloadSchemaType.BOOL),
            ("owner_user_id", models.PayloadSchemaType.KEYWORD),
            ("doc_id", models.PayloadSchemaType.KEYWORD),
            ("file_id", models.PayloadSchemaType.KEYWORD),
        ]
        for field_name, field_type in fields:
            try:
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=field_name,
                    field_schema=field_type,
                )
            except Exception as e:
                logger.debug(f"Payload index for '{field_name}' might already exist: {e}")

    def upsert_chunks(self, chunks: List[Dict[str, Any]]) -> bool:
        """
        Upserts a batch of chunk vectors and payload metadata into Qdrant.
        Each chunk item must contain:
            - chunk_id: str
            - dense_vector: List[float]
            - sparse_indices: List[int]
            - sparse_values: List[float]
            - payload: Dict[str, Any]
        """
        if not chunks:
            return True

        points: List[models.PointStruct] = []
        for ch in chunks:
            chunk_id = ch["chunk_id"]
            dense_vec = ch["dense_vector"]
            sparse_indices = ch.get("sparse_indices", [])
            sparse_values = ch.get("sparse_values", [])
            payload = ch.get("payload", {})

            point = models.PointStruct(
                id=chunk_id,
                vector={
                    self.settings.dense_vector_name: dense_vec,
                    self.settings.sparse_vector_name: models.SparseVector(
                        indices=sparse_indices,
                        values=sparse_values,
                    ),
                },
                payload=payload,
            )
            points.append(point)

        try:
            self.client.upsert(
                collection_name=self.collection_name,
                points=points,
                wait=True,
            )
            logger.info(f"Successfully upserted {len(points)} chunks into Qdrant.")
            return True
        except Exception as exc:
            logger.error(f"Failed to upsert chunks into Qdrant: {exc}")
            raise

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
        Executes hybrid search (dense + sparse with Reciprocal Rank Fusion)
        with strictly enforced RBAC at query level:
            ((department_id == dept) OR (is_public == true) OR (owner_user_id == user_id))
        """
        # Build RBAC filter
        if is_public_only:
            rbac_filter = models.Filter(
                must=[models.FieldCondition(key="is_public", match=models.MatchValue(value=True))]
            )
        elif is_admin:
            rbac_filter = None
        else:
            rbac_filter = models.Filter(
                should=[
                    models.FieldCondition(key="department_id", match=models.MatchValue(value=department_id)),
                    models.FieldCondition(key="is_public", match=models.MatchValue(value=True)),
                    models.FieldCondition(key="owner_user_id", match=models.MatchValue(value=user_id)),
                ]
            )

        try:
            # Native Qdrant query_points with RRF fusion
            prefetch = [
                models.Prefetch(
                    query=query_dense,
                    using=self.settings.dense_vector_name,
                    limit=40,
                    filter=rbac_filter,
                ),
                models.Prefetch(
                    query=models.SparseVector(
                        indices=query_sparse_indices,
                        values=query_sparse_values,
                    ),
                    using=self.settings.sparse_vector_name,
                    limit=40,
                    filter=rbac_filter,
                ),
            ]

            res = self.client.query_points(
                collection_name=self.collection_name,
                prefetch=prefetch,
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=limit,
                with_payload=True,
            )

            scored_points = res.points
            return [
                {
                    "chunk_id": str(pt.id),
                    "score": float(pt.score) if pt.score is not None else 0.0,
                    "payload": pt.payload or {},
                }
                for pt in scored_points
            ]

        except Exception as exc:
            logger.warning(f"Native RRF query_points failed ({exc}); falling back to client-side RRF fusion.")
            return self._fallback_rrf_search(
                query_dense, query_sparse_indices, query_sparse_values, rbac_filter, limit
            )

    def _fallback_rrf_search(
        self,
        query_dense: List[float],
        query_sparse_indices: List[int],
        query_sparse_values: List[float],
        rbac_filter: Optional[models.Filter],
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Client-side Reciprocal Rank Fusion (RRF) fallback."""
        if hasattr(self.client, "search"):
            dense_hits = self.client.search(
                collection_name=self.collection_name,
                query_vector=(self.settings.dense_vector_name, query_dense),
                query_filter=rbac_filter,
                limit=40,
                with_payload=True,
            )
            sparse_hits = self.client.search(
                collection_name=self.collection_name,
                query_vector=models.NamedSparseVector(
                    name=self.settings.sparse_vector_name,
                    vector=models.SparseVector(
                        indices=query_sparse_indices,
                        values=query_sparse_values,
                    ),
                ),
                query_filter=rbac_filter,
                limit=40,
                with_payload=True,
            )
        else:
            dense_res = self.client.query_points(
                collection_name=self.collection_name,
                query=query_dense,
                using=self.settings.dense_vector_name,
                query_filter=rbac_filter,
                limit=40,
                with_payload=True,
            )
            dense_hits = dense_res.points
            sparse_res = self.client.query_points(
                collection_name=self.collection_name,
                query=models.SparseVector(
                    indices=query_sparse_indices,
                    values=query_sparse_values,
                ),
                using=self.settings.sparse_vector_name,
                query_filter=rbac_filter,
                limit=40,
                with_payload=True,
            )
            sparse_hits = sparse_res.points

        rrf_scores: Dict[str, float] = {}
        payloads: Dict[str, Dict[str, Any]] = {}
        K = 60

        for rank, hit in enumerate(dense_hits):
            cid = str(hit.id)
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + (1.0 / (K + rank + 1))
            payloads[cid] = hit.payload or {}

        for rank, hit in enumerate(sparse_hits):
            cid = str(hit.id)
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + (1.0 / (K + rank + 1))
            if cid not in payloads:
                payloads[cid] = hit.payload or {}

        sorted_cids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)[:limit]
        return [
            {
                "chunk_id": cid,
                "score": rrf_scores[cid],
                "payload": payloads[cid],
            }
            for cid in sorted_cids
        ]

    def delete_by_file_id(self, file_id: str) -> bool:
        """Deletes all chunks associated with a file_id."""
        try:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[models.FieldCondition(key="file_id", match=models.MatchValue(value=file_id))]
                    )
                ),
            )
            logger.info(f"Deleted points for file_id={file_id} from Qdrant.")
            return True
        except Exception as exc:
            logger.error(f"Failed to delete file_id={file_id} from Qdrant: {exc}")
            return False

    def health_check(self) -> bool:
        """Returns True if Qdrant service is reachable."""
        try:
            _ = self.client.get_collections()
            return True
        except Exception:
            return False
