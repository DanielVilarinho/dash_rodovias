from dotenv import load_dotenv
import os
import re
import unicodedata
import json

import pandas as pd
from sqlalchemy import create_engine, text

from dash import Dash, html, dcc, Input, Output, State
import dash_bootstrap_components as dbc

load_dotenv()


# =========================
# CONFIG
# =========================
DB_USER = os.getenv("SUPABASE_DB_USER")
DB_PASSWORD = os.getenv("SUPABASE_DB_PASSWORD")
DB_HOST = os.getenv("SUPABASE_DB_HOST")
DB_PORT = os.getenv("SUPABASE_DB_PORT", "5432")
DB_NAME = os.getenv("SUPABASE_DB_NAME")

TABLE_PREFIX = os.getenv("TABLE_PREFIX", "antt_")
CONTROL_PREFIX = os.getenv("CONTROL_PREFIX", "antt_antt_")

MAPTILER_KEY = os.getenv("MAPTILER_KEY", "")

if not MAPTILER_KEY:
    raise ValueError("Defina MAPTILER_KEY no .env")

engine = create_engine(
    f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}",
    pool_pre_ping=True,
    )

STYLE_URL_DEFAULT = f"https://api.maptiler.com/maps/satellite-v4/style.json?key=dbkJTOQN6k5qhYyC10HB"


# =========================
# HELPERS
# =========================
def normalize_legacy_text(text: str) -> str:
    text = str(text or "").replace("ç", "c").replace("Ç", "C")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text


def list_data_tables() -> list[str]:
    q = text("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name LIKE :prefix
        ORDER BY table_name
    """)
    df = pd.read_sql_query(q, engine, params={"prefix": f"{TABLE_PREFIX}%"})
    tables = df["table_name"].tolist()
    return [t for t in tables if not t.startswith(CONTROL_PREFIX)]


def get_table_columns(table_name: str) -> list[str]:
    if not table_name:
        return []

    q = text("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = :table_name
        ORDER BY ordinal_position
    """)
    df = pd.read_sql_query(q, engine, params={"table_name": table_name})
    return df["column_name"].tolist()


def load_table(table_name: str, limit: int | None = 5000) -> pd.DataFrame:
    if not table_name:
        return pd.DataFrame()

    sql = f'SELECT * FROM public."{table_name}"'
    if limit is not None:
        sql += f" LIMIT {int(limit)}"

    df = pd.read_sql_query(text(sql), engine)

    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].astype(str)

    return df


def _parse_number_br(value):
    if pd.isna(value):
        return None

    s = str(value).strip()
    if not s:
        return None

    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")

    try:
        return float(s)
    except Exception:
        return None


def _safe_text(value):
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value)


def clean_geo_df(
    df: pd.DataFrame,
    lat_col: str,
    lon_col: str,
    tooltip_col: str | None = None,
    color_col: str | None = None,
) -> pd.DataFrame:
    if df.empty or not lat_col or not lon_col:
        return pd.DataFrame()

    temp = df.copy()

    temp[lat_col] = temp[lat_col].apply(_parse_number_br)
    temp[lon_col] = temp[lon_col].apply(_parse_number_br)

    temp = temp.dropna(subset=[lat_col, lon_col]).copy()

    if tooltip_col and tooltip_col in temp.columns:
        temp["_tooltip"] = temp[tooltip_col].apply(_safe_text)
    else:
        temp["_tooltip"] = "Sem tooltip"

    if color_col and color_col in temp.columns:
        codes = temp[color_col].astype(str).astype("category").cat.codes.astype("int64")
        temp["_hex_color"] = codes.map(
            lambda x: "#{:02x}{:02x}{:02x}".format(
                int((x * 53) % 255),
                int((x * 97) % 255),
                int((x * 149) % 255),
            )
        )
    else:
        temp["_hex_color"] = "#3b82f6"

    return temp[[lat_col, lon_col, "_tooltip", "_hex_color"]].reset_index(drop=True)


