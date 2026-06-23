"""The structured-output contract for a single prediction.

The label set is injected from the dataset config, so the same schema serves
DLPFC layers, cell types, or any other label vocabulary. Structured-output
rules: every object sets additionalProperties=false and lists all keys in
`required`; no numeric/length constraints.
"""


def prediction_schema(labels):
    """Build the JSON schema for one cluster prediction.

    `labels` is the dataset's label vocabulary (e.g. ["L1", ..., "WM"]).
    """
    return {
        "type": "object",
        "properties": {
            "predicted_label": {"type": "string", "enum": list(labels)},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "supporting_genes": {
                "type": "array",
                "items": {"type": "string"},
            },
            "negative_checks": {
                "type": "array",
                "items": {"type": "string"},
            },
            "ambiguous_between": {
                "type": "array",
                "items": {"type": "string", "enum": list(labels)},
            },
            "reasoning": {"type": "string"},
            "citations": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "predicted_label",
            "confidence",
            "supporting_genes",
            "negative_checks",
            "ambiguous_between",
            "reasoning",
            "citations",
        ],
        "additionalProperties": False,
    }
