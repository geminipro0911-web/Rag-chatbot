"""
Catalog Service for Tabular Data.
Manages metadata persistence into PostgreSQL (tables_catalog, columns_catalog, column_values),
triggers LLM for table description + keywords, and orchestrates synthetic few-shot generation
with DuckDB sandbox verification.
"""

from __future__ import annotations

import inspect
import json
import logging
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

import duckdb
import unidecode
from pydantic import BaseModel, Field

from application.interfaces.llm_client import LLMClient
from application.interfaces.embedder import Embedder
from application.services.excel_preprocessor import ProcessedSheet
from infrastructure.database.models import (
    ColumnCatalogModel,
    ColumnValueModel,
    FewShotExampleModel,
    TableCatalogModel,
)
from infrastructure.sandbox.secure_code_executor import validate_duckdb_sql

logger = logging.getLogger(__name__)


class TableDescriptionKeywordsOutput(BaseModel):
    description: str = Field(..., description="Mô tả tóm tắt nội dung bảng từ 2-3 câu bằng tiếng Việt")
    keywords: List[str] = Field(default_factory=list, description="Danh sách từ khóa nghiệp vụ tiếng Việt liên quan")


class FewShotPair(BaseModel):
    question: str = Field(..., description="Câu hỏi nghiệp vụ bằng tiếng Việt")
    sql_query: str = Field(..., description="Câu lệnh DuckDB SQL hợp lệ để trả lời câu hỏi")
    difficulty: str = Field(default="medium", description="Độ khó: easy, medium, hard")


class SyntheticFewShotOutput(BaseModel):
    examples: List[FewShotPair] = Field(default_factory=list, description="Danh sách 5-8 cặp câu hỏi và SQL")


