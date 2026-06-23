# CLAUDE.md — Literature-Guided Spatial Marker & Cell-Type Validator

Guidance for future Claude Code sessions on this project.

> ⚠️ **Data classification: PRIVATE.** Built fixtures, KBs, and cache outputs are
> treated as PRIVATE even though the source datasets are public/de-identified
> (DLPFC = post-mortem human; MERFISH = mouse). Confirm a GitHub destination repo
> is private/internal before pushing. No PHI/PII is present.

## What this is

An **evaluable AI agent** for the interpretation step of spatial-RNAseq: given a
cluster's top differentially-expressed marker genes, it predicts the cell type /
tissue layer, citing evidence, and is scored against expert annotations
(accuracy + confusion matrix). The agent core is **dataset-agnostic**; everything
dataset-specific lives in `configs/*.yaml` + its KB and fixtures.

## Architecture (the agent core never changes per dataset)

```
agent/
  loop.py        bounded ACTOR→CRITIC→RESOLUTION loop: Actor commits to one
                 hypothesis, Critic aggressively tries to disprove it (disproof
                 step structurally enforced), Resolution emits schema JSON
                 (retry-once then graceful fallback). Lean caps (≤2 iters/phase,
                 80 tool calls, 90s), phase-tagged trace, citation grounding.
                 Tools are restricted per phase.
  prompts.py     centralized ACTOR_CRITIC_TEMPLATE; configs inherit it via
                 system_prompt: null (a config string still overrides).
  providers.py   PROVIDER-AGNOSTIC model layer (the only vendor-aware file):
                 anthropic | openai (OpenAI/Codex) | ollama. Neutral message
                 format + one create() call; adapters translate per backend.
  literature.py  cache-first PubMed (NCBI E-utilities, stdlib only) behind
                 search_literature. Live on cache miss, then cached.
  cellmarker.py  CellMarker 2.0 SQLite promiscuity/confounder oracle behind
                 confounder_lookup (Critic). Read-only, stdlib sqlite3.
  uniprot.py     cache-first UniProt REST (function/localization, stdlib only)
                 behind uniprot_lookup (Critic). Live on cache miss, then cached.
  tools.py       read-only tools: marker_lookup, search_literature,
                 adjacency_rules, confounder_lookup, uniprot_lookup
  schema.py      structured-output contract (label enum injected from config;
                 incl. initial_hypothesis, vulnerability_score,
                 gene_classification, detected_panels)
configs/         one YAML per dataset (+provider/KB variants)
data/kb/         marker KBs (hand-curated AND CellMarker-compiled JSON) +
                 cellmarker.db (CellMarker 2.0 SQLite confounder index; PRIVATE,
                 gitignored, built by data_prep/build_cellmarker_db.py)
data/fixtures/   per-cluster DE genes + ground-truth labels
data/litcache/   committed PubMed cache snapshot (reproducible/offline demos)
data/uniprotcache/  UniProt annotation cache (gitignored unless frozen)
eval/run_eval.py loop fixtures, score, write traces to runs/
data_prep/       offline builders (datasets, KBs, SQLite index, cache warming)
docs/            HOW_IT_WORKS.md (deep dive), DATASETS.md (provenance), etc.
spatial-validator/   the prepared GitHub push folder (git-initialized)
```

## How to run

```bash
pip install -r requirements.txt            # PyYAML + provider SDK(s)
cp .env.example .env                        # keys for API providers (Ollama needs none)

# Claude (default)
python eval/run_eval.py --config configs/dlpfc.yaml [--limit N]
# OpenAI / Codex
python eval/run_eval.py --config configs/dlpfc.yaml --provider openai --model gpt-4o
# Local Ollama (offline, free)
python eval/run_eval.py --config configs/dlpfc.ollama.yaml --limit 2
```

`--provider` / `--model` / `--base-url` override the config. `--resume` reuses
prior successful predictions.

## Subsystems (see docs/HOW_IT_WORKS.md §4a/§4b/§10)

1. **Provider-agnostic** — `agent/providers.py`. Anthropic / OpenAI-compatible
   (Codex) / Ollama. Verified on Ollama (`llama3.2`, `qwen2.5:14b`).
2. **Live PubMed + persistent cache** (option B) — `agent/literature.py`,
   `literature:` config block, `data_prep/warm_litcache.py`. `source: cache_only`
   = fully offline/reproducible. Citation grounding flags ungrounded PMIDs.
