"""
Anthropic (Claude) AI Provider

This module implements the Anthropic Claude AI provider for PIM enrichment jobs.
It supports Claude 3 models (Opus, Sonnet, Haiku) and Claude 2.

Features:
    - Full conversation support with system prompts
    - Token counting using tiktoken estimation
    - Streaming support (optional)
    - Cost estimation based on current pricing
    - Automatic retry with exponential backoff

Usage:
    from frappe_pim.pim.utils.ai_providers import get_provider

    provider = get_provider("Anthropic", api_key="sk-ant-...")
    response = provider.generate(
        system_prompt="You are a product copywriter.",
        user_prompt="Write a description for wireless headphones."
    )
    print(response.content)

Note: Requires the 'anthropic' package to be installed:
    pip install anthropic

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


class AnthropicProvider(BaseAIProvider):
    """Anthropic Claude AI Provider

    Implements the BaseAIProvider interface for Anthropic's Claude models.

    Supported models:
        - claude-3-opus-20240229 (most capable)
        - claude-3-sonnet-20240229 (balanced)
        - claude-3-haiku-20240307 (fastest)
        - claude-3-5-sonnet-20240620 (newer sonnet)
        - claude-2.1 (legacy)
        - claude-2.0 (legacy)

    Attributes:
        name: "Anthropic"
        default_model: "claude-3-sonnet-20240229"
        max_context_tokens: Maximum context window size

    Example:
        >>> config = ProviderConfig(
        ...     api_key="sk-ant-...",
        ...     model="claude-3-sonnet-20240229",
        ...     temperature=0.7,
        ...     max_tokens=4096
        ... )
        >>> provider = AnthropicProvider(config)
        >>> response = provider.generate(
        ...     system_prompt="You are helpful.",
        ...     user_prompt="Describe a product."
        ... )
    """

    name = "Anthropic"
    default_model = "claude-3-sonnet-20240229"

    supported_models = [
        # Claude 3.5
        "claude-3-5-sonnet-20240620",
        "claude-3-5-sonnet-20241022",
        "claude-3-5-haiku-20241022",
        # Claude 3
        "claude-3-opus-20240229",
        "claude-3-sonnet-20240229",
        "claude-3-haiku-20240307",
        # Legacy
        "claude-2.1",
        "claude-2.0",
        "claude-instant-1.2"
    ]

    # Pricing per million tokens (as of 2024)
    pricing = {
        "claude-3-5-sonnet-20240620": {"input": 3.0, "output": 15.0},
        "claude-3-5-sonnet-20241022": {"input": 3.0, "output": 15.0},
        "claude-3-5-haiku-20241022": {"input": 0.25, "output": 1.25},
        "claude-3-opus-20240229": {"input": 15.0, "output": 75.0},
        "claude-3-sonnet-20240229": {"input": 3.0, "output": 15.0},
        "claude-3-haiku-20240307": {"input": 0.25, "output": 1.25},
        "claude-2.1": {"input": 8.0, "output": 24.0},
        "claude-2.0": {"input": 8.0, "output": 24.0},
        "claude-instant-1.2": {"input": 0.8, "output": 2.4}
    }

    # Context window sizes
    context_windows = {
        "claude-3-5-sonnet-20240620": 200000,
        "claude-3-5-sonnet-20241022": 200000,
        "claude-3-5-haiku-20241022": 200000,
        "claude-3-opus-20240229": 200000,
        "claude-3-sonnet-20240229": 200000,
        "claude-3-haiku-20240307": 200000,
        "claude-2.1": 200000,
        "claude-2.0": 100000,
        "claude-instant-1.2": 100000
    }

    def __init__(self, config: ProviderConfig):
        """Initialize Anthropic provider

        Args:
            config: Provider configuration
        """
        # Set default model if not specified
        if not config.model:
            config.model = self.default_model

        super().__init__(config)
        self.max_context_tokens = self.context_windows.get(
            config.model,
            200000
        )

    def _initialize_client(self):
        """Initialize the Anthropic client"""
        try:
            from anthropic import Anthropic

            client_kwargs = {
                "api_key": self.config.api_key,
                "timeout": self.config.timeout
            }

            if self.config.base_url:
                client_kwargs["base_url"] = self.config.base_url

            self._client = Anthropic(**client_kwargs)

        except ImportError:
            raise ImportError(
                "The 'anthropic' package is required for the Anthropic provider. "
                "Install it with: pip install anthropic"
            )

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        **kwargs
    ) -> AIResponse:
        """Generate a response using Claude

        Args:
            system_prompt: System/instruction prompt
            user_prompt: User message
            **kwargs: Additional parameters:
                - temperature: Override config temperature
                - max_tokens: Override config max_tokens
                - top_p: Top-p sampling parameter
                - stop_sequences: List of stop sequences

        Returns:
            AIResponse with the generated content
        """
        messages = self._build_messages(system_prompt, user_prompt)
        return self.generate_with_messages(
            messages,
            system_prompt=system_prompt,
            **kwargs
        )

    def generate_with_messages(
        self,
        messages: List[AIMessage],
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> AIResponse:
        """Generate a response with full conversation history

        Args:
            messages: List of conversation messages
            system_prompt: System prompt (extracted from messages if not provided)
            **kwargs: Additional parameters

        Returns:
            AIResponse with the generated content
        """
        start_time = time.time()

        try:
            self.check_rate_limit()
            client = self.get_client()

            # Separate system prompt from messages
            if system_prompt is None:
                system_prompt = ""
                for msg in messages:
                    if msg.role == "system":
                        system_prompt = msg.content
                        break

            # Build message list (excluding system messages)
            api_messages = [
                {"role": msg.role, "content": msg.content}
                for msg in messages
                if msg.role != "system"
            ]

            # Get parameters
            temperature = kwargs.get("temperature", self.config.temperature)
            max_tokens = kwargs.get("max_tokens", self.config.max_tokens)
            top_p = kwargs.get("top_p", self.config.top_p)
            stop_sequences = kwargs.get("stop_sequences", None)

            # Build request
            request_params = {
                "model": self.config.model,
                "messages": api_messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "top_p": top_p
            }

            if system_prompt:
                request_params["system"] = system_prompt

            if stop_sequences:
                request_params["stop_sequences"] = stop_sequences

            # Make request with retry
            response = self._with_retry(
                self._make_request,
                request_params
            )

            # Calculate latency
            latency_ms = int((time.time() - start_time) * 1000)

            # Extract content
            content = ""
            if response.content and len(response.content) > 0:
                content = response.content[0].text

            # Get token counts
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
            total_tokens = input_tokens + output_tokens

            # Estimate cost
            cost = self.estimate_cost(input_tokens, output_tokens)

            return AIResponse(
                success=True,
                content=content,
                raw_response={
                    "id": response.id,
                    "model": response.model,
                    "type": response.type,
                    "role": response.role,
                    "stop_reason": response.stop_reason
                },
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                model=response.model,
                finish_reason=response.stop_reason or "stop",
                latency_ms=latency_ms,
                estimated_cost=cost
            )

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            self._log_error("Anthropic API error", e)

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
        return self._client.messages.create(**params)

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count for text

        Uses character-based estimation optimized for Claude.
        Claude's tokenizer is roughly 3.5 characters per token.

        Args:
            text: Text to estimate tokens for

        Returns:
            Estimated token count
        """
        if not text:
            return 0

        # Claude uses roughly 3.5 characters per token
        return int(len(text) / 3.5) + 1

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

            # Build message list
            api_messages = [{"role": "user", "content": user_prompt}]

            # Get parameters
            temperature = kwargs.get("temperature", self.config.temperature)
            max_tokens = kwargs.get("max_tokens", self.config.max_tokens)

            # Make streaming request
            full_content = ""
            input_tokens = 0
            output_tokens = 0

            with client.messages.stream(
                model=self.config.model,
                messages=api_messages,
                system=system_prompt if system_prompt else None,
                max_tokens=max_tokens,
                temperature=temperature
            ) as stream:
                for text in stream.text_stream:
                    full_content += text
                    callback(text)

                # Get final message for token counts
                final_message = stream.get_final_message()
                input_tokens = final_message.usage.input_tokens
                output_tokens = final_message.usage.output_tokens

            latency_ms = int((time.time() - start_time) * 1000)
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
            self._log_error("Anthropic streaming error", e)

            return AIResponse(
                success=False,
                content="",
                error_message=str(e),
                model=self.config.model,
                latency_ms=latency_ms
            )


def create_anthropic_provider(
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    **kwargs
) -> AnthropicProvider:
    """Factory function to create an Anthropic provider

    Args:
        api_key: API key (uses settings if not provided)
        model: Model name
        **kwargs: Additional config parameters

    Returns:
        Configured AnthropicProvider
    """
    from .base import get_api_key_from_settings

    if not api_key:
        api_key = get_api_key_from_settings("Anthropic")

    if not api_key:
        raise ValueError(
            "Anthropic API key is required. "
            "Set it in PIM Settings or pass it directly."
        )

    config = ProviderConfig(
        api_key=api_key,
        model=model or AnthropicProvider.default_model,
        temperature=kwargs.get("temperature", 0.7),
        max_tokens=kwargs.get("max_tokens", 4096),
        top_p=kwargs.get("top_p", 1.0),
        timeout=kwargs.get("timeout", 120),
        max_retries=kwargs.get("max_retries", 3),
        retry_delay=kwargs.get("retry_delay", 1.0),
        base_url=kwargs.get("base_url"),
        extra_params=kwargs.get("extra_params")
    )

    return AnthropicProvider(config)
