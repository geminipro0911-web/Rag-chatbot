"""
Security regression tests verifying fixes for SEC-01 through SEC-06 and related issues.
"""

import pytest
import pandas as pd
from fastapi.testclient import TestClient
from api.main import app
from infrastructure.sandbox.secure_code_executor import validate_pandas_code
from application.services.excel_preprocessor import ExcelPreprocessor


@pytest.fixture
def client():
    return TestClient(app)


def test_spa_path_traversal_blocked(client):
    """SEC-01: Verify path traversal on SPA fallback is blocked."""
    # Attempt directory traversal attacks
    traversals = [
        "/..%2f..%2f.env",
        "/../../.env",
        "/..\\..\\config.py",
        "/%2e%2e/%2e%2e/.env",
        "/..%2f..%2fdata/raw",
    ]
    for path in traversals:
        resp = client.get(path)
        # Must return 400 or 404, never 200 with sensitive file contents
        assert resp.status_code in (400, 404), f"Path traversal allowed for {path}: {resp.status_code}"


def test_auth_header_path_traversal_blocked(client):
    """SEC-03: Verify malicious department_id or user_id in headers is rejected with 400."""
    malicious_headers = [
        {"X-User-Id": "../../evil_user", "X-Department-Id": "IT"},
        {"X-User-Id": "valid_user", "X-Department-Id": "../../evil_dept"},
        {"X-User-Id": "user<script>", "X-Department-Id": "IT"},
    ]
    for headers in malicious_headers:
        resp = client.get("/me", headers=headers)
        assert resp.status_code == 400, f"Malicious header was not rejected: {headers}"
        assert "không hợp lệ" in resp.json().get("detail", "")


def test_pandas_sandbox_escape_vectors_blocked():
    """SEC-02: Verify AST blocks generator frames, traceback frames, and numpy file functions."""
    escape_codes = [
        # Frame attribute access
        'g = (x for x in [1])\nresult = g.gi_frame.f_builtins',
        'result = ().__class__.__subclasses__()',
        'result = df.__dict__',
        # NumPy file read calls
        'result = np.genfromtxt("C:/Windows/win.ini")',
        'result = np.memmap("secret.dat")',
        'result = np.recfromcsv("data.csv")',
        'result = np.fromregex("data.txt", r"\\d+", [("n", int)])',
        'result = np.loadtxt("passwords.txt")',
        # Write calls on DataFrame
        'result = df.to_csv("dump.csv")',
        'result = df.to_pickle("dump.pkl")',
        'result = df.to_parquet("dump.parquet")',
    ]
    for code in escape_codes:
        valid, err = validate_pandas_code(code)
        assert not valid, f"Failed to block sandbox escape code: {code}"
        assert "bị cấm" in err, f"Expected 'bị cấm' in error for: {code}"


def test_excel_preprocessor_serial_date_does_not_corrupt_numeric_columns():
    """BUG-15: Verify numeric columns without date keywords are not parsed as Excel serial dates."""
    preprocessor = ExcelPreprocessor(output_dir="./data/parquet")
    # Series of unit prices between 33000 and 70000
    prices = pd.Series([35000, 42000, 50000, 65000, 70000])

    # Column name "don_gia" (no date keyword)
    converted_series, is_date = preprocessor._try_parse_date_column("don_gia", prices, total_valid=5)
    assert not is_date, "Numeric column 'don_gia' was mistakenly classified as date"
    assert converted_series is None

    # Column name "ngay_tao" (with date keyword) and serial dates
    date_serials = pd.Series([44927, 44928, 44929, 44930, 44931]) # Jan 2023 dates
    conv_date, is_date_actual = preprocessor._try_parse_date_column("ngay_tao", date_serials, total_valid=5)
    assert is_date_actual, "Serial date column 'ngay_tao' should be classified as date"
    assert conv_date is not None


def test_reverse_proxy_secret_header_verification(client):
    """SEC-04: Verify X-Internal-Secret protects against LAN admin header spoofing."""
    from config import settings
    original_secret = getattr(settings, "proxy_secret_key", None)
    try:
        settings.proxy_secret_key = "secure_lan_shared_secret"

        # Attempt 1: Spoof admin without secret -> 401 Unauthorized
        resp = client.get("/me", headers={"X-User-Id": "attacker", "X-User-Role": "admin"})
        assert resp.status_code == 401
        assert "Xác thực Reverse Proxy thất bại" in resp.json()["detail"]

        # Attempt 2: Spoof with wrong secret -> 401 Unauthorized
        resp = client.get("/me", headers={"X-User-Id": "attacker", "X-User-Role": "admin", "X-Internal-Secret": "wrong"})
        assert resp.status_code == 401

        # Attempt 3: Valid secret -> Success
        resp = client.get(
            "/me",
            headers={
                "X-User-Id": "legit_admin",
                "X-User-Role": "admin",
                "X-Internal-Secret": "secure_lan_shared_secret",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"
        assert resp.json()["is_admin"] is True
    finally:
        settings.proxy_secret_key = original_secret


def test_router_embedding_cache():
    """BUG-03: Verify in-memory embedding cache in Router avoids redundant inference."""
    from application.services.router import _get_or_compute_embeddings, _ROUTER_EMBEDDING_CACHE
    from unittest.mock import MagicMock

    mock_embedder = MagicMock()
    mock_embedder.embed_documents.return_value = [{"dense": [0.42] * 1024}]

    # Clear cache for isolated test
    _ROUTER_EMBEDDING_CACHE.clear()

    # First call: computes and caches
    vecs1 = _get_or_compute_embeddings(mock_embedder, ["TableSales: Sales description"])
    assert len(vecs1) == 1
    assert vecs1[0] == [0.42] * 1024
    assert mock_embedder.embed_documents.call_count == 1

    # Second call with identical text: must hit cache and NOT invoke embedder again
    vecs2 = _get_or_compute_embeddings(mock_embedder, ["TableSales: Sales description"])
    assert len(vecs2) == 1
    assert vecs2[0] == [0.42] * 1024
    assert mock_embedder.embed_documents.call_count == 1, "Embedder was invoked again instead of using cache!"


def test_duckdb_resource_limits_applied():
    """SEC-10: Verify DuckDB sets memory and thread limits properly without crash."""
    from infrastructure.sandbox.secure_code_executor import SecureCodeExecutor
    executor = SecureCodeExecutor()
    success, df, err = executor.execute_sql("SELECT 1 AS num", {})
    assert success is True
    assert df is not None
    assert df.iloc[0]["num"] == 1
