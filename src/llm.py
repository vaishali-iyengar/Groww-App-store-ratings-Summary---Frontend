"""One structured-output call shared by theme labelling, assignment and the pulse writer.

Providers: "groq" (default, GROQ_API_KEY) and "anthropic" (ANTHROPIC_API_KEY). Every call returns
a dict that matches `schema`; the schemas set additionalProperties false and list every field as
required, which both providers' strict modes need.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict

PROVIDERS = {"groq": "GROQ_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}

# complete(system, prompt, schema, max_tokens) -> parsed JSON
Complete = Callable[[str, str, Dict[str, Any], int], Dict[str, Any]]


class LLMError(RuntimeError):
    pass


def _groq(model: str, effort: str) -> Complete:
    import groq

    client = groq.Groq(max_retries=6)  # backs off on 429s; the free tier allows few tokens per minute

    def complete(system: str, prompt: str, schema: Dict[str, Any], max_tokens: int) -> Dict[str, Any]:
        args = dict(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            max_completion_tokens=max_tokens,
            response_format={"type": "json_schema",
                             "json_schema": {"name": "result", "strict": True, "schema": schema}},
        )
        if model.startswith("openai/gpt-oss"):
            args.update(reasoning_effort=effort, include_reasoning=False)
        try:
            response = client.chat.completions.create(**args)
        except groq.BadRequestError as exc:
            if "response_format" not in str(exc) and "json_schema" not in str(exc):
                raise LLMError("Groq rejected the request: %s" % exc)
            # Model without strict schema support: ask for plain JSON and spell out the shape.
            args["response_format"] = {"type": "json_object"}
            args["messages"][0]["content"] = system + "\n\nReply with JSON only, matching this schema:\n" + json.dumps(schema)
            try:
                response = client.chat.completions.create(**args)
            except groq.APIError as exc2:
                raise LLMError("Groq call failed: %s" % exc2)
        except groq.APIError as exc:
            raise LLMError("Groq call failed: %s" % exc)
        choice = response.choices[0]
        if choice.finish_reason == "length":
            raise LLMError("Groq output hit max tokens")
        try:
            return json.loads(choice.message.content or "")
        except ValueError:
            raise LLMError("Groq returned invalid JSON")

    return complete


def _anthropic(model: str, effort: str) -> Complete:
    import anthropic

    client = anthropic.Anthropic()

    def complete(system: str, prompt: str, schema: Dict[str, Any], max_tokens: int) -> Dict[str, Any]:
        try:
            response = client.beta.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.APIError as exc:
            raise LLMError("Claude call failed: %s" % exc)
        if response.stop_reason in ("refusal", "max_tokens"):
            raise LLMError("Claude stopped early: %s" % response.stop_reason)
        return json.loads(next(b.text for b in response.content if b.type == "text"))

    return complete


def client(provider: str, model: str, effort: str = "low") -> Complete:
    if provider not in PROVIDERS:
        raise LLMError("llm_provider must be one of %s" % ", ".join(PROVIDERS))
    key = PROVIDERS[provider]
    if not os.environ.get(key):
        raise LLMError("%s is not set; export it or run with --no-llm" % key)
    return (_groq if provider == "groq" else _anthropic)(model, effort)
