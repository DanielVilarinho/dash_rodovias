import json
import unicodedata
from pathlib import Path

import pandas as pd

from metadata_service import list_tables, list_columns, get_table_sample
from dictionary_service import get_table_dictionary, get_table_description
from load_data import load_table
from shared_logger import get_shared_logger, log_event


logger = get_shared_logger("metadata_catalog_builder")

CATALOG_DIR = Path("cache")
CATALOG_DIR.mkdir(exist_ok=True)

CATALOG_FILE = CATALOG_DIR / "bi_metadata_catalog.json"


def _normalize_text(value: str) -> str:
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text


def _infer_column_tags(columns: list[str]) -> dict:
    cols_lower = [_normalize_text(c) for c in columns]

    lat_candidates = [c for c in cols_lower if "latitude" in c or c == "lat" or c.endswith("_lat")]
    lon_candidates = [c for c in cols_lower if "longitude" in c or c in ("lon", "lng") or c.endswith("_lon")]

    numeric_keywords = [
        "valor", "qtd", "qtde", "count", "total", "km", "score", "idade",
        "quantidade", "velocidade", "extensao", "largura", "n_", "numero",
        "ilesos", "feridos", "mortos", "faixas", "taxa", "volume", "receita",
        "arrecadado", "custo", "peso", "comprimento"
    ]
    date_keywords = [
        "data", "date", "mes_ano", "ano_", "_ano", "ano_de_", "ano_da_",
        "horario", "hora", "periodo", "competencia"
    ]

    stop_false_date = ["id_dataset", "dataset_name", "dataset_link", "dataset_url"]

    date_like = []
    numeric_like = []
    categorical_like = []

    for original, normalized in zip(columns, cols_lower):
        if normalized in stop_false_date:
            categorical_like.append(original)
            continue

        if any(x in normalized for x in date_keywords):
            date_like.append(original)
        elif any(x in normalized for x in numeric_keywords):
            numeric_like.append(original)
        elif "latitude" in normalized or "longitude" in normalized:
            numeric_like.append(original)
        else:
            categorical_like.append(original)

    return {
        "has_lat_lon": bool(lat_candidates and lon_candidates),
        "date_like_columns": date_like[:30],
        "numeric_like_columns": numeric_like[:30],
        "categorical_like_columns": categorical_like[:30],
    }


def _build_dictionary_summary(df_dict: pd.DataFrame) -> list[dict]:
    if df_dict is None or df_dict.empty:
        return []

    cols = df_dict.columns.tolist()
    campo_col = "Campo" if "Campo" in cols else None
    desc_col = None

    for candidate in ["Descrição", "Descricao", "description", "descricao", "Descricao"]:
        if candidate in cols:
            desc_col = candidate
            break

    if not campo_col:
        return []

    temp = df_dict.copy()

    if desc_col:
        temp = temp[[campo_col, desc_col]].drop_duplicates(subset=[campo_col]).copy()
        temp.columns = ["field_name", "field_description"]
    else:
        temp = temp[[campo_col]].drop_duplicates(subset=[campo_col]).copy()
        temp["field_description"] = ""
        temp.columns = ["field_name", "field_description"]

    return temp.head(200).to_dict("records")


def _get_volume_info(engine, table_name: str, resource_inventory_df: pd.DataFrame | None = None) -> dict:
    if resource_inventory_df is None or resource_inventory_df.empty:
        return {"size_mb": None, "matched_recurso_name": None}

    temp = resource_inventory_df.copy()
    temp["recurso_name_norm"] = temp["recurso_name"].apply(_normalize_text)
    table_norm = _normalize_text(table_name.replace("antt_", "").replace("_", " "))

    exact = temp[temp["recurso_name_norm"] == table_norm]
    if not exact.empty:
        row = exact.iloc[0]
        return {
            "size_mb": row.get("size_mb"),
            "matched_recurso_name": row.get("recurso_name"),
        }

    contains = temp[temp["recurso_name_norm"].str.contains(table_norm, na=False)]
    if not contains.empty:
        row = contains.iloc[0]
        return {
            "size_mb": row.get("size_mb"),
            "matched_recurso_name": row.get("recurso_name"),
        }

    reverse_contains = temp[temp["recurso_name_norm"].apply(lambda x: x in table_norm if x else False)]
    if not reverse_contains.empty:
        row = reverse_contains.iloc[0]
        return {
            "size_mb": row.get("size_mb"),
            "matched_recurso_name": row.get("recurso_name"),
        }

    return {"size_mb": None, "matched_recurso_name": None}


