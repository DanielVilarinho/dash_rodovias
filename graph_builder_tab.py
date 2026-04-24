import json
import uuid

import pandas as pd
import plotly.graph_objects as go
from dash import (
    html,
    dcc,
    Input,
    Output,
    State,
    ALL,
    callback_context,
)
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc

from load_data import load_table, get_table_columns
from graph_map_utils import (
    apply_user_filters,
    build_maplibre_point_component,
    build_brazil_uf_figure,
)


GRAPH_TYPES = [
    {"label": "Linha", "value": "line"},
    {"label": "Barras", "value": "bar"},
    {"label": "Colunas", "value": "column"},
    {"label": "Dispersão", "value": "scatter"},
    {"label": "Pizza", "value": "pie"},
    {"label": "Rosca", "value": "donut"},
    {"label": "Mapa de pontos", "value": "map_points"},
    {"label": "Mapa do Brasil por UF", "value": "map_br_uf"},
]

AGGREGATION_OPTIONS = [
    {"label": "Count", "value": "count"},
    {"label": "DistinctCount", "value": "distinct_count"},
    {"label": "Percent of Total", "value": "percent_of_total"},
    {"label": "Sum", "value": "sum"},
]

HEIGHT_OPTIONS = [
    {"label": "320 px", "value": 320},
    {"label": "380 px", "value": 380},
    {"label": "450 px", "value": 450},
    {"label": "520 px", "value": 520},
    {"label": "650 px", "value": 650},
]

MARKER_TYPE_OPTIONS = [
    {"label": "Círculo", "value": "circle"},
    {"label": "Quadrado", "value": "square"},
    {"label": "Losango", "value": "diamond"},
    {"label": "Pulse", "value": "pulse"},
]

MARKER_SIZE_OPTIONS = [
    {"label": "10", "value": 10},
    {"label": "12", "value": 12},
    {"label": "14", "value": 14},
    {"label": "18", "value": 18},
    {"label": "22", "value": 22},
]

MAP_MAX_LINES_OPTIONS = [
    {"label": "200", "value": 200},
    {"label": "500", "value": 500},
    {"label": "1000", "value": 1000},
    {"label": "2000", "value": 2000},
    {"label": "5000", "value": 5000},
]

FILTER_COUNT_OPTIONS = [{"label": str(i), "value": i} for i in range(0, 6)]

FILTER_OPERATORS = [
    {"label": "=", "value": "="},
    {"label": ">", "value": ">"},
    {"label": "<", "value": "<"},
]

GRAPH_COLORS = [
    "#93c5fd",
    "#86efac",
    "#f9a8d4",
    "#c4b5fd",
    "#fdba74",
    "#67e8f9",
    "#fca5a5",
    "#a7f3d0",
    "#ddd6fe",
    "#fde68a",
    "#99f6e4",
    "#fecdd3",
]


def build_filter_row(index: int, options: list[dict]):
    return html.Div(
        className="gb-filter-row",
        children=[
            dbc.Row(
                className="g-2 align-items-end",
                children=[
                    dbc.Col(
                        [
                            html.Div("Coluna", className="filter-label"),
                            dcc.Dropdown(
                                id={"type": "gb-global-filter-col", "index": index},
                                options=options,
                                className="table-dropdown",
                            ),
                        ],
                        md=4,
                    ),
                    dbc.Col(
                        [
                            html.Div("Operador", className="filter-label"),
                            dcc.Dropdown(
                                id={"type": "gb-global-filter-op", "index": index},
                                options=FILTER_OPERATORS,
                                value="=",
                                clearable=False,
                                className="table-dropdown",
                            ),
                        ],
                        md=2,
                    ),
                    dbc.Col(
                        [
                            html.Div("Valor", className="filter-label"),
                            dcc.Input(
                                id={"type": "gb-global-filter-val", "index": index},
                                type="text",
                                className="gb-input",
                            ),
                        ],
                        md=6,
                    ),
                ],
            )
        ],
    )


