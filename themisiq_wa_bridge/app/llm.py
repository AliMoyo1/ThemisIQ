"""LLM orchestration — reuses ThemisIQ's provider set.

Per the Platform Manual (Ch. 4.3) ThemisIQ supports anthropic / deepseek /
openai / gemini / ollama. We mirror that switch. In OFFLINE_MODE we return a
stub so the bridge can be smoke-tested with no keys and no network.
"""
from __future__ import annotations

import os
from .config import get_settings


def _provider_key(provider: str) -> str:
    return {
        "anthropic": get_settings().anthropic_api_key,
        "deepseek": get_settings().deepseek_api_key,
        "openai": get_settings().openai_api_key,
        "gemini": get_settings().gemini_api_key,
    }.get(provider, "")


def complete(system_prompt: str, user_prompt: str) -> str:
    """Return an LLM completion. In offline mode, returns a stub string."""
    s = get_settings()
    if s.offline_mode:
        return ("[offline stub] Draft response for prompt:\n" + user_prompt)[:1500]

    provider = s.ai_provider
    api_key = _provider_key(provider)
    if not api_key and provider != "ollama":
        return "[LLM unavailable: no API key configured]"

    # Thin dispatch. Keeps heavy SDK imports out of the hot path / optional.
    if provider == "anthropic":
        return _complete_anthropic(s.ai_model, api_key, system_prompt, user_prompt)
    if provider == "openai":
        return _complete_openai(s.ai_model, api_key, system_prompt, user_prompt)
    if provider == "deepseek":
        return _complete_openai(s.ai_model, api_key, system_prompt, user_prompt,
                                base_url="https://api.deepseek.com")
    if provider == "gemini":
        return _complete_gemini(s.ai_model, api_key, system_prompt, user_prompt)
    if provider == "ollama":
        return _complete_ollama(s.ollama_host, s.ai_model, system_prompt, user_prompt)
    return "[LLM provider not recognised]"


def _complete_anthropic(model, key, system, user) -> str:
    import anthropic  # type: ignore
    c = anthropic.Anthropic(api_key=key)
    r = c.messages.create(model=model, max_tokens=1024, system=system,
                          messages=[{"role": "user", "content": user}])
    return "".join(b.text for b in r.content)


def _complete_openai(model, key, system, user, base_url=None) -> str:
    from openai import OpenAI  # type: ignore
    c = OpenAI(api_key=key, base_url=base_url)
    r = c.chat.completions.create(
        model=model, max_tokens=1024,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}])
    return r.choices[0].message.content or ""


def _complete_gemini(model, key, system, user) -> str:
    import google.generativeai as genai  # type: ignore
    genai.configure(api_key=key)
    m = genai.GenerativeModel(model, system_instruction=system)
    r = m.generate_content(user)
    return r.text or ""


def _complete_ollama(host, model, system, user) -> str:
    import httpx
    r = httpx.post(f"{host}/api/generate", json={
        "model": model, "system": system, "prompt": user, "stream": False},
        timeout=60.0)
    r.raise_for_status()
    return r.json().get("response", "")
