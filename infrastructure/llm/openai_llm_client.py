"""
OpenAI-Compatible LLM Client Implementation.
Features:
- Configurable timeout and exponential backoff retry.
- Raw conversational chat completion.
- Robust structured output generation with Pydantic validation.
- Automatic fallback JSON parser when endpoint does not support json_schema.
- Self-correction loop when LLM output violates schema.
"""

import re
import json
import asyncio
import random
import logging
from typing import List, Dict, Any, Type, TypeVar, Optional
import httpx
from pydantic import BaseModel, ValidationError

from application.interfaces.llm_client import LLMClient
from config import settings

logger = logging.getLogger("OpenAILLMClient")
T = TypeVar("T", bound=BaseModel)


class OpenAILLMClient(LLMClient):
    """
    Robust asynchronous LLM client compatible with vLLM, Ollama, Local Gateway,
    and standard OpenAI-compatible API servers.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout_seconds: Optional[float] = None,
        max_retries: Optional[int] = None,
    ):
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.api_key = api_key or settings.llm_api_key
        self.model_name = model_name or settings.llm_model_name
        self.temperature = temperature if temperature is not None else settings.llm_temperature
        self.max_tokens = max_tokens if max_tokens is not None else settings.llm_max_tokens
        self.timeout_seconds = timeout_seconds or settings.llm_timeout_seconds
        self.max_retries = max_retries or settings.llm_max_retries

        self._headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        self._endpoint = f"{self.base_url}/chat/completions"

    async def _post_with_retry(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute POST request with exponential backoff retry strategy.
        Retries on connection errors, timeouts, rate limits (429), and server errors (5xx).
        """
        attempt = 0
        last_exception = None

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            while attempt < self.max_retries:
                try:
                    logger.debug(
                        f"Sending request to {self._endpoint} (model={payload.get('model')}, attempt={attempt + 1})"
                    )
                    response = await client.post(
                        self._endpoint,
                        headers=self._headers,
                        json=payload
                    )

                    # Success
                    if response.status_code == 200:
                        return response.json()

                    # Handle retryable HTTP statuses
                    if response.status_code in (429, 500, 502, 503, 504):
                        attempt += 1
                        delay = min(1.0 * (2 ** attempt) + random.uniform(0.1, 0.5), 10.0)
                        logger.warning(
                            f"LLM API returned status {response.status_code}. Retrying in {delay:.2f}s "
                            f"(attempt {attempt}/{self.max_retries}). Response: {response.text[:200]}"
                        )
                        await asyncio.sleep(delay)
                        continue

                    # Non-retryable error (e.g. 400 Bad Request, 401 Unauthorized)
                    error_msg = f"LLM API returned client error {response.status_code}: {response.text}"
                    logger.error(error_msg)
                    response.raise_for_status()

                except (httpx.TimeoutException, httpx.NetworkError, httpx.TransportError) as e:
                    attempt += 1
                    last_exception = e
                    delay = min(1.0 * (2 ** attempt) + random.uniform(0.1, 0.5), 10.0)
                    logger.warning(
                        f"Network exception calling LLM ({type(e).__name__}: {e}). "
                        f"Retrying in {delay:.2f}s (attempt {attempt}/{self.max_retries})"
                    )
                    await asyncio.sleep(delay)

        raise RuntimeError(
            f"Failed to communicate with LLM API at {self._endpoint} after {self.max_retries} attempts. "
            f"Last error: {last_exception}"
        )

    async def chat_completion(
        self,
        messages: Optional[List[Dict[str, str]]] = None,
        prompt: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> str:
        """
        Execute conversational completion.
        Accepts either 'messages' or ('prompt' + optional 'system_prompt').
        """
        if messages is None:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            if prompt:
                messages.append({"role": "user", "content": prompt})

        eff_temp = temperature if temperature is not None else self.temperature
        eff_max_tokens = max_tokens if max_tokens is not None else self.max_tokens

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": eff_temp,
            "max_tokens": eff_max_tokens,
        }
        if stop:
            payload["stop"] = stop

        result = await self._post_with_retry(payload)
        try:
            content = result["choices"][0]["message"]["content"]
            return content.strip()
        except (KeyError, IndexError) as e:
            logger.error(f"Malformed LLM response format: {result}")
            raise ValueError(f"Invalid response structure from LLM server: {e}")

    @staticmethod
    def _extract_json_substring(text: str) -> str:
        """
        Extract JSON payload from markdown code fences or raw text.
        Handles ```json ... ``` or finds first '{' to last '}'.
        """
        text = text.strip()

        # Check for markdown code fences
        fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
        if fence_match:
            return fence_match.group(1).strip()

        # Look for outermost matching curly brackets
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            return text[first_brace:last_brace + 1].strip()

        # Look for array brackets
        first_bracket = text.find("[")
        last_bracket = text.rfind("]")
        if first_bracket != -1 and last_bracket != -1 and last_bracket > first_bracket:
            return text[first_bracket:last_bracket + 1].strip()

        return text

    async def structured_output(
        self,
        arg1: Any = None,
        arg2: Any = None,
        response_model: Optional[Type[T]] = None,
        messages: Optional[List[Dict[str, str]]] = None,
        prompt: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_retries: int = 2,
        **kwargs: Any,
    ) -> T:
        """
        Generate structured output validated against a Pydantic model.
        Features dual-path strategy:
        1. Attempts native json_schema format.
        2. Falls back to JSON prompt mode with markdown fence extraction if unsupported.
        3. Includes self-correction loop on validation failure.
        Polymorphic: supports (messages, response_model), (response_model, messages),
        and keyword arguments (response_model=..., prompt=..., system_prompt=...).
        """
        target_model: Optional[Type[T]] = response_model
        input_messages: Optional[List[Dict[str, str]]] = messages

        # Parse positional arguments if provided
        for arg in (arg1, arg2):
            if arg is None:
                continue
            if isinstance(arg, type) and issubclass(arg, BaseModel):
                target_model = arg
            elif isinstance(arg, list):
                input_messages = arg

        if target_model is None:
            raise ValueError("structured_output requires a valid Pydantic response_model")

        if input_messages is None:
            input_messages = []
            if system_prompt:
                input_messages.append({"role": "system", "content": system_prompt})
            if prompt:
                input_messages.append({"role": "user", "content": prompt})

        eff_temp = temperature if temperature is not None else self.temperature
        schema_dict = target_model.model_json_schema()
        schema_json_str = json.dumps(schema_dict, indent=2, ensure_ascii=False)

        current_messages = list(input_messages)
        supports_json_schema = True

        for retry_attempt in range(max_retries + 1):
            payload: Dict[str, Any] = {
                "model": self.model_name,
                "messages": current_messages,
                "temperature": eff_temp,
                "max_tokens": self.max_tokens,
            }

            if supports_json_schema:
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": target_model.__name__,
                        "strict": True,
                        "schema": schema_dict,
                    },
                }

            try:
                result = await self._post_with_retry(payload)
                raw_text = result["choices"][0]["message"]["content"]
            except httpx.HTTPStatusError as err:
                # If endpoint rejected response_format=json_schema with 400 Bad Request
                if err.response.status_code == 400 and supports_json_schema:
                    logger.warning(
                        "LLM endpoint rejected 'response_format=json_schema'. "
                        "Switching to fallback JSON prompt instruction mode."
                    )
                    supports_json_schema = False

                    # Inject schema instruction into prompt
                    system_schema_instruction = (
                        f"\n\nIMPORTANT: You must respond ONLY with a valid JSON object matching this schema:\n"
                        f"{schema_json_str}\n"
                        "Do not include any commentary or extra text outside the JSON object."
                    )
                    current_messages[-1]["content"] += system_schema_instruction
                    continue
                else:
                    raise

            # Extract JSON and validate against Pydantic model
            clean_json_str = self._extract_json_substring(raw_text)

            try:
                parsed_instance = target_model.model_validate_json(clean_json_str)
                return parsed_instance
            except (ValidationError, json.JSONDecodeError) as val_err:
                logger.warning(
                    f"Structured output validation failed (attempt {retry_attempt + 1}/{max_retries + 1}): {val_err}"
                )

                if retry_attempt < max_retries:
                    # Self-correction: feed error back to LLM
                    error_feedback = (
                        f"Your previous output was invalid JSON or did not match the required schema.\n"
                        f"Validation Error: {str(val_err)}\n"
                        f"Required JSON Schema:\n{schema_json_str}\n"
                        f"Please provide the corrected JSON object ONLY."
                    )
                    current_messages.append({"role": "assistant", "content": raw_text})
                    current_messages.append({"role": "user", "content": error_feedback})
                else:
                    logger.error(
                        f"Structured output failed after {max_retries} correction retries. Raw output was: {raw_text}"
                    )
                    raise ValueError(
                        f"Failed to generate valid structured output for {target_model.__name__}: {val_err}"
                    )

        raise RuntimeError("Unreachable loop termination in structured_output.")
