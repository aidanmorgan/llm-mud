"""
Anthropic/Claude LLM Provider

Implements the LLMProvider interface for Claude models.
Uses structured output via tool use for reliable schema parsing.
"""

import json
import logging
import time
from typing import Type, TypeVar, Optional

import anthropic
from pydantic import BaseModel, ValidationError

from ..provider import (
    LLMProvider,
    ProviderConfig,
    GenerationResult,
    GenerationError,
    TokenUsage,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class AnthropicProvider(LLMProvider):
    """
    Claude/Anthropic LLM provider.

    Uses Claude's tool use feature for structured output generation,
    ensuring reliable parsing into Pydantic schemas.

    Usage:
        config = ProviderConfig(
            api_key="sk-ant-...",
            model="claude-sonnet-4-20250514",  # optional, has default
        )
        provider = AnthropicProvider(config)

        result = await provider.generate_structured(
            prompt="Generate a dark cave",
            schema=GeneratedRoom,
        )
    """

    DEFAULT_MODEL = "claude-sonnet-4-20250514"

    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self._client = anthropic.AsyncAnthropic(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.timeout,
            max_retries=config.max_retries,
        )

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def default_model(self) -> str:
        return self.DEFAULT_MODEL

    async def generate_structured(
        self,
        prompt: str,
        schema: Type[T],
        system: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> GenerationResult[T]:
        """
        Generate structured output using Claude's tool use.

        The schema is converted to a tool definition, and Claude is instructed
        to call the tool with the generated content. This ensures the output
        conforms to the expected schema.
        """
        start_time = time.monotonic()

        # Convert Pydantic schema to tool definition
        tool_name = f"generate_{schema.__name__.lower()}"
        tool = {
            "name": tool_name,
            "description": f"Generate a {schema.__name__} with the specified fields",
            "input_schema": schema.model_json_schema(),
        }

        # Build system prompt
        full_system = system or "You are a creative content generator for a fantasy MUD game."
        full_system += (
            f"\n\nYou must use the {tool_name} tool to provide your response. "
            "Be creative but stay within the constraints provided."
        )

        try:
            response = await self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens or self.config.max_tokens,
                temperature=temperature if temperature is not None else self.config.temperature,
                system=full_system,
                messages=[{"role": "user", "content": prompt}],
                tools=[tool],
                tool_choice={"type": "tool", "name": tool_name},
            )

            # Extract tool use result
            tool_use_block = None
            for block in response.content:
                if block.type == "tool_use" and block.name == tool_name:
                    tool_use_block = block
                    break

            if not tool_use_block:
                raise GenerationError(
                    "No tool use found in response",
                    provider=self.provider_name,
                    retryable=True,
                )

            # Parse into schema
            try:
                content = schema.model_validate(tool_use_block.input)
            except ValidationError as e:
                raise GenerationError(
                    f"Failed to parse response into schema: {e}",
                    provider=self.provider_name,
                    retryable=False,
                    original_error=e,
                )

            # Build usage stats
            usage = TokenUsage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            )
            self._track_usage(usage)

            latency_ms = (time.monotonic() - start_time) * 1000

            return GenerationResult(
                content=content,
                usage=usage,
                model=response.model,
                latency_ms=latency_ms,
                raw_response=json.dumps(tool_use_block.input),
            )

        except anthropic.APIConnectionError as e:
            raise GenerationError(
                f"Connection error: {e}",
                provider=self.provider_name,
                retryable=True,
                original_error=e,
            )
        except anthropic.RateLimitError as e:
            raise GenerationError(
                f"Rate limit exceeded: {e}",
                provider=self.provider_name,
                retryable=True,
                original_error=e,
            )
        except anthropic.APIStatusError as e:
            raise GenerationError(
                f"API error: {e}",
                provider=self.provider_name,
                retryable=e.status_code >= 500,
                original_error=e,
            )

    async def generate_raw(
        self,
        prompt: str,
        system: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> GenerationResult[str]:
        """Generate raw text output from Claude."""
        start_time = time.monotonic()

        try:
            response = await self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens or self.config.max_tokens,
                temperature=temperature if temperature is not None else self.config.temperature,
                system=system or "You are a creative content generator for a fantasy MUD game.",
                messages=[{"role": "user", "content": prompt}],
            )

            # Extract text content
            text_content = ""
            for block in response.content:
                if block.type == "text":
                    text_content += block.text

            # Build usage stats
            usage = TokenUsage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            )
            self._track_usage(usage)

            latency_ms = (time.monotonic() - start_time) * 1000

            return GenerationResult(
                content=text_content,
                usage=usage,
                model=response.model,
                latency_ms=latency_ms,
                raw_response=text_content,
            )

        except anthropic.APIConnectionError as e:
            raise GenerationError(
                f"Connection error: {e}",
                provider=self.provider_name,
                retryable=True,
                original_error=e,
            )
        except anthropic.RateLimitError as e:
            raise GenerationError(
                f"Rate limit exceeded: {e}",
                provider=self.provider_name,
                retryable=True,
                original_error=e,
            )
        except anthropic.APIStatusError as e:
            raise GenerationError(
                f"API error: {e}",
                provider=self.provider_name,
                retryable=e.status_code >= 500,
                original_error=e,
            )
