"""AI Categorization Service

This module provides AI-powered product categorization services including:
- Automatic category assignment based on product data
- Multi-taxonomy support (GPC, UNSPSC, custom hierarchies)
- Category hierarchy matching and prediction
- Channel-specific category mapping
- Confidence scoring for category suggestions
- Bulk categorization for catalog imports
- Category recommendation learning

The service supports multiple AI providers:
- OpenAI (GPT-4, GPT-3.5-turbo)
- Anthropic Claude (Claude 3 Opus, Sonnet, Haiku)
- Google Gemini

Key Concepts:
- Taxonomy: A category hierarchy system (GPC, UNSPSC, custom)
- Category Suggestion: AI-suggested category with confidence score
- Category Mapping: Mapping between internal and channel categories
- Category Path: Full path from root to leaf category
- Category Prediction: ML-based category prediction from product attributes

Human-in-the-Loop Workflow:
1. User requests categorization for a product
2. System analyzes product data (title, description, attributes)
3. AI suggests primary and alternative categories
4. Results are queued for human review (if required)
5. Approved categories are applied to the product
6. Learning from approvals improves future predictions

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Union


# =============================================================================
# Constants and Enums
# =============================================================================

class CategorizationProvider(Enum):
    """Supported AI providers for categorization."""
    OPENAI = "OpenAI"
    ANTHROPIC = "Anthropic"
    GOOGLE_GEMINI = "Google Gemini"


class TaxonomyType(Enum):
    """Standard taxonomy types."""
    GPC = "gpc"  # GS1 Global Product Classification
    UNSPSC = "unspsc"  # United Nations Standard Products and Services Code
    GOOGLE_PRODUCT_CATEGORY = "google_product_category"
    AMAZON_BROWSE_NODE = "amazon_browse_node"
    FACEBOOK_CATEGORY = "facebook_category"
    TRENDYOL_CATEGORY = "trendyol_category"
    HEPSIBURADA_CATEGORY = "hepsiburada_category"
    N11_CATEGORY = "n11_category"
    EBAY_CATEGORY = "ebay_category"
    CUSTOM = "custom"  # Custom/internal taxonomy


class CategorizationStatus(Enum):
    """Status of a categorization request."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"


class ConfidenceLevel(Enum):
    """Confidence level categories."""
    VERY_HIGH = "very_high"  # >= 0.95
    HIGH = "high"            # >= 0.85
    MEDIUM = "medium"        # >= 0.70
    LOW = "low"              # >= 0.50
    VERY_LOW = "very_low"    # < 0.50


class MatchType(Enum):
    """How a category was matched."""
    EXACT = "exact"              # Direct match
    SEMANTIC = "semantic"        # AI semantic matching
    KEYWORD = "keyword"          # Keyword-based matching
    ATTRIBUTE = "attribute"      # Attribute-based matching
    HISTORICAL = "historical"    # Based on historical data
    RULE_BASED = "rule_based"    # Based on configured rules
    FALLBACK = "fallback"        # Default/fallback category


# Default AI models per provider
DEFAULT_MODELS = {
    CategorizationProvider.OPENAI: "gpt-4-turbo-preview",
    CategorizationProvider.ANTHROPIC: "claude-3-sonnet-20240229",
    CategorizationProvider.GOOGLE_GEMINI: "gemini-pro",
}

# API endpoints
API_ENDPOINTS = {
    CategorizationProvider.OPENAI: "https://api.openai.com/v1/chat/completions",
    CategorizationProvider.ANTHROPIC: "https://api.anthropic.com/v1/messages",
    CategorizationProvider.GOOGLE_GEMINI: "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
}

# Rate limits (requests per minute)
RATE_LIMITS = {
    CategorizationProvider.OPENAI: 60,
    CategorizationProvider.ANTHROPIC: 50,
    CategorizationProvider.GOOGLE_GEMINI: 60,
}

# Maximum products per bulk categorization batch
MAX_BATCH_SIZE = 50

# Maximum categories to return per suggestion
MAX_SUGGESTIONS = 5

# Maximum tokens for categorization responses
MAX_TOKENS = 1000


# =============================================================================
# Prompt Templates
# =============================================================================

CATEGORIZATION_PROMPT_TEMPLATE = """You are an expert product categorization specialist. Your task is to accurately categorize products into the appropriate category hierarchy.

PRODUCT INFORMATION:
{product_info}

TAXONOMY: {taxonomy_name}
{taxonomy_description}

AVAILABLE CATEGORIES:
{available_categories}

REQUIREMENTS:
1. Select the most specific and accurate category for this product
2. Provide a primary category recommendation
3. Suggest up to 3 alternative categories if applicable
4. Provide confidence scores (0-1) for each suggestion
5. Explain your reasoning briefly
6. Consider the product's attributes, description, and any specifications
7. If the product could fit multiple categories, prioritize based on primary function

IMPORTANT:
- Only suggest categories from the provided list
- Category codes must be exact matches
- Consider the full category hierarchy/path

Respond in JSON format:
{{
    "primary": {{
        "category_code": "code",
        "category_name": "Full Category Name",
        "category_path": ["Level 1", "Level 2", "Level 3"],
        "confidence": 0.95,
        "reasoning": "Brief explanation"
    }},
    "alternatives": [
        {{
            "category_code": "code",
            "category_name": "Full Category Name",
            "category_path": ["Level 1", "Level 2", "Level 3"],
            "confidence": 0.75,
            "reasoning": "Brief explanation"
        }}
    ],
    "attributes_used": ["attr1", "attr2"],
    "keywords_matched": ["keyword1", "keyword2"]
}}"""


MULTI_TAXONOMY_PROMPT_TEMPLATE = """You are an expert product categorization specialist. Your task is to categorize a product across multiple taxonomy systems.

PRODUCT INFORMATION:
{product_info}

TAXONOMIES TO CATEGORIZE:
{taxonomies}

For each taxonomy, select the most appropriate category. Consider that different taxonomies have different purposes:
- GPC (GS1): Global retail product classification
- UNSPSC: Procurement and services classification
- Google Product Category: E-commerce and shopping ads
- Amazon Browse Nodes: Amazon marketplace listing
- Custom: Internal business categorization

Respond in JSON format:
{{
    "categorizations": {{
        "taxonomy_code": {{
            "category_code": "code",
            "category_name": "Name",
            "category_path": ["Path"],
            "confidence": 0.9,
            "reasoning": "explanation"
        }}
    }},
    "product_type": "Brief product type description",
    "key_attributes": ["attr1", "attr2"]
}}"""


CHANNEL_MAPPING_PROMPT_TEMPLATE = """You are an expert in e-commerce channel category mapping. Your task is to map a product's category to the appropriate channel-specific category.

PRODUCT INFORMATION:
{product_info}

CURRENT CATEGORY:
{current_category}

TARGET CHANNEL: {channel_name}
{channel_description}

AVAILABLE TARGET CATEGORIES:
{target_categories}

Map the product to the most appropriate category in the target channel's taxonomy.
Consider:
1. Category equivalence between taxonomies
2. Channel-specific category requirements
3. Best practices for the target channel

Respond in JSON format:
{{
    "mapped_category": {{
        "category_code": "code",
        "category_name": "Name",
        "category_path": ["Path"],
        "confidence": 0.9
    }},
    "required_attributes": ["attr1", "attr2"],
    "reasoning": "Brief explanation of mapping logic"
}}"""


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class CategoryInfo:
    """Information about a category."""
    code: str
    name: str
    path: List[str] = field(default_factory=list)
    level: int = 0
    parent_code: Optional[str] = None
    taxonomy: TaxonomyType = TaxonomyType.CUSTOM
    attributes: List[str] = field(default_factory=list)
    is_leaf: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "code": self.code,
            "name": self.name,
            "path": self.path,
            "level": self.level,
            "parent_code": self.parent_code,
            "taxonomy": self.taxonomy.value,
            "attributes": self.attributes,
            "is_leaf": self.is_leaf,
        }

    @property
    def full_path(self) -> str:
        """Get full path as string."""
        return " > ".join(self.path) if self.path else self.name


