import json
from functools import lru_cache
from urllib.request import urlopen

import pandas as pd
import plotly.express as px
from dash import html


MAPTILER_STYLE_URL = "https://api.maptiler.com/maps/satellite-v4/style.json?key=dbkJTOQN6k5qhYyC10HB"

BRAZIL_UF_GEOJSON_URL = (
    "https://raw.githubusercontent.com/codeforamerica/click_that_hood/master/public/data/brazil-states.geojson"
)

UF_TO_STATE = {
    "AC": "Acre",
    "AL": "Alagoas",
    "AP": "Amapá",
    "AM": "Amazonas",
    "BA": "Bahia",
    "CE": "Ceará",
    "DF": "Distrito Federal",
    "ES": "Espírito Santo",
    "GO": "Goiás",
    "MA": "Maranhão",
    "MT": "Mato Grosso",
    "MS": "Mato Grosso do Sul",
    "MG": "Minas Gerais",
    "PA": "Pará",
    "PB": "Paraíba",
    "PR": "Paraná",
    "PE": "Pernambuco",
    "PI": "Piauí",
    "RJ": "Rio de Janeiro",
    "RN": "Rio Grande do Norte",
    "RS": "Rio Grande do Sul",
    "RO": "Rondônia",
    "RR": "Roraima",
    "SC": "Santa Catarina",
    "SP": "São Paulo",
    "SE": "Sergipe",
    "TO": "Tocantins",
}


def _safe_text(value):
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value)


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


def _hex_color_from_series(series: pd.Series) -> pd.Series:
    codes = series.astype(str).astype("category").cat.codes.astype("int64")
    return codes.map(
        lambda x: "#{:02x}{:02x}{:02x}".format(
            int((x * 53) % 255),
            int((x * 97) % 255),
            int((x * 149) % 255),
        )
    )


def apply_user_filters(df: pd.DataFrame, filters: list[dict] | None) -> pd.DataFrame:
    if df is None or df.empty or not filters:
        return df

    temp = df.copy()

    for f in filters:
        col = f.get("column")
        op = f.get("operator")
        raw_value = f.get("value")

        if not col or col not in temp.columns:
            continue

        if raw_value is None or str(raw_value).strip() == "":
            continue

        if op == "=":
            mask = temp[col].astype(str).str.strip().str.lower() == str(raw_value).strip().lower()
            temp = temp[mask]

        elif op in (">", "<"):
            series_num = pd.to_numeric(temp[col], errors="coerce")
            value_num = _parse_number_br(raw_value)
            if value_num is None:
                continue

            if op == ">":
                temp = temp[series_num > value_num]
            else:
                temp = temp[series_num < value_num]

    return temp.reset_index(drop=True)


def prepare_point_map_df(
    df: pd.DataFrame,
    lat_col: str,
    lon_col: str,
    tooltip_col: str | None = None,
    color_col: str | None = None,
    max_points: int = 1000,
) -> pd.DataFrame:
    if df is None or df.empty or not lat_col or not lon_col:
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
        temp["_hex_color"] = _hex_color_from_series(temp[color_col])
    else:
        temp["_hex_color"] = "#3b82f6"

    temp = temp[[lat_col, lon_col, "_tooltip", "_hex_color"]].reset_index(drop=True)

    max_points = int(max_points or 1000)
    if max_points > 0 and len(temp) > max_points:
        temp = temp.head(max_points).copy()

    return temp


def build_maplibre_point_component(
    df: pd.DataFrame,
    lat_col: str,
    lon_col: str,
    tooltip_col: str | None,
    color_col: str | None,
    height: int = 380,
    marker_type: str = "circle",
    marker_size: int = 14,
    style_url: str = MAPTILER_STYLE_URL,
    max_points: int = 1000,
):
    point_df = prepare_point_map_df(
        df=df,
        lat_col=lat_col,
        lon_col=lon_col,
        tooltip_col=tooltip_col,
        color_col=color_col,
        max_points=max_points,
    )

    if point_df.empty:
        return html.Div(
            "Nenhum dado válido para o mapa.",
            className="empty-state",
            style={"height": f"{height}px", "display": "flex", "alignItems": "center", "justifyContent": "center"},
        )

    points = []
    for _, row in point_df.iterrows():
        points.append(
            {
                "lat": float(row[lat_col]),
                "lon": float(row[lon_col]),
                "tooltip": str(row["_tooltip"]),
                "color": str(row["_hex_color"]),
            }
        )

    points_json = json.dumps(points, ensure_ascii=False)

    html_doc = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>MapLibre</title>
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
      background: white;
    }}
    #map {{
      width: 100%;
      height: 100%;
    }}
    .custom-marker {{
      cursor: pointer;
      box-shadow: 0 6px 14px rgba(0,0,0,0.18);
      border: 2px solid white;
      background: var(--marker-color);
      color: var(--marker-color);
    }}
    .marker-circle {{
      border-radius: 50%;
    }}
    .marker-square {{
      border-radius: 4px;
    }}
    .marker-diamond {{
      border-radius: 4px;
      transform: rotate(45deg);
    }}
    .marker-pulse {{
      border-radius: 50%;
      position: relative;
      animation: pulseScale 1.8s infinite;
    }}
    .marker-pulse::after {{
      content: "";
      position: absolute;
      inset: -6px;
      border-radius: 50%;
      border: 2px solid var(--marker-color);
      opacity: 0.45;
      animation: pulseRing 1.8s infinite;
    }}
    @keyframes pulseScale {{
      0% {{ transform: scale(1); }}
      50% {{ transform: scale(1.05); }}
      100% {{ transform: scale(1); }}
    }}
    @keyframes pulseRing {{
      0% {{ transform: scale(0.8); opacity: 0.7; }}
      70% {{ transform: scale(1.5); opacity: 0; }}
      100% {{ transform: scale(1.5); opacity: 0; }}
    }}
    .popup-wrap {{
      min-width: 180px;
      color: #264653;
    }}
    .popup-title {{
      font-weight: 700;
      margin-bottom: 8px;
      color: #1f3b4d;
      word-break: break-word;
    }}
    .popup-line {{
      font-size: 12px;
      color: #5f6c7b;
      margin-bottom: 2px;
    }}
    .maplibregl-popup-content {{
      border-radius: 14px;
      padding: 12px 14px;
      font-size: 13px;
      color: #264653;
      box-shadow: 0 10px 24px rgba(0,0,0,0.16);
    }}
  </style>
