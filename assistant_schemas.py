CHART_TYPES = [
    "line",
    "bar",
    "column",
    "scatter",
    "pie",
    "donut",
    "map_points",
    "map_br_uf",
]

ASSISTANT_ACTION_SCHEMA = {
    "name": "assistant_action",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create_chart", "answer_only"],
            },
            "message": {
                "type": "string",
            },
            "chart": {
                "type": ["object", "null"],
                "additionalProperties": False,
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": CHART_TYPES,
                    },
                    "title": {"type": "string"},
                    "height": {"type": "integer"},
                    "agg_mode": {
                        "type": "string",
                        "enum": ["count", "distinct_count", "percent_of_total", "sum"],
                    },
                    "x": {"type": ["string", "null"]},
                    "y": {"type": ["string", "null"]},
                    "value": {"type": ["string", "null"]},
                    "extra": {"type": ["string", "null"]},
                    "map_marker_type": {"type": ["string", "null"]},
                    "map_marker_size": {"type": ["integer", "null"]},
                    "map_max_lines": {"type": ["integer", "null"]},
                },
                "required": [
                    "type",
                    "title",
                    "height",
                    "agg_mode",
                    "x",
                    "y",
                    "value",
                    "extra",
                    "map_marker_type",
                    "map_marker_size",
                    "map_max_lines",
                ],
            },
        },
        "required": ["action", "message", "chart"],
    },
}