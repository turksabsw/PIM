"""
AI Enrichment REST API
Provides REST API endpoints for AI-powered product enrichment operations
"""

import frappe
from frappe import _
from typing import Optional, List, Dict, Any
from frappe.utils import now_datetime, cint, flt
import json


# ============================================================================
# Direct Enrichment APIs
# ============================================================================

@frappe.whitelist()
def enrich_product(
    sku: Optional[str] = None,
    product_name: Optional[str] = None,
    job_type: str = "Description Generation",
    ai_provider: str = "Anthropic",
    prompt_template: Optional[str] = None,
    custom_prompt: Optional[str] = None,
    channel: Optional[str] = None,
    locale: Optional[str] = None,
    auto_apply: bool = False,
    async_mode: bool = False
) -> Dict[str, Any]:
    """Enrich a single product with AI-generated content

    Performs real-time AI enrichment for a single product. Can run synchronously
    (returns result immediately) or asynchronously (queues a job).

    Args:
        sku: Product SKU
        product_name: Product Master document name
        job_type: Type of enrichment to perform:
            - Description Generation: Generate product descriptions
            - Attribute Extraction: Extract attributes from text
            - Classification Suggestion: Suggest taxonomy classifications
            - SEO Optimization: Generate SEO-friendly content
            - Content Enhancement: Improve existing content
            - Quality Check: Check content quality
        ai_provider: AI provider to use (Anthropic, OpenAI, Google Gemini, etc.)
        prompt_template: Name of AI Prompt Template to use
        custom_prompt: Custom prompt text (overrides template)
        channel: Target channel for context
        locale: Target locale for context
        auto_apply: If True, automatically apply results to product
        async_mode: If True, queue for background processing

    Returns:
        Dictionary containing:
            - success: Whether enrichment succeeded
            - content: Generated content (if sync mode)
            - job: Job name (if async mode)
            - product: Product name
            - confidence: AI confidence score (0-1)
            - tokens_used: Number of tokens consumed
            - estimated_cost: Estimated cost in USD

    Raises:
        frappe.DoesNotExistError: If product not found
        frappe.PermissionError: If user lacks permission
    """
    auto_apply = _to_bool(auto_apply)
    async_mode = _to_bool(async_mode)

    # Find product
    pname = product_name
    if not pname and sku:
        pname = frappe.db.get_value("Product Master", {"sku": sku}, "name")

    if not pname:
        frappe.throw(
            _("Product not found"),
            exc=frappe.DoesNotExistError
        )

    # Check permissions
    if not frappe.has_permission("Product Master", "read", pname):
        frappe.throw(_("Permission denied"), exc=frappe.PermissionError)

    if auto_apply and not frappe.has_permission("Product Master", "write", pname):
        frappe.throw(
            _("You do not have permission to modify this product"),
            exc=frappe.PermissionError
        )

    # If async mode, create a job
    if async_mode:
        job = _create_enrichment_job_for_product(
            product=pname,
            job_type=job_type,
            ai_provider=ai_provider,
            prompt_template=prompt_template,
            custom_prompt=custom_prompt,
            channel=channel,
            locale=locale,
            auto_apply=auto_apply
        )
        return {
            "success": True,
            "async": True,
            "job": job["name"],
            "product": pname,
            "message": _("Enrichment job queued for background processing")
        }

    # Synchronous enrichment
    return _perform_enrichment(
        product=pname,
        job_type=job_type,
        ai_provider=ai_provider,
        prompt_template=prompt_template,
        custom_prompt=custom_prompt,
        channel=channel,
        locale=locale,
        auto_apply=auto_apply
    )


@frappe.whitelist()
def enrich_products(
    products: Optional[str] = None,
    skus: Optional[str] = None,
    job_type: str = "Description Generation",
    ai_provider: str = "Anthropic",
    prompt_template: Optional[str] = None,
    selection_method: str = "Manual Selection",
    filter_product_family: Optional[str] = None,
    filter_channel: Optional[str] = None,
    require_approval: bool = True,
    priority: str = "Normal"
) -> Dict[str, Any]:
    """Create an AI enrichment job for multiple products

    Creates a batch enrichment job that processes multiple products in the background.
    Results can be configured to require approval before being applied.

    Args:
        products: JSON array of product names
        skus: JSON array of product SKUs (alternative to products)
        job_type: Type of enrichment to perform
        ai_provider: AI provider to use
        prompt_template: Name of AI Prompt Template to use
        selection_method: How to select products:
            - Manual Selection: Use provided product list
            - Product Family: All products in a family
            - Channel: All products assigned to channel
            - All Products: All products in the system
        filter_product_family: Product family for family-based selection
        filter_channel: Channel for channel-based selection
        require_approval: If True, results need approval before applying
        priority: Job priority (Low, Normal, High, Critical)

    Returns:
        Dictionary with job details and status
    """
    require_approval = _to_bool(require_approval)

    # Parse product lists
    product_list = _parse_list_param(products)
    sku_list = _parse_list_param(skus)

    # Resolve SKUs to product names
    if sku_list:
        resolved = frappe.get_all(
            "Product Master",
            filters={"sku": ["in", sku_list]},
            pluck="name"
        )
        product_list.extend(resolved)

    # Create job document
    job = frappe.new_doc("AI Enrichment Job")
    job.job_name = f"Batch {job_type} - {now_datetime().strftime('%Y-%m-%d %H:%M')}"
    job.job_type = job_type
    job.ai_provider = ai_provider
    job.prompt_template = prompt_template
    job.selection_method = selection_method
    job.require_approval = require_approval
    job.priority = priority

    if selection_method == "Manual Selection" and product_list:
        for p in product_list:
            if frappe.has_permission("Product Master", "read", p):
                job.append("products", {"product": p})
    elif selection_method == "Product Family" and filter_product_family:
        job.filter_product_family = filter_product_family
    elif selection_method == "Channel" and filter_channel:
        job.filter_channel = filter_channel

    job.insert()

    return {
        "job": job.name,
        "job_name": job.job_name,
        "status": job.status,
        "selection_method": selection_method,
        "total_products": job.get_product_count(),
        "message": _("Enrichment job created. Submit the job to start processing.")
    }


