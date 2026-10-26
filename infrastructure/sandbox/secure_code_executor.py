"""
Secure Code Executor Implementation.
Implements CodeExecutor interface with:
- Dual-layer defense for DuckDB: sqlglot AST verification & in-memory locked connection.
- Multi-layer defense for Pandas: AST whitelist, restricted builtins, and isolated subprocess sandbox
  with 15s hard timeout and OS memory constraints (setrlimit / Win32 Job Object).
"""

from __future__ import annotations

import ast
import logging
import multiprocessing as mp
import os
import sys
import traceback
from typing import Any, Dict, List, Optional, Tuple

import duckdb
import pandas as pd
import sqlglot
from sqlglot import exp

from config import settings
from application.interfaces.code_executor import CodeExecutor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SQL AST Security Validation
# ---------------------------------------------------------------------------

PROHIBITED_SQL_ROOT_NAMES = {
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "create",
    "command",
    "pragma",
    "copy",
    "attach",
    "detach",
    "install",
    "set",
    "load",
    "export",
    "call",
}

PROHIBITED_SQL_FUNC_NAMES = {
    "read_parquet",
    "read_csv",
    "read_json",
    "read_blob",
    "read_text",
    "read_ndjson",
    "parquet_scan",
    "scan_parquet",
    "glob",
}


def validate_duckdb_sql(query: str) -> Tuple[bool, Optional[str]]:
    """
    Validates DuckDB SQL using sqlglot AST parsing.
    Enforces:
    - Exactly 1 statement.
    - Root statement MUST be SELECT or WITH (exp.Select or exp.Union).
    - Prohibits COPY, ATTACH, INSTALL, LOAD, PRAGMA, SET, EXPORT, DDL, DML.
    - Prohibits file-reading functions (read_*, glob, parquet_scan...).
    """
    if not query or not query.strip():
        return False, "Câu lệnh SQL rỗng."

    try:
        parsed = sqlglot.parse(query, read="duckdb")
    except Exception as e:
        return False, f"Lỗi cú pháp SQL (sqlglot parse error): {e}"

    if len(parsed) == 0:
        return False, "Không tìm thấy câu lệnh SQL hợp lệ."
    if len(parsed) > 1:
        return False, "Chỉ cho phép duy nhất MỘT câu lệnh SQL (chống multi-query injection)."

    stmt = parsed[0]
    if stmt is None:
        return False, "Câu lệnh SQL không hợp lệ."

    # Must be SELECT or UNION (CTE / WITH is wrapped inside Select or Union)
    if not isinstance(stmt, (exp.Select, exp.Union)):
        return False, f"Chỉ cho phép câu lệnh SELECT hoặc WITH. Bị cấm câu lệnh loại: {type(stmt).__name__}"

    # Walk AST nodes
    for node in stmt.walk():
        # Check prohibited expression types
        node_type_name = type(node).__name__.lower()
        if node_type_name in PROHIBITED_SQL_ROOT_NAMES:
            return False, f"Phát hiện cú pháp bị cấm trong sandbox: {type(node).__name__}"

        # Check prohibited file functions
        node_type_name = type(node).__name__.lower()
        if "read" in node_type_name or "scan" in node_type_name or "glob" in node_type_name:
            if not isinstance(node, (exp.Select, exp.From, exp.Table, exp.Literal, exp.Column)):
                return False, f"Hàm truy cập tệp tin bị cấm trong truy vấn: {type(node).__name__}"

        if isinstance(node, (exp.Anonymous, exp.Func)):
            func_name = (node.name or "").lower()
            if func_name in PROHIBITED_SQL_FUNC_NAMES or func_name.startswith("read_"):
                return False, f"Hàm truy cập tệp tin bị cấm trong truy vấn: {func_name}"

    return True, None


# ---------------------------------------------------------------------------
# Pandas AST Security Validation
# ---------------------------------------------------------------------------

ALLOWED_PANDAS_MODULES = {
    "pandas",
    "pd",
    "numpy",
    "np",
    "math",
    "statistics",
    "datetime",
}

BANNED_PANDAS_CALLS = {
    "eval",
    "exec",
    "compile",
    "open",
    "__import__",
    "getattr",
    "setattr",
    "delattr",
    "hasattr",
    "globals",
    "locals",
    "vars",
    "input",
    "breakpoint",
    "exit",
    "quit",
    "help",
    "system",
    "popen",
    "spawn",
    "load",
    "loads",
    "dump",
    "dumps",
    "save",
    "savez",
    "fromfile",
    "genfromtxt",
    "recfromcsv",
    "recfromtxt",
    "memmap",
    "fromregex",
    "loadtxt",
    "to_pickle",
    "to_csv",
    "to_parquet",
    "to_excel",
    "to_sql",
    "to_json",
    "read_csv",
    "read_parquet",
    "read_excel",
    "read_sql",
    "read_json",
}