@dataclass
class CategorySuggestion:
    """A single category suggestion from AI."""
    category: CategoryInfo
    confidence: float
    match_type: MatchType = MatchType.SEMANTIC
    reasoning: Optional[str] = None
    keywords_matched: List[str] = field(default_factory=list)
    attributes_used: List[str] = field(default_factory=list)

    @property
    def confidence_level(self) -> ConfidenceLevel:
        """Get confidence level category."""
        if self.confidence >= 0.95:
            return ConfidenceLevel.VERY_HIGH
        elif self.confidence >= 0.85:
            return ConfidenceLevel.HIGH
        elif self.confidence >= 0.70:
            return ConfidenceLevel.MEDIUM
        elif self.confidence >= 0.50:
            return ConfidenceLevel.LOW
        else:
            return ConfidenceLevel.VERY_LOW

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "category": self.category.to_dict(),
            "confidence": round(self.confidence, 3),
            "confidence_level": self.confidence_level.value,
            "match_type": self.match_type.value,
            "reasoning": self.reasoning,
            "keywords_matched": self.keywords_matched,
            "attributes_used": self.attributes_used,
        }


@dataclass
class CategorizationRequest:
    """Request for product categorization."""
    product: str
    product_data: Dict[str, Any]
    taxonomy: TaxonomyType = TaxonomyType.CUSTOM
    available_categories: Optional[List[CategoryInfo]] = None
    channel: Optional[str] = None
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "product": self.product,
            "product_data": self.product_data,
            "taxonomy": self.taxonomy.value,
            "channel": self.channel,
            "request_id": self.request_id,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class CategorizationResult:
    """Result of a categorization request."""
    request_id: str
    product: str
    status: CategorizationStatus
    taxonomy: TaxonomyType
    primary_suggestion: Optional[CategorySuggestion] = None
    alternative_suggestions: List[CategorySuggestion] = field(default_factory=list)
    provider: Optional[CategorizationProvider] = None
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
            "taxonomy": self.taxonomy.value,
            "primary_suggestion": self.primary_suggestion.to_dict() if self.primary_suggestion else None,
            "alternative_suggestions": [s.to_dict() for s in self.alternative_suggestions],
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
class BulkCategorizationResult:
    """Result of bulk categorization operation."""
    total_products: int
    successful: int = 0
    failed: int = 0
    results: List[CategorizationResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    processing_time_ms: int = 0
    job_id: Optional[str] = None

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
            "job_id": self.job_id,
        }


@dataclass
class CategoryMapping:
    """Mapping between categories across taxonomies."""
    source_taxonomy: TaxonomyType
    source_category: CategoryInfo
    target_taxonomy: TaxonomyType
    target_category: CategoryInfo
    confidence: float
    bidirectional: bool = False
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "source_taxonomy": self.source_taxonomy.value,
            "source_category": self.source_category.to_dict(),
            "target_taxonomy": self.target_taxonomy.value,
            "target_category": self.target_category.to_dict(),
            "confidence": round(self.confidence, 3),
            "bidirectional": self.bidirectional,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class CategorizationRule:
    """Rule-based categorization rule."""
    rule_id: str
    name: str
    taxonomy: TaxonomyType
    target_category: CategoryInfo
    conditions: List[Dict[str, Any]] = field(default_factory=list)
    priority: int = 100
    is_active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "taxonomy": self.taxonomy.value,
            "target_category": self.target_category.to_dict(),
            "conditions": self.conditions,
            "priority": self.priority,
            "is_active": self.is_active,
        }

    def evaluate(self, product_data: Dict[str, Any]) -> Tuple[bool, float]:
        """Evaluate if product matches rule conditions.

        Args:
            product_data: Product data dictionary

        Returns:
            Tuple of (matches, confidence)
        """
        if not self.conditions:
            return False, 0.0

        matched_conditions = 0
        total_conditions = len(self.conditions)

        for condition in self.conditions:
            field_name = condition.get("field")
            operator = condition.get("operator", "equals")
            value = condition.get("value")

            if not field_name:
                continue

            product_value = product_data.get(field_name, "")
            if isinstance(product_value, str):
                product_value = product_value.lower()
            if isinstance(value, str):
                value = value.lower()

            # Evaluate condition
            matches = False
            if operator == "equals":
                matches = product_value == value
            elif operator == "contains":
                matches = value in str(product_value) if product_value else False
            elif operator == "starts_with":
                matches = str(product_value).startswith(str(value)) if product_value else False
            elif operator == "ends_with":
                matches = str(product_value).endswith(str(value)) if product_value else False
            elif operator == "regex":
                try:
                    matches = bool(re.search(str(value), str(product_value)))
                except Exception:
                    matches = False
            elif operator == "in_list":
                if isinstance(value, list):
                    matches = product_value in [v.lower() if isinstance(v, str) else v for v in value]
                else:
                    matches = product_value in str(value).split(",")

            if matches:
                matched_conditions += 1

        if matched_conditions == total_conditions:
            return True, 0.95  # Full match, high confidence
        elif matched_conditions > total_conditions / 2:
            return True, 0.70  # Partial match, medium confidence

        return False, 0.0


# =============================================================================
# Category Taxonomy Manager
# =============================================================================

