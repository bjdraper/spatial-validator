"""Provider-agnostic model layer.

The agent loop speaks a single neutral message format and a single `create()`
call; each provider here translates that to/from one backend's wire format.
This is the *only* file that knows a vendor SDK exists.

Supported providers (set `provider:` in the dataset config):
  * anthropic            — Claude via the Anthropic SDK (default)
  * openai               — OpenAI / Codex, or any OpenAI-compatible endpoint
  * ollama               — local models via Ollama's OpenAI-compatible API

`openai` and `ollama` share one adapter because Ollama exposes an
OpenAI-compatible `/v1` surface; they differ only in default base_url/key.

Neutral message format (what the loop builds and passes around):
  {"role": "user",         "content": "<text>"}
  {"role": "assistant",    "text": "<text>", "tool_calls": [{"id","name","input"}]}
  {"role": "tool_results", "results": [{"id","name","output": <dict>}]}

Neutral tools are the Anthropic-style dicts already defined in tools.TOOLS
(name / description / input_schema); the OpenAI adapter converts them.
"""
import json
import os


class Response:
    """Normalized model response the loop consumes, regardless of provider."""

    def __init__(self, text, tool_calls, stop_reason):
        self.text = text or ""
        self.tool_calls = tool_calls or []  # [{"id","name","input": dict}]
        self.stop_reason = stop_reason       # "tool_use" => the loop runs tools

    @property
    def wants_tools(self):
        return self.stop_reason == "tool_use"


def make_client(cfg):
    """Build the provider client named by `cfg['provider']` (default anthropic)."""
    provider = (cfg.get("provider") or "anthropic").lower()
    if provider == "anthropic":
        return AnthropicProvider(cfg)
    if provider in ("openai", "openai-compatible", "ollama"):
        return OpenAIProvider(cfg)
    raise ValueError(
        f"unknown provider {provider!r}; use anthropic | openai | ollama"
    )


def _extract_json(text):
    """Parse a JSON object from model text, tolerating reasoning-model noise.

    Local reasoning models (e.g. deepseek-r1) may wrap output in <think>…</think>
    or prose. Try a clean parse first, then strip think-blocks and grab the
    outermost {...}. Schema-constrained providers won't need the fallback.
    """
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass
    if "</think>" in text:
        text = text.split("</think>", 1)[1]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError(f"no JSON object in model output: {text[:200]!r}")


# --------------------------------------------------------------------------- #
# Anthropic                                                                    #
# --------------------------------------------------------------------------- #
class AnthropicProvider:
    def __init__(self, cfg):
        import anthropic  # imported lazily so OpenAI-only users needn't install it

        self.cfg = cfg
        self.client = anthropic.Anthropic(max_retries=6)  # ride out 429/5xx/529

    def _gen_params(self):
        # thinking / effort are omitted when unset, so models that don't support
        # them (e.g. Haiku 4.5) work by leaving them null in the YAML.
        params = {}
        if self.cfg.get("thinking"):
            params["thinking"] = {"type": self.cfg["thinking"]}
        if self.cfg.get("effort"):
            params["output_config"] = {"effort": self.cfg["effort"]}
        return params

    @staticmethod
    def _to_wire(messages):
        wire = []
        for m in messages:
            role = m["role"]
            if role == "user":
                wire.append({"role": "user", "content": m["content"]})
            elif role == "assistant":
                blocks = []
                if m.get("text"):
                    blocks.append({"type": "text", "text": m["text"]})
                for tc in m.get("tool_calls", []):
                    blocks.append(
                        {"type": "tool_use", "id": tc["id"],
                         "name": tc["name"], "input": tc["input"]}
                    )
                wire.append({"role": "assistant", "content": blocks})
            elif role == "tool_results":
                wire.append({
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": r["id"],
                         "content": json.dumps(r["output"])}
                        for r in m["results"]
                    ],
                })
        return wire

    def create(self, *, system, messages, tools=None, json_schema=None, max_tokens=4000):
        sys_blocks = [{
            "type": "text", "text": system,
            "cache_control": {"type": "ephemeral"},  # cached across all clusters
        }]
        kwargs = dict(
            model=self.cfg["model"], max_tokens=max_tokens,
            system=sys_blocks, messages=self._to_wire(messages),
        )
        params = self._gen_params()
        if tools:
            kwargs["tools"] = tools  # already Anthropic-shaped
        if json_schema:
            oc = params.pop("output_config", {})
            oc["format"] = {"type": "json_schema", "schema": json_schema}
            kwargs["output_config"] = oc
        kwargs.update(params)
        resp = self.client.messages.create(**kwargs)
        text = "".join(b.text for b in resp.content if b.type == "text")
        tool_calls = [
            {"id": b.id, "name": b.name, "input": b.input}
            for b in resp.content if b.type == "tool_use"
        ]
        return Response(text, tool_calls, resp.stop_reason)