@frappe.whitelist()
def generate_description(
    sku: Optional[str] = None,
    product_name: Optional[str] = None,
    description_type: str = "short",
    ai_provider: str = "Anthropic",
    channel: Optional[str] = None,
    locale: Optional[str] = None,
    max_length: Optional[int] = None,
    style: str = "professional"
) -> Dict[str, Any]:
    """Generate product description using AI

    Convenience method for generating product descriptions without creating a full job.

    Args:
        sku: Product SKU
        product_name: Product Master document name
        description_type: Type of description (short, long, marketing, technical)
        ai_provider: AI provider to use
        channel: Target channel for context
        locale: Target locale for language/style
        max_length: Maximum character length for description
        style: Writing style (professional, casual, technical, marketing)

    Returns:
        Dictionary with generated description and metadata
    """
    # Find product
    pname = product_name
    if not pname and sku:
        pname = frappe.db.get_value("Product Master", {"sku": sku}, "name")

    if not pname:
        frappe.throw(
            _("Product not found"),
            exc=frappe.DoesNotExistError
        )

    # Check permissions
    if not frappe.has_permission("Product Master", "read", pname):
        frappe.throw(_("Permission denied"), exc=frappe.PermissionError)

    # Get product data
    product = frappe.get_doc("Product Master", pname)
    product_data = {
        "name": product.name,
        "sku": product.sku,
        "product_name": product.product_name,
        "short_description": product.short_description,
        "long_description": product.long_description,
        "product_type": product.product_type,
        "product_family": product.product_family,
        "brand": product.brand,
        "manufacturer": product.manufacturer
    }

    # Get attributes
    attributes_data = _get_product_attributes_for_ai(pname, locale, channel)

    # Build custom prompt based on description type
    style_instructions = {
        "professional": "Use professional, business-appropriate language.",
        "casual": "Use friendly, conversational language.",
        "technical": "Use precise technical terminology and specifications.",
        "marketing": "Use persuasive, engaging marketing language."
    }

    length_instruction = ""
    if max_length:
        length_instruction = f"Keep the description under {max_length} characters."

    if description_type == "short":
        custom_prompt = f"""Generate a concise short product description for:
Product: {product.product_name}
SKU: {product.sku}
Brand: {product.brand or 'N/A'}
Category: {product.product_family or 'N/A'}

Key attributes:
{json.dumps(attributes_data, indent=2) if attributes_data else 'No attributes available'}

{style_instructions.get(style, style_instructions['professional'])}
{length_instruction}

Provide only the description text without any preamble."""

    else:  # long, marketing, technical
        custom_prompt = f"""Generate a detailed {description_type} product description for:
Product: {product.product_name}
SKU: {product.sku}
Brand: {product.brand or 'N/A'}
Category: {product.product_family or 'N/A'}

Current short description: {product.short_description or 'None'}

Key attributes:
{json.dumps(attributes_data, indent=2) if attributes_data else 'No attributes available'}

{style_instructions.get(style, style_instructions['professional'])}
{length_instruction}
Include key features, benefits, and use cases.
Provide only the description text without any preamble."""

    # Perform enrichment
    return _perform_enrichment(
        product=pname,
        job_type="Description Generation",
        ai_provider=ai_provider,
        custom_prompt=custom_prompt,
        channel=channel,
        locale=locale,
        auto_apply=False
    )


