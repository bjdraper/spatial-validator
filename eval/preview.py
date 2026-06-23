"""Offline evidence preview — NO API, NO cost.

For each cluster, runs the same KB lookups the agent's `marker_lookup` tool
does, and shows the layer "signature": which genes vote for which layers,
weighted by specificity. This is the raw evidence the agent reasons over — NOT
the agent's actual decision (that needs the model + a credit balance).

A naive specificity-weighted argmax is printed only to show how separable the
layers are from markers alone; the real agent does more (negative markers,
adjacency, conflict resolution).

    python eval/preview.py --config configs/dlpfc.yaml --section 151673
"""
import argparse
import collections
import glob
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
sys.path.insert(0, REPO)

import yaml  # noqa: E402

from agent import load_kb  # noqa: E402
from agent.tools import marker_lookup  # noqa: E402

WEIGHT = {"high": 3, "medium": 2, "low": 1, "none": 0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--section", default=None, help="only this section_id")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(args.config))
    kb = load_kb(cfg)

    correct = adjacent = total = 0
    for f in sorted(glob.glob(os.path.join(cfg["fixtures"], "*.json"))):
        d = json.load(open(f))
        if args.section and d.get("section_id") != args.section:
            continue
        print(f"\n{'='*70}\nSECTION {d.get('section_id')}\n{'='*70}")

        for c in d["clusters"]:
            truth = c["ground_truth"]
            votes = collections.Counter()
            print(f"\n--- cluster '{c['cluster_id']}'  (truth: {truth}) ---")
            for g in c["top_genes"]:
                r = marker_lookup(g, cfg, kb)
                if not r.get("found"):
                    print(f"   {g:<10} —       not in KB")
                    continue
                e = r["entries"][0]
                spec, ids = e["specificity"], e["identities"]
                w = WEIGHT[spec]
                for label in ids:
                    votes[label] += w
                flag = "  [WM marker -> negative for grey]" if ids == ["WM"] else ""
                target = ",".join(ids) if ids else "(ignore)"
                print(f"   {g:<10} {spec:<7} -> {target}{flag}")

            sig = ", ".join(f"{lab}:{n}" for lab, n in votes.most_common(5))
            pred = votes.most_common(1)[0][0] if votes else "?"
            total += 1
            if pred == truth:
                correct += 1
                verdict = "hit"
            elif pred in (cfg.get("adjacency") or {}).get(truth, []):
                adjacent += 1
                verdict = "adjacent"
            else:
                verdict = "miss"
            print(f"   SIGNATURE (weighted votes): {sig}")
            print(f"   naive argmax: {pred}   truth: {truth}   [{verdict}]")

    print(f"\n{'='*70}")
    print(f"Naive specificity-vote baseline: {correct}/{total} exact, "
          f"{adjacent}/{total} adjacent.")
    print("(This is the evidence landscape, NOT the agent. The agent reasons "
          "over this same evidence with negative markers, adjacency, and "
          "conflict resolution.)")


if __name__ == "__main__":
    main()
