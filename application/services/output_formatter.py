"""
Output Formatter & Citation Enforcer Service.
Implements Module 4:
- Tabular result rendering (VN number formatting, VN date, >50 rows truncation with statistics).
- Document RAG result formatting with in-text [n] citations and References footer.
- Post-generation citation audit (fuzzy match >= 90 with source chunks, index existence).
- Standardized API response structure.
"""

from __future__ import annotations

import datetime
import logging
import re
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# API DTOs
# ---------------------------------------------------------------------------

class SourceCitation(BaseModel):
    """Citation source metadata for API response."""
    index: int = Field(..., description="Reference index [n]")
    file_name: str = Field(..., description="Name of source file")
    page: Optional[int] = Field(default=None, description="Page number")
    section_title: Optional[str] = Field(default=None, description="Section heading")
    quote: str = Field(default="", description="Verbatim quote excerpt")
    score: Optional[float] = Field(default=None, description="Relevance / rerank score")


class TableResultDTO(BaseModel):
    """Structured tabular result metadata."""
    table_name: str
    file_name: Optional[str] = None
    sheet_name: Optional[str] = None
    total_rows: int
    displayed_rows: int
    columns: List[str]


class DebugInfo(BaseModel):
    """Debug info returned only when admin flag is enabled."""
    rewritten_query: Optional[str] = None
    language: Optional[str] = None
    code: Optional[str] = None
    attempts: int = 1
    latency_ms: Optional[float] = None
    rerank_scores: Optional[List[float]] = None


class ChatResponse(BaseModel):
    """Standardized Chat Response Model according to Module 4.4."""
    answer_markdown: str = Field(..., description="Complete markdown response")
    route: str = Field(..., description="Executed route: TABULAR | DOCUMENT | HYBRID | etc.")
    sources: List[SourceCitation] = Field(default_factory=list, description="Citations used in answer")
    tables: List[TableResultDTO] = Field(default_factory=list, description="Tabular metadata")
    debug: Optional[DebugInfo] = Field(default=None, description="Admin debug diagnostics")


# ---------------------------------------------------------------------------
# Number and Date Formatting Helpers (Vietnamese Standard)
# ---------------------------------------------------------------------------

def format_vn_number(val: Any) -> str:
    """
    Formats numeric value in Vietnamese notation:
    e.g. 1234567 -> 1.234.567
         1234567.89 -> 1.234.567,89
    """
    if pd.isna(val) or val is None:
        return ""
    if isinstance(val, (int, np.integer)):
        return f"{val:,}".replace(",", ".")
    if isinstance(val, (float, np.floating)):
        if val.is_integer():
            return f"{int(val):,}".replace(",", ".")
        # Format up to 2 decimal places with comma decimal separator
        formatted = f"{val:,.2f}"
        # Swap ',' and '.' for Vietnamese format (1,234.56 -> 1.234,56)
        parts = formatted.split(".")
        int_part = parts[0].replace(",", ".")
        dec_part = parts[1]
        return f"{int_part},{dec_part}"
    return str(val)


def format_vn_date(val: Any) -> str:
    """Formats date/datetime into dd/mm/yyyy."""
    if pd.isna(val) or val is None:
        return ""
    if isinstance(val, (datetime.datetime, datetime.date, pd.Timestamp)):
        return val.strftime("%d/%m/%Y")
    return str(val)


def df_to_markdown_safe(df: pd.DataFrame) -> str:
    """Renders DataFrame as Markdown table, using tabulate if present or native formatter."""
    try:
        return df.to_markdown(index=False)
    except Exception:
        cols = list(df.columns)
        header = "| " + " | ".join(str(c) for c in cols) + " |"
        sep = "| " + " | ".join("---" for _ in cols) + " |"
        rows = []
        for _, row in df.iterrows():
            row_str = "| " + " | ".join(str(row[c]) if not pd.isna(row[c]) else "" for c in cols) + " |"
            rows.append(row_str)
        return "\n".join([header, sep] + rows)


