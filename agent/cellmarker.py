"""Confounder / promiscuity lookup over a local CellMarker 2.0 SQLite index.

This is the Critic's "is this DEG actually specific?" oracle. CellMarker 2.0 is a
curated marker database, so a gene reported as a marker for MANY distinct cell
types is a *shared* (non-specific) marker — a confounder the Actor's hypothesis
must survive. A gene reported for one cell type is a candidate specific biomarker.

(True housekeeping genes are often absent or sparse here precisely because they
are rarely curated AS markers; the housekeeping_signal below is a weak heuristic —
the Critic should corroborate with uniprot_lookup + search_literature.)

Read-only and never-raises, matching the tool contract: a missing DB file or any
query error degrades gracefully to a `found: False` result rather than throwing.
Stdlib only (sqlite3); the .db is built offline by data_prep/build_cellmarker_db.py.
"""
import os
import sqlite3

# Distinct-cell-type thresholds, picked from the Mouse CellMarker distribution
# (median 1, p90 4, p99 13): 1 = specific, 2-4 = moderate, 5+ = broad/shared.
_SPECIFIC_MAX = 1
_MODERATE_MAX = 4
# Broadly claimed across many cell types AND tissues -> weak housekeeping signal.
_HOUSEKEEPING_CELLS = 10
_HOUSEKEEPING_TISSUES = 8

_CONN = {}  # path -> sqlite3.Connection (read-only, cached across clusters)


def _connect(path):
    if path not in _CONN:
        # Open read-only via URI so a tool call can never mutate the index.
        uri = f"file:{os.path.abspath(path)}?mode=ro"
        _CONN[path] = sqlite3.connect(uri, uri=True, check_same_thread=False)
    return _CONN[path]


def confounder_lookup(gene, cfg):
    """Return every cell type CellMarker 2.0 reports for `gene`, with a
    promiscuity / specificity verdict for the Critic.
    """
    path = cfg.get("cellmarker_db")
    g = (gene or "").strip()
    if not path or not os.path.exists(path):
        return {"gene": gene, "found": False,
                "note": "CellMarker SQLite index not configured/built "
                        "(data_prep/build_cellmarker_db.py)."}

    conn = _connect(path)
    rows = conn.execute(
        "SELECT DISTINCT cell_name, tissue, species FROM markers "
        "WHERE gene = ? COLLATE NOCASE",
        (g,),
    ).fetchall()
    if not rows:
        return {"gene": gene, "found": False,
                "note": "Not reported as a marker in CellMarker 2.0 (absent here "
                        "is common for housekeeping/technical genes)."}

    cell_types = sorted({r[0] for r in rows if r[0]})
    tissues = sorted({r[1] for r in rows if r[1]})
    n = len(cell_types)

    if n <= _SPECIFIC_MAX:
        promiscuity, specificity = "low", "high"
    elif n <= _MODERATE_MAX:
        promiscuity, specificity = "medium", "medium"
    else:
        promiscuity, specificity = "high", "low"

    housekeeping_signal = (n >= _HOUSEKEEPING_CELLS
                           and len(tissues) >= _HOUSEKEEPING_TISSUES)

    if promiscuity == "low":
        note = (f"Reported as a marker for a single cell type "
                f"({cell_types[0]}) — a candidate specific biomarker.")
    else:
        note = (f"Reported as a marker for {n} distinct cell types across "
                f"{len(tissues)} tissues — a {promiscuity}-promiscuity / shared "
                f"marker, so it weakly discriminates between those cell types.")
        if housekeeping_signal:
            note += (" Breadth suggests a ubiquitous/housekeeping-like gene; "
                     "corroborate with uniprot_lookup / search_literature.")

    return {
        "gene": gene,
        "found": True,
        "n_cell_types": n,
        "cell_types": cell_types[:25],   # cap payload; verdict already summarizes
        "tissues": tissues[:25],
        "promiscuity": promiscuity,
        "specificity": specificity,
        "housekeeping_signal": housekeeping_signal,
        "note": note,
    }
