import pandas as pd
from dash import Dash, html, dcc, dash_table, Input, Output
import dash_bootstrap_components as dbc

from config import APP_TITLE
from load_data import (
    get_engine,
    list_antt_tables,
    load_table,
    dataframe_for_dash,
    get_table_total_rows,
    get_table_metadata_map,
    get_dictionary_fields_for_table,
)
from graph_builder_tab import build_graph_builder_tab, register_graph_builder_callbacks

engine = get_engine()
data_tables, control_tables = list_antt_tables(engine)
table_metadata_map = get_table_metadata_map(engine, data_tables)

DEFAULT_PAGE_SIZE = 100
PAGE_SIZE_OPTIONS = [20, 50, 100, 200, 500]

initial_table = None
resources_dim_df = dataframe_for_dash(load_table(engine, "antt_antt_recursos_dim"))
dictionary_full_df = dataframe_for_dash(load_table(engine, "antt_antt_dicionarios_campos"))


app = Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    title=APP_TITLE,
)
server = app.server


def build_table(df, table_id="main-table", page_size=DEFAULT_PAGE_SIZE):
    if df is None or df.empty:
        return html.Div(
            "Nenhum dado encontrado para esta visualização.",
            className="empty-state"
        )

    return dash_table.DataTable(
        id=table_id,
        columns=[{"name": c, "id": c} for c in df.columns],
        data=df.to_dict("records"),
        sort_action="native",
        filter_action="native",
        page_action="native",
        page_current=0,
        page_size=page_size,
        style_as_list_view=True,
        style_table={
            "overflowX": "auto",
            "borderRadius": "18px",
            "position": "relative",
            "zIndex": 1,
            "maxHeight": "72vh",
        },
        style_header={
            "backgroundColor": "#dbeafe",
            "color": "#264653",
            "fontWeight": "700",
            "border": "none",
            "padding": "14px 12px",
            "fontFamily": "Arial, sans-serif",
            "position": "sticky",
            "top": 0,
            "zIndex": 2,
        },
        style_cell={
            "backgroundColor": "#ffffff",
            "color": "#374151",
            "border": "none",
            "padding": "12px",
            "textAlign": "left",
            "minWidth": "120px",
            "maxWidth": "320px",
            "whiteSpace": "normal",
            "fontFamily": "Arial, sans-serif",
            "fontSize": "14px",
        },
        style_data={
            "borderBottom": "1px solid #edf2f7",
        },
        style_filter={
            "backgroundColor": "#f8fafc",
            "border": "1px solid #e5e7eb",
            "color": "#374151",
        },
        css=[
            {
                "selector": ".dash-spreadsheet-container .dash-spreadsheet-inner table",
                "rule": "border-collapse: separate; border-spacing: 0;",
            }
        ],
    )


def build_meta(table_name, df, total_rows, page_size):
    return html.Div(
        [
            html.Span(f"Tabela atual: {table_name}", className="meta-pill"),
            html.Span(f"Linhas totais no banco: {total_rows}", className="meta-pill"),
            html.Span(f"Linhas carregadas no app: {len(df)}", className="meta-pill"),
            html.Span(f"Colunas exibidas: {len(df.columns)}", className="meta-pill"),
            html.Span(f"Linhas por página: {page_size}", className="meta-pill"),
        ],
        className="meta-row",
    )


def build_dictionary_meta(table_name, df, page_size):
    return html.Div(
        [
            html.Span(f"Tabela atual: {table_name}", className="meta-pill"),
            html.Span(f"Campos únicos: {len(df)}", className="meta-pill"),
            html.Span(f"Linhas por página: {page_size}", className="meta-pill"),
        ],
        className="meta-row",
    )


def build_simple_meta(table_name, df, page_size):
    return html.Div(
        [
            html.Span(f"Tabela atual: {table_name}", className="meta-pill"),
            html.Span(f"Linhas: {len(df)}", className="meta-pill"),
            html.Span(f"Colunas: {len(df.columns)}", className="meta-pill"),
            html.Span(f"Linhas por página: {page_size}", className="meta-pill"),
        ],
        className="meta-row",
    )


