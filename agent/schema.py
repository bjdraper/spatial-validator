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
            # Actor: the primary hypothesis, before the Critic stress-tested it.
            "initial_hypothesis": {"type": "string"},
            "predicted_label": {"type": "string", "enum": list(labels)},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            # Critic: risk that the resolved label is a misclassification.
            "vulnerability_score": {
                "type": "string",
                "enum": ["high", "medium", "low"],
            },
            "supporting_genes": {
                "type": "array",
                "items": {"type": "string"},
            },
            # Critic: per-DEG discrimination — housekeeping vs biomarker, and
            # which cell types / tissue the marker pertains to.
            "gene_classification": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "gene": {"type": "string"},
                        "role": {
                            "type": "string",
                            "enum": ["biomarker", "housekeeping", "ambiguous"],
                        },
                        "pertains_to": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["gene", "role", "pertains_to"],
                    "additionalProperties": False,
                },
            },
            # Critic: named co-expression signatures the DEG set matches.
            "detected_panels": {
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
            "initial_hypothesis",
            "predicted_label",
            "confidence",
            "vulnerability_score",
            "supporting_genes",
            "gene_classification",
            "detected_panels",
            "negative_checks",
            "ambiguous_between",
            "reasoning",
            "citations",
        ],
        "additionalProperties": False,
    }
