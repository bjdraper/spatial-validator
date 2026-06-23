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
  loop.py        bounded agent loop: gather evidence via tools, then a final
                 schema-constrained call. Hard caps (iters/tool-calls/90s),
                 full trace, citation grounding.
  providers.py   PROVIDER-AGNOSTIC model layer (the only vendor-aware file):
                 anthropic | openai (OpenAI/Codex) | ollama. Neutral message
                 format + one create() call; adapters translate per backend.
  literature.py  cache-first PubMed (NCBI E-utilities, stdlib only) behind
                 search_literature. Live on cache miss, then cached.
  tools.py       read-only tools: marker_lookup, search_literature, adjacency_rules
  schema.py      structured-output contract (label enum injected from config)
configs/         one YAML per dataset (+provider/KB variants)
data/kb/         marker knowledge bases (hand-curated AND CellMarker-compiled)
data/fixtures/   per-cluster DE genes + ground-truth labels
data/litcache/   committed PubMed cache snapshot (reproducible/offline demos)
eval/run_eval.py loop fixtures, score, write traces to runs/
data_prep/       offline builders (datasets, KBs, cache warming)
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

## Three subsystems added recently (see docs/HOW_IT_WORKS.md §4a/§4b/§10)

1. **Provider-agnostic** — `agent/providers.py`. Anthropic / OpenAI-compatible
   (Codex) / Ollama. Verified on Ollama (`llama3.2`, `qwen2.5:14b`).
2. **Live PubMed + persistent cache** (option B) — `agent/literature.py`,
   `literature:` config block, `data_prep/warm_litcache.py`. `source: cache_only`
   = fully offline/reproducible. Citation grounding flags ungrounded PMIDs.
3. **CellMarker 2.0 marker DB** (general cell-type discriminator redesign) —
   `data_prep/build_kb.py` compiles CellMarker 2.0 into the KB schema
   (tissue filter + fine→coarse label map in `data_prep/labelmaps/` + dominance
   filter + evidence-weighted specificity). `configs/merfish.cellmarker.yaml`.

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
- No agent-core edits to add a dataset — only config + KB + fixtures.
- The PubMed MCP is session-only; the deployed agent uses its own stdlib
  E-utilities client (`agent/literature.py`), not the MCP.

## Open follow-ups

- Finish the full 8-cluster CellMarker vs hand-KB A/B (and optionally a Claude run).
- Populate negative markers as `direction: negative` (currently prose in notes).
- Optionally add PanglaoDB (has a real specificity column) alongside CellMarker.
