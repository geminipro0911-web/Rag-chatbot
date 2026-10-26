"""
Entity Linker Service.
Multi-tier entity linking pipeline resolving user query mentions to canonical database values.

Tiers:
1. LLM extraction of entity mentions + candidate columns (with heuristic fallback).
2. Normalization: lowercase, unidecode, strip punctuation, collapse whitespace.
3. Exact matching against entity aliases dictionary (pre-seeded & DB entity_aliases).
4. RapidFuzz (WRatio / token_set_ratio) on distinct values:
   - Score >= 90 -> accepted match ('fuzzy')
   - Score 70-89 -> ambiguous candidate
5. LLM candidate disambiguation: strictly pick from candidate list (never create new values).
   - If no match/candidate -> 'unlinked' (score = 0.0).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple, Union

import unidecode
from pydantic import BaseModel, Field
from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from application.interfaces.llm_client import LLMClient
from domain.entities.entity_link import EntityLinkResult, EntityMention
from infrastructure.database.models import ColumnValueModel, EntityAliasModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default Alias Dictionary (Admin extensible via DB)
# ---------------------------------------------------------------------------

DEFAULT_ENTITY_ALIASES: Dict[str, str] = {
    # Locations / Cities / Provinces
    "hn": "Hà Nội",
    "ha noi": "Hà Nội",
    "hanoi": "Hà Nội",
    "hcm": "Hồ Chí Minh",
    "tphcm": "Hồ Chí Minh",
    "tp hcm": "Hồ Chí Minh",
    "tp ho chi minh": "Hồ Chí Minh",
    "sg": "Hồ Chí Minh",
    "sai gon": "Hồ Chí Minh",
    "saigon": "Hồ Chí Minh",
    "dn": "Đà Nẵng",
    "da nang": "Đà Nẵng",
    "hp": "Hải Phòng",
    "hai phong": "Hải Phòng",
    "ct": "Cần Thơ",
    "can tho": "Cần Thơ",
    "bd": "Bình Dương",
    "binh duong": "Bình Dương",
    "dna": "Đồng Nai",
    "dong nai": "Đồng Nai",
    "vt": "Vũng Tàu",
    "vung tau": "Vũng Tàu",
    "brvt": "Bà Rịa - Vũng Tàu",
    "hue": "Huế",
    "thua thien hue": "Thừa Thiên Huế",
    # Quarters / Time units
    "q1": "Quý 1",
    "q 1": "Quý 1",
    "quy 1": "Quý 1",
    "q2": "Quý 2",
    "q 2": "Quý 2",
    "quy 2": "Quý 2",
    "q3": "Quý 3",
    "q 3": "Quý 3",
    "quy 3": "Quý 3",
    "q4": "Quý 4",
    "q 4": "Quý 4",
    "quy 4": "Quý 4",
    "t1": "Tháng 1",
    "t2": "Tháng 2",
    "t3": "Tháng 3",
    "t4": "Tháng 4",
    "t5": "Tháng 5",
    "t6": "Tháng 6",
    "t7": "Tháng 7",
    "t8": "Tháng 8",
    "t9": "Tháng 9",
    "t10": "Tháng 10",
    "t11": "Tháng 11",
    "t12": "Tháng 12",
    # Roles / Departments
    "nv": "Nhân viên",
    "gd": "Giám đốc",
    "tgd": "Tổng giám đốc",
    "tp": "Trưởng phòng",
    "pp": "Phó phòng",
    "kd": "Kinh doanh",
    "kt": "Kế toán",
    "tc": "Tài chính",
    "mkt": "Marketing",
    "ns": "Nhân sự",
    "it": "Công nghệ thông tin",
    "cntt": "Công nghệ thông tin",
}


def normalize_entity_text(text: str) -> str:
    """
    Tier 2 Normalization: lowercase, unidecode, strip punctuation, collapse whitespace.
    """
    if not text:
        return ""
    # lowercase
    norm = text.lower()
    # unidecode
    norm = unidecode.unidecode(norm)
    # strip punctuation and non-alphanumeric chars (keep spaces and digits)
    norm = re.sub(r"[^\w\s]", " ", norm)
    # collapse whitespace
    norm = re.sub(r"\s+", " ", norm).strip()
    return norm


# ---------------------------------------------------------------------------
# Structured Schemas for LLM Extraction and Disambiguation
# ---------------------------------------------------------------------------

class EntityMentionItem(BaseModel):
    mention: str = Field(..., description="Mention text extracted from query, e.g. 'HN', 'quý 1', 'phòng kinh doanh'")
    column: Optional[str] = Field(None, description="Expected or candidate column name, e.g. 'chi_nhanh', 'quy'")


class EntityExtractionOutput(BaseModel):
    mentions: List[EntityMentionItem] = Field(default_factory=list, description="Extracted entity mentions")


class EntityDisambiguationOutput(BaseModel):
    selected_value: Optional[str] = Field(
        None,
        description="The selected canonical value strictly from the candidate list, or null if none match."
    )


class DistinctValueEntry:
    """Internal helper representing a distinct database column value."""
    def __init__(self, table_id: str, column_name: str, original_value: str, normalized_value: Optional[str] = None):
        self.table_id = table_id
        self.column_name = column_name
        self.original_value = str(original_value)
        self.normalized_value = normalized_value or normalize_entity_text(str(original_value))


# ---------------------------------------------------------------------------
# Entity Linker Class
# ---------------------------------------------------------------------------

class EntityLinker:
    """
    Multi-tier Entity Linker resolving entity mentions in natural language queries
    to canonical database values in tabular schemas.
    """

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        db_session: Optional[Session] = None,
        custom_aliases: Optional[Dict[str, str]] = None,
    ):
        self.llm_client = llm_client
        self.db_session = db_session
        self.aliases: Dict[str, str] = {}

        # 1. Load default seeds
        for k, v in DEFAULT_ENTITY_ALIASES.items():
            self.aliases[normalize_entity_text(k)] = v

        # 2. Add custom aliases if provided
        if custom_aliases:
            for k, v in custom_aliases.items():
                self.aliases[normalize_entity_text(k)] = v

        # 3. Load from database if session is available
        if self.db_session:
            self._load_aliases_from_db()

    def _load_aliases_from_db(self) -> None:
        """Loads aliases from PostgreSQL entity_aliases table."""
        try:
            stmt = select(EntityAliasModel)
            results = self.db_session.execute(stmt).scalars().all()
            for row in results:
                norm_key = normalize_entity_text(row.alias)
                self.aliases[norm_key] = row.standard_name
            logger.info("Loaded %d entity aliases from database.", len(results))
        except Exception as e:
            logger.warning("Could not load aliases from database: %s", e)

    async def extract_mentions(
        self,
        query: str,
        catalog_columns: Optional[List[Dict[str, str]]] = None,
    ) -> List[EntityMention]:
        """
        Tier 1: Extract entity mentions and optional candidate columns using LLM,
        with robust heuristic fallback.
        """
        if self.llm_client:
            schema_hints = ""
            if catalog_columns:
                col_descs = [f"- {c.get('column_alias', c.get('column_name'))}: {c.get('column_name')}" for c in catalog_columns[:15]]
                schema_hints = "Các cột dữ liệu khả dụng trong bảng:\n" + "\n".join(col_descs) + "\n\n"

            prompt = (
                "Bạn là chuyên gia NLP xử lý ngôn ngữ tự nhiên cho hệ thống truy vấn cơ sở dữ liệu doanh nghiệp.\n"
                "Nhiệm vụ: Trích xuất các thực thể cụ thể (entity mentions) xuất hiện trong câu hỏi của người dùng "
                "dùng làm điều kiện lọc (ví dụ: tên chi nhánh, phòng ban, quý, tháng, năm, tên người, trạng thái, mã đơn hàng, sản phẩm).\n"
                f"{schema_hints}"
                "Câu hỏi người dùng: \"" + query + "\"\n\n"
                "Hãy trích xuất danh sách các mentions và cột dự kiến tương ứng dưới dạng JSON."
            )

            try:
                extraction = await self.llm_client.structured_output(
                    prompt=prompt,
                    response_model=EntityExtractionOutput,
                    system_prompt="Bạn là bộ trích xuất thực thể (NER) chính xác cho hệ thống cơ sở dữ liệu.",
                    temperature=0.0,
                )
                if extraction.mentions:
                    return [EntityMention(mention=m.mention, column=m.column) for m in extraction.mentions if m.mention.strip()]
            except Exception as e:
                logger.warning("LLM entity extraction failed, falling back to heuristic: %s", e)

        # Heuristic fallback:
        # 1. Check for common alias keys present in the query
        norm_q = normalize_entity_text(query)
        q_words = norm_q.split()
        extracted: List[EntityMention] = []
        seen_mentions = set()

        # Check multi-word and single-word alias matches
        for alias_key in sorted(self.aliases.keys(), key=lambda x: len(x), reverse=True):
            pattern = r"\b" + re.escape(alias_key) + r"\b"
            if re.search(pattern, norm_q):
                if alias_key not in seen_mentions:
                    extracted.append(EntityMention(mention=alias_key, column=None))
                    seen_mentions.add(alias_key)

        # Check for quoted phrases "..."
        quotes = re.findall(r'["\']([^"\']+)["\']', query)
        for q_item in quotes:
            q_clean = q_item.strip()
            if q_clean and q_clean.lower() not in seen_mentions:
                extracted.append(EntityMention(mention=q_clean, column=None))
                seen_mentions.add(q_clean.lower())

        # Check for standalone uppercase acronyms (e.g. HN, HCM, TPHCM, Q1, Q2) in original query
        acronyms = re.findall(r'\b[A-Z0-9]{2,6}\b', query)
        for ac in acronyms:
            if ac.lower() not in seen_mentions:
                extracted.append(EntityMention(mention=ac, column=None))
                seen_mentions.add(ac.lower())

        return extracted

    async def link_entities(
        self,
        query: str,
        table_values: Optional[List[Union[ColumnValueModel, Dict[str, Any], DistinctValueEntry]]] = None,
        candidate_tables: Optional[List[Dict[str, Any]]] = None,
        extracted_mentions: Optional[List[EntityMention]] = None,
    ) -> List[EntityLinkResult]:
        """
        Executes the complete multi-tier entity linking pipeline.

        Args:
            query: Natural language query (usually rewritten query).
            table_values: Collection of distinct column values to match against.
            candidate_tables: Optional list of candidate table definitions for context.
            extracted_mentions: Optional pre-extracted mentions. If None, extracted via Tier 1.

        Returns:
            List of EntityLinkResult objects.
        """
        # Parse distinct values into unified DistinctValueEntry objects
        dv_entries: List[DistinctValueEntry] = []
        if table_values:
            for item in table_values:
                if isinstance(item, DistinctValueEntry):
                    dv_entries.append(item)
                elif isinstance(item, ColumnValueModel):
                    dv_entries.append(
                        DistinctValueEntry(
                            table_id=item.table_id,
                            column_name=item.column_name,
                            original_value=item.original_value,
                            normalized_value=item.normalized_value,
                        )
                    )
                elif isinstance(item, dict):
                    dv_entries.append(
                        DistinctValueEntry(
                            table_id=item.get("table_id", ""),
                            column_name=item.get("column_name", ""),
                            original_value=item.get("original_value", ""),
                            normalized_value=item.get("normalized_value"),
                        )
                    )

        # If db_session is provided and table_values was empty, query DB column_values
        if not dv_entries and self.db_session and candidate_tables:
            table_ids = [t.get("id") for t in candidate_tables if t.get("id")]
            if table_ids:
                try:
                    stmt = select(ColumnValueModel).where(ColumnValueModel.table_id.in_(table_ids))
                    db_vals = self.db_session.execute(stmt).scalars().all()
                    for v in db_vals:
                        dv_entries.append(
                            DistinctValueEntry(
                                table_id=v.table_id,
                                column_name=v.column_name,
                                original_value=v.original_value,
                                normalized_value=v.normalized_value,
                            )
                        )
                except Exception as e:
                    logger.warning("Failed to query column_values from DB: %s", e)

        # Tier 1: Extract mentions
        if extracted_mentions is None:
            catalog_cols: List[Dict[str, str]] = []
            if candidate_tables:
                for tbl in candidate_tables:
                    for col in tbl.get("columns", []):
                        if isinstance(col, dict):
                            catalog_cols.append(col)
            extracted_mentions = await self.extract_mentions(query, catalog_columns=catalog_cols or None)

        results: List[EntityLinkResult] = []

        default_table_id = ""
        if candidate_tables and len(candidate_tables) > 0:
            default_table_id = candidate_tables[0].get("id", "")
        elif dv_entries:
            default_table_id = dv_entries[0].table_id

        for entity_item in extracted_mentions:
            mention = entity_item.mention.strip()
            if not mention:
                continue

            # Tier 2: Normalize
            norm_mention = normalize_entity_text(mention)
            target_column = entity_item.column

            # Tier 3: Alias dictionary exact match
            if norm_mention in self.aliases:
                standard_name = self.aliases[norm_mention]
                norm_standard = normalize_entity_text(standard_name)

                # Find match in distinct values
                matched_dv = None
                # Check candidate column first if provided
                for dv in dv_entries:
                    if target_column and dv.column_name.lower() != target_column.lower():
                        continue
                    if dv.normalized_value == norm_standard or dv.original_value.lower() == standard_name.lower():
                        matched_dv = dv
                        break

                # If not found in target column, search across all columns
                if not matched_dv:
                    for dv in dv_entries:
                        if dv.normalized_value == norm_standard or dv.original_value.lower() == standard_name.lower():
                            matched_dv = dv
                            break

                # If matched to a specific distinct value
                if matched_dv:
                    results.append(
                        EntityLinkResult(
                            mention=mention,
                            table_id=matched_dv.table_id,
                            column=matched_dv.column_name,
                            value=matched_dv.original_value,
                            method="alias",
                            score=1.0,
                        )
                    )
                    continue
                else:
                    # Match via alias even if distinct values not populated
                    results.append(
                        EntityLinkResult(
                            mention=mention,
                            table_id=default_table_id,
                            column=target_column or "",
                            value=standard_name,
                            method="alias",
                            score=1.0,
                        )
                    )
                    continue

            # Tier 4: RapidFuzz on distinct values
            # Filter distinct values relevant to target column if specified
            candidates_pool = dv_entries
            if target_column:
                filtered = [dv for dv in dv_entries if dv.column_name.lower() == target_column.lower()]
                if filtered:
                    candidates_pool = filtered

            high_matches: List[Tuple[DistinctValueEntry, float]] = []
            ambiguous_candidates: List[Tuple[DistinctValueEntry, float]] = []

            for dv in candidates_pool:
                score_w = fuzz.WRatio(norm_mention, dv.normalized_value)
                score_t = fuzz.token_set_ratio(norm_mention, dv.normalized_value)
                score = float(max(score_w, score_t))

                if score >= 90.0:
                    high_matches.append((dv, score))
                elif score >= 70.0:
                    ambiguous_candidates.append((dv, score))

            # Tier 4 Check: Clear unique match >= 90?
            # If exactly 1 match >= 90, or the top match is clearly ahead of the runner-up (>= 10 points higher)
            if high_matches:
                high_matches.sort(key=lambda x: x[1], reverse=True)
                is_clear_winner = len(high_matches) == 1 or (high_matches[0][1] - high_matches[1][1] >= 10.0)
                if is_clear_winner:
                    best_dv, best_score = high_matches[0]
                    results.append(
                        EntityLinkResult(
                            mention=mention,
                            table_id=best_dv.table_id,
                            column=best_dv.column_name,
                            value=best_dv.original_value,
                            method="fuzzy",
                            score=round(best_score / 100.0, 3),
                        )
                    )
                    continue

            # Tier 5: Multiple candidates (ties/close >= 90 or candidates in 70-89) -> LLM Disambiguation
            combined_candidates: List[Tuple[DistinctValueEntry, float]] = high_matches + ambiguous_candidates
            if combined_candidates and self.llm_client:
                # Sort and deduplicate top candidates
                combined_candidates.sort(key=lambda x: x[1], reverse=True)
                unique_candidates_map: Dict[str, DistinctValueEntry] = {}
                for cand_dv, cand_score in combined_candidates[:8]:
                    if cand_dv.original_value not in unique_candidates_map:
                        unique_candidates_map[cand_dv.original_value] = cand_dv

                candidate_names = list(unique_candidates_map.keys())

                disambig_prompt = (
                    f"Người dùng đưa ra câu hỏi: \"{query}\"\n"
                    f"Trong câu hỏi có nhắc tới thực thể: \"{mention}\" (cột tương ứng: {target_column or 'chưa rõ'}).\n\n"
                    f"Danh sách các giá trị hợp lệ có sẵn trong cơ sở dữ liệu:\n"
                    + "\n".join([f"- {name}" for name in candidate_names])
                    + "\n\n"
                    "QUY TẮC BẮT BUỘC:\n"
                    "1. Hãy chọn DUY NHẤT một giá trị từ danh sách trên mà người dùng đang muốn ám chỉ nhất.\n"
                    "2. TUYỆT ĐỐI KHÔNG ĐƯỢC tạo ra, sửa đổi hoặc bịa đặt giá trị mới không nằm trong danh sách trên.\n"
                    "3. Nếu không có giá trị nào trong danh sách thực sự phù hợp, hãy đặt selected_value là null."
                )

                try:
                    disambig_result = await self.llm_client.structured_output(
                        prompt=disambig_prompt,
                        response_model=EntityDisambiguationOutput,
                        system_prompt="Bạn là trợ lý giải quyết nhập nhằng thực thể (entity disambiguation) chính xác.",
                        temperature=0.0,
                    )

                    chosen = disambig_result.selected_value
                    # Strict validation: verify chosen value is strictly from candidate list
                    if chosen and chosen in unique_candidates_map:
                        chosen_dv = unique_candidates_map[chosen]
                        match_score = next((s for dv, s in combined_candidates if dv.original_value == chosen), 75.0)
                        results.append(
                            EntityLinkResult(
                                mention=mention,
                                table_id=chosen_dv.table_id,
                                column=chosen_dv.column_name,
                                value=chosen_dv.original_value,
                                method="llm",
                                score=round(match_score / 100.0, 3),
                            )
                        )
                        continue
                except Exception as e:
                    logger.warning("LLM entity disambiguation failed: %s", e)

            # If there were multiple high matches but LLM failed, fallback to top high match
            if high_matches:
                best_dv, best_score = high_matches[0]
                results.append(
                    EntityLinkResult(
                        mention=mention,
                        table_id=best_dv.table_id,
                        column=best_dv.column_name,
                        value=best_dv.original_value,
                        method="fuzzy",
                        score=round(best_score / 100.0, 3),
                    )
                )
                continue

            # If no candidates or LLM could not resolve -> mark unlinked
            results.append(
                EntityLinkResult(
                    mention=mention,
                    table_id=default_table_id,
                    column=target_column or "",
                    value=mention,
                    method="unlinked",
                    score=0.0,
                )
            )

        return results
