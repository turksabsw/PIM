"""
Base AI Provider Interface

This module defines the abstract base class for AI providers used in PIM
enrichment jobs. All provider implementations must inherit from this class
and implement the required methods.

The base class provides:
    - Common configuration handling
    - Token counting utilities
    - Cost estimation
    - Error handling
    - Rate limiting support
    - Retry logic with exponential backoff

Supported providers:
    - Anthropic (Claude)
    - OpenAI (GPT)
    - Google Gemini
    - Azure OpenAI
    - AWS Bedrock

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List, Tuple, Union
from dataclasses import dataclass
from datetime import datetime
import time
import json


@dataclass
class AIMessage:
    """Represents a message in a conversation"""
    role: str  # 'system', 'user', 'assistant'
    content: str


@dataclass
class AIResponse:
    """Standardized AI response format"""
    success: bool
    content: str
    raw_response: Optional[Dict[str, Any]] = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    model: str = ""
    finish_reason: str = ""
    error_message: Optional[str] = None
    latency_ms: int = 0
    estimated_cost: float = 0.0


@dataclass
class ProviderConfig:
    """AI Provider configuration"""
    api_key: str
    model: str
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 1.0
    timeout: int = 120
    max_retries: int = 3
    retry_delay: float = 1.0
    organization: Optional[str] = None
    base_url: Optional[str] = None
    extra_params: Optional[Dict[str, Any]] = None


class BaseAIProvider(ABC):
    """Abstract base class for AI providers

    All AI provider implementations must inherit from this class and
    implement the required abstract methods.

    Attributes:
        config: Provider configuration
        name: Provider name (e.g., 'Anthropic', 'OpenAI')
        default_model: Default model to use
        supported_models: List of supported model names
        pricing: Token pricing per million tokens

    Example:
        >>> provider = AnthropicProvider(config)
        >>> response = provider.generate(
        ...     system_prompt="You are a product copywriter.",
        ...     user_prompt="Write a description for a wireless headphone."
        ... )
        >>> print(response.content)
    """

    name: str = "Base"
    default_model: str = ""
    supported_models: List[str] = []
    pricing: Dict[str, Dict[str, float]] = {}

    def __init__(self, config: ProviderConfig):
        """Initialize the AI provider

        Args:
            config: Provider configuration
        """
        self.config = config
        self._validate_config()
        self._client = None
        self._last_request_time = 0
        self._request_count = 0

    def _validate_config(self):
        """Validate the configuration"""
        if not self.config.api_key:
            raise ValueError(f"{self.name} API key is required")

        if self.config.model and self.supported_models:
            if self.config.model not in self.supported_models:
                # Don't raise error, just log warning
                self._log_warning(
                    f"Model '{self.config.model}' may not be supported. "
                    f"Supported models: {', '.join(self.supported_models)}"
                )

    def _log_warning(self, message: str):
        """Log a warning message"""
        try:
            import frappe
            frappe.log_error(message=message, title=f"{self.name} Provider Warning")
        except ImportError:
            pass

    def _log_error(self, message: str, exception: Optional[Exception] = None):
        """Log an error message"""
        try:
            import frappe
            error_msg = message
            if exception:
                error_msg = f"{message}: {str(exception)}"
            frappe.log_error(message=error_msg, title=f"{self.name} Provider Error")
        except ImportError:
            pass

    @abstractmethod
    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        **kwargs
    ) -> AIResponse:
        """Generate a response from the AI model

        Args:
            system_prompt: System/instruction prompt
            user_prompt: User message/prompt
            **kwargs: Additional provider-specific parameters

        Returns:
            AIResponse with the generated content
        """
        pass

    @abstractmethod
    def generate_with_messages(
        self,
        messages: List[AIMessage],
        **kwargs
    ) -> AIResponse:
        """Generate a response with full conversation history

        Args:
            messages: List of conversation messages
            **kwargs: Additional provider-specific parameters

        Returns:
            AIResponse with the generated content
        """
        pass

    @abstractmethod
    def _initialize_client(self):
        """Initialize the API client"""
        pass

    def get_client(self):
        """Get or initialize the API client"""
        if self._client is None:
            self._initialize_client()
        return self._client

    def _build_messages(
        self,
        system_prompt: str,
        user_prompt: str
    ) -> List[AIMessage]:
        """Build message list from prompts

        Args:
            system_prompt: System prompt
            user_prompt: User prompt

        Returns:
            List of AIMessage objects
        """
        messages = []
        if system_prompt:
            messages.append(AIMessage(role="system", content=system_prompt))
        messages.append(AIMessage(role="user", content=user_prompt))
        return messages

    def _with_retry(
        self,
        func: callable,
        *args,
        **kwargs
    ) -> Any:
        """Execute a function with retry logic

        Uses exponential backoff for retries.

        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result

        Raises:
            Last exception if all retries fail
        """
        last_exception = None
        retry_delay = self.config.retry_delay

        for attempt in range(self.config.max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                error_str = str(e).lower()

                # Don't retry on authentication errors
                if "authentication" in error_str or "api key" in error_str:
                    raise

                # Don't retry on invalid request errors
                if "invalid" in error_str and "request" in error_str:
                    raise

                # Check if rate limited
                if "rate" in error_str and "limit" in error_str:
                    # Wait longer for rate limits
                    retry_delay = retry_delay * 2

                if attempt < self.config.max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff

        raise last_exception

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count for text

        Uses a simple heuristic: ~4 characters per token for English.
        Override in subclasses for more accurate counting.

        Args:
            text: Text to estimate tokens for

        Returns:
            Estimated token count
        """
        # Simple estimation: ~4 characters per token for English
        return len(text) // 4 + 1

    def estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        model: Optional[str] = None
    ) -> float:
        """Estimate API cost based on token usage

        Args:
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            model: Model name (uses config model if not provided)

        Returns:
            Estimated cost in USD
        """
        model = model or self.config.model

        if model not in self.pricing:
            # Use default pricing if model not found
            model = next(iter(self.pricing.keys()), None)
            if not model:
                return 0.0

        rates = self.pricing.get(model, {"input": 0.0, "output": 0.0})
        input_cost = (input_tokens / 1_000_000) * rates.get("input", 0.0)
        output_cost = (output_tokens / 1_000_000) * rates.get("output", 0.0)

        return round(input_cost + output_cost, 6)

    def check_rate_limit(self):
        """Check and enforce rate limiting

        Ensures minimum time between requests.
        Override in subclasses for provider-specific rate limiting.
        """
        current_time = time.time()
        min_interval = 0.1  # 100ms minimum between requests

        elapsed = current_time - self._last_request_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)

        self._last_request_time = time.time()
        self._request_count += 1

    def get_model_info(self, model: Optional[str] = None) -> Dict[str, Any]:
        """Get information about a model

        Args:
            model: Model name (uses config model if not provided)

        Returns:
            Dict with model information
        """
        model = model or self.config.model
        return {
            "provider": self.name,
            "model": model,
            "is_supported": model in self.supported_models if self.supported_models else True,
            "pricing": self.pricing.get(model, {}),
        }

    def health_check(self) -> Dict[str, Any]:
        """Perform a health check on the provider

        Returns:
            Dict with health check results
        """
        result = {
            "provider": self.name,
            "status": "unknown",
            "model": self.config.model,
            "timestamp": datetime.now().isoformat(),
            "error": None
        }

        try:
            # Try a minimal generation to verify connectivity
            response = self.generate(
                system_prompt="",
                user_prompt="Say OK"
            )
            result["status"] = "healthy" if response.success else "unhealthy"
            if not response.success:
                result["error"] = response.error_message
        except Exception as e:
            result["status"] = "unhealthy"
            result["error"] = str(e)

        return result


