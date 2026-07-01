"""
OpenAI (GPT) AI Provider

This module implements the OpenAI GPT AI provider for PIM enrichment jobs.
It supports GPT-4, GPT-4 Turbo, GPT-3.5 Turbo, and compatible models.

Features:
    - Full conversation support with system messages
    - Function/tool calling support
    - Token counting using tiktoken
    - Streaming support (optional)
    - Cost estimation based on current pricing
    - Azure OpenAI compatibility
    - Automatic retry with exponential backoff

Usage:
    from frappe_pim.pim.utils.ai_providers import get_provider

    provider = get_provider("OpenAI", api_key="sk-...")
    response = provider.generate(
        system_prompt="You are a product copywriter.",
        user_prompt="Write a description for wireless headphones."
    )
    print(response.content)

Note: Requires the 'openai' package to be installed:
    pip install openai

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

from typing import Optional, List, Dict, Any
import time

from .base import (
    BaseAIProvider,
    ProviderConfig,
    AIMessage,
    AIResponse
)


class OpenAIProvider(BaseAIProvider):
    """OpenAI GPT AI Provider

    Implements the BaseAIProvider interface for OpenAI's GPT models.

    Supported models:
        - gpt-4-turbo-preview (GPT-4 Turbo)
        - gpt-4-turbo (GPT-4 Turbo with vision)
        - gpt-4 (GPT-4)
        - gpt-4-32k (GPT-4 with 32k context)
        - gpt-3.5-turbo (ChatGPT)
        - gpt-3.5-turbo-16k (ChatGPT with 16k context)
        - gpt-4o (GPT-4 Omni)
        - gpt-4o-mini (GPT-4 Omni Mini)

    Attributes:
        name: "OpenAI"
        default_model: "gpt-4-turbo-preview"
        max_context_tokens: Maximum context window size

    Example:
        >>> config = ProviderConfig(
        ...     api_key="sk-...",
        ...     model="gpt-4-turbo-preview",
        ...     temperature=0.7,
        ...     max_tokens=4096
        ... )
        >>> provider = OpenAIProvider(config)
        >>> response = provider.generate(
        ...     system_prompt="You are helpful.",
        ...     user_prompt="Describe a product."
        ... )
    """

    name = "OpenAI"
    default_model = "gpt-4-turbo-preview"

    supported_models = [
        # GPT-4 Omni
        "gpt-4o",
        "gpt-4o-2024-05-13",
        "gpt-4o-2024-08-06",
        "gpt-4o-mini",
        "gpt-4o-mini-2024-07-18",
        # GPT-4 Turbo
        "gpt-4-turbo",
        "gpt-4-turbo-preview",
        "gpt-4-turbo-2024-04-09",
        "gpt-4-1106-preview",
        "gpt-4-0125-preview",
        # GPT-4
        "gpt-4",
        "gpt-4-0613",
        "gpt-4-32k",
        "gpt-4-32k-0613",
        # GPT-3.5 Turbo
        "gpt-3.5-turbo",
        "gpt-3.5-turbo-0125",
        "gpt-3.5-turbo-1106",
        "gpt-3.5-turbo-16k",
        "gpt-3.5-turbo-instruct"
    ]

    # Pricing per million tokens (as of 2024)
    pricing = {
        "gpt-4o": {"input": 5.0, "output": 15.0},
        "gpt-4o-2024-05-13": {"input": 5.0, "output": 15.0},
        "gpt-4o-2024-08-06": {"input": 2.5, "output": 10.0},
        "gpt-4o-mini": {"input": 0.15, "output": 0.6},
        "gpt-4o-mini-2024-07-18": {"input": 0.15, "output": 0.6},
        "gpt-4-turbo": {"input": 10.0, "output": 30.0},
        "gpt-4-turbo-preview": {"input": 10.0, "output": 30.0},
        "gpt-4-turbo-2024-04-09": {"input": 10.0, "output": 30.0},
        "gpt-4-1106-preview": {"input": 10.0, "output": 30.0},
        "gpt-4-0125-preview": {"input": 10.0, "output": 30.0},
        "gpt-4": {"input": 30.0, "output": 60.0},
        "gpt-4-0613": {"input": 30.0, "output": 60.0},
        "gpt-4-32k": {"input": 60.0, "output": 120.0},
        "gpt-4-32k-0613": {"input": 60.0, "output": 120.0},
        "gpt-3.5-turbo": {"input": 0.5, "output": 1.5},
        "gpt-3.5-turbo-0125": {"input": 0.5, "output": 1.5},
        "gpt-3.5-turbo-1106": {"input": 1.0, "output": 2.0},
        "gpt-3.5-turbo-16k": {"input": 3.0, "output": 4.0},
        "gpt-3.5-turbo-instruct": {"input": 1.5, "output": 2.0}
    }

    # Context window sizes
    context_windows = {
        "gpt-4o": 128000,
        "gpt-4o-2024-05-13": 128000,
        "gpt-4o-2024-08-06": 128000,
        "gpt-4o-mini": 128000,
        "gpt-4o-mini-2024-07-18": 128000,
        "gpt-4-turbo": 128000,
        "gpt-4-turbo-preview": 128000,
        "gpt-4-turbo-2024-04-09": 128000,
        "gpt-4-1106-preview": 128000,
        "gpt-4-0125-preview": 128000,
        "gpt-4": 8192,
        "gpt-4-0613": 8192,
        "gpt-4-32k": 32768,
        "gpt-4-32k-0613": 32768,
        "gpt-3.5-turbo": 16385,
        "gpt-3.5-turbo-0125": 16385,
        "gpt-3.5-turbo-1106": 16385,
        "gpt-3.5-turbo-16k": 16385,
        "gpt-3.5-turbo-instruct": 4096
    }

    def __init__(self, config: ProviderConfig):
        """Initialize OpenAI provider

        Args:
            config: Provider configuration
        """
        # Set default model if not specified
        if not config.model:
            config.model = self.default_model

        super().__init__(config)
        self.max_context_tokens = self.context_windows.get(
            config.model,
            128000
        )

    def _initialize_client(self):
        """Initialize the OpenAI client"""
        try:
            from openai import OpenAI

            client_kwargs = {
                "api_key": self.config.api_key,
                "timeout": self.config.timeout
            }

            if self.config.organization:
                client_kwargs["organization"] = self.config.organization

            if self.config.base_url:
                client_kwargs["base_url"] = self.config.base_url

            self._client = OpenAI(**client_kwargs)

        except ImportError:
            raise ImportError(
                "The 'openai' package is required for the OpenAI provider. "
                "Install it with: pip install openai"
            )

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        **kwargs
    ) -> AIResponse:
        """Generate a response using GPT

        Args:
            system_prompt: System/instruction prompt
            user_prompt: User message
            **kwargs: Additional parameters:
                - temperature: Override config temperature
                - max_tokens: Override config max_tokens
                - top_p: Top-p sampling parameter
                - frequency_penalty: Frequency penalty
                - presence_penalty: Presence penalty
                - stop: List of stop sequences
                - response_format: Response format (e.g., {"type": "json_object"})

        Returns:
            AIResponse with the generated content
        """
        messages = self._build_messages(system_prompt, user_prompt)
        return self.generate_with_messages(messages, **kwargs)

    def generate_with_messages(
        self,
        messages: List[AIMessage],
        **kwargs
    ) -> AIResponse:
        """Generate a response with full conversation history

        Args:
            messages: List of conversation messages
            **kwargs: Additional parameters

        Returns:
            AIResponse with the generated content
        """
        start_time = time.time()

        try:
            self.check_rate_limit()
            client = self.get_client()

            # Convert to OpenAI message format
            api_messages = [
                {"role": msg.role, "content": msg.content}
                for msg in messages
            ]

            # Get parameters
            temperature = kwargs.get("temperature", self.config.temperature)
            max_tokens = kwargs.get("max_tokens", self.config.max_tokens)
            top_p = kwargs.get("top_p", self.config.top_p)
            frequency_penalty = kwargs.get("frequency_penalty", 0)
            presence_penalty = kwargs.get("presence_penalty", 0)
            stop = kwargs.get("stop", None)
            response_format = kwargs.get("response_format", None)

            # Build request
            request_params = {
                "model": self.config.model,
                "messages": api_messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "top_p": top_p,
                "frequency_penalty": frequency_penalty,
                "presence_penalty": presence_penalty
            }

            if stop:
                request_params["stop"] = stop

            if response_format:
                request_params["response_format"] = response_format

            # Make request with retry
            response = self._with_retry(
                self._make_request,
                request_params
            )

            # Calculate latency
            latency_ms = int((time.time() - start_time) * 1000)

            # Extract content
            content = ""
            finish_reason = "stop"
            if response.choices and len(response.choices) > 0:
                choice = response.choices[0]
                content = choice.message.content or ""
                finish_reason = choice.finish_reason or "stop"

            # Get token counts
            input_tokens = response.usage.prompt_tokens if response.usage else 0
            output_tokens = response.usage.completion_tokens if response.usage else 0
            total_tokens = response.usage.total_tokens if response.usage else 0

            # Estimate cost
            cost = self.estimate_cost(input_tokens, output_tokens)

            return AIResponse(
                success=True,
                content=content,
                raw_response={
                    "id": response.id,
                    "model": response.model,
                    "object": response.object,
                    "created": response.created,
                    "system_fingerprint": getattr(response, 'system_fingerprint', None)
                },
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                model=response.model,
                finish_reason=finish_reason,
                latency_ms=latency_ms,
                estimated_cost=cost
            )

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            self._log_error("OpenAI API error", e)

            return AIResponse(
                success=False,
                content="",
                error_message=str(e),
                model=self.config.model,
                latency_ms=latency_ms
            )

    def _make_request(self, params: Dict[str, Any]):
        """Make the API request

        Args:
            params: Request parameters

        Returns:
            API response
        """
        return self._client.chat.completions.create(**params)

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count for text

        Tries to use tiktoken if available, otherwise falls back
        to character-based estimation.

        Args:
            text: Text to estimate tokens for

        Returns:
            Estimated token count
        """
        if not text:
            return 0

        try:
            import tiktoken
            # Get encoding for the model
            try:
                encoding = tiktoken.encoding_for_model(self.config.model)
            except KeyError:
                # Fallback to cl100k_base for unknown models
                encoding = tiktoken.get_encoding("cl100k_base")

            return len(encoding.encode(text))

        except ImportError:
            # Fallback: roughly 4 characters per token
            return int(len(text) / 4) + 1

    def count_message_tokens(self, messages: List[AIMessage]) -> int:
        """Count tokens for a list of messages

        Args:
            messages: List of messages

        Returns:
            Total estimated token count
        """
        total = 0
        for msg in messages:
            # Add overhead for message structure (~4 tokens per message)
            total += 4
            total += self.estimate_tokens(msg.content)
            # Add role token
            total += 1
        # Add 2 for priming
        total += 2
        return total

    def get_max_response_tokens(
        self,
        system_prompt: str,
        user_prompt: str
    ) -> int:
        """Calculate maximum tokens available for response

        Args:
            system_prompt: System prompt
            user_prompt: User prompt

        Returns:
            Maximum tokens available for response
        """
        input_tokens = (
            self.estimate_tokens(system_prompt) +
            self.estimate_tokens(user_prompt) +
            10  # Message overhead
        )

        return min(
            self.config.max_tokens,
            self.max_context_tokens - input_tokens
        )

    def generate_with_json_mode(
        self,
        system_prompt: str,
        user_prompt: str,
        **kwargs
    ) -> AIResponse:
        """Generate response in JSON mode

        Forces the model to output valid JSON.

        Args:
            system_prompt: System prompt (should mention JSON output)
            user_prompt: User prompt
            **kwargs: Additional parameters

        Returns:
            AIResponse with JSON content
        """
        return self.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format={"type": "json_object"},
            **kwargs
        )

    def stream_generate(
        self,
        system_prompt: str,
        user_prompt: str,
        callback: callable,
        **kwargs
    ) -> AIResponse:
        """Generate response with streaming

        Streams the response and calls the callback for each chunk.

        Args:
            system_prompt: System prompt
            user_prompt: User prompt
            callback: Function to call with each chunk (chunk: str)
            **kwargs: Additional parameters

        Returns:
            Final AIResponse with complete content
        """
        start_time = time.time()

        try:
            self.check_rate_limit()
            client = self.get_client()

            # Build messages
            messages = [{"role": "user", "content": user_prompt}]
            if system_prompt:
                messages.insert(0, {"role": "system", "content": system_prompt})

            # Get parameters
            temperature = kwargs.get("temperature", self.config.temperature)
            max_tokens = kwargs.get("max_tokens", self.config.max_tokens)

            # Make streaming request
            full_content = ""

            stream = client.chat.completions.create(
                model=self.config.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True
            )

            for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        full_content += delta.content
                        callback(delta.content)

            latency_ms = int((time.time() - start_time) * 1000)

            # Estimate tokens since streaming doesn't provide them
            input_tokens = self.estimate_tokens(system_prompt + user_prompt)
            output_tokens = self.estimate_tokens(full_content)
            cost = self.estimate_cost(input_tokens, output_tokens)

            return AIResponse(
                success=True,
                content=full_content,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                model=self.config.model,
                finish_reason="stop",
                latency_ms=latency_ms,
                estimated_cost=cost
            )

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            self._log_error("OpenAI streaming error", e)

            return AIResponse(
                success=False,
                content="",
                error_message=str(e),
                model=self.config.model,
                latency_ms=latency_ms
            )


