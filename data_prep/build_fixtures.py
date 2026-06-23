"""Convert a labelled DLPFC section (.h5ad) into the agent's fixture JSON.

Layer-as-cluster strategy: each expert-annotated layer becomes one test case,
with its top differentially expressed genes. Ground truth is unambiguous.

Usage:
    python data_prep/build_fixtures.py \
        --h5ad data/raw/151673.h5ad --section 151673 --label-col layer

Requires the data dependencies: pip install -r requirements-data.txt
"""
import argparse
import json
import os

import scanpy as sc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--h5ad", required=True, help="labelled AnnData for one section")
    ap.add_argument("--section", required=True, help="section id, e.g. 151673")
    ap.add_argument("--label-col", default="layer", help="obs column with layer labels")
    ap.add_argument("--top-n", type=int, default=15)
    ap.add_argument("--out-dir", default="data/fixtures/dlpfc")
    args = ap.parse_args()

    adata = sc.read_h5ad(args.h5ad)
    adata = adata[~adata.obs[args.label_col].isna()].copy()

    sc.pp.normalize_total(adata, target_sum=1e4)
    sc.pp.log1p(adata)
    sc.tl.rank_genes_groups(adata, groupby=args.label_col, method="wilcoxon")

    col = adata.obs[args.label_col]
    groups = list(col.cat.categories) if hasattr(col, "cat") else sorted(col.unique())
    names = adata.uns["rank_genes_groups"]["names"]

    clusters = []
    for g in groups:
        top = [str(names[g][i]) for i in range(args.top_n)]
        clusters.append(
            {
                "cluster_id": str(g),
                "ground_truth": str(g),
                "top_genes": top,
                "neighbors": [],
            }
        )

    os.makedirs(args.out_dir, exist_ok=True)
    out = os.path.join(args.out_dir, f"{args.section}.json")
    with open(out, "w") as f:
        json.dump(
            {
                "dataset": "DLPFC (Maynard 2021)",
                "section_id": args.section,
                "clusters": clusters,
            },
            f,
            indent=2,
        )
    print(f"Wrote {out} ({len(clusters)} layers)")


if __name__ == "__main__":
    main()
