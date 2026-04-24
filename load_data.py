import re
import unicodedata
from functools import lru_cache

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from config import (
    DB_USER,
    DB_PASSWORD,
    DB_HOST,
    DB_PORT,
    DB_NAME,
    TABLE_PREFIX,
    CONTROL_PREFIX,
)

CSV_LAST_COLUMNS = [
    "csv_encoding_used",
    "csv_sep_used",
    "csv_atypical_flags",
]

RESOURCE_DIM_TABLE = "antt_antt_recursos_dim"
DICTIONARY_FIELDS_TABLE = "antt_antt_dicionarios_campos"

_ENGINE = None


def normalize_legacy_text(text: str) -> str:
    text = str(text or "").replace("ç", "c").replace("Ç", "C")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text


def sanitize_table_name(name: str, prefix: str = "") -> str:
    s = normalize_legacy_text(name).strip().lower()
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^a-z0-9_]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    if not s:
        s = "tabela"
    if not re.match(r"^[a-z_]", s):
        s = "_" + s
    return (prefix + s)[:63]


def strip_data_prefix(table_name: str) -> str:
    name = str(table_name or "").strip().lower()
    if name.startswith(TABLE_PREFIX):
        return name[len(TABLE_PREFIX):]
    return name


def get_engine() -> Engine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = create_engine(
            f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}",
            pool_pre_ping=True,
        )
    return _ENGINE


def list_antt_tables(engine: Engine) -> tuple[list[str], list[str]]:
    query = text("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name LIKE :table_prefix
        ORDER BY table_name
    """)

    df = pd.read_sql_query(query, engine, params={"table_prefix": f"{TABLE_PREFIX}%"})
    all_tables = df["table_name"].tolist()

    control_tables = [t for t in all_tables if t.startswith(CONTROL_PREFIX)]
    data_tables = [t for t in all_tables if not t.startswith(CONTROL_PREFIX)]

    return data_tables, control_tables


@lru_cache(maxsize=256)
def _get_table_total_rows_cached(table_name: str) -> int:
    engine = get_engine()
    query = text(f'SELECT COUNT(*) AS total_rows FROM public."{table_name}"')
    with engine.begin() as conn:
        result = conn.execute(query).scalar()
    return int(result or 0)


def get_table_total_rows(engine: Engine, table_name: str) -> int:
    if not table_name:
        return 0
    return _get_table_total_rows_cached(table_name)


def reorder_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    cols = list(df.columns)
    last_cols_existing = [c for c in CSV_LAST_COLUMNS if c in cols]
    normal_cols = [c for c in cols if c not in last_cols_existing]

    return df[normal_cols + last_cols_existing]


def _query_table(table_name: str, limit: int | None = None) -> pd.DataFrame:
    engine = get_engine()
    sql = f'SELECT * FROM public."{table_name}"'
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    df = pd.read_sql_query(text(sql), engine)
    return reorder_columns(df)


@lru_cache(maxsize=128)
def _load_small_table_cached(table_name: str) -> pd.DataFrame:
    df = _query_table(table_name, limit=None)
    return df.copy()


def load_table(engine: Engine, table_name: str, limit: int | None = None) -> pd.DataFrame:
    if not table_name:
        return pd.DataFrame()

    total_rows = get_table_total_rows(engine, table_name)

    if total_rows <= 1000:
        df = _load_small_table_cached(table_name).copy()
        if limit is not None:
            return df.head(limit).copy()
        return df

    return _query_table(table_name, limit=limit)


def get_table_columns(engine: Engine, table_name: str) -> list[str]:
    if not table_name:
        return []

    query = text("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = :table_name
        ORDER BY ordinal_position
    """)

    df = pd.read_sql_query(query, engine, params={"table_name": table_name})
    cols = df["column_name"].tolist()
    last_cols_existing = [c for c in CSV_LAST_COLUMNS if c in cols]
    normal_cols = [c for c in cols if c not in last_cols_existing]
    return normal_cols + last_cols_existing


def dataframe_for_dash(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    df = df.copy()

    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].astype(str)
        elif pd.api.types.is_object_dtype(df[col]):
            df[col] = df[col].astype(str)

    df = df.fillna("")
    df = reorder_columns(df)
    return df


def get_resource_dim(engine: Engine) -> pd.DataFrame:
    query = text(f'''
        SELECT *
        FROM public."{RESOURCE_DIM_TABLE}"
    ''')

    try:
        df = pd.read_sql_query(query, engine)
    except Exception:
        return pd.DataFrame()

    if df.empty:
        return df

    if "recurso_name" in df.columns:
        df["recurso_name"] = df["recurso_name"].fillna("").astype(str)

    if "recurso_description" in df.columns:
        df["recurso_description"] = df["recurso_description"].fillna("").astype(str)

    if "recurso_name" in df.columns:
        df["recurso_name_sanitized"] = df["recurso_name"].apply(sanitize_table_name)

    return df


def get_table_metadata_map(engine: Engine, table_names: list[str]) -> dict[str, dict]:
    resource_df = get_resource_dim(engine)
    metadata_map = {
        table_name: {
            "description": "",
            "id_recurso": None,
            "resource_name": "",
        }
        for table_name in table_names
    }

    if resource_df.empty or "recurso_name_sanitized" not in resource_df.columns:
        return metadata_map

    resource_lookup = {}
    for _, row in resource_df.iterrows():
        key = str(row.get("recurso_name_sanitized", "")).strip()
        if not key:
            continue

        resource_lookup[key] = {
            "description": str(row.get("recurso_description", "") or "").strip(),
            "id_recurso": row.get("id_recurso"),
            "resource_name": str(row.get("recurso_name", "") or "").strip(),
        }

    for table_name in table_names:
        stripped_name = strip_data_prefix(table_name)
        sanitized_lookup_key = sanitize_table_name(stripped_name)

        if sanitized_lookup_key in resource_lookup:
            metadata_map[table_name] = resource_lookup[sanitized_lookup_key]

    return metadata_map


def get_dictionary_fields_for_table(engine: Engine, table_name: str, metadata_map: dict[str, dict]) -> pd.DataFrame:
    if not table_name:
        return pd.DataFrame()

    table_meta = metadata_map.get(table_name, {})
    id_recurso = table_meta.get("id_recurso")

    if id_recurso is None or (isinstance(id_recurso, float) and pd.isna(id_recurso)):
        return pd.DataFrame()

    query = text(f'''
        SELECT *
        FROM public."{DICTIONARY_FIELDS_TABLE}"
        WHERE id_recurso = :id_recurso
    ''')

    try:
        df = pd.read_sql_query(query, engine, params={"id_recurso": id_recurso})
    except Exception:
        return pd.DataFrame()

    if df.empty:
        return df

    if "Campo" in df.columns:
        df["Campo"] = df["Campo"].fillna("").astype(str)
        df = df.drop_duplicates(subset=["Campo"], keep="first")
        df = df.sort_values(by="Campo", kind="stable").reset_index(drop=True)

    return df