@frappe.whitelist()
def extract_attributes(
    sku: Optional[str] = None,
    product_name: Optional[str] = None,
    text: Optional[str] = None,
    ai_provider: str = "Anthropic",
    target_attributes: Optional[str] = None
) -> Dict[str, Any]:
    """Extract product attributes from text using AI

    Analyzes text (or product descriptions) to extract structured attributes.

    Args:
        sku: Product SKU
        product_name: Product Master document name
        text: Custom text to analyze (overrides product descriptions)
        ai_provider: AI provider to use
        target_attributes: JSON array of attribute names to extract

    Returns:
        Dictionary with extracted attributes and confidence scores
    """
    # Find product
    pname = product_name
    if not pname and sku:
        pname = frappe.db.get_value("Product Master", {"sku": sku}, "name")

    if not pname:
        frappe.throw(
            _("Product not found"),
            exc=frappe.DoesNotExistError
        )

    # Check permissions
    if not frappe.has_permission("Product Master", "read", pname):
        frappe.throw(_("Permission denied"), exc=frappe.PermissionError)

    # Get text to analyze
    analyze_text = text
    if not analyze_text:
        product = frappe.get_doc("Product Master", pname)
        analyze_text = f"{product.product_name or ''} {product.short_description or ''} {product.long_description or ''}"

    if not analyze_text or len(analyze_text.strip()) < 10:
        return {
            "success": False,
            "error": _("Insufficient text to analyze"),
            "product": pname
        }

    # Parse target attributes
    target_attr_list = _parse_list_param(target_attributes)

    # Get available attributes from product family
    available_attributes = []
    family = frappe.db.get_value("Product Master", pname, "product_family")
    if family:
        try:
            attrs = frappe.get_all(
                "Family Attribute Item",
                filters={"parent": family},
                fields=["attribute", "is_required"],
                order_by="sort_order"
            )
            for attr in attrs:
                attr_info = frappe.db.get_value(
                    "Attribute",
                    attr["attribute"],
                    ["attribute_name", "attribute_type", "unit_of_measure"],
                    as_dict=True
                )
                if attr_info:
                    available_attributes.append({
                        "code": attr["attribute"],
                        "name": attr_info["attribute_name"],
                        "type": attr_info["attribute_type"],
                        "unit": attr_info.get("unit_of_measure"),
                        "required": attr["is_required"]
                    })
        except Exception:
            pass

    # Filter to target attributes if specified
    if target_attr_list:
        available_attributes = [
            a for a in available_attributes
            if a["code"] in target_attr_list or a["name"] in target_attr_list
        ]

    # Build extraction prompt
    attr_list_text = "\n".join([
        f"- {a['name']} ({a['type']}){' [' + a['unit'] + ']' if a.get('unit') else ''}"
        for a in available_attributes
    ]) if available_attributes else "Extract any product attributes you can identify."

    custom_prompt = f"""Extract product attributes from the following text.

Text to analyze:
{analyze_text}

Attributes to extract:
{attr_list_text}

Return a JSON object with the following structure:
{{
    "attributes": [
        {{
            "attribute": "attribute_code_or_name",
            "value": "extracted_value",
            "confidence": 0.0-1.0
        }}
    ],
    "unmatched_values": ["any values that don't match known attributes"]
}}

Only include attributes you can confidently extract from the text."""

    # Perform enrichment
    result = _perform_enrichment(
        product=pname,
        job_type="Attribute Extraction",
        ai_provider=ai_provider,
        custom_prompt=custom_prompt,
        auto_apply=False
    )

    # Parse JSON from response
    if result.get("success") and result.get("content"):
        try:
            parsed = json.loads(result["content"])
            result["extracted_attributes"] = parsed.get("attributes", [])
            result["unmatched_values"] = parsed.get("unmatched_values", [])
        except json.JSONDecodeError:
            result["extracted_attributes"] = []
            result["parse_error"] = _("Failed to parse AI response as JSON")

    return result


@frappe.whitelist()
def suggest_classifications(
    sku: Optional[str] = None,
    product_name: Optional[str] = None,
    taxonomy: Optional[str] = None,
    ai_provider: str = "Anthropic",
    limit: int = 5
) -> Dict[str, Any]:
    """Get AI-powered taxonomy classification suggestions

    Uses AI to suggest appropriate taxonomy classifications for a product.

    Args:
        sku: Product SKU
        product_name: Product Master document name
        taxonomy: Limit suggestions to specific taxonomy
        ai_provider: AI provider to use
        limit: Maximum number of suggestions

    Returns:
        Dictionary with classification suggestions and confidence scores
    """
    limit = min(int(limit), 20)

    # Find product
    pname = product_name
    if not pname and sku:
        pname = frappe.db.get_value("Product Master", {"sku": sku}, "name")

    if not pname:
        frappe.throw(
            _("Product not found"),
            exc=frappe.DoesNotExistError
        )

    # Check permissions
    if not frappe.has_permission("Product Master", "read", pname):
        frappe.throw(_("Permission denied"), exc=frappe.PermissionError)

    # Get product data
    product = frappe.get_doc("Product Master", pname)

    # Get available taxonomy nodes
    node_filters = {"enabled": 1, "is_leaf": 1}
    if taxonomy:
        node_filters["taxonomy"] = taxonomy

    available_nodes = frappe.get_all(
        "Taxonomy Node",
        filters=node_filters,
        fields=["name", "node_name", "node_code", "full_path", "taxonomy"],
        limit_page_length=500
    )

    if not available_nodes:
        return {
            "success": False,
            "error": _("No taxonomy nodes available for classification"),
            "product": pname
        }

    # Build prompt
    product_text = f"{product.product_name or ''} {product.short_description or ''}"

    node_list = "\n".join([
        f"- [{n['node_code']}] {n['node_name']} | {n['full_path']}"
        for n in available_nodes[:100]  # Limit to prevent token overflow
    ])

    custom_prompt = f"""Classify the following product into appropriate taxonomy categories.

Product Information:
- Name: {product.product_name}
- Brand: {product.brand or 'N/A'}
- Description: {product.short_description or 'N/A'}
- Family: {product.product_family or 'N/A'}

Available Categories (format: [code] name | full path):
{node_list}

Return a JSON array with up to {limit} most appropriate classifications:
[
    {{
        "node_code": "category_code",
        "node_name": "category_name",
        "confidence": 0.0-1.0,
        "reasoning": "brief explanation"
    }}
]

Only suggest categories you are confident about. Order by confidence (highest first)."""

    # Perform enrichment
    result = _perform_enrichment(
        product=pname,
        job_type="Classification Suggestion",
        ai_provider=ai_provider,
        custom_prompt=custom_prompt,
        auto_apply=False
    )

    # Parse and enrich suggestions
    if result.get("success") and result.get("content"):
        try:
            suggestions = json.loads(result["content"])
            # Enrich with full node details
            enriched = []
            for sug in suggestions[:limit]:
                node_code = sug.get("node_code")
                node_info = frappe.db.get_value(
                    "Taxonomy Node",
                    {"node_code": node_code, "is_leaf": 1},
                    ["name", "node_name", "taxonomy", "full_path"],
                    as_dict=True
                )
                if node_info:
                    enriched.append({
                        "node": node_info["name"],
                        "node_code": node_code,
                        "node_name": node_info["node_name"],
                        "taxonomy": node_info["taxonomy"],
                        "full_path": node_info["full_path"],
                        "confidence": sug.get("confidence", 0.5),
                        "reasoning": sug.get("reasoning", "")
                    })
            result["suggestions"] = enriched
        except json.JSONDecodeError:
            result["suggestions"] = []
            result["parse_error"] = _("Failed to parse AI response as JSON")

    return result


