"""
Google Gemini AI Provider

This module implements the Google Gemini AI provider for PIM enrichment jobs.
It supports Gemini Pro, Gemini Ultra, and Gemini Flash models.

Features:
    - Full conversation support with system instructions
    - Multi-modal support (text and images)
    - Token counting
    - Safety settings configuration
    - Cost estimation based on current pricing
    - Automatic retry with exponential backoff

Usage:
    from frappe_pim.pim.utils.ai_providers import get_provider

    provider = get_provider("Google Gemini", api_key="...")
    response = provider.generate(
        system_prompt="You are a product copywriter.",
        user_prompt="Write a description for wireless headphones."
    )
    print(response.content)

Note: Requires the 'google-generativeai' package to be installed:
    pip install google-generativeai

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


class GeminiProvider(BaseAIProvider):
    """Google Gemini AI Provider

    Implements the BaseAIProvider interface for Google's Gemini models.

    Supported models:
        - gemini-1.5-pro (latest, 1M context)
        - gemini-1.5-flash (fast, 1M context)
        - gemini-pro (stable)
        - gemini-pro-vision (multimodal)
        - gemini-1.0-pro (legacy)

    Attributes:
        name: "Google Gemini"
        default_model: "gemini-1.5-pro"
        max_context_tokens: Maximum context window size

    Example:
        >>> config = ProviderConfig(
        ...     api_key="...",
        ...     model="gemini-1.5-pro",
        ...     temperature=0.7,
        ...     max_tokens=4096
        ... )
        >>> provider = GeminiProvider(config)
        >>> response = provider.generate(
        ...     system_prompt="You are helpful.",
        ...     user_prompt="Describe a product."
        ... )
    """

    name = "Google Gemini"
    default_model = "gemini-1.5-pro"

    supported_models = [
        # Gemini 1.5
        "gemini-1.5-pro",
        "gemini-1.5-pro-latest",
        "gemini-1.5-flash",
        "gemini-1.5-flash-latest",
        # Gemini Pro
        "gemini-pro",
        "gemini-pro-vision",
        "gemini-1.0-pro",
        "gemini-1.0-pro-vision",
        # Experimental/Preview
        "gemini-exp-1206",
        "gemini-2.0-flash-exp"
    ]

    # Pricing per million tokens (as of 2024)
    # Note: Gemini pricing varies by context length
    pricing = {
        "gemini-1.5-pro": {"input": 3.5, "output": 10.5},
        "gemini-1.5-pro-latest": {"input": 3.5, "output": 10.5},
        "gemini-1.5-flash": {"input": 0.075, "output": 0.3},
        "gemini-1.5-flash-latest": {"input": 0.075, "output": 0.3},
        "gemini-pro": {"input": 0.5, "output": 1.5},
        "gemini-pro-vision": {"input": 0.5, "output": 1.5},
        "gemini-1.0-pro": {"input": 0.5, "output": 1.5},
        "gemini-1.0-pro-vision": {"input": 0.5, "output": 1.5},
        "gemini-exp-1206": {"input": 0.0, "output": 0.0},  # Free tier
        "gemini-2.0-flash-exp": {"input": 0.0, "output": 0.0}  # Free tier
    }

    # Context window sizes
    context_windows = {
        "gemini-1.5-pro": 1000000,
        "gemini-1.5-pro-latest": 1000000,
        "gemini-1.5-flash": 1000000,
        "gemini-1.5-flash-latest": 1000000,
        "gemini-pro": 32000,
        "gemini-pro-vision": 16384,
        "gemini-1.0-pro": 32000,
        "gemini-1.0-pro-vision": 16384,
        "gemini-exp-1206": 2000000,
        "gemini-2.0-flash-exp": 1000000
    }

    def __init__(self, config: ProviderConfig):
        """Initialize Gemini provider

        Args:
            config: Provider configuration
        """
        # Set default model if not specified
        if not config.model:
            config.model = self.default_model

        super().__init__(config)
        self.max_context_tokens = self.context_windows.get(
            config.model,
            32000
        )
        self._generation_config = None
        self._safety_settings = None

    def _initialize_client(self):
        """Initialize the Gemini client"""
        try:
            import google.generativeai as genai

            genai.configure(api_key=self.config.api_key)

            # Create generation config
            self._generation_config = genai.GenerationConfig(
                temperature=self.config.temperature,
                max_output_tokens=self.config.max_tokens,
                top_p=self.config.top_p
            )

            # Default safety settings (can be overridden)
            self._safety_settings = [
                {
                    "category": "HARM_CATEGORY_HARASSMENT",
                    "threshold": "BLOCK_MEDIUM_AND_ABOVE"
                },
                {
                    "category": "HARM_CATEGORY_HATE_SPEECH",
                    "threshold": "BLOCK_MEDIUM_AND_ABOVE"
                },
                {
                    "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                    "threshold": "BLOCK_MEDIUM_AND_ABOVE"
                },
                {
                    "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                    "threshold": "BLOCK_MEDIUM_AND_ABOVE"
                }
            ]

            # Get the model
            self._client = genai.GenerativeModel(
                model_name=self.config.model,
                generation_config=self._generation_config,
                safety_settings=self._safety_settings
            )

        except ImportError:
            raise ImportError(
                "The 'google-generativeai' package is required for the Gemini provider. "
                "Install it with: pip install google-generativeai"
            )

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        **kwargs
    ) -> AIResponse:
        """Generate a response using Gemini

        Args:
            system_prompt: System/instruction prompt
            user_prompt: User message
            **kwargs: Additional parameters:
                - temperature: Override config temperature
                - max_tokens: Override config max_tokens
                - top_p: Top-p sampling parameter
                - safety_settings: Override safety settings

        Returns:
            AIResponse with the generated content
        """
        start_time = time.time()

        try:
            self.check_rate_limit()
            client = self.get_client()

            # Build prompt with system instruction
            full_prompt = user_prompt
            if system_prompt:
                full_prompt = f"{system_prompt}\n\n{user_prompt}"

            # Get parameters
            temperature = kwargs.get("temperature", self.config.temperature)
            max_tokens = kwargs.get("max_tokens", self.config.max_tokens)
            top_p = kwargs.get("top_p", self.config.top_p)

            # Create generation config for this request
            import google.generativeai as genai
            generation_config = genai.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
                top_p=top_p
            )

            # Make request with retry
            response = self._with_retry(
                self._make_request,
                full_prompt,
                generation_config,
                kwargs.get("safety_settings")
            )

            # Calculate latency
            latency_ms = int((time.time() - start_time) * 1000)

            # Extract content
            content = ""
            finish_reason = "stop"

            if response.candidates and len(response.candidates) > 0:
                candidate = response.candidates[0]
                if candidate.content and candidate.content.parts:
                    content = candidate.content.parts[0].text
                if candidate.finish_reason:
                    finish_reason = str(candidate.finish_reason.name).lower()

            # Get token counts
            input_tokens = 0
            output_tokens = 0

            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                input_tokens = response.usage_metadata.prompt_token_count or 0
                output_tokens = response.usage_metadata.candidates_token_count or 0

            total_tokens = input_tokens + output_tokens

            # Estimate cost
            cost = self.estimate_cost(input_tokens, output_tokens)

            return AIResponse(
                success=True,
                content=content,
                raw_response={
                    "candidates_count": len(response.candidates) if response.candidates else 0,
                    "finish_reason": finish_reason
                },
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                model=self.config.model,
                finish_reason=finish_reason,
                latency_ms=latency_ms,
                estimated_cost=cost
            )

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            self._log_error("Gemini API error", e)

            # Check for safety-related errors
            error_message = str(e)
            if "safety" in error_message.lower() or "blocked" in error_message.lower():
                error_message = f"Content was blocked by safety filters: {error_message}"

            return AIResponse(
                success=False,
                content="",
                error_message=error_message,
                model=self.config.model,
                latency_ms=latency_ms
            )

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

            # Extract system prompt and build chat history
            system_prompt = ""
            chat_history = []

            for msg in messages:
                if msg.role == "system":
                    system_prompt = msg.content
                elif msg.role == "user":
                    chat_history.append({
                        "role": "user",
                        "parts": [msg.content]
                    })
                elif msg.role == "assistant":
                    chat_history.append({
                        "role": "model",
                        "parts": [msg.content]
                    })

            # Get parameters
            temperature = kwargs.get("temperature", self.config.temperature)
            max_tokens = kwargs.get("max_tokens", self.config.max_tokens)

            # Create generation config
            import google.generativeai as genai
            generation_config = genai.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
                top_p=kwargs.get("top_p", self.config.top_p)
            )

            # Create model with system instruction if provided
            if system_prompt:
                model = genai.GenerativeModel(
                    model_name=self.config.model,
                    generation_config=generation_config,
                    safety_settings=self._safety_settings,
                    system_instruction=system_prompt
                )
            else:
                model = genai.GenerativeModel(
                    model_name=self.config.model,
                    generation_config=generation_config,
                    safety_settings=self._safety_settings
                )

            # Start chat and send messages
            if len(chat_history) > 1:
                # Multi-turn conversation
                chat = model.start_chat(history=chat_history[:-1])
                last_message = chat_history[-1]["parts"][0]
                response = self._with_retry(
                    lambda: chat.send_message(last_message)
                )
            else:
                # Single message
                content = chat_history[0]["parts"][0] if chat_history else ""
                response = self._with_retry(
                    lambda: model.generate_content(content)
                )

            # Calculate latency
            latency_ms = int((time.time() - start_time) * 1000)

            # Extract content
            content = ""
            finish_reason = "stop"

            if response.candidates and len(response.candidates) > 0:
                candidate = response.candidates[0]
                if candidate.content and candidate.content.parts:
                    content = candidate.content.parts[0].text
                if candidate.finish_reason:
                    finish_reason = str(candidate.finish_reason.name).lower()

            # Get token counts
            input_tokens = 0
            output_tokens = 0

            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                input_tokens = response.usage_metadata.prompt_token_count or 0
                output_tokens = response.usage_metadata.candidates_token_count or 0

            total_tokens = input_tokens + output_tokens
            cost = self.estimate_cost(input_tokens, output_tokens)

            return AIResponse(
                success=True,
                content=content,
                raw_response={
                    "candidates_count": len(response.candidates) if response.candidates else 0,
                    "finish_reason": finish_reason
                },
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                model=self.config.model,
                finish_reason=finish_reason,
                latency_ms=latency_ms,
                estimated_cost=cost
            )

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            self._log_error("Gemini chat error", e)

            return AIResponse(
                success=False,
                content="",
                error_message=str(e),
                model=self.config.model,
                latency_ms=latency_ms
            )

    def _make_request(
        self,
        prompt: str,
        generation_config: Any,
        safety_settings: Optional[List[Dict]] = None
    ):
        """Make the API request

        Args:
            prompt: Prompt text
            generation_config: Generation configuration
            safety_settings: Optional safety settings override

        Returns:
            API response
        """
        return self._client.generate_content(
            prompt,
            generation_config=generation_config,
            safety_settings=safety_settings or self._safety_settings
        )

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count for text

        Gemini uses roughly 4 characters per token for English.

        Args:
            text: Text to estimate tokens for

        Returns:
            Estimated token count
        """
        if not text:
            return 0

        # Try to use the model's count_tokens method
        try:
            client = self.get_client()
            result = client.count_tokens(text)
            return result.total_tokens
        except Exception:
            pass

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

    def set_safety_settings(self, settings: List[Dict]):
        """Update safety settings

        Args:
            settings: List of safety setting dictionaries
        """
        self._safety_settings = settings
        # Reinitialize client with new settings
        self._client = None

    def generate_with_images(
        self,
        prompt: str,
        images: List[str],
        **kwargs
    ) -> AIResponse:
        """Generate response with image inputs

        Uses vision-capable models for multimodal content.

        Args:
            prompt: Text prompt
            images: List of image URLs or base64-encoded images
            **kwargs: Additional parameters

        Returns:
            AIResponse with the generated content
        """
        start_time = time.time()

        try:
            self.check_rate_limit()

            import google.generativeai as genai

            # Use vision model if not already
            model_name = self.config.model
            if "vision" not in model_name.lower() and "1.5" not in model_name:
                model_name = "gemini-1.5-flash"

            # Build content parts
            parts = [prompt]

            for image in images:
                try:
                    if image.startswith("http"):
                        # URL - fetch and convert
                        import urllib.request
                        import base64

                        with urllib.request.urlopen(image) as response:
                            image_data = response.read()
                            mime_type = response.headers.get('Content-Type', 'image/jpeg')

                        parts.append({
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": base64.b64encode(image_data).decode()
                            }
                        })
                    elif image.startswith("data:"):
                        # Data URL
                        header, data = image.split(",", 1)
                        mime_type = header.split(":")[1].split(";")[0]
                        parts.append({
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": data
                            }
                        })
                    else:
                        # Assume base64
                        parts.append({
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": image
                            }
                        })
                except Exception as img_error:
                    self._log_warning(f"Could not process image: {str(img_error)}")
                    continue

            # Create model
            model = genai.GenerativeModel(
                model_name=model_name,
                generation_config=self._generation_config,
                safety_settings=self._safety_settings
            )

            # Generate
            response = self._with_retry(
                lambda: model.generate_content(parts)
            )

            latency_ms = int((time.time() - start_time) * 1000)

            # Extract content
            content = ""
            if response.candidates and len(response.candidates) > 0:
                candidate = response.candidates[0]
                if candidate.content and candidate.content.parts:
                    content = candidate.content.parts[0].text

            # Get token counts
            input_tokens = 0
            output_tokens = 0
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                input_tokens = response.usage_metadata.prompt_token_count or 0
                output_tokens = response.usage_metadata.candidates_token_count or 0

            return AIResponse(
                success=True,
                content=content,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                model=model_name,
                finish_reason="stop",
                latency_ms=latency_ms,
                estimated_cost=self.estimate_cost(input_tokens, output_tokens)
            )

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            self._log_error("Gemini vision error", e)

            return AIResponse(
                success=False,
                content="",
                error_message=str(e),
                model=self.config.model,
                latency_ms=latency_ms
            )


def create_gemini_provider(
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    **kwargs
) -> GeminiProvider:
    """Factory function to create a Gemini provider

    Args:
        api_key: API key (uses settings if not provided)
        model: Model name
        **kwargs: Additional config parameters

    Returns:
        Configured GeminiProvider
    """
    from .base import get_api_key_from_settings

    if not api_key:
        api_key = get_api_key_from_settings("Google Gemini")

    if not api_key:
        raise ValueError(
            "Google Gemini API key is required. "
            "Set it in PIM Settings or pass it directly."
        )

    config = ProviderConfig(
        api_key=api_key,
        model=model or GeminiProvider.default_model,
        temperature=kwargs.get("temperature", 0.7),
        max_tokens=kwargs.get("max_tokens", 4096),
        top_p=kwargs.get("top_p", 1.0),
        timeout=kwargs.get("timeout", 120),
        max_retries=kwargs.get("max_retries", 3),
        retry_delay=kwargs.get("retry_delay", 1.0),
        base_url=kwargs.get("base_url"),
        extra_params=kwargs.get("extra_params")
    )

    return GeminiProvider(config)
