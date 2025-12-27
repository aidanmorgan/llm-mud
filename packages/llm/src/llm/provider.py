"""
LLM Provider Abstraction

Defines the interface for LLM providers with support for:
- Structured output via Pydantic schemas
- Raw text generation
- Token usage tracking
- Error handling with retries
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TypeVar, Generic, Optional, Type, Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# TypeVar for structured output (bound to BaseModel)
T = TypeVar("T", bound=BaseModel)

# TypeVar for any content type (including str for raw output)
ContentT = TypeVar("ContentT")


class GenerationError(Exception):
    """Error during LLM generation."""

    def __init__(
        self,
        message: str,
        provider: str = "",
        retryable: bool = False,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable
        self.original_error = original_error


@dataclass
class TokenUsage:
    """Token usage statistics for a generation request."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class GenerationResult(Generic[ContentT]):
    """Result of an LLM generation request."""

    content: ContentT
    usage: TokenUsage = field(default_factory=TokenUsage)
    model: str = ""
    latency_ms: float = 0.0
    raw_response: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.content is not None


@dataclass
class ProviderConfig:
    """Configuration for an LLM provider."""

    api_key: str
    model: str = ""
    max_tokens: int = 4096
    temperature: float = 0.7
    timeout: float = 30.0
    max_retries: int = 3
    base_url: Optional[str] = None


class LLMProvider(ABC):
    """
    Abstract base class for LLM providers.

    Provides a unified interface for generating content using different
    LLM backends (Claude, GPT, local models, etc.).

    Usage:
        provider = AnthropicProvider(config)

        # Structured output
        result = await provider.generate_structured(
            prompt="Generate a dark cave room",
            schema=GeneratedRoom,
            system="You are a fantasy world builder."
        )
        room = result.content  # GeneratedRoom instance

        # Raw text
        result = await provider.generate_raw(
            prompt="Describe a goblin",
            system="You are a fantasy writer."
        )
        text = result.content  # str
    """

    def __init__(self, config: ProviderConfig):
        self.config = config
        self._request_count = 0
        self._total_tokens = 0

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider name (e.g., 'anthropic', 'openai')."""
        pass

    @property
    def default_model(self) -> str:
        """Return the default model for this provider."""
        return ""

    @property
    def model(self) -> str:
        """Return the configured model or default."""
        return self.config.model or self.default_model

    @abstractmethod
    async def generate_structured(
        self,
        prompt: str,
        schema: Type[T],
        system: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> GenerationResult[T]:
        """
        Generate structured output matching a Pydantic schema.

        Args:
            prompt: The user prompt describing what to generate
            schema: Pydantic model class for the expected output
            system: Optional system prompt
            temperature: Override default temperature
            max_tokens: Override default max tokens

        Returns:
            GenerationResult containing the parsed schema instance

        Raises:
            GenerationError: If generation or parsing fails
        """
        pass

    @abstractmethod
    async def generate_raw(
        self,
        prompt: str,
        system: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> GenerationResult[str]:
        """
        Generate raw text output.

        Args:
            prompt: The user prompt
            system: Optional system prompt
            temperature: Override default temperature
            max_tokens: Override default max tokens

        Returns:
            GenerationResult containing the raw text response

        Raises:
            GenerationError: If generation fails
        """
        pass

    async def generate_batch(
        self,
        prompts: list[str],
        schema: Type[T],
        system: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> list[GenerationResult[T]]:
        """
        Generate multiple structured outputs.

        Default implementation calls generate_structured sequentially.
        Providers may override for batch API support.

        Args:
            prompts: List of prompts to process
            schema: Pydantic model class for expected output
            system: Optional system prompt (shared across all)
            temperature: Override default temperature
            max_tokens: Override default max tokens

        Returns:
            List of GenerationResults
        """
        results = []
        for prompt in prompts:
            try:
                result = await self.generate_structured(
                    prompt=prompt,
                    schema=schema,
                    system=system,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                results.append(result)
            except GenerationError as e:
                logger.warning(f"Batch generation failed for prompt: {e}")
                # Continue with remaining prompts
        return results

    def get_stats(self) -> dict[str, Any]:
        """Get provider usage statistics."""
        return {
            "provider": self.provider_name,
            "model": self.model,
            "request_count": self._request_count,
            "total_tokens": self._total_tokens,
        }

    def _track_usage(self, usage: TokenUsage) -> None:
        """Track token usage for statistics."""
        self._request_count += 1
        self._total_tokens += usage.total_tokens