# --------------------------------------------------------------------------- #
# OpenAI / Codex / Ollama (OpenAI-compatible)                                  #
# --------------------------------------------------------------------------- #
def _to_openai_tools(tools):
    """Anthropic tool dicts -> OpenAI function-tool dicts."""
    return [
        {"type": "function", "function": {
            "name": t["name"], "description": t["description"],
            "parameters": t["input_schema"],
        }}
        for t in tools
    ]


class OpenAIProvider:
    def __init__(self, cfg):
        from openai import OpenAI  # lazy: only needed for OpenAI/Ollama configs

        self.cfg = cfg
        provider = (cfg.get("provider") or "openai").lower()
        is_ollama = provider == "ollama"

        base_url = cfg.get("base_url")
        if is_ollama and not base_url:
            base_url = "http://localhost:11434/v1"

        key_env = cfg.get("api_key_env") or (
            "OLLAMA_API_KEY" if is_ollama else "OPENAI_API_KEY"
        )
        # Ollama ignores the key but the SDK requires a non-empty string.
        api_key = os.environ.get(key_env) or ("ollama" if is_ollama else None)
        if not api_key:
            raise RuntimeError(
                f"no API key: set {key_env} in your environment / .env"
            )
        self.client = OpenAI(base_url=base_url, api_key=api_key, max_retries=6)

    @staticmethod
    def _to_wire(messages):
        wire = []
        for m in messages:
            role = m["role"]
            if role == "user":
                wire.append({"role": "user", "content": m["content"]})
            elif role == "assistant":
                msg = {"role": "assistant", "content": m.get("text") or ""}
                if m.get("tool_calls"):
                    msg["tool_calls"] = [
                        {"id": tc["id"], "type": "function",
                         "function": {"name": tc["name"],
                                      "arguments": json.dumps(tc["input"])}}
                        for tc in m["tool_calls"]
                    ]
                wire.append(msg)
            elif role == "tool_results":
                # OpenAI expects one message per tool result.
                for r in m["results"]:
                    wire.append({
                        "role": "tool", "tool_call_id": r["id"],
                        "content": json.dumps(r["output"]),
                    })
        return wire

    def create(self, *, system, messages, tools=None, json_schema=None, max_tokens=4000):
        wire = [{"role": "system", "content": system}]
        wire.extend(self._to_wire(messages))
        kwargs = dict(model=self.cfg["model"], messages=wire, max_tokens=max_tokens)
        if self.cfg.get("temperature") is not None:
            kwargs["temperature"] = self.cfg["temperature"]
        if tools:
            kwargs["tools"] = _to_openai_tools(tools)
            kwargs["tool_choice"] = "auto"
        if json_schema:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "prediction", "schema": json_schema,
                                "strict": True},
            }
        resp = self.client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        tool_calls = []
        for tc in (msg.tool_calls or []):
            try:
                args = json.loads(tc.function.arguments or "{}")
            except ValueError:
                args = {}
            tool_calls.append({"id": tc.id, "name": tc.function.name, "input": args})
        finish = resp.choices[0].finish_reason
        stop_reason = "tool_use" if (tool_calls or finish == "tool_calls") else finish
        return Response(msg.content, tool_calls, stop_reason)
