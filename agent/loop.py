"""The bounded, auditable Actor-Critic agent loop.

Control guarantees:
  * hard caps on iterations, tool calls, and wall-clock time
  * pinned model id (from config) for reproducibility
  * a full trace of every step, returned alongside the prediction
  * read-only tools, so a run can never take a destructive action
  * a final structured-output call enforces the prediction contract

The agent works in three explicit, trace-tagged stages:
  ACTOR      gather positive evidence and commit to ONE primary hypothesis
  CRITIC     aggressively try to disprove it — housekeeping-vs-biomarker
             discrimination, shared-marker confounders, literature provenance,
             negative markers — and rate its vulnerability. This disproof step
             is structurally enforced (the loop nudges once if the Critic made
             no disproof-tool call).
  RESOLUTION a final no-tools call emits JSON matching `prediction_schema`, so
             eval scoring is mechanical.

The loop is provider-agnostic: it speaks the neutral message format from
`providers.py` and calls `client.create(...)`, so the same logic runs against
Claude (Anthropic), OpenAI/Codex, or a local Ollama model.
"""
import json
import re
import time

from .prompts import ACTOR_CRITIC_TEMPLATE
from .providers import _extract_json
from .schema import prediction_schema
from .tools import TOOLS, dispatch

# Tools available to each phase. The Actor forms a hypothesis from markers and
# spatial context; uniprot_lookup + search_literature are reserved for the Critic
# so the disproof evidence genuinely belongs to the critique pass (and isn't
# front-loaded into the Actor phase). The Critic gets the full arsenal.
_ACTOR_TOOLS = {"marker_lookup", "confounder_lookup", "adjacency_rules"}
_CRITIC_TOOLS = {"marker_lookup", "confounder_lookup", "adjacency_rules",
                 "uniprot_lookup", "search_literature"}

# Critic tools that count as a genuine attempt to disprove the hypothesis.
_DISPROOF_TOOLS = {"confounder_lookup", "uniprot_lookup", "search_literature"}


def _tools_for(names):
    """Subset of the TOOLS schema list whose names are in `names`."""
    return [t for t in TOOLS if t["name"] in names]


def _short(out):
    """One-line summary of a tool result, for the live demo."""
    if isinstance(out, dict):
        if out.get("entries"):
            e = out["entries"][0]
            return f"{e.get('identities')} ({e.get('specificity', '?')})"
        if "n_cell_types" in out:  # confounder_lookup
            return f"{out['n_cell_types']} cell types, {out.get('promiscuity')} promiscuity"
        if "subcellular_location" in out or out.get("protein_name"):  # uniprot_lookup
            return out.get("protein_name") or "uniprot hit"
        if out.get("found") is False:
            return out.get("note", "not found")[:70]
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
        "Resolve this cluster to one candidate label using the ACTOR-CRITIC "
        "framework: first form a primary hypothesis, then aggressively try to "
        "disprove it before deciding."
    )


_ACTOR_DIRECTOR = (
    "[ACTOR] Form ONE primary hypothesis. Use marker_lookup (and adjacency_rules "
    "where spatial order applies) on the top DEGs, then state the single "
    "best-supported candidate label and its positive-marker justification."
)

_CRITIC_DIRECTOR = (
    "[CRITIC] Now aggressively try to disprove that hypothesis. You MUST: "
    "(1) for each top DEG, classify it as housekeeping vs biomarker using "
    "uniprot_lookup (function/localization) and confounder_lookup (how many cell "
    "types share it), noting which cell types/tissue it pertains to; "
    "(2) use confounder_lookup to surface confounding cell types that share the "
    "top DEGs; (3) use search_literature for marker provenance and known "
    "co-expression panels; (4) scan for negative markers of the hypothesis; "
    "(5) assign a vulnerability_score (high/medium/low). If a fatal flaw appears, "
    "pivot to the next-best candidate and re-critique it the same way."
)

_CRITIC_NUDGE = (
    "[CRITIC] You have not yet used any disproof tool (confounder_lookup, "
    "uniprot_lookup, or search_literature). Do so now to stress-test the "
    "hypothesis before resolving."
)


def _run_phase(client, system, messages, cfg, kb, trace, *, phase, director,
               tools, start, timeout_s, max_tool_calls, max_iters, pmids_seen, verbose):
    """Run one bounded tool-using phase. Mutates messages/trace/pmids_seen.

    `tools` is the phase's allowed TOOLS subset. Returns the set of tool names
    called during this phase (used to enforce the Critic's disproof step).
    """
    messages.append({"role": "user", "content": director})
    if verbose:
        print(f"\n  === {phase.upper()} ===")
    tools_called = set()

    for _ in range(max_iters):
        if time.monotonic() - start > timeout_s:
            trace["timeout"] = True
            break

        resp = client.create(
            system=system, messages=messages, tools=tools, max_tokens=4000
        )
        messages.append(
            {"role": "assistant", "text": resp.text, "tool_calls": resp.tool_calls}
        )
        trace["steps"].append(
            {"phase": phase, "stop_reason": resp.stop_reason, "text": resp.text}
        )
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
                tools_called.add(call["name"])
            if call["name"] == "search_literature" and isinstance(out, dict):
                for m in out.get("matches", []):
                    if m.get("pmid"):
                        pmids_seen.add(str(m["pmid"]))
            trace["steps"].append(
                {"phase": phase, "tool": call["name"], "input": call["input"], "output": out}
            )
            if verbose:
                print(f"     \U0001f527 {call['name']}({json.dumps(call['input'])}) -> {_short(out)}")
            results.append({"id": call["id"], "name": call["name"], "output": out})
        messages.append({"role": "tool_results", "results": results})

    return tools_called