3. **CellMarker 2.0 marker DB** (general cell-type discriminator redesign) —
   `data_prep/build_kb.py` compiles CellMarker 2.0 into the KB schema
   (tissue filter + fine→coarse label map in `data_prep/labelmaps/` + dominance
   filter + evidence-weighted specificity). `configs/merfish.cellmarker.yaml`.
4. **Actor–Critic framework** — `agent/loop.py` + `agent/prompts.py`. The agent
   forms ONE hypothesis (ACTOR: `marker_lookup`/`confounder_lookup`/`adjacency_rules`),
   then aggressively tries to disprove it (CRITIC: adds `uniprot_lookup` +
   `search_literature`), then RESOLUTION emits schema JSON. Tools are restricted
   per phase so disproof evidence belongs to the Critic; if the Critic runs no
   disproof tool, one nudge is forced (`trace.critic_disproof_*`). New tools:
   - `confounder_lookup` (`agent/cellmarker.py`) — CellMarker 2.0 **SQLite** index
     (`data_prep/build_cellmarker_db.py` → `data/kb/cellmarker.db`, fine-grained /
     all-tissue on purpose); returns how many cell types share a gene →
     promiscuity/specificity verdict (shared-marker & housekeeping signal).
   - `uniprot_lookup` (`agent/uniprot.py`) — UniProt REST function + subcellular
     localization, cached like literature; `uniprot:` config block.
   Critic discriminations surface as schema fields: `gene_classification`
   (housekeeping vs biomarker + `pertains_to`), `detected_panels`,
   `vulnerability_score`. Verified end-to-end: Claude Sonnet (no-thinking /
   effort=medium) on MERFISH Excitatory → correct, ~65s cached / ~100s cold
   (cold = first-run live UniProt). Tuned lean (≤2 iters/phase, 80-call budget,
   90s) after a budget-thrash bug starved the Critic and blanked the final JSON;
   resolution now retries once then falls back. A `demo/demo_run.py` walkthrough
   lists clusters, shows genes, streams the phases, and prints the breakdown +
   eval check.

## Key facts / decisions

- **Models available locally (Ollama):** `llama3.2` (weak tool use),
  `qwen2.5:14b` (recommended local; ~9GB fits 24GB M4 Pro). Use latest Claude
  models for API runs (Opus 4.8 / Sonnet 4.6).
- **A/B so far** (qwen2.5:14b, MERFISH, literature off to isolate the KB):
  hand-curated KB = **8/8**; CellMarker KB = 1-cluster smoke test passed (full
  run pending).
- **CellMarker download mirror** (works): `http://117.50.127.228/CellMarker/...`.
  NCBI E-utilities reachable; `NCBI_API_KEY` optional (raises 3→10 req/s).
- **Cluster-as-celltype fixtures**: a fixture's cluster_id often equals its
  ground-truth label, so eval prints read `pred=X truth=X` — the agent only sees
  genes, never the label; it's a genuine independent prediction.

## Conventions

- Scratch/temp files → the session scratchpad, never the repo.
- `.env` is gitignored; never commit keys. `data/raw/`, `runs/`, `*.h5ad`, logs
  are gitignored. `data/litcache/` IS committed (the demo snapshot).
- No agent-core edits to add a dataset — only config + KB + fixtures. (The
  Actor–Critic prompt is centralized; configs inherit it via `system_prompt: null`.)
- The PubMed MCP is session-only; the deployed agent uses its own stdlib
  E-utilities client (`agent/literature.py`), not the MCP. Same for UniProt
  (`agent/uniprot.py`) — stdlib `urllib`, no SDK.
- New tools degrade gracefully (missing `.db` / offline cache → `found: false`),
  matching the never-raise tool contract.

## Open follow-ups

- Finish the full 8-cluster CellMarker vs hand-KB A/B (and optionally a Claude run).
- Populate negative markers as `direction: negative` (currently prose in notes);
  the Critic also infers negatives from `confounder_lookup` promiscuity now.
- Optionally add PanglaoDB (has a real specificity column) alongside CellMarker.
- `cellmarker.db` is built from the **mouse** CellMarker file; DLPFC (human) hits it
  case-insensitively (symbols largely overlap) but a human DB would improve coverage.
- Tune Actor–Critic caps (per-phase iters / 120s) and re-run the MERFISH A/B under
  the new loop; consider committing a `data/uniprotcache/` snapshot for offline demos.