class MockAIProvider(BaseAIProvider):
    """Mock AI provider for testing

    Returns predefined responses without making actual API calls.
    Useful for testing and development.
    """

    name = "Mock"
    default_model = "mock-model"
    supported_models = ["mock-model"]
    pricing = {"mock-model": {"input": 0.0, "output": 0.0}}

    def __init__(
        self,
        config: Optional[ProviderConfig] = None,
        mock_response: str = "This is a mock response."
    ):
        """Initialize mock provider

        Args:
            config: Optional provider config
            mock_response: Response to return
        """
        if config is None:
            config = ProviderConfig(
                api_key="mock-key",
                model="mock-model"
            )
        super().__init__(config)
        self.mock_response = mock_response

    def _initialize_client(self):
        """Initialize mock client"""
        self._client = "mock"

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        **kwargs
    ) -> AIResponse:
        """Generate mock response"""
        input_tokens = self.estimate_tokens(system_prompt + user_prompt)
        output_tokens = self.estimate_tokens(self.mock_response)

        return AIResponse(
            success=True,
            content=self.mock_response,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            model=self.config.model,
            finish_reason="stop",
            latency_ms=10
        )

    def generate_with_messages(
        self,
        messages: List[AIMessage],
        **kwargs
    ) -> AIResponse:
        """Generate mock response from messages"""
        total_content = " ".join([m.content for m in messages])
        input_tokens = self.estimate_tokens(total_content)
        output_tokens = self.estimate_tokens(self.mock_response)

        return AIResponse(
            success=True,
            content=self.mock_response,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            model=self.config.model,
            finish_reason="stop",
            latency_ms=10
        )


# Utility Functions

