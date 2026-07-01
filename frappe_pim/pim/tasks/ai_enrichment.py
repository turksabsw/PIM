# Copyright (c) 2024, Frappe PIM and contributors
# For license information, please see license.txt

"""
AI Enrichment Background Tasks
Provides background job processing for AI-powered product enrichment with retry logic,
batch processing, and approval queue integration.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, cint, flt
from typing import Optional, List, Dict, Any
import json
import time
import traceback


# ============================================================================
# Constants
# ============================================================================

# Default retry configuration
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 60  # seconds
RETRY_BACKOFF_MULTIPLIER = 2  # exponential backoff multiplier
MAX_RETRY_DELAY = 600  # 10 minutes max delay

# Batch processing
DEFAULT_BATCH_SIZE = 10
BATCH_COMMIT_INTERVAL = 5  # Commit every N products

# Job cleanup
DEFAULT_JOB_RETENTION_DAYS = 30


# ============================================================================
# Main Job Processor
# ============================================================================

def process_enrichment_job(job: str) -> Dict[str, Any]:
    """Process an AI enrichment job

    Main entry point for background processing of AI enrichment jobs.
    Called by frappe.enqueue() from AI Enrichment Job on_submit.

    Args:
        job: AI Enrichment Job document name

    Returns:
        Dictionary with processing results

    Note:
        This function is designed to be called via frappe.enqueue() and handles
        its own error recovery and progress updates.
    """
    result = {
        "job": job,
        "success": False,
        "processed": 0,
        "successful": 0,
        "failed": 0,
        "skipped": 0
    }

    try:
        # Load job document
        job_doc = frappe.get_doc("AI Enrichment Job", job)

        # Check if job is still queued (not cancelled)
        if job_doc.status not in ("Queued", "Processing"):
            frappe.log_error(
                f"Job {job} is not in Queued/Processing status: {job_doc.status}",
                "AI Enrichment Task"
            )
            return result

        # Mark job as started
        job_doc.mark_started()
        frappe.db.commit()

        # Get products to process
        products = job_doc.get_products_to_process()

        if not products:
            job_doc.mark_completed()
            frappe.db.commit()
            result["success"] = True
            return result

        # Get processing configuration
        batch_size = job_doc.batch_size or DEFAULT_BATCH_SIZE
        max_retries = job_doc.max_retries if job_doc.max_retries is not None else DEFAULT_MAX_RETRIES

        # Process products in batches
        total_batches = (len(products) + batch_size - 1) // batch_size

        for batch_num in range(total_batches):
            # Check if job was cancelled
            current_status = frappe.db.get_value("AI Enrichment Job", job, "status")
            if current_status == "Cancelled":
                break

            start_idx = batch_num * batch_size
            end_idx = min(start_idx + batch_size, len(products))
            batch_products = products[start_idx:end_idx]

            # Process batch
            batch_result = _process_product_batch(
                job_doc=job_doc,
                products=batch_products,
                max_retries=max_retries
            )

            # Update progress
            result["processed"] += batch_result["processed"]
            result["successful"] += batch_result["successful"]
            result["failed"] += batch_result["failed"]
            result["skipped"] += batch_result["skipped"]

            job_doc.update_progress(
                processed=batch_result["processed"],
                successful=batch_result["successful"],
                failed=batch_result["failed"],
                skipped=batch_result["skipped"],
                pending_approval=batch_result.get("pending_approval", 0),
                current_batch=batch_num + 1
            )

            # Update token usage
            job_doc.update_token_usage(
                input_tokens=batch_result.get("input_tokens", 0),
                output_tokens=batch_result.get("output_tokens", 0)
            )

            # Commit after each batch
            frappe.db.commit()

        # Mark job as completed
        job_doc.reload()
        job_doc.mark_completed()
        frappe.db.commit()

        result["success"] = True

    except Exception as e:
        error_msg = str(e)
        frappe.log_error(
            f"AI Enrichment Job {job} failed: {error_msg}\n{traceback.format_exc()}",
            "AI Enrichment Task"
        )

        try:
            job_doc = frappe.get_doc("AI Enrichment Job", job)
            job_doc.mark_failed(error_msg)
            frappe.db.commit()
        except Exception:
            pass

        result["error"] = error_msg

    return result


def _process_product_batch(
    job_doc,
    products: List[str],
    max_retries: int = DEFAULT_MAX_RETRIES
) -> Dict[str, Any]:
    """Process a batch of products for AI enrichment

    Args:
        job_doc: AI Enrichment Job document
        products: List of product names to process
        max_retries: Maximum retry attempts per product

    Returns:
        Dictionary with batch processing results
    """
    result = {
        "processed": 0,
        "successful": 0,
        "failed": 0,
        "skipped": 0,
        "pending_approval": 0,
        "input_tokens": 0,
        "output_tokens": 0
    }

    for product_name in products:
        try:
            # Process single product with retry logic
            product_result = _process_single_product_with_retry(
                job_doc=job_doc,
                product_name=product_name,
                max_retries=max_retries
            )

            result["processed"] += 1

            if product_result.get("success"):
                result["successful"] += 1
                if product_result.get("pending_approval"):
                    result["pending_approval"] += 1
            elif product_result.get("skipped"):
                result["skipped"] += 1
            else:
                result["failed"] += 1

            # Accumulate token usage
            result["input_tokens"] += product_result.get("input_tokens", 0)
            result["output_tokens"] += product_result.get("output_tokens", 0)

            # Log processing
            job_doc.log_processing(
                product=product_name,
                action="processed" if product_result.get("success") else "failed",
                details={
                    "tokens": product_result.get("input_tokens", 0) + product_result.get("output_tokens", 0),
                    "retries": product_result.get("retries", 0)
                }
            )

        except Exception as e:
            result["processed"] += 1
            result["failed"] += 1

            job_doc.log_error(
                product=product_name,
                error=str(e),
                details={"traceback": traceback.format_exc()[:500]}
            )

    return result


def _process_single_product_with_retry(
    job_doc,
    product_name: str,
    max_retries: int = DEFAULT_MAX_RETRIES
) -> Dict[str, Any]:
    """Process a single product with exponential backoff retry logic

    Args:
        job_doc: AI Enrichment Job document
        product_name: Product Master document name
        max_retries: Maximum number of retry attempts

    Returns:
        Dictionary with processing result
    """
    result = {
        "success": False,
        "product": product_name,
        "retries": 0,
        "input_tokens": 0,
        "output_tokens": 0
    }

    # Check if product should be skipped
    if _should_skip_product(job_doc, product_name):
        result["skipped"] = True
        return result

    retry_delay = DEFAULT_RETRY_DELAY

    for attempt in range(max_retries + 1):
        result["retries"] = attempt

        try:
            # Perform the actual AI enrichment
            enrichment_result = _perform_product_enrichment(
                job_doc=job_doc,
                product_name=product_name
            )

            result["success"] = enrichment_result.get("success", False)
            result["input_tokens"] = enrichment_result.get("input_tokens", 0)
            result["output_tokens"] = enrichment_result.get("output_tokens", 0)
            result["content"] = enrichment_result.get("content")
            result["confidence"] = enrichment_result.get("confidence")

            if result["success"]:
                # Handle result based on approval settings
                if job_doc.require_approval:
                    _create_approval_entry(job_doc, product_name, enrichment_result)
                    result["pending_approval"] = True
                else:
                    _apply_enrichment_result(job_doc, product_name, enrichment_result)

                return result

            # If failed but not due to rate limit, don't retry
            if not _is_retryable_error(enrichment_result.get("error", "")):
                result["error"] = enrichment_result.get("error")
                return result

        except RateLimitError as e:
            # Rate limit - wait and retry
            if attempt < max_retries:
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * RETRY_BACKOFF_MULTIPLIER, MAX_RETRY_DELAY)
                continue
            else:
                result["error"] = f"Rate limit exceeded after {max_retries} retries"
                return result

        except ProviderError as e:
            # Provider error - may be retryable
            if attempt < max_retries and _is_retryable_error(str(e)):
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * RETRY_BACKOFF_MULTIPLIER, MAX_RETRY_DELAY)
                continue
            else:
                result["error"] = str(e)
                return result

        except Exception as e:
            # Unexpected error
            result["error"] = str(e)
            return result

    return result


def _should_skip_product(job_doc, product_name: str) -> bool:
    """Check if a product should be skipped based on job settings

    Args:
        job_doc: AI Enrichment Job document
        product_name: Product Master document name

    Returns:
        True if product should be skipped
    """
    try:
        # Check if product exists
        if not frappe.db.exists("Product Master", product_name):
            return True

        # Check if product already has content for this job type
        if job_doc.skip_already_enriched:
            product = frappe.get_doc("Product Master", product_name)

            if job_doc.job_type == "Description Generation":
                if product.short_description and product.long_description:
                    return True

            elif job_doc.job_type == "Classification Suggestion":
                # Check if product has classifications
                if frappe.db.exists(
                    "Product Classification",
                    {"parent": product_name}
                ):
                    return True

        return False

    except Exception:
        return False


def _perform_product_enrichment(
    job_doc,
    product_name: str
) -> Dict[str, Any]:
    """Perform AI enrichment for a single product

    Args:
        job_doc: AI Enrichment Job document
        product_name: Product Master document name

    Returns:
        Dictionary with enrichment result
    """
    try:
        # Get AI provider
        provider = _get_ai_provider(job_doc.ai_provider)

        # Build prompt
        prompts = _build_prompts(job_doc, product_name)

        # Call AI provider
        response = provider.generate(
            system_prompt=prompts.get("system_prompt", ""),
            user_prompt=prompts.get("user_prompt", ""),
            temperature=job_doc.temperature,
            max_tokens=job_doc.max_tokens
        )

        if not response.success:
            return {
                "success": False,
                "error": response.error_message,
                "input_tokens": response.input_tokens or 0,
                "output_tokens": response.output_tokens or 0
            }

        return {
            "success": True,
            "content": response.content,
            "confidence": response.confidence or 0.8,
            "input_tokens": response.input_tokens or 0,
            "output_tokens": response.output_tokens or 0,
            "model": response.model
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def _get_ai_provider(provider_name: str):
    """Get AI provider instance

    Args:
        provider_name: Name of the AI provider

    Returns:
        AI provider instance

    Raises:
        ProviderError: If provider is not available
    """
    try:
        from frappe_pim.pim.utils.ai_providers import get_provider
        return get_provider(provider_name)
    except ImportError:
        raise ProviderError(f"AI providers module not available")
    except Exception as e:
        raise ProviderError(f"Failed to get provider {provider_name}: {str(e)}")


def _build_prompts(job_doc, product_name: str) -> Dict[str, str]:
    """Build prompts for AI enrichment

    Args:
        job_doc: AI Enrichment Job document
        product_name: Product Master document name

    Returns:
        Dictionary with system_prompt and user_prompt
    """
    system_prompt = ""
    user_prompt = ""

    # Load product data
    product = frappe.get_doc("Product Master", product_name)
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

    # Get product attributes
    attributes = _get_product_attributes(product_name, job_doc.target_locale, job_doc.filter_channel)

    if job_doc.prompt_template:
        # Use template
        try:
            template_doc = frappe.get_doc("AI Prompt Template", job_doc.prompt_template)

            channel_data = None
            if job_doc.filter_channel:
                channel_data = frappe.get_doc("Channel", job_doc.filter_channel).as_dict()

            locale_data = None
            if job_doc.target_locale:
                locale_data = frappe.get_doc("PIM Locale", job_doc.target_locale).as_dict()

            rendered = template_doc.render_prompt(
                product=product_data,
                attributes=attributes,
                channel=channel_data,
                locale=locale_data
            )
            system_prompt = rendered.get("system_prompt", "")
            user_prompt = rendered.get("user_prompt", "")

        except Exception as e:
            frappe.log_error(f"Failed to render prompt template: {str(e)}")
            # Fall back to custom prompt
            user_prompt = job_doc.custom_prompt or ""

    elif job_doc.custom_prompt:
        user_prompt = job_doc.custom_prompt
        system_prompt = _get_default_system_prompt(job_doc.job_type)

    else:
        # Generate default prompt based on job type
        system_prompt = _get_default_system_prompt(job_doc.job_type)
        user_prompt = _get_default_user_prompt(job_doc.job_type, product_data, attributes)

    return {
        "system_prompt": system_prompt,
        "user_prompt": user_prompt
    }


def _get_default_system_prompt(job_type: str) -> str:
    """Get default system prompt for job type"""
    prompts = {
        "Description Generation": "You are an expert product copywriter. Generate compelling, accurate product descriptions that highlight key features and benefits.",
        "Attribute Extraction": "You are a product data specialist. Extract structured attribute data from product information accurately and consistently.",
        "Classification Suggestion": "You are a product taxonomy expert. Suggest appropriate classifications based on product characteristics.",
        "Image Analysis": "You are a visual product analyst. Describe product images and extract relevant visual attributes.",
        "SEO Optimization": "You are an SEO specialist. Optimize product content for search engines while maintaining readability.",
        "Translation": "You are a professional translator. Translate product content accurately while maintaining the original meaning and tone.",
        "Content Enhancement": "You are a content editor. Improve product content quality, clarity, and consistency.",
        "Quality Check": "You are a quality assurance specialist. Review product content for accuracy, completeness, and consistency.",
        "Custom": "You are an AI assistant helping to enrich product information for a Product Information Management (PIM) system."
    }
    return prompts.get(job_type, prompts["Custom"])


def _get_default_user_prompt(
    job_type: str,
    product_data: Dict[str, Any],
    attributes: Dict[str, Any]
) -> str:
    """Generate default user prompt based on job type and product data"""
    attrs_text = json.dumps(attributes, indent=2) if attributes else "No attributes available"

    if job_type == "Description Generation":
        return f"""Generate a product description for:

