"""Evaluation harness. Runs the agent over a dataset's fixtures and scores it.

Usage (from the repo root):
    python eval/run_eval.py --config configs/dlpfc.yaml
    python eval/run_eval.py --config configs/dlpfc.yaml --limit 3   # quick check

Outputs accuracy + a rubric score + a confusion matrix, and writes full
per-cluster traces to runs/ for debugging and reproducibility.
"""
import argparse
import glob
import json
import os
import sys

import yaml

# Allow running from the repo root without installing the package.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import load_kb, make_client, predict  # noqa: E402


def _load_dotenv(path=".env"):
    """Minimal .env loader (no dependency) so a teammate's key just works."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def load_fixtures(path):
    clusters = []
    for f in sorted(glob.glob(os.path.join(path, "*.json"))):
        with open(f) as fh:
            data = json.load(fh)
        for c in data.get("clusters", []):
            c["_section"] = data.get("section_id", os.path.basename(f))
            clusters.append(c)
    return clusters


def score(pred, truth, cfg):
    if pred == truth:
        return 1.0
    if pred in (cfg.get("adjacency") or {}).get(truth, []):
        return cfg.get("adjacent_partial_credit", 0.0)
    return 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--limit", type=int, default=None, help="cap number of clusters")
    ap.add_argument("--out", default="runs")
    ap.add_argument("--resume", action="store_true",
                    help="reuse successful predictions in <out>/traces.json; re-run only errored/missing")
    ap.add_argument("--model", default=None, help="override the model id in the config")
    ap.add_argument("--provider", default=None,
                    help="override the provider: anthropic | openai | ollama")
    ap.add_argument("--base-url", default=None,
                    help="override the OpenAI-compatible base URL (openai/ollama)")
    args = ap.parse_args()

    with open(args.config) as f:
        cfg = yaml.safe_load(f)
    if args.model:
        cfg["model"] = args.model
    if args.provider:
        cfg["provider"] = args.provider
    if args.base_url:
        cfg["base_url"] = args.base_url
    kb = load_kb(cfg)
    _load_dotenv()
    client = make_client(cfg)  # anthropic | openai | ollama, per cfg/--provider

    clusters = load_fixtures(cfg["fixtures"])
    if args.limit:
        clusters = clusters[: args.limit]

    os.makedirs(args.out, exist_ok=True)
    traces_path = os.path.join(args.out, "traces.json")

    # Resume: reuse prior successful predictions; re-run only errored/missing.
    prior = []
    if args.resume and os.path.exists(traces_path):
        with open(traces_path) as f:
            prior = json.load(f)
        cached_n = sum(1 for e in prior if isinstance((e or {}).get("prediction"), dict))
        print(f"resume: {cached_n} cached predictions in {traces_path}\n")

    # Fixed-length trace list aligned to clusters, seeded from prior.
    traces = (list(prior)[: len(clusters)] + [None] * len(clusters))[: len(clusters)]
    rubric_total, exact, graded = 0.0, 0, 0
    confusion = {}

    for i, cl in enumerate(clusters):
        prev = traces[i]
        cached = (
            isinstance(prev, dict)
            and prev.get("cluster_id") == cl["cluster_id"]
            and isinstance(prev.get("prediction"), dict)
        )
        if cached:
            pred, trace, tag = prev["prediction"], prev, "cached"
        else:
            try:
                pred, trace = predict(client, cl, cfg, kb)
            except Exception as exc:  # a transient API error shouldn't kill the run
                print(f"[{cl['cluster_id']:<10}] ERROR: {type(exc).__name__}: {exc}")
                traces[i] = {"cluster_id": cl["cluster_id"], "error": str(exc)}
                with open(traces_path, "w") as f:
                    json.dump(traces, f, indent=2, default=str)
                continue
            tag = "run"

        traces[i] = trace
        p, t = pred["predicted_label"], cl.get("ground_truth")
        s = score(p, t, cfg) if t else None
        if s is not None:
            graded += 1
            rubric_total += s
            exact += int(p == t)
            confusion.setdefault(t, {}).setdefault(p, 0)
            confusion[t][p] += 1
        with open(traces_path, "w") as f:  # incremental: crash-safe + resumable
            json.dump(traces, f, indent=2, default=str)
        print(
            f"[{cl['cluster_id']:<10}] pred={p:<4} truth={t} "
            f"score={s} conf={pred['confidence']} ({tag}, {trace.get('elapsed_s', '-')}s)"
        )

    print("\n=== Summary ===")
    if graded:
        print(f"Exact accuracy : {exact}/{graded} = {exact / graded:.1%}")
        print(f"Rubric score   : {rubric_total / graded:.1%}  (adjacent layers get partial credit)")
    else:
        print("No ground-truth labels in fixtures — predictions only.")

    with open(os.path.join(args.out, "traces.json"), "w") as f:
        json.dump(traces, f, indent=2, default=str)
    with open(os.path.join(args.out, "confusion.json"), "w") as f:
        json.dump(confusion, f, indent=2)
    print(f"Traces  -> {args.out}/traces.json")
    print(f"Confusion -> {args.out}/confusion.json")


if __name__ == "__main__":
    main()
