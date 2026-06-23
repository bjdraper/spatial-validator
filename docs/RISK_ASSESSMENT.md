# Risk Assessment — Workshop Criteria Compliance

## Compliance with the disqualifying criteria

| Criterion | Status | Evidence / mitigation |
|---|---|---|
| Data/systems inaccessible from a personal laptop | ✅ Clear | All data (DLPFC fixtures, marker KB) is local; only external call is the model API. |
| Touches PHI / PII / financial / credentials | ✅ Clear | DLPFC is public, de-identified, post-mortem brain data — no PHI/PII. No financial/credential data. |
| Output reaches an external party without human review | ✅ Clear | Internal tool; predictions are reviewed by the analyst. No external delivery. |
| Requires training / fine-tuning a model | ✅ Clear | Frontier model + prompting + tool use only. No fine-tuning. |
| Platform-building | ✅ Clear | A single focused validator, not a framework/platform. |
| Autonomous changes on external systems | ✅ Clear | Tools are read-only; no writes, no external actions. |
| Trivial RAG over a document pile | ✅ Clear | Reasoning layer (specificity weighting, negative markers, adjacency, conflict resolution) makes it multi-step agentic, not retrieve-and-echo. Verified in traces (e.g. L3 via neurofilament co-expression). |

## Must-have requirements

| Requirement | Status |
|---|---|
| Bounded (~2.5h, 2 engineers) | ✅ Core build fits; data download + KB curation are pre-workshop prep. |
| Real user present | ✅ The team has this bottleneck. |
| Real data, 5+ examples on a laptop | ✅ 5 sections / 33 clusters local. |
| Internal-facing only | ✅ |
| Evaluable in one sentence | ✅ "Predicted layer matches expert annotation." |
| Agentic | ✅ Tool use + retrieval + multi-step reasoning + self-critique. |

## Operational risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| **No model credits on workshop day** (we hit a billing 400) | Medium | Confirm each participant's frontier-model account has working credits *and* is logged in before the workshop — this is an explicit workshop rule. |
| API key leakage | Medium | Keys live in a gitignored `.env`, never committed, never pasted in shared channels. Rotate any exposed key immediately. |
| KB coverage gaps (~88% of recurring genes) | Medium | Expand KB from PanglaoDB/CellMarker; `eval/preview.py` shows coverage offline before spending tokens. |
| Latency exceeds the demo budget | Low | ~44s/cluster observed, within the 90s window; caps bound worst case (`max_iters`, `max_tool_calls`, `timeout_s`). |
| Non-reproducible results | Low | Model id pinned in config; full per-cluster traces written to `runs/`. |
| Over-claiming accuracy | Low | Honest scoring vs expert labels + confusion matrix; ambiguity flagged rather than forced. |

## Residual concerns
- `search_literature` corpus is empty (citations come from the KB for now) —
  not a compliance issue, a completeness gap.
- Generalization to non-cortical tissue is config-dependent and untested until a
  second dataset is added.
