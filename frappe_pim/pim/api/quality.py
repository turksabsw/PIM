"""
Quality API Endpoints for PIM

Provides API endpoints for data quality scoring, validation, and
channel readiness assessment. Calculates completeness scores,
identifies missing fields, and validates products against channel
requirements.

Key Features:
- Product quality scoring (0-100 scale)
- Channel-specific readiness scores
- Missing required field detection
- Quality issue identification
- Bulk quality assessment

Note: frappe imports are deferred to function/method level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union
import json


# =============================================================================
# Custom Exceptions
# =============================================================================

class QualityError(Exception):
    """Base exception for quality-related errors"""

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


class ProductNotFoundError(QualityError):
    """Raised when product is not found"""
    pass


class ChannelNotFoundError(QualityError):
    """Raised when channel is not found"""
    pass


class ValidationError(QualityError):
    """Raised when validation fails"""
    pass


# =============================================================================
# Enums and Constants
# =============================================================================

class QualityLevel(str, Enum):
    """Quality level classification"""
    EXCELLENT = "excellent"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    CRITICAL = "critical"


class IssueType(str, Enum):
    """Types of quality issues"""
    MISSING_REQUIRED = "missing_required"
    MISSING_RECOMMENDED = "missing_recommended"
    INVALID_FORMAT = "invalid_format"
    INVALID_LENGTH = "invalid_length"
    INVALID_VALUE = "invalid_value"
    MISSING_IMAGE = "missing_image"
    LOW_IMAGE_QUALITY = "low_image_quality"
    MISSING_DESCRIPTION = "missing_description"
    SHORT_DESCRIPTION = "short_description"
    MISSING_PRICE = "missing_price"
    MISSING_GTIN = "missing_gtin"
    INVALID_GTIN = "invalid_gtin"


class IssueSeverity(str, Enum):
    """Severity levels for quality issues"""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


# Required fields for base product quality
REQUIRED_FIELDS = [
    "item_code",
    "item_name",
    "item_group",
]

# Recommended fields for better quality score
RECOMMENDED_FIELDS = [
    "item_name",
    "description",
    "brand",
    "custom_pim_long_description",
    "standard_rate",
    "weight_per_unit",
    "stock_uom",
]

# PIM-specific custom fields on Item (custom_field.json fixture uses custom_pim_* prefix)
PIM_FIELDS = [
    "custom_pim_status",
    "custom_pim_long_description",
    "custom_pim_completeness",
    "custom_pim_product_family",
    "custom_pim_product_type",
    "custom_pim_seo_title",
    "custom_pim_meta_description",
]

# Field weights for quality scoring (0-1)
FIELD_WEIGHTS = {
    # Required fields (higher weight)
    "item_code": 0.10,
    "item_name": 0.10,
    "item_group": 0.08,
    # PIM core fields
    "description": 0.15,
    "custom_pim_long_description": 0.12,
    "custom_pim_status": 0.05,
    # Product details
    "brand": 0.08,
    "manufacturer": 0.05,
    "custom_pim_product_family": 0.03,
    # Pricing and inventory
    "standard_rate": 0.08,
    "weight_per_unit": 0.03,
    "stock_uom": 0.02,
    # GTIN/Barcode
    "barcode": 0.06,
}

# Channel-specific required fields
CHANNEL_REQUIRED_FIELDS = {
    "amazon": [
        "item_code",
        "item_name",
        "description",
        "brand",
        "barcode",
        "standard_rate",
        "item_group",
    ],
    "amazon_us": [
        "item_code",
        "item_name",
        "description",
        "brand",
        "barcode",
        "standard_rate",
        "item_group",
    ],
    "shopify": [
        "item_code",
        "item_name",
        "description",
        "standard_rate",
    ],
    "ebay": [
        "item_code",
        "item_name",
        "description",
        "item_group",
        "standard_rate",
    ],
    "walmart": [
        "item_code",
        "item_name",
        "description",
        "brand",
        "barcode",
        "standard_rate",
        "item_group",
    ],
    "trendyol": [
        "item_code",
        "item_name",
        "description",
        "brand",
        "barcode",
        "standard_rate",
        "item_group",
    ],
    "n11": [
        "item_code",
        "item_name",
        "description",
        "standard_rate",
        "item_group",
    ],
    "hepsiburada": [
        "item_code",
        "item_name",
        "description",
        "brand",
        "barcode",
        "standard_rate",
        "item_group",
    ],
}

# Default channel requirements for unknown channels
DEFAULT_CHANNEL_FIELDS = [
    "item_code",
    "item_name",
    "description",
    "standard_rate",
]

# Minimum description length for quality
MIN_DESCRIPTION_LENGTH = 50
MIN_TITLE_LENGTH = 10
MAX_TITLE_LENGTH = 200


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class QualityIssue:
    """Represents a single quality issue"""
    field: str
    issue_type: IssueType
    severity: IssueSeverity
    message: str
    current_value: Any = None
    expected_value: Any = None

    def to_dict(self) -> Dict:
        return {
            "field": self.field,
            "issue_type": self.issue_type.value if isinstance(self.issue_type, IssueType) else self.issue_type,
            "severity": self.severity.value if isinstance(self.severity, IssueSeverity) else self.severity,
            "message": self.message,
            "current_value": str(self.current_value) if self.current_value is not None else None,
            "expected_value": str(self.expected_value) if self.expected_value is not None else None,
        }


@dataclass
class QualityScore:
    """Quality score result for a product"""
    product: str
    score: float  # 0-100
    level: QualityLevel
    completeness: float  # 0-100
    issues: List[QualityIssue] = field(default_factory=list)
    missing_required: List[str] = field(default_factory=list)
    missing_recommended: List[str] = field(default_factory=list)
    field_scores: Dict[str, float] = field(default_factory=dict)
    calculated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict:
        return {
            "product": self.product,
            "score": round(self.score, 2),
            "level": self.level.value if isinstance(self.level, QualityLevel) else self.level,
            "completeness": round(self.completeness, 2),
            "issues": [i.to_dict() for i in self.issues],
            "missing_required": self.missing_required,
            "missing_recommended": self.missing_recommended,
            "field_scores": self.field_scores,
            "calculated_at": self.calculated_at.isoformat(),
        }


@dataclass
class ChannelReadiness:
    """Channel readiness score for a product"""
    product: str
    channel: str
    channel_name: str
    is_ready: bool
    score: float  # 0-100
    missing_fields: List[str] = field(default_factory=list)
    issues: List[QualityIssue] = field(default_factory=list)
    validation_errors: List[Dict] = field(default_factory=list)
    calculated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict:
        return {
            "product": self.product,
            "channel": self.channel,
            "channel_name": self.channel_name,
            "is_ready": self.is_ready,
            "score": round(self.score, 2),
            "missing_fields": self.missing_fields,
            "issues": [i.to_dict() for i in self.issues],
            "validation_errors": self.validation_errors,
            "calculated_at": self.calculated_at.isoformat(),
        }


@dataclass
class QualityValidationResult:
    """Result of quality validation"""
    product: str
    is_valid: bool
    score: float
    errors: List[QualityIssue] = field(default_factory=list)
    warnings: List[QualityIssue] = field(default_factory=list)
    info: List[QualityIssue] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "product": self.product,
            "is_valid": self.is_valid,
            "score": round(self.score, 2),
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
            "info": [i.to_dict() for i in self.info],
        }


@dataclass
class QualitySummary:
    """Summary of quality for multiple products"""
    total_products: int
    average_score: float
    distribution: Dict[str, int]  # level -> count
    top_issues: List[Dict]  # Most common issues
    calculated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict:
        return {
            "total_products": self.total_products,
            "average_score": round(self.average_score, 2),
            "distribution": self.distribution,
            "top_issues": self.top_issues,
            "calculated_at": self.calculated_at.isoformat(),
        }


# =============================================================================
# Helper Functions
# =============================================================================

def _get_quality_level(score: float) -> QualityLevel:
    """Convert numeric score to quality level.

    Args:
        score: Quality score (0-100)

    Returns:
        QualityLevel enum value
    """
    if score >= 90:
        return QualityLevel.EXCELLENT
    elif score >= 75:
        return QualityLevel.GOOD
    elif score >= 50:
        return QualityLevel.FAIR
    elif score >= 25:
        return QualityLevel.POOR
    else:
        return QualityLevel.CRITICAL


def _is_field_populated(value: Any) -> bool:
    """Check if a field value is considered populated.

    Args:
        value: Field value to check

    Returns:
        True if the field has a meaningful value
    """
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    if isinstance(value, (int, float)):
        return value != 0
    return bool(value)


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

    # Add PIM custom fields if they exist
    for pim_field in PIM_FIELDS:
        if hasattr(item, pim_field):
            product_data[pim_field] = getattr(item, pim_field)

    # Check for barcode
    if hasattr(item, 'barcodes') and item.barcodes:
        product_data['barcode'] = item.barcodes[0].barcode if item.barcodes else None
    elif hasattr(item, 'barcode'):
        product_data['barcode'] = item.barcode

    return product_data


def _get_channel_config(channel_code: str) -> Dict:
    """Get channel configuration.

    Args:
        channel_code: Channel code (e.g., 'amazon', 'shopify')

    Returns:
        Dictionary with channel configuration
    """
    import frappe

    channel_code_lower = channel_code.lower()

    # Try to get channel from database
    channel_doc = None
    try:
        if frappe.db.exists("Channel", {"channel_code": channel_code_lower}):
            channel_doc = frappe.get_doc("Channel", {"channel_code": channel_code_lower})
    except Exception:
        pass

    # Get required fields for this channel
    required_fields = CHANNEL_REQUIRED_FIELDS.get(
        channel_code_lower,
        DEFAULT_CHANNEL_FIELDS
    )

    # Build config
    config = {
        "channel_code": channel_code_lower,
        "channel_name": channel_doc.channel_name if channel_doc else channel_code.title(),
        "required_fields": required_fields,
        "is_active": channel_doc.enabled if channel_doc else True,
    }

    return config


def _validate_gtin(gtin: str) -> Tuple[bool, str]:
    """Validate GTIN/barcode format and check digit.

    Args:
        gtin: GTIN string to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not gtin:
        return False, "GTIN is empty"

    # Remove any whitespace
    gtin = str(gtin).strip()

    # Check if numeric
    if not gtin.isdigit():
        return False, "GTIN must contain only digits"

    # Check valid lengths (GTIN-8, GTIN-12, GTIN-13, GTIN-14)
    if len(gtin) not in (8, 12, 13, 14):
        return False, f"Invalid GTIN length: {len(gtin)}. Must be 8, 12, 13, or 14 digits"

    # Validate check digit
    digits = [int(d) for d in gtin]
    check_digit = digits[-1]

    # Calculate expected check digit
    total = 0
    for i, digit in enumerate(digits[:-1]):
        if (len(gtin) - 1 - i) % 2 == 0:
            total += digit * 1
        else:
            total += digit * 3

    expected_check = (10 - (total % 10)) % 10

    if check_digit != expected_check:
        return False, f"Invalid check digit. Expected {expected_check}, got {check_digit}"

    return True, ""