def make_preview_card(graph_type: str):
    graph_type = graph_type or "line"

    labels = {
        "line": "Linha",
        "bar": "Barras",
        "column": "Colunas",
        "scatter": "Dispersão",
        "pie": "Pizza",
        "donut": "Rosca",
        "map_points": "Mapa de pontos",
        "map_br_uf": "Mapa do Brasil por UF",
    }

    preview_class = f"graph-preview graph-preview--{graph_type}"

    return html.Div(
        className="graph-preview-box",
        children=[
            html.Div("Preview", className="graph-preview-title"),
            html.Div(className=preview_class),
            html.Div(labels.get(graph_type, "Linha"), className="graph-preview-caption"),
        ],
    )


def build_graph_builder_tab():
    return dcc.Tab(
        label="Graph Builder",
        value="tab-graph-builder",
        className="custom-tab",
        selected_className="custom-tab--selected",
        children=[
            html.Div(
                className="tab-content-wrap",
                children=[
                    dcc.Store(id="gb-charts-store", data=[]),
                    dcc.Store(id="gb-edit-chart-id", data=None),
                    dbc.Modal(
                        id="gb-modal",
                        is_open=False,
                        centered=True,
                        size="xl",
                        children=[
                            dbc.ModalHeader(dbc.ModalTitle("Adicionar / Editar gráfico")),
                            dbc.ModalBody(
                                [
                                    html.Div(
                                        className="gb-modal-grid",
                                        children=[
                                            html.Div(
                                                className="gb-modal-left",
                                                children=[
                                                    html.Div("Tipo de gráfico", className="filter-label"),
                                                    dcc.Dropdown(
                                                        id="gb-chart-type",
                                                        options=GRAPH_TYPES,
                                                        value="line",
                                                        clearable=False,
                                                        className="table-dropdown",
                                                    ),
                                                    html.Div(
                                                        id="gb-preview",
                                                        children=make_preview_card("line"),
                                                        className="gb-preview-wrap",
                                                    ),
                                                ],
                                            ),
                                            html.Div(
                                                className="gb-modal-right",
                                                children=[
                                                    html.Div("Título do gráfico", className="filter-label"),
                                                    dcc.Input(
                                                        id="gb-chart-title",
                                                        type="text",
                                                        placeholder="Ex.: Evolução por período",
                                                        className="gb-input",
                                                    ),
                                                    html.Div("Altura do container", className="filter-label"),
                                                    dcc.Dropdown(
                                                        id="gb-chart-height",
                                                        options=HEIGHT_OPTIONS,
                                                        value=380,
                                                        clearable=False,
                                                        className="table-dropdown",
                                                    ),
                                                    html.Div(
                                                        id="gb-agg-wrap",
                                                        children=[
                                                            html.Div("Agregação", className="filter-label"),
                                                            dcc.Dropdown(
                                                                id="gb-agg-mode",
                                                                options=AGGREGATION_OPTIONS,
                                                                value="count",
                                                                clearable=False,
                                                                className="table-dropdown",
                                                            ),
                                                        ],
                                                    ),
                                                    html.Div(
                                                        id="gb-x-wrap",
                                                        children=[
                                                            html.Div(id="gb-x-label", children="Eixo X / Categoria", className="filter-label"),
                                                            dcc.Dropdown(id="gb-x-col", options=[], className="table-dropdown"),
                                                        ],
                                                    ),
                                                    html.Div(
                                                        id="gb-y-wrap",
                                                        children=[
                                                            html.Div(id="gb-y-label", children="Campo de valor", className="filter-label"),
                                                            dcc.Dropdown(id="gb-y-col", options=[], className="table-dropdown"),
                                                        ],
                                                    ),
                                                    html.Div(
                                                        id="gb-value-wrap",
                                                        children=[
                                                            html.Div(id="gb-value-label", children="Coluna de categoria", className="filter-label"),
                                                            dcc.Dropdown(id="gb-value-col", options=[], className="table-dropdown"),
                                                        ],
                                                    ),
                                                    html.Div(
                                                        id="gb-extra-wrap",
                                                        children=[
                                                            html.Div(id="gb-extra-label", children="Campo extra", className="filter-label"),
                                                            dcc.Dropdown(id="gb-extra-col", options=[], className="table-dropdown"),
                                                        ],
                                                    ),
                                                    html.Div(
                                                        id="gb-map-marker-type-wrap",
                                                        children=[
                                                            html.Div("Tipo do marcador", className="filter-label"),
                                                            dcc.Dropdown(
                                                                id="gb-map-marker-type",
                                                                options=MARKER_TYPE_OPTIONS,
                                                                value="circle",
                                                                clearable=False,
                                                                className="table-dropdown",
                                                            ),
                                                        ],
                                                    ),
                                                    html.Div(
                                                        id="gb-map-marker-size-wrap",
                                                        children=[
                                                            html.Div("Tamanho do marcador", className="filter-label"),
                                                            dcc.Dropdown(
                                                                id="gb-map-marker-size",
                                                                options=MARKER_SIZE_OPTIONS,
                                                                value=14,
                                                                clearable=False,
                                                                className="table-dropdown",
                                                            ),
                                                        ],
                                                    ),
                                                    html.Div(
                                                        id="gb-map-max-lines-wrap",
                                                        children=[
                                                            html.Div("Máximo de linhas no mapa", className="filter-label"),
                                                            dcc.Dropdown(
                                                                id="gb-map-max-lines",
                                                                options=MAP_MAX_LINES_OPTIONS,
                                                                value=1000,
                                                                clearable=False,
                                                                className="table-dropdown",
                                                            ),
                                                        ],
                                                    ),
                                                ],
                                            ),
                                        ],
                                    )
                                ]
                            ),
                            dbc.ModalFooter(
                                [
                                    dbc.Button("Cancelar", id="gb-cancel", color="light"),
                                    dbc.Button("Salvar gráfico", id="gb-save", color="primary"),
                                ]
                            ),
                        ],
                    ),
                    html.Div(
                        className="table-card graph-builder-card",
                        children=[
                            html.Div(
                                className="graph-builder-header",
                                children=[
                                    html.Div(
                                        [
                                            html.H3("Graph Builder", className="graph-builder-title"),
                                            html.P(
                                                "Monte gráficos a partir da tabela selecionada no topo.",
                                                className="graph-builder-subtitle",
                                            ),
                                        ]
                                    ),
                                    dbc.Button("Adicionar gráfico", id="gb-open-modal", color="primary"),
                                ],
                            ),
                            html.Div(id="gb-table-status", className="description-box"),
                            dbc.Accordion(
                                [
                                    dbc.AccordionItem(
                                        [
                                            html.Div("Quantidade de filtros", className="filter-label"),
                                            dcc.Dropdown(
                                                id="gb-global-filter-count",
                                                options=FILTER_COUNT_OPTIONS,
                                                value=0,
                                                clearable=False,
                                                className="table-dropdown",
                                            ),
                                            html.Div(id="gb-global-filters-rows", className="gb-filters-rows"),
                                        ],
                                        title="Filtros globais do tab",
                                    )
                                ],
                                start_collapsed=True,
                                always_open=False,
                                className="gb-filters-accordion mb-3",
                            ),
                            html.Div(
                                id="gb-empty-state",
                                className="gb-empty-state",
                                children=[
                                    html.Button("+", id="gb-open-modal-plus", className="gb-plus-button"),
                                    html.Div("Nenhum gráfico adicionado", className="gb-empty-title"),
                                    html.Div(
                                        "Escolha uma tabela no dropdown e clique para criar seu primeiro gráfico.",
                                        className="gb-empty-subtitle",
                                    ),
                                ],
                            ),
                            html.Div(id="gb-charts-container", className="gb-charts-grid"),
                        ],
                    ),
                ],
            )
        ],
    )