class TaxonomyManager:
    """Manages category taxonomies and their hierarchies.

    This class handles loading, caching, and querying of category taxonomies
    from various sources (database, files, APIs).
    """

    def __init__(self):
        """Initialize the taxonomy manager."""
        self._taxonomies: Dict[TaxonomyType, Dict[str, CategoryInfo]] = {}
        self._loaded: Set[TaxonomyType] = set()

    def load_taxonomy(
        self,
        taxonomy: TaxonomyType,
        force_reload: bool = False
    ) -> Dict[str, CategoryInfo]:
        """Load a taxonomy into memory.

        Args:
            taxonomy: Taxonomy type to load
            force_reload: Force reload even if cached

        Returns:
            Dictionary of category code to CategoryInfo
        """
        if taxonomy in self._loaded and not force_reload:
            return self._taxonomies.get(taxonomy, {})

        categories = {}

        if taxonomy == TaxonomyType.CUSTOM:
            categories = self._load_custom_taxonomy()
        elif taxonomy == TaxonomyType.GPC:
            categories = self._load_gpc_taxonomy()
        elif taxonomy == TaxonomyType.UNSPSC:
            categories = self._load_unspsc_taxonomy()
        elif taxonomy == TaxonomyType.GOOGLE_PRODUCT_CATEGORY:
            categories = self._load_google_taxonomy()
        else:
            categories = self._load_channel_taxonomy(taxonomy)

        self._taxonomies[taxonomy] = categories
        self._loaded.add(taxonomy)

        return categories

    def get_category(
        self,
        taxonomy: TaxonomyType,
        code: str
    ) -> Optional[CategoryInfo]:
        """Get a category by code.

        Args:
            taxonomy: Taxonomy type
            code: Category code

        Returns:
            CategoryInfo or None if not found
        """
        self.load_taxonomy(taxonomy)
        return self._taxonomies.get(taxonomy, {}).get(code)

    def get_categories_for_ai(
        self,
        taxonomy: TaxonomyType,
        max_categories: int = 500
    ) -> str:
        """Get categories formatted for AI prompt.

        Args:
            taxonomy: Taxonomy type
            max_categories: Maximum categories to include

        Returns:
            Formatted category list string
        """
        categories = self.load_taxonomy(taxonomy)

        if not categories:
            return "No categories available."

        lines = []
        count = 0
        for code, cat in categories.items():
            if count >= max_categories:
                lines.append(f"... and {len(categories) - count} more categories")
                break
            path_str = " > ".join(cat.path) if cat.path else cat.name
            lines.append(f"- {code}: {path_str}")
            count += 1

        return "\n".join(lines)

    def search_categories(
        self,
        taxonomy: TaxonomyType,
        query: str,
        limit: int = 20
    ) -> List[CategoryInfo]:
        """Search categories by name or code.

        Args:
            taxonomy: Taxonomy type
            query: Search query
            limit: Maximum results

        Returns:
            List of matching CategoryInfo
        """
        categories = self.load_taxonomy(taxonomy)
        query_lower = query.lower()
        results = []

        for code, cat in categories.items():
            if query_lower in code.lower() or query_lower in cat.name.lower():
                results.append(cat)
                if len(results) >= limit:
                    break

            # Also search in path
            for path_part in cat.path:
                if query_lower in path_part.lower() and cat not in results:
                    results.append(cat)
                    break

            if len(results) >= limit:
                break

        return results

    def get_leaf_categories(
        self,
        taxonomy: TaxonomyType
    ) -> List[CategoryInfo]:
        """Get all leaf (non-parent) categories.

        Args:
            taxonomy: Taxonomy type

        Returns:
            List of leaf CategoryInfo
        """
        categories = self.load_taxonomy(taxonomy)
        return [cat for cat in categories.values() if cat.is_leaf]

    def _load_custom_taxonomy(self) -> Dict[str, CategoryInfo]:
        """Load custom taxonomy from database."""
        import frappe

        try:
            # Try to load from Item Group
            categories = {}
            groups = frappe.get_all(
                "Item Group",
                fields=["name", "parent_item_group", "is_group", "lft", "rgt"],
                order_by="lft asc"
            )

            # Build hierarchy
            for group in groups:
                path = self._get_item_group_path(group["name"])
                categories[group["name"]] = CategoryInfo(
                    code=group["name"],
                    name=group["name"],
                    path=path,
                    level=len(path),
                    parent_code=group.get("parent_item_group"),
                    taxonomy=TaxonomyType.CUSTOM,
                    is_leaf=not group.get("is_group", False),
                )

            return categories

        except Exception:
            return {}

    def _get_item_group_path(self, group_name: str) -> List[str]:
        """Get full path for an item group."""
        import frappe

        try:
            path = []
            current = group_name
            while current:
                path.insert(0, current)
                parent = frappe.db.get_value("Item Group", current, "parent_item_group")
                if parent == current or not parent:
                    break
                current = parent
            return path
        except Exception:
            return [group_name]

    def _load_gpc_taxonomy(self) -> Dict[str, CategoryInfo]:
        """Load GPC taxonomy.

        Note: In production, this would load from GS1 data files or API.
        """
        import frappe

        try:
            # Check if GPC Category DocType exists
            if not frappe.db.exists("DocType", "GPC Category"):
                return self._get_sample_gpc_categories()

            categories = {}
            gpc_cats = frappe.get_all(
                "GPC Category",
                fields=["code", "title", "parent_code", "level", "is_leaf"],
                order_by="code asc"
            )

            for cat in gpc_cats:
                path = self._build_gpc_path(cat["code"], gpc_cats)
                categories[cat["code"]] = CategoryInfo(
                    code=cat["code"],
                    name=cat["title"],
                    path=path,
                    level=cat.get("level", 1),
                    parent_code=cat.get("parent_code"),
                    taxonomy=TaxonomyType.GPC,
                    is_leaf=cat.get("is_leaf", True),
                )

            return categories

        except Exception:
            return self._get_sample_gpc_categories()

    def _build_gpc_path(self, code: str, all_cats: List[Dict]) -> List[str]:
        """Build GPC category path."""
        cat_map = {c["code"]: c for c in all_cats}
        path = []
        current_code = code

        while current_code:
            cat = cat_map.get(current_code)
            if not cat:
                break
            path.insert(0, cat["title"])
            current_code = cat.get("parent_code")
            if current_code == code:  # Prevent infinite loop
                break

        return path

    def _get_sample_gpc_categories(self) -> Dict[str, CategoryInfo]:
        """Get sample GPC categories for testing."""
        # Sample GPC hierarchy (segment > family > class > brick)
        sample_categories = [
            ("10000000", "Food/Beverages/Tobacco", ["Food/Beverages/Tobacco"]),
            ("10001000", "Prepared/Preserved Foods", ["Food/Beverages/Tobacco", "Prepared/Preserved Foods"]),
            ("10001001", "Canned Vegetables", ["Food/Beverages/Tobacco", "Prepared/Preserved Foods", "Canned Vegetables"]),
            ("50000000", "Electronics", ["Electronics"]),
            ("50001000", "Consumer Electronics", ["Electronics", "Consumer Electronics"]),
            ("50001001", "Smartphones", ["Electronics", "Consumer Electronics", "Smartphones"]),
            ("50001002", "Tablets", ["Electronics", "Consumer Electronics", "Tablets"]),
            ("50002000", "Computer Equipment", ["Electronics", "Computer Equipment"]),
            ("50002001", "Laptops", ["Electronics", "Computer Equipment", "Laptops"]),
            ("60000000", "Apparel", ["Apparel"]),
            ("60001000", "Men's Clothing", ["Apparel", "Men's Clothing"]),
            ("60001001", "Men's Shirts", ["Apparel", "Men's Clothing", "Men's Shirts"]),
            ("60002000", "Women's Clothing", ["Apparel", "Women's Clothing"]),
            ("60002001", "Women's Dresses", ["Apparel", "Women's Clothing", "Women's Dresses"]),
            ("70000000", "Home/Garden", ["Home/Garden"]),
            ("70001000", "Furniture", ["Home/Garden", "Furniture"]),
            ("70001001", "Sofas", ["Home/Garden", "Furniture", "Sofas"]),
            ("70002000", "Kitchen", ["Home/Garden", "Kitchen"]),
            ("70002001", "Cookware", ["Home/Garden", "Kitchen", "Cookware"]),
        ]

        categories = {}
        for code, name, path in sample_categories:
            categories[code] = CategoryInfo(
                code=code,
                name=name,
                path=path,
                level=len(path),
                taxonomy=TaxonomyType.GPC,
                is_leaf=len(code) == 8,
            )

        return categories

    def _load_unspsc_taxonomy(self) -> Dict[str, CategoryInfo]:
        """Load UNSPSC taxonomy."""
        # Sample UNSPSC categories
        sample_categories = [
            ("43000000", "Information Technology Broadcasting and Telecommunications", ["IT/Broadcasting/Telecom"]),
            ("43200000", "Components for information technology or broadcasting or telecommunications", ["IT/Broadcasting/Telecom", "Components"]),
            ("43211500", "Computer accessories", ["IT/Broadcasting/Telecom", "Components", "Computer accessories"]),
            ("43211503", "Mouse devices", ["IT/Broadcasting/Telecom", "Components", "Computer accessories", "Mouse devices"]),
            ("43211507", "Keyboards", ["IT/Broadcasting/Telecom", "Components", "Computer accessories", "Keyboards"]),
            ("53000000", "Apparel and Luggage and Personal Care Products", ["Apparel/Luggage/Personal Care"]),
            ("53100000", "Clothing", ["Apparel/Luggage/Personal Care", "Clothing"]),
            ("53101500", "Shirts and tops", ["Apparel/Luggage/Personal Care", "Clothing", "Shirts and tops"]),
            ("53101600", "Pants and shorts", ["Apparel/Luggage/Personal Care", "Clothing", "Pants and shorts"]),
        ]

        categories = {}
        for code, name, path in sample_categories:
            categories[code] = CategoryInfo(
                code=code,
                name=name,
                path=path,
                level=len(path),
                taxonomy=TaxonomyType.UNSPSC,
                is_leaf=len(code) == 8,
            )

        return categories

    def _load_google_taxonomy(self) -> Dict[str, CategoryInfo]:
        """Load Google Product Category taxonomy."""
        # Sample Google Product Categories
        sample_categories = [
            ("166", "Electronics", ["Electronics"]),
            ("222", "Electronics > Computers & Tablets", ["Electronics", "Computers & Tablets"]),
            ("328", "Electronics > Computers & Tablets > Laptops", ["Electronics", "Computers & Tablets", "Laptops"]),
            ("4745", "Electronics > Computers & Tablets > Tablets", ["Electronics", "Computers & Tablets", "Tablets"]),
            ("267", "Electronics > Cell Phones & Accessories", ["Electronics", "Cell Phones & Accessories"]),
            ("268", "Electronics > Cell Phones & Accessories > Cell Phones", ["Electronics", "Cell Phones & Accessories", "Cell Phones"]),
            ("1604", "Apparel & Accessories", ["Apparel & Accessories"]),
            ("1594", "Apparel & Accessories > Clothing", ["Apparel & Accessories", "Clothing"]),
            ("5388", "Apparel & Accessories > Clothing > Shirts & Tops", ["Apparel & Accessories", "Clothing", "Shirts & Tops"]),
            ("436", "Home & Garden", ["Home & Garden"]),
            ("696", "Home & Garden > Furniture", ["Home & Garden", "Furniture"]),
            ("457", "Home & Garden > Kitchen & Dining", ["Home & Garden", "Kitchen & Dining"]),
        ]

        categories = {}
        for code, name, path in sample_categories:
            categories[code] = CategoryInfo(
                code=code,
                name=name,
                path=path,
                level=len(path),
                taxonomy=TaxonomyType.GOOGLE_PRODUCT_CATEGORY,
                is_leaf=True,
            )

        return categories

    def _load_channel_taxonomy(
        self,
        taxonomy: TaxonomyType
    ) -> Dict[str, CategoryInfo]:
        """Load channel-specific taxonomy."""
        import frappe

        try:
            # Try to load from Channel Category DocType
            doctype_name = f"{taxonomy.value.replace('_', ' ').title()} Category"
            if not frappe.db.exists("DocType", doctype_name):
                return {}

            categories = {}
            channel_cats = frappe.get_all(
                doctype_name,
                fields=["code", "name", "parent_code", "level", "full_path"],
            )

            for cat in channel_cats:
                path = cat.get("full_path", "").split(" > ") if cat.get("full_path") else [cat["name"]]
                categories[cat["code"]] = CategoryInfo(
                    code=cat["code"],
                    name=cat["name"],
                    path=path,
                    level=cat.get("level", 1),
                    parent_code=cat.get("parent_code"),
                    taxonomy=taxonomy,
                    is_leaf=True,
                )

            return categories

        except Exception:
            return {}


