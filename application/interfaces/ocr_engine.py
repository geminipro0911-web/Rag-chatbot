"""
OCR Engine Interface.
Defines abstract contracts for OCR detection, recognition, and scanned table layout extraction.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List


class OCREngine(ABC):
    """Abstract interface for offline OCR extraction (Vietnamese recognition + Table structure)."""

    @abstractmethod
    def extract_page(
        self,
        image_bytes: bytes,
        lang: str = "vi"
    ) -> Dict[str, Any]:
        """
        Process a rendered scanned document page image.

        Args:
            image_bytes: Raw PNG/JPEG image bytes of the page (e.g. rendered at 300 DPI).
            lang: Target language code (default 'vi').

        Returns:
            Dict containing:
                - text: Extracted page text string.
                - confidence: Average OCR confidence score (0.0 to 1.0).
                - tables: List of extracted markdown/structured tables.
        """
        pass
