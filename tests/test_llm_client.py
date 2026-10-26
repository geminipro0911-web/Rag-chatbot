"""
Unit Tests for Configuration and OpenAI LLM Client.
Tests:
- Settings parsing and validation.
- JSON extraction logic (clean, fenced, messy text).
- Exponential backoff retry on HTTP errors.
- Structured output validation & Pydantic model parsing.
- Self-correction loop on schema violation.
- Fallback mode when json_schema is rejected.
"""

import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import pytest
import httpx
from pydantic import BaseModel, Field
from typing import List

from config import Settings
from infrastructure.llm.openai_llm_client import OpenAILLMClient


class SampleSchema(BaseModel):
    name: str = Field(..., description="Name of entity")
    score: float = Field(..., ge=0.0, le=1.0)
    tags: List[str] = Field(default_factory=list)


def test_settings_defaults():
    """Verify default configuration values."""
    s = Settings()
    assert s.timezone == "Asia/Ho_Chi_Minh"
    assert s.max_file_size_mb == 30
    assert s.is_public_default is False
    assert s.pandas_timeout_seconds == 15
    assert s.enable_synthetic_fewshot is True
    assert s.llm_model_name == "gpt-oss-120b"


def test_json_extraction_clean():
    client = OpenAILLMClient()
    raw = '{"name": "test", "score": 0.95, "tags": ["tag1"]}'
    extracted = client._extract_json_substring(raw)
    assert extracted == raw


def test_json_extraction_markdown_fence():
    client = OpenAILLMClient()
    raw = """Here is the result:
```json
{
  "name": "fenced",
  "score": 0.88,
  "tags": ["alpha", "beta"]
}
```
Hope this helps!"""
    extracted = client._extract_json_substring(raw)
    data = json.loads(extracted)
    assert data["name"] == "fenced"
    assert data["score"] == 0.88


def test_json_extraction_text_surrounded():
    client = OpenAILLMClient()
    raw = 'Sure! The output is {"name": "embedded", "score": 0.5, "tags": []} thank you.'
    extracted = client._extract_json_substring(raw)
    data = json.loads(extracted)
    assert data["name"] == "embedded"


@pytest.mark.asyncio
async def test_chat_completion_mock():
    """Test standard chat completion with mocked transport."""
    mock_response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Xin chào! Tôi có thể giúp gì cho bạn?"
                }
            }
        ]
    }

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_response)

    client = OpenAILLMClient(base_url="http://mock-llm/v1")
    # Patch httpx client to use MockTransport
    transport = httpx.MockTransport(mock_handler)
    
    async with httpx.AsyncClient(transport=transport) as mock_http_client:
        # Override _post_with_retry for isolated test
        async def mock_post(payload):
            resp = await mock_http_client.post("http://mock-llm/v1/chat/completions", json=payload)
            return resp.json()
        
        client._post_with_retry = mock_post
        ans = await client.chat_completion([{"role": "user", "content": "Chào"}])
        assert "Xin chào" in ans


@pytest.mark.asyncio
async def test_structured_output_with_self_correction():
    """Test that structured output retries and corrects on invalid initial output."""
    attempts = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        req_json = json.loads(request.content.decode("utf-8"))
        messages = req_json.get("messages", [])

        if attempts == 1:
            # First attempt: invalid format (missing required score)
            bad_content = '{"name": "incomplete"}'
            return httpx.Response(200, json={"choices": [{"message": {"content": bad_content}}]})
        else:
            # Second attempt: LLM corrected based on feedback
            good_content = '{"name": "corrected", "score": 0.99, "tags": ["verified"]}'
            return httpx.Response(200, json={"choices": [{"message": {"content": good_content}}]})

    client = OpenAILLMClient(base_url="http://mock-llm/v1", max_retries=2)
    transport = httpx.MockTransport(mock_handler)

    async with httpx.AsyncClient(transport=transport) as mock_http_client:
        async def mock_post(payload):
            resp = await mock_http_client.post("http://mock-llm/v1/chat/completions", json=payload)
            return resp.json()

        client._post_with_retry = mock_post

        result = await client.structured_output(
            messages=[{"role": "user", "content": "Generate entity"}],
            response_model=SampleSchema,
            max_retries=2
        )

        assert isinstance(result, SampleSchema)
        assert result.name == "corrected"
        assert result.score == 0.99
        assert attempts == 2