class AzureOpenAIProvider(OpenAIProvider):
    """Azure OpenAI AI Provider

    Extends the OpenAI provider to work with Azure OpenAI Service.

    Requires additional configuration:
        - base_url: Azure OpenAI endpoint
        - model: Deployment name (not model name)

    Example:
        >>> config = ProviderConfig(
        ...     api_key="azure-key",
        ...     model="my-gpt4-deployment",
        ...     base_url="https://my-resource.openai.azure.com/"
        ... )
        >>> provider = AzureOpenAIProvider(config)
    """

    name = "Azure OpenAI"

    def _initialize_client(self):
        """Initialize the Azure OpenAI client"""
        try:
            from openai import AzureOpenAI

            if not self.config.base_url:
                raise ValueError(
                    "Azure OpenAI endpoint (base_url) is required"
                )

            # Extract API version from extra_params or use default
            api_version = "2024-02-15-preview"
            if self.config.extra_params:
                api_version = self.config.extra_params.get(
                    "api_version",
                    api_version
                )

            self._client = AzureOpenAI(
                api_key=self.config.api_key,
                api_version=api_version,
                azure_endpoint=self.config.base_url,
                timeout=self.config.timeout
            )

        except ImportError:
            raise ImportError(
                "The 'openai' package is required for the Azure OpenAI provider. "
                "Install it with: pip install openai"
            )