# =============================================================================
# API Functions - Frappe Whitelisted
# =============================================================================

def get_quality_score(product_code: str) -> Dict:
    """Get the quality score for a product.

    Calculates a comprehensive quality score based on field completeness,
    data validity, and quality rules.

    Args:
        product_code: Product/Item code

    Returns:
        Dictionary with quality score details

    Example:
        result = get_quality_score("PROD-001")
        # Returns: {"product": "PROD-001", "score": 85.5, "level": "good", ...}
    """
    import frappe

    try:
        # Get product data
        product_data = _get_product_data(product_code)

        # Calculate quality score
        score_result = calculate_quality_score(product_data)

        # Update product with calculated score if writable
        try:
            if frappe.has_permission("Item", "write", product_code):
                frappe.db.set_value(
                    "Item", product_code,
                    {
                        "custom_pim_data_quality_score": score_result.score,
                        "custom_pim_completeness": score_result.completeness,
                    },
                    update_modified=False
                )
        except Exception:
            pass  # Don't fail if we can't update

        return score_result.to_dict()

    except ProductNotFoundError as e:
        frappe.throw(e.message, exc=frappe.DoesNotExistError)
    except Exception as e:
        frappe.log_error(f"Quality score calculation failed: {e}")
        frappe.throw(str(e))


