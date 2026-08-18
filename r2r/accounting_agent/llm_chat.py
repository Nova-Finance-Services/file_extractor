"""OpenAI primary, Anthropic failover — same shape as the Edge agent chat."""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

import requests

from r2r.config import (
    ANTHROPIC_API_KEY,
    CLAUDE_MODEL_COMPLEX,
    CLAUDE_MODEL_MEDIUM,
    OPENAI_API_KEY,
    OPENAI_MODEL_COMPLEX,
    OPENAI_MODEL_MEDIUM,
)

logger = logging.getLogger(__name__)

_last_llm_info: Optional[dict[str, Any]] = None
_openai_client = None


def get_last_agent_llm_info() -> Optional[dict[str, Any]]:
    return _last_llm_info


def _openai():
    global _openai_client
    if _openai_client is None:
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        from openai import OpenAI
        _openai_client = OpenAI(api_key=OPENAI_API_KEY)
    return _openai_client


def _call_openai(messages: list[dict[str, Any]], tools: list[dict[str, Any]], model: str) -> dict[str, Any]:
    completion = _openai().chat.completions.create(
        model=model,
        messages=messages,
        tools=tools,
        tool_choice="auto",
    )
    msg = completion.choices[0].message
    tool_calls = []
    for tc in msg.tool_calls or []:
        if getattr(tc, "type", None) == "function" and getattr(tc, "function", None):
            tool_calls.append({
                "id": str(tc.id),
                "name": str(tc.function.name),
                "arguments": tc.function.arguments if isinstance(tc.function.arguments, str) else "{}",
            })
    return {"content": msg.content, "toolCalls": tool_calls}


def _convert_messages_for_anthropic(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    system_parts: list[str] = []
    out: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        if role == "system":
            if message.get("content"):
                system_parts.append(str(message["content"]))
            continue
        if role == "tool":
            out.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": message.get("tool_call_id"),
                    "content": message.get("content") or "",
                }],
            })
            continue
        if role == "assistant":
            blocks: list[dict[str, Any]] = []
            if message.get("content"):
                blocks.append({"type": "text", "text": message["content"]})
            for tc in message.get("tool_calls") or []:
                try:
                    parsed = json.loads(tc["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    parsed = {}
                blocks.append({
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["function"]["name"],
                    "input": parsed,
                })
            out.append({"role": "assistant", "content": blocks or (message.get("content") or "")})
            continue
        out.append({"role": "user", "content": message.get("content") or ""})
    return "\n\n".join(system_parts), out


def _call_anthropic(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    model: str,
    max_tokens: int,
) -> dict[str, Any]:
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured")
    system, anthropic_messages = _convert_messages_for_anthropic(messages)
    anthropic_tools = [
        {
            "name": t["function"]["name"],
            "description": t["function"].get("description"),
            "input_schema": t["function"].get("parameters") or {"type": "object", "properties": {}},
        }
        for t in tools
    ]
    body: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": anthropic_messages,
        "tools": anthropic_tools,
    }
    if system:
        body["system"] = system
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json=body,
        timeout=120,
    )
    if not response.ok:
        raise RuntimeError(f"Anthropic {response.status_code}: {response.text[:400]}")
    payload = response.json()
    blocks = payload.get("content") or []
    text = "".join(b.get("text") or "" for b in blocks if b.get("type") == "text")
    tool_calls = [
        {
            "id": str(b.get("id")),
            "name": str(b.get("name")),
            "arguments": json.dumps(b.get("input") or {}),
        }
        for b in blocks
        if b.get("type") == "tool_use" and b.get("name") and b.get("id")
    ]
    return {"content": text or None, "toolCalls": tool_calls}


def agent_chat_with_failover(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
    global _last_llm_info
    try:
        result = _call_openai(messages, tools, OPENAI_MODEL_COMPLEX)
        _last_llm_info = {
            "primary_provider": "openai",
            "provider_used": "openai",
            "fallback_used": False,
            "model": OPENAI_MODEL_COMPLEX,
        }
        return result
    except Exception as primary_error:
        logger.warning("[accounting-agent] OpenAI failed, trying Anthropic: %s", primary_error)
        try:
            result = _call_anthropic(messages, tools, CLAUDE_MODEL_COMPLEX, 4096)
            _last_llm_info = {
                "primary_provider": "openai",
                "provider_used": "anthropic",
                "fallback_used": True,
                "model": CLAUDE_MODEL_COMPLEX,
            }
            return result
        except Exception as fallback_error:
            raise RuntimeError(
                f"All LLM providers failed. OpenAI: {primary_error}. Anthropic: {fallback_error}"
            ) from fallback_error


def run_llm_review(prompt: str) -> Optional[dict[str, Any]]:
    system = "Return ONLY valid JSON with keys: approved (boolean), summary (string), concerns (string[])."
    raw: Optional[str] = None
    try:
        completion = _openai().chat.completions.create(
            model=OPENAI_MODEL_MEDIUM,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        raw = completion.choices[0].message.content
        if not raw:
            raise RuntimeError("Empty OpenAI JSON response")
    except Exception as open_ai_error:
        logger.warning("[accounting-agent] OpenAI JSON completion failed, trying Anthropic: %s", open_ai_error)
        if not ANTHROPIC_API_KEY:
            return None
        try:
            response = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": CLAUDE_MODEL_MEDIUM,
                    "max_tokens": 1024,
                    "system": system,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=60,
            )
            if not response.ok:
                raise RuntimeError(response.text[:400])
            blocks = response.json().get("content") or []
            raw = "".join(b.get("text") or "" for b in blocks if b.get("type") == "text")
            if not raw:
                raise RuntimeError("Empty Anthropic JSON response")
        except Exception as exc:
            logger.warning("[accounting-agent] LLM JSON completion failed (non-fatal): %s", exc)
            return None

    try:
        parsed = json.loads(raw)
        return {
            "approved": bool(parsed.get("approved")),
            "summary": parsed.get("summary") if isinstance(parsed.get("summary"), str) else "",
            "concerns": [str(c) for c in parsed.get("concerns")] if isinstance(parsed.get("concerns"), list) else [],
        }
    except Exception as exc:
        logger.warning("[accounting-agent] LLM review JSON parse failed (non-fatal): %s", exc)
        return None
