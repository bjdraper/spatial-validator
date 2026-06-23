# Literature-Guided Spatial Marker & Cell-Type Validator

An evaluable AI agent for the **interpretation** step of a spatial-RNASeq
workflow. Given a cluster's top differentially expressed marker genes, it
predicts the cell type / tissue layer — using a marker knowledge base, negative
markers, spatial adjacency, and literature — and emits a structured, cited
prediction that is scored against expert annotations.

> **Data classification: PRIVATE.** The underlying datasets are public and
> de-identified (DLPFC is post-mortem human; MERFISH is mouse), but the built
> fixtures in this repo are treated as PRIVATE. Confirm the destination repo's
> visibility before sharing. No PHI/PII is present.

## Provider-agnostic — runs on Claude, Codex, or local Ollama models

The model layer is fully decoupled (`agent/providers.py` is the *only*
vendor-aware file). The same agent logic, KBs, prompts, and scoring run against
any of three backends — pick one with `provider:` in the config, or override
per run with `--provider`:

| Provider | `provider:` | Auth | Example |
|---|---|---|---|
| **Anthropic** (Claude) | `anthropic` | `ANTHROPIC_API_KEY` | `claude-sonnet-4-6`, `claude-opus-4-8` |
| **OpenAI / Codex** (or any OpenAI-compatible endpoint) | `openai` | `OPENAI_API_KEY` (+ optional `base_url`) | `gpt-4o` |
| **Ollama** (local, offline, no key) | `ollama` | none | `llama3.2`, `qwen2.5:14b` |

```bash
# Claude (default — configs/dlpfc.yaml sets provider: anthropic)
python eval/run_eval.py --config configs/dlpfc.yaml

# OpenAI / Codex
python eval/run_eval.py --config configs/dlpfc.yaml --provider openai --model gpt-4o

# Local model via Ollama — no API key, runs offline
python eval/run_eval.py --config configs/dlpfc.ollama.yaml --limit 2
```

`provider: openai` also accepts `base_url:` for any OpenAI-compatible server.
Local models must support **tool-calling** to gather marker evidence (llama3.2
does; pull a stronger model like `qwen2.5:14b` for better accuracy).

## Why it's evaluable

Benchmarked on the **DLPFC (Maynard et al. 2021)** dataset: every spot is
expert-annotated into one of 7 classes (L1–L6, WM), so scoring is objective
(accuracy + confusion matrix). Runs per cluster in well under 90s, no model
training, public de-identified data only. A second dataset (MERFISH mouse
hypothalamus) proves the design generalizes to a cell-type task with a different
label vocabulary — same agent code, new config + KB + fixtures.

## Layout

```
agent/        dataset-AGNOSTIC core — never edited per dataset
  loop.py       bounded, auditable agent loop (caps + full trace)
  providers.py  provider-agnostic model layer (anthropic | openai | ollama)
  tools.py      marker_lookup, search_literature, adjacency_rules (read-only)
  schema.py     structured-output contract (label enum from config)
configs/      one YAML per dataset+provider (model, labels, adjacency, KB, prompt)
data/
  kb/           marker knowledge base(s)
  fixtures/     per-cluster DE genes + ground-truth labels
eval/run_eval.py   loop the fixtures, score, write traces
data_prep/    offline: fetch dataset + build fixtures (see data_prep/README.md)
docs/         design notes, teaching guide, dataset provenance
```

Adding a dataset = a new `configs/*.yaml` + its KB and fixtures. No agent edits.

## Setup

```bash
pip install -r requirements.txt        # PyYAML + the provider SDK(s) you use
cp .env.example .env                    # add keys for the API providers you use
```

`requirements.txt` lists both `anthropic` and `openai` — install only what your
chosen provider needs. Ollama needs no Python key (just a running `ollama serve`).

## Datasets

Fixtures (the per-cluster "clusters") ship pre-built in `data/fixtures/`. To
regenerate them from the raw public datasets, see **[`data_prep/README.md`](data_prep/README.md)**;
full provenance and citations are in **[`DATASETS.md`](DATASETS.md)**.

## Control / reproducibility

- Hard caps on iterations, tool calls, and wall-clock time.
- Model id + provider pinned in config; full per-cluster trace written to `runs/`.
- Tools are read-only; the prediction is schema-validated.
- `--resume` reuses prior successful predictions and re-runs only errors.
