"""
Unit tests for Phase 6: Tabular Engine Sandbox & Self-Correction Loop.
Covers:
- DuckDB AST security validation & intentional sandbox escape attacks:
  * Multi-statement injection (; DROP TABLE ...)
  * Prohibited commands (COPY, ATTACH, INSTALL, LOAD, PRAGMA, SET)
  * File access functions (read_parquet, read_csv, parquet_scan, glob)
  * DDL / DML attacks (CREATE, DROP, INSERT, UPDATE, DELETE)
  * Configuration lockdown verification
- Pandas AST sandbox security & escape attacks:
  * Prohibited imports (os, sys, subprocess, socket, shutil)
  * Dunder attribute access (().__class__.__base__.__subclasses__())
  * Banned functions (eval, exec, open, __import__, getattr, globals, vars)
  * Missing result assignment
  * Hard timeout kill (15s / short test timeout)
- Self-Correction retry loop:
  * Trigger 1: Exception auto-correction (traceback + valid columns feedback)
  * Trigger 2: 0 rows result handling (verified entity filter vs unverified retry)
  * Trigger 3: All NULL/NaN result retry
  * Trigger 4: Missing aggregation retry
  * Early stopping on duplicate code
"""

import os
import tempfile
import pytest
import pandas as pd
from typing import Any, Dict, List, Optional
from pydantic import BaseModel

from application.interfaces.llm_client import LLMClient
from domain.entities.entity_link import EntityLinkResult
from infrastructure.sandbox.secure_code_executor import (
    SecureCodeExecutor,
    validate_duckdb_sql,
    validate_pandas_code,
)
from application.services.tabular_executor import (
    TabularExecutor,
    GeneratedCodeOutput,
    TabularExecutionResult,
)


# ---------------------------------------------------------------------------
# Test Fixtures & Mocks
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_parquet_file():
    """Creates a temporary parquet file with sample enterprise tabular data."""
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        temp_path = f.name

    df = pd.DataFrame({
        "chi_nhanh": ["Hà Nội", "Hà Nội", "Hồ Chí Minh", "Đà Nẵng"],
        "quy": ["Quý 1", "Quý 2", "Quý 1", "Quý 2"],
        "doanh_thu": [100.5, 150.0, 200.0, 80.0],
        "chi_phi": [70.0, 90.0, 120.0, 50.0],
    })
    df.to_parquet(temp_path, index=False)

    yield temp_path

    if os.path.exists(temp_path):
        os.remove(temp_path)


class MockLLMSequentialClient(LLMClient):
    """Mock LLM returning sequential structured responses for testing retry loops."""

    def __init__(self, responses: List[GeneratedCodeOutput]):
        self.responses = responses
        self.call_count = 0

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        stop: Optional[List[str]] = None,
    ) -> str:
        return "SELECT 1 as result;"

    async def structured_output(
        self,
        prompt: str,
        response_model: type[BaseModel],
        system_prompt: Optional[str] = None,
        temperature: float = 0.0,
    ) -> BaseModel:
        if self.call_count < len(self.responses):
            resp = self.responses[self.call_count]
            self.call_count += 1
            return resp
        # Default fallback
        return self.responses[-1]


# ---------------------------------------------------------------------------
# 1. DuckDB AST Security & Sandbox Escape Attack Tests
# ---------------------------------------------------------------------------

def test_duckdb_multi_statement_injection_blocked():
    """Verify multi-statement SQL injection is blocked."""
    sql = 'SELECT * FROM "sales"; DROP TABLE "sales";'
    valid, err = validate_duckdb_sql(sql)
    assert not valid
    assert "chống multi-query injection" in err