def _fallback_prediction(cfg, reason):
    """Schema-shaped placeholder when the Resolution call yields no JSON, so a
    single bad turn degrades gracefully instead of crashing the run."""
    labels = list(cfg["label_vocabulary"])
    return {
        "initial_hypothesis": "", "predicted_label": labels[0],
        "confidence": "low", "vulnerability_score": "high",
        "supporting_genes": [], "gene_classification": [], "detected_panels": [],
        "negative_checks": [], "ambiguous_between": [],
        "reasoning": f"RESOLUTION FAILED: {reason}", "citations": [],
    }


def predict(client, cluster, cfg, kb, *, max_iters_actor=2, max_iters_critic=2,
            max_tool_calls=80, timeout_s=90, verbose=False):
    """Run the agent on one cluster. Returns (prediction_dict, trace_dict).

    Lean 3-phase Actor-Critic loop: each phase is capped to 1-2 iterations so a
    model that batches its tool calls (e.g. one round of marker_lookup across all
    DEGs) finishes a phase in a single turn. The tool-call budget is generous
    enough that wide batching never thrashes on "budget exceeded".

    `client` is any provider from providers.make_client(). verbose=True prints
    interim reasoning and each tool call live, for the demo. The eval leaves it
    off.
    """
    system = cfg.get("system_prompt") or ACTOR_CRITIC_TEMPLATE
    messages = [{"role": "user", "content": _user_query(cluster, cfg)}]
    trace = {"cluster_id": cluster["cluster_id"], "steps": [], "tool_calls": 0,
             "phases": ["actor", "critic", "resolution"]}
    pmids_seen = set()  # PMIDs the agent actually retrieved, for citation grounding
    start = time.monotonic()

    common = dict(start=start, timeout_s=timeout_s, max_tool_calls=max_tool_calls,
                  pmids_seen=pmids_seen, verbose=verbose)

    # --- ACTOR: commit to a primary hypothesis -----------------------------
    _run_phase(client, system, messages, cfg, kb, trace,
               phase="actor", director=_ACTOR_DIRECTOR, tools=_tools_for(_ACTOR_TOOLS),
               max_iters=max_iters_actor, **common)

    # --- CRITIC: aggressively try to disprove it ---------------------------
    critic_tools = _run_phase(client, system, messages, cfg, kb, trace,
                              phase="critic", director=_CRITIC_DIRECTOR,
                              tools=_tools_for(_CRITIC_TOOLS),
                              max_iters=max_iters_critic, **common)
    # Enforce the disproof step: if the Critic ran no disproof tool, nudge once.
    enforced = False
    if not (critic_tools & _DISPROOF_TOOLS) and trace["tool_calls"] <= max_tool_calls \
            and time.monotonic() - start <= timeout_s:
        enforced = True
        more = _run_phase(client, system, messages, cfg, kb, trace,
                          phase="critic", director=_CRITIC_NUDGE,
                          tools=_tools_for(_CRITIC_TOOLS), max_iters=2, **common)
        critic_tools |= more
    trace["critic_disproof_tools"] = sorted(critic_tools & _DISPROOF_TOOLS)
    trace["critic_disproof_enforced"] = enforced

    # --- RESOLUTION: structured-output contract ----------------------------
    messages.append({
        "role": "user",
        "content": "[RESOLUTION] Reconcile the Actor's hypothesis with the "
                   "Critic's findings and output your final prediction as JSON "
                   "matching the schema. Output JSON only.",
    })
    schema = prediction_schema(cfg["label_vocabulary"])
    # Try the structured call up to twice (an empty/no-JSON turn can happen if a
    # model spends its whole budget on thinking), then fall back gracefully.
    prediction = None
    for attempt in range(2):
        final = client.create(system=system, messages=messages,
                               json_schema=schema, max_tokens=4000)
        trace["steps"].append({"phase": "resolution", "stop_reason": final.stop_reason,
                               "text": final.text})
        try:
            prediction = _extract_json(final.text)
            break
        except ValueError:
            messages.append({"role": "user",
                             "content": "Your previous turn contained no JSON. "
                                        "Output ONLY the prediction JSON now."})
    if prediction is None:
        trace["resolution_error"] = "no JSON after retry"
        prediction = _fallback_prediction(cfg, "model returned no JSON object")

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