# ============================================================================
# Job Management APIs
# ============================================================================

@frappe.whitelist()
def get_enrichment_job(
    job: str,
    include_products: bool = False,
    include_errors: bool = False
) -> Dict[str, Any]:
    """Get details of an AI enrichment job

    Args:
        job: Job document name
        include_products: Include product processing status
        include_errors: Include error log details

    Returns:
        Dictionary with job details
    """
    include_products = _to_bool(include_products)
    include_errors = _to_bool(include_errors)

    # Check permissions
    if not frappe.has_permission("AI Enrichment Job", "read", job):
        frappe.throw(_("Permission denied"), exc=frappe.PermissionError)

    doc = frappe.get_doc("AI Enrichment Job", job)

    result = {
        "name": doc.name,
        "job_name": doc.job_name,
        "job_type": doc.job_type,
        "status": doc.status,
        "ai_provider": doc.ai_provider,
        "ai_model": doc.ai_model,
        "selection_method": doc.selection_method,
        "total_products": doc.total_products,
        "processed_count": doc.processed_count,
        "successful_count": doc.successful_count,
        "failed_count": doc.failed_count,
        "skipped_count": doc.skipped_count,
        "pending_approval_count": doc.pending_approval_count,
        "progress_percent": doc.progress_percent,
        "priority": doc.priority,
        "require_approval": doc.require_approval,
        "started_at": str(doc.started_at) if doc.started_at else None,
        "completed_at": str(doc.completed_at) if doc.completed_at else None,
        "duration_seconds": doc.duration_seconds,
        "total_tokens_used": doc.total_tokens_used,
        "estimated_cost": doc.estimated_cost,
        "created_by": doc.created_by,
        "creation": str(doc.creation)
    }

    if include_products and doc.products:
        result["products"] = [
            {
                "product": p.product,
                "status": p.status,
                "error": p.error,
                "processed_at": str(p.processed_at) if p.processed_at else None
            }
            for p in doc.products
        ]

    if include_errors and doc.error_log:
        try:
            result["errors"] = json.loads(doc.error_log)
        except (json.JSONDecodeError, TypeError):
            result["errors"] = []

    return result


@frappe.whitelist()
def get_enrichment_jobs(
    status: Optional[str] = None,
    job_type: Optional[str] = None,
    ai_provider: Optional[str] = None,
    created_by: Optional[str] = None,
    limit: int = 20,
    offset: int = 0
) -> Dict[str, Any]:
    """Get list of AI enrichment jobs

    Args:
        status: Filter by status (Draft, Queued, Processing, Completed, Failed, Cancelled)
        job_type: Filter by job type
        ai_provider: Filter by AI provider
        created_by: Filter by creator
        limit: Maximum results (default 20, max 100)
        offset: Skip first N results

    Returns:
        Dictionary with 'data' list and 'total' count
    """
    limit = min(int(limit), 100)
    offset = int(offset)

    filters = {"docstatus": ["!=", 2]}

    if status:
        filters["status"] = status
    if job_type:
        filters["job_type"] = job_type
    if ai_provider:
        filters["ai_provider"] = ai_provider
    if created_by:
        filters["created_by"] = created_by

    jobs = frappe.get_all(
        "AI Enrichment Job",
        filters=filters,
        fields=[
            "name", "job_name", "job_type", "status", "priority",
            "ai_provider", "total_products", "processed_count",
            "successful_count", "failed_count", "progress_percent",
            "created_by", "creation", "started_at", "completed_at"
        ],
        order_by="creation desc",
        limit_start=offset,
        limit_page_length=limit
    )

    total = frappe.db.count("AI Enrichment Job", filters=filters)

    return {
        "data": jobs,
        "total": total,
        "limit": limit,
        "offset": offset
    }


@frappe.whitelist()
def submit_enrichment_job(job: str) -> Dict[str, Any]:
    """Submit an enrichment job for processing

    Args:
        job: Job document name

    Returns:
        Dictionary with submission status
    """
    # Check permissions
    if not frappe.has_permission("AI Enrichment Job", "submit", job):
        frappe.throw(_("Permission denied"), exc=frappe.PermissionError)

    doc = frappe.get_doc("AI Enrichment Job", job)

    if doc.docstatus != 0:
        frappe.throw(_("Job has already been submitted"))

    doc.submit()

    return {
        "job": job,
        "status": doc.status,
        "total_products": doc.total_products,
        "queue_position": doc.queue_position,
        "message": _("Job submitted for processing")
    }


