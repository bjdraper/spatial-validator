"""Build MERFISH mouse-hypothalamus fixtures (cell-type-as-cluster).

Demonstrates the agent generalizing to a non-cortical, cell-TYPE task with a
different label vocabulary — same agent code, new config + KB + fixtures.

The 16 fine-grained classes are collapsed into 8 major cell types; the Blank
control probes and the "Ambiguous" class are dropped.

    python data_prep/fetch_merfish.py
"""
import json
import os
import warnings

warnings.filterwarnings("ignore")
import scanpy as sc  # noqa: E402
import squidpy as sq  # noqa: E402

TOP_N = 15
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(REPO, "data", "fixtures", "merfish")

_MAJOR = {"Excitatory", "Inhibitory", "Astrocyte", "Microglia", "Ependymal", "Pericytes"}


def collapse(c):
    if c.startswith("OD "):
        return "Oligodendrocyte"
    if c.startswith("Endothelial"):
        return "Endothelial"
    return c if c in _MAJOR else None  # "Ambiguous" -> None -> dropped


def main():
    ad = sq.datasets.merfish()
    ad = ad[:, ~ad.var_names.str.startswith("Blank")].copy()  # drop control probes
    ad.obs["celltype"] = ad.obs["Cell_class"].astype(str).map(collapse)
    ad = ad[~ad.obs["celltype"].isna()].copy()

    sc.pp.normalize_total(ad, target_sum=1e4)
    sc.pp.log1p(ad)
    ad.obs["celltype"] = ad.obs["celltype"].astype("category")
    sc.tl.rank_genes_groups(ad, "celltype", method="wilcoxon")

    names = ad.uns["rank_genes_groups"]["names"]
    groups = list(ad.obs["celltype"].cat.categories)
    clusters = []
    for g in groups:
        top = [str(names[g][i]) for i in range(TOP_N)]
        clusters.append(
            {"cluster_id": g, "ground_truth": g, "top_genes": top, "neighbors": []}
        )
        print(f"{g:<16}: {', '.join(top[:8])}")

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "hypothalamus.json")
    with open(out, "w") as f:
        json.dump(
            {
                "dataset": "MERFISH mouse hypothalamus (Moffitt et al. 2018)",
                "section_id": "hypothalamus",
                "clusters": clusters,
            },
            f,
            indent=2,
        )
    print(f"\nWrote {out} ({len(clusters)} cell types)")


if __name__ == "__main__":
    main()