BANNED_PANDAS_ATTRIBUTES = {
    "io",
    "os",
    "sys",
    "subprocess",
    "shutil",
    "pathlib",
    "ctypes",
    "builtins",
    "_builtins",
    "core",
    "compat",
    "lib",
    "testing",
    "_testing",
    "arrays",
    "plotting",
    "gi_frame",
    "gi_code",
    "cr_frame",
    "cr_code",
    "ag_frame",
    "ag_code",
    "f_builtins",
    "f_globals",
    "f_locals",
    "f_back",
    "f_code",
    "tb_frame",
    "tb_next",
    "func_globals",
    "func_code",
}


def validate_pandas_code(code: str) -> Tuple[bool, Optional[str]]:
    """
    Validates Python Pandas code using AST inspection.
    Enforces:
    - Whitelist imports: pandas, numpy, math, statistics, datetime.
    - Prohibits dunder attribute access (__*__).
    - Prohibits file I/O methods (read_*, to_* except safe transformations).
    - Prohibits dangerous builtins/calls: eval, exec, compile, open, getattr, globals, etc.
    - Requires assignment to variable 'result'.
    """
    if not code or not code.strip():
        return False, "Đoạn mã Python rỗng."

    try:
        tree = ast.parse(code)
    except Exception as e:
        return False, f"Lỗi cú pháp Python (SyntaxError): {e}"

    has_result_assign = False

    for node in ast.walk(tree):
        # 1. Imports check
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod_root = alias.name.split(".")[0]
                if mod_root not in ALLOWED_PANDAS_MODULES:
                    return False, f"Thư viện bị cấm import: '{alias.name}'. Chỉ cho phép: pandas, numpy, math, statistics, datetime."
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mod_root = node.module.split(".")[0]
                if mod_root not in ALLOWED_PANDAS_MODULES:
                    return False, f"Thư viện bị cấm import from: '{node.module}'. Chỉ cho phép: pandas, numpy, math, statistics, datetime."

        # 2. Attribute access checks
        if isinstance(node, ast.Attribute):
            attr_name = node.attr
            if attr_name.startswith("_"):
                return False, f"Truy cập thuộc tính nội bộ dunder/private bị cấm: '{attr_name}'"
            if attr_name in BANNED_PANDAS_ATTRIBUTES:
                return False, f"Truy cập thuộc tính bị cấm trong sandbox: '{attr_name}'"
            if attr_name.startswith("read_"):
                return False, f"Hàm đọc file bị cấm trong sandbox: '{attr_name}()'"
            if attr_name.startswith("to_") and attr_name not in {
                "to_datetime", "to_numeric", "to_frame", "to_dict", "to_list", "to_numpy", "to_string"
            }:
                return False, f"Phương thức xuất file bị cấm trong sandbox: '{attr_name}()'"

        # 3. Banned function / method calls
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
                if func_name in BANNED_PANDAS_CALLS:
                    return False, f"Hàm bị cấm thực thi trong sandbox: '{func_name}()'"
            elif isinstance(node.func, ast.Attribute):
                method_name = node.func.attr
                if method_name in BANNED_PANDAS_CALLS:
                    return False, f"Phương thức bị cấm thực thi trong sandbox: '{method_name}()'"

        # 4. Check for assignment to 'result'
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "result":
                    has_result_assign = True
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "result":
                has_result_assign = True

    if not has_result_assign:
        return False, "Code bắt buộc phải gán kết quả đầu ra vào biến 'result'."

    return True, None


# ---------------------------------------------------------------------------
# Multiprocessing Worker for Pandas Isolated Subprocess
# ---------------------------------------------------------------------------

