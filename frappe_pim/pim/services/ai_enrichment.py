"""AI Enrichment Service

This module provides AI-powered product enrichment services including:
- Product description generation (short and long descriptions)
- SEO-optimized title generation
- Bullet point feature extraction
- Keyword and tag suggestion
- Attribute extraction from product data
- Multi-language description generation

The service supports multiple AI providers:
- OpenAI (GPT-4, GPT-3.5-turbo)
- Anthropic Claude (Claude 3 Opus, Sonnet, Haiku)
- Google Gemini
- Azure OpenAI

Key Concepts:
- Enrichment Request: A request to enrich product data with AI
- Enrichment Result: AI-generated content with confidence scores
- Approval Queue: Human-in-the-loop review system for AI content
- Prompt Templates: Configurable templates for different enrichment tasks

Human-in-the-Loop Workflow:
1. User requests AI enrichment for a product
2. AI generates suggestions with confidence scores
3. Results are queued for human approval (if required by settings)
4. Approved content is applied to the product
5. Rejected content is logged for model improvement

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union


# =============================================================================
# Constants and Enums
# =============================================================================

class AIProvider(Enum):
    """Supported AI providers."""
    OPENAI = "OpenAI"
    ANTHROPIC = "Anthropic"
    GOOGLE_GEMINI = "Google Gemini"
    AZURE_OPENAI = "Azure OpenAI"


class EnrichmentType(Enum):
    """Types of AI enrichment tasks."""
    DESCRIPTION_SHORT = "description_short"
    DESCRIPTION_LONG = "description_long"
    SEO_TITLE = "seo_title"
    BULLET_POINTS = "bullet_points"
    KEYWORDS = "keywords"
    TAGS = "tags"
    CATEGORY_SUGGESTION = "category_suggestion"
    ATTRIBUTE_EXTRACTION = "attribute_extraction"
    IMAGE_ALT_TEXT = "image_alt_text"
    META_DESCRIPTION = "meta_description"


class EnrichmentStatus(Enum):
    """Status of an enrichment request."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"


class ConfidenceLevel(Enum):
    """Confidence level categories."""
    HIGH = "high"       # >= 0.8
    MEDIUM = "medium"   # >= 0.6
    LOW = "low"         # >= 0.4
    VERY_LOW = "very_low"  # < 0.4


# Default AI models per provider
DEFAULT_MODELS = {
    AIProvider.OPENAI: "gpt-4-turbo-preview",
    AIProvider.ANTHROPIC: "claude-3-sonnet-20240229",
    AIProvider.GOOGLE_GEMINI: "gemini-pro",
    AIProvider.AZURE_OPENAI: "gpt-4",
}

# API endpoints
API_ENDPOINTS = {
    AIProvider.OPENAI: "https://api.openai.com/v1/chat/completions",
    AIProvider.ANTHROPIC: "https://api.anthropic.com/v1/messages",
    AIProvider.GOOGLE_GEMINI: "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
}

# Rate limits (requests per minute)
RATE_LIMITS = {
    AIProvider.OPENAI: 60,
    AIProvider.ANTHROPIC: 50,
    AIProvider.GOOGLE_GEMINI: 60,
    AIProvider.AZURE_OPENAI: 60,
}

# Maximum tokens for different enrichment types
MAX_TOKENS = {
    EnrichmentType.DESCRIPTION_SHORT: 150,
    EnrichmentType.DESCRIPTION_LONG: 500,
    EnrichmentType.SEO_TITLE: 80,
    EnrichmentType.BULLET_POINTS: 300,
    EnrichmentType.KEYWORDS: 100,
    EnrichmentType.TAGS: 100,
    EnrichmentType.CATEGORY_SUGGESTION: 150,
    EnrichmentType.ATTRIBUTE_EXTRACTION: 400,
    EnrichmentType.IMAGE_ALT_TEXT: 100,
    EnrichmentType.META_DESCRIPTION: 160,
}


# =============================================================================
# Prompt Templates
# =============================================================================

