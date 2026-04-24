import json
import os
import re
import unicodedata

import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI
from sqlalchemy import text

from assistant_memory import (
    get_session_messages,
    append_session_message,
    trim_session_messages,
)
from metadata_catalog_service import (
    load_metadata_catalog,
    search_catalog,
    summarize_catalog_table,
    find_tables_with_field,
    list_catalog_tables,
)
from shared_logger import get_shared_logger, log_event

load_dotenv()

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

logger = get_shared_logger("assistant_chat_service")


def get_openai_client():
    if not OPENAI_API_KEY:
        raise ValueError("Defina OPENAI_API_KEY no .env")
    return OpenAI(api_key=OPENAI_API_KEY)


def _normalize_text(value: str) -> str:
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text


def build_chat_system_prompt() -> str:
    return """
Você é um copiloto de BI e catálogo de dados.

Seu papel é:
- explicar tabelas
- explicar colunas
- sugerir quais tabelas parecem melhores para um tema
- sugerir gráficos
- responder com base no catálogo já indexado e no contexto enviado

Regras:
- nunca invente tabela ou coluna
- se houver tabela selecionada, priorize ela
- use o contexto do catálogo enviado
- responda em texto claro e útil
- não devolva blocos JSON crus para o usuário
- não diga que faltou catálogo se o contexto enviado já tiver tabelas, colunas, dicionário ou resumo
- use markdown simples quando ajudar:
  - **negrito**
  - listas
"""


def build_chat_context(engine, user_message: str, selected_table: str | None = None) -> dict:
    log_event(logger, "build_chat_context_start", user_message=user_message, selected_table=selected_table)

    catalog = load_metadata_catalog(engine=engine, auto_create=True)
    log_event(logger, "catalog_loaded_for_chat", records=len(catalog))

    selected_table_summary = None
    if selected_table:
        selected_table_summary = summarize_catalog_table(
            selected_table,
            catalog=catalog,
            engine=engine,
        )

    related_tables = search_catalog(
        user_message,
        catalog=catalog,
        engine=engine,
        limit=8,
    )

    field_matches = find_tables_with_field(
        user_message,
        catalog=catalog,
        engine=engine,
        limit=50,
    )

    context = {
        "catalog_table_count": len(catalog),
        "catalog_table_names_preview": list_catalog_tables(catalog=catalog, limit=30),
        "catalog_all_tables": catalog,
        "selected_table": selected_table,
        "selected_table_summary": selected_table_summary,
        "related_tables": related_tables,
        "field_matches": field_matches,
    }

    log_event(
        logger,
        "build_chat_context_end",
        selected_table_found=bool(selected_table_summary),
        related_tables=len(related_tables),
        field_matches=len(field_matches),
        catalog_table_count=len(catalog),
    )
    return context


def _get_context_table_pool(context: dict) -> list[dict]:
    pool = []

    all_tables = context.get("catalog_all_tables") or []
    if all_tables:
        pool.extend(all_tables)

    selected_summary = context.get("selected_table_summary") or {}
    if selected_summary.get("found"):
        pool.append(selected_summary)

    pool.extend(context.get("related_tables", []))
    pool.extend(context.get("field_matches", []))

    seen = set()
    unique_pool = []
    for item in pool:
        table_name = item.get("table_name")
        if not table_name or table_name in seen:
            continue
        seen.add(table_name)
        unique_pool.append(item)

    return unique_pool


def _find_tables_by_exact_column(context: dict, column_name: str) -> list[dict]:
    target = _normalize_text(column_name)
    if not target:
        return []

    matches = []
    for item in _get_context_table_pool(context):
        columns = [_normalize_text(c) for c in item.get("columns", [])]
        if target in columns:
            matches.append(item)

    return matches


def _find_tables_by_partial_column(context: dict, term: str) -> list[dict]:
    target = _normalize_text(term)
    if not target:
        return []

    matches = []
    for item in _get_context_table_pool(context):
        columns = [_normalize_text(c) for c in item.get("columns", [])]
        if any(target in c for c in columns):
            matches.append(item)

    return matches


