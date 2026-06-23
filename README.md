# Literature-Guided Spatial Marker & Cell-Type Validator

An evaluable AI agent for the **interpretation** step of a spatial-RNASeq
workflow. Given a cluster's top differentially expressed marker genes, it
predicts the cell type / tissue layer — using a marker knowledge base, negative
markers, spatial adjacency, and literature — and emits a structured, cited
prediction that is scored against expert annotations.

## Why it's evaluable

Benchmarked on the **DLPFC (Maynard et al. 2021)** dataset: every spot is
expert-annotated into one of 7 classes (L1–L6, WM), so scoring is objective
(accuracy + confusion matrix). Runs per cluster in well under 90s, no model
training, public de-identified data only.

## Layout

```
agent/        dataset-AGNOSTIC core — never edited per dataset
  loop.py       bounded, auditable agent loop (caps + full trace)
  tools.py      marker_lookup, search_literature, adjacency_rules (read-only)
  schema.py     structured-output contract (label enum from config)
configs/      one YAML per dataset (model, labels, adjacency, KB, prompt)
data/
  kb/           marker knowledge base(s)
  fixtures/     per-cluster DE genes + ground-truth labels
eval/run_eval.py   loop the fixtures, score, write traces
data_prep/    offline: fetch dataset + build fixtures
```

Adding a dataset = a new `configs/*.yaml` + its KB and fixtures. No agent edits.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env      # add your ANTHROPIC_API_KEY
```

## Run

```bash
python eval/run_eval.py --config configs/dlpfc.yaml            # full
python eval/run_eval.py --config configs/dlpfc.yaml --limit 2  # quick smoke test
```

Ships with a small placeholder fixture so it runs immediately. Replace it with
real fixtures via `data_prep/` (see `data_prep/README.md`).

## Models / providers

The agent is provider-agnostic (`agent/providers.py` is the only vendor-aware
file). Pick a backend with `provider:` in the config, or override per-run:

```bash
# Claude (default)
python eval/run_eval.py --config configs/dlpfc.yaml

# Local model via Ollama — no API key, runs offline
python eval/run_eval.py --config configs/dlpfc.ollama.yaml --limit 2

# OpenAI / Codex (or any OpenAI-compatible endpoint)
python eval/run_eval.py --config configs/dlpfc.yaml \
    --provider openai --model gpt-4o     # set OPENAI_API_KEY in .env
```

`provider: openai` also accepts a `base_url:` for any OpenAI-compatible server.
Local models must support tool-calling to gather marker evidence (llama3.2 does;
pull a larger model like `qwen2.5:14b` for better accuracy).

## Control / reproducibility

- Hard caps on iterations, tool calls, and wall-clock time.
- Model id pinned in config; full per-cluster trace written to `runs/`.
- Tools are read-only; the prediction is schema-validated.