# =============================================================================
# AI Categorization Service
# =============================================================================

class AICategorizationService:
    """Service for AI-powered product categorization.

    This service provides high-level operations for automatically categorizing
    products using AI providers like OpenAI and Anthropic Claude.

    Attributes:
        provider: AI provider to use
        model: Specific model to use
        api_key: API key for the provider
        require_approval: Whether to require human approval
        taxonomy_manager: Manager for category taxonomies
    """

    def __init__(
        self,
        provider: Optional[CategorizationProvider] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        require_approval: bool = True
    ):
        """Initialize the AI categorization service.

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
        self.taxonomy_manager = TaxonomyManager()

    def _ensure_initialized(self):
        """Ensure the service is initialized with settings."""
        if self._initialized:
            return

        if not self._provider or not self._api_key:
            config = _get_ai_config()
            if not config:
                raise ValueError(
                    "AI categorization is not enabled. Please configure in PIM Settings."
                )

            if not self._provider:
                provider_str = config.get("provider")
                if provider_str:
                    # Map from AIProvider to CategorizationProvider
                    provider_map = {
                        "OpenAI": CategorizationProvider.OPENAI,
                        "Anthropic": CategorizationProvider.ANTHROPIC,
                        "Google Gemini": CategorizationProvider.GOOGLE_GEMINI,
                    }
                    self._provider = provider_map.get(provider_str)
                    if not self._provider:
                        raise ValueError(f"Unsupported AI provider: {provider_str}")
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
    def provider(self) -> CategorizationProvider:
        """Get the AI provider."""
        self._ensure_initialized()
        return self._provider

    @property
    def model(self) -> str:
        """Get the model name."""
        self._ensure_initialized()
        return self._model

    def categorize_product(
        self,
        product: str,
        taxonomy: TaxonomyType = TaxonomyType.CUSTOM,
        channel: Optional[str] = None
    ) -> CategorizationResult:
        """Categorize a single product.

        Args:
            product: Product Master name
            taxonomy: Target taxonomy
            channel: Optional channel for channel-specific categorization

        Returns:
            CategorizationResult with category suggestions
        """
        self._ensure_initialized()

        product_data = _get_product_data(product)
        if not product_data:
            return CategorizationResult(
                request_id=str(uuid.uuid4()),
                product=product,
                status=CategorizationStatus.FAILED,
                taxonomy=taxonomy,
                error_message=f"Product not found: {product}"
            )

        request = CategorizationRequest(
            product=product,
            product_data=product_data,
            taxonomy=taxonomy,
            channel=channel,
        )

        return self._process_categorization(request)

    def categorize_for_channel(
        self,
        product: str,
        channel: str
    ) -> CategorizationResult:
        """Categorize a product for a specific channel.

        Args:
            product: Product Master name
            channel: Channel name

        Returns:
            CategorizationResult with channel-specific category
        """
        self._ensure_initialized()

        # Get channel taxonomy
        channel_taxonomy = self._get_channel_taxonomy(channel)
        if not channel_taxonomy:
            return CategorizationResult(
                request_id=str(uuid.uuid4()),
                product=product,
                status=CategorizationStatus.FAILED,
                taxonomy=TaxonomyType.CUSTOM,
                error_message=f"Unknown channel or no taxonomy for: {channel}"
            )

        return self.categorize_product(product, channel_taxonomy, channel)

    def categorize_multi_taxonomy(
        self,
        product: str,
        taxonomies: List[TaxonomyType]
    ) -> Dict[str, CategorizationResult]:
        """Categorize a product across multiple taxonomies.

        Args:
            product: Product Master name
            taxonomies: List of target taxonomies

        Returns:
            Dictionary mapping taxonomy to CategorizationResult
        """
        self._ensure_initialized()

        results = {}
        for taxonomy in taxonomies:
            results[taxonomy.value] = self.categorize_product(product, taxonomy)

        return results

    def bulk_categorize(
        self,
        products: List[str],
        taxonomy: TaxonomyType = TaxonomyType.CUSTOM,
        async_process: bool = True
    ) -> BulkCategorizationResult:
        """Categorize multiple products.

        Args:
            products: List of Product Master names
            taxonomy: Target taxonomy
            async_process: If True, process in background

        Returns:
            BulkCategorizationResult with all results
        """
        import time

        self._ensure_initialized()

        start_time = time.time()

        bulk_result = BulkCategorizationResult(
            total_products=len(products)
        )

        if async_process and len(products) > 5:
            # Enqueue as background job
            import frappe
            job = frappe.enqueue(
                "frappe_pim.pim.services.ai_categorization._bulk_categorize_job",
                queue="long",
                timeout=3600,
                products=products,
                taxonomy=taxonomy.value,
            )

            bulk_result.job_id = job.id if hasattr(job, "id") else str(job)
            bulk_result.processing_time_ms = int((time.time() - start_time) * 1000)
            return bulk_result

        for product in products:
            try:
                result = self.categorize_product(product, taxonomy)
                bulk_result.results.append(result)

                if result.status == CategorizationStatus.COMPLETED:
                    bulk_result.successful += 1
                else:
                    bulk_result.failed += 1

            except Exception as e:
                bulk_result.failed += 1
                bulk_result.errors.append(f"{product}: {str(e)}")

        bulk_result.processing_time_ms = int((time.time() - start_time) * 1000)
        return bulk_result

    def map_category_to_channel(
        self,
        product: str,
        source_category: str,
        target_channel: str
    ) -> CategoryMapping:
        """Map a product's category to a channel-specific category.

        Args:
            product: Product Master name
            source_category: Current category code
            target_channel: Target channel name

        Returns:
            CategoryMapping with mapped category
        """
        self._ensure_initialized()

        product_data = _get_product_data(product)
        if not product_data:
            raise ValueError(f"Product not found: {product}")

        target_taxonomy = self._get_channel_taxonomy(target_channel)
        if not target_taxonomy:
            raise ValueError(f"No taxonomy found for channel: {target_channel}")

        # Get target categories
        target_categories = self.taxonomy_manager.get_categories_for_ai(
            target_taxonomy,
            max_categories=300
        )

        # Build prompt
        prompt = CHANNEL_MAPPING_PROMPT_TEMPLATE.format(
            product_info=self._format_product_info(product_data),
            current_category=source_category,
            channel_name=target_channel,
            channel_description=self._get_channel_description(target_channel),
            target_categories=target_categories,
        )

        # Call AI
        ai_response = self._call_ai_provider(prompt)

        # Parse response
        return self._parse_mapping_response(
            ai_response,
            TaxonomyType.CUSTOM,
            target_taxonomy
        )

    def apply_rules(
        self,
        product: str,
        rules: Optional[List[CategorizationRule]] = None
    ) -> Optional[CategorySuggestion]:
        """Apply categorization rules to a product.

        Args:
            product: Product Master name
            rules: Optional list of rules (loads from database if not provided)

        Returns:
            CategorySuggestion if a rule matches, None otherwise
        """
        product_data = _get_product_data(product)
        if not product_data:
            return None

        if not rules:
            rules = _get_categorization_rules()

        # Sort rules by priority
        sorted_rules = sorted(rules, key=lambda r: r.priority)

        for rule in sorted_rules:
            if not rule.is_active:
                continue

            matches, confidence = rule.evaluate(product_data)
            if matches:
                return CategorySuggestion(
                    category=rule.target_category,
                    confidence=confidence,
                    match_type=MatchType.RULE_BASED,
                    reasoning=f"Matched rule: {rule.name}",
                )

        return None

    def _process_categorization(
        self,
        request: CategorizationRequest
    ) -> CategorizationResult:
        """Process a categorization request.

        Args:
            request: CategorizationRequest to process

        Returns:
            CategorizationResult with AI-generated suggestions
        """
        import time

        start_time = time.time()

        result = CategorizationResult(
            request_id=request.request_id,
            product=request.product,
            status=CategorizationStatus.PROCESSING,
            taxonomy=request.taxonomy,
            provider=self.provider,
            model=self.model,
        )

        try:
            # First try rule-based categorization
            rule_suggestion = self.apply_rules(request.product)
            if rule_suggestion and rule_suggestion.confidence >= 0.9:
                result.primary_suggestion = rule_suggestion
                result.status = CategorizationStatus.COMPLETED
                result.processing_time_ms = int((time.time() - start_time) * 1000)
                return result

            # Get available categories
            available_categories = self.taxonomy_manager.get_categories_for_ai(
                request.taxonomy,
                max_categories=500
            )

            # Build prompt
            prompt = CATEGORIZATION_PROMPT_TEMPLATE.format(
                product_info=self._format_product_info(request.product_data),
                taxonomy_name=request.taxonomy.value,
                taxonomy_description=self._get_taxonomy_description(request.taxonomy),
                available_categories=available_categories,
            )

            # Call AI provider
            ai_response = self._call_ai_provider(prompt)

            # Parse response
            suggestions = self._parse_categorization_response(
                ai_response,
                request.taxonomy
            )

            if suggestions:
                result.primary_suggestion = suggestions[0]
                result.alternative_suggestions = suggestions[1:MAX_SUGGESTIONS]

            result.status = CategorizationStatus.COMPLETED
            result.prompt_tokens = ai_response.get("prompt_tokens", 0)
            result.completion_tokens = ai_response.get("completion_tokens", 0)
            result.total_tokens = ai_response.get("total_tokens", 0)

            # Queue for approval if required
            if self.require_approval and result.primary_suggestion:
                _create_approval_queue_entry(request, result)

        except Exception as e:
            result.status = CategorizationStatus.FAILED
            result.error_message = str(e)
            _log_categorization_error(request, str(e))

        result.processing_time_ms = int((time.time() - start_time) * 1000)

        # Log the result
        _log_categorization_result(request, result)

        return result

    def _format_product_info(self, product_data: Dict[str, Any]) -> str:
        """Format product data for the AI prompt.

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
            lines.append(f"Current Category: {product_data['item_group']}")

        if product_data.get("description"):
            desc = product_data['description'][:500]  # Limit description length
            lines.append(f"Description: {desc}")

        # PIM fields
        if product_data.get("pim_title"):
            lines.append(f"PIM Title: {product_data['pim_title']}")

        if product_data.get("pim_description"):
            pim_desc = product_data['pim_description'][:500]
            lines.append(f"PIM Description: {pim_desc}")

        # Attributes
        attributes = product_data.get("attributes", [])
        if attributes:
            lines.append("\nProduct Attributes:")
            for attr in attributes[:20]:  # Limit to 20 attributes
                if isinstance(attr, dict):
                    lines.append(f"  - {attr.get('attribute')}: {attr.get('attribute_value')}")
                else:
                    lines.append(f"  - {attr}")

        # Specifications
        specs = product_data.get("specifications", {})
        if specs:
            lines.append("\nSpecifications:")
            for key, value in list(specs.items())[:15]:
                lines.append(f"  - {key}: {value}")

        # Additional fields
        optional_fields = [
            ("gtin", "GTIN/Barcode"),
            ("weight_per_unit", "Weight"),
            ("stock_uom", "Unit of Measure"),
            ("country_of_origin", "Country of Origin"),
            ("manufacturer", "Manufacturer"),
        ]

        for field, label in optional_fields:
            if product_data.get(field):
                lines.append(f"{label}: {product_data[field]}")

        return "\n".join(lines)

    def _get_taxonomy_description(self, taxonomy: TaxonomyType) -> str:
        """Get description for a taxonomy type."""
        descriptions = {
            TaxonomyType.GPC: "GS1 Global Product Classification - Standard retail product taxonomy with segment > family > class > brick hierarchy.",
            TaxonomyType.UNSPSC: "United Nations Standard Products and Services Code - Procurement-focused classification system.",
            TaxonomyType.GOOGLE_PRODUCT_CATEGORY: "Google Product Category - Used for Google Shopping and Google Merchant Center listings.",
            TaxonomyType.AMAZON_BROWSE_NODE: "Amazon Browse Node - Amazon's product categorization for marketplace listings.",
            TaxonomyType.FACEBOOK_CATEGORY: "Facebook/Meta Commerce Category - Used for Facebook and Instagram Shop listings.",
            TaxonomyType.TRENDYOL_CATEGORY: "Trendyol marketplace product categories for Turkish e-commerce.",
            TaxonomyType.HEPSIBURADA_CATEGORY: "Hepsiburada marketplace product categories for Turkish e-commerce.",
            TaxonomyType.N11_CATEGORY: "N11 marketplace product categories for Turkish e-commerce.",
            TaxonomyType.EBAY_CATEGORY: "eBay category taxonomy for marketplace listings.",
            TaxonomyType.CUSTOM: "Custom internal product category hierarchy.",
        }
        return descriptions.get(taxonomy, "Custom product classification system.")

    def _get_channel_taxonomy(self, channel: str) -> Optional[TaxonomyType]:
        """Get taxonomy type for a channel."""
        channel_lower = channel.lower()
        channel_taxonomy_map = {
            "amazon": TaxonomyType.AMAZON_BROWSE_NODE,
            "google": TaxonomyType.GOOGLE_PRODUCT_CATEGORY,
            "google_merchant": TaxonomyType.GOOGLE_PRODUCT_CATEGORY,
            "facebook": TaxonomyType.FACEBOOK_CATEGORY,
            "meta": TaxonomyType.FACEBOOK_CATEGORY,
            "trendyol": TaxonomyType.TRENDYOL_CATEGORY,
            "hepsiburada": TaxonomyType.HEPSIBURADA_CATEGORY,
            "n11": TaxonomyType.N11_CATEGORY,
            "ebay": TaxonomyType.EBAY_CATEGORY,
        }
        return channel_taxonomy_map.get(channel_lower, TaxonomyType.CUSTOM)

    def _get_channel_description(self, channel: str) -> str:
        """Get description for a channel."""
        channel_lower = channel.lower()
        descriptions = {
            "amazon": "Amazon marketplace - requires accurate browse node assignment for product visibility.",
            "google": "Google Shopping - accurate category mapping improves ad performance.",
            "trendyol": "Trendyol marketplace - Turkey's largest e-commerce platform.",
            "hepsiburada": "Hepsiburada marketplace - major Turkish e-commerce platform.",
            "n11": "N11 marketplace - Turkish e-commerce platform.",
            "ebay": "eBay marketplace - global auction and shopping platform.",
        }
        return descriptions.get(channel_lower, f"E-commerce channel: {channel}")

    def _call_ai_provider(self, prompt: str) -> Dict[str, Any]:
        """Call the AI provider API.

        Args:
            prompt: The prompt to send

        Returns:
            Dictionary with response and token usage
        """
        if self.provider == CategorizationProvider.OPENAI:
            return self._call_openai(prompt)
        elif self.provider == CategorizationProvider.ANTHROPIC:
            return self._call_anthropic(prompt)
        elif self.provider == CategorizationProvider.GOOGLE_GEMINI:
            return self._call_gemini(prompt)
        else:
            raise ValueError(f"Unsupported AI provider: {self.provider}")

    def _call_openai(self, prompt: str) -> Dict[str, Any]:
        """Call OpenAI API."""
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
                    "content": "You are an expert product categorization specialist. Provide accurate category assignments based on product information."
                },
                {"role": "user", "content": prompt}
            ],
            "max_tokens": MAX_TOKENS,
            "temperature": 0.3,  # Lower temperature for more consistent categorization
        }

        response = requests.post(
            API_ENDPOINTS[CategorizationProvider.OPENAI],
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

    def _call_anthropic(self, prompt: str) -> Dict[str, Any]:
        """Call Anthropic Claude API."""
        import requests

        headers = {
            "x-api-key": self._api_key,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }

        data = {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "system": "You are an expert product categorization specialist. Provide accurate category assignments based on product information.",
        }

        response = requests.post(
            API_ENDPOINTS[CategorizationProvider.ANTHROPIC],
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

    def _call_gemini(self, prompt: str) -> Dict[str, Any]:
        """Call Google Gemini API."""
        import requests

        endpoint = API_ENDPOINTS[CategorizationProvider.GOOGLE_GEMINI].format(model=self.model)
        url = f"{endpoint}?key={self._api_key}"

        data = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": f"System: You are an expert product categorization specialist.\n\nUser: {prompt}"
                        }
                    ]
                }
            ],
            "generationConfig": {
                "maxOutputTokens": MAX_TOKENS,
                "temperature": 0.3,
            }
        }

        response = requests.post(url, json=data, timeout=60)

        if response.status_code != 200:
            error_msg = response.json().get("error", {}).get("message", response.text)
            raise Exception(f"Gemini API error: {error_msg}")

        result = response.json()

        content = ""
        if result.get("candidates"):
            content = result["candidates"][0]["content"]["parts"][0]["text"]

        usage = result.get("usageMetadata", {})

        return {
            "content": content,
            "prompt_tokens": usage.get("promptTokenCount", 0),
            "completion_tokens": usage.get("candidatesTokenCount", 0),
            "total_tokens": usage.get("totalTokenCount", 0),
        }

    def _parse_categorization_response(
        self,
        ai_response: Dict[str, Any],
        taxonomy: TaxonomyType
    ) -> List[CategorySuggestion]:
        """Parse AI response into category suggestions.

        Args:
            ai_response: Response from AI provider
            taxonomy: Target taxonomy

        Returns:
            List of CategorySuggestion objects
        """
        content = ai_response.get("content", "").strip()

        if not content:
            return []

        suggestions = []

        try:
            # Extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', content)
            if not json_match:
                return []

            data = json.loads(json_match.group())

            # Parse primary suggestion
            primary = data.get("primary")
            if primary:
                category_info = CategoryInfo(
                    code=primary.get("category_code", ""),
                    name=primary.get("category_name", ""),
                    path=primary.get("category_path", []),
                    taxonomy=taxonomy,
                )

                suggestions.append(CategorySuggestion(
                    category=category_info,
                    confidence=float(primary.get("confidence", 0.7)),
                    match_type=MatchType.SEMANTIC,
                    reasoning=primary.get("reasoning"),
                    keywords_matched=data.get("keywords_matched", []),
                    attributes_used=data.get("attributes_used", []),
                ))

            # Parse alternative suggestions
            alternatives = data.get("alternatives", [])
            for alt in alternatives:
                category_info = CategoryInfo(
                    code=alt.get("category_code", ""),
                    name=alt.get("category_name", ""),
                    path=alt.get("category_path", []),
                    taxonomy=taxonomy,
                )

                suggestions.append(CategorySuggestion(
                    category=category_info,
                    confidence=float(alt.get("confidence", 0.5)),
                    match_type=MatchType.SEMANTIC,
                    reasoning=alt.get("reasoning"),
                ))

        except json.JSONDecodeError:
            # Try to extract basic category from text response
            pass

        return suggestions

    def _parse_mapping_response(
        self,
        ai_response: Dict[str, Any],
        source_taxonomy: TaxonomyType,
        target_taxonomy: TaxonomyType
    ) -> CategoryMapping:
        """Parse AI response into category mapping.

        Args:
            ai_response: Response from AI provider
            source_taxonomy: Source taxonomy type
            target_taxonomy: Target taxonomy type

        Returns:
            CategoryMapping object
        """
        content = ai_response.get("content", "").strip()

        try:
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                data = json.loads(json_match.group())
                mapped = data.get("mapped_category", {})

                source_category = CategoryInfo(
                    code="source",
                    name="Source Category",
                    taxonomy=source_taxonomy,
                )

                target_category = CategoryInfo(
                    code=mapped.get("category_code", ""),
                    name=mapped.get("category_name", ""),
                    path=mapped.get("category_path", []),
                    taxonomy=target_taxonomy,
                )

                return CategoryMapping(
                    source_taxonomy=source_taxonomy,
                    source_category=source_category,
                    target_taxonomy=target_taxonomy,
                    target_category=target_category,
                    confidence=float(mapped.get("confidence", 0.7)),
                )

        except json.JSONDecodeError:
            pass

        # Return empty mapping on error
        return CategoryMapping(
            source_taxonomy=source_taxonomy,
            source_category=CategoryInfo(code="", name="", taxonomy=source_taxonomy),
            target_taxonomy=target_taxonomy,
            target_category=CategoryInfo(code="", name="", taxonomy=target_taxonomy),
            confidence=0.0,
        )


