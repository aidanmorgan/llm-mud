"""
LLM Provider Factory

Provides a unified way to get the configured LLM provider based on
environment settings. Supports automatic fallback from local to cloud providers.
"""

import logging
import os
from typing import Optional

from ..provider import LLMProvider, ProviderConfig

logger = logging.getLogger(__name__)


class ProviderType:
    """Supported provider types."""

    OLLAMA = "ollama"
    ANTHROPIC = "anthropic"
    OPENAI = "openai"


def get_provider_config() -> ProviderConfig:
    """Build provider config from environment variables."""
    return ProviderConfig(
        api_key=os.environ.get("LLM_API_KEY", ""),
        model=os.environ.get("LLM_MODEL", ""),
        base_url=os.environ.get("LLM_BASE_URL"),
        timeout=float(os.environ.get("LLM_TIMEOUT", "120.0")),
        max_retries=int(os.environ.get("LLM_MAX_RETRIES", "3")),
        temperature=float(os.environ.get("LLM_TEMPERATURE", "0.7")),
        max_tokens=int(os.environ.get("LLM_MAX_TOKENS", "2048")),
    )


def get_llm_provider(
    provider_type: Optional[str] = None,
    config: Optional[ProviderConfig] = None,
) -> LLMProvider:
    """
    Get configured LLM provider based on environment or explicit type.

    Provider selection priority:
    1. Explicit provider_type parameter
    2. LLM_PROVIDER environment variable
    3. Default to "ollama" for local development

    Args:
        provider_type: Explicit provider type (ollama, anthropic, openai)
        config: Optional provider config. If not provided, built from env vars.

    Returns:
        Configured LLMProvider instance

    Raises:
        ValueError: If provider type is unknown

    Examples:
        # Use environment defaults
        provider = get_llm_provider()

        # Explicit provider
        provider = get_llm_provider("anthropic")

        # With custom config
        config = ProviderConfig(api_key="...", model="claude-3-5-sonnet")
        provider = get_llm_provider("anthropic", config)
    """
    provider = provider_type or os.environ.get("LLM_PROVIDER", ProviderType.OLLAMA)

    if config is None:
        config = get_provider_config()

    if provider == ProviderType.OLLAMA:
        from .ollama import OllamaProvider

        # Ollama can use default config
        if not config.model:
            ollama_config = None
        else:
            ollama_config = config

        logger.info(f"Using Ollama provider: {config.model or 'default model'}")
        return OllamaProvider(ollama_config)

    elif provider == ProviderType.ANTHROPIC:
        from .anthropic import AnthropicProvider

        # Anthropic requires API key
        if not config.api_key:
            config.api_key = os.environ.get("ANTHROPIC_API_KEY", "")

        if not config.api_key:
            raise ValueError(
                "Anthropic provider requires ANTHROPIC_API_KEY or LLM_API_KEY"
            )

        # Set default model if not specified
        if not config.model:
            config.model = "claude-3-5-sonnet-20241022"

        logger.info(f"Using Anthropic provider: {config.model}")
        return AnthropicProvider(config)

    elif provider == ProviderType.OPENAI:
        # OpenAI support is planned but not yet implemented
        raise NotImplementedError(
            "OpenAI provider not yet implemented. Use 'ollama' or 'anthropic'."
        )

    else:
        raise ValueError(
            f"Unknown LLM provider: {provider}. "
            f"Supported: {ProviderType.OLLAMA}, {ProviderType.ANTHROPIC}"
        )


async def get_healthy_provider(
    preferred: Optional[str] = None,
    fallback_chain: Optional[list[str]] = None,
) -> LLMProvider:
    """
    Get a healthy LLM provider, with fallback support.

    Tries providers in order until one is healthy. Useful for ensuring
    availability when local Ollama might be down.

    Args:
        preferred: Preferred provider type
        fallback_chain: List of providers to try in order.
                       Defaults to ["ollama", "anthropic"]

    Returns:
        First healthy LLMProvider

    Raises:
        RuntimeError: If no providers are healthy
    """
    chain = fallback_chain or [ProviderType.OLLAMA, ProviderType.ANTHROPIC]

    if preferred:
        # Put preferred at front of chain
        chain = [preferred] + [p for p in chain if p != preferred]

    for provider_type in chain:
        try:
            provider = get_llm_provider(provider_type)

            # Check health for providers that support it
            if hasattr(provider, "check_health"):
                is_healthy = await provider.check_health()
                if is_healthy:
                    logger.info(f"Provider {provider_type} is healthy")
                    return provider
                else:
                    logger.warning(f"Provider {provider_type} health check failed")
                    continue
            else:
                # Assume healthy if no health check
                return provider

        except Exception as e:
            logger.warning(f"Failed to initialize {provider_type}: {e}")
            continue

    raise RuntimeError(
        f"No healthy LLM providers available. Tried: {chain}"
    )


__all__ = [
    "ProviderType",
    "get_provider_config",
    "get_llm_provider",
    "get_healthy_provider",
]