def format_dataframe_for_display(
    df: pd.DataFrame,
    max_rows: int = 50,
    head_rows: int = 20,
) -> Tuple[str, Optional[str]]:
    """
    Formats a Pandas DataFrame to Markdown according to Module 4.1:
    - Formats numbers in Vietnamese format (1.234.567,89).
    - Formats dates as dd/mm/yyyy.
    - If total rows > 50: displays first 20 rows + note + summary statistics table.
    
    Returns:
        Tuple of (table_markdown, summary_statistics_markdown_or_None).
    """
    if df.empty:
        return ("*Bảng không có dữ liệu.*", None)

    total_rows = len(df)
    display_df = df.copy()

    # Apply Vietnamese number and date formatting
    for col in display_df.columns:
        if pd.api.types.is_datetime64_any_dtype(display_df[col]):
            display_df[col] = display_df[col].apply(format_vn_date)
        elif pd.api.types.is_numeric_dtype(display_df[col]):
            display_df[col] = display_df[col].apply(format_vn_number)
        else:
            # Handle object columns that may contain numbers or dates
            sample = display_df[col].dropna().iloc[0] if not display_df[col].dropna().empty else None
            if isinstance(sample, (datetime.datetime, datetime.date, pd.Timestamp)):
                display_df[col] = display_df[col].apply(format_vn_date)

    summary_md: Optional[str] = None

    if total_rows > max_rows:
        sliced_df = display_df.head(head_rows)
        table_md = df_to_markdown_safe(sliced_df)
        table_md += f"\n\n*... (Đang hiển thị {head_rows} / {total_rows} dòng dữ liệu)*"

        # Calculate summary statistics for numeric columns on original dataframe
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        if numeric_cols:
            stats = []
            for col in numeric_cols:
                series = df[col].dropna()
                if not series.empty:
                    stats.append({
                        "Chỉ số": col,
                        "Số dòng (Count)": format_vn_number(int(series.count())),
                        "Tổng (Sum)": format_vn_number(series.sum()),
                        "Trung bình (Mean)": format_vn_number(series.mean()),
                        "Nhỏ nhất (Min)": format_vn_number(series.min()),
                        "Lớn nhất (Max)": format_vn_number(series.max()),
                    })
            if stats:
                stats_df = pd.DataFrame(stats)
                summary_md = (
                    "**📊 Thống kê tóm tắt các cột số:**\n\n"
                    + df_to_markdown_safe(stats_df)
                )
    else:
        table_md = df_to_markdown_safe(display_df)

    return (table_md, summary_md)


# ---------------------------------------------------------------------------
# Output Formatter & Citation Enforcer
# ---------------------------------------------------------------------------

