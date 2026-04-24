import re
import pandas as pd
from sqlalchemy import text


BLOCKED_SQL_PATTERNS = [
    r"\binsert\b",
    r"\bupdate\b",
    r"\bdelete\b",
    r"\bdrop\b",
    r"\balter\b",
    r"\btruncate\b",
    r"\bcreate\b",
    r"\bgrant\b",
    r"\brevoke\b",
]


def preview_table(engine, table_name: str, limit: int = 100) -> pd.DataFrame:
    if not table_name:
        return pd.DataFrame()

    sql = f'SELECT * FROM public."{table_name}" LIMIT {int(limit)}'
    df = pd.read_sql_query(text(sql), engine)

    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].astype(str)

    return df


def is_safe_select_sql(sql: str) -> bool:
    if not sql:
        return False

    cleaned = sql.strip().lower()

    if not cleaned.startswith("select"):
        return False

    for pattern in BLOCKED_SQL_PATTERNS:
        if re.search(pattern, cleaned):
            return False

    return True


def run_safe_sql(engine, sql: str, limit: int = 200) -> pd.DataFrame:
    if not is_safe_select_sql(sql):
        raise ValueError("A query deve ser apenas SELECT.")

    wrapped_sql = f"SELECT * FROM ({sql}) AS t LIMIT {int(limit)}"
    df = pd.read_sql_query(text(wrapped_sql), engine)

    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].astype(str)

    return df