PROMPT_TEMPLATES = {
    EnrichmentType.DESCRIPTION_SHORT: """Generate a concise, compelling product description for the following product.
The description should be 1-2 sentences, highlighting key features and benefits.

Product Information:
{product_info}

Requirements:
- Keep it under 150 characters
- Focus on the main value proposition
- Use active, engaging language
- Do not include the product name at the start

Respond with ONLY the description text, no explanations.""",

    EnrichmentType.DESCRIPTION_LONG: """Generate a detailed product description for the following product.
The description should be comprehensive yet engaging, suitable for an e-commerce product page.

Product Information:
{product_info}

Requirements:
- 2-4 paragraphs
- Highlight key features and benefits
- Include specifications where relevant
- Use persuasive but honest language
- Suitable for {target_audience}
- Optimized for SEO with natural keyword usage

Respond with ONLY the description text, no explanations.""",

    EnrichmentType.SEO_TITLE: """Generate an SEO-optimized product title for the following product.

Product Information:
{product_info}

Requirements:
- 50-70 characters ideal length
- Include primary keywords
- Include brand name if available
- Clear and descriptive
- Do not use all caps or excessive punctuation

Respond with ONLY the title text, no explanations.""",

    EnrichmentType.BULLET_POINTS: """Generate compelling bullet points for the following product.
These will be used on the product detail page.

Product Information:
{product_info}

Requirements:
- 4-6 bullet points
- Start each with a strong feature or benefit
- Keep each bullet to 1-2 lines
- Focus on customer benefits, not just features
- Use action-oriented language

Respond with ONLY the bullet points, one per line, starting with • symbol.""",

    EnrichmentType.KEYWORDS: """Extract relevant keywords for the following product.
These keywords will be used for search optimization and categorization.

Product Information:
{product_info}

Requirements:
- 10-15 keywords
- Mix of short-tail and long-tail keywords
- Include product type, features, use cases
- Consider search intent
- Separate with commas

Respond with ONLY the comma-separated keywords, no explanations.""",

    EnrichmentType.TAGS: """Generate product tags for the following product.
Tags will be used for filtering and discovery.

Product Information:
{product_info}

Requirements:
- 5-10 tags
- Single words or short phrases
- Include category, style, use case, material
- Avoid duplicating existing categories

Respond with ONLY the comma-separated tags, no explanations.""",

    EnrichmentType.CATEGORY_SUGGESTION: """Suggest the most appropriate product categories for the following product.

Product Information:
{product_info}

Available Categories:
{available_categories}

Requirements:
- Suggest primary category and up to 2 secondary categories
- Choose from available categories only
- Explain your reasoning briefly

Respond in JSON format:
{{"primary": "category_name", "secondary": ["cat1", "cat2"], "reasoning": "brief explanation"}}""",

    EnrichmentType.ATTRIBUTE_EXTRACTION: """Extract structured product attributes from the following product information.

Product Information:
{product_info}

Required Attributes:
{required_attributes}

Requirements:
- Extract values for each required attribute if present
- Use null for attributes that cannot be determined
- Include confidence score (0-1) for each extraction
- Standardize units where applicable

Respond in JSON format:
{{"attributes": {{"attr_name": {{"value": "extracted_value", "confidence": 0.9}}, ...}}}}""",

    EnrichmentType.IMAGE_ALT_TEXT: """Generate descriptive alt text for the product image.

Product Information:
{product_info}

Image Context:
{image_context}

Requirements:
- Clear, descriptive text for accessibility
- 125 characters or less
- Describe what's in the image
- Include relevant product details

Respond with ONLY the alt text, no explanations.""",

    EnrichmentType.META_DESCRIPTION: """Generate a meta description for the product page.

Product Information:
{product_info}

Requirements:
- 150-160 characters
- Include primary keyword
- Call to action
- Compelling for click-through

Respond with ONLY the meta description text, no explanations.""",
}


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class EnrichmentRequest:
    """Request for AI enrichment."""
    product: str
    enrichment_type: EnrichmentType
    product_data: Dict[str, Any]
    language: str = "en"
    target_audience: str = "general consumers"
    additional_context: Optional[str] = None
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "product": self.product,
            "enrichment_type": self.enrichment_type.value,
            "product_data": self.product_data,
            "language": self.language,
            "target_audience": self.target_audience,
            "additional_context": self.additional_context,
            "request_id": self.request_id,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class EnrichmentSuggestion:
    """A single AI-generated suggestion."""
    content: str
    confidence: float
    enrichment_type: EnrichmentType
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def confidence_level(self) -> ConfidenceLevel:
        """Get confidence level category."""
        if self.confidence >= 0.8:
            return ConfidenceLevel.HIGH
        elif self.confidence >= 0.6:
            return ConfidenceLevel.MEDIUM
        elif self.confidence >= 0.4:
            return ConfidenceLevel.LOW
        else:
            return ConfidenceLevel.VERY_LOW

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "content": self.content,
            "confidence": round(self.confidence, 3),
            "confidence_level": self.confidence_level.value,
            "enrichment_type": self.enrichment_type.value,
            "metadata": self.metadata,
        }


@dataclass
class EnrichmentResult:
    """Result of an enrichment request."""
    request_id: str
    product: str
    status: EnrichmentStatus
    suggestions: List[EnrichmentSuggestion] = field(default_factory=list)
    provider: Optional[AIProvider] = None
    model: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    processing_time_ms: int = 0
    error_message: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "request_id": self.request_id,
            "product": self.product,
            "status": self.status.value,
            "suggestions": [s.to_dict() for s in self.suggestions],
            "provider": self.provider.value if self.provider else None,
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "processing_time_ms": self.processing_time_ms,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class BulkEnrichmentResult:
    """Result of bulk enrichment operation."""
    total_products: int
    successful: int = 0
    failed: int = 0
    results: List[EnrichmentResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    processing_time_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_products": self.total_products,
            "successful": self.successful,
            "failed": self.failed,
            "success_rate": round(self.successful / max(self.total_products, 1) * 100, 1),
            "results": [r.to_dict() for r in self.results],
            "errors": self.errors,
            "processing_time_ms": self.processing_time_ms,
        }


# =============================================================================
# AI Enrichment Service
# =============================================================================

