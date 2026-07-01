"""PIM Portal API Endpoints

This module provides API endpoints for Brand Portal partners to:
- Browse product catalogs for their assigned brands
- Submit new products and enrichments for approval
- Check status of their submissions
- Download product data and media assets
- Manage their portal profile

All API functions are decorated with @frappe.whitelist() for security
and require appropriate portal user permissions.

Portal Roles and Permissions:
- Viewer: Read-only access to product data
- Contributor: Can submit data for approval
- Editor: Can directly edit product data
- Partner Admin: Full access + user management

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional


# Pagination defaults
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 500


# =============================================================================
# Catalog Browsing APIs
# =============================================================================

def browse_catalog(
    brand=None,
    search=None,
    product_family=None,
    status=None,
    page=1,
    page_size=DEFAULT_PAGE_SIZE,
    sort_by="modified",
    sort_order="desc",
    fields=None
):
    """Browse product catalog for partner's assigned brands.

    Partners can only browse products for brands they are assigned to.
    This is the main endpoint for catalog exploration.

    Args:
        brand: Filter by specific brand (must be in user's assigned brands)
        search: Search term for product name, code, or description
        product_family: Filter by product family/category
        status: Filter by product status (e.g., 'Active', 'Draft')
        page: Page number (1-indexed)
        page_size: Items per page (max 500)
        sort_by: Field to sort by (default: modified)
        sort_order: Sort order - 'asc' or 'desc' (default: desc)
        fields: List of fields to return (optional, defaults to standard set)

    Returns:
        dict: {
            products: list of product records,
            total: total count,
            page: current page,
            page_size: items per page,
            total_pages: total pages available
        }

    Example:
        >>> result = browse_catalog(brand="MY-BRAND", search="laptop")
        >>> print(f"Found {result['total']} products")
    """
    import frappe
    from frappe import _

    # Validate portal access
    portal_user = _get_current_portal_user()
    if not portal_user:
        frappe.throw(_("Portal access required"), frappe.PermissionError)

    if not portal_user.get("permissions", {}).get("can_view_products"):
        frappe.throw(_("You don't have permission to view products"), frappe.PermissionError)

    # Validate brand access
    accessible_brands = [b["brand"] for b in portal_user.get("brands", [])]
    if not accessible_brands:
        return {
            "products": [],
            "total": 0,
            "page": page,
            "page_size": page_size,
            "total_pages": 0
        }

    # Build filters
    filters = {}

    if brand:
        if brand not in accessible_brands:
            frappe.throw(_("You don't have access to brand: {0}").format(brand), frappe.PermissionError)
        filters["brand"] = brand
    else:
        # Filter to only accessible brands
        filters["brand"] = ["in", accessible_brands]

    if product_family:
        filters["product_family"] = product_family

    if status:
        filters["status"] = status

    # Pagination
    page = max(1, int(page))
    page_size = min(max(1, int(page_size)), MAX_PAGE_SIZE)
    offset = (page - 1) * page_size

    # Default fields for portal view
    if not fields:
        fields = [
            "name", "product_name", "product_code", "status",
            "short_description", "product_family", "brand",
            "image", "completeness_score", "modified"
        ]
    elif isinstance(fields, str):
        fields = [f.strip() for f in fields.split(",")]

    # Build or_filters for search
    or_filters = None
    if search:
        search_term = f"%{search}%"
        or_filters = [
            ["product_name", "like", search_term],
            ["product_code", "like", search_term],
            ["short_description", "like", search_term],
        ]

    # Get products
    products = frappe.get_all(
        "Product Master",
        filters=filters,
        or_filters=or_filters,
        fields=fields,
        order_by=f"{sort_by} {sort_order}",
        limit_page_length=page_size,
        limit_start=offset
    )

    # Get total count
    total = frappe.db.count("Product Master", filters=filters)
    total_pages = (total + page_size - 1) // page_size

    # Record activity
    _record_portal_activity(portal_user["name"], "browse_catalog")

    return {
        "products": products,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }


def get_product(product_name, include_attributes=True, include_media=True):
    """Get detailed product information.

    Returns complete product details for portal view, including
    attributes and media if requested.

    Args:
        product_name: Name (ID) of the Product Master
        include_attributes: Include EAV attributes (default: True)
        include_media: Include media assets (default: True)

    Returns:
        dict: Complete product data

    Example:
        >>> product = get_product("PROD-001", include_media=True)
        >>> print(product["product_name"])
    """
    import frappe
    from frappe import _

    # Validate portal access
    portal_user = _get_current_portal_user()
    if not portal_user:
        frappe.throw(_("Portal access required"), frappe.PermissionError)

    if not portal_user.get("permissions", {}).get("can_view_products"):
        frappe.throw(_("You don't have permission to view products"), frappe.PermissionError)

    # Get product
    try:
        product = frappe.get_doc("Product Master", product_name)
    except frappe.DoesNotExistError:
        frappe.throw(_("Product not found: {0}").format(product_name), frappe.DoesNotExistError)

    # Validate brand access
    accessible_brands = [b["brand"] for b in portal_user.get("brands", [])]
    if product.brand and product.brand not in accessible_brands:
        frappe.throw(_("You don't have access to this product's brand"), frappe.PermissionError)

    # Build response
    data = {
        "name": product.name,
        "product_name": product.product_name,
        "product_code": product.product_code,
        "status": product.status,
        "brand": product.brand,
        "product_family": product.product_family,
        "short_description": product.short_description,
        "long_description": product.long_description,
        "image": product.image,
        "barcode": product.get("barcode"),
        "completeness_score": product.completeness_score,
        "created": product.creation.isoformat() if product.creation else None,
        "modified": product.modified.isoformat() if product.modified else None
    }

    if include_attributes:
        data["attributes"] = _get_product_attributes_for_portal(product)

    if include_media and portal_user.get("permissions", {}).get("can_view_media"):
        data["media"] = _get_product_media_for_portal(product)

    # Record activity
    _record_portal_activity(portal_user["name"], "view_product", product_name)

    return data


def get_product_families(brand=None):
    """Get list of product families accessible to the portal user.

    Args:
        brand: Optional filter by brand

    Returns:
        list: Product families with counts
    """
    import frappe
    from frappe import _

    # Validate portal access
    portal_user = _get_current_portal_user()
    if not portal_user:
        frappe.throw(_("Portal access required"), frappe.PermissionError)

    accessible_brands = [b["brand"] for b in portal_user.get("brands", [])]
    if not accessible_brands:
        return []

    # Build brand filter
    if brand:
        if brand not in accessible_brands:
            frappe.throw(_("You don't have access to brand: {0}").format(brand), frappe.PermissionError)
        brand_filter = f"= '{frappe.db.escape(brand)}'"
    else:
        brand_list = ", ".join([f"'{frappe.db.escape(b)}'" for b in accessible_brands])
        brand_filter = f"IN ({brand_list})"

    # Get product families with counts
    families = frappe.db.sql(f"""
        SELECT product_family, COUNT(*) as product_count
        FROM `tabProduct Master`
        WHERE brand {brand_filter}
        AND product_family IS NOT NULL
        AND product_family != ''
        GROUP BY product_family
        ORDER BY product_count DESC
    """, as_dict=True)

    return families


def search_products(query, brand=None, limit=20):
    """Quick search products by name, code, or GTIN.

    Provides fast typeahead search for products in the portal.

    Args:
        query: Search query string (minimum 2 characters)
        brand: Optional filter by brand
        limit: Maximum results (default: 20, max: 100)

    Returns:
        list: Matching products with basic info
    """
    import frappe
    from frappe import _

    if not query or len(query) < 2:
        return []

    # Validate portal access
    portal_user = _get_current_portal_user()
    if not portal_user:
        frappe.throw(_("Portal access required"), frappe.PermissionError)

    if not portal_user.get("permissions", {}).get("can_view_products"):
        frappe.throw(_("You don't have permission to view products"), frappe.PermissionError)

    accessible_brands = [b["brand"] for b in portal_user.get("brands", [])]
    if not accessible_brands:
        return []

    # Validate brand access
    if brand and brand not in accessible_brands:
        frappe.throw(_("You don't have access to brand: {0}").format(brand), frappe.PermissionError)

    # Build filters
    filters = {}
    if brand:
        filters["brand"] = brand
    else:
        filters["brand"] = ["in", accessible_brands]

    limit = min(max(1, int(limit)), 100)
    search_term = f"%{query}%"

    # Search
    products = frappe.get_all(
        "Product Master",
        filters=filters,
        or_filters=[
            ["product_name", "like", search_term],
            ["product_code", "like", search_term],
            ["barcode", "like", search_term],
        ],
        fields=["name", "product_name", "product_code", "brand", "image"],
        order_by="product_name asc",
        limit_page_length=limit
    )

    return products


# =============================================================================
# Submission APIs
# =============================================================================

def create_product_submission(
    submission_type,
    title,
    brand,
    product=None,
    product_name=None,
    product_code=None,
    gtin=None,
    short_description=None,
    long_description=None,
    bullet_points=None,
    keywords=None,
    category_suggestion=None,
    attributes_json=None,
    msrp=None,
    submitter_notes=None,
    submit_immediately=False
):
    """Create a new product submission for approval.

    Partners use this endpoint to submit new products or enrichments
    for review by PIM managers.

    Args:
        submission_type: Type of submission:
            - 'New Product': Submit a new product
            - 'Product Update': Update existing product
            - 'Enrichment': Add/improve product data
            - 'Media Upload': Upload media assets
        title: Brief description of the submission
        brand: Brand code (must be in user's assigned brands)
        product: Existing product (required for updates/enrichments)
        product_name: Product name (required for new products)
        product_code: Product SKU/code
        gtin: GTIN/barcode (validated against GS1 standards)
        short_description: Short product description
        long_description: Detailed product description
        bullet_points: Feature bullet points (one per line)
        keywords: Search keywords (comma-separated)
        category_suggestion: Suggested product category
        attributes_json: Product attributes as JSON string
        msrp: Manufacturer's suggested retail price
        submitter_notes: Notes for the reviewer
        submit_immediately: Submit for review right away (default: False)

    Returns:
        dict: Created submission with name, status, and scores

    Example:
        >>> result = create_product_submission(
        ...     submission_type="New Product",
        ...     title="New Laptop SKU",
        ...     brand="MY-BRAND",
        ...     product_name="Gaming Laptop XYZ",
        ...     product_code="LAP-001",
        ...     short_description="High-performance gaming laptop",
        ...     submit_immediately=True
        ... )
        >>> print(f"Created submission: {result['name']}")
    """
    import frappe
    from frappe import _

    # Validate portal access
    portal_user = _get_current_portal_user()
    if not portal_user:
        frappe.throw(_("Portal access required"), frappe.PermissionError)

    if not portal_user.get("permissions", {}).get("can_submit_data"):
        frappe.throw(_("You don't have permission to submit data"), frappe.PermissionError)

    # Validate brand access
    accessible_brands = [b["brand"] for b in portal_user.get("brands", [])]
    if brand and brand not in accessible_brands:
        frappe.throw(_("You don't have access to brand: {0}").format(brand), frappe.PermissionError)

    # Validate submission type requirements
    if submission_type == "New Product":
        if not product_name:
            frappe.throw(_("Product name is required for new product submissions"))
    elif submission_type in ["Product Update", "Enrichment", "Media Upload"]:
        if not product:
            frappe.throw(_("Existing product is required for {0}").format(submission_type))

    # Build submission data
    doc_data = {
        "doctype": "Partner Submission",
        "submission_type": submission_type,
        "title": title,
        "brand": brand,
        "submitted_by": frappe.session.user,
        "portal_user": portal_user["name"],
        "status": "Draft"
    }

    # Add optional fields
    optional_fields = {
        "product": product,
        "product_name": product_name,
        "product_code": product_code,
        "gtin": gtin,
        "short_description": short_description,
        "long_description": long_description,
        "bullet_points": bullet_points,
        "keywords": keywords,
        "category_suggestion": category_suggestion,
        "attributes_json": attributes_json,
        "msrp": msrp,
        "submitter_notes": submitter_notes
    }

    for field, value in optional_fields.items():
        if value is not None:
            doc_data[field] = value

    # Create submission
    doc = frappe.get_doc(doc_data)
    doc.insert()

    if submit_immediately:
        doc.status = "Submitted"
        doc.submitted_at = frappe.utils.now_datetime()
        doc.save()

    # Record activity
    _record_portal_activity(portal_user["name"], "create_submission", doc.name)

    return {
        "name": doc.name,
        "status": doc.status,
        "validation_status": doc.validation_status,
        "completeness_score": doc.completeness_score,
        "data_quality_score": doc.data_quality_score
    }


def submit_for_review(submission_name):
    """Submit a draft submission for review.

    Changes status from 'Draft' to 'Submitted' and triggers
    the review workflow.

    Args:
        submission_name: Name of the Partner Submission

    Returns:
        dict: Updated submission status
    """
    import frappe
    from frappe import _

    # Validate portal access
    portal_user = _get_current_portal_user()
    if not portal_user:
        frappe.throw(_("Portal access required"), frappe.PermissionError)

    if not portal_user.get("permissions", {}).get("can_submit_data"):
        frappe.throw(_("You don't have permission to submit data"), frappe.PermissionError)

    # Get submission
    doc = frappe.get_doc("Partner Submission", submission_name)

    # Verify ownership
    if doc.submitted_by != frappe.session.user and doc.portal_user != portal_user["name"]:
        frappe.throw(_("You can only submit your own submissions"), frappe.PermissionError)

    if doc.status != "Draft":
        frappe.throw(_("Only draft submissions can be submitted for review"))

    # Submit
    doc.status = "Submitted"
    doc.submitted_at = frappe.utils.now_datetime()
    doc.save()

    # Record activity
    _record_portal_activity(portal_user["name"], "submit_for_review", doc.name)

    return {
        "name": doc.name,
        "status": doc.status,
        "submitted_at": doc.submitted_at.isoformat() if doc.submitted_at else None
    }


def get_my_submissions(
    status=None,
    submission_type=None,
    brand=None,
    page=1,
    page_size=DEFAULT_PAGE_SIZE
):
    """Get current user's submissions.

    Returns submissions created by the current portal user with
    optional filtering.

    Args:
        status: Filter by status (Draft, Submitted, Under Review, etc.)
        submission_type: Filter by submission type
        brand: Filter by brand
        page: Page number (1-indexed)
        page_size: Items per page

    Returns:
        dict: {
            submissions: list of submissions,
            total: total count,
            page: current page,
            page_size: items per page,
            status_counts: dict of counts by status
        }
    """
    import frappe
    from frappe import _

    # Validate portal access
    portal_user = _get_current_portal_user()
    if not portal_user:
        frappe.throw(_("Portal access required"), frappe.PermissionError)

    # Build filters
    filters = {"submitted_by": frappe.session.user}

    if status:
        filters["status"] = status
    if submission_type:
        filters["submission_type"] = submission_type
    if brand:
        filters["brand"] = brand

    # Pagination
    page = max(1, int(page))
    page_size = min(max(1, int(page_size)), MAX_PAGE_SIZE)
    offset = (page - 1) * page_size

    # Get submissions
    submissions = frappe.get_all(
        "Partner Submission",
        filters=filters,
        fields=[
            "name", "title", "submission_type", "status", "priority",
            "product", "product_name", "brand", "submitted_at",
            "completeness_score", "data_quality_score", "validation_status",
            "reviewed_at", "rejection_reason", "modified"
        ],
        order_by="modified desc",
        limit_page_length=page_size,
        limit_start=offset
    )

    # Get total count
    total = frappe.db.count("Partner Submission", filters)

    # Get status counts
    status_counts = {}
    all_statuses = ["Draft", "Submitted", "Under Review", "Approved",
                    "Partially Approved", "Rejected", "Applied", "Cancelled"]
    for s in all_statuses:
        count_filters = {"submitted_by": frappe.session.user, "status": s}
        if brand:
            count_filters["brand"] = brand
        status_counts[s] = frappe.db.count("Partner Submission", count_filters)

    return {
        "submissions": submissions,
        "total": total,
        "page": page,
        "page_size": page_size,
        "status_counts": status_counts
    }


def get_submission_details(submission_name):
    """Get detailed submission information.

    Returns complete submission details including field changes,
    media files, and review information.

    Args:
        submission_name: Name of the Partner Submission

    Returns:
        dict: Complete submission data
    """
    import frappe
    from frappe import _

    # Validate portal access
    portal_user = _get_current_portal_user()
    if not portal_user:
        frappe.throw(_("Portal access required"), frappe.PermissionError)

    # Get submission
    try:
        doc = frappe.get_doc("Partner Submission", submission_name)
    except frappe.DoesNotExistError:
        frappe.throw(_("Submission not found: {0}").format(submission_name))

    # Verify ownership or reviewer access
    is_owner = doc.submitted_by == frappe.session.user or doc.portal_user == portal_user["name"]
    is_reviewer = portal_user.get("permissions", {}).get("can_approve_submissions")

    if not is_owner and not is_reviewer:
        frappe.throw(_("You don't have access to this submission"), frappe.PermissionError)

    # Build response
    data = {
        "name": doc.name,
        "title": doc.title,
        "submission_type": doc.submission_type,
        "status": doc.status,
        "priority": doc.priority,
        "brand": doc.brand,
        "product": doc.product,
        "product_name": doc.product_name,
        "product_code": doc.product_code,
        "gtin": doc.gtin,
        "short_description": doc.short_description,
        "long_description": doc.long_description,
        "bullet_points": doc.bullet_points,
        "keywords": doc.keywords,
        "category_suggestion": doc.category_suggestion,
        "attributes_json": doc.attributes_json,
        "msrp": doc.msrp,
        "submitter_notes": doc.submitter_notes,
        "submitted_by": doc.submitted_by,
        "submitted_at": doc.submitted_at.isoformat() if doc.submitted_at else None,
        "validation_status": doc.validation_status,
        "validation_errors": doc.validation_errors,
        "completeness_score": doc.completeness_score,
        "data_quality_score": doc.data_quality_score,
        "assigned_reviewer": doc.assigned_reviewer,
        "reviewed_by": doc.reviewed_by,
        "reviewed_at": doc.reviewed_at.isoformat() if doc.reviewed_at else None,
        "approval_status_notes": doc.approval_status_notes,
        "rejection_reason": doc.rejection_reason,
        "approved_fields_count": doc.approved_fields_count,
        "rejected_fields_count": doc.rejected_fields_count,
        "applied_at": doc.applied_at.isoformat() if doc.applied_at else None,
        "created_product": doc.created_product,
        "modified": doc.modified.isoformat() if doc.modified else None
    }

    # Include field changes
    data["data_fields"] = []
    for field in doc.data_fields or []:
        data["data_fields"].append({
            "field_name": field.field_name,
            "field_label": field.field_label,
            "old_value": field.old_value,
            "new_value": field.new_value,
            "approval_status": field.approval_status,
            "reviewer_comment": field.reviewer_comment
        })

    # Include media files
    data["media_files"] = []
    for media in doc.media_files or []:
        data["media_files"].append({
            "file_name": media.file_name,
            "file_url": media.file_url,
            "media_type": media.media_type,
            "approval_status": media.approval_status
        })

    return data


def update_submission(
    submission_name,
    title=None,
    product_name=None,
    product_code=None,
    gtin=None,
    short_description=None,
    long_description=None,
    bullet_points=None,
    keywords=None,
    category_suggestion=None,
    attributes_json=None,
    msrp=None,
    submitter_notes=None
):
    """Update a draft submission.

    Only draft submissions can be updated. Once submitted for
    review, changes require creating a new submission.

    Args:
        submission_name: Name of the Partner Submission
        title: Updated title
        product_name: Updated product name
        product_code: Updated product code
        gtin: Updated GTIN
        short_description: Updated short description
        long_description: Updated long description
        bullet_points: Updated bullet points
        keywords: Updated keywords
        category_suggestion: Updated category suggestion
        attributes_json: Updated attributes JSON
        msrp: Updated MSRP
        submitter_notes: Updated notes

    Returns:
        dict: Updated submission status
    """
    import frappe
    from frappe import _

    # Validate portal access
    portal_user = _get_current_portal_user()
    if not portal_user:
        frappe.throw(_("Portal access required"), frappe.PermissionError)

    # Get submission
    doc = frappe.get_doc("Partner Submission", submission_name)

    # Verify ownership
    if doc.submitted_by != frappe.session.user and doc.portal_user != portal_user["name"]:
        frappe.throw(_("You can only update your own submissions"), frappe.PermissionError)

    if doc.status != "Draft":
        frappe.throw(_("Only draft submissions can be updated"))

    # Update fields
    updateable_fields = {
        "title": title,
        "product_name": product_name,
        "product_code": product_code,
        "gtin": gtin,
        "short_description": short_description,
        "long_description": long_description,
        "bullet_points": bullet_points,
        "keywords": keywords,
        "category_suggestion": category_suggestion,
        "attributes_json": attributes_json,
        "msrp": msrp,
        "submitter_notes": submitter_notes
    }

    for field, value in updateable_fields.items():
        if value is not None:
            setattr(doc, field, value)

    doc.save()

    return {
        "name": doc.name,
        "status": doc.status,
        "validation_status": doc.validation_status,
        "completeness_score": doc.completeness_score,
        "data_quality_score": doc.data_quality_score
    }


def cancel_submission(submission_name, reason=None):
    """Cancel a submission.

    Cancels a submission that hasn't been applied yet.

    Args:
        submission_name: Name of the Partner Submission
        reason: Reason for cancellation

    Returns:
        dict: Updated submission status
    """
    import frappe
    from frappe import _

    # Validate portal access
    portal_user = _get_current_portal_user()
    if not portal_user:
        frappe.throw(_("Portal access required"), frappe.PermissionError)

    # Get submission
    doc = frappe.get_doc("Partner Submission", submission_name)

    # Verify ownership
    if doc.submitted_by != frappe.session.user and doc.portal_user != portal_user["name"]:
        frappe.throw(_("You can only cancel your own submissions"), frappe.PermissionError)

    if doc.status == "Applied":
        frappe.throw(_("Applied submissions cannot be cancelled"))

    # Cancel
    doc.status = "Cancelled"
    if reason:
        doc.approval_status_notes = f"Cancelled by submitter: {reason}"
    doc.save()

    # Record activity
    _record_portal_activity(portal_user["name"], "cancel_submission", doc.name)

    return {
        "name": doc.name,
        "status": doc.status
    }


def reopen_submission(submission_name):
    """Reopen a cancelled or rejected submission.

    Reopens the submission as a draft for editing.

    Args:
        submission_name: Name of the Partner Submission

    Returns:
        dict: Updated submission status
    """
    import frappe
    from frappe import _

    # Validate portal access
    portal_user = _get_current_portal_user()
    if not portal_user:
        frappe.throw(_("Portal access required"), frappe.PermissionError)

    if not portal_user.get("permissions", {}).get("can_submit_data"):
        frappe.throw(_("You don't have permission to submit data"), frappe.PermissionError)

    # Get submission
    doc = frappe.get_doc("Partner Submission", submission_name)

    # Verify ownership
    if doc.submitted_by != frappe.session.user and doc.portal_user != portal_user["name"]:
        frappe.throw(_("You can only reopen your own submissions"), frappe.PermissionError)

    if doc.status not in ["Cancelled", "Rejected"]:
        frappe.throw(_("Only cancelled or rejected submissions can be reopened"))

    # Reopen
    doc.status = "Draft"
    doc.reviewed_by = None
    doc.reviewed_at = None
    doc.rejection_reason = None
    doc.save()

    # Record activity
    _record_portal_activity(portal_user["name"], "reopen_submission", doc.name)

    return {
        "name": doc.name,
        "status": doc.status
    }


# =============================================================================
# Status Check APIs
# =============================================================================

def get_submission_status(submission_name):
    """Get current status of a submission.

    Quick endpoint to check submission status without
    fetching full details.

    Args:
        submission_name: Name of the Partner Submission

    Returns:
        dict: Submission status information
    """
    import frappe
    from frappe import _

    # Validate portal access
    portal_user = _get_current_portal_user()
    if not portal_user:
        frappe.throw(_("Portal access required"), frappe.PermissionError)

    # Get submission status
    data = frappe.db.get_value(
        "Partner Submission",
        submission_name,
        ["name", "status", "submitted_at", "reviewed_at", "applied_at",
         "rejection_reason", "validation_status", "assigned_reviewer"],
        as_dict=True
    )

    if not data:
        frappe.throw(_("Submission not found: {0}").format(submission_name))

    # Verify access (owner or reviewer)
    submitted_by = frappe.db.get_value("Partner Submission", submission_name, "submitted_by")
    if submitted_by != frappe.session.user:
        is_reviewer = portal_user.get("permissions", {}).get("can_approve_submissions")
        if not is_reviewer:
            frappe.throw(_("You don't have access to this submission"), frappe.PermissionError)

    return data


def get_submission_stats():
    """Get submission statistics for current user.

    Returns summary of user's submission activity.

    Returns:
        dict: Submission statistics
    """
    import frappe
    from frappe import _

    # Validate portal access
    portal_user = _get_current_portal_user()
    if not portal_user:
        frappe.throw(_("Portal access required"), frappe.PermissionError)

    user = frappe.session.user

    # Get counts by status
    stats = {
        "total": frappe.db.count("Partner Submission", {"submitted_by": user}),
        "draft": frappe.db.count("Partner Submission", {"submitted_by": user, "status": "Draft"}),
        "pending_review": frappe.db.count("Partner Submission", {
            "submitted_by": user,
            "status": ["in", ["Submitted", "Under Review"]]
        }),
        "approved": frappe.db.count("Partner Submission", {
            "submitted_by": user,
            "status": ["in", ["Approved", "Partially Approved"]]
        }),
        "rejected": frappe.db.count("Partner Submission", {"submitted_by": user, "status": "Rejected"}),
        "applied": frappe.db.count("Partner Submission", {"submitted_by": user, "status": "Applied"})
    }

    # Get recent activity
    recent = frappe.get_all(
        "Partner Submission",
        filters={"submitted_by": user},
        fields=["name", "title", "status", "modified"],
        order_by="modified desc",
        limit=5
    )
    stats["recent_submissions"] = recent

    return stats


# =============================================================================
# Portal User Profile APIs
# =============================================================================

def get_portal_profile():
    """Get current user's portal profile.

    Returns the portal user's configuration, assigned brands,
    and permissions.

    Returns:
        dict: Portal user profile
    """
    import frappe
    from frappe import _

    portal_user = _get_current_portal_user()
    if not portal_user:
        frappe.throw(_("No portal profile found for current user"), frappe.DoesNotExistError)

    return portal_user


def get_accessible_brands():
    """Get list of brands accessible to current portal user.

    Returns:
        list: List of brands with access levels
    """
    import frappe
    from frappe import _

    portal_user = _get_current_portal_user()
    if not portal_user:
        frappe.throw(_("Portal access required"), frappe.PermissionError)

    return portal_user.get("brands", [])


def update_notification_preferences(
    notify_product_updates=None,
    notify_new_products=None,
    notify_submission_status=None,
    notification_email=None,
    digest_frequency=None
):
    """Update portal user's notification preferences.

    Args:
        notify_product_updates: Receive product update notifications
        notify_new_products: Receive new product notifications
        notify_submission_status: Receive submission status notifications
        notification_email: Alternative notification email
        digest_frequency: Digest frequency (Immediate, Daily, Weekly, None)

    Returns:
        dict: Updated preferences
    """
    import frappe
    from frappe import _

    portal_user = _get_current_portal_user()
    if not portal_user:
        frappe.throw(_("Portal access required"), frappe.PermissionError)

    # Get portal user document
    doc = frappe.get_doc("Brand Portal User", portal_user["name"])

    # Update preferences
    if notify_product_updates is not None:
        doc.notify_product_updates = 1 if notify_product_updates else 0
    if notify_new_products is not None:
        doc.notify_new_products = 1 if notify_new_products else 0
    if notify_submission_status is not None:
        doc.notify_submission_status = 1 if notify_submission_status else 0
    if notification_email is not None:
        doc.notification_email = notification_email
    if digest_frequency is not None:
        doc.digest_frequency = digest_frequency

    doc.save(ignore_permissions=True)

    return {
        "notify_product_updates": doc.notify_product_updates,
        "notify_new_products": doc.notify_new_products,
        "notify_submission_status": doc.notify_submission_status,
        "notification_email": doc.notification_email,
        "digest_frequency": doc.digest_frequency
    }


def record_portal_login():
    """Record a portal login event.

    Call this when a user logs into the portal to track activity.

    Returns:
        dict: Login recorded status
    """
    import frappe
    from frappe import _

    portal_user = _get_current_portal_user()
    if not portal_user:
        return {"success": False, "reason": "No portal user found"}

    # Record login
    frappe.db.set_value(
        "Brand Portal User",
        portal_user["name"],
        {
            "last_login": frappe.utils.now_datetime(),
            "login_count": (portal_user.get("login_count") or 0) + 1
        },
        update_modified=False
    )
    frappe.db.commit()

    return {"success": True}


# =============================================================================
# Asset Download APIs
# =============================================================================

def download_product_data(products=None, brand=None, format="json"):
    """Download product data as file.

    Partners with download permission can export product data
    for their assigned brands.

    Args:
        products: List of product names (optional, defaults to all accessible)
        brand: Filter by brand
        format: Export format - json, csv (default: json)

    Returns:
        dict: Download URL and file info
    """
    import frappe
    from frappe import _

    # Validate portal access
    portal_user = _get_current_portal_user()
    if not portal_user:
        frappe.throw(_("Portal access required"), frappe.PermissionError)

    if not portal_user.get("permissions", {}).get("can_download_assets"):
        frappe.throw(_("You don't have permission to download assets"), frappe.PermissionError)

    accessible_brands = [b["brand"] for b in portal_user.get("brands", [])]
    if not accessible_brands:
        frappe.throw(_("No brands accessible"), frappe.PermissionError)

    # Validate brand
    if brand and brand not in accessible_brands:
        frappe.throw(_("You don't have access to brand: {0}").format(brand), frappe.PermissionError)

    # Build filters
    filters = {}
    if brand:
        filters["brand"] = brand
    else:
        filters["brand"] = ["in", accessible_brands]

    if products:
        if isinstance(products, str):
            products = json.loads(products)
        filters["name"] = ["in", products]

    # Get products
    product_list = frappe.get_all(
        "Product Master",
        filters=filters,
        fields=[
            "name", "product_name", "product_code", "status",
            "brand", "product_family", "short_description",
            "long_description", "barcode", "image"
        ]
    )

    # Generate export content
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if format.lower() == "csv":
        import csv
        from io import StringIO

        output = StringIO()
        if product_list:
            writer = csv.DictWriter(output, fieldnames=product_list[0].keys())
            writer.writeheader()
            writer.writerows(product_list)

        content = output.getvalue()
        filename = f"products_export_{timestamp}.csv"
        content_type = "text/csv"
    else:
        content = json.dumps({
            "metadata": {
                "exported_at": datetime.now().isoformat(),
                "exported_by": frappe.session.user,
                "product_count": len(product_list)
            },
            "products": product_list
        }, indent=2, ensure_ascii=False)
        filename = f"products_export_{timestamp}.json"
        content_type = "application/json"

    # Save file
    file_doc = frappe.get_doc({
        "doctype": "File",
        "file_name": filename,
        "content": content,
        "is_private": 1,
        "folder": "Home"
    })
    file_doc.insert(ignore_permissions=True)
    frappe.db.commit()

    # Record activity
    _record_portal_activity(portal_user["name"], "download_data", filename)

    return {
        "success": True,
        "download_url": file_doc.file_url,
        "filename": filename,
        "product_count": len(product_list)
    }


# =============================================================================
# Helper Functions
# =============================================================================

def _get_current_portal_user():
    """Get current user's portal user record.

    Returns:
        dict: Portal user data or None
    """
    import frappe

    user = frappe.session.user
    if user == "Guest":
        return None

    # Get portal user
    portal_user_name = frappe.db.get_value(
        "Brand Portal User",
        {"user": user, "status": "Active"},
        "name"
    )

    if not portal_user_name:
        return None

    # Load full document
    doc = frappe.get_doc("Brand Portal User", portal_user_name)

    # Check if active
    if not doc.is_active():
        return None

    return {
        "name": doc.name,
        "user": doc.user,
        "user_full_name": doc.user_full_name,
        "status": doc.status,
        "portal_role": doc.portal_role,
        "is_active": doc.is_active(),
        "brands": doc.get_accessible_brands(),
        "permissions": {
            "can_view_products": doc.can_view_products,
            "can_view_media": doc.can_view_media,
            "can_download_assets": doc.can_download_assets,
            "can_submit_data": doc.can_submit_data,
            "can_edit_products": doc.can_edit_products,
            "can_upload_media": doc.can_upload_media,
            "can_export_feeds": doc.can_export_feeds,
            "can_view_analytics": doc.can_view_analytics,
            "can_manage_users": doc.can_manage_users,
            "can_approve_submissions": doc.can_approve_submissions,
            "can_publish_to_channels": doc.can_publish_to_channels,
            "api_access_enabled": doc.api_access_enabled,
        },
        "login_count": doc.login_count
    }


def _get_product_attributes_for_portal(product):
    """Get product attributes formatted for portal view.

    Args:
        product: Product Master document

    Returns:
        dict: Attribute name -> value mapping
    """
    attributes = {}

    for attr_value in (product.get("attribute_values") or []):
        attr_code = attr_value.get("attribute")
        if not attr_code:
            continue

        # Get the value from appropriate column
        value = (
            attr_value.get("value_text") or
            attr_value.get("value_int") or
            attr_value.get("value_float") or
            attr_value.get("value_date") or
            attr_value.get("value_link")
        )

        if attr_value.get("value_boolean") is not None:
            value = attr_value.get("value_boolean")

        attributes[attr_code] = value

    return attributes


def _get_product_media_for_portal(product):
    """Get product media formatted for portal view.

    Args:
        product: Product Master document

    Returns:
        list: Media items
    """
    media_list = []

    # Primary image
    if product.get("image"):
        media_list.append({
            "type": "image",
            "url": product.image,
            "is_primary": True
        })

    # Additional media from child table
    for media in (product.get("media") or []):
        media_list.append({
            "type": media.get("media_type", "image"),
            "url": media.get("file_url"),
            "is_primary": False
        })

    return media_list


def _record_portal_activity(portal_user_name, activity_type, reference=None):
    """Record portal user activity.

    Args:
        portal_user_name: Name of Brand Portal User
        activity_type: Type of activity performed
        reference: Optional reference document
    """
    import frappe

    try:
        # Update last activity timestamp
        frappe.db.set_value(
            "Brand Portal User",
            portal_user_name,
            "last_activity",
            frappe.utils.now_datetime(),
            update_modified=False
        )

        # Optionally log to activity log
        frappe.logger().debug(
            f"Portal activity: {activity_type} by {portal_user_name}, ref: {reference}"
        )
    except Exception:
        pass  # Non-critical, don't fail main operation


# =============================================================================
# Whitelist Registration
# =============================================================================

def _wrap_for_whitelist():
    """Apply frappe.whitelist() decorators at runtime."""
    import frappe

    # List of functions to whitelist
    api_functions = [
        # Catalog browsing
        "browse_catalog",
        "get_product",
        "get_product_families",
        "search_products",
        # Submissions
        "create_product_submission",
        "submit_for_review",
        "get_my_submissions",
        "get_submission_details",
        "update_submission",
        "cancel_submission",
        "reopen_submission",
        # Status checks
        "get_submission_status",
        "get_submission_stats",
        # Portal profile
        "get_portal_profile",
        "get_accessible_brands",
        "update_notification_preferences",
        "record_portal_login",
        # Downloads
        "download_product_data",
    ]

    for func_name in api_functions:
        func = globals().get(func_name)
        if func and callable(func):
            globals()[func_name] = frappe.whitelist()(func)


# Apply whitelist decorators when module is imported
try:
    _wrap_for_whitelist()
except ImportError:
    pass  # frappe not available (e.g., during testing/verification)
