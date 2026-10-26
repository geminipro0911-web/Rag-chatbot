"""
RapidOCR Engine Implementation.
Implements OCREngine interface using rapidocr_onnxruntime for local, fast Vietnamese & English text recognition.
"""

from __future__ import annotations

import io
import logging
from typing import Any, Dict, List, Optional
import numpy as np
from PIL import Image

from application.interfaces.ocr_engine import OCREngine

logger = logging.getLogger(__name__)


class RapidOCREngine(OCREngine):
    """Local offline OCR engine powered by RapidOCR ONNX."""

    def __init__(self) -> None:
        self._engine = None
        self._initialized = False

    def _ensure_init(self) -> None:
        if not self._initialized:
            try:
                from rapidocr_onnxruntime import RapidOCR
                self._engine = RapidOCR()
                self._initialized = True
                logger.info("RapidOCR engine initialized successfully.")
            except Exception as e:
                logger.warning("Failed to initialize RapidOCR engine: %s", e)
                self._initialized = True
                self._engine = None

    def extract_page(
        self,
        image_bytes: bytes,
        lang: str = "vi"
    ) -> Dict[str, Any]:
        """
        Processes rendered image bytes of a page.
        Returns extracted text string, average confidence, and detected tables.
        """
        self._ensure_init()
        if self._engine is None:
            return {
                "text": "",
                "confidence": 0.0,
                "tables": [],
            }

        try:
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            img_np = np.array(image)
            ocr_results, _ = self._engine(img_np)

            if not ocr_results:
                return {
                    "text": "",
                    "confidence": 0.0,
                    "tables": [],
                }

            text_lines: List[str] = []
            scores: List[float] = []

            for item in ocr_results:
                # Each item is [dt_box, text, score]
                if len(item) >= 3:
                    text_lines.append(str(item[1]))
                    try:
                        scores.append(float(item[2]))
                    except (ValueError, TypeError):
                        pass

            avg_confidence = float(np.mean(scores)) if scores else 0.85
            full_text = "\n".join(text_lines)

            return {
                "text": full_text,
                "confidence": avg_confidence,
                "tables": [],
            }
        except Exception as exc:
            logger.warning("RapidOCR extraction failed on page: %s", exc)
            return {
                "text": "",
                "confidence": 0.0,
                "tables": [],
            }