def _find_tables_by_dictionary_field(context: dict, term: str) -> list[dict]:
    target = _normalize_text(term)
    if not target:
        return []

    matches = []
    for item in _get_context_table_pool(context):
        dictionary_summary = item.get("dictionary_summary", []) or []
        for field in dictionary_summary:
            field_name = _normalize_text(field.get("field_name"))
            if field_name == target or target in field_name:
                matches.append(item)
                break

    return matches


def _find_tables_with_column_strategy(context: dict, exact_name: str, partial_term: str | None = None) -> list[dict]:
    exact_matches = _find_tables_by_exact_column(context, exact_name)
    if exact_matches:
        return exact_matches

    if partial_term:
        partial_matches = _find_tables_by_partial_column(context, partial_term)
        if partial_matches:
            return partial_matches

        dict_matches = _find_tables_by_dictionary_field(context, partial_term)
        if dict_matches:
            return dict_matches

    return []


def _message_mentions_table(user_message: str, catalog_tables: list[dict]) -> bool:
    msg = _normalize_text(user_message)

    for item in catalog_tables:
        table_name = item.get("table_name") or ""
        table_norm = _normalize_text(table_name)
        short_norm = _normalize_text(table_name.replace("antt_", "").replace("_", " "))
        resource_norm = _normalize_text((item.get("volume_info") or {}).get("matched_recurso_name") or "")

        if table_norm and table_norm in msg:
            return True
        if short_norm and short_norm in msg:
            return True
        if resource_norm and resource_norm in msg:
            return True

    return False


def _resolve_target_table(context: dict, user_message: str, last_query_context: dict | None = None) -> dict | None:
    selected_summary = context.get("selected_table_summary") or {}
    if selected_summary.get("found"):
        return selected_summary

    all_tables = context.get("catalog_all_tables") or []

    if last_query_context:
        fallback_table = last_query_context.get("table_name")
        if fallback_table and not _message_mentions_table(user_message, all_tables):
            fallback_summary = summarize_catalog_table(
                fallback_table,
                catalog=all_tables,
                engine=context.get("engine"),
            )
            if fallback_summary and fallback_summary.get("found"):
                return fallback_summary

    msg = _normalize_text(user_message)

    scored = []
    for item in all_tables:
        table_name = item.get("table_name") or ""
        table_norm = _normalize_text(table_name)
        short_norm = _normalize_text(table_name.replace("antt_", "").replace("_", " "))
        desc_norm = _normalize_text(item.get("table_description") or "")
        resource_norm = _normalize_text((item.get("volume_info") or {}).get("matched_recurso_name") or "")

        score = 0
        if short_norm and short_norm in msg:
            score += 12
        if table_norm and table_norm in msg:
            score += 10
        if resource_norm and resource_norm in msg:
            score += 8
        if desc_norm:
            for token in short_norm.split():
                if token and token in msg and token in desc_norm:
                    score += 2

        if score > 0:
            scored.append((score, item))

    if scored:
        scored.sort(key=lambda x: x[0], reverse=True)
        chosen = scored[0][1]
        return {
            "found": True,
            "table_name": chosen.get("table_name"),
            "table_description": chosen.get("table_description"),
            "columns": chosen.get("columns", []),
            "dictionary_summary": chosen.get("dictionary_summary", []),
            "tags": chosen.get("tags", {}),
            "sample_rows": chosen.get("sample_rows", []),
            "volume_info": chosen.get("volume_info", {}),
        }

    if last_query_context:
        fallback_table = last_query_context.get("table_name")
        if fallback_table:
            return summarize_catalog_table(
                fallback_table,
                catalog=all_tables,
                engine=context.get("engine"),
            )

    return None


def _detect_followup_data_request(user_message: str) -> bool:
    msg = _normalize_text(user_message)

    followups = [
        "rode e devolva os dados",
        "rode e me devolva os dados",
        "devolva os dados",
        "me devolva os dados",
        "traga os dados",
        "mostre os dados",
        "execute",
        "rode",
        "agora me devolva",
        "agora traga",
        "agora mostre",
    ]

    return any(p in msg for p in followups)