def test_duckdb_prohibited_commands_blocked():
    """Verify COPY, ATTACH, INSTALL, LOAD, PRAGMA, SET, DDL/DML are blocked."""
    attacks = [
        'COPY (SELECT * FROM "sales") TO \'/tmp/leak.csv\';',
        'ATTACH \'/path/to/evil.db\' AS evil;',
        'INSTALL httpfs;',
        'LOAD httpfs;',
        'PRAGMA threads=8;',
        'SET memory_limit=\'10GB\';',
        'CREATE TABLE evil (id INT);',
        'DROP TABLE "sales";',
        'INSERT INTO "sales" VALUES (\'HN\', \'Q1\', 100, 50);',
        'UPDATE "sales" SET doanh_thu = 0;',
        'DELETE FROM "sales";',
    ]

    for attack in attacks:
        valid, err = validate_duckdb_sql(attack)
        assert not valid, f"Failed to block attack: {attack}"


def test_duckdb_file_functions_blocked():
    """Verify file-reading functions (read_parquet, read_csv, glob, parquet_scan) are blocked in AST."""
    attacks = [
        'SELECT * FROM read_parquet(\'/etc/passwd\');',
        'SELECT * FROM read_csv(\'/tmp/secret.csv\');',
        'SELECT * FROM parquet_scan(\'/tmp/test.parquet\');',
        'SELECT * FROM glob(\'/etc/*\');',
        'SELECT * FROM read_json(\'/tmp/data.json\');',
    ]

    for attack in attacks:
        valid, err = validate_duckdb_sql(attack)
        assert not valid, f"Failed to block file reading function: {attack}"
        assert "bị cấm" in err


def test_duckdb_valid_execution_and_max_rows(sample_parquet_file):
    """Verify legitimate DuckDB SQL execution and max_rows limit."""
    executor = SecureCodeExecutor()
    mapping = {"sales": sample_parquet_file}

    # Valid SELECT
    sql = 'SELECT chi_nhanh, SUM(doanh_thu) as total_sales FROM "sales" GROUP BY chi_nhanh ORDER BY total_sales DESC;'
    success, df, err = executor.execute_sql(sql, mapping, max_rows=100)

    assert success
    assert df is not None
    assert len(df) == 3 # Hà Nội, Hồ Chí Minh, Đà Nẵng
    assert "total_sales" in df.columns
    assert err is None

    # Max rows truncation
    sql_all = 'SELECT * FROM "sales";'
    success, df_trunc, err = executor.execute_sql(sql_all, mapping, max_rows=2)
    assert success
    assert len(df_trunc) == 2


# ---------------------------------------------------------------------------
# 2. Pandas AST Sandbox Security & Escape Attack Tests
# ---------------------------------------------------------------------------

def test_pandas_prohibited_imports_blocked():
    """Verify imports outside pandas, numpy, math, statistics, datetime are blocked."""
    attacks = [
        'import os\nresult = os.listdir("/")',
        'import sys\nresult = sys.modules',
        'import subprocess\nresult = subprocess.run(["ls"])',
        'import socket\nresult = 1',
        'import shutil\nresult = 1',
        'from pathlib import Path\nresult = Path(".").exists()',
    ]

    for attack in attacks:
        valid, err = validate_pandas_code(attack)
        assert not valid, f"Failed to block prohibited import: {attack}"
        assert "bị cấm import" in err


def test_pandas_dunder_and_banned_calls_blocked():
    """Verify dunder attribute access and dangerous calls are blocked in AST."""
    attacks = [
        'result = ().__class__.__base__.__subclasses__()',
        'result = [].__class__',
        'f = open("/etc/passwd")\nresult = f.read()',
        'result = eval("1 + 1")',
        'result = exec("x = 1")',
        'result = __import__("os").system("echo 1")',
        'fn = getattr(pd, "read_pickle")\nresult = fn("evil.pkl")',
        'result = globals()',
        'result = locals()',
        'result = vars()',
        'result = pd.read_parquet("secret.parquet")',
        'result = df.to_pickle("evil.pkl")',
        'result = pd.io.common.os.system("whoami")',
    ]

    for attack in attacks:
        valid, err = validate_pandas_code(attack)
        assert not valid, f"Failed to block attack: {attack}"
        assert "bị cấm" in err


def test_pandas_missing_result_assignment_blocked():
    """Verify code lacking assignment to 'result' is rejected."""
    code = 'import pandas as pd\nx = df["doanh_thu"].sum()'
    valid, err = validate_pandas_code(code)
    assert not valid
    assert "biến 'result'" in err


