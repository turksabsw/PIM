"""
PIM API Module

Provides API endpoints for PIM functionality including:
- Quality scoring and validation
- Channel publishing
- Data quality management
- AI enrichment
- Brand portal

Note: frappe imports are deferred to function/method level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

from frappe_pim.pim.api.quality import (
    get_quality_score,
    get_channel_readiness,
    get_missing_fields,
    calculate_quality_score,
    validate_product_quality,
    get_quality_issues,
    get_quality_summary,
    bulk_quality_check,
    QualityScore,
    ChannelReadiness,
    QualityIssue,
    QualityValidationResult,
)

from frappe_pim.pim.api.channel import (
    publish_to_channel,
    get_publish_status,
    validate_for_channel,
    get_channel_validation_summary,
    get_available_channels,
    test_channel_connection,
    cancel_publish_job,
    ChannelValidationResult,
    PublishJobResult,
    PublishStatusResult,
    BulkValidationResult,
    JobStatus,
)

from frappe_pim.pim.api.ai import (
    # Core AI API Functions
    enrich_product,
    get_ai_suggestions,
    approve_enrichment,
    reject_enrichment,
    # Additional AI API Functions
    bulk_enrich_products,
    get_ai_status,
    get_approval_stats,
    enqueue_bulk_enrichment,
    # AI Data Classes
    EnrichmentResult,
    SuggestionResult,
    ApprovalResult,
    AIStatusResult,
    # AI Enums
    EnrichmentType,
    ApprovalStatus,
    EnrichmentStatus,
)

from frappe_pim.pim.api.doctype_meta import get_doctype_meta

from frappe_pim.pim.api.brand_portal import (
    # Core Brand Portal API Functions
    submit_product,
    get_submissions,
    get_submission_details,
    update_submission_status,
    # Additional Brand Portal API Functions
    update_submission,
    withdraw_submission,
    get_partner_stats,
    bulk_submit_products,
    get_pending_reviews,
    # Brand Portal Data Classes
    SubmissionResult,
    SubmissionDetails,
    SubmissionListResult,
    StatusUpdateResult,
    PartnerStats,
    # Brand Portal Enums
    SubmissionStatus,
    SubmissionPriority,
    PartnerType,
)

__all__ = [
    # DocType meta (frontend form rendering)
    "get_doctype_meta",
    # Quality API
    "get_quality_score",
    "get_channel_readiness",
    "get_missing_fields",
    "calculate_quality_score",
    "validate_product_quality",
    "get_quality_issues",
    "get_quality_summary",
    "bulk_quality_check",

    # Quality Data classes
    "QualityScore",
    "ChannelReadiness",
    "QualityIssue",
    "QualityValidationResult",

    # Channel API
    "publish_to_channel",
    "get_publish_status",
    "validate_for_channel",
    "get_channel_validation_summary",
    "get_available_channels",
    "test_channel_connection",
    "cancel_publish_job",

    # Channel Data classes
    "ChannelValidationResult",
    "PublishJobResult",
    "PublishStatusResult",
    "BulkValidationResult",
    "JobStatus",

    # AI API
    "enrich_product",
    "get_ai_suggestions",
    "approve_enrichment",
    "reject_enrichment",
    "bulk_enrich_products",
    "get_ai_status",
    "get_approval_stats",
    "enqueue_bulk_enrichment",

    # AI Data Classes
    "EnrichmentResult",
    "SuggestionResult",
    "ApprovalResult",
    "AIStatusResult",

    # AI Enums
    "EnrichmentType",
    "ApprovalStatus",
    "EnrichmentStatus",

    # Brand Portal API
    "submit_product",
    "get_submissions",
    "get_submission_details",
    "update_submission_status",
    "update_submission",
    "withdraw_submission",
    "get_partner_stats",
    "bulk_submit_products",
    "get_pending_reviews",

    # Brand Portal Data Classes
    "SubmissionResult",
    "SubmissionDetails",
    "SubmissionListResult",
    "StatusUpdateResult",
    "PartnerStats",

    # Brand Portal Enums
    "SubmissionStatus",
    "SubmissionPriority",
    "PartnerType",
]
