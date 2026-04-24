import json
import os

from dotenv import load_dotenv
from openai import OpenAI

from assistant_schemas import ASSISTANT_ACTION_SCHEMA
from assistant_tools import build_bi_context, search_metadata

load_dotenv()

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


def get_openai_client():
    if not OPENAI_API_KEY:
        raise ValueError("Defina OPENAI_API_KEY no .env")
    return OpenAI(api_key=OPENAI_API_KEY)


def build_system_prompt() -> str:
    return """
Você é um copiloto de BI acoplado a um Graph Builder.

Sua função é ajudar a criar gráficos válidos com base no catálogo disponível.

Regras gerais:
- Nunca invente tabela ou coluna.
- Use apenas a tabela selecionada no contexto atual.
- Se não houver contexto suficiente, responda action=answer_only.
- Use somente os tipos de gráfico suportados.
- Responda sempre no schema JSON solicitado.

Tipos de gráfico suportados:
- line
- bar
- column
- scatter
- pie
- donut
- map_points
- map_br_uf

Regras por gráfico:
1. line / bar / column
- use x como categoria
- use y quando a agregação for sum ou distinct_count
- para count e percent_of_total, y pode ser null

2. scatter
- use x e y
- ambos devem ser campos numéricos plausíveis

3. pie / donut
- use value como coluna categórica
- x e y podem ser null
- agg_mode geralmente count

4. map_points
- use x para latitude
- use y para longitude
- use value para tooltip quando houver
- use extra para cor quando houver
- defina map_marker_type
- defina map_marker_size
- defina map_max_lines
- agg_mode pode ficar como count

5. map_br_uf
- use x para o campo UF
- use y para o campo de agregação quando necessário
- se o pedido for mapa por UF, prefira map_br_uf
- se o usuário pedir contagem por UF, use agg_mode=count
- se pedir distinct count ou sum, use y adequadamente

Defaults recomendados:
- height = 650 quando o usuário pedir maior tamanho possível
- senão use 380
- map_marker_type = circle
- map_marker_size = 14
- map_max_lines = 1000

Regra de fallback importante:
- Se o usuário não informar explicitamente o campo de contagem/valor/agregação em gráficos que usam esse tipo de campo, use "id_dataset" como padrão, desde que essa coluna exista na tabela atual.
- Essa regra vale principalmente para bar, column, line e map_br_uf quando houver necessidade de um campo de apoio para distinct_count ou sum.
- Para pie e donut, se o usuário não passar campo categórico, use o melhor campo categórico disponível; não use id_dataset como categoria.

Importante:
- Se o usuário pedir "mapa usando campo uf", isso deve virar map_br_uf, não bar/column.
- Se o usuário pedir "mapa com latitude e longitude", isso deve virar map_points.
- Se não conseguir montar com segurança, use action=answer_only explicando o motivo.
"""


def _normalize_chart_payload(chart: dict | None, available_columns: list[str] | None = None) -> dict | None:
    if not chart:
        return None

    available_columns = available_columns or []
    has_id_dataset = "id_dataset" in available_columns

    chart_type = chart.get("type")

    normalized = {
        "type": chart_type,
        "title": chart.get("title") or "Gráfico",
        "height": int(chart.get("height") or 380),
        "agg_mode": chart.get("agg_mode") or "count",
        "x": chart.get("x"),
        "y": chart.get("y"),
        "value": chart.get("value"),
        "extra": chart.get("extra"),
        "map_marker_type": chart.get("map_marker_type") or "circle",
        "map_marker_size": int(chart.get("map_marker_size") or 14),
        "map_max_lines": int(chart.get("map_max_lines") or 1000),
    }

    if has_id_dataset:
        if chart_type in ("line", "bar", "column", "map_br_uf"):
            if normalized["agg_mode"] in ("distinct_count", "sum") and not normalized["y"]:
                normalized["y"] = "id_dataset"

    if chart_type == "map_br_uf":
        normalized["map_marker_type"] = None
        normalized["map_marker_size"] = None
        normalized["map_max_lines"] = None

    if chart_type in ("line", "bar", "column", "scatter", "pie", "donut"):
        if chart_type != "scatter":
            normalized["extra"] = None
        normalized["map_marker_type"] = None
        normalized["map_marker_size"] = None
        normalized["map_max_lines"] = None

    if chart_type in ("pie", "donut"):
        normalized["y"] = None
        normalized["extra"] = None
        normalized["map_marker_type"] = None
        normalized["map_marker_size"] = None
        normalized["map_max_lines"] = None

    if chart_type == "scatter":
        normalized["value"] = None
        normalized["extra"] = None
        normalized["map_marker_type"] = None
        normalized["map_marker_size"] = None
        normalized["map_max_lines"] = None

    return normalized


def suggest_chart_from_prompt(engine, prompt: str, selected_table: str | None = None) -> dict:
    client = get_openai_client()

    context = build_bi_context(engine, selected_table=selected_table)
    available_columns = []
    if context.get("tables"):
        available_columns = context["tables"][0].get("columns", [])

    metadata_search = search_metadata(engine, prompt)

    user_input = {
        "user_prompt": prompt,
        "context": context,
        "metadata_search": metadata_search,
    }

    response = client.responses.create(
        model=OPENAI_MODEL,
        input=[
            {"role": "system", "content": build_system_prompt()},
            {"role": "user", "content": json.dumps(user_input, ensure_ascii=False)},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": ASSISTANT_ACTION_SCHEMA["name"],
                "schema": ASSISTANT_ACTION_SCHEMA["schema"],
            }
        },
    )

    raw_text = response.output_text
    data = json.loads(raw_text)

    if data.get("action") == "create_chart" and data.get("chart"):
        normalized_chart = _normalize_chart_payload(
            data["chart"],
            available_columns=available_columns,
        )
        return {
            "ok": True,
            "message": data.get("message", "Gráfico sugerido com sucesso."),
            "chart": normalized_chart,
        }

    return {
        "ok": False,
        "message": data.get("message", "Não foi possível sugerir um gráfico com segurança."),
        "chart": None,
    }