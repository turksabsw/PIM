"""
Channel Publishing API Endpoints for PIM

Provides API endpoints for publishing products to marketplace channels,
checking publish status, and validating products against channel requirements.

Key Features:
- Publish products to configured marketplace channels
- Check status of ongoing publish jobs
- Validate products against channel-specific requirements
- Bulk publishing with progress tracking
- Channel readiness assessment

Note: frappe imports are deferred to function/method level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union
import json

from frappe_pim.pim.channels.base import (
    ChannelAdapter,
    ValidationResult,
    MappingResult,
    PublishResult,
    StatusResult,
    PublishStatus,
    RateLimitError,
    AuthenticationError,
    PublishError,
    ChannelAdapterError,
    get_adapter,
    list_adapters,
)


# =============================================================================
# Custom Exceptions
# =============================================================================

class ChannelAPIError(Exception):
    """Base exception for channel API errors"""

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


class ProductNotFoundError(ChannelAPIError):
    """Raised when product is not found"""
    pass


class ChannelNotFoundError(ChannelAPIError):
    """Raised when channel is not found or not configured"""
    pass


class ChannelNotActiveError(ChannelAPIError):
    """Raised when channel is not active"""
    pass


class PublishJobNotFoundError(ChannelAPIError):
    """Raised when publish job is not found"""
    pass


class ValidationFailedError(ChannelAPIError):
    """Raised when validation fails for one or more products"""
    pass


# =============================================================================
# Enums and Constants
# =============================================================================

class JobStatus(str, Enum):
    """Status values for publish jobs in database"""
    PENDING = "pending"
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"
    CANCELLED = "cancelled"


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class ChannelValidationResult:
    """Result of validating a product against a channel"""
    product: str
    channel: str
    channel_name: str
    is_valid: bool
    errors: List[Dict] = field(default_factory=list)
    warnings: List[Dict] = field(default_factory=list)
    validated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict:
        return {
            "product": self.product,
            "channel": self.channel,
            "channel_name": self.channel_name,
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "validated_at": self.validated_at.isoformat(),
        }


@dataclass
class PublishJobResult:
    """Result of a publish operation"""
    job_id: str
    channel: str
    channel_name: str
    status: str
    products_submitted: int = 0
    products_succeeded: int = 0
    products_failed: int = 0
    errors: List[Dict] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    external_id: str = None

    def to_dict(self) -> Dict:
        return {
            "job_id": self.job_id,
            "channel": self.channel,
            "channel_name": self.channel_name,
            "status": self.status,
            "products_submitted": self.products_submitted,
            "products_succeeded": self.products_succeeded,
            "products_failed": self.products_failed,
            "errors": self.errors,
            "created_at": self.created_at.isoformat(),
            "external_id": self.external_id,
        }


@dataclass
class PublishStatusResult:
    """Result of checking publish job status"""
    job_id: str
    channel: str
    status: str
    progress: float = 0.0
    products_processed: int = 0
    products_total: int = 0
    errors: List[Dict] = field(default_factory=list)
    last_checked: datetime = field(default_factory=datetime.now)
    completed_at: datetime = None

    def to_dict(self) -> Dict:
        return {
            "job_id": self.job_id,
            "channel": self.channel,
            "status": self.status,
            "progress": round(self.progress, 2),
            "products_processed": self.products_processed,
            "products_total": self.products_total,
            "errors": self.errors,
            "last_checked": self.last_checked.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


@dataclass
class BulkValidationResult:
    """Result of validating multiple products"""
    channel: str
    total_products: int
    valid_count: int
    invalid_count: int
    results: List[ChannelValidationResult] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "channel": self.channel,
            "total_products": self.total_products,
            "valid_count": self.valid_count,
            "invalid_count": self.invalid_count,
            "results": [r.to_dict() for r in self.results],
        }


# =============================================================================
# Helper Functions
# =============================================================================

def _get_channel_doc(channel: str) -> Any:
    """Get channel document from database.

    Args:
        channel: Channel name or channel code

    Returns:
        Channel document

    Raises:
        ChannelNotFoundError: If channel is not found
    """
    import frappe

    # Try by name first
    if frappe.db.exists("Channel", channel):
        return frappe.get_doc("Channel", channel)

    # Try by channel_code
    channel_name = frappe.db.get_value("Channel", {"channel_code": channel.lower()}, "name")
    if channel_name:
        return frappe.get_doc("Channel", channel_name)

    raise ChannelNotFoundError(
        f"Channel not found: {channel}",
        details={"channel": channel}
    )


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
        "custom_pim_product_family": "pim_product_family",
        "custom_pim_product_type": "pim_product_type",
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


def _get_products_data(product_codes: List[str]) -> List[Dict]:
    """Get multiple products data.

    Args:
        product_codes: List of product/item codes

    Returns:
        List of product data dictionaries
    """
    products = []
    for code in product_codes:
        try:
            products.append(_get_product_data(code))
        except ProductNotFoundError:
            pass  # Skip products that don't exist
    return products


def _create_publish_job(channel: str, product_codes: List[str], job_id: str) -> None:
    """Create a publish job record in the database.

    Args:
        channel: Channel code
        product_codes: List of product codes being published
        job_id: Unique job identifier
    """
    import frappe

    try:
        # Check if Channel Publish Job DocType exists
        if frappe.db.exists("DocType", "Channel Publish Job"):
            job = frappe.new_doc("Channel Publish Job")
            job.job_id = job_id
            job.channel = channel
            job.status = JobStatus.PENDING.value
            job.products_submitted = len(product_codes)
            job.product_codes = json.dumps(product_codes)
            job.insert(ignore_permissions=True)
        else:
            # Log job info if DocType doesn't exist
            frappe.log_error(
                message=json.dumps({
                    "job_id": job_id,
                    "channel": channel,
                    "product_count": len(product_codes),
                    "product_codes": product_codes[:10],  # First 10 only
                }),
                title=f"PIM Publish Job Created - {channel}"
            )
    except Exception:
        pass  # Don't fail publish if job tracking fails


def _update_publish_job(job_id: str, status: str, **kwargs) -> None:
    """Update a publish job record.

    Args:
        job_id: Job identifier
        status: New status
        **kwargs: Additional fields to update
    """
    import frappe

    try:
        if frappe.db.exists("DocType", "Channel Publish Job"):
            job_name = frappe.db.get_value("Channel Publish Job", {"job_id": job_id}, "name")
            if job_name:
                frappe.db.set_value("Channel Publish Job", job_name, {
                    "status": status,
                    **kwargs
                })
    except Exception:
        pass


def _get_adapter_for_channel(channel_doc: Any) -> ChannelAdapter:
    """Get the appropriate adapter for a channel.

    Args:
        channel_doc: Channel document

    Returns:
        ChannelAdapter instance

    Raises:
        ChannelNotFoundError: If no adapter found for channel
    """
    import frappe

    channel_code = getattr(channel_doc, 'channel_code', None)

    if not channel_code:
        raise ChannelNotFoundError(
            f"Channel has no channel_code: {channel_doc.name}",
            details={"channel": channel_doc.name}
        )

    try:
        return get_adapter(channel_code, channel_doc)
    except Exception as e:
        raise ChannelNotFoundError(
            f"No adapter available for channel: {channel_code}",
            details={"channel": channel_code, "error": str(e)}
        )


# =============================================================================
# API Functions
# =============================================================================

def publish_to_channel(
    channel: str,
    products: Union[str, List[str]],
    validate_first: bool = True,
    async_mode: bool = False
) -> Dict:
    """Publish products to a marketplace channel.

    Validates products against channel requirements, maps attributes to
    channel format, and submits them for publishing.

    Args:
        channel: Channel name or channel code to publish to
        products: Single product code or list of product codes
        validate_first: If True, validate products before publishing (default True)
        async_mode: If True, queue the job for background processing (default False)

    Returns:
        Dictionary with publish job details including job_id and status

    Example:
        # Single product
        result = publish_to_channel("amazon", "PROD-001")

        # Multiple products
        result = publish_to_channel("shopify", ["PROD-001", "PROD-002", "PROD-003"])

        # Skip validation (not recommended)
        result = publish_to_channel("amazon", products, validate_first=False)
    """
    import frappe
    import uuid

    try:
        # Normalize products to list
        if isinstance(products, str):
            product_codes = [products]
        else:
            product_codes = list(products)

        if not product_codes:
            frappe.throw(frappe._("No products specified for publishing"))

        # Get channel document
        channel_doc = _get_channel_doc(channel)

        # Check if channel is active
        if hasattr(channel_doc, 'enabled') and not channel_doc.enabled:
            raise ChannelNotActiveError(
                f"Channel is not active: {channel}",
                details={"channel": channel}
            )

        # Get adapter for channel
        adapter = _get_adapter_for_channel(channel_doc)

        # Get product data
        products_data = _get_products_data(product_codes)

        if not products_data:
            raise ProductNotFoundError(
                "No valid products found",
                details={"product_codes": product_codes}
            )

        # Validate products if requested
        if validate_first:
            validation_results = adapter.validate_products(products_data)
            invalid_products = [r for r in validation_results if not r.is_valid]

            if invalid_products:
                errors = []
                for result in invalid_products:
                    errors.extend([{
                        "product": result.product,
                        **error
                    } for error in result.errors])

                raise ValidationFailedError(
                    f"Validation failed for {len(invalid_products)} product(s)",
                    details={
                        "invalid_count": len(invalid_products),
                        "errors": errors,
                    }
                )

        # Generate job ID
        job_id = str(uuid.uuid4())

        # Create job record
        _create_publish_job(adapter.channel_code, product_codes, job_id)

        # Async publishing
        if async_mode:
            # Queue for background processing
            frappe.enqueue(
                "frappe_pim.pim.api.channel._execute_publish",
                job_id=job_id,
                channel_name=channel_doc.name,
                products_data=products_data,
                queue="long",
                timeout=600,
            )

            return PublishJobResult(
                job_id=job_id,
                channel=adapter.channel_code,
                channel_name=adapter.channel_name,
                status=JobStatus.QUEUED.value,
                products_submitted=len(products_data),
            ).to_dict()

        # Synchronous publishing
        result = adapter.publish(products_data)

        # Update job status
        status = JobStatus.COMPLETED.value if result.success else JobStatus.FAILED.value
        if result.status == PublishStatus.PARTIAL:
            status = JobStatus.PARTIAL.value

        _update_publish_job(
            job_id,
            status=status,
            products_succeeded=result.products_succeeded,
            products_failed=result.products_failed,
            external_id=result.external_id,
        )

        return PublishJobResult(
            job_id=job_id,
            channel=adapter.channel_code,
            channel_name=adapter.channel_name,
            status=status,
            products_submitted=result.products_submitted,
            products_succeeded=result.products_succeeded,
            products_failed=result.products_failed,
            errors=result.errors,
            external_id=result.external_id,
        ).to_dict()

    except ChannelAPIError as e:
        frappe.log_error(f"Channel API Error: {e.message}")
        frappe.throw(e.message)
    except ChannelAdapterError as e:
        frappe.log_error(f"Channel Adapter Error: {e.message}")
        frappe.throw(e.message)
    except RateLimitError as e:
        frappe.log_error(f"Rate Limit Error: {e.message}")
        frappe.throw(
            frappe._("Channel rate limit exceeded. Please try again in {0} seconds.").format(e.retry_after)
        )
    except AuthenticationError as e:
        frappe.log_error(f"Authentication Error: {e.message}")
        frappe.throw(frappe._("Channel authentication failed. Please check channel credentials."))
    except Exception as e:
        frappe.log_error(f"Publish Error: {str(e)}")
        frappe.throw(str(e))


def _execute_publish(job_id: str, channel_name: str, products_data: List[Dict]) -> None:
    """Execute publishing in background job.

    Internal function called by frappe.enqueue for async publishing.

    Args:
        job_id: Job identifier
        channel_name: Channel document name
        products_data: List of product data dictionaries
    """
    import frappe

    try:
        # Update status to in progress
        _update_publish_job(job_id, status=JobStatus.IN_PROGRESS.value)

        # Get channel and adapter
        channel_doc = frappe.get_doc("Channel", channel_name)
        adapter = _get_adapter_for_channel(channel_doc)

        # Execute publish
        result = adapter.publish(products_data)

        # Determine final status
        if result.success:
            status = JobStatus.COMPLETED.value
        elif result.status == PublishStatus.PARTIAL:
            status = JobStatus.PARTIAL.value
        else:
            status = JobStatus.FAILED.value

        # Update job with results
        _update_publish_job(
            job_id,
            status=status,
            products_succeeded=result.products_succeeded,
            products_failed=result.products_failed,
            external_id=result.external_id,
            errors=json.dumps(result.errors) if result.errors else None,
        )

    except Exception as e:
        frappe.log_error(f"Background publish failed for job {job_id}: {str(e)}")
        _update_publish_job(
            job_id,
            status=JobStatus.FAILED.value,
            errors=json.dumps([{"message": str(e)}]),
        )


def get_publish_status(job_id: str, check_external: bool = True) -> Dict:
    """Get the status of a publish job.

    Retrieves the current status of a publish job, optionally checking
    with the external channel API for the latest status.

    Args:
        job_id: The job ID returned from publish_to_channel
        check_external: If True, also check status from channel API (default True)

    Returns:
        Dictionary with job status details

    Example:
        status = get_publish_status("123e4567-e89b-12d3-a456-426614174000")
        # Returns: {"job_id": "...", "status": "completed", "progress": 1.0, ...}
    """
    import frappe

    try:
        # Try to get job from database
        job_data = None

        if frappe.db.exists("DocType", "Channel Publish Job"):
            job_name = frappe.db.get_value("Channel Publish Job", {"job_id": job_id}, "name")
            if job_name:
                job_data = frappe.get_doc("Channel Publish Job", job_name)

        if not job_data:
            raise PublishJobNotFoundError(
                f"Publish job not found: {job_id}",
                details={"job_id": job_id}
            )

        # Build status result from database
        status_result = PublishStatusResult(
            job_id=job_id,
            channel=job_data.channel if hasattr(job_data, 'channel') else "",
            status=job_data.status if hasattr(job_data, 'status') else JobStatus.PENDING.value,
            products_total=job_data.products_submitted if hasattr(job_data, 'products_submitted') else 0,
            products_processed=getattr(job_data, 'products_succeeded', 0) + getattr(job_data, 'products_failed', 0),
        )

        # Calculate progress
        if status_result.products_total > 0:
            status_result.progress = status_result.products_processed / status_result.products_total
        elif status_result.status in (JobStatus.COMPLETED.value, JobStatus.FAILED.value):
            status_result.progress = 1.0

        # Parse stored errors
        if hasattr(job_data, 'errors') and job_data.errors:
            try:
                status_result.errors = json.loads(job_data.errors)
            except (json.JSONDecodeError, TypeError):
                pass

        # Check external status if requested and job is in progress
        if check_external and status_result.status == JobStatus.IN_PROGRESS.value:
            external_id = getattr(job_data, 'external_id', None)

            if external_id:
                try:
                    channel_doc = _get_channel_doc(job_data.channel)
                    adapter = _get_adapter_for_channel(channel_doc)

                    external_status = adapter.get_status(external_id)

                    # Update with external status
                    status_result.status = external_status.status.value if isinstance(
                        external_status.status, PublishStatus
                    ) else external_status.status

                    status_result.progress = external_status.progress
                    status_result.products_processed = external_status.products_processed
                    status_result.errors = external_status.errors

                    if external_status.completed_at:
                        status_result.completed_at = external_status.completed_at

                    # Update database with external status
                    _update_publish_job(
                        job_id,
                        status=status_result.status,
                        products_succeeded=external_status.products_processed - len(external_status.errors),
                        products_failed=len(external_status.errors),
                    )

                except Exception as e:
                    # Log but don't fail - return stored status
                    frappe.log_error(f"Failed to get external status for job {job_id}: {str(e)}")

        return status_result.to_dict()

    except ChannelAPIError as e:
        frappe.log_error(f"Channel API Error: {e.message}")
        frappe.throw(e.message)
    except Exception as e:
        frappe.log_error(f"Get Status Error: {str(e)}")
        frappe.throw(str(e))


def validate_for_channel(
    channel: str,
    products: Union[str, List[str]]
) -> Union[Dict, List[Dict]]:
    """Validate products against channel requirements.

    Checks if products meet all requirements for publishing to a specific
    channel without actually publishing them.

    Args:
        channel: Channel name or channel code to validate against
        products: Single product code or list of product codes

    Returns:
        For single product: Dictionary with validation result
        For multiple products: List of validation result dictionaries

    Example:
        # Single product
        result = validate_for_channel("amazon", "PROD-001")
        # Returns: {"product": "PROD-001", "is_valid": True, ...}

        # Multiple products
        results = validate_for_channel("shopify", ["PROD-001", "PROD-002"])
        # Returns: [{"product": "PROD-001", ...}, {"product": "PROD-002", ...}]
    """
    import frappe

    try:
        # Determine if single or multiple products
        single_product = isinstance(products, str)
        if single_product:
            product_codes = [products]
        else:
            product_codes = list(products)

        if not product_codes:
            frappe.throw(frappe._("No products specified for validation"))

        # Get channel document
        channel_doc = _get_channel_doc(channel)

        # Get adapter for channel
        adapter = _get_adapter_for_channel(channel_doc)

        # Get product data
        products_data = _get_products_data(product_codes)

        if not products_data:
            raise ProductNotFoundError(
                "No valid products found",
                details={"product_codes": product_codes}
            )

        # Validate each product
        results = []
        for product_data in products_data:
            validation_result = adapter.validate_product(product_data)

            channel_result = ChannelValidationResult(
                product=product_data.get("item_code", product_data.get("name")),
                channel=adapter.channel_code,
                channel_name=adapter.channel_name,
                is_valid=validation_result.is_valid,
                errors=validation_result.errors,
                warnings=validation_result.warnings,
            )

            results.append(channel_result)

        # Return single result for single product
        if single_product:
            return results[0].to_dict()

        return [r.to_dict() for r in results]

    except ChannelAPIError as e:
        frappe.log_error(f"Channel API Error: {e.message}")
        frappe.throw(e.message)
    except ChannelAdapterError as e:
        frappe.log_error(f"Channel Adapter Error: {e.message}")
        frappe.throw(e.message)
    except Exception as e:
        frappe.log_error(f"Validation Error: {str(e)}")
        frappe.throw(str(e))


def get_channel_validation_summary(
    channel: str,
    filters: Dict = None,
    limit: int = 100
) -> Dict:
    """Get validation summary for multiple products against a channel.

    Validates products and returns aggregate statistics about how many
    products are ready for publishing.

    Args:
        channel: Channel name or channel code
        filters: Optional Frappe filters for product selection
        limit: Maximum number of products to validate (default 100)

    Returns:
        Dictionary with validation summary statistics

    Example:
        summary = get_channel_validation_summary("amazon")
        # Returns: {"total": 100, "valid": 75, "invalid": 25, "common_errors": [...]}
    """
    import frappe

    try:
        # Get channel document
        channel_doc = _get_channel_doc(channel)

        # Get adapter for channel
        adapter = _get_adapter_for_channel(channel_doc)

        # Get products
        products = frappe.get_all(
            "Item",
            filters=filters or {},
            fields=["name", "item_code", "item_name", "item_group", "brand",
                    "description", "stock_uom", "standard_rate"],
            limit_page_length=limit,
        )

        if not products:
            return {
                "channel": adapter.channel_code,
                "channel_name": adapter.channel_name,
                "total_products": 0,
                "valid_count": 0,
                "invalid_count": 0,
                "validation_rate": 0,
                "common_errors": [],
            }

        # Validate all products
        valid_count = 0
        invalid_count = 0
        error_counts = {}

        for product in products:
            product_data = dict(product)
            validation_result = adapter.validate_product(product_data)

            if validation_result.is_valid:
                valid_count += 1
            else:
                invalid_count += 1

                # Track error types
                for error in validation_result.errors:
                    error_key = f"{error.get('field', 'unknown')}:{error.get('rule', 'unknown')}"
                    error_counts[error_key] = error_counts.get(error_key, 0) + 1

        # Get most common errors
        common_errors = sorted(
            [{"error": k, "count": v} for k, v in error_counts.items()],
            key=lambda x: x["count"],
            reverse=True
        )[:10]

        total = valid_count + invalid_count
        validation_rate = (valid_count / total * 100) if total > 0 else 0

        return {
            "channel": adapter.channel_code,
            "channel_name": adapter.channel_name,
            "total_products": total,
            "valid_count": valid_count,
            "invalid_count": invalid_count,
            "validation_rate": round(validation_rate, 2),
            "common_errors": common_errors,
        }

    except ChannelAPIError as e:
        frappe.log_error(f"Channel API Error: {e.message}")
        frappe.throw(e.message)
    except Exception as e:
        frappe.log_error(f"Validation Summary Error: {str(e)}")
        frappe.throw(str(e))


def get_available_channels() -> List[Dict]:
    """Get list of available channels with their status.

    Returns:
        List of channel information dictionaries

    Example:
        channels = get_available_channels()
        # Returns: [{"name": "Amazon", "code": "amazon", "enabled": True}, ...]
    """
    import frappe

    try:
        channels = []

        # Get channels from database
        if frappe.db.exists("DocType", "Channel"):
            db_channels = frappe.get_all(
                "Channel",
                filters={},
                fields=["name", "channel_name", "channel_code", "enabled", "connection_status"]
            )

            for ch in db_channels:
                channels.append({
                    "name": ch.name,
                    "channel_name": ch.channel_name or ch.name,
                    "channel_code": ch.channel_code,
                    "enabled": ch.enabled if ch.enabled is not None else True,
                    "connection_status": ch.connection_status or "Unknown",
                    "has_adapter": ch.channel_code in list_adapters() if ch.channel_code else False,
                })

        # Add registered adapters that don't have channel docs
        registered_adapters = list_adapters()
        existing_codes = {ch["channel_code"] for ch in channels if ch.get("channel_code")}

        for adapter_code in registered_adapters:
            if adapter_code not in existing_codes:
                channels.append({
                    "name": adapter_code.title(),
                    "channel_name": adapter_code.replace("_", " ").title(),
                    "channel_code": adapter_code,
                    "enabled": False,  # Not configured
                    "connection_status": "Not Configured",
                    "has_adapter": True,
                })

        return channels

    except Exception as e:
        frappe.log_error(f"Get Channels Error: {str(e)}")
        return []


def test_channel_connection(channel: str) -> Dict:
    """Test connection to a channel.

    Args:
        channel: Channel name or channel code

    Returns:
        Dictionary with connection test results

    Example:
        result = test_channel_connection("amazon")
        # Returns: {"success": True, "message": "Connection successful"}
    """
    import frappe

    try:
        # Get channel document
        channel_doc = _get_channel_doc(channel)

        # Get adapter
        adapter = _get_adapter_for_channel(channel_doc)

        # Test connection
        result = adapter.test_connection()

        # Update channel connection status
        if hasattr(channel_doc, 'connection_status'):
            channel_doc.connection_status = "Connected" if result.get("success") else "Disconnected"
            channel_doc.save(ignore_permissions=True)

        return result

    except ChannelNotFoundError as e:
        return {
            "success": False,
            "message": e.message,
        }
    except Exception as e:
        return {
            "success": False,
            "message": str(e),
        }


def cancel_publish_job(job_id: str) -> Dict:
    """Cancel a pending or in-progress publish job.

    Args:
        job_id: The job ID to cancel

    Returns:
        Dictionary with cancellation status

    Example:
        result = cancel_publish_job("123e4567-e89b-12d3-a456-426614174000")
        # Returns: {"success": True, "message": "Job cancelled"}
    """
    import frappe

    try:
        if not frappe.db.exists("DocType", "Channel Publish Job"):
            frappe.throw(frappe._("Job tracking is not configured"))

        job_name = frappe.db.get_value("Channel Publish Job", {"job_id": job_id}, "name")
        if not job_name:
            raise PublishJobNotFoundError(
                f"Publish job not found: {job_id}",
                details={"job_id": job_id}
            )

        job = frappe.get_doc("Channel Publish Job", job_name)

        # Can only cancel pending or in-progress jobs
        if job.status not in (JobStatus.PENDING.value, JobStatus.QUEUED.value, JobStatus.IN_PROGRESS.value):
            return {
                "success": False,
                "message": f"Cannot cancel job with status: {job.status}",
            }

        # Update status
        job.status = JobStatus.CANCELLED.value
        job.save(ignore_permissions=True)

        return {
            "success": True,
            "message": "Job cancelled successfully",
            "job_id": job_id,
        }

    except ChannelAPIError as e:
        return {
            "success": False,
            "message": e.message,
        }
    except Exception as e:
        frappe.log_error(f"Cancel Job Error: {str(e)}")
        return {
            "success": False,
            "message": str(e),
        }


# =============================================================================
# Frappe Whitelist Decorators
# =============================================================================

# Apply whitelist decorators
try:
    import frappe

    publish_to_channel = frappe.whitelist()(publish_to_channel)
    get_publish_status = frappe.whitelist()(get_publish_status)
    validate_for_channel = frappe.whitelist()(validate_for_channel)
    get_channel_validation_summary = frappe.whitelist()(get_channel_validation_summary)
    get_available_channels = frappe.whitelist()(get_available_channels)
    test_channel_connection = frappe.whitelist()(test_channel_connection)
    cancel_publish_job = frappe.whitelist()(cancel_publish_job)
except ImportError:
    pass  # Allow import without frappe for testing


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # API Functions
    "publish_to_channel",
    "get_publish_status",
    "validate_for_channel",
    "get_channel_validation_summary",
    "get_available_channels",
    "test_channel_connection",
    "cancel_publish_job",

    # Data Classes
    "ChannelValidationResult",
    "PublishJobResult",
    "PublishStatusResult",
    "BulkValidationResult",

    # Enums
    "JobStatus",

    # Exceptions
    "ChannelAPIError",
    "ProductNotFoundError",
    "ChannelNotFoundError",
    "ChannelNotActiveError",
    "PublishJobNotFoundError",
    "ValidationFailedError",
]
