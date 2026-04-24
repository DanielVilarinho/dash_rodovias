import json
from pathlib import Path

from metadata_catalog_builder import rebuild_metadata_catalog
from shared_logger import get_shared_logger, log_event


logger = get_shared_logger("metadata_catalog_service")

CATALOG_FILE = Path("cache") / "bi_metadata_catalog.json"


def load_metadata_catalog(
    engine=None,
    filepath: Path = CATALOG_FILE,
    auto_create: bool = True,
) -> list[dict]:
    log_event(
        logger,
        "load_metadata_catalog_start",
        filepath=str(filepath),
        exists=filepath.exists(),
        auto_create=auto_create,
        has_engine=engine is not None,
    )

    if filepath.exists():
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            log_event(logger, "load_metadata_catalog_success", records=len(data))
            return data
        except Exception as e:
            log_event(logger, "load_metadata_catalog_read_error", error=str(e))
            if not auto_create or engine is None:
                return []

    if auto_create and engine is not None:
        try:
            log_event(logger, "load_metadata_catalog_autocreate_start")
            catalog = rebuild_metadata_catalog(engine)
            log_event(logger, "load_metadata_catalog_autocreate_end", records=len(catalog))
            return catalog
        except Exception as e:
            log_event(logger, "load_metadata_catalog_autocreate_error", error=str(e))
            return []

    log_event(logger, "load_metadata_catalog_end_empty")
    return []


def get_catalog_table(
    table_name: str,
    catalog: list[dict] | None = None,
    engine=None,
) -> dict | None:
    catalog = catalog or load_metadata_catalog(engine=engine)
    for item in catalog:
        if item.get("table_name") == table_name:
            return item
    return None


def search_catalog(
    query: str,
    catalog: list[dict] | None = None,
    engine=None,
    limit: int = 10,
) -> list[dict]:
    catalog = catalog or load_metadata_catalog(engine=engine)

    q = str(query or "").strip().lower()
    if not q:
        return catalog[:limit]

    scored = []
    for item in catalog:
        search_text = str(item.get("search_text") or "").lower()

        score = 0
        if q in str(item.get("table_name") or "").lower():
            score += 10
        if q in str(item.get("table_description") or "").lower():
            score += 6
        if q in search_text:
            score += 3

        if score > 0:
            scored.append((score, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:limit]]


def find_tables_with_field(
    field_name: str,
    catalog: list[dict] | None = None,
    engine=None,
    limit: int = 50,
) -> list[dict]:
    catalog = catalog or load_metadata_catalog(engine=engine)
    q = str(field_name or "").strip().lower()

    matches = []
    for item in catalog:
        columns = [str(c).lower() for c in item.get("columns", [])]
        if any(q in c for c in columns):
            matches.append(item)

    return matches[:limit]


def list_catalog_tables(
    catalog: list[dict] | None = None,
    engine=None,
    limit: int = 200,
) -> list[str]:
    catalog = catalog or load_metadata_catalog(engine=engine)
    return [item.get("table_name") for item in catalog[:limit]]


def summarize_catalog_table(
    table_name: str,
    catalog: list[dict] | None = None,
    engine=None,
) -> dict:
    item = get_catalog_table(table_name, catalog=catalog, engine=engine)
    if not item:
        return {
            "found": False,
            "message": "Tabela não encontrada no catálogo.",
        }

    return {
        "found": True,
        "table_name": item.get("table_name"),
        "table_description": item.get("table_description"),
        "columns": item.get("columns", []),
        "dictionary_summary": item.get("dictionary_summary", []),
        "tags": item.get("tags", {}),
        "sample_rows": item.get("sample_rows", []),
        "volume_info": item.get("volume_info", {}),
    }