class OutputFormatter:
    """
    Enforces strict citation integrity, formats tabular data with VN conventions,
    and synthesizes uniform markdown responses.
    """

    @staticmethod
    def format_dataframe_for_display(
        df: pd.DataFrame,
        max_rows: int = 50,
        preview_rows: int = 20,
        head_rows: Optional[int] = None,
    ) -> str:
        """Helper on OutputFormatter that returns table markdown string."""
        eff_head = head_rows if head_rows is not None else preview_rows
        tbl_md, _ = format_dataframe_for_display(df, max_rows=max_rows, head_rows=eff_head)
        return tbl_md

    @staticmethod
    def render_tabular_section(
        explanation: str,
        df: pd.DataFrame,
        file_name: Optional[str] = None,
        sheet_name: Optional[str] = None,
        table_name: Optional[str] = None,
    ) -> str:
        """
        Renders complete tabular markdown response according to Module 4.1:
        - 2-4 sentences executive explanation on top.
        - Rendered markdown table (VN formatted, >50 rows handled).
        - Optional summary statistics.
        - Source line: '📊 Nguồn dữ liệu: File [...] - Sheet [...]'.
        """
        table_md, summary_md = format_dataframe_for_display(df)

        parts: List[str] = []
        if explanation and explanation.strip():
            parts.append(explanation.strip())

        parts.append(table_md)

        if summary_md:
            parts.append(summary_md)

        # Source reference line
        src_file = file_name or "Dữ liệu hệ thống"
        src_sheet = sheet_name or table_name or "Sheet1"
        parts.append(f"📊 Nguồn dữ liệu: File [{src_file}] - Sheet [{src_sheet}]")

        return "\n\n".join(parts)

    @staticmethod
    def render_references_block(sources: List[SourceCitation]) -> str:
        """
        Renders References section according to Module 4.2:
        ### 📚 Chỉ mục nguồn trích dẫn (References)
        [1] Tên_file.pdf | Trang: X | Mục: Tiêu đề — "Trích đoạn nguyên văn..."
        """
        if not sources:
            return ""

        lines = ["### 📚 Chỉ mục nguồn trích dẫn (References)"]
        for s in sources:
            page_str = f"Trang: {s.page}" if s.page is not None else "Trang: N/A"
            section_str = f"Mục: {s.section_title}" if s.section_title else "Mục: Văn bản"
            quote_str = f' — "{s.quote}"' if s.quote else ""
            lines.append(f"[{s.index}] {s.file_name} | {page_str} | {section_str}{quote_str}")

        return "\n".join(lines)

    @staticmethod
    def audit_citations(
        text: str,
        source_chunks: List[Dict[str, Any]],
        fuzzy_threshold: float = 90.0,
    ) -> Tuple[bool, str, List[int]]:
        """
        Audits citations in generated text against source chunks according to Module 4.3:
        1. Checks that every `[n]` in the text exists in 1 <= n <= len(source_chunks).
        2. Extracts verbatim quotes from the References section and checks fuzzy match >= 90
           against the respective chunk text.
        
        Returns:
            Tuple of (is_valid, error_reason, list_of_invalid_indices).
        """
        if not source_chunks:
            # If no sources provided, text shouldn't cite [n]
            cited = re.findall(r"\[(\d+)\]", text)
            if cited:
                return False, f"Văn bản trích dẫn {cited} nhưng không có tài liệu nguồn.", [int(x) for x in cited]
            return True, "", []

        total_sources = len(source_chunks)

        # 1. Check in-text citations [n]
        found_indices = [int(m) for m in re.findall(r"\[(\d+)\]", text)]
        invalid_indices: List[int] = []

        for idx in found_indices:
            if idx < 1 or idx > total_sources:
                invalid_indices.append(idx)

        if invalid_indices:
            return (
                False,
                f"Ký hiệu trích dẫn [{invalid_indices[0]}] vượt quá số lượng tài liệu nguồn ({total_sources}).",
                invalid_indices,
            )

        # 2. Check quote fidelity in References section
        # Format: [1] File.pdf | Trang: 1 | Mục: Title — "Quote excerpt..." (supports -, –, — and various quotes)
        ref_pattern = re.compile(
            r"\[(\d+)\]\s*([^|\n]+)\s*\|\s*Trang:\s*([^|\n]+)\s*\|\s*Mục:\s*([^\-—–\n]+)\s*[\-—–]\s*[\"“”']([^\"“”']+)[\"“”']"
        )
        matches = ref_pattern.findall(text)

        for match in matches:
            ref_idx = int(match[0])
            quote = match[4].strip()

            if 1 <= ref_idx <= total_sources:
                chunk_data = source_chunks[ref_idx - 1]
                chunk_text = (
                    chunk_data.get("content")
                    or chunk_data.get("text")
                    or chunk_data.get("payload", {}).get("content")
                    or chunk_data.get("payload", {}).get("text", "")
                )

                # Compute fuzzy ratio
                ratio = fuzz.partial_ratio(quote.lower(), chunk_text.lower())
                token_ratio = fuzz.token_set_ratio(quote.lower(), chunk_text.lower())
                best_score = max(ratio, token_ratio)

                if best_score < fuzzy_threshold:
                    logger.warning(
                        f"Citation [{ref_idx}] failed fuzzy audit: score={best_score:.1f} < {fuzzy_threshold} "
                        f"for quote: '{quote[:40]}...'"
                    )
                    return (
                        False,
                        f"Trích đoạn [{ref_idx}] ('{quote[:30]}...') không khớp với nội dung gốc (độ khớp: {best_score:.1f}% < 90%).",
                        [ref_idx],
                    )

        return True, "", []

    @staticmethod
    def sanitize_citations(text: str, max_valid_index: int) -> str:
        """
        Fallback citation cleanup if retry still fails:
        Removes invalid `[n]` references or marks them with warning tag.
        """
        def replace_fn(match: re.Match) -> str:
            idx = int(match.group(1))
            if idx < 1 or idx > max_valid_index:
                return "⚠️[Trích dẫn chưa xác minh]"
            return match.group(0)

        cleaned = re.sub(r"\[(\d+)\]", replace_fn, text)
        return cleaned