def build_map_html(df: pd.DataFrame, lat_col: str, lon_col: str, style_url: str) -> str:
    points = []
    for _, row in df.iterrows():
        tooltip = str(row["_tooltip"]).replace("\\", "\\\\").replace("`", "\\`")
        points.append(
            {
                "lat": float(row[lat_col]),
                "lon": float(row[lon_col]),
                "tooltip": tooltip,
                "color": str(row["_hex_color"]),
            }
        )

    points_json = json.dumps(points, ensure_ascii=False)

    html_doc = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>MapLibre Test</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet" />
  <script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
  <style>
    html, body {{
      margin: 0;
      padding: 0;
      width: 100%;
      height: 100%;
      overflow: hidden;
      font-family: Arial, sans-serif;
    }}

    #map {{
      width: 100%;
      height: 100%;
    }}

    .custom-marker {{
      width: 14px;
      height: 14px;
      border-radius: 50%;
      border: 2px solid white;
      box-shadow: 0 0 0 1px rgba(0,0,0,0.12);
      cursor: pointer;
    }}

    .maplibregl-popup-content {{
      border-radius: 12px;
      padding: 10px 12px;
      font-size: 13px;
      color: #264653;
    }}
  </style>
</head>
<body>
  <div id="map"></div>

  <script>
    const styleUrl = `{style_url}`;
    const points = {points_json};

    const map = new maplibregl.Map({{
      container: 'map',
      style: styleUrl,
      center: [-51.9253, -14.2350],
      zoom: 4
    }});

    map.addControl(new maplibregl.NavigationControl(), 'top-right');

    map.on('load', () => {{
      const bounds = new maplibregl.LngLatBounds();

      points.forEach((p) => {{
        const el = document.createElement('div');
        el.className = 'custom-marker';
        el.style.background = p.color;

        const popup = new maplibregl.Popup({{ offset: 18 }})
          .setHTML(`<b>${{p.tooltip}}</b><br/>Lat: ${{p.lat}}<br/>Lon: ${{p.lon}}`);

        new maplibregl.Marker(el)
          .setLngLat([p.lon, p.lat])
          .setPopup(popup)
          .addTo(map);

        bounds.extend([p.lon, p.lat]);
      }});

      if (points.length > 0) {{
        map.fitBounds(bounds, {{ padding: 40, maxZoom: 14 }});
      }}
    }});
  </script>
