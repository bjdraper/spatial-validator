"""Interactive, demo-ready walkthrough of the Actor-Critic agent.

Flow:
  1. lists the dataset's clusters,
  2. you pick one and choose a backend (local Ollama / Claude API),
  3. the ACTOR -> CRITIC -> RESOLUTION decisions stream live to the terminal,
  4. it prints a key-gene TABLE (biomarker vs housekeeping, what each gene
     pertains to, KB specificity, shared-marker promiscuity, and which genes
     drove the final call) plus the prediction and the eval confirmation.

    # list clusters:
    python demo/demo_run.py --config configs/merfish.cellmarker.yaml --list

    # run cluster #3 locally (free, offline-ish) or on Claude:
    python demo/demo_run.py --config configs/merfish.cellmarker.yaml --pick 3 --backend local
    python demo/demo_run.py --config configs/merfish.cellmarker.yaml --pick 3 --backend claude

Omit --pick / --backend at an interactive terminal and it prompts you.
"""
import argparse
import json
import os
import sys

import yaml

# Reuse the agent package and the eval helpers (load_fixtures / score / dotenv).
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "eval"))

from agent import load_kb, make_client, predict  # noqa: E402
from run_eval import _load_dotenv, load_fixtures, score  # noqa: E402

LOCAL_MODEL = "qwen2.5:14b"  # recommended local tool-capable model (see CLAUDE.md)

# --- tiny terminal styling (no dependency); auto-disabled when not a TTY -------
_TTY = sys.stdout.isatty()


def _c(code, s):
    return f"\033[{code}m{s}\033[0m" if _TTY else s


def bold(s): return _c("1", s)
def dim(s): return _c("2", s)
def green(s): return _c("32", s)
def yellow(s): return _c("33", s)
def red(s): return _c("31", s)
def cyan(s): return _c("36", s)
def mag(s): return _c("35", s)


def rule(title=""):
    line = "─" * 74
    if title:
        print(f"\n{bold(title)}\n{dim(line)}")
    else:
        print(dim(line))


def list_clusters(clusters):
    print(bold(f"\nClusters in this dataset ({len(clusters)}):"))
    print(dim("  #    cluster_id            section        #genes"))
    for i, c in enumerate(clusters):
        print(f"  {cyan(str(i)):<4} {c['cluster_id']:<20}  {str(c.get('_section','')):<13} "
              f"{len(c.get('top_genes', []))}")
    print(dim("\n  (expert ground-truth labels are hidden so the prediction stays honest)"))


def choose_cluster(clusters, pick):
    if pick is None:
        if not sys.stdin.isatty():
            sys.exit("No --pick given and stdin is not interactive. "
                     "Re-run with --pick <index> (see --list).")
        try:
            pick = int(input(bold("\nPick a cluster by # : ")).strip())
        except (ValueError, EOFError):
            sys.exit("Not a valid index.")
    if not (0 <= pick < len(clusters)):
        sys.exit(f"--pick must be 0..{len(clusters) - 1}")
    return clusters[pick]


def choose_backend(cfg, backend, model):
    """Resolve the run backend: 'local' (Ollama/qwen) or 'claude' (the config's
    Anthropic settings). Prompts interactively when unset at a TTY."""
    if backend is None:
        if sys.stdin.isatty():
            ans = input(bold("Backend — [l]ocal qwen or [c]laude API ? ")).strip().lower()
            backend = "local" if ans.startswith("l") else "claude" if ans.startswith("c") else None
        if backend is None:
            backend = "claude"  # default for non-interactive
    if backend == "local":
        cfg["provider"] = "ollama"
        cfg["model"] = model or LOCAL_MODEL
    elif backend == "claude":
        cfg["provider"] = "anthropic"
        if model:
            cfg["model"] = model
        # else keep the config's model (e.g. claude-sonnet-4-6)
    else:
        sys.exit("--backend must be 'local' or 'claude'")
    return backend


