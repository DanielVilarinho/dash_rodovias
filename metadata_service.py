import pandas as pd
from sqlalchemy import text


def list_tables(engine, schema: str = "public", prefix: str = "antt_") -> list[str]:
    q = text("""
        select table_name
        from information_schema.tables
        where table_schema = :schema
          and table_name like :prefix
        order by table_name
    """)
    df = pd.read_sql_query(q, engine, params={"schema": schema, "prefix": f"{prefix}%"})
    return df["table_name"].tolist()


def list_columns(engine, table_name: str, schema: str = "public") -> list[str]:
    if not table_name:
        return []

    q = text("""
        select column_name
        from information_schema.columns
        where table_schema = :schema
          and table_name = :table_name
        order by ordinal_position
    """)
    df = pd.read_sql_query(q, engine, params={"schema": schema, "table_name": table_name})
    return df["column_name"].tolist()


def find_tables_by_field(engine, field_name: str, schema: str = "public") -> list[str]:
    if not field_name:
        return []

    q = text("""
        select table_name
        from information_schema.columns
        where table_schema = :schema
          and lower(column_name) like :field_name
        order by table_name
    """)
    df = pd.read_sql_query(
        q,
        engine,
        params={"schema": schema, "field_name": f"%{field_name.lower()}%"},
    )
    return df["table_name"].tolist()


def get_table_sample(engine, table_name: str, limit: int = 5) -> list[dict]:
    if not table_name:
        return []

    sql = f'SELECT * FROM public."{table_name}" LIMIT {int(limit)}'
    df = pd.read_sql_query(text(sql), engine)

    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].astype(str)

    return df.to_dict("records")