def _safe_numeric_series(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _format_value(v, agg_mode: str):
    if pd.isna(v):
        return ""
    if agg_mode == "percent_of_total":
        return f"{float(v):.2f}%"
    if float(v).is_integer():
        return f"{int(v)}"
    return f"{float(v):.2f}"


def _compute_grouped(df: pd.DataFrame, x_col: str, y_col: str | None, agg_mode: str) -> pd.DataFrame:
    temp = df.copy()
    temp[x_col] = temp[x_col].fillna("Vazio").astype(str)

    if agg_mode == "count":
        return temp.groupby(x_col, dropna=False).size().reset_index(name="metric")

    if agg_mode == "distinct_count":
        if not y_col:
            return pd.DataFrame(columns=[x_col, "metric"])
        return temp.groupby(x_col, dropna=False)[y_col].nunique(dropna=True).reset_index(name="metric")

    if agg_mode == "percent_of_total":
        if y_col:
            y = _safe_numeric_series(temp[y_col])
            temp = pd.DataFrame({x_col: temp[x_col], "metric": y}).dropna()
            grouped = temp.groupby(x_col, dropna=False)["metric"].sum().reset_index()
        else:
            grouped = temp.groupby(x_col, dropna=False).size().reset_index(name="metric")

        total = grouped["metric"].sum()
        if total and total != 0:
            grouped["metric"] = grouped["metric"] / total * 100
        return grouped

    if agg_mode == "sum":
        if not y_col:
            return pd.DataFrame(columns=[x_col, "metric"])
        y = _safe_numeric_series(temp[y_col])
        temp = pd.DataFrame({x_col: temp[x_col], "metric": y}).dropna()
        return temp.groupby(x_col, dropna=False)["metric"].sum().reset_index()

    return pd.DataFrame(columns=[x_col, "metric"])


def _build_custom_legend(spec: dict, df: pd.DataFrame):
    graph_type = spec.get("type")
    value_col = spec.get("value")

    if graph_type not in ("pie", "donut") or not value_col or value_col not in df.columns:
        return None

    counts = (
        df[value_col]
        .fillna("Vazio")
        .astype(str)
        .value_counts(dropna=False)
        .reset_index()
    )
    counts.columns = [value_col, "count"]

    total = counts["count"].sum()
    counts["pct"] = counts["count"] / total * 100 if total > 0 else 0

    items = []
    for i, row in counts.iterrows():
        color = GRAPH_COLORS[i % len(GRAPH_COLORS)]
        items.append(
            html.Div(
                className="custom-legend-item",
                children=[
                    html.Span(className="custom-legend-color", style={"backgroundColor": color}),
                    html.Div(
                        className="custom-legend-text-wrap",
                        children=[
                            html.Div(str(row[value_col]), className="custom-legend-label"),
                            html.Div(f'{row["pct"]:.2f}% ({int(row["count"])})', className="custom-legend-value"),
                        ],
                    ),
                ],
            )
        )

    return html.Div(
        className="custom-legend-box",
        children=[
            html.Div("Legenda", className="custom-legend-title"),
            html.Div(className="custom-legend-scroll", children=items),
        ],
    )


def build_figure(df: pd.DataFrame, spec: dict):
    graph_type = spec.get("type")
    title = spec.get("title") or "Gráfico"
    x_col = spec.get("x")
    y_col = spec.get("y")
    value_col = spec.get("value")
    agg_mode = spec.get("agg_mode", "count")
    container_height = int(spec.get("height", 380) or 380)

    if graph_type == "map_br_uf":
        return build_brazil_uf_figure(
            df=df,
            uf_col=x_col,
            agg_field=y_col,
            agg_mode=agg_mode,
            title=title,
            height=container_height,
        )

    fig = go.Figure()
    auto_scroll_height = container_height

    if graph_type == "line" and x_col:
        grouped = _compute_grouped(df, x_col, y_col, agg_mode)
        if not grouped.empty:
            grouped["label_text"] = grouped["metric"].apply(lambda v: _format_value(v, agg_mode))
            fig.add_trace(
                go.Scatter(
                    x=grouped[x_col],
                    y=grouped["metric"],
                    mode="lines+markers+text",
                    text=grouped["label_text"],
                    textposition="top center",
                    line=dict(color=GRAPH_COLORS[0], width=3),
                    marker=dict(size=7, color=GRAPH_COLORS[0]),
                    name=agg_mode,
                )
            )

    elif graph_type == "bar" and x_col:
        grouped = _compute_grouped(df, x_col, y_col, agg_mode)
        if not grouped.empty:
            grouped = grouped.sort_values("metric", ascending=True)
            grouped["label_text"] = grouped["metric"].apply(lambda v: _format_value(v, agg_mode))
            auto_scroll_height = max(container_height, 120 + len(grouped) * 32)
            fig.add_trace(
                go.Bar(
                    x=grouped["metric"],
                    y=grouped[x_col],
                    orientation="h",
                    marker=dict(color=GRAPH_COLORS[1]),
                    text=grouped["label_text"],
                    textposition="outside",
                    cliponaxis=False,
                    name=agg_mode,
                )
            )

    elif graph_type == "column" and x_col:
        grouped = _compute_grouped(df, x_col, y_col, agg_mode)
        if not grouped.empty:
            grouped["label_text"] = grouped["metric"].apply(lambda v: _format_value(v, agg_mode))
            fig.add_trace(
                go.Bar(
                    x=grouped[x_col],
                    y=grouped["metric"],
                    marker=dict(color=GRAPH_COLORS[2]),
                    text=grouped["label_text"],
                    textposition="outside",
                    cliponaxis=False,
                    name=agg_mode,
                )
            )

    elif graph_type == "scatter" and x_col and y_col:
        x = _safe_numeric_series(df[x_col])
        y = _safe_numeric_series(df[y_col])
        temp = pd.DataFrame({x_col: x, y_col: y}).dropna()
        temp["label_text"] = temp[y_col].apply(lambda v: _format_value(v, "sum"))
        fig.add_trace(
            go.Scatter(
                x=temp[x_col],
                y=temp[y_col],
                mode="markers+text",
                text=temp["label_text"],
                textposition="top center",
                marker=dict(size=9, color=GRAPH_COLORS[3], opacity=0.75),
                name=f"{x_col} x {y_col}",
            )
        )

    elif graph_type in ("pie", "donut") and value_col and value_col in df.columns:
        counts = (
            df[value_col]
            .fillna("Vazio")
            .astype(str)
            .value_counts(dropna=False)
            .reset_index()
        )
        counts.columns = [value_col, "count"]

        fig.add_trace(
            go.Pie(
                labels=counts[value_col],
                values=counts["count"],
                hole=0.45 if graph_type == "donut" else 0,
                marker=dict(colors=GRAPH_COLORS),
                textinfo="percent+label",
                textposition="auto",
                hovertemplate="%{label}<br>%{percent}<br>Qtd: %{value}<extra></extra>",
                sort=False,
            )
        )

    yaxis_title = "Valor"
    if agg_mode == "percent_of_total":
        yaxis_title = "% do total"
    elif agg_mode == "count":
        yaxis_title = "Count"
    elif agg_mode == "distinct_count":
        yaxis_title = "DistinctCount"
    elif agg_mode == "sum":
        yaxis_title = f"Soma de {y_col}" if y_col else "Soma"

    fig.update_layout(
        title=title,
        paper_bgcolor="white",
        plot_bgcolor="white",
        font=dict(color="#264653"),
        margin=dict(l=40, r=20, t=60, b=40),
        height=auto_scroll_height if graph_type == "bar" else container_height,
        autosize=True,
        showlegend=False if graph_type in ("pie", "donut") else True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            x=0,
            font=dict(size=11),
        ),
    )

    if graph_type in ("line", "column", "scatter"):
        fig.update_xaxes(showgrid=True, gridcolor="#edf2f7")
        fig.update_yaxes(showgrid=True, gridcolor="#edf2f7", title=yaxis_title)

    if graph_type == "bar":
        fig.update_xaxes(showgrid=True, gridcolor="#edf2f7", title=yaxis_title)
        fig.update_yaxes(showgrid=False, automargin=True)

    return fig, auto_scroll_height