# --- evidence + table ---------------------------------------------------------
def _evidence_by_gene(trace):
    """Pull per-gene evidence the tools actually returned, keyed by UPPER gene."""
    spec, promisc = {}, {}
    for s in trace.get("steps", []):
        out = s.get("output") or {}
        g = str(out.get("gene", "")).upper()
        if not g:
            continue
        if s.get("tool") == "marker_lookup":
            if out.get("entries"):
                spec[g] = out["entries"][0].get("specificity", "?")
            elif out.get("found") is False:
                spec.setdefault(g, "absent")
        elif s.get("tool") == "confounder_lookup":
            if "promiscuity" in out:
                promisc[g] = out.get("promiscuity")
            elif out.get("found") is False:
                promisc.setdefault(g, "—")
    return spec, promisc


_ROLE_COLOR = {"biomarker": green, "housekeeping": red, "ambiguous": yellow}


def gene_table(cluster, pred, trace):
    top = cluster.get("top_genes", [])
    by_gene = {g.get("gene", "").upper(): g
               for g in (pred.get("gene_classification") or [])}
    supporting = {s.upper() for s in (pred.get("supporting_genes") or [])}
    spec, promisc = _evidence_by_gene(trace)

    rule("KEY-GENE TABLE  (▸ = drove the final call)")
    hdr = (f"  {'#':<3}{'GENE':<12}{'ROLE':<13}{'KB SPEC':<9}"
           f"{'SHARED':<9}{'PERTAINS TO':<26}{'▸'}")
    print(bold(hdr))
    print(dim("  " + "─" * 72))

    n_bio = n_hk = 0
    for i, g in enumerate(top, 1):
        gu = g.upper()
        gc = by_gene.get(gu, {})
        role = gc.get("role", "unclassified")
        if role == "biomarker":
            n_bio += 1
        elif role == "housekeeping":
            n_hk += 1
        role_col = _ROLE_COLOR.get(role, dim)
        pert = ", ".join(gc.get("pertains_to", []) or []) or "—"
        if len(pert) > 24:
            pert = pert[:23] + "…"
        sp = spec.get(gu, "—")
        pr = promisc.get(gu, "—")
        star = mag("▸") if gu in supporting else " "
        # explicit padding on plain text; color wraps the already-padded cell
        # (ANSI codes don't affect terminal column width).
        print(f"  {str(i):<3}{g:<12}{role_col(role.ljust(12))} {sp:<8} "
              f"{pr:<8} {pert:<25} {star}")

    print(dim("  " + "─" * 72))
    print(f"  {green(str(n_bio)+' biomarker')} · {red(str(n_hk)+' housekeeping')} · "
          f"{dim(str(len(top)-n_bio-n_hk)+' other/unclassified')}   "
          f"{dim('(of '+str(len(top))+' DEGs)')}")

    panels = pred.get("detected_panels") or []
    if panels:
        print(cyan(bold("\n  Co-expression panels / signatures detected:")))
        for p in panels:
            print(f"    • {p}")


