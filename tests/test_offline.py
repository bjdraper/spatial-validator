"""Offline smoke test — runs WITHOUT an API key.

Exercises everything except the paid model call: config/KB/fixture loading,
the tools (against the real KB), the structured-output schema, the full agent
loop wiring (message assembly, tool_use parsing, dispatch, trace), and scoring.
The Claude API client is mocked.

    python tests/test_offline.py
"""
import json
import os
import sys
from types import SimpleNamespace as NS

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)  # config paths are repo-root relative
sys.path.insert(0, REPO)

import yaml  # noqa: E402

from agent import dispatch, load_kb, predict  # noqa: E402
from agent.schema import prediction_schema  # noqa: E402
from eval.run_eval import load_fixtures, score  # noqa: E402


# --- a fake Claude client: no network, scripted responses ---------------------
def _text(t):
    return NS(type="text", text=t)


def _tool(tid, name, inp):
    return NS(type="tool_use", id=tid, name=name, input=inp)


class _FakeMessages:
    def __init__(self):
        self.calls = 0

    def create(self, **kw):
        self.calls += 1
        # The final prediction call is the one carrying output_config.format.
        if (kw.get("output_config") or {}).get("format"):
            payload = {
                "predicted_label": "L4",
                "confidence": "high",
                "supporting_genes": ["RORB"],
                "negative_checks": ["no WM markers (MOBP/MBP) present"],
                "ambiguous_between": [],
                "reasoning": "mock final answer",
                "citations": ["brain_markers.json: RORB"],
            }
            return NS(content=[_text(json.dumps(payload))], stop_reason="end_turn")
        # First turn: request a tool call so we exercise dispatch.
        if self.calls == 1:
            return NS(
                content=[_text("Checking RORB."), _tool("t1", "marker_lookup", {"gene": "RORB"})],
                stop_reason="tool_use",
            )
        return NS(content=[_text("Enough evidence.")], stop_reason="end_turn")


class _FakeClient:
    def __init__(self):
        self.messages = _FakeMessages()


def main():
    cfg = yaml.safe_load(open("configs/dlpfc.yaml"))
    kb = load_kb(cfg)
    ok = True

    # 1. KB + tools
    r = dispatch("marker_lookup", {"gene": "RORB"}, cfg, kb)
    assert r["found"] and "L4" in r["entries"][0]["identities"], r
    print(f"PASS  marker_lookup(RORB) -> L4 ({r['entries'][0]['specificity']})")

    r = dispatch("marker_lookup", {"gene": "MOBP"}, cfg, kb)
    assert r["found"] and r["entries"][0]["identities"] == ["WM"]
    print("PASS  marker_lookup(MOBP) -> WM")

    r = dispatch("adjacency_rules", {"label": "L4"}, cfg, kb)
    assert set(r["can_be_adjacent_to"]) == {"L3", "L5"}, r
    print(f"PASS  adjacency_rules(L4) -> {r['can_be_adjacent_to']}")

    # 2. Schema reflects the dataset's label vocabulary
    sch = prediction_schema(cfg["label_vocabulary"])
    assert sch["properties"]["predicted_label"]["enum"] == cfg["label_vocabulary"]
    print(f"PASS  schema enum = {cfg['label_vocabulary']}")

    # 3. Fixtures load
    clusters = load_fixtures(cfg["fixtures"])
    assert clusters, "no fixtures found — run data_prep/fetch_dlpfc.R"
    print(f"PASS  loaded {len(clusters)} clusters from {cfg['fixtures']}")

    # 4. Full loop wiring with the mocked client
    cluster = next(c for c in clusters if c["ground_truth"] == "L4")
    pred, trace = predict(_FakeClient(), cluster, cfg, kb)
    assert pred["predicted_label"] in cfg["label_vocabulary"]
    assert trace["tool_calls"] >= 1
    assert any(s.get("tool") == "marker_lookup" for s in trace["steps"])
    print(f"PASS  predict() wiring: pred={pred['predicted_label']}, "
          f"tool_calls={trace['tool_calls']}, steps={len(trace['steps'])}")

    # 5. Scoring rubric (exact / adjacent / miss)
    assert score("L4", "L4", cfg) == 1.0
    assert score("L3", "L4", cfg) == cfg["adjacent_partial_credit"]
    assert score("WM", "L4", cfg) == 0.0
    print("PASS  scoring: exact=1.0, adjacent=0.5, miss=0.0")

    print("\nAll offline checks passed. The only thing left untested is the "
          "real model call (needs ANTHROPIC_API_KEY).")
    return ok


if __name__ == "__main__":
    main()