app.layout = dbc.Container(
    fluid=True,
    className="app-shell",
    children=[
        dbc.Row(
            dbc.Col(
                html.Div(
                    className="hero-card",
                    children=[
                        html.Div(
                            className="hero-top",
                            children=[
                                html.Div(
                                    [
                                        html.Div("Dashboard ANTT", className="eyebrow"),
                                        html.H1("Visualização de tabelas do Supabase", className="page-title"),
                                        html.P(
                                            "Selecione uma tabela para explorar os dados salvos no banco e construir gráficos.",
                                            className="page-subtitle",
                                        ),
                                    ]
                                ),
                                html.Div(
                                    className="hero-badges",
                                    children=[
                                        html.Div(
                                            [
                                                html.Span("Tabelas de dados", className="badge-label"),
                                                html.Strong(str(len(data_tables)), className="badge-value"),
                                            ],
                                            className="soft-badge",
                                        ),
                                        html.Div(
                                            [
                                                html.Span("Tabelas de controle", className="badge-label"),
                                                html.Strong(str(len(control_tables)), className="badge-value"),
                                            ],
                                            className="soft-badge soft-badge-alt",
                                        ),
                                    ],
                                ),
                            ],
                        )
                    ],
                ),
                width=12,
            )
        ),

        dbc.Row(
            [
                dbc.Col(
                    html.Div(
                        className="filter-card filter-card-top",
                        children=[
                            html.Div("Tabela", className="filter-label"),
                            dcc.Dropdown(
                                id="table-selector",
                                options=[{"label": t, "value": t} for t in data_tables],
                                value=None,
                                clearable=True,
                                placeholder="Selecione uma tabela",
                                className="table-dropdown",
                                optionHeight=40,
                            ),
                            html.Div(
                                id="table-description-box",
                                className="description-box",
                                children=[
                                    html.Div("Descrição", className="description-title"),
                                    html.Div(
                                        "Selecione uma tabela para ver a descrição.",
                                        id="table-description-text",
                                        className="description-text",
                                    ),
                                ],
                            ),
                        ],
                    ),
                    md=8,
                    xs=12,
                ),
                dbc.Col(
                    html.Div(
                        className="filter-card",
                        children=[
                            html.Div("Linhas por página", className="filter-label"),
                            dcc.Dropdown(
                                id="page-size-selector",
                                options=[{"label": str(x), "value": x} for x in PAGE_SIZE_OPTIONS],
                                value=DEFAULT_PAGE_SIZE,
                                clearable=False,
                                className="table-dropdown",
                            ),
                        ],
                    ),
                    md=4,
                    xs=12,
                ),
            ],
            className="section-gap",
        ),

        dbc.Row(
            dbc.Col(
                dcc.Tabs(
                    id="main-tabs",
                    value="tab-dados",
                    className="custom-tabs",
                    children=[
                        dcc.Tab(
                            label="Dados da tabela",
                            value="tab-dados",
                            className="custom-tab",
                            selected_className="custom-tab--selected",
                            children=[
                                html.Div(
                                    className="tab-content-wrap",
                                    children=[
                                        html.Div(
                                            className="table-card",
                                            children=[
                                                html.Div(id="table-meta", className="table-meta"),
                                                html.Div(
                                                    id="table-wrapper",
                                                    children=html.Div(
                                                        "Selecione uma tabela para visualizar os dados.",
                                                        className="empty-state",
                                                    ),
                                                ),
                                            ],
                                        )
                                    ],
                                )
                            ],
                        ),
                        dcc.Tab(
                            label="Dicionário filtrado",
                            value="tab-dicionario",
                            className="custom-tab",
                            selected_className="custom-tab--selected",
                            children=[
                                html.Div(
                                    className="tab-content-wrap",
                                    children=[
                                        html.Div(
                                            className="table-card",
                                            children=[
                                                html.Div(id="dictionary-meta", className="table-meta"),
                                                html.Div(
                                                    id="dictionary-wrapper",
                                                    children=html.Div(
                                                        "Selecione uma tabela para visualizar o dicionário.",
                                                        className="empty-state",
                                                    ),
                                                ),
                                            ],
                                        )
                                    ],
                                )
                            ],
                        ),
                        dcc.Tab(
                            label="Dicionário completo",
                            value="tab-dicionario-full",
                            className="custom-tab",
                            selected_className="custom-tab--selected",
                            children=[
                                html.Div(
                                    className="tab-content-wrap",
                                    children=[
                                        html.Div(
                                            className="table-card",
                                            children=[
                                                html.Div(
                                                    id="dictionary-full-meta",
                                                    className="table-meta",
                                                    children=build_simple_meta(
                                                        "antt_antt_dicionarios_campos",
                                                        dictionary_full_df,
                                                        DEFAULT_PAGE_SIZE,
                                                    ),
                                                ),
                                                html.Div(
                                                    id="dictionary-full-wrapper",
                                                    children=build_table(
                                                        dictionary_full_df,
                                                        table_id="dictionary-full-table",
                                                        page_size=DEFAULT_PAGE_SIZE,
                                                    ),
                                                ),
                                            ],
                                        )
                                    ],
                                )
                            ],
                        ),
                        dcc.Tab(
                            label="Recursos DIM",
                            value="tab-recursos-dim",
                            className="custom-tab",
                            selected_className="custom-tab--selected",
                            children=[
                                html.Div(
                                    className="tab-content-wrap",
                                    children=[
                                        html.Div(
                                            className="table-card",
                                            children=[
                                                html.Div(
                                                    id="resources-meta",
                                                    className="table-meta",
                                                    children=build_simple_meta(
                                                        "antt_antt_recursos_dim",
                                                        resources_dim_df,
                                                        DEFAULT_PAGE_SIZE,
                                                    ),
                                                ),
                                                html.Div(
                                                    id="resources-wrapper",
                                                    children=build_table(
                                                        resources_dim_df,
                                                        table_id="resources-dim-table",
                                                        page_size=DEFAULT_PAGE_SIZE,
                                                    ),
                                                ),
                                            ],
                                        )
                                    ],
                                )
                            ],
                        ),
                        build_graph_builder_tab(),
                    ],
                ),
                width=12,
            )
        ),
    ],
)