@frappe.whitelist()
def cancel_enrichment_job(job: str) -> Dict[str, Any]:
    """Cancel an enrichment job

    Args:
        job: Job document name

    Returns:
        Dictionary with cancellation status
    """
    # Check permissions
    if not frappe.has_permission("AI Enrichment Job", "cancel", job):
        frappe.throw(_("Permission denied"), exc=frappe.PermissionError)

    doc = frappe.get_doc("AI Enrichment Job", job)

    if doc.status == "Processing":
        doc.cancel_processing()
    elif doc.docstatus == 1:
        doc.cancel()
    else:
        frappe.throw(_("Job cannot be cancelled in current state"))

    return {
        "job": job,
        "status": "Cancelled",
        "message": _("Job has been cancelled")
    }


@frappe.whitelist()
def retry_enrichment_job(job: str) -> Dict[str, Any]:
    """Retry failed products in an enrichment job

    Creates a new job with only the failed products from the original job.

    Args:
        job: Original job document name

    Returns:
        Dictionary with new job details
    """
    # Check permissions
    if not frappe.has_permission("AI Enrichment Job", "create"):
        frappe.throw(_("Permission denied"), exc=frappe.PermissionError)

    doc = frappe.get_doc("AI Enrichment Job", job)
    result = doc.retry_failed()

    return {
        "original_job": job,
        "new_job": result["job"],
        "failed_products": result["products"],
        "message": _("Retry job created with {0} failed products").format(result["products"])
    }


# ============================================================================
# Approval Queue APIs
# ============================================================================

