"""
Rate Limiter for LLM API Calls

Provides token bucket rate limiting to prevent exceeding API quotas
and manage costs. Supports both requests-per-minute and tokens-per-minute limits.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import ray
from ray.actor import ActorHandle

logger = logging.getLogger(__name__)

ACTOR_NAME = "rate_limiter"
ACTOR_NAMESPACE = "llmmud"


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""

    # Requests per minute
    requests_per_minute: int = 60

    # Tokens per minute (input + output)
    tokens_per_minute: int = 100000

    # Maximum burst size (requests)
    burst_size: int = 10

    # Cost tracking
    cost_per_1k_input_tokens: float = 0.003
    cost_per_1k_output_tokens: float = 0.015

    # Budget limits (optional)
    hourly_cost_limit: Optional[float] = None
    daily_cost_limit: Optional[float] = None


@dataclass
class UsageStats:
    """Usage statistics for a time period."""

    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost: float = 0.0
    period_start: float = field(default_factory=time.time)

    def reset(self) -> None:
        """Reset stats for a new period."""
        self.requests = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_cost = 0.0
        self.period_start = time.time()


@ray.remote
class RateLimiter:
    """
    Ray actor for rate limiting LLM API calls.

    Uses a token bucket algorithm with separate buckets for
    request count and token count. Also tracks costs and can
    enforce budget limits.

    Usage:
        limiter = get_rate_limiter()
        await limiter.acquire.remote()  # Wait for permit
        # ... make API call ...
        await limiter.record_usage.remote(input_tokens=100, output_tokens=500)
    """

    def __init__(self, config: Optional[RateLimitConfig] = None):
        self._config = config or RateLimitConfig()

        # Token bucket state for requests
        self._request_tokens = float(self._config.burst_size)
        self._request_refill_rate = self._config.requests_per_minute / 60.0
        self._last_request_refill = time.time()

        # Token bucket state for API tokens
        self._api_tokens = float(self._config.tokens_per_minute)
        self._token_refill_rate = self._config.tokens_per_minute / 60.0
        self._last_token_refill = time.time()

        # Usage tracking
        self._hourly_stats = UsageStats()
        self._daily_stats = UsageStats()
        self._total_stats = UsageStats()

        # Lock for concurrent access
        self._acquiring = False

        logger.info(
            f"RateLimiter initialized: {self._config.requests_per_minute} RPM, "
            f"{self._config.tokens_per_minute} TPM"
        )

    def _refill_buckets(self) -> None:
        """Refill token buckets based on elapsed time."""
        now = time.time()

        # Refill request bucket
        elapsed = now - self._last_request_refill
        self._request_tokens = min(
            self._config.burst_size, self._request_tokens + elapsed * self._request_refill_rate
        )
        self._last_request_refill = now

        # Refill API token bucket
        elapsed = now - self._last_token_refill
        self._api_tokens = min(
            self._config.tokens_per_minute, self._api_tokens + elapsed * self._token_refill_rate
        )
        self._last_token_refill = now

    def _check_budget_limits(self) -> Optional[str]:
        """Check if any budget limits have been exceeded. Returns error message if so."""
        now = time.time()

        # Check hourly limit
        if self._config.hourly_cost_limit:
            if now - self._hourly_stats.period_start >= 3600:
                self._hourly_stats.reset()
            if self._hourly_stats.total_cost >= self._config.hourly_cost_limit:
                return f"Hourly cost limit (${self._config.hourly_cost_limit}) exceeded"

        # Check daily limit
        if self._config.daily_cost_limit:
            if now - self._daily_stats.period_start >= 86400:
                self._daily_stats.reset()
            if self._daily_stats.total_cost >= self._config.daily_cost_limit:
                return f"Daily cost limit (${self._config.daily_cost_limit}) exceeded"

        return None

    async def acquire(self, estimated_tokens: int = 1000) -> bool:
        """
        Acquire a permit to make an API call.

        Blocks until a permit is available or budget is exceeded.

        Args:
            estimated_tokens: Estimated tokens for this request (for token limiting)

        Returns:
            True if permit acquired, False if budget exceeded
        """
        # Check budget limits first
        budget_error = self._check_budget_limits()
        if budget_error:
            logger.warning(budget_error)
            return False

        # Wait for token buckets to have capacity
        while True:
            self._refill_buckets()

            if self._request_tokens >= 1 and self._api_tokens >= estimated_tokens:
                self._request_tokens -= 1
                self._api_tokens -= estimated_tokens
                return True

            # Calculate wait time
            wait_for_request = (
                (1 - self._request_tokens) / self._request_refill_rate
                if self._request_tokens < 1
                else 0
            )
            wait_for_tokens = (
                (estimated_tokens - self._api_tokens) / self._token_refill_rate
                if self._api_tokens < estimated_tokens
                else 0
            )
            wait_time = max(wait_for_request, wait_for_tokens, 0.1)

            logger.debug(f"Rate limit: waiting {wait_time:.2f}s")
            await asyncio.sleep(min(wait_time, 5.0))

    async def record_usage(self, input_tokens: int, output_tokens: int) -> None:
        """
        Record actual token usage after a request completes.

        Updates usage statistics and cost tracking.
        """
        cost = (input_tokens / 1000 * self._config.cost_per_1k_input_tokens) + (
            output_tokens / 1000 * self._config.cost_per_1k_output_tokens
        )

        # Update all stats
        for stats in [self._hourly_stats, self._daily_stats, self._total_stats]:
            stats.requests += 1
            stats.input_tokens += input_tokens
            stats.output_tokens += output_tokens
            stats.total_cost += cost

        logger.debug(f"Recorded usage: {input_tokens} in, {output_tokens} out, ${cost:.4f}")

    async def get_stats(self) -> dict:
        """Get current usage statistics."""
        return {
            "hourly": {
                "requests": self._hourly_stats.requests,
                "input_tokens": self._hourly_stats.input_tokens,
                "output_tokens": self._hourly_stats.output_tokens,
                "cost": self._hourly_stats.total_cost,
            },
            "daily": {
                "requests": self._daily_stats.requests,
                "input_tokens": self._daily_stats.input_tokens,
                "output_tokens": self._daily_stats.output_tokens,
                "cost": self._daily_stats.total_cost,
            },
            "total": {
                "requests": self._total_stats.requests,
                "input_tokens": self._total_stats.input_tokens,
                "output_tokens": self._total_stats.output_tokens,
                "cost": self._total_stats.total_cost,
            },
            "current_capacity": {
                "request_tokens": self._request_tokens,
                "api_tokens": self._api_tokens,
            },
        }

    async def update_config(self, config: RateLimitConfig) -> None:
        """Update rate limit configuration."""
        self._config = config
        self._request_refill_rate = config.requests_per_minute / 60.0
        self._token_refill_rate = config.tokens_per_minute / 60.0
        logger.info(f"Rate limiter config updated: {config.requests_per_minute} RPM")


# =============================================================================
# Actor Lifecycle Functions
# =============================================================================


def start_rate_limiter(config: Optional[RateLimitConfig] = None) -> ActorHandle:
    """Start the rate limiter actor."""
    actor: ActorHandle = RateLimiter.options(
        name=ACTOR_NAME,
        namespace=ACTOR_NAMESPACE,
        lifetime="detached",
    ).remote(
        config
    )  # type: ignore[assignment]
    logger.info(f"Started RateLimiter as {ACTOR_NAMESPACE}/{ACTOR_NAME}")
    return actor


def get_rate_limiter() -> ActorHandle:
    """Get the rate limiter actor."""
    return ray.get_actor(ACTOR_NAME, namespace=ACTOR_NAMESPACE)


def rate_limiter_exists() -> bool:
    """Check if the rate limiter actor exists."""
    try:
        ray.get_actor(ACTOR_NAME, namespace=ACTOR_NAMESPACE)
        return True
    except ValueError:
        return False


def stop_rate_limiter() -> bool:
    """Stop the rate limiter actor."""
    try:
        actor = ray.get_actor(ACTOR_NAME, namespace=ACTOR_NAMESPACE)
        ray.kill(actor)
        logger.info("Stopped RateLimiter")
        return True
    except ValueError:
        return False
