"""
AI Providers Package

This package provides unified AI provider integrations for the PIM system.
It supports multiple AI providers with a consistent interface for generating
product enrichment content.

Supported Providers:
    - Anthropic (Claude) - Claude 3 models
    - OpenAI (GPT) - GPT-4, GPT-4 Turbo, GPT-3.5
    - Google Gemini - Gemini Pro, Gemini Flash
    - Azure OpenAI - Azure-hosted GPT models
    - AWS Bedrock (via Anthropic adapter)
    - Mock (for testing)

Usage:
    Basic usage with automatic API key lookup from PIM Settings:

        from frappe_pim.pim.utils.ai_providers import get_provider

        # Get a provider (API key from PIM Settings)
        provider = get_provider("Anthropic")

        # Generate content
        response = provider.generate(
            system_prompt="You are a product copywriter.",
            user_prompt="Write a description for wireless headphones."
        )

        if response.success:
            print(response.content)
            print(f"Tokens used: {response.total_tokens}")
            print(f"Cost: ${response.estimated_cost:.4f}")
        else:
            print(f"Error: {response.error_message}")

    With explicit API key:

        provider = get_provider(
            "OpenAI",
            api_key="sk-...",
            model="gpt-4-turbo-preview",
            temperature=0.5
        )

    Using the factory functions directly:

        from frappe_pim.pim.utils.ai_providers import create_anthropic_provider

        provider = create_anthropic_provider(
            api_key="sk-ant-...",
            model="claude-3-sonnet-20240229",
            max_tokens=4096
        )

Configuration:
    API keys can be configured in PIM Settings (recommended for security)
    or passed directly to the provider. Keys are stored encrypted as
    Password fields in PIM Settings.

    Required packages (install as needed):
        - anthropic: pip install anthropic
        - openai: pip install openai
        - google-generativeai: pip install google-generativeai

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

from typing import Optional, Dict, Any, Type, List

# Import base classes and utilities
from .base import (
    BaseAIProvider,
    ProviderConfig,
    AIMessage,
    AIResponse,
    MockAIProvider,
    get_api_key_from_settings,
    get_provider_config_from_settings,
    validate_api_key,
    parse_json_response
)

# Provider registry
_PROVIDERS: Dict[str, Type[BaseAIProvider]] = {}


def _register_providers():
    """Register all available providers"""
    global _PROVIDERS

    # Import providers lazily to avoid import errors
    # if optional packages are not installed

    try:
        from .anthropic import AnthropicProvider
        _PROVIDERS["Anthropic"] = AnthropicProvider
    except ImportError:
        pass

    try:
        from .openai_provider import OpenAIProvider, AzureOpenAIProvider
        _PROVIDERS["OpenAI"] = OpenAIProvider
        _PROVIDERS["Azure OpenAI"] = AzureOpenAIProvider
    except ImportError:
        pass

    try:
        from .gemini import GeminiProvider
        _PROVIDERS["Google Gemini"] = GeminiProvider
    except ImportError:
        pass

    # Mock provider is always available
    _PROVIDERS["Mock"] = MockAIProvider


# Register providers on module load
_register_providers()


def get_provider(
    provider_name: str,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    **kwargs
) -> BaseAIProvider:
    """Get an AI provider instance

    This is the main factory function for creating AI provider instances.
    It handles API key retrieval from PIM Settings if not provided.

    Args:
        provider_name: Name of the provider
            - "Anthropic" - Claude models
            - "OpenAI" - GPT models
            - "Google Gemini" - Gemini models
            - "Azure OpenAI" - Azure-hosted GPT
            - "Mock" - Mock provider for testing
        api_key: API key (optional, retrieved from PIM Settings if not provided)
        model: Model name (optional, uses provider default if not provided)
        **kwargs: Additional configuration options:
            - temperature: Sampling temperature (0.0-1.0)
            - max_tokens: Maximum response tokens
            - top_p: Top-p sampling parameter
            - timeout: Request timeout in seconds
            - max_retries: Number of retries on failure
            - retry_delay: Initial delay between retries
            - organization: Organization ID (OpenAI)
            - base_url: Custom API endpoint

    Returns:
        Configured AI provider instance

    Raises:
        ValueError: If provider is not supported or API key is missing

    Example:
        >>> provider = get_provider("Anthropic", temperature=0.5)
        >>> response = provider.generate(
        ...     system_prompt="You are helpful.",
        ...     user_prompt="Describe a product."
        ... )
    """
    # Normalize provider name
    provider_name = _normalize_provider_name(provider_name)

    if provider_name not in _PROVIDERS:
        available = ", ".join(_PROVIDERS.keys())
        raise ValueError(
            f"Provider '{provider_name}' is not supported. "
            f"Available providers: {available}"
        )

    # Get API key from settings if not provided
    if not api_key and provider_name != "Mock":
        api_key = get_api_key_from_settings(provider_name)

    if not api_key and provider_name != "Mock":
        raise ValueError(
            f"API key is required for {provider_name}. "
            "Set it in PIM Settings or pass it directly."
        )

    # Get provider-specific settings
    settings_config = get_provider_config_from_settings(provider_name)

    # Build configuration
    config = ProviderConfig(
        api_key=api_key or "mock-key",
        model=model or settings_config.get("model") or "",
        temperature=kwargs.get("temperature", settings_config.get("temperature", 0.7)),
        max_tokens=kwargs.get("max_tokens", settings_config.get("max_tokens", 4096)),
        top_p=kwargs.get("top_p", settings_config.get("top_p", 1.0)),
        timeout=kwargs.get("timeout", settings_config.get("timeout", 120)),
        max_retries=kwargs.get("max_retries", 3),
        retry_delay=kwargs.get("retry_delay", 1.0),
        organization=kwargs.get("organization", settings_config.get("organization")),
        base_url=kwargs.get("base_url", settings_config.get("base_url")),
        extra_params=kwargs.get("extra_params", settings_config.get("extra_params"))
    )

    # Create and return provider
    provider_class = _PROVIDERS[provider_name]
    return provider_class(config)


def _normalize_provider_name(name: str) -> str:
    """Normalize provider name to standard format

    Args:
        name: Provider name (case-insensitive)

    Returns:
        Normalized provider name
    """
    name_lower = name.lower().strip()

    # Map common variations
    mappings = {
        "anthropic": "Anthropic",
        "claude": "Anthropic",
        "openai": "OpenAI",
        "gpt": "OpenAI",
        "gpt-4": "OpenAI",
        "gpt4": "OpenAI",
        "gemini": "Google Gemini",
        "google": "Google Gemini",
        "google gemini": "Google Gemini",
        "azure": "Azure OpenAI",
        "azure openai": "Azure OpenAI",
        "azureopenai": "Azure OpenAI",
        "mock": "Mock",
        "test": "Mock"
    }

    return mappings.get(name_lower, name)


def get_available_providers() -> List[str]:
    """Get list of available providers

    Returns:
        List of provider names that are properly installed
    """
    return list(_PROVIDERS.keys())


def get_provider_info(provider_name: str) -> Dict[str, Any]:
    """Get information about a provider

    Args:
        provider_name: Name of the provider

    Returns:
        Dict with provider information
    """
    provider_name = _normalize_provider_name(provider_name)

    if provider_name not in _PROVIDERS:
        return {"error": f"Provider '{provider_name}' not found"}

    provider_class = _PROVIDERS[provider_name]

    return {
        "name": provider_class.name,
        "default_model": provider_class.default_model,
        "supported_models": provider_class.supported_models,
        "pricing": provider_class.pricing
    }


def test_provider(
    provider_name: str,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """Test a provider connection

    Args:
        provider_name: Name of the provider
        api_key: API key (optional)

    Returns:
        Dict with test results
    """
    try:
        provider = get_provider(provider_name, api_key=api_key)
        return provider.health_check()
    except Exception as e:
        return {
            "provider": provider_name,
            "status": "error",
            "error": str(e)
        }


# Convenience factory functions
def create_anthropic_provider(
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    **kwargs
):
    """Create an Anthropic provider

    See :func:`get_provider` for parameter documentation.
    """
    return get_provider("Anthropic", api_key=api_key, model=model, **kwargs)


def create_openai_provider(
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    **kwargs
):
    """Create an OpenAI provider

    See :func:`get_provider` for parameter documentation.
    """
    return get_provider("OpenAI", api_key=api_key, model=model, **kwargs)


def create_gemini_provider(
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    **kwargs
):
    """Create a Gemini provider

    See :func:`get_provider` for parameter documentation.
    """
    return get_provider("Google Gemini", api_key=api_key, model=model, **kwargs)


def create_azure_openai_provider(
    api_key: Optional[str] = None,
    deployment: Optional[str] = None,
    endpoint: Optional[str] = None,
    **kwargs
):
    """Create an Azure OpenAI provider

    Args:
        api_key: Azure OpenAI API key
        deployment: Deployment name
        endpoint: Azure OpenAI endpoint URL
        **kwargs: Additional configuration

    See :func:`get_provider` for additional parameter documentation.
    """
    return get_provider(
        "Azure OpenAI",
        api_key=api_key,
        model=deployment,
        base_url=endpoint,
        **kwargs
    )


def create_mock_provider(mock_response: str = "This is a mock response."):
    """Create a mock provider for testing

    Args:
        mock_response: Response to return

    Returns:
        MockAIProvider instance
    """
    return MockAIProvider(mock_response=mock_response)


# Whitelisted API functions for Frappe
def get_providers_api():
    """Frappe API to get available providers"""
    try:
        import frappe

        @frappe.whitelist()
        def get_ai_providers():
            """Get list of available AI providers

            Returns:
                List of provider info dictionaries
            """
            providers = []
            for name in get_available_providers():
                info = get_provider_info(name)
                info["name"] = name
                providers.append(info)
            return providers

        return get_ai_providers
    except ImportError:
        return None


def test_provider_api():
    """Frappe API to test provider connection"""
    try:
        import frappe

        @frappe.whitelist()
        def test_ai_provider(provider: str, api_key: Optional[str] = None):
            """Test AI provider connection

            Args:
                provider: Provider name
                api_key: Optional API key override

            Returns:
                Dict with test results
            """
            return test_provider(provider, api_key)

        return test_ai_provider
    except ImportError:
        return None


# Export public API
__all__ = [
    # Base classes
    "BaseAIProvider",
    "ProviderConfig",
    "AIMessage",
    "AIResponse",
    "MockAIProvider",
    # Factory functions
    "get_provider",
    "create_anthropic_provider",
    "create_openai_provider",
    "create_gemini_provider",
    "create_azure_openai_provider",
    "create_mock_provider",
    # Discovery functions
    "get_available_providers",
    "get_provider_info",
    "test_provider",
    # Utilities
    "get_api_key_from_settings",
    "get_provider_config_from_settings",
    "validate_api_key",
    "parse_json_response"
]
