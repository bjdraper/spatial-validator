# User Stories

Roles: **Analyst** = bioinformatician interpreting clusters.

## 1. Predict a cluster's identity from its markers  ⭐ MINIMALLY VIABLE
> As an Analyst, I input a cluster's top DE marker genes and receive a predicted
> tissue layer with supporting genes and citations, so I can skip manually
> cross-referencing markers against the literature.

This is the minimally viable story — it delivers the core value end to end
(input genes → cited prediction) and is what the 90-second demo shows.

## 2. Get an honest uncertainty flag, not a confident guess
> As an Analyst, when the markers genuinely conflict, the agent tells me it is
> ambiguous (e.g. `ambiguous_between: [L2, L3]`) with a confidence level, so I
> know which clusters to review by hand rather than trusting a forced answer.

## 3. Validate the agent against ground truth before I rely on it
> As an Analyst, I run the agent across a section of expert-annotated clusters
> and get an accuracy + rubric score and a confusion matrix, so I can trust its
> predictions (and see which layers it confuses) before using it on new data.

## 4. Resolve hard cases with reasoning, not just vote-counting
> As an Analyst, the agent uses negative markers and spatial adjacency to handle
> contaminated signatures (e.g. a deep layer heavy with white-matter myelin
> genes), so L6 is not naively miscalled as WM.

## 5. Reuse the agent on a different dataset
> As an Analyst, I point the tool at a new dataset config (labels, markers,
> fixtures) and run the same agent unchanged, so the validator generalizes
> beyond DLPFC without rewriting the logic.

Stories 1–3 are achievable in the ~2.5h build window; 4 is largely in place via
the KB + prompt; 5 is enabled by the config-driven design.
