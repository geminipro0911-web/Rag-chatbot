"""
Code Executor Interface.
Defines abstract contracts for DuckDB SQL execution and sandboxed Pandas code execution.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Tuple, Optional
import pandas as pd


class CodeExecutor(ABC):
    """Abstract interface for secure database and data science code execution."""

    @abstractmethod
    def execute_sql(
        self,
        query: str,
        table_parquet_mapping: Dict[str, str],
        max_rows: int = 10000
    ) -> Tuple[bool, Optional[pd.DataFrame], Optional[str]]:
        """
        Execute validated DuckDB SQL query in a restricted in-memory environment.

        Args:
            query: Single SELECT / WITH query string.
            table_parquet_mapping: Dict of {table_name: parquet_file_path} for allowed tables.
            max_rows: Maximum rows allowed in result.

        Returns:
            Tuple of:
                - success: bool
                - result_df: Optional[pd.DataFrame]
                - error_message: Optional[str]
        """
        pass

    @abstractmethod
    def execute_pandas(
        self,
        code: str,
        dataframes: Dict[str, pd.DataFrame],
        timeout_seconds: int = 15,
        max_ram_mb: int = 512
    ) -> Tuple[bool, Optional[pd.DataFrame], Optional[str]]:
        """
        Execute sandboxed Python Pandas code in an isolated sub-process with memory and timeout limits.

        Args:
            code: Python code string. Must produce variable `result`.
            dataframes: Dict of {df_variable_name: DataFrame} preloaded into the scope.
            timeout_seconds: Hard timeout in seconds (default 15s).
            max_ram_mb: Maximum memory limit in MB (default 512MB).

        Returns:
            Tuple of:
                - success: bool
                - result_df: Optional[pd.DataFrame]
                - error_message: Optional[str]
        """
        pass
