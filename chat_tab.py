import uuid
import pandas as pd

from dash import html, dcc, Input, Output, State, callback_context
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
from dash import dash_table

from assistant_chat_service import ask_bi_chatbot
from assistant_memory import clear_session_messages
from shared_logger import get_shared_logger, log_event


logger = get_shared_logger("chat_tab")


def _message_bubble(role: str, content: str):
    is_user = role == "user"

    return html.Div(
        style={
            "display": "flex",
            "justifyContent": "flex-end" if is_user else "flex-start",
            "marginBottom": "14px",
        },
        children=[
            html.Div(
                [
                    html.Div(
                        "Você" if is_user else "Assistente BI",
                        style={
                            "fontSize": "12px",
                            "fontWeight": "700",
                            "marginBottom": "6px",
                            "color": "#4b5563",
                            "opacity": 0.9,
                        },
                    ),
                    dcc.Markdown(
                        content,
                        style={
                            "lineHeight": "1.55",
                            "margin": "0",
                        },
                    ),
                ],
                style={
                    "maxWidth": "78%",
                    "padding": "14px 16px",
                    "borderRadius": "18px",
                    "background": "#dbeafe" if is_user else "#f8fafc",
                    "color": "#1f2937",
                    "boxShadow": "0 4px 14px rgba(0,0,0,0.05)",
                    "fontSize": "14px",
                    "border": "1px solid #e5e7eb",
                },
            )
        ],
    )


def _thinking_bubble():
    return html.Div(
        style={
            "display": "flex",
            "justifyContent": "flex-start",
            "marginBottom": "14px",
        },
        children=[
            html.Div(
                [
                    html.Div(
                        "Assistente BI",
                        style={
                            "fontSize": "12px",
                            "fontWeight": "700",
                            "marginBottom": "6px",
                            "color": "#4b5563",
                            "opacity": 0.9,
                        },
                    ),
                    html.Div(
                        [
                            html.Span("Pensando", style={"marginRight": "8px"}),
                            html.Span("•", style={"opacity": 0.45, "marginRight": "4px"}),
                            html.Span("•", style={"opacity": 0.65, "marginRight": "4px"}),
                            html.Span("•", style={"opacity": 0.85}),
                        ],
                        style={"lineHeight": "1.55"},
                    ),
                ],
                style={
                    "maxWidth": "78%",
                    "padding": "14px 16px",
                    "borderRadius": "18px",
                    "background": "#f8fafc",
                    "color": "#1f2937",
                    "boxShadow": "0 4px 14px rgba(0,0,0,0.05)",
                    "fontSize": "14px",
                    "border": "1px solid #e5e7eb",
                },
            )
        ],
    )


def _render_preview_table(table_payload: dict):
    if not table_payload or not table_payload.get("rows"):
        return html.Div()

    df = pd.DataFrame(table_payload["rows"])
    if df.empty:
        return html.Div()

    return html.Div(
        style={"marginTop": "10px"},
        children=[
            html.Div(
                "Resultado tabular",
                style={
                    "fontSize": "12px",
                    "fontWeight": "700",
                    "marginBottom": "8px",
                    "color": "#4b5563",
                },
            ),
            dash_table.DataTable(
                columns=[{"name": c, "id": c} for c in df.columns],
                data=df.to_dict("records"),
                page_size=min(10, len(df)),
                style_table={"overflowX": "auto", "borderRadius": "12px"},
                style_cell={
                    "textAlign": "left",
                    "padding": "8px",
                    "fontSize": "12px",
                    "whiteSpace": "normal",
                    "maxWidth": "240px",
                },
                style_header={
                    "backgroundColor": "#eff6ff",
                    "fontWeight": "700",
                    "border": "none",
                },
                style_data={"borderBottom": "1px solid #edf2f7"},
            ),
        ],
    )