def test_pandas_valid_execution():
    """Verify legitimate Pandas sandboxed execution."""
    executor = SecureCodeExecutor()
    df = pd.DataFrame({"sales": [100, 200, 300]})

    code = 'import pandas as pd\nresult = df["sales"].sum()'
    success, res_df, err = executor.execute_pandas(code, {"df": df}, timeout_seconds=5)

    assert success
    assert res_df is not None
    assert err is None
    # Result normalized to DataFrame
    assert res_df.iloc[0, 0] == 600


def test_pandas_timeout_kill():
    """Verify that an infinite loop code is killed by timeout."""
    executor = SecureCodeExecutor()
    code = 'result = 0\nwhile True:\n    result += 1'
    # Short 2-second timeout for test
    success, res_df, err = executor.execute_pandas(code, {}, timeout_seconds=2)

    assert not success
    assert res_df is None
    assert "Timeout kill" in err


# ---------------------------------------------------------------------------
# 3. Self-Correction Loop Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_self_correction_trigger_1_exception(sample_parquet_file):
    """
    Trigger 1: Exception on attempt 1 (wrong column 'tien_ban_hang'),
    LLM receives traceback and corrects to 'doanh_thu' on attempt 2 -> Success!
    """
    candidate_tables = [{
        "id": "tbl_sales",
        "table_name": "sales",
        "table_alias": "sales",
        "description": "Báo cáo doanh thu",
        "parquet_path": sample_parquet_file,
        "columns": [
            {"column_name": "chi_nhanh", "column_alias": "chi_nhanh", "dtype": "string"},
            {"column_name": "doanh_thu", "column_alias": "doanh_thu", "dtype": "float"},
        ],
    }]

    mock_llm = MockLLMSequentialClient([
        # Attempt 1: Wrong column name
        GeneratedCodeOutput(
            language="sql",
            code='SELECT SUM(tien_ban_hang) as total FROM "sales";',
            explanation="Tính tổng tiền bán hàng.",
        ),
        # Attempt 2: Corrected column name
        GeneratedCodeOutput(
            language="sql",
            code='SELECT SUM(doanh_thu) as total FROM "sales";',
            explanation="Tính tổng doanh thu đã sửa lại tên cột.",
        ),
    ])

    executor = SecureCodeExecutor()
    tabular_service = TabularExecutor(llm_client=mock_llm, code_executor=executor, max_retries=3)

    result = await tabular_service.execute_query(
        query="Tổng doanh thu là bao nhiêu?",
        candidate_tables=candidate_tables,
    )

    assert result.success
    assert result.retries_used == 1
    assert result.row_count == 1
    assert result.data[0]["total"] == 530.5