def get_channel_readiness(product_code: str, channel: str = None) -> Union[Dict, List[Dict]]:
    """Get channel readiness score for a product.

    Calculates how ready a product is for publishing to a specific channel
    or all configured channels.

    Args:
        product_code: Product/Item code
        channel: Optional channel code. If None, returns readiness for all channels.

    Returns:
        Dictionary with channel readiness details, or list of dicts for all channels

    Example:
        # Single channel
        result = get_channel_readiness("PROD-001", "amazon")
        # Returns: {"product": "PROD-001", "channel": "amazon", "is_ready": True, ...}

        # All channels
        results = get_channel_readiness("PROD-001")
        # Returns: [{"channel": "amazon", ...}, {"channel": "shopify", ...}]
    """
    import frappe

    try:
        # Get product data
        product_data = _get_product_data(product_code)

        if channel:
            # Single channel readiness
            readiness = _calculate_channel_readiness(product_data, channel)
            return readiness.to_dict()
        else:
            # All channels readiness
            results = []
            for channel_code in CHANNEL_REQUIRED_FIELDS.keys():
                try:
                    readiness = _calculate_channel_readiness(product_data, channel_code)
                    results.append(readiness.to_dict())
                except Exception:
                    pass  # Skip channels with errors

            return results

    except ProductNotFoundError as e:
        frappe.throw(e.message, exc=frappe.DoesNotExistError)
    except Exception as e:
        frappe.log_error(f"Channel readiness calculation failed: {e}")
        frappe.throw(str(e))


