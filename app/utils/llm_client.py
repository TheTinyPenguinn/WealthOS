from __future__ import annotations

import os
from typing import Optional


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


def call_llm(
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
        import google.generativeai as genai

        genai.configure(api_key=selected_key)
        use_model = model or "gemini-1.5-flash"
        response = genai.GenerativeModel(use_model).generate_content(full_prompt)
        return (response.text or "").strip()

    if selected_provider == "openai":
        from openai import OpenAI

        client = OpenAI(api_key=selected_key)
        use_model = model or "gpt-4o-mini"
        response = client.chat.completions.create(
            model=use_model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": full_prompt}],
        )
        return (response.choices[0].message.content or "").strip()

    from anthropic import Anthropic

    client = Anthropic(api_key=selected_key)
    use_model = model or "claude-3-5-sonnet-latest"
    response = client.messages.create(
        model=use_model,
        temperature=temperature,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": full_prompt}],
    )
    if not response.content:
        return ""
    return "".join(block.text for block in response.content if getattr(block, "type", "") == "text").strip()


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
        import google.generativeai as genai

        genai.configure(api_key=selected_key)
        use_model = model or "gemini-1.5-flash"
        response = genai.GenerativeModel(use_model).generate_content(
            [prompt, {"mime_type": mime_type, "data": image_bytes}]
        )
        return (response.text or "").strip()

    if selected_provider == "openai":
        import base64
        from openai import OpenAI

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
