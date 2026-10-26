"""
Convenience entrypoint for LLM Client.
Re-exports OpenAILLMClient and LLMClient interface.
"""

from application.interfaces.llm_client import LLMClient
from infrastructure.llm.openai_llm_client import OpenAILLMClient

__all__ = ["LLMClient", "OpenAILLMClient"]
