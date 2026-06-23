"""Build a region-as-cluster fixture set from the squidpy mouse-brain Visium demo.

Mirrors the existing DLPFC/MERFISH fixtures (cluster_id + top DE genes +
ground_truth + spatial neighbours), but the task here is ANATOMICAL REGION
classification on a coronal section. The dataset ships expert region labels in
`adata.obs['cluster']`; we collapse the fine sub-clusters (Cortex_1..5,
Thalamus_1/2, ...) to coarse regions, compute each region's top differentially
expressed genes (scanpy, technical genes filtered), and derive a region spatial
adjacency graph for the agent's adjacency_rules tool + partial-credit scoring.

    python data_prep/build_fixtures_squidpy.py \
        --out data/fixtures/mousebrain/coronal.json \
        --adjacency-out data/fixtures/mousebrain/_adjacency.json

Needs scanpy + squidpy (data_prep-only deps; the agent runtime is stdlib + SDK).
The downloaded .h5ad and the built fixtures are PRIVATE artifacts (gitignored).
"""
import argparse
import json
import os
import re
import warnings

warnings.filterwarnings("ignore")
import numpy as np  # noqa: E402
import scanpy as sc  # noqa: E402
import squidpy as sq  # noqa: E402

# Fine sub-cluster label -> coarse anatomical region (first matching substring).
REGION_MAP = [
    ("pyramidal_layer_dentate", "Hippocampus"),  # dentate gyrus granule layer
    ("pyramidal_layer", "Hippocampus"),          # CA pyramidal layer
    ("hippocampus", "Hippocampus"),
    ("cortex", "Cortex"),
    ("hypothalamus", "Hypothalamus"),  # before "thalamus" — it contains that substring
    ("thalamus", "Thalamus"),
    ("striatum", "Striatum"),
    ("fiber", "Fiber_tract"),
    ("ventricle", "Lateral_ventricle"),
]

# Technical / non-discriminative genes to drop from marker lists (same spirit as
# the DLPFC fixture prep: mito, ribosomal, haemoglobin, lncRNA, predicted genes).
_TECH = re.compile(
    r"^(mt-|Rp[sl]\d|Hb[ab]-|Gm\d|Malat1$|Neat1$|Xist$|.*Rik$|.*-ps\d*$)", re.I
)


def coarse_region(label):
    low = str(label).lower()
    for kw, region in REGION_MAP:
        if kw in low:
            return region
    return None


def top_genes_for(adata, region, n=15):
    names = adata.uns["rank_genes_groups"]["names"][region]
    out = []
    for g in names:
        if _TECH.match(g):
            continue
        out.append(g)
        if len(out) >= n:
            break
    return out


def region_adjacency(adata, region_key, min_edges=8):
    """Two regions are adjacent if enough spots of one border spots of the other
    in the Visium hex grid. Returns {region: [adjacent regions]} (symmetric)."""
    sq.gr.spatial_neighbors(adata, coord_type="grid", n_neighs=6)
    conn = adata.obsp["spatial_connectivities"].tocoo()
    regions = adata.obs[region_key].to_numpy()
    counts = {}
    for i, j in zip(conn.row, conn.col):
        a, b = regions[i], regions[j]
        if a != b:
            counts[(a, b)] = counts.get((a, b), 0) + 1
    adj = {r: set() for r in np.unique(regions)}
    for (a, b), c in counts.items():
        # symmetric border strength (edges counted both directions)
        if c + counts.get((b, a), 0) >= min_edges * 2:
            adj[a].add(b)
            adj[b].add(a)
    return {r: sorted(v) for r, v in adj.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--adjacency-out", default=None,
                    help="also write the derived region adjacency dict (for the config)")
    ap.add_argument("--n-genes", type=int, default=15)
    ap.add_argument("--min-edges", type=int, default=8,
                    help="min bordering spot-pairs to call two regions adjacent")
    args = ap.parse_args()

    adata = sq.datasets.visium_hne_adata()  # auto-downloads + caches
    adata.obs["region"] = [coarse_region(c) for c in adata.obs["cluster"]]
    adata = adata[adata.obs["region"].notna()].copy()
    adata.obs["region"] = adata.obs["region"].astype("category")

    # DE per region on the log-normalised .X (use_raw=False: adata.raw holds the
    # un-logged counts, which rank_genes_groups would otherwise default to).
    sc.tl.rank_genes_groups(adata, "region", method="wilcoxon", use_raw=False)
    adj = region_adjacency(adata, "region", min_edges=args.min_edges)

    regions = list(adata.obs["region"].cat.categories)
    clusters = []
    for r in regions:
        clusters.append({
            "cluster_id": r,
            "ground_truth": r,
            "top_genes": top_genes_for(adata, r, args.n_genes),
            "neighbors": adj.get(r, []),
        })

    payload = {
        "dataset": "squidpy visium_hne (mouse brain coronal, 10x Visium H&E)",
        "section_id": "coronal",
        "clusters": clusters,
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(payload, f, indent=2)

    if args.adjacency_out:
        with open(args.adjacency_out, "w") as f:
            json.dump(adj, f, indent=2)

    print(f"Wrote {args.out}: {len(clusters)} regions "
          f"({adata.n_obs} spots after collapse).")
    print("Region adjacency (paste into the config):")
    for r in regions:
        print(f"  {r}: {adj.get(r, [])}")
    for c in clusters:
        print(f"  {c['cluster_id']:<18} -> {', '.join(c['top_genes'][:8])} ...")


if __name__ == "__main__":
    main()
