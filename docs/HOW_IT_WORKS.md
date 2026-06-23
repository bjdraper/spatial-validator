# How it works

A walkthrough of the Literature-Guided Spatial Marker & Cell-Type Validator:
the pieces, what the agent calls, where it makes decisions, and how it's scored.

---

## 1. What the system does

**Input:** one cluster from a spatial-transcriptomics dataset — its ID and its
top differentially expressed (DE) marker genes.

**Output:** a structured, cited prediction of the cluster's tissue layer / cell
type, chosen from a fixed label set.

**Why it's evaluable:** we run it against the DLPFC (Maynard et al. 2021)
dataset, where every region is expert-annotated into one of 7 classes
(L1–L6, WM). The agent's prediction is compared to that label, so scoring is
objective.

The design principle throughout: the **agent logic is dataset-agnostic**, and
everything dataset-specific (labels, markers, adjacency, prompt) lives in
`configs/dlpfc.yaml` + `data/`. Swapping the config runs the same agent on a
different dataset.

---

## 2. The pieces and how data flows

```
configs/dlpfc.yaml ─┐   (model, label set, adjacency, prompt, paths)
data/kb/*.json ─────┤
data/fixtures/*.json ┤
                     ▼
        eval/run_eval.py  ── for each cluster ──►  agent/loop.py: predict()
                     │                                   │
                     │                          ┌────────┴─────────┐
                     │                          │  Claude API      │  (the only
                     │                          │  (claude-opus-4-8)│   network /
                     │                          └────────┬─────────┘   paid call)
                     │                                   │ tool calls
                     │                          agent/tools.py (read-only)
                     │                                   │
                     ▼                                   ▼
   score vs ground truth                    marker_lookup / search_literature /
   confusion.json, traces.json              adjacency_rules  → data/kb
```

| File | Role |
|---|---|
| `configs/dlpfc.yaml` | All dataset-specific knobs: pinned `model`, `label_vocabulary` (the 7 classes), `adjacency` rules, scoring `adjacent_partial_credit`, paths, and the `system_prompt`. |
| `data/kb/brain_markers.json` | The marker knowledge base — 68 entries: `gene → identities, direction, specificity, note, citation`. |
| `data/fixtures/dlpfc/*.json` | The test set: per layer, the top DE genes + the ground-truth label. |
| `agent/loop.py` | The bounded agent loop (`predict()`). |
| `agent/tools.py` | The three read-only tools + KB loader. |
| `agent/schema.py` | The structured-output contract. |
| `eval/run_eval.py` | Loops the fixtures, calls the agent, scores, writes results. |

---

## 3. The agent loop (`agent/loop.py → predict()`)

One cluster is processed in **two phases**.

### Phase A — evidence gathering (bounded tool loop)

1. Build the **system prompt** (from config, prompt-cached) and a **user
   message** containing: cluster ID, species/tissue, the candidate label set,
   and the cluster's top DE genes.
2. Call the Claude API with the three tools available, **adaptive thinking** on,
   and **effort = high**.
3. Inspect `stop_reason`:
   - `tool_use` → the model wants data. Execute every requested tool locally,
     append the results, loop back to step 2.
   - anything else → the model is done gathering; exit the loop.
4. Repeat until done **or** a hard cap trips (see §6).

### Phase B — commit to a structured answer

5. Append one final user turn ("output your final prediction as JSON"), drop the
   tools, and call the API again with **`output_config.format` = the prediction
   schema**. This forces a clean JSON object — no free text to parse.
6. Parse the JSON, attach the full step-by-step trace and elapsed time, and
   return `(prediction, trace)`.

Separating "gather evidence with tools" (Phase A) from "emit the contract"
(Phase B) is deliberate: tool turns produce `tool_use` blocks, not JSON, so we
only constrain the format on the final, tool-free turn.

---

## 4. What the agent can call (the tools — `agent/tools.py`)

All three are **read-only** (no side effects, so a run can never alter anything).
`marker_lookup` and `adjacency_rules` are local; `search_literature` reaches
PubMed (with a persistent cache — see §4a).

| Tool | Input | Returns | Purpose |
|---|---|---|---|
| `marker_lookup` | `gene` | KB entry: `identities` (labels it points to), `direction`, `specificity` (`high`/`medium`/`low`/`none`), `note`, `citation`; or `found: false` | The core call — turn a gene into evidence about which label it implies and how much to trust it. |
| `adjacency_rules` | `label` | which labels can be spatially adjacent to that one (from config) | Sanity-check spatial plausibility (cortical layers are an ordered stack). Empty for non-spatial tasks. |
| `search_literature` | `query` | ranked PubMed refs — title, journal, year, snippet, **PMID + DOI** | Corroborate a marker call, or reason about a gene missing from the KB. Live + cached (§4a). |

