"""
Unified AI client for ThemisIQ.

All modules call create_message() instead of directly using provider SDKs.
Supports: anthropic, deepseek, gemini, openai, ollama.
Provider is selected via AI_PROVIDER env var (default: anthropic).
"""
import json
import logging
import os
import re

import httpx

from config import settings

log = logging.getLogger(__name__)


def _provider():
    return getattr(settings, "AI_PROVIDER", "anthropic").lower()


def _key(name):
    return getattr(settings, name, "") or ""


def _model_for_provider(provider=None):
    p = provider or _provider()
    return {
        "anthropic": getattr(settings, "ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
        "openai": getattr(settings, "OPENAI_MODEL", "gpt-4o"),
        "gemini": getattr(settings, "GEMINI_MODEL", "gemini-1.5-pro"),
        "deepseek": getattr(settings, "DEEPSEEK_MODEL", "deepseek-chat"),
        "ollama": getattr(settings, "OLLAMA_MODEL", "llama3.2"),
    }.get(p, "claude-sonnet-4-20250514")


def is_configured() -> bool:
    """Return True if the active AI provider has an API key set."""
    p = _provider()
    if p == "anthropic":
        return bool(_key("ANTHROPIC_API_KEY"))
    if p == "openai":
        return bool(_key("OPENAI_API_KEY"))
    if p == "gemini":
        return bool(_key("GEMINI_API_KEY"))
    if p == "deepseek":
        return bool(_key("DEEPSEEK_API_KEY"))
    if p == "ollama":
        return True
    return False


def provider_name() -> str:
    """Return a human-readable name for the current provider."""
    return {
        "anthropic": "Claude",
        "openai": "GPT",
        "gemini": "Gemini",
        "deepseek": "DeepSeek",
        "ollama": "Ollama",
    }.get(_provider(), _provider())


def create_message(
    messages: list[dict],
    system: str = "",
    max_tokens: int = 2000,
    model: str = "",
) -> str:
    """
    Send a chat completion request to the configured AI provider.

    Args:
        messages: list of {"role": "user"|"assistant", "content": str}
        system: optional system prompt
        max_tokens: max response tokens
        model: override model name (default: from config)

    Returns:
        The assistant's response text.

    Raises:
        RuntimeError on API errors or missing configuration.
    """
    p = _provider()
    model = model or _model_for_provider(p)

    if p == "anthropic":
        return _anthropic(messages, system, max_tokens, model)
    elif p == "deepseek":
        return _openai_compat(
            messages, system, max_tokens, model,
            _key("DEEPSEEK_API_KEY"),
            "https://api.deepseek.com/v1/chat/completions",
            "DEEPSEEK_API_KEY",
        )
    elif p == "gemini":
        return _gemini(messages, system, max_tokens, model)
    elif p == "openai":
        return _openai_compat(
            messages, system, max_tokens, model,
            _key("OPENAI_API_KEY"),
            "https://api.openai.com/v1/chat/completions",
            "OPENAI_API_KEY",
        )
    elif p == "ollama":
        host = getattr(settings, "OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        return _openai_compat(
            messages, system, max_tokens, model,
            "",
            f"{host}/v1/chat/completions",
            "",
        )
    else:
        raise RuntimeError(f"Unknown AI_PROVIDER: {p}")


def _anthropic(messages, system, max_tokens, model):
    key = _key("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")
    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system:
        body["system"] = system
    with httpx.Client(timeout=120) as client:
        r = client.post("https://api.anthropic.com/v1/messages", headers=headers, json=body)
        r.raise_for_status()
        data = r.json()
        return data["content"][0]["text"]


def _openai_compat(messages, system, max_tokens, model, api_key, url, key_name):
    if key_name and not api_key:
        raise RuntimeError(f"{key_name} not configured")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": msgs,
    }
    with httpx.Client(timeout=120) as client:
        r = client.post(url, headers=headers, json=body)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


def _gemini(messages, system, max_tokens, model):
    key = _key("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not configured")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    parts_text = ""
    if system:
        parts_text += system + "\n\n"
    for m in messages:
        parts_text += m["content"] + "\n\n"
    body = {
        "contents": [{"parts": [{"text": parts_text.strip()}]}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    with httpx.Client(timeout=120) as client:
        r = client.post(url, json=body)
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def safe_json_parse(text, fallback=None):
    """Lenient JSON parser for AI responses."""
    text = re.sub(r"```json|```", "", text).strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    m = re.search(r"\[[\s\S]*\]", text)
    if m:
        try:
            return json.loads(m.group(0))
        except (json.JSONDecodeError, TypeError):
            pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except (json.JSONDecodeError, TypeError):
            pass
    return fallback
