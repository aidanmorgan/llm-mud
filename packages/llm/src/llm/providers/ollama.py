"""
Ollama LLM Provider

Implements the LLMProvider interface for local LLM inference via Ollama.
Supports structured output via JSON mode for reliable schema parsing.

Recommended models for game content generation:
- deepseek-coder-v2:16b-lite-instruct-q4_K_M (fast, good at JSON)
- llama3.1:8b (balanced performance)
- mistral:7b (fast, good quality)
"""

import json
import logging
import os
import time
from typing import Type, TypeVar, Optional

import httpx
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


class OllamaProvider(LLMProvider):
    """
    Local LLM provider via Ollama.

    Ollama runs locally and provides fast inference without API costs.
    Supports structured JSON output for reliable schema parsing.

    Usage:
        config = ProviderConfig(
            api_key="",  # Not needed for Ollama
            model="deepseek-coder-v2:16b-lite-instruct-q4_K_M",
            base_url="http://localhost:11434",
        )
        provider = OllamaProvider(config)

        result = await provider.generate_structured(
            prompt="Generate a dark cave",
            schema=GeneratedRoom,
        )
    """

    DEFAULT_MODEL = "deepseek-coder-v2:16b-lite-instruct-q4_K_M"
    DEFAULT_HOST = "http://localhost:11434"

    def __init__(self, config: Optional[ProviderConfig] = None):
        # Allow creation without config for simple local use
        if config is None:
            config = ProviderConfig(
                api_key="",  # Not needed for Ollama
                model=os.environ.get("LLM_MODEL", self.DEFAULT_MODEL),
                base_url=os.environ.get("OLLAMA_HOST", self.DEFAULT_HOST),
                timeout=120.0,  # Local models can be slower
                max_retries=2,
            )
        super().__init__(config)

        self._host = config.base_url or self.DEFAULT_HOST
        self._client = httpx.AsyncClient(
            base_url=self._host,
            timeout=config.timeout,
        )

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def default_model(self) -> str:
        return self.DEFAULT_MODEL

    async def check_health(self) -> bool:
        """Check if Ollama is running and responsive."""
        try:
            response = await self._client.get("/api/tags")
            return response.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> list[str]:
        """List available models in Ollama."""
        try:
            response = await self._client.get("/api/tags")
            response.raise_for_status()
            data = response.json()
            return [model["name"] for model in data.get("models", [])]
        except Exception as e:
            logger.warning(f"Failed to list models: {e}")
            return []

    async def generate_structured(
        self,
        prompt: str,
        schema: Type[T],
        system: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> GenerationResult[T]:
        """
        Generate structured output using Ollama's JSON mode.

        The schema is provided as a JSON schema in the prompt, and Ollama
        is instructed to respond with valid JSON matching the schema.
        """
        start_time = time.monotonic()

        # Build the JSON schema for the prompt
        json_schema = schema.model_json_schema()
        schema_str = json.dumps(json_schema, indent=2)

        # Build system prompt with schema
        full_system = system or "You are a creative content generator for a fantasy MUD game."
        full_system += f"""

You must respond with a valid JSON object that matches this schema:
{schema_str}

IMPORTANT:
- Return ONLY the JSON object, no other text
- Ensure all required fields are present
- Follow the field constraints (min/max length, enums, etc.)
"""

        try:
            response = await self._client.post(
                "/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "system": full_system,
                    "stream": False,
                    "format": "json",  # Enable JSON mode
                    "options": {
                        "temperature": temperature if temperature is not None else self.config.temperature,
                        "num_predict": max_tokens or self.config.max_tokens,
                    },
                },
            )
            response.raise_for_status()
            data = response.json()

            # Extract the response text
            response_text = data.get("response", "")

            if not response_text:
                raise GenerationError(
                    "Empty response from Ollama",
                    provider=self.provider_name,
                    retryable=True,
                )

            # Parse JSON response
            try:
                json_data = json.loads(response_text)
            except json.JSONDecodeError as e:
                raise GenerationError(
                    f"Invalid JSON in response: {e}",
                    provider=self.provider_name,
                    retryable=True,
                    original_error=e,
                )

            # Validate against schema
            try:
                content = schema.model_validate(json_data)
            except ValidationError as e:
                raise GenerationError(
                    f"Failed to validate response against schema: {e}",
                    provider=self.provider_name,
                    retryable=True,
                    original_error=e,
                )

            # Build usage stats (Ollama provides token counts)
            usage = TokenUsage(
                input_tokens=data.get("prompt_eval_count", 0),
                output_tokens=data.get("eval_count", 0),
            )
            self._track_usage(usage)

            latency_ms = (time.monotonic() - start_time) * 1000

            return GenerationResult(
                content=content,
                usage=usage,
                model=data.get("model", self.model),
                latency_ms=latency_ms,
                raw_response=response_text,
            )

        except httpx.ConnectError as e:
            raise GenerationError(
                f"Cannot connect to Ollama at {self._host}. Is Ollama running?",
                provider=self.provider_name,
                retryable=True,
                original_error=e,
            )
        except httpx.TimeoutException as e:
            raise GenerationError(
                "Request timed out. Try a smaller model or increase timeout.",
                provider=self.provider_name,
                retryable=True,
                original_error=e,
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise GenerationError(
                    f"Model '{self.model}' not found. Run: ollama pull {self.model}",
                    provider=self.provider_name,
                    retryable=False,
                    original_error=e,
                )
            raise GenerationError(
                f"HTTP error: {e}",
                provider=self.provider_name,
                retryable=e.response.status_code >= 500,
                original_error=e,
            )

    async def generate_raw(
        self,
        prompt: str,
        system: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> GenerationResult[str]:
        """Generate raw text output from Ollama."""
        start_time = time.monotonic()

        try:
            response = await self._client.post(
                "/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "system": system or "You are a creative content generator for a fantasy MUD game.",
                    "stream": False,
                    "options": {
                        "temperature": temperature if temperature is not None else self.config.temperature,
                        "num_predict": max_tokens or self.config.max_tokens,
                    },
                },
            )
            response.raise_for_status()
            data = response.json()

            response_text = data.get("response", "")

            # Build usage stats
            usage = TokenUsage(
                input_tokens=data.get("prompt_eval_count", 0),
                output_tokens=data.get("eval_count", 0),
            )
            self._track_usage(usage)

            latency_ms = (time.monotonic() - start_time) * 1000

            return GenerationResult(
                content=response_text,
                usage=usage,
                model=data.get("model", self.model),
                latency_ms=latency_ms,
                raw_response=response_text,
            )

        except httpx.ConnectError as e:
            raise GenerationError(
                f"Cannot connect to Ollama at {self._host}. Is Ollama running?",
                provider=self.provider_name,
                retryable=True,
                original_error=e,
            )
        except httpx.TimeoutException as e:
            raise GenerationError(
                "Request timed out",
                provider=self.provider_name,
                retryable=True,
                original_error=e,
            )
        except httpx.HTTPStatusError as e:
            raise GenerationError(
                f"HTTP error: {e}",
                provider=self.provider_name,
                retryable=e.response.status_code >= 500,
                original_error=e,
            )

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()
