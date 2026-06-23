"""The bounded, auditable agent loop.

Control guarantees:
  * hard caps on iterations, tool calls, and wall-clock time
  * pinned model id (from config) for reproducibility
  * a full trace of every step, returned alongside the prediction
  * read-only tools, so a run can never take a destructive action
  * a final structured-output call enforces the prediction contract

The agent gathers evidence with tools, then a final no-tools call emits JSON
matching `prediction_schema`, so eval scoring is mechanical.

The loop is provider-agnostic: it speaks the neutral message format from
`providers.py` and calls `client.create(...)`, so the same logic runs against
Claude (Anthropic), OpenAI/Codex, or a local Ollama model.
"""
import json
import re
import time

from .providers import _extract_json
from .schema import prediction_schema
from .tools import TOOLS, dispatch


def _short(out):
    """One-line summary of a tool result, for the live demo."""
    if isinstance(out, dict):
        if out.get("entries"):
            e = out["entries"][0]
            return f"{e.get('identities')} ({e.get('specificity', '?')})"
        if out.get("found") is False:
            return "not in KB"
        if "can_be_adjacent_to" in out:
            return f"can border {out['can_be_adjacent_to']}"
        if "matches" in out:
            return f"{len(out['matches'])} literature match(es)" if out["matches"] else "no literature indexed"
        if "error" in out:
            return f"error: {out['error']}"
    return str(out)[:70]


def _user_query(cluster, cfg):
    genes = ", ".join(cluster["top_genes"])
    neighbors = cluster.get("neighbors") or []
    nb = f"\nSpatially adjacent cluster IDs: {neighbors}" if neighbors else ""
    return (
        f"Cluster ID: {cluster['cluster_id']}\n"
        f"Species / tissue: {cfg['species']} {cfg['tissue']}\n"
        f"Candidate labels: {cfg['label_vocabulary']}\n"
        f"Top differentially expressed marker genes (highest first): {genes}{nb}\n\n"
        "Identify the most likely cell type / tissue layer for this cluster. "
        "Use the tools to look up each marker, check for negative-marker "
        "violations, and verify spatial plausibility before deciding. If the "
        "evidence genuinely splits between labels, pick the best-supported one "
        "and list the rest in ambiguous_between."
    )


def predict(client, cluster, cfg, kb, *, max_iters=4, max_tool_calls=25, timeout_s=90, verbose=False):
    """Run the agent on one cluster. Returns (prediction_dict, trace_dict).

    `client` is any provider from providers.make_client(). verbose=True prints
    interim reasoning and each tool call live, for the demo. The eval leaves it
    off.
    """
    system = cfg["system_prompt"]
    messages = [{"role": "user", "content": _user_query(cluster, cfg)}]
    trace = {"cluster_id": cluster["cluster_id"], "steps": [], "tool_calls": 0}
    pmids_seen = set()  # PMIDs the agent actually retrieved, for citation grounding
    start = time.monotonic()

    for _ in range(max_iters):
        if time.monotonic() - start > timeout_s:
            trace["timeout"] = True
            break

        resp = client.create(
            system=system, messages=messages, tools=TOOLS, max_tokens=4000
        )
        messages.append(
            {"role": "assistant", "text": resp.text, "tool_calls": resp.tool_calls}
        )
        trace["steps"].append({"stop_reason": resp.stop_reason, "text": resp.text})
        if verbose:
            txt = " ".join(resp.text.split())  # collapse whitespace/markdown
            if txt:
                if len(txt) > 240:
                    txt = txt[:240] + " ..."
                print(f"\n  \U0001f4ad {txt}")

        if not resp.wants_tools:
            break

        results = []
        for call in resp.tool_calls:
            trace["tool_calls"] += 1
            if trace["tool_calls"] > max_tool_calls:
                out = {"error": "tool-call budget exceeded"}
            else:
                out = dispatch(call["name"], call["input"], cfg, kb)
            if call["name"] == "search_literature" and isinstance(out, dict):
                for m in out.get("matches", []):
                    if m.get("pmid"):
                        pmids_seen.add(str(m["pmid"]))
            trace["steps"].append(
                {"tool": call["name"], "input": call["input"], "output": out}
            )
            if verbose:
                print(f"     \U0001f527 {call['name']}({json.dumps(call['input'])}) -> {_short(out)}")
            results.append({"id": call["id"], "name": call["name"], "output": out})
        messages.append({"role": "tool_results", "results": results})

    # Final turn: no tools, structured output -> clean JSON contract.
    messages.append(
        {"role": "user", "content": "Now output your final prediction as JSON."}
    )
    final = client.create(
        system=system,
        messages=messages,
        json_schema=prediction_schema(cfg["label_vocabulary"]),
        max_tokens=2000,
    )
    prediction = _extract_json(final.text)

    # Citation grounding: flag any PMID the agent cited but never retrieved.
    cited_pmids = set(re.findall(r"\b\d{7,8}\b", " ".join(prediction.get("citations", []))))
    ungrounded = sorted(cited_pmids - pmids_seen)
    trace["literature"] = {
        "pmids_retrieved": sorted(pmids_seen),
        "ungrounded_pmid_citations": ungrounded,
    }
    prediction["citation_grounded"] = not ungrounded

    trace["prediction"] = prediction
    trace["elapsed_s"] = round(time.monotonic() - start, 1)
    return prediction, trace
