"""
Enterprise RAG & Tabular Execution Harness - FastAPI Application.
Air-gapped, 100% offline deployment with native uvicorn runner.
Mounts:
- POST /upload, GET /upload/{job_id}, DELETE /files/{file_id}
- POST /chat
- POST /feedback
- GET /health
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Dict, Any

import uvicorn
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from config import settings
from infrastructure.database.session import engine, get_db, test_db_connection
from infrastructure.database.models import Base
from infrastructure.vector_store.qdrant_store import QdrantVectorStore
from api.dependencies.services import get_vector_store
from api.dependencies.auth import AuthContext, get_current_user
from application.interfaces.vector_store import VectorStore

from api.routes.upload import router as upload_router
from api.routes.chat import router as chat_router
from api.routes.feedback import router as feedback_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("enterprise_rag.api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifecycle manager.
    Initializes storage folders, database schema, and Qdrant collection on startup.
    """
    logger.info("Initializing Enterprise RAG & Tabular Application...")
    settings.ensure_directories()

    # 1. Initialize DB tables
    try:
        if test_db_connection():
            Base.metadata.create_all(bind=engine)
            logger.info("PostgreSQL database tables verified and initialized.")
        else:
            logger.info("Database host not reachable at startup; skipping schema auto-creation.")
    except Exception as exc:
        logger.warning(f"Database schema auto-creation check: {exc}")

    # 2. Initialize Qdrant collection
    try:
        if get_vector_store in app.dependency_overrides:
            vs = app.dependency_overrides[get_vector_store]()
        else:
            vs = get_vector_store()
        vs.init_collection()
        logger.info("Qdrant collection verified and ready.")
    except Exception as exc:
        logger.warning(f"Qdrant collection init check: {exc}")

    yield

    logger.info("Enterprise RAG & Tabular Application shutdown complete.")


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="Air-gapped 100% offline Enterprise RAG & Tabular Execution Harness with Clean Architecture.",
    lifespan=lifespan,
)

# CORS configuration for frontend enterprise clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API Routers
app.include_router(upload_router)
app.include_router(chat_router)
app.include_router(feedback_router)


@app.get("/health", tags=["Health"])
def health_check(
    db: Session = Depends(get_db),
    vector_store: VectorStore = Depends(get_vector_store),
) -> Dict[str, Any]:
    """Health status check for system, PostgreSQL, and Qdrant vector store."""
    from sqlalchemy import text
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    vs_ok = vector_store.health_check()

    overall = "healthy" if db_ok and vs_ok else ("degraded" if db_ok or vs_ok else "unhealthy")

    return {
        "status": overall,
        "database": "connected" if db_ok else "disconnected",
        "vector_store": "ready" if vs_ok else "unavailable",
        "app_env": settings.app_env,
        "timezone": settings.timezone,
    }


@app.get("/me", tags=["Auth"])
def get_current_user_profile(
    auth: AuthContext = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Returns authenticated user profile extracted from reverse proxy ADSSO headers.
    Used by frontend to populate read-only user identity badge.
    """
    return {
        "user_id": auth.user_id,
        "full_name": auth.full_name or auth.user_id,
        "department_id": auth.department_id,
        "role": auth.role,
        "is_admin": auth.is_admin,
    }


# Static Frontend Serving for Zero-Docker LAN deployment
frontend_dist = Path("frontend/dist")
assets_dir = frontend_dist / "assets"
if assets_dir.is_dir():
    app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_spa_fallback(full_path: str):
    """
    Single Page Application (SPA) catch-all fallback route.
    Serves static frontend files and falls back to index.html for client-side routing.
    Does not intercept existing API endpoints or swagger docs.
    """
    segments = [s for s in full_path.replace("\\", "/").split("/") if s]
    first_segment = segments[0] if segments else ""
    reserved_segments = {
        "api", "docs", "redoc", "openapi.json", "health",
        "me", "upload", "files", "chat", "sessions", "feedback"
    }
    if first_segment in reserved_segments or any(s.startswith(".") for s in segments):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

    resolved_dist = frontend_dist.resolve()
    if full_path:
        try:
            target_file = (resolved_dist / full_path).resolve()
            if not target_file.is_relative_to(resolved_dist):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid path")
            if target_file.is_file():
                return FileResponse(target_file)
        except (ValueError, OSError):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid path")

    index_file = resolved_dist / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Frontend static build not found. Run 'npm run build' in frontend/ to generate assets."
    )


if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
    )