def get_missing_fields(product_code: str, channel: str = None) -> Dict:
    """Get missing required and recommended fields for a product.

    Args:
        product_code: Product/Item code
        channel: Optional channel code to get channel-specific missing fields

    Returns:
        Dictionary with missing required and recommended fields

    Example:
        result = get_missing_fields("PROD-001")
        # Returns: {"missing_required": ["brand"], "missing_recommended": ["description"]}

        result = get_missing_fields("PROD-001", "amazon")
        # Returns channel-specific missing fields
    """
    import frappe

    try:
        # Get product data
        product_data = _get_product_data(product_code)

        missing_required = []
        missing_recommended = []

        if channel:
            # Channel-specific required fields
            channel_config = _get_channel_config(channel)
            required_fields = channel_config["required_fields"]
        else:
            # General required fields
            required_fields = REQUIRED_FIELDS

        # Check required fields
        for field_name in required_fields:
            value = product_data.get(field_name)
            if not _is_field_populated(value):
                missing_required.append(field_name)

        # Check recommended fields (only for general, not channel-specific)
        if not channel:
            for field_name in RECOMMENDED_FIELDS:
                if field_name not in required_fields:
                    value = product_data.get(field_name)
                    if not _is_field_populated(value):
                        missing_recommended.append(field_name)

        return {
            "product": product_code,
            "channel": channel,
            "missing_required": missing_required,
            "missing_recommended": missing_recommended,
            "required_count": len(missing_required),
            "recommended_count": len(missing_recommended),
        }

    except ProductNotFoundError as e:
        frappe.throw(e.message, exc=frappe.DoesNotExistError)
    except Exception as e:
        frappe.log_error(f"Missing fields check failed: {e}")
        frappe.throw(str(e))