### 4a. Literature search — live PubMed + persistent cache (`agent/literature.py`)

`search_literature` queries PubMed via NCBI E-utilities (stdlib only) and caches
every result under `literature.cache_dir`. Configured per dataset:

- `source: pubmed` — live on a cache miss, then cached; `cache_only` — committed
  snapshot only (offline, reproducible); `none` — disabled.
- `as_of:` pins a PubMed date ceiling so "live" stays reproducible.
- A committed `data/litcache/` snapshot makes demo/benchmark runs fast + offline.
- Pre-warm a new dataset: `python data_prep/warm_litcache.py --config <cfg>`.
- **Citation grounding:** the loop records which PMIDs were actually retrieved;
  any PMID the model *cites* but never retrieved is flagged
  (`citation_grounded` on the prediction, `ungrounded_pmid_citations` in trace).

The model decides *which* genes to look up and *whether* to check adjacency —
those calls aren't scripted.

---

## 5. Decision points

Two kinds: **model decisions** (the agent's reasoning) and **control decisions**
(the harness enforcing bounds).

### Model decisions (inside the conversation)

| Decision | How it's driven |
|---|---|
| Which genes to look up | Model picks from the cluster's DE list; prompt tells it to look up every candidate marker. |
| **Weighing evidence by specificity** | The KB tags each gene `high`/`medium`/`low`/`none`. A `high` marker (e.g. `RORB→L4`, `MOBP→WM`) outweighs several `low` pan-neuronal ones (`SNAP25`, `NRGN`); `none` genes (`TUBA1B`, `SCGB2A2`) are flagged to ignore. |
| **Negative markers** | The prompt makes a gene that *should be absent* count against a candidate. WM markers carry an explicit note that their presence in a grey-matter candidate is a negative signal. Recorded in `negative_checks`. |
| **Spatial plausibility** | The model may call `adjacency_rules` to check a candidate against the ordered layer stack. |
| **Conflict resolution** | When genes point to different layers, the model reconciles using specificity + negative markers + adjacency, in its thinking. |
| **Ambiguity vs. commitment** | If evidence genuinely splits, it picks the best-supported label and lists the rest in `ambiguous_between` rather than guessing confidently — an honest "ambiguous(L2|L3)" is correct behaviour, not a failure. |

### Control decisions (in `predict()`)

| Decision | Mechanism |
|---|---|
| Continue or stop the loop | branch on `stop_reason` (`tool_use` → continue) |
| Stop runaway loops | `max_iters=4`, `max_tool_calls=12`, `timeout_s=90` (hard caps) |
| Enforce the output shape | final call constrained by `prediction_schema` |

---

## 6. Control & reproducibility

- **Hard caps** on iterations, tool calls, and wall-clock — the agent physically
  cannot loop forever or blow the 90 s budget.
- **Pinned model id** (`claude-opus-4-8`, in config) so results are reproducible.
- **Full trace per cluster** (every tool call, input, output, stop reason, final
  prediction) written to `runs/traces.json`.
- **Read-only tools** — no destructive actions possible.
- **Schema-validated output** — a non-conforming run fails loudly.
- Note: on Opus 4.8 you can't set `temperature`/`top_p` (removed), so you get
  *stable behaviour* via low-variance prompting + effort + caps, not
  bit-identical determinism.

---

## 7. The prediction contract (`agent/schema.py`)

The final JSON the agent must produce (label enum is injected from the config,
so the schema is dataset-agnostic):

| Field | Meaning |
|---|---|
| `predicted_label` | one label from the dataset's vocabulary (the graded answer) |
| `confidence` | `high` / `medium` / `low` |
| `supporting_genes` | genes that drove the call |
| `negative_checks` | negative-marker reasoning applied |
| `ambiguous_between` | other labels still in contention |
| `reasoning` | short rationale |
| `citations` | KB entries / literature relied on |

---

## 8. Evaluation criteria (`eval/run_eval.py`)

### Test set
Each fixture is built **layer-as-cluster**: every expert-annotated layer in a
section becomes one test case, labelled with its top-15 DE genes (technical
genes — mitochondrial, ribosomal, `MALAT1`/`NEAT1` — filtered out). Ground truth
is the layer label. Current set: **5 sections, 33 clusters**.

### Scoring rubric (`score()`)
Per cluster, compare `predicted_label` to `ground_truth`:

| Outcome | Score |
|---|---|
| Exact match | **1.0** |
| Adjacent layer (per the config's `adjacency`, e.g. L3↔L4) | **0.5** |
| Non-adjacent / grey-vs-WM error | **0.0** |

Adjacent partial credit reflects that L2-vs-L3 confusion is biologically minor
and even methods/experts disagree there.

### Reported metrics
- **Exact accuracy** — fraction scored 1.0.
- **Rubric score** — mean of the rubric above (gives partial credit).
- **Confusion matrix** (`runs/confusion.json`) — which true layer gets predicted
  as which; reveals systematic confusions (expect L2↔L3, L5↔L6).
- **Traces** (`runs/traces.json`) — full per-cluster reasoning for audit.

### Offline gate
`tests/test_offline.py` verifies the entire pipeline (tools, KB, schema, loop
wiring, scoring) **without an API key**, by mocking the client — a CI/onboarding
check that costs nothing.

---

## 9. Worked examples

**Easy — a WM cluster** (top genes `MOBP, MBP, PLP1, MAG, CNP`): every gene is a
`high`-specificity WM marker. `marker_lookup` returns `WM` for each, no
grey-matter signal, no negative-marker violations → `predicted_label: WM`,
`confidence: high`.

**Hard — an L4 cluster in 151673** (top genes `NEFM, NEFL, TUBA1B, MBP, SNAP25`):
- `NEFM`/`NEFL` → `low`-specificity neurofilaments spanning L3–L5 (don't pin L4).
- `TUBA1B` → `none` (ignored).
- `MBP` → `WM` marker — a *negative* signal for any grey-matter call, but here
  it's mild WM bleed-through.
- `SNAP25` → pan-neuronal (confirms grey matter, not the layer).
- `RORB` (the canonical L4 marker) **isn't in the top genes** for this section.

So L4 must be inferred from "deep-ish projection-neuron signature + grey matter,
not WM" — a genuinely hard case, and exactly why L3↔L4↔L5 confusion is expected
and why the rubric gives adjacent layers partial credit.

---

## 10. Current state & known gaps

- ✅ Repo, fixtures (33 DLPFC + 8 MERFISH cases), KBs, eval, offline tests.
- ✅ **Provider-agnostic** model layer (`agent/providers.py`): Claude / OpenAI
  (Codex) / local Ollama — pick via `provider:` in the config or `--provider`.
- ✅ **Live PubMed literature search + persistent cache** (§4a). Verified
  end-to-end; cache snapshot committed.
- ✅ **CellMarker 2.0 marker DB option** (§4b) — `data_prep/build_kb.py` compiles
  CellMarker 2.0 into the KB schema; `marker_lookup` unchanged. Smoke-tested.
- **A/B (qwen2.5:14b, MERFISH, literature off):** hand-curated KB scored **8/8**;
  CellMarker KB passed a 1-cluster smoke test (full run not yet completed).
- **Hand-KB coverage ~88%** (DLPFC) / partial (MERFISH); CellMarker KB covers
  33/78 MERFISH fixture genes — gaps fall through to the live PubMed backstop.
- **`adjacency` is reasoning-only** in the layer-as-cluster setup: fixtures carry
  no populated neighbours, so `adjacency_rules` informs the model of the layer
  stack's structure but has no concrete neighbour labels to check against.
- **Negative markers** are still encoded as prose in KB notes, not as
  `direction: negative` entries (the schema supports them).

### 4b note — CellMarker 2.0 as marker DB (the redesign toward a general cell-type discriminator)

`data_prep/build_kb.py` turns CellMarker 2.0 into the same KB JSON schema
`marker_lookup` already reads (so no agent code changes), with: tissue filtering,
a fine→coarse cell-name collapse map (`data_prep/labelmaps/*.json`), a
**dominance filter** that drops minority-noise labels (e.g. `Gad1`'s stray
"Excitatory" record), and an **evidence-weighted specificity** proxy (`high`
needs one label + ≥3 supporting records). Tradeoff: far more coverage (2,153
genes vs 57 hand-curated) at the cost of noise — hence the filters.

## 11. Provenance

DLPFC data fetched via `spatialLIBD::fetch_data("spe")` (Maynard et al. 2021,
*Nat Neurosci*), manual annotations from `layer_guess_reordered_short`, per-layer
DE via `scran::findMarkers` (upregulated), built by `data_prep/fetch_dlpfc.R`.
Public, de-identified, post-mortem data.