def final_block(cluster, cfg, pred, trace):
    rule("FINAL PREDICTION  (Resolution)")
    hyp = pred.get("initial_hypothesis", "")
    label = pred.get("predicted_label", "?")
    pivoted = hyp and label and (label not in str(hyp))
    if hyp:
        h = hyp if len(hyp) < 100 else hyp[:99] + "…"
        print(f"  Actor's hypothesis  : {dim(h)}")
    print(f"  {bold('Predicted label')}     : {bold(green(label))}"
          + (yellow("   ← Critic pivoted the Actor's call") if pivoted else ""))
    print(f"  Confidence          : {pred.get('confidence','?')}")
    vs = pred.get("vulnerability_score", "?")
    vs_col = {"low": green, "medium": yellow, "high": red}.get(vs, dim)
    print(f"  Vulnerability       : {vs_col(vs)}  {dim('(Critic risk-of-misclassification)')}")
    sup = ", ".join(pred.get("supporting_genes") or []) or "—"
    print(f"  Genes driving call  : {bold(sup)}")

    negs = pred.get("negative_checks") or []
    if negs:
        print(f"\n  {bold('Negative-marker checks:')}")
        for n in negs[:6]:
            nn = n if len(n) < 110 else n[:109] + "…"
            print(f"    • {dim(nn)}")

    cites = pred.get("citations") or []
    if cites:
        grounded = pred.get("citation_grounded", True)
        flag = green("grounded") if grounded else yellow("ungrounded PMIDs flagged")
        print(f"\n  Citations ({flag}): {dim(', '.join(cites[:6]))}")

    # --- evaluation check ---
    rule("EVALUATION CHECK")
    truth = cluster.get("ground_truth")
    if not truth:
        print(dim("  No ground-truth label in this fixture — prediction only."))
        return
    s = score(label, truth, cfg)
    if label == truth:
        verdict = green(bold("✓ CONFIRMED — exact match"))
    elif s > 0:
        verdict = yellow(bold(f"≈ PARTIAL — adjacent label (credit {s})"))
    else:
        verdict = red(bold("✗ MISMATCH"))
    print(f"  Expert ground truth : {bold(truth)}")
    print(f"  Agent prediction    : {bold(label)}")
    print(f"  Result              : {verdict}   {dim(f'score={s}')}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--list", action="store_true", help="list clusters and exit")
    ap.add_argument("--pick", type=int, default=None, help="cluster index from --list")
    ap.add_argument("--backend", choices=["local", "claude"], default=None,
                    help="local (Ollama/qwen) or claude (Anthropic API)")
    ap.add_argument("--model", default=None, help="override the model id")
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--out", default="runs/demo_trace.json")
    args = ap.parse_args()

    with open(args.config) as f:
        cfg = yaml.safe_load(f)
    if args.base_url:
        cfg["base_url"] = args.base_url

    clusters = load_fixtures(cfg["fixtures"])
    if not clusters:
        sys.exit(f"No fixtures found under {cfg['fixtures']}")

    rule(f"ACTOR–CRITIC DEMO  ·  {cfg['species']} {cfg['tissue']}")
    list_clusters(clusters)
    if args.list:
        return

    cluster = choose_cluster(clusters, args.pick)
    backend = choose_backend(cfg, args.backend, args.model)

    # --- show the inputs -------------------------------------------------------
    rule(f"INPUT  ·  cluster {bold(cluster['cluster_id'])}  ·  "
         f"backend {bold(backend)} ({cfg['model']})")
    print(f"  Species / tissue  : {cfg['species']} {cfg['tissue']}")
    print(f"  Candidate labels  : {cfg['label_vocabulary']}")
    nb = cluster.get("neighbors") or []
    if nb:
        print(f"  Spatial neighbours: {nb}")
    print(f"\n  {bold('Top differentially-expressed genes (highest first):')}")
    genes = cluster.get("top_genes", [])
    for i in range(0, len(genes), 5):
        print("    " + "  ".join(f"{g:<11}" for g in genes[i:i + 5]))

    # --- run the agent (verbose streams the ACTOR / CRITIC decisions live) ------
    rule("INTERNAL DECISIONS  (live)")
    print(dim("  legend:  🧠 = model reasoning    🔧 = tool call → result    "
              "=== PHASE ==="))
    _load_dotenv()
    client = make_client(cfg)
    kb = load_kb(cfg)
    pred, trace = predict(client, cluster, cfg, kb, verbose=True)

    # --- structured output -----------------------------------------------------
    gene_table(cluster, pred, trace)
    final_block(cluster, cfg, pred, trace)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(trace, f, indent=2, default=str)
    print(dim(f"\n  trace: {args.out}   ·   {trace.get('elapsed_s','?')}s   ·   "
              f"{trace.get('tool_calls','?')} tool calls"))


if __name__ == "__main__":
    main()