class AIEnrichmentService:
    """Service for AI-powered product enrichment.

    This service provides high-level operations for enriching product data
    using AI providers like OpenAI and Anthropic Claude.

    Attributes:
        provider: AI provider to use
        model: Specific model to use
        api_key: API key for the provider
        require_approval: Whether to require human approval
    """

    def __init__(
        self,
        provider: Optional[AIProvider] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        require_approval: bool = True
    ):
        """Initialize the AI enrichment service.

        Args:
            provider: AI provider (loaded from settings if not provided)
            model: Model to use (loaded from settings if not provided)
            api_key: API key (loaded from settings if not provided)
            require_approval: Whether to require human approval
        """
        self._provider = provider
        self._model = model
        self._api_key = api_key
        self.require_approval = require_approval
        self._initialized = False

    def _ensure_initialized(self):
        """Ensure the service is initialized with settings."""
        if self._initialized:
            return

        if not self._provider or not self._api_key:
            config = _get_ai_config()
            if not config:
                raise ValueError(
                    "AI enrichment is not enabled. Please configure in PIM Settings."
                )

            if not self._provider:
                provider_str = config.get("provider")
                if provider_str:
                    self._provider = AIProvider(provider_str)
                else:
                    raise ValueError("AI provider is not configured.")

            if not self._api_key:
                self._api_key = _get_ai_api_key()
                if not self._api_key:
                    raise ValueError("AI API key is not configured.")

            if not self._model:
                self._model = config.get("model") or DEFAULT_MODELS.get(self._provider)

            self.require_approval = config.get("require_approval", True)

        self._initialized = True

    @property
    def provider(self) -> AIProvider:
        """Get the AI provider."""
        self._ensure_initialized()
        return self._provider

    @property
    def model(self) -> str:
        """Get the model name."""
        self._ensure_initialized()
        return self._model

    def generate_description(
        self,
        product: str,
        description_type: str = "long",
        language: str = "en",
        target_audience: str = "general consumers"
    ) -> EnrichmentResult:
        """Generate a product description.

        Args:
            product: Product Master name
            description_type: "short" or "long"
            language: Target language code
            target_audience: Target audience description

        Returns:
            EnrichmentResult with generated description
        """
        self._ensure_initialized()

        enrichment_type = (
            EnrichmentType.DESCRIPTION_SHORT
            if description_type == "short"
            else EnrichmentType.DESCRIPTION_LONG
        )

        product_data = _get_product_data(product)
        if not product_data:
            return EnrichmentResult(
                request_id=str(uuid.uuid4()),
                product=product,
                status=EnrichmentStatus.FAILED,
                error_message=f"Product not found: {product}"
            )

        request = EnrichmentRequest(
            product=product,
            enrichment_type=enrichment_type,
            product_data=product_data,
            language=language,
            target_audience=target_audience,
        )

        return self._process_enrichment(request)

    def generate_seo_content(
        self,
        product: str,
        content_types: Optional[List[str]] = None,
        language: str = "en"
    ) -> Dict[str, EnrichmentResult]:
        """Generate SEO-optimized content for a product.

        Args:
            product: Product Master name
            content_types: List of content types (title, meta_description, keywords)
            language: Target language code

        Returns:
            Dictionary mapping content type to EnrichmentResult
        """
        self._ensure_initialized()

        if not content_types:
            content_types = ["seo_title", "meta_description", "keywords"]

        type_mapping = {
            "seo_title": EnrichmentType.SEO_TITLE,
            "meta_description": EnrichmentType.META_DESCRIPTION,
            "keywords": EnrichmentType.KEYWORDS,
            "tags": EnrichmentType.TAGS,
        }

        product_data = _get_product_data(product)
        if not product_data:
            return {
                ct: EnrichmentResult(
                    request_id=str(uuid.uuid4()),
                    product=product,
                    status=EnrichmentStatus.FAILED,
                    error_message=f"Product not found: {product}"
                )
                for ct in content_types
            }

        results = {}
        for content_type in content_types:
            enrichment_type = type_mapping.get(content_type)
            if not enrichment_type:
                continue

            request = EnrichmentRequest(
                product=product,
                enrichment_type=enrichment_type,
                product_data=product_data,
                language=language,
            )

            results[content_type] = self._process_enrichment(request)

        return results

    def generate_bullet_points(
        self,
        product: str,
        count: int = 5,
        language: str = "en"
    ) -> EnrichmentResult:
        """Generate bullet point features for a product.

        Args:
            product: Product Master name
            count: Number of bullet points to generate
            language: Target language code

        Returns:
            EnrichmentResult with bullet points
        """
        self._ensure_initialized()

        product_data = _get_product_data(product)
        if not product_data:
            return EnrichmentResult(
                request_id=str(uuid.uuid4()),
                product=product,
                status=EnrichmentStatus.FAILED,
                error_message=f"Product not found: {product}"
            )

        request = EnrichmentRequest(
            product=product,
            enrichment_type=EnrichmentType.BULLET_POINTS,
            product_data=product_data,
            language=language,
            additional_context=f"Generate exactly {count} bullet points.",
        )

        return self._process_enrichment(request)

    def extract_attributes(
        self,
        product: str,
        required_attributes: List[str]
    ) -> EnrichmentResult:
        """Extract structured attributes from product data.

        Args:
            product: Product Master name
            required_attributes: List of attribute names to extract

        Returns:
            EnrichmentResult with extracted attributes
        """
        self._ensure_initialized()

        product_data = _get_product_data(product)
        if not product_data:
            return EnrichmentResult(
                request_id=str(uuid.uuid4()),
                product=product,
                status=EnrichmentStatus.FAILED,
                error_message=f"Product not found: {product}"
            )

        # Add required attributes to product data for prompt
        product_data["_required_attributes"] = required_attributes

        request = EnrichmentRequest(
            product=product,
            enrichment_type=EnrichmentType.ATTRIBUTE_EXTRACTION,
            product_data=product_data,
        )

        return self._process_enrichment(request)

    def suggest_categories(
        self,
        product: str,
        available_categories: Optional[List[str]] = None
    ) -> EnrichmentResult:
        """Suggest categories for a product.

        Args:
            product: Product Master name
            available_categories: List of available category names

        Returns:
            EnrichmentResult with category suggestions
        """
        self._ensure_initialized()

        product_data = _get_product_data(product)
        if not product_data:
            return EnrichmentResult(
                request_id=str(uuid.uuid4()),
                product=product,
                status=EnrichmentStatus.FAILED,
                error_message=f"Product not found: {product}"
            )

        if not available_categories:
            available_categories = _get_available_categories()

        product_data["_available_categories"] = available_categories

        request = EnrichmentRequest(
            product=product,
            enrichment_type=EnrichmentType.CATEGORY_SUGGESTION,
            product_data=product_data,
        )

        return self._process_enrichment(request)

    def enrich_product(
        self,
        product: str,
        enrichment_types: Optional[List[str]] = None,
        language: str = "en",
        target_audience: str = "general consumers"
    ) -> Dict[str, EnrichmentResult]:
        """Enrich a product with multiple content types.

        Args:
            product: Product Master name
            enrichment_types: List of enrichment types to generate
            language: Target language code
            target_audience: Target audience description

        Returns:
            Dictionary mapping enrichment type to result
        """
        self._ensure_initialized()

        if not enrichment_types:
            enrichment_types = [
                "description_short",
                "description_long",
                "bullet_points",
                "keywords",
                "seo_title",
            ]

        results = {}

        # Generate descriptions
        if "description_short" in enrichment_types:
            results["description_short"] = self.generate_description(
                product, "short", language, target_audience
            )

        if "description_long" in enrichment_types:
            results["description_long"] = self.generate_description(
                product, "long", language, target_audience
            )

        # Generate bullet points
        if "bullet_points" in enrichment_types:
            results["bullet_points"] = self.generate_bullet_points(
                product, 5, language
            )

        # Generate SEO content
        seo_types = [
            t for t in enrichment_types
            if t in ["seo_title", "meta_description", "keywords", "tags"]
        ]
        if seo_types:
            seo_results = self.generate_seo_content(product, seo_types, language)
            results.update(seo_results)

        return results

    def bulk_enrich(
        self,
        products: List[str],
        enrichment_types: Optional[List[str]] = None,
        language: str = "en",
        async_process: bool = True
    ) -> BulkEnrichmentResult:
        """Enrich multiple products.

        Args:
            products: List of Product Master names
            enrichment_types: List of enrichment types to generate
            language: Target language code
            async_process: If True, process in background

        Returns:
            BulkEnrichmentResult with all results
        """
        import frappe
        import time

        self._ensure_initialized()

        start_time = time.time()

        bulk_result = BulkEnrichmentResult(
            total_products=len(products)
        )

        if async_process and len(products) > 3:
            # Enqueue as background job
            job = frappe.enqueue(
                "frappe_pim.pim.services.ai_enrichment._bulk_enrich_job",
                queue="long",
                timeout=3600,
                products=products,
                enrichment_types=enrichment_types,
                language=language,
            )

            bulk_result.processing_time_ms = int((time.time() - start_time) * 1000)
            return bulk_result

        for product in products:
            try:
                product_results = self.enrich_product(
                    product,
                    enrichment_types,
                    language,
                )

                # Track results
                for enrichment_type, result in product_results.items():
                    bulk_result.results.append(result)
                    if result.status == EnrichmentStatus.COMPLETED:
                        bulk_result.successful += 1
                    else:
                        bulk_result.failed += 1

            except Exception as e:
                bulk_result.failed += 1
                bulk_result.errors.append(f"{product}: {str(e)}")

        bulk_result.processing_time_ms = int((time.time() - start_time) * 1000)
        return bulk_result

    def _process_enrichment(self, request: EnrichmentRequest) -> EnrichmentResult:
        """Process an enrichment request.

        Args:
            request: EnrichmentRequest to process

        Returns:
            EnrichmentResult with AI-generated content
        """
        import time

        start_time = time.time()

        result = EnrichmentResult(
            request_id=request.request_id,
            product=request.product,
            status=EnrichmentStatus.PROCESSING,
            provider=self.provider,
            model=self.model,
        )

        try:
            # Build prompt
            prompt = self._build_prompt(request)

            # Call AI provider
            ai_response = self._call_ai_provider(prompt, request.enrichment_type)

            # Parse response
            suggestions = self._parse_response(
                ai_response,
                request.enrichment_type
            )

            result.suggestions = suggestions
            result.status = EnrichmentStatus.COMPLETED
            result.prompt_tokens = ai_response.get("prompt_tokens", 0)
            result.completion_tokens = ai_response.get("completion_tokens", 0)
            result.total_tokens = ai_response.get("total_tokens", 0)

            # Queue for approval if required
            if self.require_approval and suggestions:
                _create_approval_queue_entry(request, result)

        except Exception as e:
            result.status = EnrichmentStatus.FAILED
            result.error_message = str(e)
            _log_enrichment_error(request, str(e))

        result.processing_time_ms = int((time.time() - start_time) * 1000)

        # Log the result
        _log_enrichment_result(request, result)

        return result

    def _build_prompt(self, request: EnrichmentRequest) -> str:
        """Build the prompt for the AI provider.

        Args:
            request: EnrichmentRequest with context

        Returns:
            Formatted prompt string
        """
        template = PROMPT_TEMPLATES.get(request.enrichment_type)
        if not template:
            raise ValueError(f"No template for enrichment type: {request.enrichment_type}")

        # Format product info
        product_info = self._format_product_info(request.product_data)

        # Build template variables
        variables = {
            "product_info": product_info,
            "target_audience": request.target_audience,
            "language": request.language,
        }

        # Add special variables for specific types
        if request.enrichment_type == EnrichmentType.CATEGORY_SUGGESTION:
            categories = request.product_data.get("_available_categories", [])
            variables["available_categories"] = "\n".join(f"- {c}" for c in categories)

        if request.enrichment_type == EnrichmentType.ATTRIBUTE_EXTRACTION:
            attrs = request.product_data.get("_required_attributes", [])
            variables["required_attributes"] = "\n".join(f"- {a}" for a in attrs)

        if request.enrichment_type == EnrichmentType.IMAGE_ALT_TEXT:
            variables["image_context"] = request.additional_context or "Main product image"

        # Format template
        prompt = template.format(**variables)

        # Add language instruction if not English
        if request.language != "en":
            language_name = _get_language_name(request.language)
            prompt += f"\n\nIMPORTANT: Generate the content in {language_name}."

        # Add additional context
        if request.additional_context:
            prompt += f"\n\nAdditional context: {request.additional_context}"

        return prompt

    def _format_product_info(self, product_data: Dict[str, Any]) -> str:
        """Format product data for the prompt.

        Args:
            product_data: Product data dictionary

        Returns:
            Formatted product information string
        """
        lines = []

        # Core fields
        if product_data.get("item_name"):
            lines.append(f"Product Name: {product_data['item_name']}")

        if product_data.get("item_code"):
            lines.append(f"SKU/Item Code: {product_data['item_code']}")

        if product_data.get("brand"):
            lines.append(f"Brand: {product_data['brand']}")

        if product_data.get("item_group"):
            lines.append(f"Category: {product_data['item_group']}")

        if product_data.get("description"):
            lines.append(f"Existing Description: {product_data['description']}")

        # PIM fields
        if product_data.get("pim_title"):
            lines.append(f"PIM Title: {product_data['pim_title']}")

        if product_data.get("pim_description"):
            lines.append(f"PIM Description: {product_data['pim_description']}")

        # Attributes
        attributes = product_data.get("attributes", [])
        if attributes:
            lines.append("\nAttributes:")
            for attr in attributes:
                if isinstance(attr, dict):
                    lines.append(f"  - {attr.get('attribute')}: {attr.get('attribute_value')}")
                else:
                    lines.append(f"  - {attr}")

        # Specifications
        specs = product_data.get("specifications", {})
        if specs:
            lines.append("\nSpecifications:")
            for key, value in specs.items():
                lines.append(f"  - {key}: {value}")

        # Additional fields
        optional_fields = [
            ("weight_per_unit", "Weight"),
            ("net_weight", "Net Weight"),
            ("stock_uom", "Unit of Measure"),
            ("country_of_origin", "Country of Origin"),
            ("customs_tariff_number", "HS Code"),
        ]

        for field, label in optional_fields:
            if product_data.get(field):
                lines.append(f"{label}: {product_data[field]}")

        return "\n".join(lines)

    def _call_ai_provider(
        self,
        prompt: str,
        enrichment_type: EnrichmentType
    ) -> Dict[str, Any]:
        """Call the AI provider API.

        Args:
            prompt: The prompt to send
            enrichment_type: Type of enrichment for token limits

        Returns:
            Dictionary with response and token usage
        """
        max_tokens = MAX_TOKENS.get(enrichment_type, 300)

        if self.provider == AIProvider.OPENAI:
            return self._call_openai(prompt, max_tokens)
        elif self.provider == AIProvider.ANTHROPIC:
            return self._call_anthropic(prompt, max_tokens)
        elif self.provider == AIProvider.GOOGLE_GEMINI:
            return self._call_gemini(prompt, max_tokens)
        elif self.provider == AIProvider.AZURE_OPENAI:
            return self._call_azure_openai(prompt, max_tokens)
        else:
            raise ValueError(f"Unsupported AI provider: {self.provider}")

    def _call_openai(self, prompt: str, max_tokens: int) -> Dict[str, Any]:
        """Call OpenAI API.

        Args:
            prompt: The prompt to send
            max_tokens: Maximum tokens for response

        Returns:
            Dictionary with response and token usage
        """
        import requests

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        data = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a professional product content writer specializing in e-commerce product descriptions. Generate high-quality, accurate, and engaging content."
                },
                {"role": "user", "content": prompt}
            ],
            "max_tokens": max_tokens,
            "temperature": 0.7,
        }

        response = requests.post(
            API_ENDPOINTS[AIProvider.OPENAI],
            headers=headers,
            json=data,
            timeout=60
        )

        if response.status_code != 200:
            error_msg = response.json().get("error", {}).get("message", response.text)
            raise Exception(f"OpenAI API error: {error_msg}")

        result = response.json()
        usage = result.get("usage", {})

        return {
            "content": result["choices"][0]["message"]["content"],
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }

    def _call_anthropic(self, prompt: str, max_tokens: int) -> Dict[str, Any]:
        """Call Anthropic Claude API.

        Args:
            prompt: The prompt to send
            max_tokens: Maximum tokens for response

        Returns:
            Dictionary with response and token usage
        """
        import requests

        headers = {
            "x-api-key": self._api_key,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }

        data = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "system": "You are a professional product content writer specializing in e-commerce product descriptions. Generate high-quality, accurate, and engaging content.",
        }

        response = requests.post(
            API_ENDPOINTS[AIProvider.ANTHROPIC],
            headers=headers,
            json=data,
            timeout=60
        )

        if response.status_code != 200:
            error_data = response.json()
            error_msg = error_data.get("error", {}).get("message", response.text)
            raise Exception(f"Anthropic API error: {error_msg}")

        result = response.json()
        usage = result.get("usage", {})

        return {
            "content": result["content"][0]["text"],
            "prompt_tokens": usage.get("input_tokens", 0),
            "completion_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
        }

    def _call_gemini(self, prompt: str, max_tokens: int) -> Dict[str, Any]:
        """Call Google Gemini API.

        Args:
            prompt: The prompt to send
            max_tokens: Maximum tokens for response

        Returns:
            Dictionary with response and token usage
        """
        import requests

        endpoint = API_ENDPOINTS[AIProvider.GOOGLE_GEMINI].format(model=self.model)
        url = f"{endpoint}?key={self._api_key}"

        data = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": f"System: You are a professional product content writer specializing in e-commerce product descriptions.\n\nUser: {prompt}"
                        }
                    ]
                }
            ],
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": 0.7,
            }
        }

        response = requests.post(
            url,
            json=data,
            timeout=60
        )

        if response.status_code != 200:
            error_msg = response.json().get("error", {}).get("message", response.text)
            raise Exception(f"Gemini API error: {error_msg}")

        result = response.json()

        content = ""
        if result.get("candidates"):
            content = result["candidates"][0]["content"]["parts"][0]["text"]

        # Gemini doesn't always return token counts
        usage = result.get("usageMetadata", {})

        return {
            "content": content,
            "prompt_tokens": usage.get("promptTokenCount", 0),
            "completion_tokens": usage.get("candidatesTokenCount", 0),
            "total_tokens": usage.get("totalTokenCount", 0),
        }

    def _call_azure_openai(self, prompt: str, max_tokens: int) -> Dict[str, Any]:
        """Call Azure OpenAI API.

        Args:
            prompt: The prompt to send
            max_tokens: Maximum tokens for response

        Returns:
            Dictionary with response and token usage
        """
        # Azure OpenAI requires additional configuration
        # This is a placeholder - would need endpoint URL from settings
        raise NotImplementedError(
            "Azure OpenAI requires additional endpoint configuration. "
            "Please use OpenAI or Anthropic instead."
        )

    def _parse_response(
        self,
        ai_response: Dict[str, Any],
        enrichment_type: EnrichmentType
    ) -> List[EnrichmentSuggestion]:
        """Parse AI response into suggestions.

        Args:
            ai_response: Response from AI provider
            enrichment_type: Type of enrichment

        Returns:
            List of EnrichmentSuggestion objects
        """
        content = ai_response.get("content", "").strip()

        if not content:
            return []

        suggestions = []

        # Parse based on enrichment type
        if enrichment_type in [
            EnrichmentType.DESCRIPTION_SHORT,
            EnrichmentType.DESCRIPTION_LONG,
            EnrichmentType.SEO_TITLE,
            EnrichmentType.META_DESCRIPTION,
            EnrichmentType.IMAGE_ALT_TEXT,
        ]:
            # Single text response
            suggestions.append(EnrichmentSuggestion(
                content=content,
                confidence=0.85,
                enrichment_type=enrichment_type,
            ))

        elif enrichment_type == EnrichmentType.BULLET_POINTS:
            # Parse bullet points
            lines = content.split("\n")
            bullet_points = []
            for line in lines:
                line = line.strip()
                if line:
                    # Remove bullet characters
                    line = line.lstrip("•-*·►▪")
                    line = line.strip()
                    if line:
                        bullet_points.append(line)

            if bullet_points:
                suggestions.append(EnrichmentSuggestion(
                    content="\n".join(f"• {bp}" for bp in bullet_points),
                    confidence=0.82,
                    enrichment_type=enrichment_type,
                    metadata={"bullet_count": len(bullet_points)},
                ))

        elif enrichment_type in [EnrichmentType.KEYWORDS, EnrichmentType.TAGS]:
            # Parse comma-separated list
            items = [k.strip() for k in content.split(",") if k.strip()]
            suggestions.append(EnrichmentSuggestion(
                content=", ".join(items),
                confidence=0.80,
                enrichment_type=enrichment_type,
                metadata={"count": len(items)},
            ))

        elif enrichment_type == EnrichmentType.CATEGORY_SUGGESTION:
            # Parse JSON response
            try:
                data = json.loads(content)
                suggestions.append(EnrichmentSuggestion(
                    content=json.dumps(data),
                    confidence=0.75,
                    enrichment_type=enrichment_type,
                    metadata={
                        "primary": data.get("primary"),
                        "secondary": data.get("secondary", []),
                        "reasoning": data.get("reasoning"),
                    },
                ))
            except json.JSONDecodeError:
                # Fallback to raw content
                suggestions.append(EnrichmentSuggestion(
                    content=content,
                    confidence=0.60,
                    enrichment_type=enrichment_type,
                ))

        elif enrichment_type == EnrichmentType.ATTRIBUTE_EXTRACTION:
            # Parse JSON response
            try:
                data = json.loads(content)
                attributes = data.get("attributes", {})

                for attr_name, attr_data in attributes.items():
                    if isinstance(attr_data, dict):
                        suggestions.append(EnrichmentSuggestion(
                            content=str(attr_data.get("value")),
                            confidence=attr_data.get("confidence", 0.7),
                            enrichment_type=enrichment_type,
                            metadata={"attribute_name": attr_name},
                        ))
            except json.JSONDecodeError:
                suggestions.append(EnrichmentSuggestion(
                    content=content,
                    confidence=0.50,
                    enrichment_type=enrichment_type,
                ))

        return suggestions