def get_api_key_from_settings(provider: str) -> Optional[str]:
    """Get API key for a provider from PIM Settings

    Args:
        provider: Provider name (e.g., 'Anthropic', 'OpenAI')

    Returns:
        API key string or None
    """
    try:
        import frappe

        # Try to get from PIM Settings
        settings = frappe.get_single("PIM Settings")

        key_field_map = {
            "Anthropic": "anthropic_api_key",
            "OpenAI": "openai_api_key",
            "Google Gemini": "gemini_api_key",
            "Azure OpenAI": "azure_openai_api_key",
            "AWS Bedrock": "aws_access_key_id"  # AWS uses different auth
        }

        field = key_field_map.get(provider)
        if field and hasattr(settings, field):
            key = getattr(settings, field)
            # Decrypt if it's a password field
            if key:
                return settings.get_password(field) if hasattr(settings, 'get_password') else key

        # Fallback to site_config
        site_config_keys = {
            "Anthropic": "anthropic_api_key",
            "OpenAI": "openai_api_key",
            "Google Gemini": "google_api_key",
            "Azure OpenAI": "azure_openai_key",
            "AWS Bedrock": "aws_access_key"
        }

        config_key = site_config_keys.get(provider)
        if config_key:
            return frappe.conf.get(config_key)

        return None

    except Exception:
        return None


def get_provider_config_from_settings(provider: str) -> Dict[str, Any]:
    """Get full provider configuration from PIM Settings

    Args:
        provider: Provider name

    Returns:
        Dict with provider configuration
    """
    try:
        import frappe

        settings = frappe.get_single("PIM Settings")

        # Base config
        config = {
            "api_key": get_api_key_from_settings(provider),
            "model": None,
            "temperature": 0.7,
            "max_tokens": 4096,
            "timeout": 120
        }

        # Provider-specific settings
        if provider == "Anthropic":
            if hasattr(settings, "anthropic_default_model"):
                config["model"] = settings.anthropic_default_model
        elif provider == "OpenAI":
            if hasattr(settings, "openai_default_model"):
                config["model"] = settings.openai_default_model
            if hasattr(settings, "openai_organization"):
                config["organization"] = settings.openai_organization
        elif provider == "Google Gemini":
            if hasattr(settings, "gemini_default_model"):
                config["model"] = settings.gemini_default_model
        elif provider == "Azure OpenAI":
            if hasattr(settings, "azure_openai_endpoint"):
                config["base_url"] = settings.azure_openai_endpoint
            if hasattr(settings, "azure_openai_deployment"):
                config["model"] = settings.azure_openai_deployment

        # Global settings
        if hasattr(settings, "ai_default_temperature"):
            config["temperature"] = settings.ai_default_temperature
        if hasattr(settings, "ai_default_max_tokens"):
            config["max_tokens"] = settings.ai_default_max_tokens
        if hasattr(settings, "ai_request_timeout"):
            config["timeout"] = settings.ai_request_timeout

        return config

    except Exception:
        return {"api_key": None}


def validate_api_key(provider: str, api_key: str) -> Tuple[bool, str]:
    """Validate an API key for a provider

    Args:
        provider: Provider name
        api_key: API key to validate

    Returns:
        Tuple of (is_valid, message)
    """
    if not api_key:
        return False, "API key is required"

    # Basic format validation
    if provider == "Anthropic":
        if not api_key.startswith("sk-ant-"):
            return False, "Anthropic API keys should start with 'sk-ant-'"
    elif provider == "OpenAI":
        if not api_key.startswith(("sk-", "sk-proj-")):
            return False, "OpenAI API keys should start with 'sk-'"
    elif provider == "Google Gemini":
        if len(api_key) < 30:
            return False, "Invalid Google API key format"

    return True, "API key format is valid"


def parse_json_response(content: str) -> Tuple[Optional[Dict], str]:
    """Parse JSON from AI response content

    Handles cases where the AI includes markdown code blocks
    or extra text around the JSON.

    Args:
        content: Raw AI response content

    Returns:
        Tuple of (parsed_dict, error_message)
    """
    # Try direct parse first
    try:
        return json.loads(content), ""
    except json.JSONDecodeError:
        pass

    # Try to extract JSON from markdown code blocks
    import re

    # Pattern for JSON in code blocks
    patterns = [
        r'```json\s*([\s\S]*?)\s*```',  # ```json ... ```
        r'```\s*([\s\S]*?)\s*```',       # ``` ... ```
        r'\{[\s\S]*\}',                   # Raw object
        r'\[[\s\S]*\]'                    # Raw array
    ]

    for pattern in patterns:
        match = re.search(pattern, content)
        if match:
            try:
                json_str = match.group(1) if '```' in pattern else match.group(0)
                return json.loads(json_str.strip()), ""
            except json.JSONDecodeError:
                continue

    return None, "Could not parse JSON from response"
