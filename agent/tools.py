"""Read-only tools the agent can call. No side effects, so re-running is safe.

Each tool takes the model-supplied args plus the dataset `cfg` and loaded `kb`,
and returns a JSON-serialisable dict.
"""
import json

TOOLS = [
    {
        "name": "marker_lookup",
        "description": (
            "Look up a gene in the marker knowledge base. Returns known cell "
            "type / tissue-layer identities for the gene, whether it is a "
            "positive or negative marker, the tissue/species context, and a "
            "citation. Call this for every candidate marker gene before "
            "deciding."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "gene": {"type": "string", "description": "Gene symbol, e.g. RORB"}
            },
            "required": ["gene"],
        },
    },
    {
        "name": "search_literature",
        "description": (
            "Search PubMed (live, with a persistent cache) for a gene and/or "
            "cell-type / tissue-layer combination, to find supporting "
            "publications. Returns ranked references — title, journal, year, a "
            "snippet, and a citable PMID + DOI. Use it to corroborate a marker "
            "assignment, or to reason about a gene that is missing from the "
            "marker knowledge base. Cite the PMIDs you rely on."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search phrase"}
            },
            "required": ["query"],
        },
    },
    {
        "name": "adjacency_rules",
        "description": (
            "Return which labels can be spatially adjacent to a candidate "
            "label. Use it to sanity-check that a candidate is spatially "
            "plausible given the cluster's neighbours. Datasets without spatial "
            "ordering return no constraints."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "label": {"type": "string", "description": "Candidate label, e.g. L4"}
            },
            "required": ["label"],
        },
    },
    {
        "name": "confounder_lookup",
        "description": (
            "CRITIC TOOL. List every cell type that CellMarker 2.0 reports this "
            "gene as a marker for, across all tissues, with a promiscuity / "
            "specificity verdict. Use it to expose SHARED or non-specific markers "
            "(a gene claimed by many cell types weakly discriminates between them) "
            "and to flag housekeeping-like genes. A gene reported for a single "
            "cell type is a candidate specific biomarker. Call this on the top "
            "DEGs to test whether the hypothesis rests on confoundable markers."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "gene": {"type": "string", "description": "Gene symbol, e.g. Gad1"}
            },
            "required": ["gene"],
        },
    },
    {
        "name": "uniprot_lookup",
        "description": (
            "CRITIC TOOL. Fetch UniProt functional annotation for a gene/protein: "
            "molecular function, subcellular localization, and keywords. Use it to "
            "judge whether a DEG is a specialised cell-type biomarker (e.g. a "
            "lineage transcription factor, a synaptic protein) or a ubiquitous "
            "housekeeping protein (cytoskeleton, ribosome, metabolism) that should "
            "not drive a cell-type call."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "gene": {"type": "string", "description": "Gene symbol, e.g. RORB"}
            },
            "required": ["gene"],
        },
    },
]


def load_kb(cfg):
    """Load the marker knowledge base (and optional literature corpus)."""
    with open(cfg["marker_kb"]) as f:
        kb = json.load(f)
    kb.setdefault("markers", [])
    kb.setdefault("literature", [])
    return kb


def marker_lookup(gene, cfg, kb):
    g = (gene or "").strip().upper()
    hits = [m for m in kb["markers"] if m.get("gene", "").upper() == g]
    if not hits:
        return {
            "gene": gene,
            "found": False,
            "note": "No entry in the marker knowledge base.",
        }
    return {"gene": gene, "found": True, "entries": hits}


def search_literature(query, cfg, kb):
    # Live PubMed + persistent cache when configured (see agent/literature.py).
    if (cfg.get("literature") or {}).get("enabled"):
        from . import literature
        return literature.search(query, cfg)

    # Back-compat fallback: substring match over a hand-curated KB corpus.
    lit = kb.get("literature", [])
    if not lit:
        return {
            "query": query,
            "matches": [],
            "note": "No literature corpus configured for this dataset.",
        }
    terms = (query or "").lower().split()
    matches = [
        s for s in lit if any(t in s.get("text", "").lower() for t in terms)
    ]
    return {"query": query, "matches": matches[:5]}


def confounder_lookup(gene, cfg, kb):
    # CellMarker 2.0 SQLite promiscuity/confounder oracle (see agent/cellmarker.py).
    from . import cellmarker
    return cellmarker.confounder_lookup(gene, cfg)


def uniprot_lookup(gene, cfg, kb):
    # UniProt REST function/localization annotation, cached (see agent/uniprot.py).
    from . import uniprot
    return uniprot.lookup(gene, cfg)


def adjacency_rules(label, cfg, kb):
    adj = cfg.get("adjacency") or {}
    if not adj:
        return {
            "label": label,
            "note": "No spatial adjacency constraints for this dataset.",
        }
    return {
        "label": label,
        "can_be_adjacent_to": adj.get(label, []),
        "note": "Spatially plausible only if neighbouring clusters match these labels.",
    }


_DISPATCH = {
    "marker_lookup": lambda a, c, k: marker_lookup(a.get("gene", ""), c, k),
    "search_literature": lambda a, c, k: search_literature(a.get("query", ""), c, k),
    "adjacency_rules": lambda a, c, k: adjacency_rules(a.get("label", ""), c, k),
    "confounder_lookup": lambda a, c, k: confounder_lookup(a.get("gene", ""), c, k),
    "uniprot_lookup": lambda a, c, k: uniprot_lookup(a.get("gene", ""), c, k),
}


def dispatch(name, args, cfg, kb):
    """Execute a tool by name; never raises (errors come back as data)."""
    fn = _DISPATCH.get(name)
    if fn is None:
        return {"error": f"unknown tool: {name}"}
    try:
        return fn(args, cfg, kb)
    except Exception as exc:  # tools are read-only; surface errors to the model
        return {"error": str(exc)}
