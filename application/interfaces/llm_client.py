"""
LLM Client Interface.
Defines abstract contracts for raw chat completion and validated structured output.
Supports both conversational messages lists and direct prompt / system_prompt inputs.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Type, TypeVar, Optional
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMClient(ABC):
    """Abstract interface for LLM communication."""

    @abstractmethod
    async def chat_completion(
        self,
        messages: Optional[List[Dict[str, str]]] = None,
        prompt: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: Optional[int] = 4096,
        stop: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> str:
        """
        Execute raw conversational completion with LLM.
        Accepts either 'messages' or ('prompt' + optional 'system_prompt').
        """
        pass

    @abstractmethod
    async def structured_output(
        self,
        response_model: Type[T],
        messages: Optional[List[Dict[str, str]]] = None,
        prompt: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_retries: int = 2,
        **kwargs: Any,
    ) -> T:
        """
        Execute structured LLM generation and validate output against a Pydantic model.
        Supports native json_schema response_format and json markdown fallback parser.
        Accepts either 'messages' or ('prompt' + optional 'system_prompt').
        """
        pass
