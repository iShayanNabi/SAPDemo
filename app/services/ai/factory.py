"""Factory that resolves the configured AI provider.

Resolution order:

1. an explicitly requested provider name (used by tests);
2. ``settings.ai_provider`` when the matching API key exists;
3. the mock provider.

Step 3 is what makes "runs without API keys" a hard guarantee rather than a
hope: if anything is missing or misconfigured, the caller still gets a working
provider, just a mock one.
"""

from __future__ import annotations

from app.core.config import AIProviderName, settings
from app.core.exceptions import AIProviderError
from app.core.logging import get_logger
from app.services.ai.base import AIProvider
from app.services.ai.mock_provider import MockAIProvider
from app.services.ai.providers import AnthropicProvider, OpenAIProvider

logger = get_logger(__name__)


def get_ai_provider(provider_name: AIProviderName | str | None = None) -> AIProvider:
    """Return an AI provider instance, falling back to the mock provider."""
    requested = (provider_name or settings.resolved_ai_provider()).lower()

    if requested == "anthropic":
        try:
            return AnthropicProvider()
        except AIProviderError as exc:
            logger.warning("Anthropic provider unavailable (%s); using mock mode.", exc.message)
            return MockAIProvider()

    if requested == "openai":
        try:
            return OpenAIProvider()
        except AIProviderError as exc:
            logger.warning("OpenAI provider unavailable (%s); using mock mode.", exc.message)
            return MockAIProvider()

    if requested != "mock":
        logger.warning("Unknown AI provider '%s'; using mock mode.", requested)
    return MockAIProvider()


def describe_active_provider() -> dict[str, object]:
    """Return a log/UI-safe description of the active provider (never the key)."""
    resolved = settings.resolved_ai_provider()
    return {
        "configured_provider": settings.ai_provider,
        "resolved_provider": resolved,
        "is_mock": resolved == "mock",
        "ai_enabled": settings.ai_enabled,
        "model": {
            "anthropic": settings.anthropic_model,
            "openai": settings.openai_model,
            "mock": "mock-deterministic-v1",
        }[resolved],
        "timeout_seconds": settings.ai_timeout_seconds,
        "max_retries": settings.ai_max_retries,
    }
