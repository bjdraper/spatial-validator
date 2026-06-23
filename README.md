# Evaluation datasets — download & cluster build

Code to download the two public spatial-transcriptomics datasets used to
evaluate the **Literature-Guided Spatial Marker & Cell-Type Validator** and turn
them into the per-cluster fixtures the agent is scored on.

A *cluster* = one expert-annotated group (a cortical layer, or a cell type)
represented by its top differentially-expressed marker genes plus its
ground-truth label. The scripts here fetch the raw data, compute per-cluster DE,
and write the fixtures to `data/fixtures/<dataset>/*.json`.

> **Data classification: PRIVATE.** The underlying datasets are public and
> de-identified (DLPFC is post-mortem human; MERFISH is mouse), but the built
> fixtures in this repo are treated as PRIVATE. Confirm the destination repo's
> visibility before sharing. No PHI/PII is present.

## What gets built

| Dataset | Source package | Clusters | Builder |
|---|---|---|---|
| Human DLPFC (10x Visium) | `spatialLIBD` (R/Bioconductor) | 33 (5 sections, layers L1–L6 + WM) | `data_prep/fetch_dlpfc.R` |
| Mouse hypothalamus (MERFISH) | `squidpy` (Python) | 8 cell types (1 region) | `data_prep/fetch_merfish.py` |

Full provenance, access routes, and citations: see [`DATASETS.md`](DATASETS.md).

## Quick start

### DLPFC (R / spatialLIBD — recommended)

```bash
Rscript data_prep/fetch_dlpfc.R
```

First run installs `spatialLIBD` + `scran` + `scuttle` from Bioconductor and
downloads the ~2 GB `SpatialExperiment` (cached by ExperimentHub afterwards).
Edit `SECTIONS` at the top of the script to pick which sections to build
(default: `151507, 151510, 151669, 151673, 151676` — spans all 3 donors).
Writes `data/fixtures/dlpfc/<section>.json`.

### MERFISH (Python / squidpy)

```bash
pip install -r requirements-data.txt   # plus: pip install squidpy
python data_prep/fetch_merfish.py
```

One call to `squidpy.datasets.merfish()` (cached locally), collapses the 16
fine-grained classes into 8 major cell types, drops control probes / Ambiguous.
Writes `data/fixtures/merfish/hypothalamus.json`.

### DLPFC alternative (Python / scanpy)

If you already have a labelled section as `.h5ad`:

```bash
pip install -r requirements-data.txt
python data_prep/build_fixtures.py \
    --h5ad data/raw/151673.h5ad --section 151673 --label-col layer
```

## Verifying your run

`data/fixtures/` ships with reference outputs already built from the sections
above. After running the scripts, your regenerated JSON should match these
(top-15 genes per cluster + ground-truth label). They're the contract the eval
loads — same shape regardless of which route built them:

```json
{
  "dataset": "...",
  "section_id": "...",
  "clusters": [
    {"cluster_id": "L1", "ground_truth": "L1", "top_genes": ["...", "..."], "neighbors": []}
  ]
}
```

## Requirements

- **DLPFC:** R (≥4.x) with Bioconductor — packages auto-install on first run.
- **MERFISH / scanpy route:** Python — `pip install -r requirements-data.txt`
  (scanpy/anndata/pandas/numpy); plus `squidpy` for the MERFISH fetch.