# =============================================================================
# Public API Functions
# =============================================================================

def generate_product_description(
    product: str,
    description_type: str = "long",
    language: str = "en",
    target_audience: str = "general consumers",
    async_generate: bool = False
) -> Dict[str, Any]:
    """Generate a product description using AI.

    This is the main API function for generating descriptions.

    Args:
        product: Product Master name
        description_type: "short" or "long"
        language: Target language code
        target_audience: Target audience description
        async_generate: If True, process in background

    Returns:
        Dictionary with generation result or job ID
    """
    import frappe

    if async_generate:
        job = frappe.enqueue(
            "frappe_pim.pim.services.ai_enrichment._generate_description_job",
            queue="default",
            timeout=120,
            product=product,
            description_type=description_type,
            language=language,
            target_audience=target_audience,
        )
        return {
            "success": True,
            "job_id": job.id if hasattr(job, "id") else str(job),
            "status": "queued"
        }

    service = AIEnrichmentService()
    result = service.generate_description(
        product=product,
        description_type=description_type,
        language=language,
        target_audience=target_audience,
    )

    return result.to_dict()


def generate_seo_content(
    product: str,
    content_types: Optional[List[str]] = None,
    language: str = "en"
) -> Dict[str, Any]:
    """Generate SEO content for a product.

    Args:
        product: Product Master name
        content_types: List of content types to generate
        language: Target language code

    Returns:
        Dictionary with results for each content type
    """
    service = AIEnrichmentService()
    results = service.generate_seo_content(
        product=product,
        content_types=content_types,
        language=language,
    )

    return {
        content_type: result.to_dict()
        for content_type, result in results.items()
    }


