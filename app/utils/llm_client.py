from __future__ import annotations

import inspect
import json
import os
import re
import time
from typing import Any, Optional


def _normalize_provider(provider: Optional[str]) -> str:
    resolved = (provider or os.getenv("LLM_PROVIDER", "gemini")).strip().lower()
    if resolved not in {"gemini", "openai", "anthropic"}:
        return "gemini"
    return resolved


def _resolve_api_key(provider: str, api_key: Optional[str]) -> str:
    if api_key and api_key.strip():
        return api_key.strip()

    env_key_map = {
        "gemini": "GEMINI_API_KEY",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
    }
    return os.getenv(env_key_map[provider], "").strip()


def _extract_json_object(text: str) -> dict:
    if not text:
        return {}
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
    raw = raw.strip()
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        pass

    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


# Provider-side conditions that clear on their own; anything else fails straight away.
_TRANSIENT_MARKERS = ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "overloaded")

_GEMINI_FALLBACK = "gemini-3.8-flash"
_gemini_model_cache: list[str] = []

_ANTHROPIC_FALLBACK = "claude-sonnet-5"
_anthropic_model_cache: list[str] = []


def _anthropic_candidates(client, preferred: Optional[str]) -> list[str]:
    """Anthropic models to try, best first. Same reasoning as the Gemini list:
    aliases get retired, so ask the account what it can actually reach."""
    global _anthropic_model_cache
    ordered = [preferred or _ANTHROPIC_FALLBACK]

    if not _anthropic_model_cache:
        try:
            _anthropic_model_cache = [m.id for m in client.models.list()]
        except Exception:
            _anthropic_model_cache = [_ANTHROPIC_FALLBACK]

    for name in _anthropic_model_cache:
        if name not in ordered:
            ordered.append(name)
    return ordered


def _gemini_candidates(client, preferred: Optional[str]) -> list[str]:
    """Models to try, best first: the chosen one, then whatever this key can reach.

    Model names get retired and individual models get saturated, so a single
    hardcoded name is a single point of failure. The live list is asked for once
    and reused, and a lookup failure is never fatal.
    """
    global _gemini_model_cache
    ordered = [preferred or _GEMINI_FALLBACK]

    if not _gemini_model_cache:
        try:
            _gemini_model_cache = [
                m.name.split("/")[-1]
                for m in client.models.list()
                if "generateContent" in (getattr(m, "supported_actions", None) or [])
            ]
        except Exception:
            _gemini_model_cache = [_GEMINI_FALLBACK]

    for name in _gemini_model_cache:
        if name not in ordered:
            ordered.append(name)
    return ordered