def calculate_quality_score(product_data: Dict) -> QualityScore:
    """Calculate quality score for product data.

    Calculates a weighted quality score based on field completeness,
    content quality, and validation rules.

    Args:
        product_data: Dictionary with product field values

    Returns:
        QualityScore object with detailed scoring information
    """
    product_code = product_data.get("item_code") or product_data.get("name", "unknown")

    issues = []
    missing_required = []
    missing_recommended = []
    field_scores = {}

    total_weight = 0
    weighted_score = 0

    # Check required fields
    for field_name in REQUIRED_FIELDS:
        weight = FIELD_WEIGHTS.get(field_name, 0.05)
        total_weight += weight

        value = product_data.get(field_name)
        if _is_field_populated(value):
            field_scores[field_name] = 100
            weighted_score += weight * 100
        else:
            field_scores[field_name] = 0
            missing_required.append(field_name)
            issues.append(QualityIssue(
                field=field_name,
                issue_type=IssueType.MISSING_REQUIRED,
                severity=IssueSeverity.ERROR,
                message=f"Required field '{field_name}' is missing",
            ))

    # Check recommended fields
    for field_name in RECOMMENDED_FIELDS:
        if field_name in REQUIRED_FIELDS:
            continue

        weight = FIELD_WEIGHTS.get(field_name, 0.03)
        total_weight += weight

        value = product_data.get(field_name)
        if _is_field_populated(value):
            field_scores[field_name] = 100
            weighted_score += weight * 100
        else:
            field_scores[field_name] = 0
            missing_recommended.append(field_name)
            issues.append(QualityIssue(
                field=field_name,
                issue_type=IssueType.MISSING_RECOMMENDED,
                severity=IssueSeverity.WARNING,
                message=f"Recommended field '{field_name}' is missing",
            ))

    # Validate content quality for populated fields

    # Title length check
    title = product_data.get("item_name") or ""
    if title:
        if len(title) < MIN_TITLE_LENGTH:
            issues.append(QualityIssue(
                field="item_name",
                issue_type=IssueType.INVALID_LENGTH,
                severity=IssueSeverity.WARNING,
                message=f"Title is too short (min {MIN_TITLE_LENGTH} characters)",
                current_value=len(title),
                expected_value=MIN_TITLE_LENGTH,
            ))
            # Reduce field score
            if "item_name" in field_scores:
                field_scores["item_name"] = 50

        if len(title) > MAX_TITLE_LENGTH:
            issues.append(QualityIssue(
                field="item_name",
                issue_type=IssueType.INVALID_LENGTH,
                severity=IssueSeverity.WARNING,
                message=f"Title is too long (max {MAX_TITLE_LENGTH} characters)",
                current_value=len(title),
                expected_value=MAX_TITLE_LENGTH,
            ))
            if "item_name" in field_scores:
                field_scores["item_name"] = 70

    # Description length check
    description = product_data.get("description") or product_data.get("custom_pim_long_description") or ""
    if description:
        if len(description) < MIN_DESCRIPTION_LENGTH:
            issues.append(QualityIssue(
                field="description",
                issue_type=IssueType.SHORT_DESCRIPTION,
                severity=IssueSeverity.WARNING,
                message=f"Description is too short (min {MIN_DESCRIPTION_LENGTH} characters)",
                current_value=len(description),
                expected_value=MIN_DESCRIPTION_LENGTH,
            ))
            if "description" in field_scores:
                field_scores["description"] = 60

    # GTIN validation
    barcode = product_data.get("barcode")
    if barcode:
        is_valid, error_msg = _validate_gtin(barcode)
        if not is_valid:
            issues.append(QualityIssue(
                field="barcode",
                issue_type=IssueType.INVALID_GTIN,
                severity=IssueSeverity.ERROR,
                message=f"Invalid GTIN: {error_msg}",
                current_value=barcode,
            ))
            if "barcode" in field_scores:
                field_scores["barcode"] = 0
    else:
        issues.append(QualityIssue(
            field="barcode",
            issue_type=IssueType.MISSING_GTIN,
            severity=IssueSeverity.WARNING,
            message="Product is missing GTIN/barcode",
        ))

    # Price check
    price = product_data.get("standard_rate")
    if not price or price <= 0:
        issues.append(QualityIssue(
            field="standard_rate",
            issue_type=IssueType.MISSING_PRICE,
            severity=IssueSeverity.WARNING,
            message="Product is missing price or has zero price",
            current_value=price,
        ))

    # Calculate final scores
    if total_weight > 0:
        score = weighted_score / total_weight
    else:
        score = 0

    # Calculate completeness (percentage of all fields filled)
    all_fields = set(REQUIRED_FIELDS + RECOMMENDED_FIELDS)
    filled_count = sum(1 for f in all_fields if _is_field_populated(product_data.get(f)))
    completeness = (filled_count / len(all_fields)) * 100 if all_fields else 0

    # Determine quality level
    level = _get_quality_level(score)

    return QualityScore(
        product=product_code,
        score=score,
        level=level,
        completeness=completeness,
        issues=issues,
        missing_required=missing_required,
        missing_recommended=missing_recommended,
        field_scores=field_scores,
    )