class CatalogService:
    """Manages metadata catalogs, description generation, and verified synthetic few-shot examples."""

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        embedder: Optional[Embedder] = None,
        enable_synthetic_fewshot: bool = True,
    ):
        self.llm_client = llm_client
        self.embedder = embedder
        self.enable_synthetic_fewshot = enable_synthetic_fewshot

    async def generate_table_description_and_keywords(
        self,
        processed_sheet: ProcessedSheet,
    ) -> Tuple[str, List[str]]:
        """Generates 2-3 sentence table summary and business keywords via LLM."""
        if not self.llm_client:
            return (
                f"Bảng dữ liệu {processed_sheet.sheet_name} từ tệp {processed_sheet.source_file}.",
                [processed_sheet.sheet_name],
            )

        schema_summary = []
        for col in processed_sheet.columns_schema:
            sample_str = ", ".join(str(s) for s in col.sample_values[:3])
            schema_summary.append(f"- Cột '{col.original_name}' (alias: {col.column_alias}, kiểu: {col.data_type}): mẫu [{sample_str}]")

        prompt = (
            f"Bạn là chuyên gia phân tích dữ liệu doanh nghiệp.\n"
            f"Hãy đọc thông tin schema của bảng tính sau và viết mô tả tóm tắt (2-3 câu) cùng danh sách từ khóa nghiệp vụ:\n"
            f"Tên tệp: {processed_sheet.source_file}\n"
            f"Tên sheet: {processed_sheet.sheet_name}\n"
            f"Số dòng: {processed_sheet.row_count}\n"
            f"Cột dữ liệu:\n" + "\n".join(schema_summary) + "\n\n"
            f"Yêu cầu:\n"
            f"1. Mô tả rõ mục đích nghiệp vụ của bảng bằng tiếng Việt trang trọng.\n"
            f"2. Đưa ra 5-10 từ khóa nghiệp vụ tiếng Việt liên quan chặt chẽ đến dữ liệu."
        )

        try:
            res: TableDescriptionKeywordsOutput = await self.llm_client.structured_output(
                messages=[
                    {"role": "system", "content": "Bạn là chuyên gia phân tích dữ liệu doanh nghiệp. Hãy trả về JSON đúng schema."},
                    {"role": "user", "content": prompt},
                ],
                response_model=TableDescriptionKeywordsOutput,
                temperature=0.2,
            )
            return res.description, res.keywords
        except Exception as exc:
            logger.warning(f"Failed to generate table description via LLM: {exc}")
            return (
                f"Bảng {processed_sheet.sheet_name} trích xuất từ tệp {processed_sheet.source_file} gồm {processed_sheet.row_count} dòng.",
                [processed_sheet.sheet_name],
            )

    async def generate_and_validate_fewshots(
        self,
        processed_sheet: ProcessedSheet,
        num_target: int = 6,
    ) -> List[Dict[str, Any]]:
        """
        Generates synthetic few-shot QA pairs and verifies each query in DuckDB sandbox.
        Keeps only queries that succeed and return >= 1 row.
        """
        if not self.enable_synthetic_fewshot or not self.llm_client:
            return []

        # Build schema context for LLM
        col_descriptions = []
        clean_sheet_name = unidecode.unidecode(str(processed_sheet.sheet_name))
        table_alias = re.sub(r"[^a-zA-Z0-9_]+", "_", clean_sheet_name).strip("_").lower()
        if not table_alias or table_alias[0].isdigit():
            table_alias = f"tbl_{table_alias}"

        for col in processed_sheet.columns_schema:
            sample_str = ", ".join(str(s) for s in col.sample_values[:3])
            col_descriptions.append(
                f"  - `{col.column_alias}` (Tên gốc: '{col.original_name}', Kiểu: {col.data_type}, Mẫu: [{sample_str}])"
            )

        prompt = (
            f"Bạn là chuyên gia viết truy vấn DuckDB SQL cho cơ sở dữ liệu doanh nghiệp.\n"
            f"Hãy tạo {num_target} cặp (câu hỏi tiếng Việt, truy vấn DuckDB SQL) với độ khó đa dạng:\n"
            f"- Lọc điều kiện (WHERE)\n"
            f"- Gom nhóm & tổng hợp (GROUP BY, SUM, COUNT, AVG)\n"
            f"- Xếp hạng / Top N (ORDER BY ... LIMIT N)\n"
            f"- Theo thời gian (nếu có cột ngày tháng)\n"
            f"- So sánh / tính toán tỷ lệ\n\n"
            f"Tên bảng quy ước: `{table_alias}`\n"
            f"Danh sách các cột (chỉ dùng column_alias trong SQL):\n"
            + "\n".join(col_descriptions)
            + f"\n\nQuy tắc bắt buộc:\n"
            f"1. Chỉ viết câu truy vấn SELECT an toàn, không có INSERT/UPDATE/DELETE/DROP.\n"
            f"2. Tên cột trong SQL phải viết chính xác theo `column_alias`.\n"
            f"3. Dùng các giá trị mẫu thực tế đã cung cấp để đảm bảo điều kiện WHERE trả về dữ liệu.\n"
            f"4. Trả về đúng định dạng JSON danh sách examples."
        )

        try:
            output: SyntheticFewShotOutput = await self.llm_client.structured_output(
                messages=[
                    {"role": "system", "content": "Bạn là chuyên gia tạo synthetic DuckDB SQL. Trả về JSON đúng định dạng."},
                    {"role": "user", "content": prompt},
                ],
                response_model=SyntheticFewShotOutput,
                temperature=0.3,
            )
        except Exception as exc:
            logger.warning(f"LLM synthetic few-shot generation failed: {exc}")
            return []

        # Validate each generated query against the actual Parquet file in DuckDB
        validated_examples: List[Dict[str, Any]] = []

        for pair in output.examples:
            is_valid = self.validate_sql_query(
                sql_query=pair.sql_query,
                parquet_path=processed_sheet.parquet_path,
                table_alias=table_alias,
                table_id=processed_sheet.table_id,
            )
            if is_valid:
                embedding = None
                if self.embedder:
                    try:
                        emb_res = self.embedder.embed_query(pair.question)
                        if inspect.isawaitable(emb_res):
                            emb_res = await emb_res
                        embedding = emb_res.get("dense") if isinstance(emb_res, dict) else emb_res
                    except Exception as e:
                        logger.warning(f"Failed to embed few-shot question: {e}")

                validated_examples.append({
                    "id": str(uuid.uuid4()),
                    "table_id": processed_sheet.table_id,
                    "question": pair.question,
                    "sql_query": pair.sql_query,
                    "language": "sql",
                    "source": "synthetic",
                    "difficulty": pair.difficulty,
                    "embedding": embedding,
                    "is_active": True,
                })
                logger.info(f"Synthetic SQL validated successfully: '{pair.question}'")
            else:
                logger.warning(f"Synthetic SQL failed sandbox check (error or 0 rows returned): {pair.sql_query}")

        return validated_examples

    def validate_sql_query(
        self,
        sql_query: str,
        parquet_path: str,
        table_alias: str,
        table_id: Optional[str] = None,
    ) -> bool:
        """
        Executes SQL query in DuckDB sandbox against the parquet file.
        Returns True only if the query executes without error and returns >= 1 row.
        """
        clean_sql = sql_query.strip().strip(";")
        # Reject non-SELECT queries
        if not re.match(r"^\s*(WITH|SELECT)\b", clean_sql, re.IGNORECASE):
            return False

        escaped_parquet = parquet_path.replace("\\", "/")
        clean_alias = unidecode.unidecode(str(table_alias))
        safe_alias = re.sub(r"[^a-zA-Z0-9_]+", "_", clean_alias).strip("_").lower()
        if not safe_alias or safe_alias[0].isdigit():
            safe_alias = f"tbl_{safe_alias}"

        # If table_alias was passed as UUID with hyphens, wrap in quotes in SQL if unquoted
        if "-" in table_alias and table_alias in clean_sql and f'"{table_alias}"' not in clean_sql:
            clean_sql = clean_sql.replace(table_alias, f'"{table_alias}"')

        if table_id and "-" in table_id and table_id in clean_sql and f'"{table_id}"' not in clean_sql:
            clean_sql = clean_sql.replace(table_id, f'"{table_id}"')

        # Pre-validate SQL syntax & prohibit dangerous commands using sqlglot sandbox validator
        is_syntax_valid, syntax_err = validate_duckdb_sql(clean_sql)
        if not is_syntax_valid:
            logger.debug(f"Synthetic SQL failed sandbox security check: {syntax_err}")
            return False

        try:
            con = duckdb.connect(database=":memory:")
            # Materialize into in-memory tables before locking external access
            con.execute(f'CREATE TABLE "{table_alias}" AS SELECT * FROM read_parquet(\'{escaped_parquet}\');')
            if safe_alias != table_alias:
                con.execute(f'CREATE OR REPLACE VIEW "{safe_alias}" AS SELECT * FROM "{table_alias}";')
            if "data_table" != table_alias:
                con.execute(f'CREATE OR REPLACE VIEW data_table AS SELECT * FROM "{table_alias}";')
            if table_id and table_id != table_alias:
                con.execute(f'CREATE OR REPLACE VIEW "{table_id}" AS SELECT * FROM "{table_alias}";')
                safe_tid = re.sub(r"[^a-zA-Z0-9_]+", "_", table_id).strip("_")
                if safe_tid not in (table_id, table_alias, "data_table"):
                    con.execute(f'CREATE OR REPLACE VIEW "{safe_tid}" AS SELECT * FROM "{table_alias}";')

            # Lock DuckDB configuration & external access now that parquet is loaded in memory
            try:
                con.execute("SET enable_external_access = false;")
                con.execute("SET lock_configuration = true;")
            except Exception:
                pass

            # Execute query
            cursor = con.execute(clean_sql)
            rows = cursor.fetchall()
            con.close()

            # Must return >= 1 row
            return rows is not None and len(rows) >= 1
        except Exception as exc:
            logger.debug(f"DuckDB validation error for query [{sql_query}]: {exc}")
            return False

    def build_orm_entities(
        self,
        processed_sheet: ProcessedSheet,
        description: str,
        keywords: List[str],
        fewshots: List[Dict[str, Any]],
    ) -> Tuple[TableCatalogModel, List[ColumnCatalogModel], List[ColumnValueModel], List[FewShotExampleModel]]:
        """Instantiates SQLAlchemy ORM models ready for database persistence."""
        table_orm = TableCatalogModel(
            id=processed_sheet.table_id,
            file_id=processed_sheet.file_id,
            sheet_name=processed_sheet.sheet_name,
            parquet_path=processed_sheet.parquet_path,
            owner_user_id=processed_sheet.owner_user_id,
            department_id=processed_sheet.department_id,
            is_public=processed_sheet.is_public,
            row_count=processed_sheet.row_count,
            table_description=description,
            business_keywords=keywords,
            warnings=processed_sheet.warnings,
        )

        columns_orm: List[ColumnCatalogModel] = []
        for col in processed_sheet.columns_schema:
            clean_sample_values = []
            for s in col.sample_values:
                if hasattr(s, "isoformat"):
                    clean_sample_values.append(s.isoformat())
                elif hasattr(s, "item"):
                    clean_sample_values.append(s.item())
                else:
                    clean_sample_values.append(s)

            col_orm = ColumnCatalogModel(
                id=str(uuid.uuid4()),
                table_id=processed_sheet.table_id,
                original_name=col.original_name,
                column_alias=col.column_alias,
                data_type=col.data_type,
                sample_values=clean_sample_values,
                min_val=str(col.min_value) if col.min_value is not None else None,
                max_val=str(col.max_value) if col.max_value is not None else None,
                null_ratio=col.null_ratio,
            )
            columns_orm.append(col_orm)

        values_orm: List[ColumnValueModel] = []
        for col_alias, val_list in processed_sheet.distinct_values.items():
            for v in val_list:
                v_orm = ColumnValueModel(
                    id=str(uuid.uuid4()),
                    table_id=processed_sheet.table_id,
                    column_name=col_alias,
                    original_value=v["original_value"],
                    normalized_value=v["normalized_value"],
                    frequency=v["frequency"],
                )
                values_orm.append(v_orm)

        fewshots_orm: List[FewShotExampleModel] = []
        for fs in fewshots:
            fs_orm = FewShotExampleModel(
                id=fs["id"],
                table_id=fs["table_id"],
                question=fs["question"],
                sql_query=fs["sql_query"],
                language=fs["language"],
                source=fs["source"],
                difficulty=fs["difficulty"],
                embedding=fs["embedding"],
                is_active=fs["is_active"],
            )
            fewshots_orm.append(fs_orm)

        return table_orm, columns_orm, values_orm, fewshots_orm
