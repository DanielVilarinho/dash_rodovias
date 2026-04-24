import re
import unicodedata
import pandas as pd
from sqlalchemy import text


def normalize_legacy_text(value: str) -> str:
    value = str(value or "").replace("ç", "c").replace("Ç", "C")
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value


def sanitize_table_name(name: str) -> str:
    s = normalize_legacy_text(name).strip().lower()
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^a-z0-9_]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def get_resource_metadata(engine) -> pd.DataFrame:
    q = text("""
        select
            id_recurso,
            recurso_name,
            recurso_description
        from public."antt_antt_recursos_dim"
    """)
    df = pd.read_sql_query(q, engine)
    if df.empty:
        return df

    df["recurso_name_tratado"] = df["recurso_name"].apply(sanitize_table_name)
    return df


def get_table_dictionary(engine, table_name: str) -> pd.DataFrame:
    if not table_name:
        return pd.DataFrame()

    recursos = get_resource_metadata(engine)
    if recursos.empty:
        return pd.DataFrame()

    table_name_tratada = sanitize_table_name(table_name.replace("antt_", "", 1))
    match = recursos[recursos["recurso_name_tratado"] == table_name_tratada].copy()

    if match.empty:
        return pd.DataFrame()

    id_recurso = match.iloc[0]["id_recurso"]

    q = text("""
        select *
        from public."antt_antt_dicionarios_campos"
        where id_recurso = :id_recurso
    """)
    df = pd.read_sql_query(q, engine, params={"id_recurso": id_recurso})
    return df


def get_table_description(engine, table_name: str) -> str:
    if not table_name:
        return ""

    recursos = get_resource_metadata(engine)
    if recursos.empty:
        return ""

    table_name_tratada = sanitize_table_name(table_name.replace("antt_", "", 1))
    match = recursos[recursos["recurso_name_tratado"] == table_name_tratada].copy()

    if match.empty:
        return ""

    return str(match.iloc[0].get("recurso_description") or "").strip()