def _call_text_llm(
    prompt: str,
    *,
    system_prompt: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    provider: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 1024,
) -> str:
    """Call the provider, retrying transient failures, then trying other vendors.

    One vendor being overloaded should not take the assistant down, so after the
    chosen provider is exhausted we try any other provider that has its own key
    configured. The caller's key is never sent to a different vendor: fallbacks
    resolve their own key from the environment or secrets.
    """
    delays = (1.0, 3.0)
    first_choice = _normalize_provider(provider)
    last_exc: Optional[Exception] = None

    for candidate, candidate_key in _provider_candidates(first_choice, api_key):
        for attempt in range(len(delays) + 1):
            try:
                return _call_text_llm_once(
                    prompt,
                    system_prompt=system_prompt,
                    model=model if candidate == first_choice else None,
                    api_key=candidate_key,
                    provider=candidate,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as exc:
                last_exc = exc
                if not any(marker in str(exc) for marker in _TRANSIENT_MARKERS):
                    break  # permanent for this vendor; try the next one
                if attempt == len(delays):
                    break
                time.sleep(delays[attempt])

    raise last_exc if last_exc else RuntimeError("No LLM provider was reachable.")


def _provider_candidates(
    first_choice: str, api_key: Optional[str]
) -> list[tuple[str, Optional[str]]]:
    """The chosen provider first, then any other vendor holding its own key."""
    candidates: list[tuple[str, Optional[str]]] = [(first_choice, api_key)]
    for other in ("gemini", "anthropic", "openai"):
        if other == first_choice:
            continue
        if _resolve_api_key(other, None):
            candidates.append((other, None))
    return candidates


def _call_text_llm_once(
    prompt: str,
    *,
    system_prompt: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    provider: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 1024,
) -> str:
    selected_provider = _normalize_provider(provider)
    selected_key = _resolve_api_key(selected_provider, api_key)
    if not selected_key:
        raise RuntimeError(f"Missing API key for provider '{selected_provider}'.")

    full_prompt = prompt if not system_prompt else f"{system_prompt}\n\n{prompt}"

    if selected_provider == "gemini":
        try:
            from google import genai
        except ImportError as e:
            raise RuntimeError(
                "Missing package `google-genai`. Run: pip install google-genai"
            ) from e

        client = genai.Client(api_key=selected_key)
        last_exc: Optional[Exception] = None
        for candidate in _gemini_candidates(client, model):
            try:
                response = client.models.generate_content(model=candidate, contents=full_prompt)
                return (response.text or "").strip()
            except Exception as exc:
                # A retired model or a saturated one: try the next. Anything else
                # (bad key, malformed request) fails now rather than 5 models later.
                if not any(m in str(exc) for m in _TRANSIENT_MARKERS + ("NOT_FOUND", "404")):
                    raise
                last_exc = exc
        raise last_exc if last_exc else RuntimeError("No Gemini model produced a response.")

    if selected_provider == "openai":
        try:
            from openai import OpenAI
        except ImportError as e:
            raise RuntimeError("Missing package `openai`. Run: pip install openai") from e

        client = OpenAI(api_key=selected_key)
        use_model = model or "gpt-4o-mini"
        response = client.chat.completions.create(
            model=use_model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": full_prompt}],
        )
        return (response.choices[0].message.content or "").strip()

    try:
        from anthropic import Anthropic
    except ImportError as e:
        raise RuntimeError(
            "Missing package `anthropic`. Run: pip install anthropic "
            "or set LLM_PROVIDER=gemini and use GEMINI_API_KEY."
        ) from e

    client = Anthropic(api_key=selected_key)
    last_exc: Optional[Exception] = None
    for candidate in _anthropic_candidates(client, model):
        create_kwargs: dict[str, Any] = {
            "model": candidate,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": full_prompt}],
        }
        # anthropic 1.x removed temperature from messages.create().
        if "temperature" in inspect.signature(client.messages.create).parameters:
            create_kwargs["temperature"] = temperature
        try:
            response = client.messages.create(**create_kwargs)
        except Exception as exc:
            # Retired alias or saturated model: try the next. Anything else
            # (bad key, malformed request) fails now rather than 5 models later.
            if not any(m in str(exc) for m in _TRANSIENT_MARKERS + ("not_found", "NOT_FOUND", "404")):
                raise
            last_exc = exc
            continue
        if not response.content:
            return ""
        return "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        ).strip()
    raise last_exc if last_exc else RuntimeError("No Anthropic model produced a response.")


def call_llm(
    prompt_or_system: str,
    messages: Optional[list[dict]] = None,
    tools: Optional[list[dict]] = None,
    *,
    system_prompt: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    provider: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 1024,
) -> Any:
    # Legacy mode: return plain text string.
    if messages is None:
        return _call_text_llm(
            prompt_or_system,
            system_prompt=system_prompt,
            model=model,
            api_key=api_key,
            provider=provider,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    # Agent mode: return dict {"tool_call": {...} | None, "text": str | None}
    system_text = prompt_or_system or ""
    tool_specs = tools or []
    prompt = (
        "You are an agent that must reply in strict JSON.\n"
        "Return exactly one JSON object with either:\n"
        '1) {"tool_call":{"name":"tool_name","arguments":{...}}}\n'
        '2) {"text":"final answer"}\n'
        "Never include markdown.\n\n"
        f"SYSTEM:\n{system_text}\n\n"
        f"TOOLS:\n{json.dumps(tool_specs, ensure_ascii=True)}\n\n"
        f"MESSAGES:\n{json.dumps(messages, ensure_ascii=True)}\n"
    )
    raw = _call_text_llm(
        prompt,
        model=model,
        api_key=api_key,
        provider=provider,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    data = _extract_json_object(raw)
    if not data:
        return {"tool_call": None, "text": (raw or "").strip()}

    tc = data.get("tool_call")
    if isinstance(tc, dict) and isinstance(tc.get("name"), str):
        args = tc.get("arguments", {})
        if not isinstance(args, dict):
            args = {}
        return {"tool_call": {"name": tc["name"], "arguments": args}, "text": None}

    txt = data.get("text")
    return {"tool_call": None, "text": str(txt).strip() if txt is not None else (raw or "").strip()}


def call_vision(
    prompt: str,
    image_bytes: bytes,
    *,
    mime_type: str = "image/png",
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    provider: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 1024,
) -> str:
    selected_provider = _normalize_provider(provider)
    selected_key = _resolve_api_key(selected_provider, api_key)
    if not selected_key:
        raise RuntimeError(f"Missing API key for provider '{selected_provider}'.")

    if selected_provider == "gemini":
        try:
            from google import genai
            from google.genai import types
        except ImportError as e:
            raise RuntimeError(
                "Missing package `google-genai`. Run: pip install google-genai"
            ) from e

        client = genai.Client(api_key=selected_key)
        use_model = model or "gemini-3.8-flash"
        response = client.models.generate_content(
            model=use_model,
            contents=[prompt, types.Part.from_bytes(data=image_bytes, mime_type=mime_type)],
        )
        return (response.text or "").strip()

    if selected_provider == "openai":
        import base64
        try:
            from openai import OpenAI
        except ImportError as e:
            raise RuntimeError("Missing package `openai`. Run: pip install openai") from e

        client = OpenAI(api_key=selected_key)
        use_model = model or "gpt-4o-mini"
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        response = client.chat.completions.create(
            model=use_model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}},
                    ],
                }
            ],
        )
        return (response.choices[0].message.content or "").strip()

    raise NotImplementedError("Vision is not implemented for Anthropic in this client.")
