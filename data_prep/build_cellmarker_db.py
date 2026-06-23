"""Build a CellMarker 2.0 SQLite index for the agent's `confounder_lookup` tool.

Unlike `data_prep/build_kb.py` (which collapses fine cell names to a dataset's
label vocabulary and filters to one tissue, producing the Actor's positive-marker
JSON KB), this builder keeps the **raw, fine-grained cell names across ALL tissues**
on purpose. That breadth is exactly what makes the DB a confounder / promiscuity
oracle for the Critic: "how many distinct cell types report this gene?" is the
signal that separates a specific biomarker from a housekeeping / non-specific gene.

    # download the species file once (see data_prep/README.md):
    #   http://117.50.127.228/CellMarker/CellMarker_download_files/file/Cell_marker_Mouse.xlsx
    python data_prep/build_cellmarker_db.py \
        --xlsx data/raw/Cell_marker_Mouse.xlsx \
        --out data/kb/cellmarker.db

Output schema (one row per gene/cell-name/tissue/PMID record):
    markers(gene TEXT, cell_name TEXT, tissue TEXT, species TEXT, pmid TEXT)
    INDEX idx_gene ON markers(gene COLLATE NOCASE)

NOTE: the builder needs pandas + openpyxl (already used by build_kb.py); the agent
runtime needs only stdlib sqlite3. The output .db is PRIVATE (gitignored) even
though CellMarker 2.0 is public — it inherits the repo's data classification.
"""
import argparse
import os
import sqlite3

import pandas as pd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", help="CellMarker 2.0 species .xlsx file")
    ap.add_argument("--csv", help="CellMarker 2.0 .csv/.tsv (alternative to --xlsx)")
    ap.add_argument("--out", required=True, help="output SQLite path, e.g. data/kb/cellmarker.db")
    args = ap.parse_args()

    if not (args.xlsx or args.csv):
        ap.error("provide --xlsx or --csv")

    if args.xlsx:
        df = pd.read_excel(args.xlsx)
    else:
        sep = "\t" if args.csv.endswith((".tsv", ".txt")) else ","
        df = pd.read_csv(args.csv, sep=sep)

    # Normal cells only (drop cancer), require a gene symbol. Mirrors build_kb.py
    # so the confounder oracle and the positive KB are drawn from the same slice.
    df = df[df["cell_type"].astype(str).str.lower() == "normal cell"]
    df = df[df["Symbol"].notna()]

    rows = []
    for _, r in df.iterrows():
        gene = str(r["Symbol"]).strip()
        if not gene:
            continue
        cell_name = str(r.get("cell_name", "")).strip()
        tissue = " / ".join(
            t for t in [str(r.get("tissue_class", "")).strip(),
                        str(r.get("tissue_type", "")).strip()] if t and t != "nan"
        )
        species = str(r.get("species", "")).strip().lower()
        pmid = str(r["PMID"]).split(".")[0] if pd.notna(r.get("PMID")) else ""
        pmid = pmid if pmid.isdigit() else ""
        rows.append((gene, cell_name, tissue, species, pmid))

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    if os.path.exists(args.out):
        os.remove(args.out)  # rebuild from scratch; never append
    conn = sqlite3.connect(args.out)
    conn.execute(
        "CREATE TABLE markers ("
        "gene TEXT, cell_name TEXT, tissue TEXT, species TEXT, pmid TEXT)"
    )
    conn.executemany(
        "INSERT INTO markers (gene, cell_name, tissue, species, pmid) "
        "VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.execute("CREATE INDEX idx_gene ON markers(gene COLLATE NOCASE)")
    conn.commit()

    n_genes = conn.execute("SELECT COUNT(DISTINCT gene) FROM markers").fetchone()[0]
    n_cells = conn.execute("SELECT COUNT(DISTINCT cell_name) FROM markers").fetchone()[0]
    conn.close()
    src = args.xlsx or args.csv
    print(f"Wrote {args.out}: {len(rows)} records, {n_genes} genes, "
          f"{n_cells} distinct cell names (from {os.path.basename(src)}).")


if __name__ == "__main__":
    main()
