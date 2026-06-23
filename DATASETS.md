# Evaluation datasets & citations

Both datasets are **public, de-identified (or non-human), and downloadable to a
personal laptop**, with **expert ground-truth annotations** so the agent is
objectively scorable — satisfying the workshop's "real data" and "evaluable"
requirements with no PHI/PII.

---

## 1. Primary benchmark — Human DLPFC (10x Visium)

**What it is.** Transcriptome-scale spatial gene expression across the six-layered
human dorsolateral prefrontal cortex (DLPFC), 10x Genomics Visium. Every spot is
expert-annotated into one of **7 classes: L1–L6 + white matter (WM)**. The de
facto benchmark for spatial-domain detection.

**What we use.** 5 sections spanning all 3 donors — `151507, 151510, 151669,
151673, 151676` — built **layer-as-cluster** (each annotated layer → one test
case, labelled by its top-15 DE genes; technical genes filtered). **33 clusters
total** (151669 spans 5 layers, the others 7). Ground-truth column:
`layer_guess_reordered_short`.

**Access.** Fetched via the `spatialLIBD` Bioconductor package
(`fetch_data("spe")`), which ships the `SpatialExperiment` with layer labels
attached; per-layer DE via `scran::findMarkers`. Reproduce with
`data_prep/fetch_dlpfc.R`. Data: post-mortem, public, de-identified — **no PHI**.

**Citations.**
- Maynard KR, Collado-Torres L, Weber LM, et al. **Transcriptome-scale spatial
  gene expression in the human dorsolateral prefrontal cortex.** *Nature
  Neuroscience* 24, 425–436 (2021). doi:10.1038/s41593-020-00787-0 (PMID 33558695).
- Pardo B, Spangler A, Weber LM, et al. **spatialLIBD: an R/Bioconductor package
  to visualize spatially-resolved transcriptomics data.** *BMC Genomics* 23, 434
  (2022). doi:10.1186/s12864-022-08601-w  *(software used to obtain the data)*
- Data portal: http://research.libd.org/spatialLIBD

---

## 2. Generalization dataset — Mouse hypothalamus (MERFISH)

**What it is.** A molecularly annotated, spatially resolved single-cell atlas of
the mouse hypothalamic preoptic region by MERFISH (imaging-based, ~155-gene
targeted panel). Cells are annotated into classes (`Cell_class`).

**What we use.** Collapsed to **8 major cell types** — Excitatory, Inhibitory,
Astrocyte, Oligodendrocyte, Endothelial, Microglia, Ependymal, Pericytes (the 16
fine-grained classes merged; `Blank` control probes and `Ambiguous` dropped),
built **cell-type-as-cluster** with top-15 DE genes. Demonstrates the agent
generalizing to a **cell-type** task on a non-cortical tissue with a different
label vocabulary — same agent code, new config + KB + fixtures.

**Access.** Loaded via `squidpy.datasets.merfish()` (one call; cached locally).
Reproduce with `data_prep/fetch_merfish.py`. Mouse data — **no PHI**.

**Citations.**
- Moffitt JR, Bambah-Mukku D, Eichhorn SW, et al. **Molecular, spatial, and
  functional single-cell profiling of the hypothalamic preoptic region.**
  *Science* 362, eaau5324 (2018). doi:10.1126/science.aau5324 (PMC6482113).
- Palla G, Spitzer H, Klein M, et al. **Squidpy: a scalable framework for spatial
  omics analysis.** *Nature Methods* 19, 171–178 (2022).
  doi:10.1038/s41592-021-01358-2 (PMID 35102346)  *(software used to obtain the data)*

---

## 3. Marker knowledge-base reference sources

The marker KBs (`data/kb/*.json`) encode gene → layer/cell-type associations
drawn from canonical references. Entries cite these descriptively (not verbatim):

- Zeng H, Shen EH, Hohmann JG, et al. **Large-scale cellular-resolution gene
  profiling in human neocortex reveals species-specific molecular signatures.**
  *Cell* 149, 483–496 (2012). doi:10.1016/j.cell.2012.02.052  *(cortical layer markers)*
- **Allen Human Brain Atlas** — Allen Institute for Brain Science.
  https://portal.brain-map.org  *(layer/cell-type marker provenance)*
- Franzén O, Gan LM, Björkegren JLM. **PanglaoDB: a web server for exploration of
  mouse and human single-cell RNA sequencing data.** *Database* 2019, baz046.
  doi:10.1093/database/baz046  *(cell-type markers; KB expansion source)*
- Hu C, Li T, Xu Y, et al. **CellMarker 2.0: an updated database of manually
  curated cell markers.** *Nucleic Acids Research* 51, D870–D876 (2023).
  doi:10.1093/nar/gkac947  *(cell-type markers; KB expansion source)*
- Maynard et al. 2021 (above) — DLPFC layer-enriched gene tables.

> Note: the seed KBs are partial (DLPFC ~88%, MERFISH ~50% of recurring DE genes
> covered) and intended to be expanded from PanglaoDB / CellMarker as part of the
> work. Markers without well-established layer/type specificity are deliberately
> left unassigned rather than guessed.

---

## 4. Scoring & ground truth

| Dataset | Labels | Test cases | Ground truth | Scoring |
|---|---|---|---|---|
| DLPFC | L1–L6, WM (7) | 33 (5 sections) | Expert manual layer annotation (Maynard 2021) | exact + adjacent-layer rubric (0.5) |
| MERFISH | 8 cell types | 8 (1 region) | Author cell-class labels (Moffitt 2018), collapsed | exact (no adjacency) |

Success criterion (one sentence): *the agent's predicted layer/cell type matches
the expert annotation*, reported as exact accuracy + a confusion matrix, beating
a naive specificity-weighted marker vote.