Product: {product_data.get('product_name', 'N/A')}
SKU: {product_data.get('sku', 'N/A')}
Brand: {product_data.get('brand', 'N/A')}
Category: {product_data.get('product_family', 'N/A')}

Current description: {product_data.get('short_description', 'None')}

Attributes:
{attrs_text}

Provide a compelling description that highlights key features and benefits."""

    elif job_type == "Attribute Extraction":
        return f"""Extract product attributes from this information:

Product: {product_data.get('product_name', 'N/A')}
Description: {product_data.get('short_description', '')} {product_data.get('long_description', '')}

Return a JSON object with extracted attributes in the format:
{{"attributes": [{{"attribute": "name", "value": "value", "confidence": 0.0-1.0}}]}}"""

    elif job_type == "Classification Suggestion":
        return f"""Suggest product classifications for:

Product: {product_data.get('product_name', 'N/A')}
Brand: {product_data.get('brand', 'N/A')}
Description: {product_data.get('short_description', 'N/A')}

Attributes:
{attrs_text}

Return a JSON array with classification suggestions."""

    else:
        return f"""Process this product information:

Product: {product_data.get('product_name', 'N/A')}
SKU: {product_data.get('sku', 'N/A')}
Brand: {product_data.get('brand', 'N/A')}
Description: {product_data.get('short_description', 'N/A')}

