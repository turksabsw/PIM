"""
AI Enrichment API Endpoints for PIM

Provides API endpoints for AI-powered product enrichment, including
description generation, title enhancement, keyword suggestions, and
approval queue management.

Key Features:
- Enrich products with AI-generated content
- Get AI suggestions for products
- Approve/reject AI enrichment suggestions
- Batch enrichment processing
- AI configuration and status

Note: frappe imports are deferred to function/method level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union
import json


# =============================================================================
# Custom Exceptions
# =============================================================================

class AIEnrichmentError(Exception):
    """Base exception for AI enrichment errors"""

    def __init__(self, message: str, details: Dict = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> Dict:
        return {
            "error": self.__class__.__name__,
            "message": self.message,
            "details": self.details,
        }


class ProductNotFoundError(AIEnrichmentError):
    """Raised when product is not found"""
    pass


class EnrichmentNotFoundError(AIEnrichmentError):
    """Raised when enrichment queue entry is not found"""
    pass


class AIProviderError(AIEnrichmentError):
    """Raised when AI provider is unavailable or fails"""
    pass


class InvalidEnrichmentTypeError(AIEnrichmentError):
    """Raised when enrichment type is invalid"""
    pass


class ApprovalError(AIEnrichmentError):
    """Raised when approval operation fails"""
    pass


# =============================================================================
# Enums and Constants
# =============================================================================

class EnrichmentType(str, Enum):
    """Type of enrichment operation"""
    DESCRIPTION = "description"
    TITLE = "title"
    KEYWORDS = "keywords"
    TRANSLATION = "translation"
    META_DESCRIPTION = "meta_description"
    BULLET_POINTS = "bullet_points"


class ApprovalStatus(str, Enum):
    """Status of approval queue entry"""
    PENDING = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"
    AUTO_APPROVED = "Auto Approved"
    EXPIRED = "Expired"


class EnrichmentStatus(str, Enum):
    """Status of an enrichment request"""
    SUCCESS = "success"
    ERROR = "error"
    PENDING_APPROVAL = "pending_approval"
    NO_AI_AVAILABLE = "no_ai_available"
    INVALID_INPUT = "invalid_input"
    RATE_LIMITED = "rate_limited"


# Valid enrichment types
VALID_ENRICHMENT_TYPES = [
    "description",
    "title",
    "keywords",
    "translation",
    "meta_description",
    "bullet_points",
]

# Default settings for enrichment
DEFAULT_ENRICHMENT_SETTINGS = {
    "description": {
        "min_length": 100,
        "max_length": 500,
        "tone": "professional",
    },
    "title": {
        "max_length": 200,
    },
    "keywords": {
        "count": 10,
    },
    "bullet_points": {
        "count": 5,
        "min_length": 30,
        "max_length": 100,
    },
    "meta_description": {
        "max_length": 155,
    },
}


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class EnrichmentResult:
    """Result of an enrichment operation"""
    status: str
    enrichment_type: str
    product_code: str
    content: Any = None
    original_content: Any = None
    queue_id: str = ""
    confidence_score: float = 0.0
    model_used: str = ""
    tokens_used: int = 0
    estimated_cost: float = 0.0
    error_message: str = ""
    metadata: Dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict:
        return {
            "status": self.status,
            "enrichment_type": self.enrichment_type,
            "product_code": self.product_code,
            "content": self.content,
            "original_content": self.original_content,
            "queue_id": self.queue_id,
            "confidence_score": round(self.confidence_score, 2),
            "model_used": self.model_used,
            "tokens_used": self.tokens_used,
            "estimated_cost": round(self.estimated_cost, 6),
            "error_message": self.error_message,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class SuggestionResult:
    """Result containing AI suggestions for a product"""
    product_code: str
    suggestions: List[Dict]
    pending_count: int = 0
    approved_count: int = 0
    rejected_count: int = 0
    total_count: int = 0

    def to_dict(self) -> Dict:
        return {
            "product_code": self.product_code,
            "suggestions": self.suggestions,
            "pending_count": self.pending_count,
            "approved_count": self.approved_count,
            "rejected_count": self.rejected_count,
            "total_count": self.total_count,
        }


@dataclass
class ApprovalResult:
    """Result of an approval operation"""
    queue_id: str
    status: str
    product_code: str
    enrichment_type: str
    applied: bool = False
    error_message: str = ""

    def to_dict(self) -> Dict:
        return {
            "queue_id": self.queue_id,
            "status": self.status,
            "product_code": self.product_code,
            "enrichment_type": self.enrichment_type,
            "applied": self.applied,
            "error_message": self.error_message,
        }


@dataclass
class AIStatusResult:
    """AI provider status result"""
    is_available: bool
    provider: str
    model: str
    rate_limit_remaining: int = 0
    daily_cost: float = 0.0
    daily_requests: int = 0

    def to_dict(self) -> Dict:
        return {
            "is_available": self.is_available,
            "provider": self.provider,
            "model": self.model,
            "rate_limit_remaining": self.rate_limit_remaining,
            "daily_cost": round(self.daily_cost, 4),
            "daily_requests": self.daily_requests,
        }


# =============================================================================
# Helper Functions
# =============================================================================

def _get_product_data(product_code: str) -> Dict:
    """Get product data from database.

    Args:
        product_code: Product/Item code

    Returns:
        Dictionary with product data

    Raises:
        ProductNotFoundError: If product not found
    """
    import frappe

    # Try to get as Item (underlying storage for Virtual DocType)
    if not frappe.db.exists("Item", product_code):
        raise ProductNotFoundError(
            f"Product not found: {product_code}",
            details={"product_code": product_code}
        )

    item = frappe.get_doc("Item", product_code)

    # Build product data dict
    product_data = {
        "name": item.name,
        "item_code": item.item_code,
        "item_name": item.item_name,
        "item_group": item.item_group,
        "brand": item.brand,
        "description": item.description,
        "stock_uom": item.stock_uom,
        "standard_rate": item.standard_rate,
        "weight_per_unit": item.weight_per_unit,
        "weight_uom": item.weight_uom,
        "disabled": item.disabled,
    }

    # Add PIM custom fields if they exist (custom_field.json uses custom_pim_* prefix)
    pim_field_map = {
        "custom_pim_status": "pim_status",
        "custom_pim_long_description": "pim_description",
        "custom_pim_completeness": "pim_completeness",
        "custom_pim_data_quality_score": "pim_quality_score",
        "custom_pim_meta_keywords": "pim_keywords",
        "custom_pim_meta_description": "pim_meta_description",
        "custom_pim_seo_title": "pim_seo_title",
    }

    for custom_field, output_key in pim_field_map.items():
        if hasattr(item, custom_field):
            product_data[output_key] = getattr(item, custom_field)

    # Native Item fields
    product_data["brand"] = item.brand
    product_data["manufacturer"] = item.manufacturer

    # Check for barcode
    if hasattr(item, 'barcodes') and item.barcodes:
        product_data['barcode'] = item.barcodes[0].barcode if item.barcodes else None
    elif hasattr(item, 'barcode'):
        product_data['barcode'] = item.barcode

    return product_data


def _validate_enrichment_type(enrichment_type: str) -> str:
    """Validate and normalize enrichment type.

    Args:
        enrichment_type: Type of enrichment

    Returns:
        Normalized enrichment type

    Raises:
        InvalidEnrichmentTypeError: If type is invalid
    """
    enrichment_type = enrichment_type.lower().strip()

    if enrichment_type not in VALID_ENRICHMENT_TYPES:
        raise InvalidEnrichmentTypeError(
            f"Invalid enrichment type: {enrichment_type}",
            details={
                "provided": enrichment_type,
                "valid_types": VALID_ENRICHMENT_TYPES,
            }
        )

    return enrichment_type


def _get_enrichment_function(enrichment_type: str):
    """Get the appropriate enrichment function for the type.

    Args:
        enrichment_type: Type of enrichment

    Returns:
        Enrichment function from ai.enrichment module
    """
    from frappe_pim.pim.utils.ai.enrichment import (
        generate_description,
        enhance_title,
        suggest_keywords,
        generate_bullet_points,
        generate_meta_description,
        translate_content,
    )

    function_map = {
        "description": generate_description,
        "title": enhance_title,
        "keywords": suggest_keywords,
        "bullet_points": generate_bullet_points,
        "meta_description": generate_meta_description,
        "translation": translate_content,
    }

    return function_map.get(enrichment_type)


def _check_ai_available() -> bool:
    """Check if AI provider is available.

    Returns:
        True if AI is available, False otherwise
    """
    try:
        from frappe_pim.pim.utils.ai.client import AIClient
        client = AIClient()
        return client.is_available()
    except Exception:
        return False


# =============================================================================
# API Functions - Core Enrichment
# =============================================================================

def enrich_product(
    product_code: str,
    enrichment_types: Union[str, List[str]] = None,
    language: str = "en",
    auto_approve: bool = False,
    settings: Dict = None,
    channel: str = None,
) -> Union[Dict, List[Dict]]:
    """Enrich a product with AI-generated content.

    Generates AI-powered content for the specified product based on
    the enrichment types requested.

    Args:
        product_code: Product/Item code to enrich
        enrichment_types: Type(s) of enrichment to perform. Can be a string
            for single type or list for multiple types. Valid types:
            'description', 'title', 'keywords', 'meta_description', 'bullet_points'
        language: Target language code (default: 'en')
        auto_approve: If True, automatically approve and apply high-confidence results
        settings: Optional settings override for enrichment parameters
        channel: Target channel for channel-specific formatting

    Returns:
        Dictionary or list of dictionaries with enrichment results

    Example:
        # Single enrichment type
        result = enrich_product("PROD-001", "description")

        # Multiple enrichment types
        results = enrich_product("PROD-001", ["title", "description", "keywords"])

        # With settings
        result = enrich_product("PROD-001", "description", settings={"max_length": 300})
    """
    import frappe

    try:
        # Check AI availability
        if not _check_ai_available():
            return EnrichmentResult(
                status=EnrichmentStatus.NO_AI_AVAILABLE.value,
                enrichment_type="",
                product_code=product_code,
                error_message="No AI provider configured. Set OPENAI_API_KEY or ANTHROPIC_API_KEY.",
            ).to_dict()

        # Get product data
        product_data = _get_product_data(product_code)

        # Normalize enrichment types
        if enrichment_types is None:
            enrichment_types = ["description"]
        elif isinstance(enrichment_types, str):
            enrichment_types = [enrichment_types]

        # Validate enrichment types
        validated_types = []
        for etype in enrichment_types:
            try:
                validated_types.append(_validate_enrichment_type(etype))
            except InvalidEnrichmentTypeError as e:
                # Return error for invalid type
                if len(enrichment_types) == 1:
                    return EnrichmentResult(
                        status=EnrichmentStatus.ERROR.value,
                        enrichment_type=etype,
                        product_code=product_code,
                        error_message=e.message,
                    ).to_dict()
                # Skip invalid types in multi-type request
                continue

        if not validated_types:
            return EnrichmentResult(
                status=EnrichmentStatus.INVALID_INPUT.value,
                enrichment_type="",
                product_code=product_code,
                error_message="No valid enrichment types provided",
            ).to_dict()

        # Process enrichments
        results = []
        for enrichment_type in validated_types:
            result = _perform_enrichment(
                product_data=product_data,
                enrichment_type=enrichment_type,
                language=language,
                auto_approve=auto_approve,
                settings=settings,
                channel=channel,
            )
            results.append(result)

        # Return single result for single type, list for multiple
        if len(validated_types) == 1:
            return results[0]
        return results

    except ProductNotFoundError as e:
        frappe.throw(e.message, exc=frappe.DoesNotExistError)
    except Exception as e:
        frappe.log_error(f"AI enrichment failed: {e}")
        return EnrichmentResult(
            status=EnrichmentStatus.ERROR.value,
            enrichment_type=enrichment_types[0] if enrichment_types else "",
            product_code=product_code,
            error_message=str(e),
        ).to_dict()


def _perform_enrichment(
    product_data: Dict,
    enrichment_type: str,
    language: str = "en",
    auto_approve: bool = False,
    settings: Dict = None,
    channel: str = None,
) -> Dict:
    """Perform a single enrichment operation.

    Args:
        product_data: Product data dictionary
        enrichment_type: Type of enrichment
        language: Target language
        auto_approve: Whether to auto-approve
        settings: Optional settings override
        channel: Target channel

    Returns:
        Enrichment result dictionary
    """
    from frappe_pim.pim.utils.ai.enrichment import (
        generate_description,
        enhance_title,
        suggest_keywords,
        generate_bullet_points,
        generate_meta_description,
        EnrichmentStatus as EnrichStatus,
    )

    product_code = product_data.get("item_code") or product_data.get("name", "unknown")

    # Merge settings with defaults
    default_settings = DEFAULT_ENRICHMENT_SETTINGS.get(enrichment_type, {})
    merged_settings = {**default_settings, **(settings or {})}

    try:
        # Call appropriate enrichment function
        if enrichment_type == "description":
            result = generate_description(
                product_data=product_data,
                language=language,
                tone=merged_settings.get("tone", "professional"),
                min_length=merged_settings.get("min_length", 100),
                max_length=merged_settings.get("max_length", 500),
                auto_approve=auto_approve,
                channel=channel,
            )
        elif enrichment_type == "title":
            result = enhance_title(
                product_data=product_data,
                language=language,
                max_length=merged_settings.get("max_length", 200),
                auto_approve=auto_approve,
                channel=channel,
            )
        elif enrichment_type == "keywords":
            result = suggest_keywords(
                product_data=product_data,
                language=language,
                count=merged_settings.get("count", 10),
                channel=channel,
            )
        elif enrichment_type == "bullet_points":
            result = generate_bullet_points(
                product_data=product_data,
                language=language,
                count=merged_settings.get("count", 5),
            )
        elif enrichment_type == "meta_description":
            result = generate_meta_description(
                product_data=product_data,
                language=language,
                max_length=merged_settings.get("max_length", 155),
            )
        else:
            return EnrichmentResult(
                status=EnrichmentStatus.ERROR.value,
                enrichment_type=enrichment_type,
                product_code=product_code,
                error_message=f"Enrichment type not implemented: {enrichment_type}",
            ).to_dict()

        # Convert result to API response format
        return EnrichmentResult(
            status=result.status.value if hasattr(result.status, 'value') else result.status,
            enrichment_type=enrichment_type,
            product_code=product_code,
            content=result.content,
            original_content=result.original_content,
            queue_id=result.metadata.get("queue_id", "") if result.metadata else "",
            confidence_score=result.confidence_score,
            model_used=result.model_used,
            tokens_used=result.tokens_used,
            estimated_cost=result.estimated_cost,
            metadata=result.metadata,
        ).to_dict()

    except Exception as e:
        return EnrichmentResult(
            status=EnrichmentStatus.ERROR.value,
            enrichment_type=enrichment_type,
            product_code=product_code,
            error_message=str(e),
        ).to_dict()


def get_ai_suggestions(
    product_code: str = None,
    enrichment_type: str = None,
    status: str = None,
    limit: int = 20,
    offset: int = 0,
) -> Dict:
    """Get AI suggestions from the approval queue.

    Retrieves AI-generated content suggestions that are pending approval
    or have been processed.

    Args:
        product_code: Optional filter by product code
        enrichment_type: Optional filter by enrichment type
        status: Optional filter by status ('Pending', 'Approved', 'Rejected', etc.)
        limit: Maximum number of results to return
        offset: Number of results to skip (for pagination)

    Returns:
        Dictionary with suggestions and counts

    Example:
        # Get all pending suggestions
        result = get_ai_suggestions(status="Pending")

        # Get suggestions for specific product
        result = get_ai_suggestions(product_code="PROD-001")

        # Get approved suggestions with pagination
        result = get_ai_suggestions(status="Approved", limit=10, offset=0)
    """
    import frappe

    try:
        # Build filters
        filters = {}

        if product_code:
            if not frappe.db.exists("Item", product_code):
                raise ProductNotFoundError(
                    f"Product not found: {product_code}",
                    details={"product_code": product_code}
                )
            filters["product"] = product_code

        if enrichment_type:
            try:
                enrichment_type = _validate_enrichment_type(enrichment_type)
                filters["enrichment_type"] = enrichment_type
            except InvalidEnrichmentTypeError:
                pass  # Skip invalid filter

        if status:
            valid_statuses = ["Pending", "Approved", "Rejected", "Auto Approved", "Expired"]
            if status in valid_statuses:
                filters["status"] = status

        # Check if AI Approval Queue DocType exists
        if not frappe.db.exists("DocType", "AI Approval Queue"):
            return SuggestionResult(
                product_code=product_code or "",
                suggestions=[],
                total_count=0,
            ).to_dict()

        # Get suggestions
        suggestions = frappe.get_all(
            "AI Approval Queue",
            filters=filters,
            fields=[
                "name", "product", "product_name", "enrichment_type",
                "original_content", "suggested_content", "status",
                "confidence_score", "model_used", "tokens_used",
                "estimated_cost", "reviewed_by", "reviewed_on",
                "rejection_reason", "notes", "auto_approved",
                "creation", "modified"
            ],
            order_by="creation desc",
            limit_page_length=limit,
            limit_start=offset,
        )

        # Get counts
        pending_count = frappe.db.count(
            "AI Approval Queue",
            filters={**filters, "status": "Pending"} if filters else {"status": "Pending"}
        )
        approved_count = frappe.db.count(
            "AI Approval Queue",
            filters={**filters, "status": ["in", ["Approved", "Auto Approved"]]}
            if filters else {"status": ["in", ["Approved", "Auto Approved"]]}
        )
        rejected_count = frappe.db.count(
            "AI Approval Queue",
            filters={**filters, "status": "Rejected"} if filters else {"status": "Rejected"}
        )
        total_count = frappe.db.count("AI Approval Queue", filters=filters)

        # Format suggestions
        formatted_suggestions = []
        for suggestion in suggestions:
            formatted_suggestions.append({
                "queue_id": suggestion.name,
                "product_code": suggestion.product,
                "product_name": suggestion.product_name,
                "enrichment_type": suggestion.enrichment_type,
                "original_content": suggestion.original_content,
                "suggested_content": suggestion.suggested_content,
                "status": suggestion.status,
                "confidence_score": round(suggestion.confidence_score or 0, 2),
                "model_used": suggestion.model_used,
                "tokens_used": suggestion.tokens_used,
                "estimated_cost": round(suggestion.estimated_cost or 0, 6),
                "auto_approved": bool(suggestion.auto_approved),
                "reviewed_by": suggestion.reviewed_by,
                "reviewed_on": str(suggestion.reviewed_on) if suggestion.reviewed_on else None,
                "rejection_reason": suggestion.rejection_reason,
                "notes": suggestion.notes,
                "created_at": str(suggestion.creation),
                "modified_at": str(suggestion.modified),
            })

        return SuggestionResult(
            product_code=product_code or "",
            suggestions=formatted_suggestions,
            pending_count=pending_count,
            approved_count=approved_count,
            rejected_count=rejected_count,
            total_count=total_count,
        ).to_dict()

    except ProductNotFoundError as e:
        import frappe
        frappe.throw(e.message, exc=frappe.DoesNotExistError)
    except Exception as e:
        import frappe
        frappe.log_error(f"Get AI suggestions failed: {e}")
        frappe.throw(str(e))


def approve_enrichment(
    queue_id: str,
    notes: str = None,
    apply_immediately: bool = True,
) -> Dict:
    """Approve an AI enrichment suggestion.

    Approves a pending AI suggestion and optionally applies the content
    to the product immediately.

    Args:
        queue_id: ID of the approval queue entry
        notes: Optional approval notes
        apply_immediately: If True, apply the content to product immediately

    Returns:
        Dictionary with approval result

    Example:
        result = approve_enrichment("abc123")
        result = approve_enrichment("abc123", notes="Reviewed and approved")
    """
    import frappe

    try:
        # Check if AI Approval Queue DocType exists
        if not frappe.db.exists("DocType", "AI Approval Queue"):
            raise EnrichmentNotFoundError(
                "AI Approval Queue DocType not found",
                details={"queue_id": queue_id}
            )

        # Check if entry exists
        if not frappe.db.exists("AI Approval Queue", queue_id):
            raise EnrichmentNotFoundError(
                f"Queue entry not found: {queue_id}",
                details={"queue_id": queue_id}
            )

        # Get the queue entry
        doc = frappe.get_doc("AI Approval Queue", queue_id)

        # Check status
        if doc.status != "Pending":
            raise ApprovalError(
                f"Cannot approve entry with status: {doc.status}",
                details={"queue_id": queue_id, "current_status": doc.status}
            )

        # Update status
        doc.status = "Approved"
        doc.notes = notes
        doc.reviewed_by = frappe.session.user
        doc.reviewed_on = frappe.utils.now_datetime()
        doc.save(ignore_permissions=True)

        # Apply content if requested
        applied = False
        if apply_immediately and doc.suggested_content and doc.product:
            try:
                from frappe_pim.pim.doctype.ai_approval_queue.ai_approval_queue import (
                    ENRICHMENT_FIELD_MAPPING
                )

                target_field = ENRICHMENT_FIELD_MAPPING.get(doc.enrichment_type)
                if target_field:
                    item = frappe.get_doc("Item", doc.product)
                    if hasattr(item, target_field):
                        # Handle JSON content for list-type fields
                        content = doc.suggested_content
                        if doc.enrichment_type in ["keywords", "bullet_points"]:
                            try:
                                parsed = json.loads(content)
                                if isinstance(parsed, list):
                                    content = ", ".join(str(x) for x in parsed)
                            except (json.JSONDecodeError, TypeError):
                                pass

                        item.set(target_field, content)
                        item.flags.from_ai_approval = True
                        item.save(ignore_permissions=True)
                        applied = True

            except Exception as apply_error:
                frappe.log_error(f"Error applying approved content: {apply_error}")

        return ApprovalResult(
            queue_id=queue_id,
            status="Approved",
            product_code=doc.product,
            enrichment_type=doc.enrichment_type,
            applied=applied,
        ).to_dict()

    except EnrichmentNotFoundError as e:
        frappe.throw(e.message, exc=frappe.DoesNotExistError)
    except ApprovalError as e:
        frappe.throw(e.message)
    except Exception as e:
        frappe.log_error(f"Approve enrichment failed: {e}")
        frappe.throw(str(e))


def reject_enrichment(
    queue_id: str,
    reason: str = None,
) -> Dict:
    """Reject an AI enrichment suggestion.

    Rejects a pending AI suggestion with an optional reason.

    Args:
        queue_id: ID of the approval queue entry
        reason: Optional rejection reason

    Returns:
        Dictionary with rejection result

    Example:
        result = reject_enrichment("abc123", reason="Content not suitable")
    """
    import frappe

    try:
        # Check if AI Approval Queue DocType exists
        if not frappe.db.exists("DocType", "AI Approval Queue"):
            raise EnrichmentNotFoundError(
                "AI Approval Queue DocType not found",
                details={"queue_id": queue_id}
            )

        # Check if entry exists
        if not frappe.db.exists("AI Approval Queue", queue_id):
            raise EnrichmentNotFoundError(
                f"Queue entry not found: {queue_id}",
                details={"queue_id": queue_id}
            )

        # Get the queue entry
        doc = frappe.get_doc("AI Approval Queue", queue_id)

        # Check status
        if doc.status != "Pending":
            raise ApprovalError(
                f"Cannot reject entry with status: {doc.status}",
                details={"queue_id": queue_id, "current_status": doc.status}
            )

        # Update status
        doc.status = "Rejected"
        doc.rejection_reason = reason
        doc.reviewed_by = frappe.session.user
        doc.reviewed_on = frappe.utils.now_datetime()
        doc.save(ignore_permissions=True)

        return ApprovalResult(
            queue_id=queue_id,
            status="Rejected",
            product_code=doc.product,
            enrichment_type=doc.enrichment_type,
            applied=False,
        ).to_dict()

    except EnrichmentNotFoundError as e:
        frappe.throw(e.message, exc=frappe.DoesNotExistError)
    except ApprovalError as e:
        frappe.throw(e.message)
    except Exception as e:
        frappe.log_error(f"Reject enrichment failed: {e}")
        frappe.throw(str(e))


# =============================================================================
# Additional API Functions
# =============================================================================

def bulk_enrich_products(
    product_codes: List[str],
    enrichment_types: List[str],
    language: str = "en",
    auto_approve: bool = False,
) -> List[Dict]:
    """Enrich multiple products in bulk.

    Processes AI enrichment for multiple products. This function
    processes sequentially. For large batches, consider using
    background jobs.

    Args:
        product_codes: List of product codes to enrich
        enrichment_types: List of enrichment types to perform
        language: Target language code
        auto_approve: Whether to auto-approve results

    Returns:
        List of enrichment result dictionaries

    Example:
        results = bulk_enrich_products(
            product_codes=["PROD-001", "PROD-002"],
            enrichment_types=["title", "description"],
        )
    """
    import frappe

    results = []

    for product_code in product_codes:
        try:
            result = enrich_product(
                product_code=product_code,
                enrichment_types=enrichment_types,
                language=language,
                auto_approve=auto_approve,
            )

            # Handle single or multiple results
            if isinstance(result, list):
                results.extend(result)
            else:
                results.append(result)

        except Exception as e:
            # Add error result for failed products
            for etype in enrichment_types:
                results.append(EnrichmentResult(
                    status=EnrichmentStatus.ERROR.value,
                    enrichment_type=etype,
                    product_code=product_code,
                    error_message=str(e),
                ).to_dict())

    return results


def get_ai_status() -> Dict:
    """Get AI provider status and configuration.

    Returns information about the configured AI provider,
    availability, and usage statistics.

    Returns:
        Dictionary with AI status information

    Example:
        status = get_ai_status()
        if status["is_available"]:
            print(f"Using {status['provider']} model: {status['model']}")
    """
    try:
        from frappe_pim.pim.utils.ai.client import AIClient

        client = AIClient()
        is_available = client.is_available()

        if is_available:
            return AIStatusResult(
                is_available=True,
                provider=client.config.provider.value if client.config else "unknown",
                model=client.config.model.value if client.config else "unknown",
            ).to_dict()
        else:
            return AIStatusResult(
                is_available=False,
                provider="",
                model="",
            ).to_dict()

    except Exception as e:
        return AIStatusResult(
            is_available=False,
            provider="",
            model="",
        ).to_dict()


def get_approval_stats(days: int = 30) -> Dict:
    """Get AI approval queue statistics.

    Returns statistics about AI enrichment approvals over the
    specified period.

    Args:
        days: Number of days to include in statistics

    Returns:
        Dictionary with approval statistics

    Example:
        stats = get_approval_stats(days=7)
        print(f"Approval rate: {stats['approval_rate']}%")
    """
    import frappe

    try:
        # Check if AI Approval Queue DocType exists
        if not frappe.db.exists("DocType", "AI Approval Queue"):
            return {
                "period_days": days,
                "total_entries": 0,
                "status_breakdown": {},
                "approval_rate": 0,
                "auto_approval_rate": 0,
            }

        # Use utility function from doctype
        from frappe_pim.pim.doctype.ai_approval_queue.ai_approval_queue import (
            get_approval_stats as _get_stats
        )

        return _get_stats(days)

    except Exception as e:
        import frappe
        frappe.log_error(f"Get approval stats failed: {e}")
        return {
            "period_days": days,
            "total_entries": 0,
            "status_breakdown": {},
            "approval_rate": 0,
            "auto_approval_rate": 0,
            "error": str(e),
        }


def enqueue_bulk_enrichment(
    product_codes: List[str],
    enrichment_types: List[str],
    language: str = "en",
    auto_approve: bool = False,
) -> Dict:
    """Queue bulk enrichment as a background job.

    Submits a bulk enrichment request to be processed in the background.
    This is recommended for large batches of products.

    Args:
        product_codes: List of product codes to enrich
        enrichment_types: List of enrichment types to perform
        language: Target language code
        auto_approve: Whether to auto-approve results

    Returns:
        Dictionary with job information

    Example:
        job = enqueue_bulk_enrichment(
            product_codes=["PROD-001", "PROD-002", "PROD-003"],
            enrichment_types=["description"],
        )
        print(f"Job ID: {job['job_id']}")
    """
    import frappe

    try:
        job = frappe.enqueue(
            "frappe_pim.pim.api.ai.bulk_enrich_products",
            product_codes=product_codes,
            enrichment_types=enrichment_types,
            language=language,
            auto_approve=auto_approve,
            queue="long",
            timeout=3600,  # 1 hour timeout
            is_async=True,
        )

        return {
            "status": "queued",
            "job_id": job.id if hasattr(job, 'id') else str(job),
            "product_count": len(product_codes),
            "enrichment_types": enrichment_types,
            "message": f"Bulk enrichment queued for {len(product_codes)} products",
        }

    except Exception as e:
        frappe.log_error(f"Enqueue bulk enrichment failed: {e}")
        return {
            "status": "error",
            "job_id": None,
            "error": str(e),
        }


# =============================================================================
# Frappe Whitelist Decorators
# =============================================================================

try:
    import frappe

    enrich_product = frappe.whitelist()(enrich_product)
    get_ai_suggestions = frappe.whitelist()(get_ai_suggestions)
    approve_enrichment = frappe.whitelist()(approve_enrichment)
    reject_enrichment = frappe.whitelist()(reject_enrichment)
    bulk_enrich_products = frappe.whitelist()(bulk_enrich_products)
    get_ai_status = frappe.whitelist()(get_ai_status)
    get_approval_stats = frappe.whitelist()(get_approval_stats)
    enqueue_bulk_enrichment = frappe.whitelist()(enqueue_bulk_enrichment)

except ImportError:
    pass  # Allow import without frappe for testing


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # Core API Functions
    "enrich_product",
    "get_ai_suggestions",
    "approve_enrichment",
    "reject_enrichment",

    # Additional API Functions
    "bulk_enrich_products",
    "get_ai_status",
    "get_approval_stats",
    "enqueue_bulk_enrichment",

    # Data Classes
    "EnrichmentResult",
    "SuggestionResult",
    "ApprovalResult",
    "AIStatusResult",

    # Enums
    "EnrichmentType",
    "ApprovalStatus",
    "EnrichmentStatus",

    # Exceptions
    "AIEnrichmentError",
    "ProductNotFoundError",
    "EnrichmentNotFoundError",
    "AIProviderError",
    "InvalidEnrichmentTypeError",
    "ApprovalError",

    # Constants
    "VALID_ENRICHMENT_TYPES",
    "DEFAULT_ENRICHMENT_SETTINGS",
]