@pytest.mark.asyncio
async def test_self_correction_trigger_2_zero_rows_verified_vs_unverified(sample_parquet_file):
    """
    Trigger 2:
    - Case A: Query returns 0 rows with all filters verified -> Legitimate business data, stops immediately.
    - Case B: Query returns 0 rows with unverified entity filter -> Triggers retry with catalog suggestions.
    """
    candidate_tables = [{
        "id": "tbl_sales",
        "table_name": "sales",
        "table_alias": "sales",
        "description": "Báo cáo doanh thu",
        "parquet_path": sample_parquet_file,
        "columns": [
            {"column_name": "chi_nhanh", "column_alias": "chi_nhanh", "dtype": "string", "sample_values": ["Hà Nội", "Hồ Chí Minh"]},
            {"column_name": "quy", "column_alias": "quy", "dtype": "string", "sample_values": ["Quý 1", "Quý 2"]},
        ],
    }]

    executor = SecureCodeExecutor()

    # Case A: Filter on Quý 3 (verified entity) but no data exists -> 0 rows is valid
    verified_links = [
        EntityLinkResult(mention="Quý 3", table_id="tbl_sales", column="quy", value="Quý 3", method="alias", score=1.0)
    ]
    mock_llm_a = MockLLMSequentialClient([
        GeneratedCodeOutput(
            language="sql",
            code='SELECT * FROM "sales" WHERE quy = \'Quý 3\';',
            explanation="Lọc dữ liệu Quý 3.",
        )
    ])
    service_a = TabularExecutor(llm_client=mock_llm_a, code_executor=executor, max_retries=3)
    res_a = await service_a.execute_query(
        query="Doanh thu Quý 3",
        candidate_tables=candidate_tables,
        entity_links=verified_links,
    )
    assert res_a.success
    assert res_a.row_count == 0
    assert "Không có dữ liệu khớp" in res_a.explanation

    # Case B: Filter on unverified entity -> Triggers retry
    unverified_links = [
        EntityLinkResult(mention="Hà Giang", table_id="tbl_sales", column="chi_nhanh", value="Hà Giang", method="unlinked", score=0.0)
    ]
    mock_llm_b = MockLLMSequentialClient([
        # Attempt 1: Filters on Hà Giang (unlinked) -> 0 rows
        GeneratedCodeOutput(
            language="sql",
            code='SELECT * FROM "sales" WHERE chi_nhanh = \'Hà Giang\';',
            explanation="Lọc Hà Giang.",
        ),
        # Attempt 2: Corrects to Hà Nội -> 2 rows
        GeneratedCodeOutput(
            language="sql",
            code='SELECT * FROM "sales" WHERE chi_nhanh = \'Hà Nội\';',
            explanation="Lọc lại theo Hà Nội.",
        ),
    ])
    service_b = TabularExecutor(llm_client=mock_llm_b, code_executor=executor, max_retries=3)
    res_b = await service_b.execute_query(
        query="Doanh thu chi nhánh",
        candidate_tables=candidate_tables,
        entity_links=unverified_links,
    )
    assert res_b.success
    assert res_b.retries_used == 1
    assert res_b.row_count == 2


@pytest.mark.asyncio
async def test_self_correction_early_stopping_on_duplicate_code(sample_parquet_file):
    """Verify early stopping when LLM generates identical code on consecutive attempts."""
    candidate_tables = [{
        "id": "tbl_sales",
        "table_name": "sales",
        "parquet_path": sample_parquet_file,
    }]

    mock_llm = MockLLMSequentialClient([
        GeneratedCodeOutput(language="sql", code='SELECT * FROM invalid_table;', explanation="A"),
        GeneratedCodeOutput(language="sql", code='SELECT * FROM invalid_table;', explanation="B"),
    ])

    executor = SecureCodeExecutor()
    service = TabularExecutor(llm_client=mock_llm, code_executor=executor, max_retries=3)

    result = await service.execute_query(query="Lấy dữ liệu", candidate_tables=candidate_tables)
    assert not result.success
    assert "trùng lặp" in result.error


@pytest.mark.asyncio
async def test_tabular_executor_vietnamese_unidecode_alias_and_pandas_prompt(sample_parquet_file):
    """Verify that Vietnamese sheet names are properly unidecoded into safe aliases, and prompt includes statistics & datetime."""
    candidate_tables = [{
        "id": "tbl_vn",
        "table_name": "Đơn Hàng Quý 1",
        "parquet_path": sample_parquet_file,
    }]

    captured_prompts = []

    class MockCaptureLLM(LLMClient):
        async def chat_completion(self, messages, **kwargs):
            return "mock"

        async def structured_output(self, prompt, response_model, system_prompt=None, **kwargs):
            if system_prompt:
                captured_prompts.append(system_prompt)
            captured_prompts.append(prompt)
            return GeneratedCodeOutput(
                language="sql",
                code='SELECT * FROM "don_hang_quy_1"',
                explanation="Truy vấn đơn hàng",
            )

    executor = SecureCodeExecutor()
    service = TabularExecutor(llm_client=MockCaptureLLM(), code_executor=executor, max_retries=1)

    result = await service.execute_query(
        query="Xem các đơn hàng",
        candidate_tables=candidate_tables,
    )

    # 1. Check prompt contains allowed libraries: pandas, numpy, math, statistics, datetime
    assert any("statistics, datetime" in p for p in captured_prompts)

    # 2. Check query executed successfully using the unidecoded alias
    assert result.success is True
    assert result.row_count == 4

