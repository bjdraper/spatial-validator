"""Pre-warm the literature cache for a dataset (option B).

Runs live PubMed queries for the marker genes that appear in a dataset's
fixtures and writes them into `literature.cache_dir`, so the demo / benchmark
runs from a committed, offline, reproducible snapshot. Re-running is cheap:
already-cached queries are served from disk.

    python data_prep/warm_litcache.py --config configs/dlpfc.yaml
    python data_prep/warm_litcache.py --config configs/dlpfc.yaml --top-genes 5

Generalizes to any new dataset: point it at the new config and it warms that
dataset's cache from its own fixtures + tissue context.
"""
import argparse
import glob
import json
import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent import literature  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--top-genes", type=int, default=3,
                    help="how many top genes per cluster to warm (default 3)")
    args = ap.parse_args()

    with open(args.config) as f:
        cfg = yaml.safe_load(f)
    if not (cfg.get("literature") or {}).get("enabled"):
        sys.exit("literature.enabled is false in this config — nothing to warm.")
    # Force live so warming actually populates the cache even if source=cache_only.
    cfg["literature"] = {**cfg["literature"], "source": "pubmed"}

    # Strip parenthetical abbreviations from the tissue ("... cortex (DLPFC)")
    # and omit the dataset's label code (WM, L5, ...) — both are noise to PubMed
    # and tank the hit rate. Gene + species + plain tissue + "marker" works.
    import re
    tissue = re.sub(r"\s*\([^)]*\)", "", cfg.get("tissue", "")).strip()
    species = cfg.get("species", "")
    queries = set()
    for fp in sorted(glob.glob(os.path.join(cfg["fixtures"], "*.json"))):
        data = json.load(open(fp))
        for c in data.get("clusters", []):
            for gene in c.get("top_genes", [])[: args.top_genes]:
                queries.add(f"{gene} {species} {tissue} marker".strip())

    print(f"Warming {len(queries)} queries -> {cfg['literature']['cache_dir']}")
    hits = 0
    for i, q in enumerate(sorted(queries), 1):
        r = literature.search(q, cfg)
        n = len(r.get("matches", []))
        hits += n > 0
        print(f"  [{i:>3}/{len(queries)}] {n} refs  {q}")
    print(f"\nDone. {hits}/{len(queries)} queries returned >=1 reference.")


if __name__ == "__main__":
    main()