# =============================================================================
# Public API Functions
# =============================================================================

def categorize_product(
    product: str,
    taxonomy: str = "custom",
    channel: Optional[str] = None,
    async_process: bool = False
) -> Dict[str, Any]:
    """Categorize a product using AI.

    This is the main API function for product categorization.

    Args:
        product: Product Master name
        taxonomy: Target taxonomy type
        channel: Optional channel for channel-specific categorization
        async_process: If True, process in background

    Returns:
        Dictionary with categorization result or job ID
    """
    import frappe

    if async_process:
        job = frappe.enqueue(
            "frappe_pim.pim.services.ai_categorization._categorize_product_job",
            queue="default",
            timeout=120,
            product=product,
            taxonomy=taxonomy,
            channel=channel,
        )
        return {
            "success": True,
            "job_id": job.id if hasattr(job, "id") else str(job),
            "status": "queued"
        }

    taxonomy_type = TaxonomyType(taxonomy) if taxonomy else TaxonomyType.CUSTOM

    service = AICategorizationService()
    result = service.categorize_product(
        product=product,
        taxonomy=taxonomy_type,
        channel=channel,
    )

    return result.to_dict()


def categorize_for_channel(
    product: str,
    channel: str
) -> Dict[str, Any]:
    """Categorize a product for a specific channel.

    Args:
        product: Product Master name
        channel: Channel name

    Returns:
        Dictionary with categorization result
    """
    service = AICategorizationService()
    result = service.categorize_for_channel(
        product=product,
        channel=channel,
    )

    return result.to_dict()


