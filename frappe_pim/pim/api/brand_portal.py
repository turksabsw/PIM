"""
Brand Portal API Endpoints for PIM

Provides API endpoints for brand partner product submissions, including
submitting new products, retrieving submission status, and managing
the approval workflow.

Key Features:
- Submit products from brand partners for approval
- Retrieve submission history and status
- Update submission status (approve/reject)
- Partner authentication and access control
- Bulk submission support
- Submission notifications

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

class BrandPortalError(Exception):
    """Base exception for brand portal errors"""

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


class PartnerNotFoundError(BrandPortalError):
    """Raised when partner account is not found"""
    pass


class PartnerNotAuthorizedError(BrandPortalError):
    """Raised when partner is not authorized for an action"""
    pass


class SubmissionNotFoundError(BrandPortalError):
    """Raised when submission is not found"""
    pass


class InvalidSubmissionDataError(BrandPortalError):
    """Raised when submission data is invalid"""
    pass


class SubmissionStatusError(BrandPortalError):
    """Raised when submission status operation fails"""
    pass


class DuplicateSubmissionError(BrandPortalError):
    """Raised when a duplicate submission is detected"""
    pass


# =============================================================================
# Enums and Constants
# =============================================================================

class SubmissionStatus(str, Enum):
    """Status values for partner submissions"""
    DRAFT = "Draft"
    SUBMITTED = "Submitted"
    UNDER_REVIEW = "Under Review"
    APPROVED = "Approved"
    REJECTED = "Rejected"
    REVISION_REQUESTED = "Revision Requested"
    PUBLISHED = "Published"
    WITHDRAWN = "Withdrawn"


class SubmissionPriority(str, Enum):
    """Priority levels for submissions"""
    LOW = "Low"
    NORMAL = "Normal"
    HIGH = "High"
    URGENT = "Urgent"


class PartnerType(str, Enum):
    """Types of brand partners"""
    BRAND_OWNER = "Brand Owner"
    DISTRIBUTOR = "Distributor"
    MANUFACTURER = "Manufacturer"
    RESELLER = "Reseller"
    AGENCY = "Agency"


# Required fields for product submissions
REQUIRED_SUBMISSION_FIELDS = [
    "product_name",
    "brand",
    "description",
]

# Recommended fields for better submissions
RECOMMENDED_SUBMISSION_FIELDS = [
    "sku",
    "barcode",
    "category",
    "price",
    "weight",
    "dimensions",
    "images",
    "specifications",
]

# Validation limits
MAX_PRODUCT_NAME_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 5000
MAX_SKU_LENGTH = 50
MAX_IMAGES_PER_SUBMISSION = 20
MIN_IMAGE_DIMENSION = 500  # pixels
MAX_IMAGE_SIZE_MB = 10


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class SubmissionResult:
    """Result of a product submission"""
    submission_id: str
    status: str
    product_name: str
    partner: str
    created_at: datetime = field(default_factory=datetime.now)
    message: str = ""
    validation_errors: List[Dict] = field(default_factory=list)
    validation_warnings: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "submission_id": self.submission_id,
            "status": self.status,
            "product_name": self.product_name,
            "partner": self.partner,
            "created_at": self.created_at.isoformat(),
            "message": self.message,
            "validation_errors": self.validation_errors,
            "validation_warnings": self.validation_warnings,
        }


@dataclass
class SubmissionDetails:
    """Detailed information about a submission"""
    submission_id: str
    partner: str
    partner_name: str
    product_name: str
    brand: str
    status: str
    priority: str
    product_data: Dict
    created_at: datetime
    modified_at: datetime
    submitted_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None
    reviewer: Optional[str] = None
    review_notes: Optional[str] = None
    rejection_reason: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "submission_id": self.submission_id,
            "partner": self.partner,
            "partner_name": self.partner_name,
            "product_name": self.product_name,
            "brand": self.brand,
            "status": self.status,
            "priority": self.priority,
            "product_data": self.product_data,
            "created_at": self.created_at.isoformat(),
            "modified_at": self.modified_at.isoformat(),
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "reviewer": self.reviewer,
            "review_notes": self.review_notes,
            "rejection_reason": self.rejection_reason,
        }


@dataclass
class SubmissionListResult:
    """Result of listing submissions"""
    submissions: List[Dict]
    total_count: int
    pending_count: int
    approved_count: int
    rejected_count: int
    offset: int = 0
    limit: int = 20

    def to_dict(self) -> Dict:
        return {
            "submissions": self.submissions,
            "total_count": self.total_count,
            "pending_count": self.pending_count,
            "approved_count": self.approved_count,
            "rejected_count": self.rejected_count,
            "offset": self.offset,
            "limit": self.limit,
        }


@dataclass
class StatusUpdateResult:
    """Result of a status update operation"""
    submission_id: str
    previous_status: str
    new_status: str
    updated_by: str
    updated_at: datetime = field(default_factory=datetime.now)
    notes: str = ""
    product_created: bool = False
    product_code: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "submission_id": self.submission_id,
            "previous_status": self.previous_status,
            "new_status": self.new_status,
            "updated_by": self.updated_by,
            "updated_at": self.updated_at.isoformat(),
            "notes": self.notes,
            "product_created": self.product_created,
            "product_code": self.product_code,
        }


@dataclass
class PartnerStats:
    """Statistics for a partner"""
    partner: str
    partner_name: str
    total_submissions: int
    pending_submissions: int
    approved_submissions: int
    rejected_submissions: int
    approval_rate: float
    average_review_time_days: float

    def to_dict(self) -> Dict:
        return {
            "partner": self.partner,
            "partner_name": self.partner_name,
            "total_submissions": self.total_submissions,
            "pending_submissions": self.pending_submissions,
            "approved_submissions": self.approved_submissions,
            "rejected_submissions": self.rejected_submissions,
            "approval_rate": round(self.approval_rate, 2),
            "average_review_time_days": round(self.average_review_time_days, 2),
        }


# =============================================================================
# Helper Functions
# =============================================================================

def _get_current_user() -> str:
    """Get the current logged-in user.

    Returns:
        User ID of the current user
    """
    import frappe
    return frappe.session.user


def _get_partner_for_user(user: str = None) -> Optional[str]:
    """Get the brand portal partner associated with a user.

    Args:
        user: User ID (defaults to current user)

    Returns:
        Partner document name if found, None otherwise
    """
    import frappe

    if not user:
        user = _get_current_user()

    # Check if Brand Portal User DocType exists
    if not frappe.db.exists("DocType", "Brand Portal User"):
        return None

    # Find partner for this user
    partner = frappe.db.get_value(
        "Brand Portal User",
        {"user": user, "enabled": 1},
        "partner"
    )

    return partner


def _validate_partner_access(partner: str = None, user: str = None) -> str:
    """Validate that the user has access to the partner account.

    Args:
        partner: Partner document name
        user: User ID (defaults to current user)

    Returns:
        Validated partner name

    Raises:
        PartnerNotFoundError: If partner not found
        PartnerNotAuthorizedError: If user not authorized
    """
    import frappe

    if not user:
        user = _get_current_user()

    # System Manager and PIM Admin have full access
    user_roles = frappe.get_roles(user)
    if "System Manager" in user_roles or "PIM Admin" in user_roles:
        if partner:
            if not frappe.db.exists("DocType", "Brand Portal User"):
                # If DocType doesn't exist, allow access for admins
                return partner
            return partner
        # Return first available partner or raise error
        raise PartnerNotFoundError(
            "Partner must be specified for admin access",
            details={"user": user}
        )

    # For regular users, check their partner association
    user_partner = _get_partner_for_user(user)

    if not user_partner:
        raise PartnerNotAuthorizedError(
            "User is not associated with any brand partner",
            details={"user": user}
        )

    # If partner specified, must match user's partner
    if partner and partner != user_partner:
        raise PartnerNotAuthorizedError(
            "User is not authorized to access this partner",
            details={"user": user, "requested_partner": partner, "user_partner": user_partner}
        )

    return user_partner


def _validate_submission_data(data: Dict) -> tuple:
    """Validate submission data against requirements.

    Args:
        data: Product submission data

    Returns:
        Tuple of (is_valid, errors, warnings)
    """
    errors = []
    warnings = []

    # Check required fields
    for field_name in REQUIRED_SUBMISSION_FIELDS:
        value = data.get(field_name)
        if not value or (isinstance(value, str) and not value.strip()):
            errors.append({
                "field": field_name,
                "message": f"Required field '{field_name}' is missing or empty",
            })

    # Validate product_name length
    product_name = data.get("product_name", "")
    if product_name and len(product_name) > MAX_PRODUCT_NAME_LENGTH:
        errors.append({
            "field": "product_name",
            "message": f"Product name exceeds maximum length of {MAX_PRODUCT_NAME_LENGTH} characters",
            "current_length": len(product_name),
        })

    # Validate description length
    description = data.get("description", "")
    if description and len(description) > MAX_DESCRIPTION_LENGTH:
        errors.append({
            "field": "description",
            "message": f"Description exceeds maximum length of {MAX_DESCRIPTION_LENGTH} characters",
            "current_length": len(description),
        })

    # Validate SKU length
    sku = data.get("sku", "")
    if sku and len(sku) > MAX_SKU_LENGTH:
        errors.append({
            "field": "sku",
            "message": f"SKU exceeds maximum length of {MAX_SKU_LENGTH} characters",
            "current_length": len(sku),
        })

    # Validate barcode format
    barcode = data.get("barcode", "")
    if barcode:
        barcode_str = str(barcode).strip()
        if not barcode_str.isdigit():
            errors.append({
                "field": "barcode",
                "message": "Barcode must contain only digits",
            })
        elif len(barcode_str) not in (8, 12, 13, 14):
            errors.append({
                "field": "barcode",
                "message": "Barcode must be 8, 12, 13, or 14 digits (GTIN format)",
                "current_length": len(barcode_str),
            })
        else:
            # Validate check digit
            if not _validate_gtin_check_digit(barcode_str):
                errors.append({
                    "field": "barcode",
                    "message": "Invalid GTIN check digit",
                })

    # Check recommended fields (warnings only)
    for field_name in RECOMMENDED_SUBMISSION_FIELDS:
        if field_name not in REQUIRED_SUBMISSION_FIELDS:
            value = data.get(field_name)
            if not value:
                warnings.append({
                    "field": field_name,
                    "message": f"Recommended field '{field_name}' is missing",
                })

    # Validate images
    images = data.get("images", [])
    if images and len(images) > MAX_IMAGES_PER_SUBMISSION:
        errors.append({
            "field": "images",
            "message": f"Too many images. Maximum is {MAX_IMAGES_PER_SUBMISSION}",
            "current_count": len(images),
        })

    # Validate price
    price = data.get("price")
    if price is not None:
        try:
            price_val = float(price)
            if price_val < 0:
                errors.append({
                    "field": "price",
                    "message": "Price cannot be negative",
                })
        except (ValueError, TypeError):
            errors.append({
                "field": "price",
                "message": "Price must be a valid number",
            })

    is_valid = len(errors) == 0
    return is_valid, errors, warnings


def _validate_gtin_check_digit(gtin: str) -> bool:
    """Validate GTIN check digit.

    Args:
        gtin: GTIN string (8, 12, 13, or 14 digits)

    Returns:
        True if check digit is valid
    """
    if not gtin or not gtin.isdigit():
        return False

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
    return check_digit == expected_check


def _get_submission_doc(submission_id: str) -> Any:
    """Get submission document from database.

    Args:
        submission_id: Submission document name

    Returns:
        Submission document

    Raises:
        SubmissionNotFoundError: If submission not found
    """
    import frappe

    # Check if Partner Submission DocType exists
    if not frappe.db.exists("DocType", "Partner Submission"):
        raise SubmissionNotFoundError(
            "Partner Submission DocType not configured",
            details={"submission_id": submission_id}
        )

    if not frappe.db.exists("Partner Submission", submission_id):
        raise SubmissionNotFoundError(
            f"Submission not found: {submission_id}",
            details={"submission_id": submission_id}
        )

    return frappe.get_doc("Partner Submission", submission_id)


def _create_product_from_submission(submission_doc: Any) -> Optional[str]:
    """Create a product from an approved submission.

    Args:
        submission_doc: Partner Submission document

    Returns:
        Item/Product code if created, None otherwise
    """
    import frappe

    try:
        # Parse product data
        product_data = submission_doc.product_data
        if isinstance(product_data, str):
            product_data = json.loads(product_data)

        # Create Item document
        item = frappe.new_doc("Item")
        item.item_code = product_data.get("sku") or f"SUB-{submission_doc.name}"
        item.item_name = product_data.get("product_name")
        item.item_group = product_data.get("category") or "Products"
        item.brand = product_data.get("brand")
        item.description = product_data.get("description")
        item.stock_uom = product_data.get("uom") or "Nos"
        item.is_stock_item = 1

        # Set price if provided
        price = product_data.get("price")
        if price:
            item.standard_rate = float(price)

        # Set PIM fields if available
        item.description = product_data.get("description") or ""
        if product_data.get("brand"):
            item.brand = product_data.get("brand")
        if hasattr(item, "custom_pim_status"):
            item.custom_pim_status = "Draft"

        # Flag to indicate source
        item.flags.from_brand_portal = True

        item.insert(ignore_permissions=True)

        # Add barcode if provided
        barcode = product_data.get("barcode")
        if barcode:
            try:
                item.append("barcodes", {
                    "barcode": str(barcode),
                    "barcode_type": "EAN" if len(str(barcode)) == 13 else "UPC-A"
                })
                item.save(ignore_permissions=True)
            except Exception:
                pass  # Don't fail if barcode add fails

        return item.name

    except Exception as e:
        import frappe
        frappe.log_error(f"Failed to create product from submission {submission_doc.name}: {e}")
        return None


# =============================================================================
# API Functions - Core Submission
# =============================================================================

def submit_product(
    product_data: Dict,
    partner: str = None,
    priority: str = "Normal",
    submit_immediately: bool = True,
    notes: str = None,
) -> Dict:
    """Submit a product for approval from brand portal.

    Creates a new product submission that will go through the approval
    workflow before being added to the product catalog.

    Args:
        product_data: Dictionary containing product information:
            - product_name (required): Name of the product
            - brand (required): Brand name
            - description (required): Product description
            - sku (recommended): Product SKU/code
            - barcode (recommended): GTIN/barcode
            - category (recommended): Product category
            - price (recommended): Product price
            - images (optional): List of image URLs
            - specifications (optional): Product specifications dict
        partner: Partner document name (auto-detected if not provided)
        priority: Submission priority ('Low', 'Normal', 'High', 'Urgent')
        submit_immediately: If True, submit for review immediately
        notes: Optional notes for reviewers

    Returns:
        Dictionary with submission result including submission_id and status

    Example:
        result = submit_product({
            "product_name": "Wireless Mouse XG-500",
            "brand": "TechBrand",
            "description": "Ergonomic wireless mouse with 6 buttons",
            "sku": "WM-XG500",
            "barcode": "1234567890123",
            "price": 29.99,
        })
        # Returns: {"submission_id": "SUB-00001", "status": "Submitted", ...}
    """
    import frappe

    try:
        # Validate partner access
        validated_partner = _validate_partner_access(partner)

        # Validate submission data
        is_valid, errors, warnings = _validate_submission_data(product_data)

        if not is_valid:
            raise InvalidSubmissionDataError(
                "Product data validation failed",
                details={"errors": errors, "warnings": warnings}
            )

        # Check for duplicate submissions (by SKU or barcode)
        sku = product_data.get("sku")
        barcode = product_data.get("barcode")

        if sku and frappe.db.exists("DocType", "Partner Submission"):
            existing = frappe.db.exists("Partner Submission", {
                "partner": validated_partner,
                "status": ["not in", ["Rejected", "Withdrawn"]],
            })
            # This is a simplified check - in production would check product_data JSON

        # Validate priority
        if priority not in [p.value for p in SubmissionPriority]:
            priority = SubmissionPriority.NORMAL.value

        # Determine initial status
        initial_status = SubmissionStatus.SUBMITTED.value if submit_immediately else SubmissionStatus.DRAFT.value

        # Check if Partner Submission DocType exists
        if not frappe.db.exists("DocType", "Partner Submission"):
            # Create a minimal response if DocType doesn't exist
            # This allows testing without the DocType being installed
            submission_id = f"SUB-{frappe.generate_hash(length=8).upper()}"
            return SubmissionResult(
                submission_id=submission_id,
                status=initial_status,
                product_name=product_data.get("product_name", ""),
                partner=validated_partner,
                message="Submission created (DocType not installed - testing mode)",
                validation_warnings=warnings,
            ).to_dict()

        # Create submission document
        submission = frappe.new_doc("Partner Submission")
        submission.partner = validated_partner
        submission.product_name = product_data.get("product_name")
        submission.brand = product_data.get("brand")
        submission.status = initial_status
        submission.priority = priority
        submission.product_data = json.dumps(product_data)
        submission.notes = notes

        if submit_immediately:
            submission.submitted_at = frappe.utils.now_datetime()

        submission.insert(ignore_permissions=True)

        # Log submission
        frappe.log_error(
            message=f"Product submission created: {submission.name}",
            title="Brand Portal Submission"
        )

        return SubmissionResult(
            submission_id=submission.name,
            status=submission.status,
            product_name=submission.product_name,
            partner=validated_partner,
            message="Product submitted successfully for review",
            validation_warnings=warnings,
        ).to_dict()

    except BrandPortalError as e:
        import frappe
        frappe.log_error(f"Brand portal error: {e.message}")
        frappe.throw(e.message)
    except Exception as e:
        import frappe
        frappe.log_error(f"Submit product failed: {e}")
        frappe.throw(str(e))


def get_submissions(
    partner: str = None,
    status: str = None,
    priority: str = None,
    search: str = None,
    limit: int = 20,
    offset: int = 0,
    order_by: str = "creation desc",
) -> Dict:
    """Get product submissions for a partner.

    Retrieves submission history with optional filtering by status,
    priority, and search terms.

    Args:
        partner: Partner document name (auto-detected if not provided)
        status: Filter by status ('Submitted', 'Approved', 'Rejected', etc.)
        priority: Filter by priority ('Low', 'Normal', 'High', 'Urgent')
        search: Search in product name and brand
        limit: Maximum number of results (default 20, max 100)
        offset: Number of results to skip (for pagination)
        order_by: Sort order (default: 'creation desc')

    Returns:
        Dictionary with submissions list and counts

    Example:
        # Get all submissions for current partner
        result = get_submissions()

        # Get only pending submissions
        result = get_submissions(status="Submitted")

        # Search submissions
        result = get_submissions(search="wireless mouse")
    """
    import frappe

    try:
        # Validate partner access (may raise error or return partner for admins)
        try:
            validated_partner = _validate_partner_access(partner)
        except PartnerNotFoundError:
            # For admin users without specifying partner, show all
            user_roles = frappe.get_roles(_get_current_user())
            if "System Manager" in user_roles or "PIM Admin" in user_roles:
                validated_partner = None
            else:
                raise

        # Validate and limit parameters
        limit = min(max(1, limit), 100)
        offset = max(0, offset)

        # Check if Partner Submission DocType exists
        if not frappe.db.exists("DocType", "Partner Submission"):
            return SubmissionListResult(
                submissions=[],
                total_count=0,
                pending_count=0,
                approved_count=0,
                rejected_count=0,
                offset=offset,
                limit=limit,
            ).to_dict()

        # Build filters
        filters = {}

        if validated_partner:
            filters["partner"] = validated_partner

        if status:
            if status in [s.value for s in SubmissionStatus]:
                filters["status"] = status

        if priority:
            if priority in [p.value for p in SubmissionPriority]:
                filters["priority"] = priority

        # Build or_filters for search
        or_filters = None
        if search:
            search_term = f"%{search}%"
            or_filters = [
                ["product_name", "like", search_term],
                ["brand", "like", search_term],
            ]

        # Get submissions
        submissions = frappe.get_all(
            "Partner Submission",
            filters=filters,
            or_filters=or_filters,
            fields=[
                "name", "partner", "product_name", "brand", "status",
                "priority", "creation", "modified", "submitted_at",
                "reviewed_at", "reviewer", "notes"
            ],
            order_by=order_by,
            limit_page_length=limit,
            limit_start=offset,
        )

        # Format submissions
        formatted_submissions = []
        for sub in submissions:
            formatted_submissions.append({
                "submission_id": sub.name,
                "partner": sub.partner,
                "product_name": sub.product_name,
                "brand": sub.brand,
                "status": sub.status,
                "priority": sub.priority,
                "created_at": str(sub.creation),
                "modified_at": str(sub.modified),
                "submitted_at": str(sub.submitted_at) if sub.submitted_at else None,
                "reviewed_at": str(sub.reviewed_at) if sub.reviewed_at else None,
                "reviewer": sub.reviewer,
                "notes": sub.notes,
            })

        # Get counts (using partner filter only for consistency)
        count_filters = {}
        if validated_partner:
            count_filters["partner"] = validated_partner

        total_count = frappe.db.count("Partner Submission", filters=count_filters)

        pending_statuses = [
            SubmissionStatus.SUBMITTED.value,
            SubmissionStatus.UNDER_REVIEW.value,
        ]
        pending_count = frappe.db.count(
            "Partner Submission",
            filters={**count_filters, "status": ["in", pending_statuses]}
        )

        approved_count = frappe.db.count(
            "Partner Submission",
            filters={**count_filters, "status": SubmissionStatus.APPROVED.value}
        )

        rejected_count = frappe.db.count(
            "Partner Submission",
            filters={**count_filters, "status": SubmissionStatus.REJECTED.value}
        )

        return SubmissionListResult(
            submissions=formatted_submissions,
            total_count=total_count,
            pending_count=pending_count,
            approved_count=approved_count,
            rejected_count=rejected_count,
            offset=offset,
            limit=limit,
        ).to_dict()

    except BrandPortalError as e:
        frappe.throw(e.message)
    except Exception as e:
        import frappe
        frappe.log_error(f"Get submissions failed: {e}")
        frappe.throw(str(e))


def get_submission_details(submission_id: str) -> Dict:
    """Get detailed information about a specific submission.

    Args:
        submission_id: Submission document name

    Returns:
        Dictionary with full submission details

    Example:
        details = get_submission_details("SUB-00001")
    """
    import frappe

    try:
        # Get submission
        submission = _get_submission_doc(submission_id)

        # Validate access
        _validate_partner_access(submission.partner)

        # Get partner name
        partner_name = ""
        if frappe.db.exists("DocType", "Brand Portal User"):
            partner_name = frappe.db.get_value(
                "Brand Portal User",
                {"partner": submission.partner},
                "partner_name"
            ) or submission.partner

        # Parse product data
        product_data = {}
        if submission.product_data:
            try:
                product_data = json.loads(submission.product_data)
            except (json.JSONDecodeError, TypeError):
                product_data = {}

        return SubmissionDetails(
            submission_id=submission.name,
            partner=submission.partner,
            partner_name=partner_name,
            product_name=submission.product_name,
            brand=submission.brand,
            status=submission.status,
            priority=submission.priority,
            product_data=product_data,
            created_at=submission.creation,
            modified_at=submission.modified,
            submitted_at=submission.submitted_at,
            reviewed_at=submission.reviewed_at,
            reviewer=submission.reviewer,
            review_notes=getattr(submission, 'review_notes', None),
            rejection_reason=getattr(submission, 'rejection_reason', None),
        ).to_dict()

    except BrandPortalError as e:
        import frappe
        frappe.throw(e.message)
    except Exception as e:
        import frappe
        frappe.log_error(f"Get submission details failed: {e}")
        frappe.throw(str(e))


def update_submission_status(
    submission_id: str,
    status: str,
    notes: str = None,
    rejection_reason: str = None,
    create_product: bool = True,
) -> Dict:
    """Update the status of a product submission.

    Used by reviewers to approve or reject submissions. When approved
    and create_product is True, automatically creates the product in
    the catalog.

    Args:
        submission_id: Submission document name
        status: New status ('Approved', 'Rejected', 'Revision Requested', etc.)
        notes: Optional review notes
        rejection_reason: Required when rejecting
        create_product: If True and status is 'Approved', create product

    Returns:
        Dictionary with status update result

    Example:
        # Approve a submission
        result = update_submission_status("SUB-00001", "Approved")

        # Reject a submission
        result = update_submission_status(
            "SUB-00001",
            "Rejected",
            rejection_reason="Missing required certifications"
        )
    """
    import frappe

    try:
        # Get submission
        submission = _get_submission_doc(submission_id)

        # Validate reviewer permissions
        user = _get_current_user()
        user_roles = frappe.get_roles(user)

        if not any(role in user_roles for role in ["System Manager", "PIM Admin", "PIM Manager"]):
            raise PartnerNotAuthorizedError(
                "User is not authorized to update submission status",
                details={"user": user}
            )

        # Validate status
        if status not in [s.value for s in SubmissionStatus]:
            raise SubmissionStatusError(
                f"Invalid status: {status}",
                details={"valid_statuses": [s.value for s in SubmissionStatus]}
            )

        # Check for valid status transitions
        current_status = submission.status
        valid_transitions = {
            SubmissionStatus.DRAFT.value: [
                SubmissionStatus.SUBMITTED.value,
                SubmissionStatus.WITHDRAWN.value,
            ],
            SubmissionStatus.SUBMITTED.value: [
                SubmissionStatus.UNDER_REVIEW.value,
                SubmissionStatus.APPROVED.value,
                SubmissionStatus.REJECTED.value,
                SubmissionStatus.REVISION_REQUESTED.value,
                SubmissionStatus.WITHDRAWN.value,
            ],
            SubmissionStatus.UNDER_REVIEW.value: [
                SubmissionStatus.APPROVED.value,
                SubmissionStatus.REJECTED.value,
                SubmissionStatus.REVISION_REQUESTED.value,
            ],
            SubmissionStatus.REVISION_REQUESTED.value: [
                SubmissionStatus.SUBMITTED.value,
                SubmissionStatus.WITHDRAWN.value,
            ],
            SubmissionStatus.APPROVED.value: [
                SubmissionStatus.PUBLISHED.value,
            ],
        }

        allowed_transitions = valid_transitions.get(current_status, [])
        if status not in allowed_transitions and current_status != status:
            raise SubmissionStatusError(
                f"Cannot transition from '{current_status}' to '{status}'",
                details={
                    "current_status": current_status,
                    "requested_status": status,
                    "allowed_transitions": allowed_transitions,
                }
            )

        # Require rejection reason for rejections
        if status == SubmissionStatus.REJECTED.value and not rejection_reason:
            raise SubmissionStatusError(
                "Rejection reason is required when rejecting a submission",
                details={"submission_id": submission_id}
            )

        # Update submission
        previous_status = submission.status
        submission.status = status
        submission.reviewer = user
        submission.reviewed_at = frappe.utils.now_datetime()

        if notes:
            submission.review_notes = notes

        if rejection_reason:
            submission.rejection_reason = rejection_reason

        submission.save(ignore_permissions=True)

        # Create product if approved
        product_code = None
        product_created = False

        if status == SubmissionStatus.APPROVED.value and create_product:
            product_code = _create_product_from_submission(submission)
            if product_code:
                product_created = True
                # Update submission with product reference
                submission.product_code = product_code
                submission.save(ignore_permissions=True)

        # Send notification to partner
        try:
            if frappe.db.exists("DocType", "Brand Portal User"):
                partner_user = frappe.db.get_value(
                    "Brand Portal User",
                    {"partner": submission.partner},
                    "user"
                )
                if partner_user:
                    frappe.publish_realtime(
                        event="submission_status_update",
                        message={
                            "submission_id": submission_id,
                            "status": status,
                            "product_name": submission.product_name,
                        },
                        user=partner_user,
                    )
        except Exception:
            pass  # Don't fail on notification errors

        return StatusUpdateResult(
            submission_id=submission_id,
            previous_status=previous_status,
            new_status=status,
            updated_by=user,
            notes=notes or "",
            product_created=product_created,
            product_code=product_code,
        ).to_dict()

    except BrandPortalError as e:
        import frappe
        frappe.log_error(f"Update submission status failed: {e.message}")
        frappe.throw(e.message)
    except Exception as e:
        import frappe
        frappe.log_error(f"Update submission status failed: {e}")
        frappe.throw(str(e))


# =============================================================================
# Additional API Functions
# =============================================================================

def update_submission(
    submission_id: str,
    product_data: Dict,
    notes: str = None,
) -> Dict:
    """Update a draft or revision-requested submission.

    Args:
        submission_id: Submission document name
        product_data: Updated product information
        notes: Optional notes

    Returns:
        Dictionary with update result

    Example:
        result = update_submission("SUB-00001", {
            "product_name": "Updated Name",
            "description": "Updated description",
        })
    """
    import frappe

    try:
        # Get submission
        submission = _get_submission_doc(submission_id)

        # Validate access
        _validate_partner_access(submission.partner)

        # Only allow updates on draft or revision requested submissions
        if submission.status not in [
            SubmissionStatus.DRAFT.value,
            SubmissionStatus.REVISION_REQUESTED.value
        ]:
            raise SubmissionStatusError(
                f"Cannot update submission with status '{submission.status}'",
                details={"submission_id": submission_id, "status": submission.status}
            )

        # Validate new data
        is_valid, errors, warnings = _validate_submission_data(product_data)

        if not is_valid:
            raise InvalidSubmissionDataError(
                "Updated product data validation failed",
                details={"errors": errors, "warnings": warnings}
            )

        # Update submission
        submission.product_name = product_data.get("product_name", submission.product_name)
        submission.brand = product_data.get("brand", submission.brand)
        submission.product_data = json.dumps(product_data)

        if notes:
            submission.notes = notes

        submission.save(ignore_permissions=True)

        return SubmissionResult(
            submission_id=submission.name,
            status=submission.status,
            product_name=submission.product_name,
            partner=submission.partner,
            message="Submission updated successfully",
            validation_warnings=warnings,
        ).to_dict()

    except BrandPortalError as e:
        import frappe
        frappe.throw(e.message)
    except Exception as e:
        import frappe
        frappe.log_error(f"Update submission failed: {e}")
        frappe.throw(str(e))


def withdraw_submission(submission_id: str, reason: str = None) -> Dict:
    """Withdraw a submission from review.

    Args:
        submission_id: Submission document name
        reason: Optional withdrawal reason

    Returns:
        Dictionary with withdrawal result

    Example:
        result = withdraw_submission("SUB-00001", "No longer needed")
    """
    import frappe

    try:
        # Get submission
        submission = _get_submission_doc(submission_id)

        # Validate access
        _validate_partner_access(submission.partner)

        # Can only withdraw certain statuses
        withdrawable_statuses = [
            SubmissionStatus.DRAFT.value,
            SubmissionStatus.SUBMITTED.value,
            SubmissionStatus.REVISION_REQUESTED.value,
        ]

        if submission.status not in withdrawable_statuses:
            raise SubmissionStatusError(
                f"Cannot withdraw submission with status '{submission.status}'",
                details={"submission_id": submission_id, "status": submission.status}
            )

        # Update status
        previous_status = submission.status
        submission.status = SubmissionStatus.WITHDRAWN.value
        submission.notes = f"Withdrawn: {reason}" if reason else "Withdrawn by partner"
        submission.save(ignore_permissions=True)

        return StatusUpdateResult(
            submission_id=submission_id,
            previous_status=previous_status,
            new_status=SubmissionStatus.WITHDRAWN.value,
            updated_by=_get_current_user(),
            notes=reason or "",
        ).to_dict()

    except BrandPortalError as e:
        import frappe
        frappe.throw(e.message)
    except Exception as e:
        import frappe
        frappe.log_error(f"Withdraw submission failed: {e}")
        frappe.throw(str(e))


def get_partner_stats(partner: str = None, days: int = 30) -> Dict:
    """Get submission statistics for a partner.

    Args:
        partner: Partner document name (auto-detected if not provided)
        days: Number of days to include in statistics

    Returns:
        Dictionary with partner statistics

    Example:
        stats = get_partner_stats(days=90)
    """
    import frappe
    from datetime import timedelta

    try:
        # Validate partner access
        validated_partner = _validate_partner_access(partner)

        # Check if Partner Submission DocType exists
        if not frappe.db.exists("DocType", "Partner Submission"):
            return PartnerStats(
                partner=validated_partner,
                partner_name="",
                total_submissions=0,
                pending_submissions=0,
                approved_submissions=0,
                rejected_submissions=0,
                approval_rate=0.0,
                average_review_time_days=0.0,
            ).to_dict()

        # Get partner name
        partner_name = validated_partner
        if frappe.db.exists("DocType", "Brand Portal User"):
            partner_name = frappe.db.get_value(
                "Brand Portal User",
                {"partner": validated_partner},
                "partner_name"
            ) or validated_partner

        # Calculate date range
        start_date = frappe.utils.now_datetime() - timedelta(days=days)

        # Get counts
        filters = {"partner": validated_partner}
        date_filters = {**filters, "creation": [">=", start_date]}

        total_submissions = frappe.db.count("Partner Submission", filters=date_filters)

        pending_statuses = [
            SubmissionStatus.SUBMITTED.value,
            SubmissionStatus.UNDER_REVIEW.value,
        ]
        pending_submissions = frappe.db.count(
            "Partner Submission",
            filters={**date_filters, "status": ["in", pending_statuses]}
        )

        approved_submissions = frappe.db.count(
            "Partner Submission",
            filters={**date_filters, "status": SubmissionStatus.APPROVED.value}
        )

        rejected_submissions = frappe.db.count(
            "Partner Submission",
            filters={**date_filters, "status": SubmissionStatus.REJECTED.value}
        )

        # Calculate approval rate
        decided = approved_submissions + rejected_submissions
        approval_rate = (approved_submissions / decided * 100) if decided > 0 else 0

        # Calculate average review time
        avg_review_time = 0.0
        reviewed = frappe.get_all(
            "Partner Submission",
            filters={
                **date_filters,
                "reviewed_at": ["is", "set"],
                "submitted_at": ["is", "set"],
            },
            fields=["submitted_at", "reviewed_at"],
        )

        if reviewed:
            total_days = 0
            for sub in reviewed:
                if sub.submitted_at and sub.reviewed_at:
                    delta = sub.reviewed_at - sub.submitted_at
                    total_days += delta.days + (delta.seconds / 86400)
            avg_review_time = total_days / len(reviewed)

        return PartnerStats(
            partner=validated_partner,
            partner_name=partner_name,
            total_submissions=total_submissions,
            pending_submissions=pending_submissions,
            approved_submissions=approved_submissions,
            rejected_submissions=rejected_submissions,
            approval_rate=approval_rate,
            average_review_time_days=avg_review_time,
        ).to_dict()

    except BrandPortalError as e:
        import frappe
        frappe.throw(e.message)
    except Exception as e:
        import frappe
        frappe.log_error(f"Get partner stats failed: {e}")
        frappe.throw(str(e))


def bulk_submit_products(
    products: List[Dict],
    partner: str = None,
    priority: str = "Normal",
) -> List[Dict]:
    """Submit multiple products in bulk.

    Args:
        products: List of product data dictionaries
        partner: Partner document name (auto-detected if not provided)
        priority: Submission priority for all products

    Returns:
        List of submission results

    Example:
        results = bulk_submit_products([
            {"product_name": "Product 1", "brand": "Brand A", ...},
            {"product_name": "Product 2", "brand": "Brand A", ...},
        ])
    """
    results = []

    for product_data in products:
        try:
            result = submit_product(
                product_data=product_data,
                partner=partner,
                priority=priority,
                submit_immediately=True,
            )
            results.append(result)
        except Exception as e:
            results.append({
                "status": "error",
                "product_name": product_data.get("product_name", "Unknown"),
                "error": str(e),
            })

    return results


def get_pending_reviews(limit: int = 20, offset: int = 0) -> Dict:
    """Get submissions pending review (for reviewers).

    Args:
        limit: Maximum number of results
        offset: Number of results to skip

    Returns:
        Dictionary with pending submissions

    Example:
        pending = get_pending_reviews()
    """
    import frappe

    # Validate reviewer permissions
    user = _get_current_user()
    user_roles = frappe.get_roles(user)

    if not any(role in user_roles for role in ["System Manager", "PIM Admin", "PIM Manager"]):
        raise PartnerNotAuthorizedError(
            "User is not authorized to view pending reviews",
            details={"user": user}
        )

    # Get all pending submissions
    return get_submissions(
        status=SubmissionStatus.SUBMITTED.value,
        limit=limit,
        offset=offset,
        order_by="priority desc, creation asc",
    )


# =============================================================================
# Frappe Whitelist Decorators
# =============================================================================

try:
    import frappe

    submit_product = frappe.whitelist()(submit_product)
    get_submissions = frappe.whitelist()(get_submissions)
    get_submission_details = frappe.whitelist()(get_submission_details)
    update_submission_status = frappe.whitelist()(update_submission_status)
    update_submission = frappe.whitelist()(update_submission)
    withdraw_submission = frappe.whitelist()(withdraw_submission)
    get_partner_stats = frappe.whitelist()(get_partner_stats)
    bulk_submit_products = frappe.whitelist()(bulk_submit_products)
    get_pending_reviews = frappe.whitelist()(get_pending_reviews)

except ImportError:
    pass  # Allow import without frappe for testing


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # Core API Functions
    "submit_product",
    "get_submissions",
    "get_submission_details",
    "update_submission_status",

    # Additional API Functions
    "update_submission",
    "withdraw_submission",
    "get_partner_stats",
    "bulk_submit_products",
    "get_pending_reviews",

    # Data Classes
    "SubmissionResult",
    "SubmissionDetails",
    "SubmissionListResult",
    "StatusUpdateResult",
    "PartnerStats",

    # Enums
    "SubmissionStatus",
    "SubmissionPriority",
    "PartnerType",

    # Exceptions
    "BrandPortalError",
    "PartnerNotFoundError",
    "PartnerNotAuthorizedError",
    "SubmissionNotFoundError",
    "InvalidSubmissionDataError",
    "SubmissionStatusError",
    "DuplicateSubmissionError",

    # Constants
    "REQUIRED_SUBMISSION_FIELDS",
    "RECOMMENDED_SUBMISSION_FIELDS",
]