def build_metadata_catalog(engine, table_prefix: str = "antt_") -> list[dict]:
    log_event(logger, "build_metadata_catalog_start", table_prefix=table_prefix)

    tables = list_tables(engine, prefix=table_prefix)
    log_event(logger, "tables_listed", total_tables=len(tables))

    resource_inventory_df = pd.DataFrame()
    try:
        resource_inventory_df = load_table(engine, "antt_antt_extraction_csv_inventory", limit=None)
        log_event(logger, "resource_inventory_loaded", rows=len(resource_inventory_df))
    except Exception as e:
        log_event(logger, "resource_inventory_load_error", error=str(e))

    catalog = []

    for idx, table_name in enumerate(tables, start=1):
        log_event(logger, "table_processing_start", index=idx, table_name=table_name)

        try:
            columns = list_columns(engine, table_name)
        except Exception as e:
            log_event(logger, "table_columns_error", table_name=table_name, error=str(e))
            columns = []

        try:
            table_description = get_table_description(engine, table_name)
        except Exception as e:
            log_event(logger, "table_description_error", table_name=table_name, error=str(e))
            table_description = ""

        try:
            df_dict = get_table_dictionary(engine, table_name)
        except Exception as e:
            log_event(logger, "table_dictionary_error", table_name=table_name, error=str(e))
            df_dict = pd.DataFrame()

        try:
            sample_rows = get_table_sample(engine, table_name, limit=5)
        except Exception as e:
            log_event(logger, "table_sample_error", table_name=table_name, error=str(e))
            sample_rows = []

        tags = _infer_column_tags(columns)
        dictionary_summary = _build_dictionary_summary(df_dict)
        volume_info = _get_volume_info(engine, table_name, resource_inventory_df)

        search_text_parts = [
            table_name,
            table_description or "",
            " ".join(columns),
            " ".join([item["field_name"] for item in dictionary_summary]),
            " ".join([item["field_description"] for item in dictionary_summary if item.get("field_description")]),
            " ".join(tags.get("date_like_columns", [])),
            " ".join(tags.get("numeric_like_columns", [])),
            str(volume_info.get("matched_recurso_name") or ""),
        ]

        catalog_item = {
            "table_name": table_name,
            "table_description": table_description,
            "columns": columns,
            "dictionary_summary": dictionary_summary,
            "sample_rows": sample_rows,
            "tags": tags,
            "volume_info": volume_info,
            "search_text": " ".join(search_text_parts).strip(),
        }

        catalog.append(catalog_item)
        log_event(
            logger,
            "table_processing_end",
            table_name=table_name,
            columns_count=len(columns),
            dict_summary_count=len(dictionary_summary),
            sample_count=len(sample_rows),
            size_mb=volume_info.get("size_mb"),
        )

    log_event(logger, "build_metadata_catalog_end", final_count=len(catalog))
    return catalog


def save_metadata_catalog(catalog: list[dict], filepath: Path = CATALOG_FILE):
    log_event(logger, "save_metadata_catalog_start", filepath=str(filepath), records=len(catalog))
    filepath.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log_event(logger, "save_metadata_catalog_end", filepath=str(filepath))


def rebuild_metadata_catalog(engine, table_prefix: str = "antt_") -> list[dict]:
    log_event(logger, "rebuild_metadata_catalog_start", table_prefix=table_prefix)
    catalog = build_metadata_catalog(engine, table_prefix=table_prefix)
    save_metadata_catalog(catalog)
    log_event(logger, "rebuild_metadata_catalog_end", total=len(catalog))
    return catalog


if __name__ == "__main__":
    from dotenv import load_dotenv
    import os
    from sqlalchemy import create_engine

    load_dotenv()

    user = os.getenv("SUPABASE_DB_USER")
    pwd = os.getenv("SUPABASE_DB_PASSWORD")
    host = os.getenv("SUPABASE_DB_HOST")
    port = os.getenv("SUPABASE_DB_PORT", "5432")
    db = os.getenv("SUPABASE_DB_NAME")

    log_event(logger, "script_start", host=host, port=port, db=db)

    engine = create_engine(f"postgresql+psycopg2://{user}:{pwd}@{host}:{port}/{db}")

    catalog = rebuild_metadata_catalog(engine)
    print(f"Catálogo gerado com {len(catalog)} tabelas em: {CATALOG_FILE}")