def categorize_multi_taxonomy(
    product: str,
    taxonomies: List[str]
) -> Dict[str, Any]:
    """Categorize a product across multiple taxonomies.

    Args:
        product: Product Master name
        taxonomies: List of taxonomy type strings

    Returns:
        Dictionary with results for each taxonomy
    """
    service = AICategorizationService()

    taxonomy_types = [TaxonomyType(t) for t in taxonomies]

    results = service.categorize_multi_taxonomy(
        product=product,
        taxonomies=taxonomy_types,
    )

    return {
        taxonomy: result.to_dict()
        for taxonomy, result in results.items()
    }


def bulk_categorize_products(
    products: List[str],
    taxonomy: str = "custom",
    async_process: bool = True
) -> Dict[str, Any]:
    """Categorize multiple products.

    Args:
        products: List of Product Master names
        taxonomy: Target taxonomy type
        async_process: If True, process in background

    Returns:
        Dictionary with bulk categorization results
    """
    taxonomy_type = TaxonomyType(taxonomy) if taxonomy else TaxonomyType.CUSTOM

    service = AICategorizationService()
    result = service.bulk_categorize(
        products=products,
        taxonomy=taxonomy_type,
        async_process=async_process,
    )

    return result.to_dict()


def map_category_to_channel(
    product: str,
    source_category: str,
    target_channel: str
) -> Dict[str, Any]:
    """Map a product's category to a channel-specific category.

    Args:
        product: Product Master name
        source_category: Current category code
        target_channel: Target channel name

    Returns:
        Dictionary with category mapping
    """
    service = AICategorizationService()
    mapping = service.map_category_to_channel(
        product=product,
        source_category=source_category,
        target_channel=target_channel,
    )

    return mapping.to_dict()