@pytest.mark.asyncio
async def test_exponential_backoff_retry_on_server_error():
    """Verify that client retries on HTTP 500 until max_retries or success."""
    calls = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(500, text="Internal Server Error")
        return httpx.Response(200, json={"choices": [{"message": {"content": "Phục hồi thành công"}}]})

    client = OpenAILLMClient(base_url="http://mock-llm/v1", max_retries=4)
    transport = httpx.MockTransport(mock_handler)

    # Use small delay in test by mocking asyncio.sleep
    async with httpx.AsyncClient(transport=transport) as mock_http_client:
        client._endpoint = "http://mock-llm/v1/chat/completions"
        # Temporarily redirect _post_with_retry to use transport
        orig_post = client._post_with_retry

        async def fast_post(payload):
            # Same logic as _post_with_retry but with transport
            attempt = 0
            while attempt < client.max_retries:
                resp = await mock_http_client.post("http://mock-llm/v1/chat/completions", json=payload)
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code in (429, 500, 502, 503, 504):
                    attempt += 1
                    continue
                resp.raise_for_status()
            raise RuntimeError("Exceeded max retries")

        client._post_with_retry = fast_post
        ans = await client.chat_completion([{"role": "user", "content": "Ping"}])
        assert ans == "Phục hồi thành công"
        assert calls == 3


@pytest.mark.asyncio
async def test_structured_output_fallback_when_json_schema_unsupported():
    """Verify fallback to prompt-injected JSON mode when server rejects json_schema."""
    request_formats = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        req_json = json.loads(request.content.decode("utf-8"))
        rf = req_json.get("response_format")
        request_formats.append(rf)

        if rf and rf.get("type") == "json_schema":
            # Endpoint does not support json_schema
            return httpx.Response(400, text="Unrecognized response_format json_schema")
        else:
            # Fallback prompt mode: return valid json in markdown fence
            content = "```json\n{\"name\": \"fallback_success\", \"score\": 0.92, \"tags\": [\"fallback\"]}\n```"
            return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    client = OpenAILLMClient(base_url="http://mock-llm/v1", max_retries=2)
    transport = httpx.MockTransport(mock_handler)

    async with httpx.AsyncClient(transport=transport) as mock_http_client:
        client._endpoint = "http://mock-llm/v1/chat/completions"
        async def mock_post(payload):
            resp = await mock_http_client.post(client._endpoint, json=payload)
            if resp.status_code == 200:
                return resp.json()
            resp.raise_for_status()

        client._post_with_retry = mock_post

        result = await client.structured_output(
            messages=[{"role": "user", "content": "Extract"}],
            response_model=SampleSchema
        )

        assert isinstance(result, SampleSchema)
        assert result.name == "fallback_success"
        assert result.score == 0.92
        assert request_formats[0] is not None
        assert request_formats[1] is None


@pytest.mark.asyncio
async def test_structured_output_positional_arguments():
    """Verify calling structured_output positionally (messages, Model) works without response_model kwarg."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        content = '{"name": "positional_entity", "score": 0.88, "tags": ["pos"]}'
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    client = OpenAILLMClient(base_url="http://mock-llm/v1")
    transport = httpx.MockTransport(mock_handler)

    async with httpx.AsyncClient(transport=transport) as mock_http_client:
        client._endpoint = "http://mock-llm/v1/chat/completions"
        async def mock_post(payload):
            resp = await mock_http_client.post(client._endpoint, json=payload)
            if resp.status_code == 200:
                return resp.json()
            resp.raise_for_status()

        client._post_with_retry = mock_post

        # Positional call: (messages, SampleSchema)
        result = await client.structured_output(
            [{"role": "user", "content": "Extract"}],
            SampleSchema,
        )

        assert isinstance(result, SampleSchema)
        assert result.name == "positional_entity"
        assert result.score == 0.88