def _run_pandas_sandbox_worker(
    code: str,
    dataframes: Dict[str, pd.DataFrame],
    queue: Any,
    max_ram_mb: int,
) -> None:
    """Worker process executing sandboxed Pandas code."""
    try:
        # Apply Linux resource limit if available
        if sys.platform != "win32":
            try:
                import resource
                max_bytes = max_ram_mb * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (max_bytes, max_bytes))
            except Exception as e:
                logger.debug("Could not set RLIMIT_AS: %s", e)

        # Safe __import__ restricted strictly to allowed modules
        def safe_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> Any:
            root_mod = name.split(".")[0]
            if root_mod not in ALLOWED_PANDAS_MODULES:
                raise ImportError(f"Thư viện bị cấm import trong sandbox: '{name}'")
            return __import__(name, globals, locals, fromlist, level)

        # Restricted builtins
        restricted_builtins = {
            "__import__": safe_import,
            "abs": abs,
            "round": round,
            "min": min,
            "max": max,
            "sum": sum,
            "len": len,
            "range": range,
            "enumerate": enumerate,
            "zip": zip,
            "map": map,
            "filter": filter,
            "sorted": sorted,
            "reversed": reversed,
            "bool": bool,
            "int": int,
            "float": float,
            "str": str,
            "list": list,
            "dict": dict,
            "set": set,
            "tuple": tuple,
            "isinstance": isinstance,
            "issubclass": issubclass,
            "None": None,
            "True": True,
            "False": False,
            "print": lambda *args, **kwargs: None,
        }

        import datetime
        import math
        import numpy as np
        import statistics

        # Disable I/O methods on pd and np in subprocess
        for attr in [
            "read_csv", "read_parquet", "read_excel", "read_sql", "read_json",
            "read_html", "read_clipboard", "read_feather", "read_orc", "read_table",
            "to_pickle", "to_csv", "to_parquet", "to_excel", "to_sql", "to_json",
            "to_hdf", "to_feather", "io"
        ]:
            if hasattr(pd, attr):
                try:
                    delattr(pd, attr)
                except Exception:
                    pass

        for df_cls in [pd.DataFrame, pd.Series]:
            for attr in [
                "to_csv", "to_parquet", "to_excel", "to_sql", "to_json",
                "to_pickle", "to_hdf", "to_feather", "to_stata", "to_xml"
            ]:
                if hasattr(df_cls, attr):
                    try:
                        delattr(df_cls, attr)
                    except Exception:
                        pass

        for attr in [
            "load", "save", "savez", "loadtxt", "fromfile", "frombuffer",
            "genfromtxt", "recfromcsv", "recfromtxt", "memmap", "fromregex"
        ]:
            if hasattr(np, attr):
                try:
                    delattr(np, attr)
                except Exception:
                    pass

        safe_globals = {
            "__builtins__": restricted_builtins,
            "pd": pd,
            "pandas": pd,
            "np": np,
            "numpy": np,
            "math": math,
            "statistics": statistics,
            "datetime": datetime,
            **dataframes,
        }

        # Execute code in isolated namespace
        exec(code, safe_globals)

        if "result" not in safe_globals:
            queue.put((False, None, "Code không gán giá trị vào biến 'result'."))
            return

        result = safe_globals["result"]

        # Normalize result to pandas DataFrame
        if hasattr(result, "item") and not isinstance(result, (pd.DataFrame, pd.Series)):
            val = result.item()
        else:
            val = result

        if isinstance(val, pd.Series):
            result_df = val.to_frame()
        elif isinstance(val, pd.DataFrame):
            result_df = val
        elif isinstance(val, list):
            if val and isinstance(val[0], dict):
                result_df = pd.DataFrame(val)
            else:
                result_df = pd.DataFrame({"result": val})
        elif isinstance(val, dict):
            result_df = pd.DataFrame([val])
        else:
            result_df = pd.DataFrame({"result": [val]})

        queue.put((True, result_df, None))

    except Exception as e:
        tb_lines = traceback.format_exc().strip().split("\n")
        last_tb = "\n".join(tb_lines[-10:])
        queue.put((False, None, f"{type(e).__name__}: {e}\n{last_tb}"))


# ---------------------------------------------------------------------------
# Secure Code Executor Implementation
# ---------------------------------------------------------------------------