def get_categorization_status(request_id: str) -> Optional[Dict[str, Any]]:
    """Get the status of a categorization request.

    Args:
        request_id: The categorization request ID

    Returns:
        Dictionary with status or None if not found
    """
    return _get_categorization_log(request_id)


def approve_categorization(
    queue_entry: str,
    approved_category: Optional[str] = None
) -> Dict[str, Any]:
    """Approve an AI categorization suggestion.

    Args:
        queue_entry: AI Approval Queue entry name
        approved_category: Optional modified category code

    Returns:
        Dictionary with approval result
    """
    return _process_approval(queue_entry, approved=True, category=approved_category)


def reject_categorization(
    queue_entry: str,
    rejection_reason: Optional[str] = None
) -> Dict[str, Any]:
    """Reject an AI categorization suggestion.

    Args:
        queue_entry: AI Approval Queue entry name
        rejection_reason: Reason for rejection

    Returns:
        Dictionary with rejection result
    """
    return _process_approval(queue_entry, approved=False, reason=rejection_reason)


def get_pending_categorizations(
    product: Optional[str] = None,
    taxonomy: Optional[str] = None,
    limit: int = 50
) -> Dict[str, Any]:
    """Get pending categorization approvals.

    Args:
        product: Optional filter by product
        taxonomy: Optional filter by taxonomy
        limit: Maximum entries to return

    Returns:
        Dictionary with pending approvals
    """
    import frappe

    filters = {
        "status": "Pending",
        "enrichment_type": "category_suggestion"
    }

    if product:
        filters["product"] = product

    try:
        entries = frappe.get_all(
            "AI Approval Queue",
            filters=filters,
            fields=[
                "name", "product", "suggested_content",
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


def get_available_taxonomies() -> List[Dict[str, str]]:
    """Get list of available taxonomies.

    Returns:
        List of taxonomy information
    """
    return [
        {"value": t.value, "label": t.value.replace("_", " ").title()}
        for t in TaxonomyType
    ]


def get_taxonomy_categories(
    taxonomy: str,
    search: Optional[str] = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """Get categories for a taxonomy.

    Args:
        taxonomy: Taxonomy type
        search: Optional search query
        limit: Maximum categories to return

    Returns:
        List of category dictionaries
    """
    manager = TaxonomyManager()
    taxonomy_type = TaxonomyType(taxonomy) if taxonomy else TaxonomyType.CUSTOM

    if search:
        categories = manager.search_categories(taxonomy_type, search, limit)
    else:
        categories_dict = manager.load_taxonomy(taxonomy_type)
        categories = list(categories_dict.values())[:limit]

    return [cat.to_dict() for cat in categories]


def search_categories(
    query: str,
    taxonomy: str = "custom",
    limit: int = 20
) -> List[Dict[str, Any]]:
    """Search for categories by name or code.

    Args:
        query: Search query
        taxonomy: Taxonomy type
        limit: Maximum results

    Returns:
        List of matching category dictionaries
    """
    manager = TaxonomyManager()
    taxonomy_type = TaxonomyType(taxonomy) if taxonomy else TaxonomyType.CUSTOM

    categories = manager.search_categories(taxonomy_type, query, limit)
    return [cat.to_dict() for cat in categories]


def get_categorization_rules(
    taxonomy: Optional[str] = None,
    active_only: bool = True
) -> List[Dict[str, Any]]:
    """Get categorization rules.

    Args:
        taxonomy: Optional filter by taxonomy
        active_only: Only return active rules

    Returns:
        List of rule dictionaries
    """
    rules = _get_categorization_rules(taxonomy, active_only)
    return [rule.to_dict() for rule in rules]


def test_categorization_connection() -> Dict[str, Any]:
    """Test the AI provider connection for categorization.

    Returns:
        Dictionary with connection test result
    """
    try:
        service = AICategorizationService()
        service._ensure_initialized()

        # Simple test prompt
        test_prompt = "Return a JSON object: {\"status\": \"ok\", \"provider\": \"" + service.provider.value + "\"}"

        response = service._call_ai_provider(test_prompt)

        return {
            "success": True,
            "provider": service.provider.value,
            "model": service.model,
            "message": "Connection successful"
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": "Connection failed"
        }


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
    """Get product data for categorization.

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


def _get_categorization_rules(
    taxonomy: Optional[str] = None,
    active_only: bool = True
) -> List[CategorizationRule]:
    """Get categorization rules from database.

    Args:
        taxonomy: Optional filter by taxonomy
        active_only: Only return active rules

    Returns:
        List of CategorizationRule objects
    """
    import frappe

    rules = []

    try:
        # Check if Categorization Rule DocType exists
        if not frappe.db.exists("DocType", "Categorization Rule"):
            return rules

        filters = {}
        if taxonomy:
            filters["taxonomy"] = taxonomy
        if active_only:
            filters["is_active"] = 1

        db_rules = frappe.get_all(
            "Categorization Rule",
            filters=filters,
            fields=["*"],
            order_by="priority asc"
        )

        for db_rule in db_rules:
            target_cat = CategoryInfo(
                code=db_rule.get("target_category_code", ""),
                name=db_rule.get("target_category_name", ""),
                taxonomy=TaxonomyType(db_rule.get("taxonomy", "custom")),
            )

            conditions = json.loads(db_rule.get("conditions", "[]"))

            rules.append(CategorizationRule(
                rule_id=db_rule.get("name"),
                name=db_rule.get("rule_name", ""),
                taxonomy=TaxonomyType(db_rule.get("taxonomy", "custom")),
                target_category=target_cat,
                conditions=conditions,
                priority=db_rule.get("priority", 100),
                is_active=db_rule.get("is_active", True),
            ))

    except Exception:
        pass

    return rules


def _create_approval_queue_entry(
    request: CategorizationRequest,
    result: CategorizationResult
) -> Optional[str]:
    """Create an entry in the AI Approval Queue.

    Args:
        request: Original categorization request
        result: Categorization result with suggestions

    Returns:
        Queue entry name if created
    """
    import frappe
    from datetime import datetime

    if not result.primary_suggestion:
        return None

    try:
        # Check if AI Approval Queue DocType exists
        if not frappe.db.exists("DocType", "AI Approval Queue"):
            return None

        suggestion = result.primary_suggestion

        entry = frappe.get_doc({
            "doctype": "AI Approval Queue",
            "product": request.product,
            "enrichment_type": "category_suggestion",
            "suggested_content": json.dumps({
                "category_code": suggestion.category.code,
                "category_name": suggestion.category.name,
                "category_path": suggestion.category.path,
                "taxonomy": result.taxonomy.value,
            }),
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
        import frappe
        frappe.log_error(
            message=f"Failed to create approval queue entry: {str(e)}",
            title="AI Categorization - Approval Queue Error"
        )
        return None


def _process_approval(
    queue_entry: str,
    approved: bool,
    category: Optional[str] = None,
    reason: Optional[str] = None
) -> Dict[str, Any]:
    """Process an approval/rejection.

    Args:
        queue_entry: AI Approval Queue entry name
        approved: Whether approved
        category: Optional category override
        reason: Rejection reason

    Returns:
        Dictionary with result
    """
    import frappe
    from datetime import datetime

    try:
        if not frappe.db.exists("AI Approval Queue", queue_entry):
            return {
                "success": False,
                "error": f"Queue entry not found: {queue_entry}"
            }

        entry = frappe.get_doc("AI Approval Queue", queue_entry)

        if approved:
            entry.status = "Approved"
            entry.approved_content = category or entry.suggested_content
            entry.approved_by = frappe.session.user
            entry.approved_at = datetime.utcnow()

            # Apply to product
            _apply_category_to_product(entry.product, entry.approved_content)

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


def _apply_category_to_product(product: str, category_data: str) -> bool:
    """Apply approved category to product.

    Args:
        product: Product Master name
        category_data: JSON string with category data

    Returns:
        True if applied successfully
    """
    import frappe

    try:
        data = json.loads(category_data) if isinstance(category_data, str) else category_data
        category_name = data.get("category_name", "")

        if not category_name:
            return False

        # Try Product Master
        if frappe.db.exists("Product Master", product):
            frappe.db.set_value(
                "Product Master",
                product,
                "item_group",
                category_name,
                update_modified=True
            )
            frappe.db.commit()
            return True

        # Try Item
        if frappe.db.exists("Item", product):
            frappe.db.set_value(
                "Item",
                product,
                "item_group",
                category_name,
                update_modified=True
            )
            frappe.db.commit()
            return True

        return False

    except Exception:
        return False


def _log_categorization_result(
    request: CategorizationRequest,
    result: CategorizationResult
):
    """Log categorization result.

    Args:
        request: Original request
        result: Categorization result
    """
    import frappe
    from datetime import datetime

    try:
        # Check if AI Enrichment Log DocType exists
        if frappe.db.exists("DocType", "AI Enrichment Log"):
            log = frappe.get_doc({
                "doctype": "AI Enrichment Log",
                "request_id": result.request_id,
                "product": request.product,
                "enrichment_type": "category_suggestion",
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


def _log_categorization_error(request: CategorizationRequest, error: str):
    """Log categorization error.

    Args:
        request: Original request
        error: Error message
    """
    import frappe

    frappe.log_error(
        message=f"""
AI Categorization Error

Product: {request.product}
Taxonomy: {request.taxonomy.value}
Request ID: {request.request_id}

Error: {error}
        """,
        title=f"AI Categorization Error - {request.product}"
    )


def _get_categorization_log(request_id: str) -> Optional[Dict[str, Any]]:
    """Get categorization log by request ID.

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
            filters={
                "request_id": request_id,
                "enrichment_type": "category_suggestion"
            },
            fields=["*"],
            limit=1
        )

        return logs[0] if logs else None

    except Exception:
        return None


def _bulk_categorize_job(
    products: List[str],
    taxonomy: str = "custom"
):
    """Background job for bulk categorization.

    Args:
        products: List of product names
        taxonomy: Target taxonomy
    """
    taxonomy_type = TaxonomyType(taxonomy) if taxonomy else TaxonomyType.CUSTOM

    service = AICategorizationService()
    service.bulk_categorize(
        products=products,
        taxonomy=taxonomy_type,
        async_process=False,
    )


def _categorize_product_job(
    product: str,
    taxonomy: str,
    channel: Optional[str] = None
):
    """Background job for single product categorization.

    Args:
        product: Product name
        taxonomy: Target taxonomy
        channel: Optional channel
    """
    taxonomy_type = TaxonomyType(taxonomy) if taxonomy else TaxonomyType.CUSTOM

    service = AICategorizationService()
    service.categorize_product(
        product=product,
        taxonomy=taxonomy_type,
        channel=channel,
    )


# =============================================================================
# Frappe API Wrappers
# =============================================================================

def _wrap_for_whitelist():
    """Wrap functions for Frappe whitelist at runtime."""
    import frappe

    functions = [
        "categorize_product",
        "categorize_for_channel",
        "categorize_multi_taxonomy",
        "bulk_categorize_products",
        "map_category_to_channel",
        "get_categorization_status",
        "approve_categorization",
        "reject_categorization",
        "get_pending_categorizations",
        "get_available_taxonomies",
        "get_taxonomy_categories",
        "search_categories",
        "get_categorization_rules",
        "test_categorization_connection",
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