@app.callback(
    Output("table-description-text", "children"),
    Output("table-wrapper", "children"),
    Output("table-meta", "children"),
    Output("dictionary-wrapper", "children"),
    Output("dictionary-meta", "children"),
    Output("resources-wrapper", "children"),
    Output("resources-meta", "children"),
    Output("dictionary-full-wrapper", "children"),
    Output("dictionary-full-meta", "children"),
    Input("table-selector", "value"),
    Input("page-size-selector", "value"),
)
def update_table_views(table_name, page_size):
    page_size = page_size or DEFAULT_PAGE_SIZE

    resources_table = build_table(
        resources_dim_df,
        table_id="resources-dim-table",
        page_size=page_size,
    )
    resources_meta = build_simple_meta(
        "antt_antt_recursos_dim",
        resources_dim_df,
        page_size,
    )

    dictionary_full_table = build_table(
        dictionary_full_df,
        table_id="dictionary-full-table",
        page_size=page_size,
    )
    dictionary_full_meta = build_simple_meta(
        "antt_antt_dicionarios_campos",
        dictionary_full_df,
        page_size,
    )

    if not table_name:
        empty_data = html.Div("Selecione uma tabela para visualizar os dados.", className="empty-state")
        empty_dict = html.Div("Selecione uma tabela para visualizar o dicionário.", className="empty-state")
        return (
            "Selecione uma tabela para ver a descrição.",
            empty_data,
            "",
            empty_dict,
            "",
            resources_table,
            resources_meta,
            dictionary_full_table,
            dictionary_full_meta,
        )

    description = table_metadata_map.get(table_name, {}).get("description", "").strip()
    description_text = description if description else "Sem descrição cadastrada para esta tabela."

    df = load_table(engine, table_name, limit=1000)
    df = dataframe_for_dash(df)
    total_rows = get_table_total_rows(engine, table_name)

    dictionary_df = get_dictionary_fields_for_table(engine, table_name, table_metadata_map)
    dictionary_df = dataframe_for_dash(dictionary_df)

    return (
        description_text,
        build_table(df, table_id="main-table", page_size=page_size),
        build_meta(table_name, df, total_rows, page_size),
        build_table(dictionary_df, table_id="dictionary-table", page_size=page_size),
        build_dictionary_meta(table_name, dictionary_df, page_size),
        resources_table,
        resources_meta,
        dictionary_full_table,
        dictionary_full_meta,
    )


register_graph_builder_callbacks(app, engine)

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8050)