class SecureCodeExecutor(CodeExecutor):
    """
    Secure execution engine for DuckDB SQL and Pandas code.
    Enforces AST security, process isolation, memory limits, and timeouts.
    """

    def __init__(self, memory_limit_mb: int = 512, default_timeout_seconds: int = 15):
        self.memory_limit_mb = memory_limit_mb
        self.default_timeout_seconds = default_timeout_seconds

    def execute_sql(
        self,
        query: str,
        table_parquet_mapping: Dict[str, str],
        max_rows: int = 10000,
    ) -> Tuple[bool, Optional[pd.DataFrame], Optional[str]]:
        """
        Executes a validated DuckDB SQL query in an in-memory connection
        with strict configuration lockdown.
        """
        # 1. AST Validation
        valid, err = validate_duckdb_sql(query)
        if not valid:
            logger.warning("DuckDB query failed AST security check: %s", err)
            return False, None, err

        con: Optional[duckdb.DuckDBPyConnection] = None
        try:
            # 2. In-memory connection & Early Resource Limits
            con = duckdb.connect(":memory:")
            threads = getattr(settings, "duckdb_threads", 4)
            max_mem = getattr(settings, "duckdb_max_memory", "2GB")
            con.execute(f"SET threads={threads};")
            con.execute(f"SET max_memory='{max_mem}';")

            # 3. Register authorized parquet tables (materialize once per file, alias via VIEW)
            primary_table_by_path: Dict[str, str] = {}
            for table_name, parquet_path in table_parquet_mapping.items():
                if not os.path.exists(parquet_path):
                    logger.warning("Parquet file not found: %s", parquet_path)
                    return False, None, f"Tệp dữ liệu bảng '{table_name}' không tồn tại: {parquet_path}"

                safe_path = os.path.abspath(parquet_path).replace("\\", "/").replace("'", "''")
                escaped_tname = str(table_name).replace('"', '""')
                if safe_path not in primary_table_by_path:
                    con.execute(
                        f'CREATE OR REPLACE TABLE "{escaped_tname}" AS SELECT * FROM read_parquet(\'{safe_path}\')'
                    )
                    primary_table_by_path[safe_path] = escaped_tname
                else:
                    primary_tname = primary_table_by_path[safe_path]
                    if escaped_tname != primary_tname:
                        con.execute(
                            f'CREATE OR REPLACE VIEW "{escaped_tname}" AS SELECT * FROM "{primary_tname}"'
                        )

            # 4. Strict Security Lockdown
            con.execute("SET enable_external_access=false;")
            con.execute("SET lock_configuration=true;")

            # 5. Execute query
            rel = con.sql(query)
            # Fetch up to max_rows + 1 to detect overflow
            df = rel.limit(max_rows + 1).df()

            if len(df) > max_rows:
                logger.warning("Query returned %d rows; truncating to %d max_rows", len(df), max_rows)
                df = df.iloc[:max_rows]

            return True, df, None

        except Exception as e:
            tb_lines = traceback.format_exc().strip().split("\n")
            last_tb = "\n".join(tb_lines[-8:])
            err_msg = f"{type(e).__name__}: {e}\n{last_tb}"
            logger.warning("DuckDB execution error: %s", err_msg)
            return False, None, err_msg

        finally:
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass

    def execute_pandas(
        self,
        code: str,
        dataframes: Dict[str, pd.DataFrame],
        timeout_seconds: Optional[int] = None,
        max_ram_mb: Optional[int] = None,
    ) -> Tuple[bool, Optional[pd.DataFrame], Optional[str]]:
        """
        Executes sandboxed Pandas code in an isolated spawned process
        with hard timeout and memory constraints.
        """
        timeout = timeout_seconds or self.default_timeout_seconds
        ram_mb = max_ram_mb or self.memory_limit_mb

        # 1. AST Validation
        valid, err = validate_pandas_code(code)
        if not valid:
            logger.warning("Pandas code failed AST security check: %s", err)
            return False, None, err

        # 2. Spawning isolated subprocess
        try:
            ctx = mp.get_context("spawn")
            queue = ctx.Queue()

            process = ctx.Process(
                target=_run_pandas_sandbox_worker,
                args=(code, dataframes, queue, ram_mb),
            )
            process.start()

            # Apply Windows Job Object memory constraint if running on Windows
            if sys.platform == "win32":
                try:
                    import win32api
                    import win32con
                    import win32job

                    job = win32job.CreateJobObject(None, "")
                    job_info = win32job.QueryInformationJobObject(
                        job, win32job.JobObjectExtendedLimitInformation
                    )
                    job_info["ProcessMemoryLimit"] = ram_mb * 1024 * 1024
                    job_info["BasicLimitInformation"]["LimitFlags"] |= (
                        win32job.JOB_OBJECT_LIMIT_PROCESS_MEMORY
                    )
                    win32job.SetInformationJobObject(
                        job, win32job.JobObjectExtendedLimitInformation, job_info
                    )
                    proc_handle = win32api.OpenProcess(
                        win32con.PROCESS_ALL_ACCESS, False, process.pid
                    )
                    win32job.AssignProcessToJobObject(job, proc_handle)
                except Exception as win_err:
                    logger.debug("Could not assign Windows Job Object memory limit: %s", win_err)

            process.join(timeout)

            # Check if process timed out
            if process.is_alive():
                logger.warning("Pandas worker exceeded %d seconds timeout, killing process...", timeout)
                process.terminate()
                process.kill()
                process.join(1)
                return False, None, f"Thực thi quá thời gian cho phép ({timeout} giây - Timeout kill)."

            # Retrieve result from queue
            if not queue.empty():
                success, result_df, err_msg = queue.get_nowait()
                return success, result_df, err_msg
            else:
                # Process exited without returning data (e.g. killed by OOM)
                exitcode = process.exitcode
                return False, None, f"Tiến trình bị ngắt đột ngột (Exit code: {exitcode}, có thể do vượt quá giới hạn RAM {ram_mb}MB)."

        except Exception as e:
            return False, None, f"Lỗi khởi chạy tiến trình sandbox: {e}"