def build_chat_tab():
    session_id = str(uuid.uuid4())
    log_event(logger, "build_chat_tab", session_id=session_id)

    return dcc.Tab(
        label="Chat BI",
        value="tab-chat-bi",
        className="custom-tab",
        selected_className="custom-tab--selected",
        children=[
            dcc.Store(id="chat-session-id", data=session_id),
            dcc.Store(id="chat-history-store", data=[]),
            dcc.Store(id="chat-pending-request", data=None),
            dcc.Store(id="chat-loading-store", data=False),
            dcc.Store(id="chat-last-table-result", data=None),
            dcc.Store(id="chat-last-query-context", data=None),
            html.Div(
                className="tab-content-wrap",
                children=[
                    html.Div(
                        className="table-card",
                        style={
                            "padding": "22px",
                            "borderRadius": "24px",
                        },
                        children=[
                            html.Div(
                                style={
                                    "display": "flex",
                                    "justifyContent": "space-between",
                                    "alignItems": "center",
                                    "marginBottom": "18px",
                                    "gap": "12px",
                                },
                                children=[
                                    html.Div(
                                        [
                                            html.H3("Chat BI", className="graph-builder-title"),
                                            html.P(
                                                "Converse com o catálogo de tabelas, peça análises, gráficos e consultas tabulares.",
                                                className="graph-builder-subtitle",
                                            ),
                                        ]
                                    ),
                                    dbc.Button(
                                        html.I(className="bi bi-trash3-fill"),
                                        id="chat-clear-btn",
                                        color="light",
                                        title="Limpar conversa",
                                        style={
                                            "width": "46px",
                                            "height": "46px",
                                            "borderRadius": "50%",
                                            "display": "flex",
                                            "alignItems": "center",
                                            "justifyContent": "center",
                                            "fontSize": "18px",
                                            "border": "1px solid #dbe5ef",
                                            "boxShadow": "0 2px 10px rgba(0,0,0,0.04)",
                                        },
                                    ),
                                ],
                            ),
                            html.Div(
                                id="chat-messages-container",
                                style={
                                    "minHeight": "420px",
                                    "maxHeight": "520px",
                                    "overflowY": "auto",
                                    "border": "1px solid #e8edf3",
                                    "borderRadius": "20px",
                                    "padding": "18px",
                                    "background": "linear-gradient(180deg, #fcfdff 0%, #f8fbff 100%)",
                                    "marginBottom": "16px",
                                },
                                children=[
                                    _message_bubble(
                                        "assistant",
                                        "Olá! Pergunte sobre tabelas, campos, dicionário, gráficos ou peça uma consulta tabular.",
                                    )
                                ],
                            ),
                            html.Div(
                                id="chat-table-preview-container",
                                style={"marginBottom": "16px"},
                                children=[],
                            ),
                            html.Div(
                                style={
                                    "display": "flex",
                                    "gap": "12px",
                                    "alignItems": "center",
                                },
                                children=[
                                    dcc.Input(
                                        id="chat-user-input",
                                        type="text",
                                        placeholder='Ex.: mostre 10 registros onde municipio = Vargem',
                                        debounce=False,
                                        style={
                                            "width": "100%",
                                            "height": "54px",
                                            "borderRadius": "16px",
                                            "border": "1px solid #dbe5ef",
                                            "padding": "0 16px",
                                            "backgroundColor": "#ffffff",
                                            "fontSize": "14px",
                                            "boxShadow": "0 2px 10px rgba(0,0,0,0.03)",
                                        },
                                    ),
                                    dbc.Button(
                                        html.I(className="bi bi-send-fill"),
                                        id="chat-send-btn",
                                        color="primary",
                                        title="Enviar mensagem",
                                        style={
                                            "width": "54px",
                                            "height": "54px",
                                            "borderRadius": "50%",
                                            "display": "flex",
                                            "alignItems": "center",
                                            "justifyContent": "center",
                                            "fontSize": "20px",
                                            "boxShadow": "0 6px 16px rgba(59,130,246,0.25)",
                                            "flexShrink": "0",
                                        },
                                    ),
                                ],
                            ),
                        ],
                    )
                ],
            ),
        ],
    )


