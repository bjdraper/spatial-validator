"""Live ~90-second demo — runs ONE cluster and shows the agent's decisions in
the terminal as they happen (interim reasoning + each tool call + the result).

    python eval/demo.py --config configs/dlpfc.yaml --section 151673 --cluster L5
    python eval/demo.py --config configs/merfish.yaml --cluster Oligodendrocyte

Defaults to the first cluster if --section/--cluster aren't given. --top-genes
trims the input so the run stays inside the demo window.
"""
import argparse
import glob
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
sys.path.insert(0, REPO)

import yaml  # noqa: E402
import anthropic  # noqa: E402

from agent import load_kb, predict  # noqa: E402


def _load_dotenv(path=".env"):
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--section", default=None)
    ap.add_argument("--cluster", default=None)
    ap.add_argument("--top-genes", type=int, default=8, help="trim input genes")
    ap.add_argument("--effort", default="low", help="low|medium|high (lower = faster demo)")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(args.config))
    if cfg.get("effort"):
        cfg["effort"] = args.effort  # snappier than the full-eval effort
    kb = load_kb(cfg)
    _load_dotenv()
    client = anthropic.Anthropic(max_retries=6)

    cl = sec = None
    for f in sorted(glob.glob(os.path.join(cfg["fixtures"], "*.json"))):
        d = json.load(open(f))
        if args.section and d.get("section_id") != args.section:
            continue
        for c in d["clusters"]:
            if args.cluster and c["cluster_id"] != args.cluster:
                continue
            cl, sec = c, d.get("section_id")
            break
        if cl:
            break
    if cl is None:
        print("No matching cluster — check --section/--cluster.")
        return

    cl = dict(cl)
    cl["top_genes"] = cl["top_genes"][: args.top_genes]
    truth = cl.get("ground_truth")

    bar = "=" * 66
    print(f"\n{bar}\n SPATIAL MARKER VALIDATOR  -  live demo\n{bar}")
    print(f" dataset  : {os.path.basename(args.config)}   (section {sec})")
    print(f" cluster  : {cl['cluster_id']}   [expert label hidden until the end]")
    print(f" model    : {cfg['model']}   (effort: {cfg.get('effort')})")
    print(f" genes in : {', '.join(cl['top_genes'])}")
    print("-" * 66)
    print(" agent working  (interim reasoning + tool calls below):")

    pred, trace = predict(client, cl, cfg, kb, verbose=True)

    verdict = "MATCH" if pred["predicted_label"] == truth else "MISS"
    print("\n" + "-" * 66)
    print(f" PREDICTION : {pred['predicted_label']}   "
          f"confidence: {pred['confidence']}   [{verdict} vs expert: {truth}]")
    print(f" supporting : {', '.join(pred['supporting_genes'])}")
    if pred.get("negative_checks"):
        print(f" neg checks : {'; '.join(pred['negative_checks'])}")
    if pred.get("ambiguous_between"):
        print(f" ambiguous  : {', '.join(pred['ambiguous_between'])}")
    print(f" reasoning  : {pred['reasoning']}")
    if pred.get("citations"):
        print(f" citations  : {', '.join(pred['citations'])}")
    print(f"\n {trace['tool_calls']} tool calls, {trace['elapsed_s']}s")
    print(bar + "\n")


if __name__ == "__main__":
    main()
