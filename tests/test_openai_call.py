"""Tests for accounting-agent OpenAI Responses helper `_call_openai`."""
import os

import pytest
from dotenv import load_dotenv

from r2r.accounting_agent.llm_chat import _call_openai
from r2r.config import OPENAI_MODEL_COMPLEX

load_dotenv()

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "record_no_action",
            "description": "Record that no accounting action is required.",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"],
            },
        },
    }
]


def test_call_openai(mocker):
    mocker.patch("r2r.accounting_agent.llm_chat.OPENAI_API_KEY", "sk-test")
    mock_resp = mocker.Mock()
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "output": [{
            "type": "function_call",
            "call_id": "call_1",
            "name": "record_no_action",
            "arguments": '{"reason":"nothing to post"}',
        }]
    }
    post = mocker.patch("r2r.accounting_agent.llm_chat.requests.post", return_value=mock_resp)

    result = _call_openai(
        [
            {"role": "system", "content": "Call the tool."},
            {"role": "user", "content": "Nothing to post."},
        ],
        _TOOLS,
        "gpt-5.6-sol",
    )

    assert post.call_args[0][0] == "https://api.openai.com/v1/responses"
    payload = post.call_args.kwargs["json"]
    assert payload["model"] == "gpt-5.6-sol"
    assert payload["instructions"] == "Call the tool."
    assert payload["tools"][0] == {
        "type": "function",
        "name": "record_no_action",
        "description": "Record that no accounting action is required.",
        "parameters": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
        },
    }
    assert result["toolCalls"] == [{
        "id": "call_1",
        "name": "record_no_action",
        "arguments": '{"reason":"nothing to post"}',
    }]


@pytest.mark.openai
def test_call_openai_live():
    if os.environ.get("ACCOUNTING_AGENT_OPENAI", "").strip() != "1":
        pytest.skip("Set ACCOUNTING_AGENT_OPENAI=1 to hit the real OpenAI Responses API")
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        pytest.skip("Set OPENAI_API_KEY")

    import r2r.accounting_agent.llm_chat as llm_chat
    llm_chat.OPENAI_API_KEY = key

    result = _call_openai(
        [
            {
                "role": "system",
                "content": "You MUST call record_no_action. Do not answer in prose.",
            },
            {
                "role": "user",
                "content": "Nothing to post this period. Call record_no_action with a short reason.",
            },
        ],
        _TOOLS,
        OPENAI_MODEL_COMPLEX,
    )
    print(f"\nmodel={OPENAI_MODEL_COMPLEX} result={result}")
    assert result["toolCalls"], result
    assert result["toolCalls"][0]["name"] == "record_no_action"
    assert result["toolCalls"][0]["id"]
    assert result["toolCalls"][0]["arguments"]
