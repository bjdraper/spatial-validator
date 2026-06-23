# One-Pager — Literature-Guided Spatial Marker & Cell-Type Validator

## Problem
In a spatial-RNASeq workflow, the slowest, most manual step is **downstream
interpretation**: going from a cluster's top differentially expressed (DE) genes
to "which tissue layer / cell type is this?" Bioinformaticians spend hours
cross-referencing marker genes against PubMed and reference atlases, resolving
conflicting signals by hand. We turn that into an agent.

## User
A*STAR bioinformaticians (the team itself) doing spatial-transcriptomics
analysis. At least one team member personally hits this interpretation
bottleneck on real work — it is our own pain point, not a hypothetical user's.

## Inputs & systems
- **Input:** one cluster's ID + its top DE marker genes (the output of the
  clustering step).
- **Knowledge:** a local, structured marker knowledge base (`data/kb/`) — genes
  → layer identities, specificity, direction, citation.
- **Reasoning:** a frontier model (Claude Opus 4.8) via the Claude API, driven
  by a bounded agent loop with three read-only tools (marker lookup, spatial
  adjacency, literature search).
- **Evaluation data:** 5 DLPFC sections (Maynard et al. 2021), 33 clusters,
  expert layer annotations — all on a personal laptop, public and de-identified.
- Everything runs from a laptop; the only external dependency is the model API.

## Demo scenario (≤90 seconds)
Feed the agent one cluster's top genes. Watch it call `marker_lookup` on each
gene, weigh them by specificity, apply negative-marker and adjacency reasoning,
and emit a cited, structured prediction of the layer. Show a case where this
**beats a naive marker-vote** (e.g. L3, where flat voting picks L2 but the agent
uses neurofilament co-expression to correctly call L3).

## Success criteria (one sentence)
**The agent's predicted layer matches the expert annotation** — measured as
exact accuracy (and a rubric score giving adjacent layers partial credit) across
the held-out DLPFC clusters, beating the naive specificity-vote baseline.

Result (Claude Opus 4.8 benchmark, all 33 clusters): **90.9% exact (30/33),
93.9% rubric.** The only errors are deep-layer-vs-white-matter confusions
(L6->WM x2 adjacent, L4->WM x1) from myelin-gene contamination at the cortex/WM
border; L1-L3, L5 and WM scored 100%. Naive specificity-vote baseline: 5/7 on
the demo section.

## Why it's not trivial RAG
The value is in the reasoning over retrieved evidence — specificity weighting,
negative markers, spatial adjacency, and conflict resolution — not in retrieving
a marker and echoing it. Verified by inspecting agent traces.