</body>
</html>
"""
    return html_doc


# =========================
# APP
# =========================
tables = list_data_tables()

app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])
server = app.server

app.layout = dbc.Container(
    fluid=True,
    className="p-4",
    style={
        "minHeight": "100vh",
        "background": "linear-gradient(180deg, #f8fafc 0%, #fefefe 100%)",
    },
    children=[
        html.Div(
            style={
                "background": "rgba(255,255,255,0.92)",
                "borderRadius": "24px",
                "padding": "24px",
                "boxShadow": "0 10px 30px rgba(38,70,83,0.08)",
                "marginBottom": "20px",
            },
            children=[
                html.H2("Teste MapLibre + MapTiler", style={"color": "#264653", "marginBottom": "8px"}),
                html.P(
                    "Versão simples para testar style.json do MapTiler com pontos sobre o mapa.",
                    style={"color": "#5f6c7b", "marginBottom": "0"},
                ),
            ],
        ),

        dbc.Row(
            className="g-3 mb-3",
            children=[
                dbc.Col(
                    [
                        html.Div("Tabela", style={"fontWeight": "700", "marginBottom": "8px", "color": "#6b7280"}),
                        dcc.Dropdown(
                            id="table-selector",
                            options=[{"label": t, "value": t} for t in tables],
                            value='antt_quilometro_pista_marginal',
                            placeholder="Selecione uma tabela",
                            clearable=True,
                        ),
                    ],
                    md=3,
                ),
                dbc.Col(
                    [
                        html.Div("Latitude", style={"fontWeight": "700", "marginBottom": "8px", "color": "#6b7280"}),
                        dcc.Dropdown(id="lat-col", options=[]),
                    ],
                    md=2,
                ),
                dbc.Col(
                    [
                        html.Div("Longitude", style={"fontWeight": "700", "marginBottom": "8px", "color": "#6b7280"}),
                        dcc.Dropdown(id="lon-col", options=[]),
                    ],
                    md=2,
                ),
                dbc.Col(
                    [
                        html.Div("Tooltip", style={"fontWeight": "700", "marginBottom": "8px", "color": "#6b7280"}),
                        dcc.Dropdown(id="tooltip-col", options=[]),
                    ],
                    md=3,
                ),
                dbc.Col(
                    [
                        html.Div("Cor", style={"fontWeight": "700", "marginBottom": "8px", "color": "#6b7280"}),
                        dcc.Dropdown(id="color-col", options=[]),
                    ],
                    md=2,
                ),
            ],
        ),

        dbc.Row(
            className="g-3 mb-3",
            children=[
                dbc.Col(
                    [
                        html.Div("Style URL", style={"fontWeight": "700", "marginBottom": "8px", "color": "#6b7280"}),
                        dcc.Input(
                            id="style-url",
                            type="text",
                            value=STYLE_URL_DEFAULT,
                            style={"width": "100%", "height": "38px"},
                        ),
                    ],
                    md=6,
                ),
                dbc.Col(
                    [
                        html.Div("Limite de linhas", style={"fontWeight": "700", "marginBottom": "8px", "color": "#6b7280"}),
                        dcc.Dropdown(
                            id="row-limit",
                            options=[
                                {"label": "500", "value": 500},
                                {"label": "1.000", "value": 1000},
                                {"label": "5.000", "value": 5000},
                                {"label": "10.000", "value": 10000},
                            ],
                            value=1000,
                            clearable=False,
                        ),
                    ],
                    md=3,
                ),
                dbc.Col(
                    dbc.Button("Criar mapa", id="build-map", color="primary", size="lg"),
                    width="auto",
                    className="d-flex align-items-end",
                ),
            ],
        ),

        dcc.Loading(
            type="default",
            children=html.Div(
                id="map-container",
                style={
                    "background": "rgba(255,255,255,0.92)",
                    "borderRadius": "24px",
                    "padding": "18px",
                    "boxShadow": "0 10px 30px rgba(38,70,83,0.08)",
                    "minHeight": "760px",
                },
                children=html.Div(
                    "Selecione uma tabela e configure os campos para gerar o mapa.",
                    style={"color": "#6b7280", "padding": "40px", "textAlign": "center"},
                ),
            )
        ),
    ],
)


@app.callback(
    Output("lat-col", "options"),
    Output("lat-col", "value"),
    Output("lon-col", "options"),
    Output("lon-col", "value"),
    Output("tooltip-col", "options"),
    Output("color-col", "options"),
    Input("table-selector", "value"),
)
def update_column_options(table_name):
    if not table_name:
        return [], None, [], None, [], []

    columns = get_table_columns(table_name)
    options = [{"label": c, "value": c} for c in columns]

    lat_default = "latitude" if "latitude" in columns else None
    lon_default = "longitude" if "longitude" in columns else None

    return options, lat_default, options, lon_default, options, options


@app.callback(
    Output("map-container", "children"),
    Input("build-map", "n_clicks"),
    State("table-selector", "value"),
    State("lat-col", "value"),
    State("lon-col", "value"),
    State("tooltip-col", "value"),
    State("color-col", "value"),
    State("style-url", "value"),
    State("row-limit", "value"),
    prevent_initial_call=True,
)
def build_map(n_clicks, table_name, lat_col, lon_col, tooltip_col, color_col, style_url, row_limit):
    if not table_name or not lat_col or not lon_col:
        return html.Div(
            "Selecione tabela, latitude e longitude.",
            style={"color": "#b91c1c", "padding": "40px", "textAlign": "center"},
        )

    df = load_table(table_name, limit=row_limit)
    df = clean_geo_df(
        df=df,
        lat_col=lat_col,
        lon_col=lon_col,
        tooltip_col=tooltip_col,
        color_col=color_col,
    )

    if df.empty:
        return html.Div(
            "Nenhum dado válido com latitude/longitude após tratamento.",
            style={"color": "#b91c1c", "padding": "40px", "textAlign": "center"},
        )

    map_html = build_map_html(df, lat_col, lon_col, style_url)

    info = html.Div(
        [
            html.Div(f"Tabela: {table_name}", style={"fontWeight": "700", "color": "#264653"}),
            html.Div(f"Linhas carregadas: {len(df)}", style={"color": "#5f6c7b"}),
            html.Div("Render: MapLibre + Markers", style={"color": "#5f6c7b"}),
        ],
        style={
            "background": "#fdebd3",
            "borderRadius": "14px",
            "padding": "12px 14px",
            "marginBottom": "14px",
        },
    )

    return html.Div(
        [
            info,
            html.Iframe(
                srcDoc=map_html,
                style={
                    "width": "100%",
                    "height": "720px",
                    "border": "none",
                    "borderRadius": "18px",
                    "backgroundColor": "white",
                },
            ),
        ]
    )


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8050)