def register_graph_builder_callbacks(app, engine):
    @app.callback(
        Output("gb-table-status", "children"),
        Output("gb-x-col", "options"),
        Output("gb-y-col", "options"),
        Output("gb-value-col", "options"),
        Output("gb-extra-col", "options"),
        Input("table-selector", "value"),
    )
    def update_graph_builder_columns(table_name):
        if not table_name:
            empty_options = []
            return (
                html.Div(
                    [
                        html.Div("Tabela não selecionada", className="description-title"),
                        html.Div(
                            "Escolha uma tabela no dropdown principal para habilitar o Graph Builder.",
                            className="description-text",
                        ),
                    ]
                ),
                empty_options,
                empty_options,
                empty_options,
                empty_options,
            )

        columns = get_table_columns(engine, table_name)
        options = [{"label": c, "value": c} for c in columns]

        return (
            html.Div(
                [
                    html.Div("Tabela pronta", className="description-title"),
                    html.Div(
                        f"A tabela {table_name} está disponível para criação de gráficos.",
                        className="description-text",
                    ),
                ]
            ),
            options,
            options,
            options,
            options,
        )

    @app.callback(
        Output("gb-global-filters-rows", "children"),
        Input("gb-global-filter-count", "value"),
        Input("table-selector", "value"),
    )
    def render_global_filter_rows(filter_count, table_name):
        if not table_name:
            return []

        columns = get_table_columns(engine, table_name)
        options = [{"label": c, "value": c} for c in columns]

        rows = []
        for i in range(int(filter_count or 0)):
            rows.append(build_filter_row(i, options))
        return rows

    @app.callback(
        Output("gb-preview", "children"),
        Output("gb-x-wrap", "style"),
        Output("gb-y-wrap", "style"),
        Output("gb-value-wrap", "style"),
        Output("gb-extra-wrap", "style"),
        Output("gb-agg-wrap", "style"),
        Output("gb-map-marker-type-wrap", "style"),
        Output("gb-map-marker-size-wrap", "style"),
        Output("gb-map-max-lines-wrap", "style"),
        Output("gb-x-label", "children"),
        Output("gb-y-label", "children"),
        Output("gb-value-label", "children"),
        Output("gb-extra-label", "children"),
        Input("gb-chart-type", "value"),
    )
    def update_graph_type_ui(graph_type):
        preview = make_preview_card(graph_type)

        if graph_type in ("pie", "donut"):
            return (
                preview,
                {"display": "none"},
                {"display": "none"},
                {"display": "block"},
                {"display": "none"},
                {"display": "none"},
                {"display": "none"},
                {"display": "none"},
                {"display": "none"},
                "Eixo X / Categoria",
                "Campo de valor",
                "Coluna de categoria",
                "Campo extra",
            )

        if graph_type == "scatter":
            return (
                preview,
                {"display": "block"},
                {"display": "block"},
                {"display": "none"},
                {"display": "none"},
                {"display": "none"},
                {"display": "none"},
                {"display": "none"},
                {"display": "none"},
                "Eixo X",
                "Eixo Y",
                "Coluna de categoria",
                "Campo extra",
            )

        if graph_type == "map_points":
            return (
                preview,
                {"display": "block"},
                {"display": "block"},
                {"display": "block"},
                {"display": "block"},
                {"display": "none"},
                {"display": "block"},
                {"display": "block"},
                {"display": "block"},
                "Latitude",
                "Longitude",
                "Tooltip",
                "Cor",
            )

        if graph_type == "map_br_uf":
            return (
                preview,
                {"display": "block"},
                {"display": "block"},
                {"display": "none"},
                {"display": "none"},
                {"display": "block"},
                {"display": "none"},
                {"display": "none"},
                {"display": "none"},
                "Campo UF",
                "Campo para agregação",
                "Tooltip",
                "Campo extra",
            )

        return (
            preview,
            {"display": "block"},
            {"display": "block"},
            {"display": "none"},
            {"display": "none"},
            {"display": "block"},
            {"display": "none"},
            {"display": "none"},
            {"display": "none"},
            "Eixo X / Categoria",
            "Campo de valor",
            "Coluna de categoria",
            "Campo extra",
        )

    @app.callback(
        Output("gb-modal", "is_open"),
        Output("gb-edit-chart-id", "data"),
        Output("gb-chart-type", "value"),
        Output("gb-chart-title", "value"),
        Output("gb-chart-height", "value"),
        Output("gb-agg-mode", "value"),
        Output("gb-x-col", "value"),
        Output("gb-y-col", "value"),
        Output("gb-value-col", "value"),
        Output("gb-extra-col", "value"),
        Output("gb-map-marker-type", "value"),
        Output("gb-map-marker-size", "value"),
        Output("gb-map-max-lines", "value"),
        Input("gb-open-modal", "n_clicks"),
        Input("gb-open-modal-plus", "n_clicks"),
        Input("gb-cancel", "n_clicks"),
        Input("gb-save", "n_clicks"),
        Input({"type": "gb-edit-btn", "index": ALL}, "n_clicks"),
        State("gb-charts-store", "data"),
        prevent_initial_call=True,
    )
    def toggle_modal(
        open_click,
        open_plus_click,
        cancel_click,
        save_click,
        edit_clicks,
        charts_data,
    ):
        ctx = callback_context
        if not ctx.triggered:
            raise PreventUpdate

        trigger = ctx.triggered[0]["prop_id"].split(".")[0]
        default_values = (
            None,
            "line",
            "",
            380,
            "count",
            None,
            None,
            None,
            None,
            "circle",
            14,
            1000,
        )

        if trigger in ("gb-open-modal", "gb-open-modal-plus"):
            return True, *default_values

        if trigger in ("gb-cancel", "gb-save"):
            return False, *default_values

        if trigger.startswith("{"):
            trigger_dict = json.loads(trigger)
            edit_id = trigger_dict.get("index")
            charts_data = charts_data or []
            chart = next((c for c in charts_data if c.get("id") == edit_id), None)
            if not chart:
                raise PreventUpdate

            return (
                True,
                chart.get("id"),
                chart.get("type", "line"),
                chart.get("title", ""),
                chart.get("height", 380),
                chart.get("agg_mode", "count"),
                chart.get("x"),
                chart.get("y"),
                chart.get("value"),
                chart.get("extra"),
                chart.get("map_marker_type", "circle"),
                chart.get("map_marker_size", 14),
                chart.get("map_max_lines", 1000),
            )

        raise PreventUpdate

    @app.callback(
        Output("gb-charts-store", "data"),
        Input("gb-save", "n_clicks"),
        Input({"type": "gb-delete-btn", "index": ALL}, "n_clicks"),
        State("gb-charts-store", "data"),
        State("gb-edit-chart-id", "data"),
        State("table-selector", "value"),
        State("gb-chart-type", "value"),
        State("gb-chart-title", "value"),
        State("gb-chart-height", "value"),
        State("gb-agg-mode", "value"),
        State("gb-x-col", "value"),
        State("gb-y-col", "value"),
        State("gb-value-col", "value"),
        State("gb-extra-col", "value"),
        State("gb-map-marker-type", "value"),
        State("gb-map-marker-size", "value"),
        State("gb-map-max-lines", "value"),
        prevent_initial_call=True,
    )
    def save_or_delete_chart(
        n_clicks_save,
        delete_clicks,
        current_data,
        edit_chart_id,
        table_name,
        chart_type,
        chart_title,
        chart_height,
        agg_mode,
        x_col,
        y_col,
        value_col,
        extra_col,
        map_marker_type,
        map_marker_size,
        map_max_lines,
    ):
        ctx = callback_context
        if not ctx.triggered:
            raise PreventUpdate

        current_data = current_data or []
        trigger = ctx.triggered[0]["prop_id"].split(".")[0]

        if trigger.startswith("{"):
            trigger_dict = json.loads(trigger)
            delete_id = trigger_dict.get("index")

            clicked_value = 0
            for item in ctx.inputs_list[1]:
                if item["id"]["index"] == delete_id:
                    clicked_value = item["value"] or 0
                    break

            if clicked_value <= 0:
                raise PreventUpdate

            return [c for c in current_data if c.get("id") != delete_id]

        if not table_name or not n_clicks_save:
            raise PreventUpdate

        if chart_type in ("pie", "donut"):
            if not value_col:
                raise PreventUpdate

        elif chart_type == "scatter":
            if not x_col or not y_col:
                raise PreventUpdate

        elif chart_type == "map_points":
            if not x_col or not y_col:
                raise PreventUpdate

        elif chart_type == "map_br_uf":
            if not x_col:
                raise PreventUpdate
            if agg_mode in ("sum", "distinct_count") and not y_col:
                raise PreventUpdate

        else:
            if not x_col:
                raise PreventUpdate
            if agg_mode in ("sum", "distinct_count") and not y_col:
                raise PreventUpdate

        spec = {
            "id": edit_chart_id or str(uuid.uuid4()),
            "type": chart_type,
            "title": chart_title or f"Gráfico {len(current_data) + 1}",
            "height": int(chart_height or 380),
            "agg_mode": agg_mode,
            "x": x_col,
            "y": y_col,
            "value": value_col,
            "extra": extra_col,
            "map_marker_type": map_marker_type or "circle",
            "map_marker_size": int(map_marker_size or 14),
            "map_max_lines": int(map_max_lines or 1000),
        }

        if edit_chart_id:
            updated = []
            found = False
            for chart in current_data:
                if chart.get("id") == edit_chart_id:
                    updated.append(spec)
                    found = True
                else:
                    updated.append(chart)

            if not found:
                updated.append(spec)

            return updated

        return current_data + [spec]

    @app.callback(
        Output("gb-empty-state", "style"),
        Output("gb-charts-container", "children"),
        Input("gb-charts-store", "data"),
        Input("table-selector", "value"),
        Input({"type": "gb-global-filter-col", "index": ALL}, "value"),
        Input({"type": "gb-global-filter-op", "index": ALL}, "value"),
        Input({"type": "gb-global-filter-val", "index": ALL}, "value"),
    )
    def render_graphs(charts_data, table_name, global_filter_cols, global_filter_ops, global_filter_vals):
        charts_data = charts_data or []

        if not charts_data:
            return {"display": "flex"}, []

        if not table_name:
            return {"display": "flex"}, []

        df_full = load_table(engine, table_name, limit=None)

        global_filters = []
        for col, op, val in zip(global_filter_cols or [], global_filter_ops or [], global_filter_vals or []):
            if col and op and str(val).strip() != "":
                global_filters.append({"column": col, "operator": op, "value": str(val)})

        df_base = apply_user_filters(df_full, global_filters)

        chart_cards = []
        for i, spec in enumerate(charts_data, start=1):
            container_height = int(spec.get("height", 380) or 380)
            graph_type = spec.get("type")

            if graph_type == "map_points":
                graph_component = build_maplibre_point_component(
                    df=df_base,
                    lat_col=spec.get("x"),
                    lon_col=spec.get("y"),
                    tooltip_col=spec.get("value"),
                    color_col=spec.get("extra"),
                    height=container_height,
                    marker_type=spec.get("map_marker_type", "circle"),
                    marker_size=spec.get("map_marker_size", 14),
                    max_points=spec.get("map_max_lines", 1000),
                )

                body = html.Div(
                    className="graph-card-body graph-card-body--single",
                    children=[graph_component],
                )

            else:
                fig, graph_height = build_figure(df_base, spec)
                custom_legend = _build_custom_legend(spec, df_base)

                body = html.Div(
                    className="graph-card-body",
                    children=[
                        html.Div(
                            className="graph-main-area",
                            style={
                                "height": f"{container_height}px",
                                "overflowY": "auto",
                                "overflowX": "hidden",
                                "width": "100%",
                            },
                            children=[
                                dcc.Graph(
                                    figure=fig,
                                    config={"displayModeBar": True, "responsive": True},
                                    style={"width": "100%", "height": f"{graph_height}px"},
                                )
                            ],
                        ),
                        custom_legend if custom_legend is not None else html.Div(),
                    ],
                )

            chart_cards.append(
                html.Div(
                    className="graph-card",
                    children=[
                        html.Div(
                            className="graph-card-header",
                            children=[
                                html.Div(
                                    className="graph-card-title",
                                    children=spec.get("title") or f"Gráfico {i}",
                                ),
                                html.Div(
                                    className="graph-card-actions",
                                    children=[
                                        dbc.Button(
                                            "Editar",
                                            id={"type": "gb-edit-btn", "index": spec["id"]},
                                            color="light",
                                            size="sm",
                                            className="graph-card-btn",
                                            n_clicks=0,
                                        ),
                                        dbc.Button(
                                            "Excluir",
                                            id={"type": "gb-delete-btn", "index": spec["id"]},
                                            color="danger",
                                            outline=True,
                                            size="sm",
                                            className="graph-card-btn",
                                            n_clicks=0,
                                        ),
                                    ],
                                ),
                            ],
                        ),
                        body,
                    ],
                )
            )

        return {"display": "none"}, chart_cards