def create_openai_provider(
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    **kwargs
) -> OpenAIProvider:
    """Factory function to create an OpenAI provider

    Args:
        api_key: API key (uses settings if not provided)
        model: Model name
        **kwargs: Additional config parameters

    Returns:
        Configured OpenAIProvider
    """
    from .base import get_api_key_from_settings

    if not api_key:
        api_key = get_api_key_from_settings("OpenAI")

    if not api_key:
        raise ValueError(
            "OpenAI API key is required. "
            "Set it in PIM Settings or pass it directly."
        )

    config = ProviderConfig(
        api_key=api_key,
        model=model or OpenAIProvider.default_model,
        temperature=kwargs.get("temperature", 0.7),
        max_tokens=kwargs.get("max_tokens", 4096),
        top_p=kwargs.get("top_p", 1.0),
        timeout=kwargs.get("timeout", 120),
        max_retries=kwargs.get("max_retries", 3),
        retry_delay=kwargs.get("retry_delay", 1.0),
        organization=kwargs.get("organization"),
        base_url=kwargs.get("base_url"),
        extra_params=kwargs.get("extra_params")
    )

    return OpenAIProvider(config)


def create_azure_openai_provider(
    api_key: Optional[str] = None,
    deployment: Optional[str] = None,
    endpoint: Optional[str] = None,
    **kwargs
) -> AzureOpenAIProvider:
    """Factory function to create an Azure OpenAI provider

    Args:
        api_key: API key (uses settings if not provided)
        deployment: Deployment name
        endpoint: Azure OpenAI endpoint URL
        **kwargs: Additional config parameters

    Returns:
        Configured AzureOpenAIProvider
    """
    from .base import get_api_key_from_settings, get_provider_config_from_settings

    if not api_key:
        api_key = get_api_key_from_settings("Azure OpenAI")

    if not api_key:
        raise ValueError(
            "Azure OpenAI API key is required. "
            "Set it in PIM Settings or pass it directly."
        )

    # Get settings for endpoint if not provided
    if not endpoint:
        settings_config = get_provider_config_from_settings("Azure OpenAI")
        endpoint = settings_config.get("base_url")

    if not endpoint:
        raise ValueError(
            "Azure OpenAI endpoint is required. "
            "Set it in PIM Settings or pass it directly."
        )

    config = ProviderConfig(
        api_key=api_key,
        model=deployment or "gpt-4",
        temperature=kwargs.get("temperature", 0.7),
        max_tokens=kwargs.get("max_tokens", 4096),
        top_p=kwargs.get("top_p", 1.0),
        timeout=kwargs.get("timeout", 120),
        max_retries=kwargs.get("max_retries", 3),
        retry_delay=kwargs.get("retry_delay", 1.0),
        base_url=endpoint,
        extra_params=kwargs.get("extra_params", {"api_version": "2024-02-15-preview"})
    )

    return AzureOpenAIProvider(config)