def _calculate_channel_readiness(product_data: Dict, channel_code: str) -> ChannelReadiness:
    """Calculate channel readiness for a product.

    Args:
        product_data: Dictionary with product field values
        channel_code: Channel code (e.g., 'amazon', 'shopify')

    Returns:
        ChannelReadiness object with readiness details
    """
    product_code = product_data.get("item_code") or product_data.get("name", "unknown")

    # Get channel configuration
    channel_config = _get_channel_config(channel_code)
    required_fields = channel_config["required_fields"]
    channel_name = channel_config["channel_name"]

    issues = []
    missing_fields = []
    validation_errors = []

    # Check required fields for this channel
    for field_name in required_fields:
        value = product_data.get(field_name)
        if not _is_field_populated(value):
            missing_fields.append(field_name)
            issues.append(QualityIssue(
                field=field_name,
                issue_type=IssueType.MISSING_REQUIRED,
                severity=IssueSeverity.ERROR,
                message=f"Required for {channel_name}: '{field_name}' is missing",
            ))

    # Validate GTIN for channels that require it
    if "barcode" in required_fields:
        barcode = product_data.get("barcode")
        if barcode:
            is_valid, error_msg = _validate_gtin(barcode)
            if not is_valid:
                validation_errors.append({
                    "field": "barcode",
                    "error": error_msg,
                })
                issues.append(QualityIssue(
                    field="barcode",
                    issue_type=IssueType.INVALID_GTIN,
                    severity=IssueSeverity.ERROR,
                    message=f"Invalid GTIN for {channel_name}: {error_msg}",
                    current_value=barcode,
                ))

    # Calculate readiness score
    if required_fields:
        filled_count = len(required_fields) - len(missing_fields)
        score = (filled_count / len(required_fields)) * 100
    else:
        score = 100

    # Reduce score for validation errors
    if validation_errors:
        score = max(0, score - (len(validation_errors) * 10))

    # Product is ready if all required fields are present and valid
    is_ready = len(missing_fields) == 0 and len(validation_errors) == 0

    return ChannelReadiness(
        product=product_code,
        channel=channel_code,
        channel_name=channel_name,
        is_ready=is_ready,
        score=score,
        missing_fields=missing_fields,
        issues=issues,
        validation_errors=validation_errors,
    )


def validate_product_quality(product_code: str) -> Dict:
    """Validate product quality and return detailed validation result.

    Args:
        product_code: Product/Item code

    Returns:
        Dictionary with validation results including errors, warnings, and info

    Example:
        result = validate_product_quality("PROD-001")
        # Returns: {"is_valid": False, "errors": [...], "warnings": [...]}
    """
    import frappe

    try:
        # Get product data
        product_data = _get_product_data(product_code)

        # Calculate quality score
        score_result = calculate_quality_score(product_data)

        # Categorize issues by severity
        errors = [i for i in score_result.issues if i.severity == IssueSeverity.ERROR]
        warnings = [i for i in score_result.issues if i.severity == IssueSeverity.WARNING]
        info = [i for i in score_result.issues if i.severity == IssueSeverity.INFO]

        # Product is valid if no errors
        is_valid = len(errors) == 0

        result = QualityValidationResult(
            product=product_code,
            is_valid=is_valid,
            score=score_result.score,
            errors=errors,
            warnings=warnings,
            info=info,
        )

        return result.to_dict()

    except ProductNotFoundError as e:
        frappe.throw(e.message, exc=frappe.DoesNotExistError)
    except Exception as e:
        frappe.log_error(f"Quality validation failed: {e}")
        frappe.throw(str(e))


def get_quality_issues(product_code: str, severity: str = None) -> List[Dict]:
    """Get quality issues for a product.

    Args:
        product_code: Product/Item code
        severity: Optional filter by severity ('error', 'warning', 'info')

    Returns:
        List of quality issues

    Example:
        issues = get_quality_issues("PROD-001")
        # Returns: [{"field": "brand", "severity": "error", ...}]

        errors = get_quality_issues("PROD-001", severity="error")
    """
    import frappe

    try:
        # Get product data
        product_data = _get_product_data(product_code)

        # Calculate quality score to get issues
        score_result = calculate_quality_score(product_data)

        issues = score_result.issues

        # Filter by severity if specified
        if severity:
            severity_enum = IssueSeverity(severity.lower())
            issues = [i for i in issues if i.severity == severity_enum]

        return [i.to_dict() for i in issues]

    except ProductNotFoundError as e:
        frappe.throw(e.message, exc=frappe.DoesNotExistError)
    except Exception as e:
        frappe.log_error(f"Get quality issues failed: {e}")
        frappe.throw(str(e))


