"""Compile a marker knowledge base from CellMarker 2.0 into the agent's KB schema.

The agent's marker_lookup reads data/kb/*.json with entries:
    {gene, identities, direction, specificity, note, citation}
This script builds exactly that from CellMarker 2.0, so NO agent code changes.

    # 1. download the species file once (see data_prep/README.md):
    #    http://117.50.127.228/CellMarker/CellMarker_download_files/file/Cell_marker_Mouse.xlsx
    python data_prep/build_kb.py \
        --xlsx data/raw/Cell_marker_Mouse.xlsx \
        --tissue Brain Hypothalamus \
        --label-map data_prep/labelmaps/mouse_brain8.json \
        --out data/kb/mouse_brain_cellmarker.json

CellMarker has no specificity column, so specificity is derived by an
inverse-frequency proxy: a gene marking ONE label in this tissue is `high`,
two is `medium`, three+ is `low` (a broad, weak discriminator). This mirrors
the hand-curated grades and is the main defense against DB noise.
"""
import argparse
import json
import os
from collections import defaultdict

import pandas as pd


def load_label_map(path):
    if not path:
        return None
    rules = json.load(open(path))["rules"]
    return [(kw.lower(), label) for kw, label in rules]


def map_label(cell_name, rules):
    """Collapse a fine CellMarker cell_name to a vocabulary label (or None)."""
    if rules is None:
        return cell_name  # open vocabulary: keep the raw cell name
    low = str(cell_name).lower()
    for kw, label in rules:
        if kw in low:
            return label
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", required=True, help="CellMarker 2.0 species file")
    ap.add_argument("--tissue", nargs="*", default=[],
                    help="tissue keywords (substring match on tissue_class/_type); empty = all")
    ap.add_argument("--label-map", default=None,
                    help="JSON keyword->label collapse map; omit for open vocabulary")
    ap.add_argument("--min-share", type=float, default=0.2,
                    help="drop a label for a gene if it holds <this fraction of the "
                         "gene's records (filters literature-mining noise)")
    ap.add_argument("--min-count", type=int, default=2,
                    help="a label needs >=this many records to be kept (unless sole)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    df = pd.read_excel(args.xlsx)
    species = str(df["species"].iloc[0]).lower()

    # Normal cells only (drop cancer), valid gene symbol.
    df = df[df["cell_type"].astype(str).str.lower() == "normal cell"]
    df = df[df["Symbol"].notna()]

    if args.tissue:
        kw = [t.lower() for t in args.tissue]
        ctx = (df["tissue_class"].astype(str) + " " + df["tissue_type"].astype(str)).str.lower()
        df = df[ctx.apply(lambda s: any(k in s for k in kw))]

    rules = load_label_map(args.label_map)

    # gene -> {label -> [pmids]}
    gene_labels = defaultdict(lambda: defaultdict(list))
    for _, r in df.iterrows():
        label = map_label(r["cell_name"], rules)
        if not label:
            continue
        gene = str(r["Symbol"]).strip()
        pmid = str(r["PMID"]).split(".")[0] if pd.notna(r.get("PMID")) else ""
        if pmid and pmid.isdigit():
            gene_labels[gene][label].append(pmid)

    markers = []
    for gene in sorted(gene_labels):
        labels = gene_labels[gene]
        counts = {lab: len(pl) for lab, pl in labels.items()}
        total = sum(counts.values())
        dom = max(counts, key=counts.get)

        # Drop minority-noise labels (e.g. Gad1's stray "Excitatory" record);
        # always keep at least the dominant label.
        kept = [l for l, n in counts.items()
                if n >= args.min_count and n / total >= args.min_share]
        if not kept:
            kept = [dom]
        kept.sort()
        n_eff = len(kept)

        # Specificity from BOTH discrimination (how many labels) and evidence
        # volume (how many records back the dominant call).
        if n_eff == 1 and counts[dom] >= 3:
            spec = "high"
        elif n_eff <= 2:
            spec = "medium"
        else:
            spec = "low"

        pmids = sorted({p for l in kept for p in labels[l]})[:3]
        cite = "CellMarker 2.0" + (f"; PMID {', '.join(pmids)}" if pmids else "")
        markers.append({
            "gene": gene,
            "identities": kept,
            "direction": "positive",
            "specificity": spec,
            "note": f"CellMarker 2.0: marks {', '.join(kept)} "
                    f"({counts[dom]}/{total} records for the dominant label).",
            "citation": cite,
        })

    out = {
        "_note": f"Auto-built from CellMarker 2.0 ({os.path.basename(args.xlsx)}), "
                 f"tissue filter={args.tissue or 'all'}. Specificity is an "
                 f"inverse-frequency proxy (1 label=high, 2=medium, 3+=low).",
        "_specificity_guide": "high = marks 1 label here; medium = 2; low = 3+ (broad).",
        "species": species,
        "tissue": " / ".join(args.tissue) if args.tissue else "all",
        "markers": markers,
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)

    by_spec = defaultdict(int)
    for m in markers:
        by_spec[m["specificity"]] += 1
    print(f"Wrote {args.out}: {len(markers)} genes "
          f"(high={by_spec['high']}, medium={by_spec['medium']}, low={by_spec['low']})")


if __name__ == "__main__":
    main()
