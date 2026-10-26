"""
Service dependency injection for FastAPI application.
Provides lazy-loaded singletons and request-scoped services for LLM, vector store,
embedder, reranker, code executor, and application engines.
"""

from __future__ import annotations

import logging
from typing import Optional, Generator
from functools import lru_cache

from fastapi import Depends
from sqlalchemy.orm import Session

from config import settings
from infrastructure.database.session import get_db
from application.interfaces.llm_client import LLMClient
from application.interfaces.vector_store import VectorStore
from application.interfaces.embedder import Embedder
from application.interfaces.reranker import Reranker
from application.interfaces.code_executor import CodeExecutor

from infrastructure.llm.openai_llm_client import OpenAILLMClient
from infrastructure.vector_store.qdrant_store import QdrantVectorStore
from infrastructure.vector_store.qdrant_config import QdrantSettings
from infrastructure.models.bge_m3_embedder import BGEM3Embedder
from infrastructure.models.bge_reranker import BGEReranker
from infrastructure.sandbox.secure_code_executor import SecureCodeExecutor

from application.services.excel_preprocessor import ExcelPreprocessor
from application.services.catalog_service import CatalogService
from application.services.doc_ingestor import DocumentIngestor
from application.services.entity_linker import EntityLinker
from application.services.router import Router
from application.services.tabular_executor import TabularExecutor
from application.services.rag_engine import RAGEngine
from application.services.hybrid_engine import HybridEngine
from application.services.output_formatter import OutputFormatter

logger = logging.getLogger(__name__)

# Module-level singletons (initialized lazily or pre-warmed)
_llm_client: Optional[LLMClient] = None
_vector_store: Optional[VectorStore] = None
_embedder: Optional[Embedder] = None
_reranker: Optional[Reranker] = None
_code_executor: Optional[CodeExecutor] = None


def get_llm_client() -> LLMClient:
    """Provides LLM client communicating with local OpenAI-compatible endpoint."""
    global _llm_client
    if _llm_client is None:
        _llm_client = OpenAILLMClient(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model_name=settings.llm_model_name,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )
    return _llm_client


def get_vector_store() -> VectorStore:
    """Provides Qdrant vector store connection."""
    global _vector_store
    if _vector_store is None:
        qdrant_settings = QdrantSettings.from_env()
        _vector_store = QdrantVectorStore(settings=qdrant_settings)
    return _vector_store


def get_embedder() -> Embedder:
    """Provides BGE-M3 dense and sparse embedder."""
    global _embedder
    if _embedder is None:
        _embedder = BGEM3Embedder(
            model_path=settings.bge_m3_model_path,
            device=settings.bge_m3_device,
        )
    return _embedder


def get_reranker() -> Reranker:
    """Provides BGE-Reranker cross-encoder with RapidFuzz fallback."""
    global _reranker
    if _reranker is None:
        _reranker = BGEReranker(
            model_path=settings.reranker_model_path,
            device=settings.reranker_device,
        )
    return _reranker


def get_code_executor() -> CodeExecutor:
    """Provides secure DuckDB & Pandas code sandbox."""
    global _code_executor
    if _code_executor is None:
        _code_executor = SecureCodeExecutor(
            memory_limit_mb=settings.pandas_max_ram_mb,
            default_timeout_seconds=settings.pandas_timeout_seconds,
        )
    return _code_executor


def get_excel_preprocessor() -> ExcelPreprocessor:
    """Provides Excel parsing and Parquet conversion preprocessor."""
    return ExcelPreprocessor(
        output_dir=settings.data_parquet_dir
    )


def get_catalog_service(
    llm: LLMClient = Depends(get_llm_client),
    embedder: Embedder = Depends(get_embedder),
) -> CatalogService:
    """Provides tabular cataloging and synthetic few-shot service."""
    return CatalogService(
        llm_client=llm,
        embedder=embedder,
        enable_synthetic_fewshot=settings.enable_synthetic_fewshot,
    )


from application.interfaces.ocr_engine import OCREngine

_ocr_engine_instance: Optional[OCREngine] = None


def get_ocr_engine() -> Optional[OCREngine]:
    """Provides singleton OCR engine for scanned documents."""
    global _ocr_engine_instance
    if _ocr_engine_instance is None:
        try:
            from infrastructure.ocr.rapid_ocr import RapidOCREngine
            _ocr_engine_instance = RapidOCREngine()
        except Exception as exc:
            logger.warning("Could not instantiate RapidOCREngine: %s", exc)
            _ocr_engine_instance = None
    return _ocr_engine_instance


def get_document_ingestor(
    embedder: Embedder = Depends(get_embedder),
    vector_store: VectorStore = Depends(get_vector_store),
    ocr_engine: Optional[OCREngine] = Depends(get_ocr_engine),
) -> DocumentIngestor:
    """Provides document ingestion, chunking, and vector indexing service."""
    return DocumentIngestor(
        embedder=embedder,
        vector_store=vector_store,
        ocr_engine=ocr_engine,
    )


def get_entity_linker(
    db: Session = Depends(get_db),
    llm: LLMClient = Depends(get_llm_client),
) -> EntityLinker:
    """Provides entity normalization and disambiguation service."""
    return EntityLinker(llm_client=llm, db_session=db)


def get_router(
    llm: LLMClient = Depends(get_llm_client),
    embedder: Embedder = Depends(get_embedder),
) -> Router:
    """Provides query rewriting and intent routing service."""
    return Router(
        llm_client=llm,
        embedder=embedder,
    )


def get_tabular_executor(
    llm: LLMClient = Depends(get_llm_client),
    executor: CodeExecutor = Depends(get_code_executor),
) -> TabularExecutor:
    """Provides tabular sandbox execution and self-correction service."""
    return TabularExecutor(
        llm_client=llm,
        code_executor=executor,
    )


def get_rag_engine(
    vector_store: VectorStore = Depends(get_vector_store),
    embedder: Embedder = Depends(get_embedder),
    reranker: Reranker = Depends(get_reranker),
    llm: LLMClient = Depends(get_llm_client),
) -> RAGEngine:
    """Provides hybrid search, rerank, and citation-enforced RAG service."""
    return RAGEngine(
        vector_store=vector_store,
        embedder=embedder,
        reranker=reranker,
        llm_client=llm,
        reranker_threshold=settings.reranker_threshold,
    )


def get_hybrid_engine(
    tabular_executor: TabularExecutor = Depends(get_tabular_executor),
    rag_engine: RAGEngine = Depends(get_rag_engine),
    llm: LLMClient = Depends(get_llm_client),
) -> HybridEngine:
    """Provides parallel tabular and document hybrid synthesis service."""
    return HybridEngine(
        tabular_executor=tabular_executor,
        rag_engine=rag_engine,
        llm_client=llm,
    )