def get_quality_summary(filters: Dict = None, limit: int = 1000) -> Dict:
    """Get quality summary for multiple products.

    Args:
        filters: Optional Frappe filters for product selection
        limit: Maximum number of products to include

    Returns:
        Dictionary with quality summary statistics

    Example:
        summary = get_quality_summary()
        # Returns: {"total_products": 100, "average_score": 72.5, ...}

        summary = get_quality_summary(filters={"item_group": "Electronics"})
    """
    import frappe

    try:
        # Get products
        products = frappe.get_all(
            "Item",
            filters=filters or {},
            fields=["name", "item_code", "item_name", "item_group", "brand",
                    "description", "stock_uom", "standard_rate", "disabled"]
                    + [f for f in PIM_FIELDS if frappe.db.has_column("Item", f)],
            limit_page_length=limit,
        )

        if not products:
            return QualitySummary(
                total_products=0,
                average_score=0,
                distribution={},
                top_issues=[],
            ).to_dict()

        # Calculate scores for all products
        total_score = 0
        distribution = {level.value: 0 for level in QualityLevel}
        issue_counts = {}

        for product in products:
            product_data = dict(product)
            score_result = calculate_quality_score(product_data)

            total_score += score_result.score
            distribution[score_result.level.value] += 1

            # Count issues
            for issue in score_result.issues:
                key = f"{issue.issue_type.value}:{issue.field}"
                issue_counts[key] = issue_counts.get(key, 0) + 1

        # Calculate average
        average_score = total_score / len(products)

        # Get top issues
        top_issues = sorted(
            [{"issue": k, "count": v} for k, v in issue_counts.items()],
            key=lambda x: x["count"],
            reverse=True
        )[:10]

        return QualitySummary(
            total_products=len(products),
            average_score=average_score,
            distribution=distribution,
            top_issues=top_issues,
        ).to_dict()

    except Exception as e:
        frappe.log_error(f"Quality summary failed: {e}")
        frappe.throw(str(e))


def bulk_quality_check(product_codes: List[str]) -> List[Dict]:
    """Check quality for multiple products.

    Args:
        product_codes: List of product/item codes

    Returns:
        List of quality score dictionaries

    Example:
        results = bulk_quality_check(["PROD-001", "PROD-002", "PROD-003"])
    """
    import frappe

    results = []

    for product_code in product_codes:
        try:
            product_data = _get_product_data(product_code)
            score_result = calculate_quality_score(product_data)
            results.append(score_result.to_dict())
        except ProductNotFoundError:
            results.append({
                "product": product_code,
                "error": "Product not found",
                "score": 0,
                "level": QualityLevel.CRITICAL.value,
            })
        except Exception as e:
            results.append({
                "product": product_code,
                "error": str(e),
                "score": 0,
                "level": QualityLevel.CRITICAL.value,
            })

    return results


# =============================================================================
# Frappe Whitelist Decorators
# =============================================================================

def _whitelist_if_frappe():
    """Apply frappe.whitelist decorator if frappe is available."""
    try:
        import frappe
        return frappe.whitelist
    except ImportError:
        return lambda x: x


# Apply whitelist decorators
try:
    import frappe

    get_quality_score = frappe.whitelist()(get_quality_score)
    get_channel_readiness = frappe.whitelist()(get_channel_readiness)
    get_missing_fields = frappe.whitelist()(get_missing_fields)
    validate_product_quality = frappe.whitelist()(validate_product_quality)
    get_quality_issues = frappe.whitelist()(get_quality_issues)
    get_quality_summary = frappe.whitelist()(get_quality_summary)
    bulk_quality_check = frappe.whitelist()(bulk_quality_check)
except ImportError:
    pass  # Allow import without frappe for testing


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # API Functions
    "get_quality_score",
    "get_channel_readiness",
    "get_missing_fields",
    "calculate_quality_score",
    "validate_product_quality",
    "get_quality_issues",
    "get_quality_summary",
    "bulk_quality_check",

    # Data Classes
    "QualityScore",
    "ChannelReadiness",
    "QualityIssue",
    "QualityValidationResult",
    "QualitySummary",

    # Enums
    "QualityLevel",
    "IssueType",
    "IssueSeverity",

    # Exceptions
    "QualityError",
    "ProductNotFoundError",
    "ChannelNotFoundError",
    "ValidationError",

    # Constants
    "REQUIRED_FIELDS",
    "RECOMMENDED_FIELDS",
    "CHANNEL_REQUIRED_FIELDS",
    "FIELD_WEIGHTS",
]