</head>
<body>
  <div id="map"></div>
  <script>
    const styleUrl = `{style_url}`;
    const points = {points_json};
    const markerType = "{marker_type}";
    const markerSize = {int(marker_size)};

    function escapeHtml(text) {{
      if (text === null || text === undefined) return "";
      return String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
    }}

    function buildPopupHtml(point) {{
      return `
        <div class="popup-wrap">
          <div class="popup-title">${{escapeHtml(point.tooltip)}}</div>
          <div class="popup-line">Lat: ${{point.lat}}</div>
          <div class="popup-line">Lon: ${{point.lon}}</div>
        </div>
      `;
    }}

    function buildMarkerElement(point) {{
      const el = document.createElement('div');
      el.className = `custom-marker marker-${{markerType}}`;
      el.style.width = `${{markerSize}}px`;
      el.style.height = `${{markerSize}}px`;
      el.style.setProperty('--marker-color', point.color);
      el.style.background = point.color;
      return el;
    }}

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
        const el = buildMarkerElement(p);

        const popup = new maplibregl.Popup({{ offset: 18 }})
          .setHTML(buildPopupHtml(p));

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

    return html.Iframe(
        srcDoc=html_doc,
        style={
            "width": "100%",
            "height": f"{height}px",
            "border": "none",
            "borderRadius": "18px",
            "backgroundColor": "white",
        },
    )


@lru_cache(maxsize=1)
def get_brazil_uf_geojson():
    with urlopen(BRAZIL_UF_GEOJSON_URL, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def build_brazil_uf_figure(
    df: pd.DataFrame,
    uf_col: str,
    agg_field: str | None,
    agg_mode: str,
    title: str,
    height: int,
):
    if df is None or df.empty or not uf_col or uf_col not in df.columns:
        return px.choropleth(), height

    temp = df.copy()
    temp[uf_col] = temp[uf_col].astype(str).str.strip().str.upper()
    temp = temp[temp[uf_col].isin(UF_TO_STATE.keys())].copy()

    if temp.empty:
        return px.choropleth(), height

    if agg_mode == "count":
        grouped = temp.groupby(uf_col, dropna=False).size().reset_index(name="metric")

    elif agg_mode == "distinct_count":
        if not agg_field or agg_field not in temp.columns:
            grouped = temp.groupby(uf_col, dropna=False).size().reset_index(name="metric")
        else:
            grouped = (
                temp.groupby(uf_col, dropna=False)[agg_field]
                .nunique(dropna=True)
                .reset_index(name="metric")
            )

    elif agg_mode == "sum":
        if not agg_field or agg_field not in temp.columns:
            grouped = temp.groupby(uf_col, dropna=False).size().reset_index(name="metric")
        else:
            num = pd.to_numeric(temp[agg_field], errors="coerce")
            temp = pd.DataFrame({uf_col: temp[uf_col], "metric": num}).dropna()
            grouped = temp.groupby(uf_col, dropna=False)["metric"].sum().reset_index()

    elif agg_mode == "percent_of_total":
        if agg_field and agg_field in temp.columns:
            num = pd.to_numeric(temp[agg_field], errors="coerce")
            temp = pd.DataFrame({uf_col: temp[uf_col], "metric": num}).dropna()
            grouped = temp.groupby(uf_col, dropna=False)["metric"].sum().reset_index()
        else:
            grouped = temp.groupby(uf_col, dropna=False).size().reset_index(name="metric")

        total = grouped["metric"].sum()
        if total:
            grouped["metric"] = grouped["metric"] / total * 100

    else:
        grouped = temp.groupby(uf_col, dropna=False).size().reset_index(name="metric")

    grouped["state_name"] = grouped[uf_col].map(UF_TO_STATE)
    grouped = grouped.dropna(subset=["state_name"]).copy()

    geojson = get_brazil_uf_geojson()

    fig = px.choropleth(
        grouped,
        geojson=geojson,
        locations="state_name",
        featureidkey="properties.name",
        color="metric",
        color_continuous_scale="Blues",
        hover_name="state_name",
        hover_data={uf_col: True, "metric": True},
        title=title,
    )

    fig.update_geos(fitbounds="locations", visible=False)
    fig.update_layout(
        height=height,
        paper_bgcolor="white",
        plot_bgcolor="white",
        margin=dict(l=10, r=10, t=60, b=10),
        coloraxis_colorbar_title="Valor",
        font=dict(color="#264653"),
    )

    return fig, height