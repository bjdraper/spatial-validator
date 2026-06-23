# Data preparation

The agent eats **fixtures** (`data/fixtures/<dataset>/*.json`): per-cluster top
DE genes + ground-truth labels. This folder builds them from the real dataset.

## DLPFC (Maynard et al. 2021)

Human dorsolateral prefrontal cortex, 10x Visium, 12 sections from 3 donors,
each spot manually annotated into one of 7 classes (L1–L6, WM).

### Primary route — R / spatialLIBD (recommended)

`spatialLIBD` ships the `SpatialExperiment` with the manual layer labels
attached, so one script fetches the data, computes per-layer DE, and writes
fixtures — no scanpy needed:

```bash
Rscript data_prep/fetch_dlpfc.R
```

First run installs `spatialLIBD` + `scran` + `scuttle` from Bioconductor and
downloads the ~2 GB object (cached afterwards). Edit `SECTIONS` at the top of
the script to choose which sections to build (default: 5 spanning the 3 donors).

### Alternative route — Python / scanpy

If you already have a labelled section as `.h5ad`:

```bash
pip install -r requirements-data.txt
python data_prep/build_fixtures.py --h5ad data/raw/151673.h5ad \
    --section 151673 --label-col layer
```

Pick ~5 sections spanning the 3 donors for the core eval set.
