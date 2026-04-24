from metadata_service import list_tables, list_columns, find_tables_by_field, get_table_sample
from dictionary_service import get_table_dictionary, get_table_description


SUPPORTED_CHARTS = [
    {
        "type": "line",
        "needs": ["x"],
        "optional": ["y"],
        "description": "Evolução ou comparação em linha.",
    },
    {
        "type": "bar",
        "needs": ["x"],
        "optional": ["y"],
        "description": "Barras horizontais para ranking ou comparação.",
    },
    {
        "type": "column",
        "needs": ["x"],
        "optional": ["y"],
        "description": "Colunas verticais para comparação entre categorias.",
    },
    {
        "type": "scatter",
        "needs": ["x", "y"],
        "optional": [],
        "description": "Dispersão entre dois campos numéricos.",
    },
    {
        "type": "pie",
        "needs": ["value"],
        "optional": [],
        "description": "Participação percentual por categoria.",
    },
    {
        "type": "donut",
        "needs": ["value"],
        "optional": [],
        "description": "Rosca com participação percentual.",
    },
    {
        "type": "map_points",
        "needs": ["x", "y"],
        "optional": ["value", "extra"],
        "description": "Mapa de pontos com latitude, longitude, tooltip e cor.",
    },
    {
        "type": "map_br_uf",
        "needs": ["x"],
        "optional": ["y"],
        "description": "Mapa do Brasil por UF com intensidade de cor.",
    },
]


def build_bi_context(engine, selected_table: str | None = None) -> dict:
    context = {
        "selected_table": selected_table,
        "supported_charts": SUPPORTED_CHARTS,
        "tables": [],
        "dictionary": [],
        "description": "",
        "sample": [],
    }

    if selected_table:
        columns = list_columns(engine, selected_table)
        context["tables"].append(
            {
                "table_name": selected_table,
                "columns": columns,
            }
        )
        context["description"] = get_table_description(engine, selected_table)

        df_dict = get_table_dictionary(engine, selected_table)
        if not df_dict.empty:
            context["dictionary"] = df_dict.head(100).to_dict("records")

        context["sample"] = get_table_sample(engine, selected_table, limit=8)

    else:
        tables = list_tables(engine)
        context["tables"] = [{"table_name": t} for t in tables[:100]]

    return context


def search_metadata(engine, question: str) -> dict:
    tables = find_tables_by_field(engine, question)
    return {
        "matched_tables": tables[:50],
    }