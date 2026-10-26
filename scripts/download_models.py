#!/usr/bin/env python3
"""
Model Downloader for Air-Gapped / Offline Enterprise Deployment.

Run this script on an internet-connected machine to pre-download all required
model weights, tokenizers, and configs into the `./models` directory.
Then copy the `./models` folder into the air-gapped server environment.
"""

import os
import sys
import logging
from pathlib import Path
from huggingface_hub import snapshot_download

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("model_downloader")

TARGET_DIR = Path(__file__).resolve().parent.parent / "models"

MODELS_TO_DOWNLOAD = {
    "BAAI_bge-m3": {
        "repo_id": "BAAI/bge-m3",
        "description": "Dense + Sparse Lexical Embedding Model (1024d)"
    },
    "BAAI_bge-reranker-v2-m3": {
        "repo_id": "BAAI/bge-reranker-v2-m3",
        "description": "Cross-Encoder Multilingual Reranker"
    }
}


def download_huggingface_models():
    """Download huggingface snapshot models for offline usage."""
    for local_name, info in MODELS_TO_DOWNLOAD.items():
        repo_id = info["repo_id"]
        local_path = TARGET_DIR / local_name
        logger.info(f"Downloading {repo_id} ({info['description']}) to {local_path}...")
        try:
            snapshot_download(
                repo_id=repo_id,
                local_dir=str(local_path),
                local_dir_use_symlinks=False,
                resume_download=True
            )
            logger.info(f"Successfully downloaded {repo_id} -> {local_path}")
        except Exception as e:
            logger.error(f"Failed to download {repo_id}: {e}")
            raise


def download_vietocr_weights():
    """Download default VietOCR model weights."""
    import urllib.request
    vietocr_dir = TARGET_DIR / "vietocr"
    vietocr_dir.mkdir(parents=True, exist_ok=True)
    vgg_seq2seq_url = "https://vocr.vn/data/vietocr/vgg_seq2seq.pth"
    dest_path = vietocr_dir / "vgg_seq2seq.pth"
    
    if dest_path.exists() and dest_path.stat().st_size > 10_000_000:
        logger.info(f"VietOCR weights already exist at {dest_path}")
        return

    logger.info(f"Downloading VietOCR weights from {vgg_seq2seq_url}...")
    try:
        urllib.request.urlretrieve(vgg_seq2seq_url, str(dest_path))
        logger.info(f"Successfully downloaded VietOCR weights to {dest_path}")
    except Exception as e:
        logger.warning(f"Could not download VietOCR directly from vocr.vn: {e}. You can manually place vgg_seq2seq.pth in {vietocr_dir}")


def download_rapidocr_models():
    """Trigger RapidOCR model initialization and caching for offline deployment."""
    logger.info("Initializing RapidOCR to download/verify default ONNX model weights...")
    try:
        from rapidocr_onnxruntime import RapidOCR
        _ = RapidOCR()
        logger.info("RapidOCR models initialized and cached successfully.")
    except ImportError:
        logger.warning("rapidocr_onnxruntime is not installed. Skipping RapidOCR model download.")
    except Exception as e:
        logger.warning(f"Failed to auto-download RapidOCR models: {e}")


def verify_models():
    """Verify that required model files exist locally."""
    logger.info("Verifying downloaded models...")
    for local_name in MODELS_TO_DOWNLOAD.keys():
        path = TARGET_DIR / local_name
        if path.exists() and any(path.iterdir()):
            logger.info(f" [OK] {local_name} is present at {path}")
        else:
            logger.error(f" [MISSING] {local_name} is empty or missing!")


if __name__ == "__main__":
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"Starting model downloads into {TARGET_DIR}")
    download_huggingface_models()
    download_vietocr_weights()
    download_rapidocr_models()
    verify_models()
    logger.info("All downloads completed. You can now copy './models' to the air-gapped server.")