def register_chat_callbacks(app, engine):
    log_event(logger, "register_chat_callbacks_called")

    @app.callback(
        Output("chat-history-store", "data"),
        Output("chat-user-input", "value"),
        Output("chat-pending-request", "data"),
        Output("chat-loading-store", "data"),
        Input("chat-send-btn", "n_clicks"),
        Input("chat-user-input", "n_submit"),
        State("chat-user-input", "value"),
        State("chat-session-id", "data"),
        State("table-selector", "value"),
        State("chat-history-store", "data"),
        prevent_initial_call=True,
    )
    def queue_chat_message(n_clicks, n_submit, user_input, session_id, selected_table, history):
        ctx = callback_context
        trigger = ctx.triggered[0]["prop_id"].split(".")[0] if ctx.triggered else None

        log_event(
            logger,
            "queue_chat_message_start",
            trigger=trigger,
            n_clicks=n_clicks,
            n_submit=n_submit,
            session_id=session_id,
            selected_table=selected_table,
            user_input=user_input,
            history_count=len(history or []),
        )

        if not user_input or not str(user_input).strip():
            log_event(logger, "queue_chat_message_empty_input")
            raise PreventUpdate

        history = history or []
        history.append({"role": "user", "content": user_input})

        pending_request = {
            "session_id": session_id,
            "selected_table": selected_table,
            "user_message": user_input,
        }

        return history, "", pending_request, True

    @app.callback(
        Output("chat-history-store", "data", allow_duplicate=True),
        Output("chat-pending-request", "data", allow_duplicate=True),
        Output("chat-loading-store", "data", allow_duplicate=True),
        Output("chat-last-table-result", "data"),
        Output("chat-last-query-context", "data"),
        Input("chat-pending-request", "data"),
        State("chat-history-store", "data"),
        State("chat-last-query-context", "data"),
        prevent_initial_call=True,
    )
    def process_chat_message(pending_request, history, last_query_context):
        if not pending_request:
            raise PreventUpdate

        session_id = pending_request.get("session_id")
        selected_table = pending_request.get("selected_table")
        user_message = pending_request.get("user_message")

        log_event(
            logger,
            "process_chat_message_start",
            session_id=session_id,
            selected_table=selected_table,
            user_message=user_message,
            history_count=len(history or []),
            last_query_context=last_query_context,
        )

        history = history or []

        try:
            result = ask_bi_chatbot(
                engine=engine,
                session_id=session_id,
                user_message=user_message,
                selected_table=selected_table,
                last_query_context=last_query_context,
            )
            answer = result.get("answer", "Não consegui responder no momento.")
            table_payload = result.get("table")
            new_query_context = result.get("last_query_context", last_query_context)

            log_event(
                logger,
                "process_chat_message_success",
                answer_preview=answer[:700],
                has_table=bool(table_payload),
                new_query_context=new_query_context,
            )
        except Exception as e:
            answer = f"Erro ao consultar o assistente: {e}"
            table_payload = None
            new_query_context = last_query_context
            log_event(logger, "process_chat_message_error", error=str(e))

        history.append({"role": "assistant", "content": answer})

        return history, None, False, table_payload, new_query_context

    @app.callback(
        Output("chat-messages-container", "children"),
        Input("chat-history-store", "data"),
        Input("chat-loading-store", "data"),
    )
    def render_chat_messages(history, is_loading):
        history = history or []
        log_event(logger, "render_chat_messages", history_count=len(history), is_loading=is_loading)

        children = []

        if not history:
            children.append(
                _message_bubble(
                    "assistant",
                    "Olá! Pergunte sobre tabelas, campos, dicionário, gráficos ou peça uma consulta tabular.",
                )
            )
        else:
            children.extend([_message_bubble(item["role"], item["content"]) for item in history])

        if is_loading:
            children.append(_thinking_bubble())

        return children

    @app.callback(
        Output("chat-table-preview-container", "children"),
        Input("chat-last-table-result", "data"),
    )
    def render_chat_table_preview(table_payload):
        return _render_preview_table(table_payload)

    @app.callback(
        Output("chat-history-store", "data", allow_duplicate=True),
        Output("chat-pending-request", "data", allow_duplicate=True),
        Output("chat-loading-store", "data", allow_duplicate=True),
        Output("chat-last-table-result", "data", allow_duplicate=True),
        Output("chat-last-query-context", "data", allow_duplicate=True),
        Input("chat-clear-btn", "n_clicks"),
        State("chat-session-id", "data"),
        prevent_initial_call=True,
    )
    def clear_chat(n_clicks, session_id):
        log_event(logger, "clear_chat_start", n_clicks=n_clicks, session_id=session_id)

        if not n_clicks:
            raise PreventUpdate

        clear_session_messages(session_id)
        return [], None, False, None, None