@frappe.whitelist()
def get_pending_approvals(
    job: Optional[str] = None,
    job_type: Optional[str] = None,
    product: Optional[str] = None,
    limit: int = 20,
    offset: int = 0
) -> Dict[str, Any]:
    """Get pending AI enrichment approvals

    Args:
        job: Filter by specific job
        job_type: Filter by job type
        product: Filter by specific product
        limit: Maximum results
        offset: Skip first N results

    Returns:
        Dictionary with pending approval items
    """
    limit = min(int(limit), 100)
    offset = int(offset)

    filters = {"status": "Pending"}

    if job:
        filters["enrichment_job"] = job
    if job_type:
        filters["job_type"] = job_type
    if product:
        filters["product"] = product

    try:
        approvals = frappe.get_all(
            "AI Approval Queue",
            filters=filters,
            fields=[
                "name", "product", "enrichment_job", "job_type",
                "field_name", "original_value", "suggested_value",
                "confidence_score", "creation"
            ],
            order_by="creation desc",
            limit_start=offset,
            limit_page_length=limit
        )

        total = frappe.db.count("AI Approval Queue", filters=filters)

        # Enrich with product details
        for approval in approvals:
            if approval.get("product"):
                product_info = frappe.db.get_value(
                    "Product Master",
                    approval["product"],
                    ["sku", "product_name"],
                    as_dict=True
                )
                if product_info:
                    approval["sku"] = product_info["sku"]
                    approval["product_name"] = product_info["product_name"]

        return {
            "data": approvals,
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except Exception:
        # AI Approval Queue may not exist yet
        return {
            "data": [],
            "total": 0,
            "limit": limit,
            "offset": offset
        }


@frappe.whitelist()
def approve_suggestion(
    approval: str,
    notes: Optional[str] = None
) -> Dict[str, Any]:
    """Approve an AI suggestion and apply it to the product

    Args:
        approval: AI Approval Queue document name
        notes: Optional approval notes

    Returns:
        Dictionary with approval status
    """
    try:
        doc = frappe.get_doc("AI Approval Queue", approval)

        if doc.status != "Pending":
            frappe.throw(_("This suggestion has already been processed"))

        # Check permission on product
        if not frappe.has_permission("Product Master", "write", doc.product):
            frappe.throw(_("Permission denied"), exc=frappe.PermissionError)

        # Apply the suggestion
        _apply_ai_suggestion(doc)

        # Update approval status
        doc.status = "Approved"
        doc.approved_by = frappe.session.user
        doc.approved_at = now_datetime()
        doc.approval_notes = notes
        doc.save()

        return {
            "success": True,
            "approval": approval,
            "product": doc.product,
            "field": doc.field_name,
            "message": _("Suggestion approved and applied to product")
        }
    except frappe.DoesNotExistError:
        return {
            "success": False,
            "error": _("Approval record not found")
        }


@frappe.whitelist()
def reject_suggestion(
    approval: str,
    reason: Optional[str] = None
) -> Dict[str, Any]:
    """Reject an AI suggestion

    Args:
        approval: AI Approval Queue document name
        reason: Optional rejection reason

    Returns:
        Dictionary with rejection status
    """
    try:
        doc = frappe.get_doc("AI Approval Queue", approval)

        if doc.status != "Pending":
            frappe.throw(_("This suggestion has already been processed"))

        # Update status
        doc.status = "Rejected"
        doc.rejected_by = frappe.session.user
        doc.rejected_at = now_datetime()
        doc.rejection_reason = reason
        doc.save()

        return {
            "success": True,
            "approval": approval,
            "product": doc.product,
            "field": doc.field_name,
            "message": _("Suggestion rejected")
        }
    except frappe.DoesNotExistError:
        return {
            "success": False,
            "error": _("Approval record not found")
        }


@frappe.whitelist()
def bulk_approve_suggestions(
    approvals: str,
    notes: Optional[str] = None
) -> Dict[str, Any]:
    """Approve multiple AI suggestions at once

    Args:
        approvals: JSON array of approval document names
        notes: Optional approval notes for all

    Returns:
        Dictionary with bulk approval results
    """
    approval_list = _parse_list_param(approvals)

    if not approval_list:
        frappe.throw(_("No approvals specified"))

    results = {
        "approved": 0,
        "failed": 0,
        "errors": []
    }

    for approval_name in approval_list:
        try:
            result = approve_suggestion(approval_name, notes)
            if result.get("success"):
                results["approved"] += 1
            else:
                results["failed"] += 1
                results["errors"].append({
                    "approval": approval_name,
                    "error": result.get("error", "Unknown error")
                })
        except Exception as e:
            results["failed"] += 1
            results["errors"].append({
                "approval": approval_name,
                "error": str(e)
            })

    results["message"] = _("{0} suggestions approved, {1} failed").format(
        results["approved"], results["failed"]
    )

    return results


# ============================================================================
# Template APIs
# ============================================================================

@frappe.whitelist()
def get_prompt_templates(
    job_type: Optional[str] = None,
    is_active: bool = True
) -> List[Dict[str, Any]]:
    """Get available AI prompt templates

    Args:
        job_type: Filter by job type
        is_active: Filter by active status

    Returns:
        List of template summaries
    """
    is_active = _to_bool(is_active)

    filters = {}
    if job_type:
        filters["job_type"] = job_type
    if is_active:
        filters["is_active"] = 1

    return frappe.get_all(
        "AI Prompt Template",
        filters=filters,
        fields=[
            "name", "template_name", "template_code", "job_type",
            "is_active", "is_default", "version", "description",
            "default_ai_provider", "total_uses", "successful_uses",
            "average_confidence"
        ],
        order_by="is_default desc, total_uses desc"
    )


@frappe.whitelist()
def render_prompt_template(
    template: str,
    product: Optional[str] = None,
    channel: Optional[str] = None,
    locale: Optional[str] = None,
    extra_context: Optional[str] = None
) -> Dict[str, str]:
    """Render a prompt template with product data

    Args:
        template: Template name
        product: Product name for context
        channel: Channel for context
        locale: Locale for context
        extra_context: Additional context as JSON string

    Returns:
        Dictionary with rendered system_prompt and user_prompt
    """
    try:
        from frappe_pim.pim.doctype.ai_prompt_template.ai_prompt_template import render_template
        return render_template(template, product, channel, locale, extra_context)
    except ImportError:
        doc = frappe.get_doc("AI Prompt Template", template)

        # Load product data if provided
        product_data = None
        attributes_data = None
        if product:
            product_doc = frappe.get_doc("Product Master", product)
            product_data = product_doc.as_dict()
            attributes_data = _get_product_attributes_for_ai(product, locale, channel)

        return doc.render_prompt(
            product=product_data,
            attributes=attributes_data,
            channel=frappe.get_doc("Channel", channel).as_dict() if channel else None,
            locale=frappe.get_doc("PIM Locale", locale).as_dict() if locale else None
        )


# ============================================================================
# Provider APIs
# ============================================================================

@frappe.whitelist()
def get_ai_providers() -> List[Dict[str, Any]]:
    """Get list of available AI providers

    Returns:
        List of provider configurations
    """
    providers = [
        {
            "value": "Anthropic",
            "label": _("Anthropic (Claude)"),
            "default_model": "claude-3-sonnet-20240229",
            "models": [
                "claude-3-opus-20240229",
                "claude-3-sonnet-20240229",
                "claude-3-haiku-20240307"
            ]
        },
        {
            "value": "OpenAI",
            "label": _("OpenAI (GPT)"),
            "default_model": "gpt-4-turbo-preview",
            "models": [
                "gpt-4-turbo-preview",
                "gpt-4",
                "gpt-3.5-turbo"
            ]
        },
        {
            "value": "Google Gemini",
            "label": _("Google Gemini"),
            "default_model": "gemini-pro",
            "models": [
                "gemini-pro",
                "gemini-pro-vision"
            ]
        },
        {
            "value": "Azure OpenAI",
            "label": _("Azure OpenAI"),
            "default_model": "gpt-4",
            "models": []
        },
        {
            "value": "AWS Bedrock",
            "label": _("AWS Bedrock"),
            "default_model": "anthropic.claude-3-sonnet",
            "models": []
        }
    ]

    # Check which providers are configured
    try:
        from frappe_pim.pim.utils.ai_providers import get_available_providers
        available = get_available_providers()
        for provider in providers:
            provider["available"] = provider["value"] in available or provider["value"] == "Mock"
    except ImportError:
        for provider in providers:
            provider["available"] = False

    return providers


@frappe.whitelist()
def test_ai_provider(
    provider: str,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """Test AI provider connection

    Args:
        provider: Provider name
        api_key: Optional API key (uses PIM Settings if not provided)

    Returns:
        Dictionary with test results
    """
    try:
        from frappe_pim.pim.utils.ai_providers import test_provider
        return test_provider(provider, api_key)
    except ImportError:
        return {
            "provider": provider,
            "status": "error",
            "error": _("AI providers module not available")
        }
    except Exception as e:
        return {
            "provider": provider,
            "status": "error",
            "error": str(e)
        }


# ============================================================================
# Statistics APIs
# ============================================================================

@frappe.whitelist()
def get_enrichment_statistics() -> Dict[str, Any]:
    """Get AI enrichment usage statistics

    Returns:
        Dictionary with comprehensive statistics
    """
    stats = {
        "jobs": {
            "total": frappe.db.count("AI Enrichment Job"),
            "queued": frappe.db.count("AI Enrichment Job", {"status": "Queued", "docstatus": 1}),
            "processing": frappe.db.count("AI Enrichment Job", {"status": "Processing", "docstatus": 1}),
            "completed": frappe.db.count("AI Enrichment Job", {"status": "Completed", "docstatus": 1}),
            "failed": frappe.db.count("AI Enrichment Job", {"status": "Failed", "docstatus": 1})
        },
        "products_enriched": 0,
        "total_tokens": 0,
        "total_cost": 0,
        "pending_approvals": 0,
        "by_job_type": {},
        "by_provider": {}
    }

    # Aggregate job statistics
    result = frappe.db.sql("""
        SELECT
            SUM(successful_count) as products_enriched,
            SUM(total_tokens_used) as total_tokens,
            SUM(estimated_cost) as total_cost
        FROM `tabAI Enrichment Job`
        WHERE docstatus = 1
    """, as_dict=True)

    if result and result[0]:
        stats["products_enriched"] = cint(result[0].get("products_enriched", 0))
        stats["total_tokens"] = cint(result[0].get("total_tokens", 0))
        stats["total_cost"] = flt(result[0].get("total_cost", 0), 4)

    # Jobs by type
    type_stats = frappe.db.sql("""
        SELECT job_type, COUNT(*) as count, SUM(successful_count) as products
        FROM `tabAI Enrichment Job`
        WHERE docstatus = 1
        GROUP BY job_type
    """, as_dict=True)

    for ts in type_stats:
        stats["by_job_type"][ts["job_type"]] = {
            "jobs": ts["count"],
            "products": cint(ts["products"])
        }

    # Jobs by provider
    provider_stats = frappe.db.sql("""
        SELECT ai_provider, COUNT(*) as count, SUM(total_tokens_used) as tokens
        FROM `tabAI Enrichment Job`
        WHERE docstatus = 1
        GROUP BY ai_provider
    """, as_dict=True)

    for ps in provider_stats:
        stats["by_provider"][ps["ai_provider"]] = {
            "jobs": ps["count"],
            "tokens": cint(ps["tokens"])
        }

    # Pending approvals
    try:
        stats["pending_approvals"] = frappe.db.count(
            "AI Approval Queue",
            {"status": "Pending"}
        )
    except Exception:
        stats["pending_approvals"] = 0

    return stats


@frappe.whitelist()
def get_job_types() -> List[Dict[str, str]]:
    """Get available AI enrichment job types

    Returns:
        List of job type options
    """
    return [
        {"value": "Description Generation", "label": _("Description Generation")},
        {"value": "Attribute Extraction", "label": _("Attribute Extraction")},
        {"value": "Classification Suggestion", "label": _("Classification Suggestion")},
        {"value": "Image Analysis", "label": _("Image Analysis")},
        {"value": "SEO Optimization", "label": _("SEO Optimization")},
        {"value": "Translation", "label": _("Translation")},
        {"value": "Content Enhancement", "label": _("Content Enhancement")},
        {"value": "Quality Check", "label": _("Quality Check")},
        {"value": "Custom", "label": _("Custom")}
    ]


# ============================================================================
# Helper Functions
# ============================================================================

def _to_bool(value: Any) -> bool:
    """Convert various inputs to boolean"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes", "on")
    return bool(value)


def _parse_list_param(value: Optional[str]) -> List[str]:
    """Parse comma-separated or JSON array parameter"""
    if not value:
        return []

    # Try JSON array first
    if value.startswith("["):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            pass

    # Comma-separated
    return [item.strip() for item in value.split(",") if item.strip()]


def _get_product_attributes_for_ai(
    product_name: str,
    locale: Optional[str] = None,
    channel: Optional[str] = None
) -> Dict[str, Any]:
    """Get product attributes formatted for AI context"""
    attributes = {}

    try:
        from frappe_pim.pim.utils.attribute_resolver import get_all_scoped_attributes
        attrs = get_all_scoped_attributes(
            product=product_name,
            locale=locale,
            channel=channel
        )
        for attr_code, attr_data in attrs.items():
            attributes[attr_data.get("attribute_name", attr_code)] = attr_data.get("value")
    except ImportError:
        # Fallback to direct query
        attr_values = frappe.get_all(
            "Product Attribute Value",
            filters={"parent": product_name},
            fields=["attribute", "value"]
        )
        for av in attr_values:
            attr_name = frappe.db.get_value("Attribute", av["attribute"], "attribute_name") or av["attribute"]
            attributes[attr_name] = av["value"]

    return attributes


def _perform_enrichment(
    product: str,
    job_type: str,
    ai_provider: str,
    prompt_template: Optional[str] = None,
    custom_prompt: Optional[str] = None,
    channel: Optional[str] = None,
    locale: Optional[str] = None,
    auto_apply: bool = False
) -> Dict[str, Any]:
    """Perform synchronous AI enrichment for a product"""
    try:
        from frappe_pim.pim.utils.ai_providers import get_provider

        # Get provider
        provider = get_provider(ai_provider)

        # Build prompt
        system_prompt = ""
        user_prompt = ""

        if prompt_template:
            # Use template
            template_doc = frappe.get_doc("AI Prompt Template", prompt_template)
            product_doc = frappe.get_doc("Product Master", product)
            attributes = _get_product_attributes_for_ai(product, locale, channel)

            rendered = template_doc.render_prompt(
                product=product_doc.as_dict(),
                attributes=attributes,
                channel=frappe.get_doc("Channel", channel).as_dict() if channel else None,
                locale=frappe.get_doc("PIM Locale", locale).as_dict() if locale else None
            )
            system_prompt = rendered.get("system_prompt", "")
            user_prompt = rendered.get("user_prompt", "")
        elif custom_prompt:
            user_prompt = custom_prompt
            system_prompt = "You are an AI assistant helping to enrich product information for a Product Information Management (PIM) system. Provide accurate, professional content."
        else:
            frappe.throw(_("Either prompt_template or custom_prompt is required"))

        # Call AI provider
        response = provider.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt
        )

        if not response.success:
            return {
                "success": False,
                "product": product,
                "error": response.error_message,
                "job_type": job_type
            }

        result = {
            "success": True,
            "product": product,
            "job_type": job_type,
            "content": response.content,
            "confidence": response.confidence or 0.8,
            "tokens_used": response.total_tokens,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "estimated_cost": response.estimated_cost,
            "ai_provider": ai_provider,
            "model": response.model
        }

        # Auto-apply if requested
        if auto_apply:
            apply_result = _auto_apply_enrichment(
                product=product,
                job_type=job_type,
                content=response.content
            )
            result["applied"] = apply_result.get("success", False)
            result["apply_message"] = apply_result.get("message")

        return result

    except ImportError:
        return {
            "success": False,
            "product": product,
            "error": _("AI providers module not available"),
            "job_type": job_type
        }
    except Exception as e:
        frappe.log_error(f"AI Enrichment Error: {str(e)}", "AI Enrichment API")
        return {
            "success": False,
            "product": product,
            "error": str(e),
            "job_type": job_type
        }


def _create_enrichment_job_for_product(
    product: str,
    job_type: str,
    ai_provider: str,
    prompt_template: Optional[str] = None,
    custom_prompt: Optional[str] = None,
    channel: Optional[str] = None,
    locale: Optional[str] = None,
    auto_apply: bool = False
) -> Dict[str, Any]:
    """Create an enrichment job for a single product"""
    sku = frappe.db.get_value("Product Master", product, "sku")

    job = frappe.new_doc("AI Enrichment Job")
    job.job_name = f"{job_type} - {sku}"
    job.job_type = job_type
    job.ai_provider = ai_provider
    job.prompt_template = prompt_template
    job.custom_prompt = custom_prompt
    job.filter_channel = channel
    job.target_locale = locale
    job.selection_method = "Manual Selection"
    job.require_approval = not auto_apply
    job.priority = "High"  # Single product jobs get high priority

    job.append("products", {"product": product})
    job.insert()
    job.submit()

    return {"name": job.name, "status": job.status}


def _auto_apply_enrichment(
    product: str,
    job_type: str,
    content: str
) -> Dict[str, Any]:
    """Automatically apply AI enrichment result to product"""
    try:
        doc = frappe.get_doc("Product Master", product)

        if job_type == "Description Generation":
            # Determine which description field to update
            if len(content) <= 500:
                doc.short_description = content
                field = "short_description"
            else:
                doc.long_description = content
                field = "long_description"
            doc.save()
            return {
                "success": True,
                "message": _("{0} updated successfully").format(field)
            }

        elif job_type == "Attribute Extraction":
            # Parse and apply attributes
            try:
                data = json.loads(content)
                attrs = data.get("attributes", [])
                applied = 0

                for attr in attrs:
                    if attr.get("confidence", 0) >= 0.7:
                        # Check if attribute value exists
                        existing = frappe.db.exists(
                            "Product Attribute Value",
                            {"parent": product, "attribute": attr.get("attribute")}
                        )
                        if not existing:
                            doc.append("attribute_values", {
                                "attribute": attr.get("attribute"),
                                "value": attr.get("value")
                            })
                            applied += 1

                if applied > 0:
                    doc.save()

                return {
                    "success": True,
                    "message": _("{0} attributes applied").format(applied)
                }
            except json.JSONDecodeError:
                return {
                    "success": False,
                    "message": _("Failed to parse attribute data")
                }

        return {
            "success": False,
            "message": _("Auto-apply not supported for job type: {0}").format(job_type)
        }

    except Exception as e:
        return {
            "success": False,
            "message": str(e)
        }


def _apply_ai_suggestion(approval_doc) -> None:
    """Apply an approved AI suggestion to the product"""
    product = frappe.get_doc("Product Master", approval_doc.product)

    field = approval_doc.field_name
    value = approval_doc.suggested_value

    if field == "short_description":
        product.short_description = value
    elif field == "long_description":
        product.long_description = value
    elif field.startswith("attribute:"):
        # Handle attribute values
        attr_code = field.replace("attribute:", "")
        existing = None
        for av in product.attribute_values:
            if av.attribute == attr_code:
                existing = av
                break

        if existing:
            existing.value = value
        else:
            product.append("attribute_values", {
                "attribute": attr_code,
                "value": value
            })
    elif field.startswith("classification:"):
        # Handle classification suggestions
        taxonomy = field.replace("classification:", "")
        product.append("classifications", {
            "taxonomy": taxonomy,
            "taxonomy_node": value,
            "classification_date": now_datetime(),
            "confidence_score": approval_doc.confidence_score
        })
    elif hasattr(product, field):
        setattr(product, field, value)

    product.save()