def generate_bullet_points(
    product: str,
    count: int = 5,
    language: str = "en"
) -> Dict[str, Any]:
    """Generate bullet point features for a product.

    Args:
        product: Product Master name
        count: Number of bullet points
        language: Target language code

    Returns:
        Dictionary with generation result
    """
    service = AIEnrichmentService()
    result = service.generate_bullet_points(
        product=product,
        count=count,
        language=language,
    )

    return result.to_dict()


def extract_product_attributes(
    product: str,
    required_attributes: List[str]
) -> Dict[str, Any]:
    """Extract attributes from product data using AI.

    Args:
        product: Product Master name
        required_attributes: List of attribute names to extract

    Returns:
        Dictionary with extraction result
    """
    service = AIEnrichmentService()
    result = service.extract_attributes(
        product=product,
        required_attributes=required_attributes,
    )

    return result.to_dict()


def suggest_product_categories(
    product: str,
    available_categories: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Suggest categories for a product using AI.

    Args:
        product: Product Master name
        available_categories: List of available categories

    Returns:
        Dictionary with category suggestions
    """
    service = AIEnrichmentService()
    result = service.suggest_categories(
        product=product,
        available_categories=available_categories,
    )

    return result.to_dict()


def enrich_product(
    product: str,
    enrichment_types: Optional[List[str]] = None,
    language: str = "en",
    target_audience: str = "general consumers"
) -> Dict[str, Any]:
    """Enrich a product with multiple AI-generated content types.

    Args:
        product: Product Master name
        enrichment_types: List of content types to generate
        language: Target language code
        target_audience: Target audience description

    Returns:
        Dictionary with all enrichment results
    """
    service = AIEnrichmentService()
    results = service.enrich_product(
        product=product,
        enrichment_types=enrichment_types,
        language=language,
        target_audience=target_audience,
    )

    return {
        enrichment_type: result.to_dict()
        for enrichment_type, result in results.items()
    }


def bulk_enrich_products(
    products: List[str],
    enrichment_types: Optional[List[str]] = None,
    language: str = "en",
    async_process: bool = True
) -> Dict[str, Any]:
    """Enrich multiple products with AI-generated content.

    Args:
        products: List of Product Master names
        enrichment_types: List of content types to generate
        language: Target language code
        async_process: If True, process in background

    Returns:
        Dictionary with bulk enrichment results
    """
    service = AIEnrichmentService()
    result = service.bulk_enrich(
        products=products,
        enrichment_types=enrichment_types,
        language=language,
        async_process=async_process,
    )

    return result.to_dict()


def get_enrichment_status(request_id: str) -> Optional[Dict[str, Any]]:
    """Get the status of an enrichment request.

    Args:
        request_id: The enrichment request ID

    Returns:
        Dictionary with status or None if not found
    """
    return _get_enrichment_log(request_id)


def approve_enrichment(
    queue_entry: str,
    approved_content: Optional[str] = None
) -> Dict[str, Any]:
    """Approve an AI enrichment suggestion.

    Args:
        queue_entry: AI Approval Queue entry name
        approved_content: Optional modified content (uses suggestion if not provided)

    Returns:
        Dictionary with approval result
    """
    return _process_approval(queue_entry, approved=True, content=approved_content)


def reject_enrichment(
    queue_entry: str,
    rejection_reason: Optional[str] = None
) -> Dict[str, Any]:
    """Reject an AI enrichment suggestion.

    Args:
        queue_entry: AI Approval Queue entry name
        rejection_reason: Reason for rejection

    Returns:
        Dictionary with rejection result
    """
    return _process_approval(queue_entry, approved=False, reason=rejection_reason)


def get_pending_approvals(
    product: Optional[str] = None,
    enrichment_type: Optional[str] = None,
    limit: int = 50
) -> Dict[str, Any]:
    """Get pending AI enrichment approvals.

    Args:
        product: Optional filter by product
        enrichment_type: Optional filter by enrichment type
        limit: Maximum entries to return

    Returns:
        Dictionary with pending approvals
    """
    import frappe

    filters = {"status": "Pending"}

    if product:
        filters["product"] = product

    if enrichment_type:
        filters["enrichment_type"] = enrichment_type

    try:
        entries = frappe.get_all(
            "AI Approval Queue",
            filters=filters,
            fields=[
                "name", "product", "enrichment_type", "suggested_content",
                "confidence_score", "created_at", "ai_provider", "ai_model"
            ],
            order_by="created_at desc",
            limit=limit
        )

        return {
            "success": True,
            "count": len(entries),
            "entries": entries
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "count": 0,
            "entries": []
        }


def test_ai_connection() -> Dict[str, Any]:
    """Test the AI provider connection.

    Returns:
        Dictionary with connection test result
    """
    from frappe_pim.pim.doctype.pim_settings.pim_settings import test_ai_connection as _test
    return _test()


def get_available_enrichment_types() -> List[Dict[str, str]]:
    """Get list of available enrichment types.

    Returns:
        List of enrichment type information
    """
    return [
        {"value": et.value, "label": et.value.replace("_", " ").title()}
        for et in EnrichmentType
    ]


def get_ai_providers() -> List[Dict[str, str]]:
    """Get list of supported AI providers.

    Returns:
        List of provider information
    """
    return [
        {"value": p.value, "label": p.value}
        for p in AIProvider
    ]


# =============================================================================
# Helper Functions (Private)
# =============================================================================

def _get_ai_config() -> Optional[Dict[str, Any]]:
    """Get AI configuration from PIM Settings.

    Returns:
        Dictionary with AI config or None
    """
    import frappe

    try:
        if not frappe.db.exists("DocType", "PIM Settings"):
            return None

        settings = frappe.get_cached_doc("PIM Settings")

        if not settings.enable_ai_enrichment:
            return None

        return {
            "provider": settings.ai_provider,
            "model": settings.ai_model,
            "require_approval": settings.ai_require_approval,
        }

    except Exception:
        return None


def _get_ai_api_key() -> Optional[str]:
    """Get the AI API key from PIM Settings.

    Returns:
        Decrypted API key or None
    """
    import frappe

    try:
        settings = frappe.get_cached_doc("PIM Settings")
        return settings.get_password("ai_api_key")
    except Exception:
        return None


def _get_product_data(product_name: str) -> Optional[Dict[str, Any]]:
    """Get product data for enrichment.

    Args:
        product_name: Product Master name

    Returns:
        Dictionary with product data or None
    """
    import frappe

    try:
        # Try Product Master first
        if frappe.db.exists("Product Master", product_name):
            doc = frappe.get_doc("Product Master", product_name)
            data = doc.as_dict()

            # Get attributes
            if hasattr(doc, "attributes") and doc.attributes:
                data["attributes"] = [
                    {"attribute": a.attribute, "attribute_value": a.attribute_value}
                    for a in doc.attributes
                ]

            return data

        # Try ERPNext Item
        if frappe.db.exists("Item", product_name):
            doc = frappe.get_doc("Item", product_name)
            data = doc.as_dict()

            # Get item attributes
            if hasattr(doc, "attributes") and doc.attributes:
                data["attributes"] = [
                    {"attribute": a.attribute, "attribute_value": a.attribute_value}
                    for a in doc.attributes
                ]

            return data

        return None

    except Exception:
        return None


def _get_available_categories() -> List[str]:
    """Get available product categories.

    Returns:
        List of category names
    """
    import frappe

    try:
        categories = frappe.get_all(
            "Item Group",
            filters={"is_group": 0},
            pluck="name",
            limit=100
        )
        return categories
    except Exception:
        return []


def _get_language_name(language_code: str) -> str:
    """Get language name from code.

    Args:
        language_code: ISO language code

    Returns:
        Language name
    """
    language_map = {
        "en": "English",
        "tr": "Turkish",
        "de": "German",
        "fr": "French",
        "es": "Spanish",
        "it": "Italian",
        "pt": "Portuguese",
        "nl": "Dutch",
        "pl": "Polish",
        "ru": "Russian",
        "zh": "Chinese",
        "ja": "Japanese",
        "ko": "Korean",
        "ar": "Arabic",
    }
    return language_map.get(language_code, language_code)


def _create_approval_queue_entry(
    request: EnrichmentRequest,
    result: EnrichmentResult
) -> Optional[str]:
    """Create an entry in the AI Approval Queue.

    Args:
        request: Original enrichment request
        result: Enrichment result with suggestions

    Returns:
        Queue entry name if created
    """
    import frappe

    if not result.suggestions:
        return None

    try:
        # Check if AI Approval Queue DocType exists
        if not frappe.db.exists("DocType", "AI Approval Queue"):
            return None

        for suggestion in result.suggestions:
            entry = frappe.get_doc({
                "doctype": "AI Approval Queue",
                "product": request.product,
                "enrichment_type": request.enrichment_type.value,
                "suggested_content": suggestion.content,
                "confidence_score": suggestion.confidence,
                "ai_provider": result.provider.value if result.provider else None,
                "ai_model": result.model,
                "request_id": result.request_id,
                "status": "Pending",
                "created_at": datetime.utcnow(),
            })
            entry.insert(ignore_permissions=True)

        frappe.db.commit()
        return entry.name

    except Exception as e:
        frappe.log_error(
            message=f"Failed to create approval queue entry: {str(e)}",
            title="AI Enrichment - Approval Queue Error"
        )
        return None


def _process_approval(
    queue_entry: str,
    approved: bool,
    content: Optional[str] = None,
    reason: Optional[str] = None
) -> Dict[str, Any]:
    """Process an approval/rejection.

    Args:
        queue_entry: AI Approval Queue entry name
        approved: Whether approved
        content: Optional content override
        reason: Rejection reason

    Returns:
        Dictionary with result
    """
    import frappe

    try:
        if not frappe.db.exists("AI Approval Queue", queue_entry):
            return {
                "success": False,
                "error": f"Queue entry not found: {queue_entry}"
            }

        entry = frappe.get_doc("AI Approval Queue", queue_entry)

        if approved:
            entry.status = "Approved"
            entry.approved_content = content or entry.suggested_content
            entry.approved_by = frappe.session.user
            entry.approved_at = datetime.utcnow()

            # Apply to product
            _apply_enrichment_to_product(
                entry.product,
                entry.enrichment_type,
                entry.approved_content
            )

        else:
            entry.status = "Rejected"
            entry.rejection_reason = reason
            entry.rejected_by = frappe.session.user
            entry.rejected_at = datetime.utcnow()

        entry.save(ignore_permissions=True)
        frappe.db.commit()

        return {
            "success": True,
            "status": entry.status,
            "queue_entry": queue_entry
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def _apply_enrichment_to_product(
    product: str,
    enrichment_type: str,
    content: str
) -> bool:
    """Apply enriched content to product.

    Args:
        product: Product Master name
        enrichment_type: Type of enrichment
        content: Content to apply

    Returns:
        True if applied successfully
    """
    import frappe

    field_mapping = {
        "description_short": "pim_description",
        "description_long": "description",
        "seo_title": "pim_title",
        "keywords": "pim_keywords",
        "meta_description": "pim_meta_description",
        "bullet_points": "pim_bullet_points",
    }

    target_field = field_mapping.get(enrichment_type)
    if not target_field:
        return False

    try:
        # Try Product Master
        if frappe.db.exists("Product Master", product):
            frappe.db.set_value(
                "Product Master",
                product,
                target_field,
                content,
                update_modified=True
            )
            frappe.db.commit()
            return True

        # Try Item with custom field
        if frappe.db.exists("Item", product):
            frappe.db.set_value(
                "Item",
                product,
                target_field,
                content,
                update_modified=True
            )
            frappe.db.commit()
            return True

        return False

    except Exception:
        return False


def _log_enrichment_result(request: EnrichmentRequest, result: EnrichmentResult):
    """Log enrichment result.

    Args:
        request: Original request
        result: Enrichment result
    """
    import frappe

    try:
        # Check if AI Enrichment Log DocType exists
        if frappe.db.exists("DocType", "AI Enrichment Log"):
            log = frappe.get_doc({
                "doctype": "AI Enrichment Log",
                "request_id": result.request_id,
                "product": request.product,
                "enrichment_type": request.enrichment_type.value,
                "status": result.status.value,
                "provider": result.provider.value if result.provider else None,
                "model": result.model,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "processing_time_ms": result.processing_time_ms,
                "error_message": result.error_message,
                "created_at": datetime.utcnow(),
            })
            log.insert(ignore_permissions=True)
            frappe.db.commit()

    except Exception:
        pass  # Silently fail logging


def _log_enrichment_error(request: EnrichmentRequest, error: str):
    """Log enrichment error.

    Args:
        request: Original request
        error: Error message
    """
    import frappe

    frappe.log_error(
        message=f"""
AI Enrichment Error

Product: {request.product}
Enrichment Type: {request.enrichment_type.value}
Request ID: {request.request_id}

Error: {error}
        """,
        title=f"AI Enrichment Error - {request.product}"
    )


def _get_enrichment_log(request_id: str) -> Optional[Dict[str, Any]]:
    """Get enrichment log by request ID.

    Args:
        request_id: Request ID

    Returns:
        Log data or None
    """
    import frappe

    try:
        if not frappe.db.exists("DocType", "AI Enrichment Log"):
            return None

        logs = frappe.get_all(
            "AI Enrichment Log",
            filters={"request_id": request_id},
            fields=["*"],
            limit=1
        )

        return logs[0] if logs else None

    except Exception:
        return None


def _bulk_enrich_job(
    products: List[str],
    enrichment_types: Optional[List[str]] = None,
    language: str = "en"
):
    """Background job for bulk enrichment.

    Args:
        products: List of product names
        enrichment_types: Types to generate
        language: Target language
    """
    service = AIEnrichmentService()
    service.bulk_enrich(
        products=products,
        enrichment_types=enrichment_types,
        language=language,
        async_process=False,
    )


def _generate_description_job(
    product: str,
    description_type: str,
    language: str,
    target_audience: str
):
    """Background job for description generation.

    Args:
        product: Product name
        description_type: "short" or "long"
        language: Target language
        target_audience: Target audience
    """
    service = AIEnrichmentService()
    service.generate_description(
        product=product,
        description_type=description_type,
        language=language,
        target_audience=target_audience,
    )


# =============================================================================
# Frappe API Wrappers
# =============================================================================

def _wrap_for_whitelist():
    """Wrap functions for Frappe whitelist at runtime."""
    import frappe

    functions = [
        "generate_product_description",
        "generate_seo_content",
        "generate_bullet_points",
        "extract_product_attributes",
        "suggest_product_categories",
        "enrich_product",
        "bulk_enrich_products",
        "get_enrichment_status",
        "approve_enrichment",
        "reject_enrichment",
        "get_pending_approvals",
        "test_ai_connection",
        "get_available_enrichment_types",
        "get_ai_providers",
    ]

    module = __import__(__name__)
    for name in __name__.split(".")[1:]:
        module = getattr(module, name)

    for func_name in functions:
        func = getattr(module, func_name)
        if not getattr(func, "_whitelisted", False):
            whitelisted = frappe.whitelist()(func)
            setattr(module, func_name, whitelisted)


# Apply whitelist decorators when module is loaded in Frappe context
try:
    _wrap_for_whitelist()
except Exception:
    pass  # Not in Frappe context