def _detect_data_request(user_message: str) -> bool:
    msg = _normalize_text(user_message)

    data_triggers = [
        "mostre",
        "traga",
        "liste",
        "registros",
        "linhas",
        "dados",
        "resultado tabular",
        "sample",
        "amostra",
        "top",
        "agrupe",
        "group by",
        "faça um query",
        "faca um query",
        "faça uma query",
        "faca uma query",
        "rode",
        "execute",
        "devolva",
        "valores unicos",
        "valores únicos",
        "distinct",
        "contagem",
        "conte",
        "quantidade",
    ]

    analytic_triggers = [
        "explique",
        "descreva",
        "qual a melhor",
        "qual o melhor",
        "por que",
        "por quê",
        "compare",
        "comparar",
        "serve para mapa",
        "quais tabelas",
        "que tabelas",
        "principais colunas",
        "melhor gráfico",
        "melhor grafico",
        "resuma",
        "resumo",
    ]

    if any(t in msg for t in analytic_triggers):
        return False

    return any(t in msg for t in data_triggers)


def _detect_analytic_request(user_message: str) -> bool:
    msg = _normalize_text(user_message)

    analytic_triggers = [
        "explique",
        "descreva",
        "qual a melhor",
        "qual o melhor",
        "por que",
        "por quê",
        "compare",
        "comparar",
        "serve para mapa",
        "quais tabelas",
        "que tabelas",
        "principais colunas",
        "melhor gráfico",
        "melhor grafico",
        "resuma",
        "resumo",
    ]

    return any(t in msg for t in analytic_triggers)


def _detect_previous_sql_request(user_message: str) -> bool:
    msg = _normalize_text(user_message)
    triggers = [
        "a query anterior",
        "query anterior",
        "sql anterior",
        "rode ela",
        "rode a query anterior",
        "execute a query anterior",
        "rode a consulta anterior",
        "execute a consulta anterior",
    ]
    return any(t in msg for t in triggers)


def _extract_limit(user_message: str, default: int = 20, max_limit: int = 200) -> int:
    nums = re.findall(r"\b(\d{1,4})\b", str(user_message or ""))
    if not nums:
        return default
    value = int(nums[0])
    return max(1, min(value, max_limit))


def _parse_requested_columns(user_message: str, available_columns: list[str]) -> list[str]:
    msg = _normalize_text(user_message)
    matched = []

    for col in available_columns:
        col_norm = _normalize_text(col)
        if col_norm and col_norm in msg:
            matched.append(col)

    return matched[:15]