Attributes:
{attrs_text}"""


def _get_product_attributes(
    product_name: str,
    locale: Optional[str] = None,
    channel: Optional[str] = None
) -> Dict[str, Any]:
    """Get product attributes for AI context"""
    attributes = {}

    try:
        from frappe_pim.pim.utils.attribute_resolver import get_all_scoped_attributes
        attrs = get_all_scoped_attributes(
            product=product_name,
            locale=locale,
            channel=channel
        )
        for attr_code, attr_data in attrs.items():
            attr_name = attr_data.get("attribute_name", attr_code)
            attributes[attr_name] = attr_data.get("value")
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
    except Exception:
        pass

    return attributes


def _create_approval_entry(
    job_doc,
    product_name: str,
    enrichment_result: Dict[str, Any]
) -> Optional[str]:
    """Create an AI Approval Queue entry for review

    Args:
        job_doc: AI Enrichment Job document
        product_name: Product Master document name
        enrichment_result: Result from AI enrichment

    Returns:
        Approval queue entry name or None
    """
    try:
        # Determine field based on job type
        field_name = _get_target_field(job_doc.job_type)
        original_value = _get_original_value(product_name, field_name)

        approval = frappe.new_doc("AI Approval Queue")
        approval.product = product_name
        approval.enrichment_job = job_doc.name
        approval.job_type = job_doc.job_type
        approval.field_name = field_name
        approval.original_value = original_value
        approval.suggested_value = enrichment_result.get("content", "")
        approval.confidence_score = flt(enrichment_result.get("confidence", 0.8), 2)
        approval.ai_provider = job_doc.ai_provider
        approval.ai_model = enrichment_result.get("model", "")
        approval.status = "Pending"
        approval.insert(ignore_permissions=True)

        return approval.name

    except Exception as e:
        frappe.log_error(f"Failed to create approval entry: {str(e)}")
        return None


def _apply_enrichment_result(
    job_doc,
    product_name: str,
    enrichment_result: Dict[str, Any]
) -> bool:
    """Apply AI enrichment result directly to product

    Args:
        job_doc: AI Enrichment Job document
        product_name: Product Master document name
        enrichment_result: Result from AI enrichment

    Returns:
        True if successfully applied
    """
    try:
        content = enrichment_result.get("content", "")
        confidence = enrichment_result.get("confidence", 0.8)

        # Check auto-apply threshold
        threshold = job_doc.auto_apply_threshold or 0
        if confidence * 100 < threshold:
            # Below threshold - create approval entry instead
            _create_approval_entry(job_doc, product_name, enrichment_result)
            return True

        product = frappe.get_doc("Product Master", product_name)

        if job_doc.job_type == "Description Generation":
            # Apply to appropriate description field
            if len(content) <= 500:
                product.short_description = content
            else:
                product.long_description = content
            product.save(ignore_permissions=True)

        elif job_doc.job_type == "Attribute Extraction":
            # Parse and apply attributes
            try:
                data = json.loads(content)
                for attr in data.get("attributes", []):
                    if flt(attr.get("confidence", 0)) >= 0.7:
                        _apply_attribute_value(product, attr)
                product.save(ignore_permissions=True)
            except json.JSONDecodeError:
                pass

        elif job_doc.job_type == "Classification Suggestion":
            # Parse and apply classifications
            try:
                suggestions = json.loads(content)
                for sug in suggestions[:3]:  # Limit to top 3
                    if flt(sug.get("confidence", 0)) >= 0.8:
                        _apply_classification(product, sug)
                product.save(ignore_permissions=True)
            except json.JSONDecodeError:
                pass

        return True

    except Exception as e:
        frappe.log_error(f"Failed to apply enrichment result: {str(e)}")
        return False


def _apply_attribute_value(product, attr_data: Dict[str, Any]) -> None:
    """Apply an attribute value to a product"""
    attr_code = attr_data.get("attribute")
    value = attr_data.get("value")

    if not attr_code or not value:
        return

    # Check if attribute value exists
    existing = None
    for av in product.get("attribute_values", []):
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


def _apply_classification(product, classification_data: Dict[str, Any]) -> None:
    """Apply a classification to a product"""
    node_code = classification_data.get("node_code")

    if not node_code:
        return

    # Get taxonomy node
    node = frappe.db.get_value(
        "Taxonomy Node",
        {"node_code": node_code, "is_leaf": 1},
        ["name", "taxonomy"],
        as_dict=True
    )

    if not node:
        return

    # Check if classification exists
    existing = frappe.db.exists(
        "Product Classification",
        {
            "parent": product.name,
            "taxonomy": node["taxonomy"]
        }
    )

    if not existing:
        product.append("classifications", {
            "taxonomy": node["taxonomy"],
            "taxonomy_node": node["name"],
            "classification_date": now_datetime(),
            "confidence_score": classification_data.get("confidence", 0.8)
        })


def _get_target_field(job_type: str) -> str:
    """Get the target field name for a job type"""
    field_map = {
        "Description Generation": "long_description",
        "Attribute Extraction": "attribute_values",
        "Classification Suggestion": "classifications",
        "Image Analysis": "image_analysis",
        "SEO Optimization": "seo_content",
        "Translation": "translated_content",
        "Content Enhancement": "long_description",
        "Quality Check": "quality_score"
    }
    return field_map.get(job_type, "ai_content")


def _get_original_value(product_name: str, field_name: str) -> Optional[str]:
    """Get the original value of a field"""
    try:
        if field_name in ("attribute_values", "classifications"):
            return None

        return frappe.db.get_value("Product Master", product_name, field_name)
    except Exception:
        return None


def _is_retryable_error(error: str) -> bool:
    """Check if an error is retryable"""
    retryable_patterns = [
        "rate limit",
        "timeout",
        "connection",
        "temporary",
        "overloaded",
        "503",
        "502",
        "504",
        "429"
    ]
    error_lower = error.lower()
    return any(pattern in error_lower for pattern in retryable_patterns)


# ============================================================================
# Custom Exceptions
# ============================================================================

class RateLimitError(Exception):
    """Raised when AI provider rate limit is exceeded"""
    pass


class ProviderError(Exception):
    """Raised when AI provider encounters an error"""
    pass


# ============================================================================
# Scheduled Tasks
# ============================================================================

def process_pending_jobs() -> Dict[str, Any]:
    """Process queued AI enrichment jobs

    Scheduled task to process any queued jobs that haven't started yet.
    This handles jobs that might have been missed or need restart.

    Returns:
        Dictionary with processing summary
    """
    result = {
        "processed": 0,
        "successful": 0,
        "failed": 0
    }

    # Get queued jobs
    queued_jobs = frappe.get_all(
        "AI Enrichment Job",
        filters={
            "status": "Queued",
            "docstatus": 1
        },
        order_by="creation asc",
        limit_page_length=5  # Process 5 at a time
    )

    for job_data in queued_jobs:
        try:
            # Re-enqueue the job
            frappe.enqueue(
                "frappe_pim.pim.tasks.ai_enrichment.process_enrichment_job",
                queue="long",
                job=job_data["name"],
                enqueue_after_commit=True
            )
            result["processed"] += 1
            result["successful"] += 1
        except Exception as e:
            result["processed"] += 1
            result["failed"] += 1
            frappe.log_error(f"Failed to re-queue job {job_data['name']}: {str(e)}")

    frappe.db.commit()
    return result


def retry_failed_jobs() -> Dict[str, Any]:
    """Retry recently failed AI enrichment jobs

    Scheduled task to automatically retry jobs that failed within
    the last 24 hours and have retry attempts remaining.

    Returns:
        Dictionary with retry summary
    """
    result = {
        "checked": 0,
        "retried": 0,
        "skipped": 0
    }

    # Get recently failed jobs
    from frappe.utils import add_days
    cutoff_date = add_days(now_datetime(), -1)

    failed_jobs = frappe.get_all(
        "AI Enrichment Job",
        filters={
            "status": ["in", ["Failed", "Partially Completed"]],
            "docstatus": 1,
            "completed_at": [">=", cutoff_date]
        },
        fields=["name", "failed_count", "total_products", "max_retries"],
        order_by="completed_at desc",
        limit_page_length=10
    )

    for job_data in failed_jobs:
        result["checked"] += 1

        # Check if job should be retried
        max_retries = job_data.get("max_retries") or DEFAULT_MAX_RETRIES
        if job_data["failed_count"] > 0:
            try:
                # Create a retry job
                job_doc = frappe.get_doc("AI Enrichment Job", job_data["name"])
                retry_result = job_doc.retry_failed()

                if retry_result and retry_result.get("job"):
                    # Submit the retry job
                    retry_job = frappe.get_doc("AI Enrichment Job", retry_result["job"])
                    retry_job.submit()
                    result["retried"] += 1
                else:
                    result["skipped"] += 1

            except Exception as e:
                frappe.log_error(f"Failed to retry job {job_data['name']}: {str(e)}")
                result["skipped"] += 1
        else:
            result["skipped"] += 1

    frappe.db.commit()
    return result


def cleanup_old_jobs(days: int = DEFAULT_JOB_RETENTION_DAYS) -> Dict[str, Any]:
    """Clean up old completed AI enrichment jobs

    Scheduled task to remove old job records to prevent database bloat.
    Only removes completed jobs older than the retention period.

    Args:
        days: Number of days to retain jobs (default: 30)

    Returns:
        Dictionary with cleanup summary
    """
    result = {
        "deleted_jobs": 0,
        "deleted_approvals": 0
    }

    from frappe.utils import add_days
    cutoff_date = add_days(now_datetime(), -days)

    # Delete old approval queue entries (processed only)
    old_approvals = frappe.get_all(
        "AI Approval Queue",
        filters={
            "status": ["in", ["Approved", "Rejected"]],
            "creation": ["<", cutoff_date]
        },
        pluck="name"
    )

    for approval in old_approvals:
        try:
            frappe.delete_doc("AI Approval Queue", approval, force=True)
            result["deleted_approvals"] += 1
        except Exception:
            pass

    # Delete old completed jobs
    old_jobs = frappe.get_all(
        "AI Enrichment Job",
        filters={
            "status": "Completed",
            "docstatus": 1,
            "completed_at": ["<", cutoff_date]
        },
        pluck="name"
    )

    for job_name in old_jobs:
        try:
            job = frappe.get_doc("AI Enrichment Job", job_name)
            job.cancel()
            job.delete()
            result["deleted_jobs"] += 1
        except Exception:
            pass

    frappe.db.commit()
    return result


def update_job_statistics() -> None:
    """Update AI enrichment statistics cache

    Scheduled task to pre-calculate and cache enrichment statistics
    for dashboard display.
    """
    try:
        stats = {
            "total_jobs": frappe.db.count("AI Enrichment Job"),
            "queued": frappe.db.count("AI Enrichment Job", {"status": "Queued", "docstatus": 1}),
            "processing": frappe.db.count("AI Enrichment Job", {"status": "Processing", "docstatus": 1}),
            "completed": frappe.db.count("AI Enrichment Job", {"status": "Completed", "docstatus": 1}),
            "failed": frappe.db.count("AI Enrichment Job", {"status": "Failed", "docstatus": 1}),
            "updated_at": str(now_datetime())
        }

        # Aggregate totals
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

        # Cache the statistics
        frappe.cache().set_value("pim_ai_enrichment_stats", stats, expires_in_sec=3600)

    except Exception as e:
        frappe.log_error(f"Failed to update AI statistics: {str(e)}")
