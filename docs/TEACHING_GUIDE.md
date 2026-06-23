# Teaching guide — building the agent from fundamentals

For Jose (or anyone new): the concepts first, then the exact build order, then
how to make it cheaper and how it could run on open-source models.

---

## Part 1 — The fundamentals

### What makes this an "agent" (not a script)
A plain LLM call is one-shot: prompt in, text out. An **agent** runs a *loop*
where the model can **call tools**, read the results, and decide what to do next
— until it's satisfied. We give the model genes; it decides which to look up,
gathers evidence, reasons, and commits to an answer.

The five concepts you need:

1. **The agentic loop.** Call the model → if it asks to use a tool, run the tool
   and feed the result back → repeat → stop when it's done or a cap trips. The
   model drives; our code executes and bounds.

2. **Tool use.** A *tool* is a function we expose to the model with a name,
   description, and input schema. The model emits a "tool_use" request; we run
   the function locally and return a "tool_result". Our three tools are
   read-only KB lookups — `marker_lookup`, `adjacency_rules`, `search_literature`.

3. **Retrieval vs. reasoning (why this isn't "trivial RAG").** Retrieval =
   fetching facts (our KB lookups). The *value* is what the model does with them:
   weighing markers by specificity, using negative markers, checking spatial
   adjacency, resolving conflicts. Retrieval feeds reasoning; reasoning is the
   product.

4. **Structured output.** The final answer must match a fixed JSON schema
   (`predicted_label`, `confidence`, `supporting_genes`, …). This turns a fuzzy
   text answer into a contract a grader can score mechanically.

5. **Evaluation.** An agent you can't measure is a demo, not a tool. We score
   predictions against expert annotations (exact + an adjacent-layer rubric),
   produce a confusion matrix, and keep a full trace of every decision.

### The control mindset
A good agent is *bounded and auditable*: hard caps (iterations, tool calls,
wall-clock), a pinned model id, read-only tools (no destructive actions), and a
trace of every step. Control = reusability + reproducibility.

---

## Part 2 — How our agent maps to the concepts

| Concept | Where it lives |
|---|---|
| Agentic loop | `agent/loop.py → predict()` (Phase A: gather; Phase B: commit) |
| Tools | `agent/tools.py` (the 3 read-only tools + dispatch) |
| Knowledge base | `data/kb/brain_markers.json` (gene → identities, specificity, …) |
| Structured output | `agent/schema.py` (label enum injected from config) |
| Evaluation | `eval/run_eval.py` (loop fixtures, score, confusion, traces) |
| Config (dataset-specific) | `configs/dlpfc.yaml` |
| Offline check (no key) | `tests/test_offline.py` |
| Evidence inspector (no key) | `eval/preview.py` |

Read `docs/HOW_IT_WORKS.md` for the deep dive; this guide is the teaching path.

---

## Part 3 — The build, step by step (the ~2.5h workshop)

**Step 0 — Pre-workshop (done already).** Download the data, build fixtures,
seed the KB. This is prep, not workshop time — the rules assume "real data
available on the day."
- Verify: `ls data/fixtures/dlpfc/` shows real sections.

**Step 1 — Config + schema (15 min).** Define the dataset in `configs/*.yaml`
(model, label vocabulary, adjacency, prompt). Write `schema.py` to build the
prediction JSON schema from the label list.
- Verify: `prediction_schema(labels)` returns a schema whose enum = your labels.

**Step 2 — Tools (30 min).** Implement the read-only KB lookups in `tools.py`
and a `dispatch()` that routes a tool name to its function. Keep them pure.
- Verify: `dispatch("marker_lookup", {"gene": "RORB"}, cfg, kb)` returns L4.

**Step 3 — The loop (45 min).** Write `predict()`: build the system + user
messages, call the model with tools, branch on `stop_reason`, execute tools,
loop with caps; then a final tool-free call with structured output.
- Verify: mock the client and confirm it tool-calls then returns valid JSON
  (`tests/test_offline.py`).

**Step 4 — Eval + scoring (30 min).** `run_eval.py`: load fixtures, run
`predict` per cluster, score (exact / adjacent / miss), write confusion + traces.
- Verify: scoring unit checks (exact=1.0, adjacent=0.5, miss=0.0).

**Step 5 — Offline gate (10 min).** `tests/test_offline.py` exercises the whole
pipeline with a mocked client — no key, no cost. Run it before spending a token.

**Step 6 — Run + iterate (remaining time).** Add credits, set the key in `.env`,
run a `--limit 3` smoke test, then the full run. Read `runs/confusion.json`,
find the confused layers (expect L2↔L3, L5↔L6, L6↔WM), and sharpen the KB/prompt.
Use `eval/preview.py` (free) to check whether a KB edit helps before re-running.

**The golden rule:** every step has a *no-cost verification*. You never need the
model to know your wiring is right.

---

## Part 4 — Models & cost

The agent calls a frontier model per cluster. Prices (per million tokens):

| Model | Input / Output | Relative cost | Supports thinking/effort? | Use when |
|---|---|---|---|---|
| `claude-opus-4-8` | $5 / $25 | 1.0× (baseline) | yes | hardest reasoning, final results |
| `claude-sonnet-4-6` | $3 / $15 | ~0.6× | yes | **the sweet spot** — most of the build |
| `claude-haiku-4-5` | $1 / $5 | ~0.2× | **no** (set both to null) | cheapest, smoke tests, easy layers |

**How to switch:** edit `configs/dlpfc.yaml` — change `model`, and set
`thinking`/`effort` to `null` for Haiku (the loop omits them automatically; on
Haiku they'd otherwise error). No code change.

**Cost levers, in order of impact:**
1. **Prompt caching** (already on) — the system prompt + KB are cached, so the
   large stable prefix bills at ~0.1× after the first call. Biggest single win.
2. **Cheaper model** — Sonnet for iteration, Opus only for final numbers.
3. **Lower `effort`** — `medium` cuts thinking tokens on Opus/Sonnet.
4. **Fewer tool round-trips** — caps already bound this.

Rough order of magnitude for a full 33-cluster run: a few dollars on Opus,
~half on Sonnet, ~a fifth on Haiku — and caching pulls the input portion down
further. Develop on Sonnet/Haiku; run the final benchmark on Opus.

---

## Part 5 — Could it run on open-source models?

Yes, with one new piece — and a caveat.

**Caveat first (workshop):** the workshop requires *frontier* models (no
fine-tuning; each participant has a frontier-model subscription). So for the
submission, use Sonnet/Haiku. Open-source is a **post-workshop** path for cost
and independence.

**Why it's mostly a drop-in:** the loop, tools, KB, schema, and eval are
**model-agnostic**. Only the *client* — how we send messages and receive
tool calls — is Anthropic-specific. Open-source models don't speak the Anthropic
API, so you add a thin adapter.

**The path:**
1. Serve the OSS model behind an **OpenAI-compatible endpoint** — `ollama`,
   `vLLM`, `LM Studio`, or `text-generation-inference` all expose
   `/v1/chat/completions` with tool-calling.
2. Add a small **provider interface**: one function that takes `(messages,
   tools)` and returns `{text, tool_calls, stop_reason}`. Write an Anthropic
   implementation (what we have) and an OpenAI-compatible one (using the
   `openai` client pointed at `http://localhost:...`). `predict()` calls the
   interface instead of `client.messages.create` directly. ~50–80 lines.

**Two gaps the adapter must bridge:**
- **Tool-call format.** Anthropic uses `tool_use`/`tool_result` content blocks;
  OpenAI-compatible uses a `tools` param + `tool_calls` in the message. Translate
  between them.
- **Structured output.** Anthropic uses `output_config.format`; OpenAI-compatible
  uses `response_format={"type":"json_schema",...}`; vLLM/Ollama also support
  grammar/JSON-constrained decoding. The main risk is that smaller OSS models are
  weaker at reliable tool-calling and schema adherence — test on the easy layers
  (WM/L1) first.

**Bottom line:** the architecture already isolates the model behind one call
site, so going open-source is "add a provider adapter," not "rewrite the agent."
That isolation is itself a teaching point — keep model-specific code in one place.