def _parse_simple_filters(user_message: str, available_columns: list[str]) -> list[tuple[str, str]]:
    msg_norm = _normalize_text(user_message)
    filters = []

    for col in available_columns:
        col_norm = _normalize_text(col)

        patterns = [
            rf"{re.escape(col_norm)}\s*=\s*([^\n,;]+)",
            rf"{re.escape(col_norm)}\s*:\s*([^\n,;]+)",
            rf"{re.escape(col_norm)}\s*é\s*([^\n,;]+)",
            rf"{re.escape(col_norm)}\s*eh\s*([^\n,;]+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, msg_norm)
            if match:
                value = match.group(1).strip().strip("'").strip('"')
                if value:
                    filters.append((col, value))
                    break

    return filters[:5]


def _guess_group_column(user_message: str, available_columns: list[str]) -> str | None:
    requested = _parse_requested_columns(user_message, available_columns)
    if requested:
        return requested[0]

    msg = _normalize_text(user_message)

    priority_terms = [
        "tipo_de_acidente",
        "rodovia_uf_saida",
        "rodovia_uf_entrada",
        "rodovia_uf",
        "concessionaria",
        "municipio",
        "municipio_saida",
        "municipio_entrada",
        "sentido",
        "tipo_acesso",
        "trecho",
        "tipo_de_atendimento",
        "nome",
    ]

    for term in priority_terms:
        for col in available_columns:
            if _normalize_text(col) == _normalize_text(term):
                if term in msg or "quantidade" in msg or "contagem" in msg or "conte" in msg or "top" in msg or "unicos" in msg or "únicos" in msg:
                    return col

    return None


def _extract_sql_from_text(text_value: str) -> str | None:
    if not text_value:
        return None

    text_raw = str(text_value).strip()

    fenced = re.findall(r"```sql\s*(.*?)```", text_raw, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        sql = fenced[-1].strip().rstrip(";")
        if sql:
            return sql

    single_line = re.search(
        r"\b(SELECT|WITH)\b.*",
        text_raw,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if single_line:
        sql = single_line.group(0).strip().rstrip(";")
        if sql:
            return sql

    return None


def _extract_last_sql_from_history(history: list[dict]) -> str | None:
    if not history:
        return None

    for item in reversed(history):
        content = item.get("content", "")
        sql = _extract_sql_from_text(content)
        if sql:
            return sql

    return None


def _infer_table_from_sql(sql_text: str) -> str | None:
    if not sql_text:
        return None

    match = re.search(
        r'from\s+public\."([^"]+)"',
        sql_text,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1)

    match = re.search(
        r'from\s+"([^"]+)"',
        sql_text,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1)

    match = re.search(
        r'from\s+([a-zA-Z0-9_\.]+)',
        sql_text,
        flags=re.IGNORECASE,
    )
    if match:
        raw = match.group(1)
        return raw.split(".")[-1].replace('"', "")

    return None


def _run_raw_sql(engine, sql_text: str) -> dict:
    sql_clean = str(sql_text).strip().rstrip(";")

    log_event(
        logger,
        "run_raw_sql_start",
        sql=sql_clean,
    )

    with engine.begin() as conn:
        df = pd.read_sql(text(sql_clean), conn)

    table_name = _infer_table_from_sql(sql_clean)

    return {
        "sql": sql_clean,
        "columns": df.columns.tolist(),
        "rows": df.to_dict("records"),
        "row_count": len(df),
        "table_name": table_name,
    }


def _get_interesting_columns_for_table(
    table_name: str,
    available_columns: list[str],
    user_message: str,
) -> list[str]:
    cols_norm_map = {_normalize_text(c): c for c in available_columns}
    requested = _parse_requested_columns(user_message, available_columns)

    interesting = list(requested)

    table_norm = _normalize_text(table_name)
    msg = _normalize_text(user_message)

    def add_if_exists(*names):
        for name in names:
            normalized = _normalize_text(name)
            if normalized in cols_norm_map and cols_norm_map[normalized] not in interesting:
                interesting.append(cols_norm_map[normalized])

    if "acidente" in table_norm:
        add_if_exists(
            "data",
            "horario",
            "tipo_de_ocorrencia",
            "tipo_de_acidente",
            "km",
            "trecho",
            "sentido",
            "automovel",
            "caminhao",
            "moto",
            "onibus",
            "utilitarios",
            "ilesos",
            "levemente_feridos",
            "moderadamente_feridos",
            "gravemente_feridos",
            "mortos",
        )

    elif "radar" in table_norm:
        add_if_exists(
            "tipo_de_radar",
            "rodovia",
            "uf",
            "km_m",
            "Municipio",
            "tipo_de_pista",
            "sentido",
            "situacao",
            "latitude",
            "longitude",
            "velocidade_leve",
            "velocidade_pesado",
        )

    elif "alcas" in table_norm:
        add_if_exists(
            "concessionaria",
            "nome",
            "rodovia_uf_entrada",
            "km_m_entrada",
            "sentido_entrada",
            "latitude_entrada",
            "longitude_entrada",
            "rodovia_uf_saida",
            "km_m_saida",
            "sentido_saida",
            "latitude_saida",
            "longitude_saida",
            "n_faixas",
            "velocidade_maxima",
            "tipo_de_pavimento",
            "largura",
            "extensao",
        )

    else:
        add_if_exists(
            "data",
            "horario",
            "ano",
            "mes",
            "uf",
            "municipio",
            "latitude",
            "longitude",
            "concessionaria",
            "nome",
            "tipo",
            "categoria",
            "quantidade",
            "valor",
            "km",
            "trecho",
            "sentido",
        )

    if "interessante" in msg or "uteis" in msg or "úteis" in msg:
        return interesting[:18]

    return requested[:15] if requested else interesting[:12]


def _run_preview_query(engine, table_name: str, available_columns: list[str], user_message: str) -> dict:
    limit = _extract_limit(user_message, default=20, max_limit=200)
    selected_columns = _parse_requested_columns(user_message, available_columns)
    filters = _parse_simple_filters(user_message, available_columns)

    msg = _normalize_text(user_message)
    if ("interessante" in msg or "uteis" in msg or "úteis" in msg) and not selected_columns:
        selected_columns = _get_interesting_columns_for_table(
            table_name=table_name,
            available_columns=available_columns,
            user_message=user_message,
        )

    safe_table = f'public."{table_name}"'

    is_count_request = any(x in msg for x in ["quantidade", "contagem", "conte", "count", "agrupe", "group by"])
    is_distinct_request = any(x in msg for x in ["valores unicos", "valores únicos", "distinct", "lista unica", "lista única", "unicos", "únicos"])
    group_col = _guess_group_column(user_message, available_columns)

    params = {}
    where_sql = ""

    if filters:
        where_parts = []
        for idx, (col, value) in enumerate(filters):
            p = f"p{idx}"
            where_parts.append(f'CAST("{col}" AS TEXT) ILIKE :{p}')
            params[p] = f"%{value}%"
        where_sql = " WHERE " + " AND ".join(where_parts)

    if is_distinct_request and group_col:
        if where_sql:
            sql = (
                f'SELECT DISTINCT "{group_col}" '
                f'FROM {safe_table}{where_sql} AND "{group_col}" IS NOT NULL '
                f'ORDER BY "{group_col}" '
                f'LIMIT {limit}'
            )
        else:
            sql = (
                f'SELECT DISTINCT "{group_col}" '
                f'FROM {safe_table} '
                f'WHERE "{group_col}" IS NOT NULL '
                f'ORDER BY "{group_col}" '
                f'LIMIT {limit}'
            )

    elif is_count_request and group_col:
        sql = (
            f'SELECT "{group_col}" AS categoria, COUNT(*) AS quantidade '
            f'FROM {safe_table}'
            f'{where_sql} '
            f'GROUP BY "{group_col}" '
            f'ORDER BY quantidade DESC '
            f'LIMIT {limit}'
        )
    else:
        if selected_columns:
            safe_columns = [f'"{c}"' for c in selected_columns]
            sql = f'SELECT {", ".join(safe_columns)} FROM {safe_table}{where_sql} LIMIT {limit}'
        else:
            sql = f"SELECT * FROM {safe_table}{where_sql} LIMIT {limit}"

    log_event(
        logger,
        "run_preview_query_start",
        table_name=table_name,
        selected_columns=selected_columns,
        filters=filters,
        limit=limit,
        sql=sql,
    )

    with engine.begin() as conn:
        df = pd.read_sql(text(sql), conn, params=params)

    return {
        "sql": sql,
        "columns": df.columns.tolist(),
        "rows": df.to_dict("records"),
        "row_count": len(df),
        "table_name": table_name,
    }


def _suggest_best_graph_for_table(summary: dict) -> str:
    if not summary or not summary.get("found"):
        return "Sem tabela selecionada."

    cols = summary.get("columns", [])
    cols_norm = [_normalize_text(c) for c in cols]

    has_lat = any("latitude" in c for c in cols_norm)
    has_lon = any("longitude" in c for c in cols_norm)
    has_uf = any(c == "uf" or "rodovia_uf" in c or "uf_" in c for c in cols_norm)
    has_date = any(any(x in c for x in ["data", "mes_ano", "ano_", "horario", "hora"]) for c in cols_norm)

    if has_lat and has_lon:
        return "O melhor gráfico inicial para essa tabela parece ser um **mapa de pontos**, porque ela possui colunas de **latitude** e **longitude**."

    if has_uf:
        return "O melhor gráfico inicial para essa tabela parece ser um **mapa do Brasil por UF** ou um **gráfico de barras por UF**."

    if has_date:
        return "O melhor gráfico inicial para essa tabela parece ser um **gráfico de linha** ou **colunas por período**, porque ela possui colunas de tempo."

    return "O melhor gráfico inicial para essa tabela parece ser um **gráfico de barras** por categoria principal."


def _suggest_queries_text(summary: dict) -> str:
    if not summary or not summary.get("found"):
        return ""

    cols = summary.get("columns", [])
    preview_cols = cols[:5]

    suggestions = [
        'Você também pode me pedir consultas tabulares, por exemplo:',
        '- "mostre 20 linhas da tabela atual"',
    ]

    if preview_cols:
        suggestions.append(f'- "traga {", ".join(preview_cols[:3])} da tabela atual"')

    if any(_normalize_text(c) == "municipio" for c in cols):
        suggestions.append('- "mostre 10 registros onde municipio = Vargem"')

    if any("concessionaria" in _normalize_text(c) for c in cols):
        suggestions.append('- "conte registros por concessionaria"')

    return "\n".join(suggestions)


def _build_comparative_theme_answer(context: dict, theme: str) -> str | None:
    matches = search_catalog(theme, catalog=context.get("catalog_all_tables"), limit=6)
    if not matches:
        return None

    lines = []
    for idx, item in enumerate(matches[:4], start=1):
        table_name = item.get("table_name")
        desc = item.get("table_description") or "Sem descrição disponível."
        cols = item.get("columns", []) or []
        sample_cols = ", ".join(cols[:6]) if cols else "sem colunas carregadas"

        prefix = "Melhor candidata" if idx == 1 else "Também relevante"
        lines.append(
            f"- **{table_name}** — {prefix}. {desc} "
            f"Algumas colunas: {sample_cols}."
        )

    if theme == "radar":
        intro = "Para análise de **radares**, eu priorizaria estas tabelas:"
    else:
        intro = f"Para análise de **{theme}**, eu priorizaria estas tabelas:"

    return intro + "\n" + "\n".join(lines)


def _direct_catalog_answer(
    user_message: str,
    context: dict,
    last_query_context: dict | None = None,
    history: list[dict] | None = None,
) -> dict | None:
    msg = _normalize_text(user_message)
    is_analytic_request = _detect_analytic_request(user_message)
    is_followup_data = _detect_followup_data_request(user_message)
    explicit_previous_sql = _detect_previous_sql_request(user_message)
    history = history or []

    raw_sql_from_user = _extract_sql_from_text(user_message)
    last_sql_from_history = _extract_last_sql_from_history(history)
    last_sql_from_context = (last_query_context or {}).get("sql")

    sql_to_execute = None
    if raw_sql_from_user:
        sql_to_execute = raw_sql_from_user
    elif explicit_previous_sql:
        sql_to_execute = last_sql_from_history or last_sql_from_context

    if sql_to_execute:
        try:
            query_result = _run_raw_sql(context["engine"], sql_to_execute)
            table_name = query_result.get("table_name")

            answer = (
                f"Executei a consulta SQL.\n\n"
                f"**Query executada:**\n```sql\n{query_result['sql']}\n```\n\n"
                f"**Linhas retornadas:** {query_result['row_count']}\n"
                f"**Colunas:** {', '.join(query_result['columns'])}"
            )

            return {
                "answer": answer,
                "table": query_result,
                "last_query_context": {
                    "table_name": table_name,
                    "sql": query_result["sql"],
                    "original_user_message": user_message,
                },
            }
        except Exception as e:
            return {
                "answer": f"Tentei executar a SQL, mas ocorreu um erro: **{e}**.",
                "table": None,
                "last_query_context": last_query_context,
            }

    selected_summary = _resolve_target_table(context, user_message, last_query_context=last_query_context) or {}

    if "quantas tabelas" in msg or "numero de tabelas" in msg or "número de tabelas" in msg:
        total = context.get("catalog_table_count", 0)
        return {"answer": f"Temos **{total} tabelas** no catálogo atual."}

    if ("quais tabelas" in msg or "que tabela" in msg or "que tabelas" in msg) and ("uf" in msg or "proximo disso" in msg or "parecido com" in msg):
        matches = _find_tables_with_column_strategy(context, exact_name="uf", partial_term="uf")
        if matches:
            lines = []
            for item in matches[:30]:
                cols = item.get("columns", [])
                cols_found = [c for c in cols if "uf" in _normalize_text(c)]
                if not cols_found:
                    dict_fields = item.get("dictionary_summary", []) or []
                    cols_found = [f.get("field_name") for f in dict_fields if "uf" in _normalize_text(f.get("field_name"))]
                detail = ", ".join([c for c in cols_found if c][:8]) if cols_found else "campo relacionado a uf"
                lines.append(f"- **{item.get('table_name')}** → {detail}")
            return {"answer": "Encontrei estas tabelas com coluna exata ou próxima de **`uf`**:\n" + "\n".join(lines)}
        return {"answer": "Não encontrei tabelas com coluna exata ou próxima de **`uf`** no catálogo atual."}

    if (
        (
            "explique a tabela atual" in msg
            or "descreva a tabela atual" in msg
            or ("explique a tabela" in msg and selected_summary.get("found"))
            or ("descreva a tabela" in msg and selected_summary.get("found"))
        )
        and selected_summary.get("found")
    ):
        name = selected_summary.get("table_name")
        desc = selected_summary.get("table_description") or "Sem descrição cadastrada."
        cols = selected_summary.get("columns", [])
        preview = ", ".join(cols[:15])
        volume = selected_summary.get("volume_info", {}).get("size_mb")

        vol_text = f"\n\n**Volume aproximado:** {volume} MB." if volume is not None else ""

        return {
            "answer": (
                f"A tabela é **{name}**.\n\n"
                f"**Descrição:** {desc}\n\n"
                f"Ela possui **{len(cols)} colunas**. Algumas delas são: {preview}."
                f"{vol_text}\n\n"
                f"{_suggest_best_graph_for_table(selected_summary)}\n\n"
                f"{_suggest_queries_text(selected_summary)}"
            )
        }

    if is_analytic_request and "radar" in msg:
        comparative = _build_comparative_theme_answer(context, "radar")
        if comparative:
            return {"answer": comparative}

    if is_analytic_request and "municipio" in msg:
        matches = _find_tables_with_column_strategy(context, exact_name="municipio", partial_term="municipio")
        if matches:
            lines = []
            for item in matches[:20]:
                cols = item.get("columns", [])
                cols_found = [c for c in cols if "municipio" in _normalize_text(c) or "municipal" in _normalize_text(c)]
                if not cols_found:
                    dict_fields = item.get("dictionary_summary", []) or []
                    cols_found = [
                        f.get("field_name")
                        for f in dict_fields
                        if "municipio" in _normalize_text(f.get("field_name"))
                        or "municipal" in _normalize_text(f.get("field_name"))
                    ]
                lines.append(f"- **{item.get('table_name')}** → " + ", ".join([c for c in cols_found if c][:8]))
            return {
                "answer": "Encontrei estas tabelas com colunas relacionadas a **município**:\n" + "\n".join(lines)
            }

    if _detect_data_request(user_message) or is_followup_data:
        if not selected_summary.get("found"):
            return {
                "answer": "Entendi que você quer **dados/resultados**, mas não consegui identificar a tabela. Diga o nome da tabela no pedido, por exemplo: **antt_alcas** ou **tabela de alças**."
            }

        try:
            effective_message = user_message

            if is_followup_data and last_query_context:
                if last_query_context.get("original_user_message"):
                    effective_message = last_query_context["original_user_message"]

            query_result = _run_preview_query(
                engine=context["engine"],
                table_name=selected_summary["table_name"],
                available_columns=selected_summary.get("columns", []),
                user_message=effective_message,
            )

            query_block = f"```sql\n{query_result['sql']}\n```"

            top_without_criterion = "top" in _normalize_text(effective_message) and not any(
                x in _normalize_text(effective_message)
                for x in ["quantidade", "contagem", "conte", "count", "por "]
            )

            if top_without_criterion:
                answer = (
                    f"Executei a consulta na tabela **{selected_summary['table_name']}**.\n\n"
                    f"**Query executada:**\n{query_block}\n\n"
                    f"Como você pediu **top {query_result['row_count']}** sem informar um critério de ordenação, trouxe as **{query_result['row_count']} primeiras linhas** da tabela."
                )
            else:
                answer = (
                    f"Executei a consulta na tabela **{selected_summary['table_name']}**.\n\n"
                    f"**Query executada:**\n{query_block}\n\n"
                    f"**Linhas retornadas:** {query_result['row_count']}\n"
                    f"**Colunas:** {', '.join(query_result['columns'])}"
                )

            return {
                "answer": answer,
                "table": query_result,
                "last_query_context": {
                    "table_name": selected_summary["table_name"],
                    "sql": query_result["sql"],
                    "original_user_message": effective_message,
                },
            }
        except Exception as e:
            return {
                "answer": (
                    f"Entendi que você quer um **resultado com dados**, mas ocorreu um erro ao consultar a tabela **{selected_summary.get('table_name')}**: **{e}**.\n\n"
                    f"{_suggest_queries_text(selected_summary)}"
                )
            }

    return None


def _cleanup_answer(answer: str) -> str:
    if not answer:
        return "Não consegui responder no momento."

    answer = answer.strip()
    answer = re.sub(
        r"\n```json\s*.*?```",
        "",
        answer,
        flags=re.DOTALL | re.IGNORECASE,
    ).strip()

    return answer


def ask_bi_chatbot(
    engine,
    session_id: str,
    user_message: str,
    selected_table: str | None = None,
    last_query_context: dict | None = None,
) -> dict:
    log_event(
        logger,
        "ask_bi_chatbot_start",
        session_id=session_id,
        user_message=user_message,
        selected_table=selected_table,
    )

    context = build_chat_context(
        engine=engine,
        user_message=user_message,
        selected_table=selected_table,
    )
    context["engine"] = engine

    history = get_session_messages(session_id)

    direct_result = _direct_catalog_answer(
        user_message,
        context,
        last_query_context=last_query_context,
        history=history,
    )
    if direct_result:
        answer = _cleanup_answer(direct_result.get("answer"))
        payload = {
            "answer": answer,
            "context": context,
            "table": direct_result.get("table"),
            "last_query_context": direct_result.get("last_query_context", last_query_context),
        }

        log_event(
            logger,
            "direct_catalog_answer_used",
            answer_preview=answer[:500],
            has_table=bool(payload["table"]),
        )

        append_session_message(session_id, "user", user_message)
        append_session_message(session_id, "assistant", answer)
        trim_session_messages(session_id, max_messages=20)
        return payload

    log_event(logger, "chat_history_loaded", session_id=session_id, history_count=len(history))

    client = get_openai_client()

    messages = [{"role": "system", "content": build_chat_system_prompt()}]

    for item in history[-12:]:
        messages.append(item)

    payload = {
        "user_message": user_message,
        "context": {
            "catalog_table_count": context["catalog_table_count"],
            "catalog_table_names_preview": context["catalog_table_names_preview"],
            "selected_table": context["selected_table"],
            "selected_table_summary": context["selected_table_summary"],
            "related_tables": context["related_tables"],
            "field_matches": context["field_matches"],
        },
    }

    messages.append(
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False),
        }
    )

    log_event(logger, "openai_request_start", session_id=session_id, model=OPENAI_MODEL, messages_count=len(messages))

    response = client.responses.create(
        model=OPENAI_MODEL,
        input=messages,
    )

    answer = _cleanup_answer(response.output_text)
    log_event(logger, "openai_request_end", session_id=session_id, answer_preview=answer[:800])

    append_session_message(session_id, "user", user_message)
    append_session_message(session_id, "assistant", answer)
    trim_session_messages(session_id, max_messages=20)

    return {
        "answer": answer,
        "context": context,
        "table": None,
        "last_query_context": last_query_context,
    }