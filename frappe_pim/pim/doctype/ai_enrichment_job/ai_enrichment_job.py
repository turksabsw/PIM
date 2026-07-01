"""
AI Enrichment Job Controller
Manages batch AI processing for product enrichment
"""

import frappe
from frappe import _
from frappe.model.document import Document
from typing import Optional, List, Dict, Any
from frappe.utils import now_datetime, cint, flt
import json
import uuid


class AIEnrichmentJob(Document):
    def validate(self):
        self.validate_ai_config()
        self.validate_product_selection()
        self.validate_processing_settings()
        self.set_defaults()

    def validate_ai_config(self):
        """Validate AI configuration settings"""
        # Validate temperature
        if self.temperature is not None:
            if self.temperature < 0 or self.temperature > 1:
                frappe.throw(
                    _("Temperature must be between 0.0 and 1.0"),
                    title=_("Invalid Temperature")
                )

        # Validate max_tokens
        if self.max_tokens is not None and self.max_tokens < 1:
            frappe.throw(
                _("Max tokens must be at least 1"),
                title=_("Invalid Max Tokens")
            )

        # Require either prompt_template or custom_prompt
        if not self.prompt_template and not self.custom_prompt:
            frappe.throw(
                _("Either a Prompt Template or Custom Prompt is required"),
                title=_("Missing Prompt")
            )

    def validate_product_selection(self):
        """Validate product selection configuration"""
        if self.selection_method == "Manual Selection":
            if not self.products or len(self.products) == 0:
                frappe.throw(
                    _("At least one product is required for manual selection"),
                    title=_("No Products Selected")
                )
            # Check for duplicates
            product_names = [p.product for p in self.products]
            if len(product_names) != len(set(product_names)):
                frappe.throw(
                    _("Duplicate products are not allowed"),
                    title=_("Duplicate Products")
                )

        elif self.selection_method == "Product Family":
            if not self.filter_product_family:
                frappe.throw(
                    _("Product Family is required for this selection method"),
                    title=_("Missing Product Family")
                )

        elif self.selection_method == "Product Category":
            if not self.filter_product_category:
                frappe.throw(
                    _("Product Category is required for this selection method"),
                    title=_("Missing Product Category")
                )

        elif self.selection_method == "Channel":
            if not self.filter_channel:
                frappe.throw(
                    _("Channel is required for this selection method"),
                    title=_("Missing Channel")
                )

        elif self.selection_method == "Filter Query":
            if not self.filter_query:
                frappe.throw(
                    _("Filter Query is required for this selection method"),
                    title=_("Missing Filter Query")
                )
            # Validate JSON
            try:
                json.loads(self.filter_query)
            except json.JSONDecodeError:
                frappe.throw(
                    _("Filter Query must be valid JSON"),
                    title=_("Invalid Filter Query")
                )

    def validate_processing_settings(self):
        """Validate processing settings"""
        if self.batch_size is not None and self.batch_size < 1:
            frappe.throw(
                _("Batch size must be at least 1"),
                title=_("Invalid Batch Size")
            )

        if self.max_retries is not None and self.max_retries < 0:
            frappe.throw(
                _("Max retries cannot be negative"),
                title=_("Invalid Max Retries")
            )

        if self.auto_apply_threshold is not None:
            if self.auto_apply_threshold < 0 or self.auto_apply_threshold > 100:
                frappe.throw(
                    _("Auto-apply threshold must be between 0 and 100"),
                    title=_("Invalid Threshold")
                )

    def set_defaults(self):
        """Set default values"""
        if not self.correlation_id:
            self.correlation_id = str(uuid.uuid4())

        if not self.created_by:
            self.created_by = frappe.session.user

        # Set default model based on provider
        if not self.ai_model and self.ai_provider:
            default_models = {
                "Anthropic": "claude-3-sonnet-20240229",
                "OpenAI": "gpt-4-turbo-preview",
                "Google Gemini": "gemini-pro",
                "Azure OpenAI": "gpt-4",
                "AWS Bedrock": "anthropic.claude-3-sonnet"
            }
            self.ai_model = default_models.get(self.ai_provider, "")

    def before_submit(self):
        """Prepare job for execution before submit"""
        # Calculate total products to process
        self.total_products = self.get_product_count()

        if self.total_products == 0:
            frappe.throw(
                _("No products match the selection criteria"),
                title=_("No Products Found")
            )

        # Calculate total batches
        batch_size = self.batch_size or 10
        self.total_batches = (self.total_products + batch_size - 1) // batch_size

        # Set status to Queued
        self.status = "Queued"
        self.queue_position = self.get_queue_position()

    def on_submit(self):
        """Queue job for processing after submit"""
        # Enqueue the job for background processing
        if self.scheduled_at and self.scheduled_at > now_datetime():
            # Schedule for later
            frappe.enqueue(
                "frappe_pim.pim.tasks.ai_enrichment.process_enrichment_job",
                queue="long",
                job=self.name,
                at_front=self.priority in ("High", "Critical"),
                enqueue_after_commit=True,
                at=self.scheduled_at
            )
        else:
            # Queue immediately
            frappe.enqueue(
                "frappe_pim.pim.tasks.ai_enrichment.process_enrichment_job",
                queue="long",
                job=self.name,
                at_front=self.priority in ("High", "Critical"),
                enqueue_after_commit=True
            )

        # Create PIM Event
        self.create_pim_event("Created", f"AI Enrichment Job '{self.job_name}' queued for processing")

    def on_cancel(self):
        """Handle job cancellation"""
        self.db_set("status", "Cancelled")
        self.create_pim_event("Cancelled", f"AI Enrichment Job '{self.job_name}' was cancelled")

    def get_product_count(self) -> int:
        """Get count of products to process based on selection method"""
        if self.selection_method == "Manual Selection":
            return len(self.products) if self.products else 0

        elif self.selection_method == "All Products":
            filters = {"docstatus": 0}
            if not self.include_variants:
                filters["is_variant"] = 0
            return frappe.db.count("Product Master", filters)

        elif self.selection_method == "Product Family":
            return self._get_family_product_count()

        elif self.selection_method == "Product Category":
            return self._get_category_product_count()

        elif self.selection_method == "Channel":
            return self._get_channel_product_count()

        elif self.selection_method == "Filter Query":
            return self._get_filtered_product_count()

        return 0

    def _get_family_product_count(self) -> int:
        """Get count of products in family and sub-families"""
        try:
            # Get family and all descendants
            families = [self.filter_product_family]
            descendants = frappe.get_all(
                "Product Family",
                filters={"parent_family": self.filter_product_family},
                pluck="name"
            )
            families.extend(descendants)

            filters = {"product_family": ["in", families]}
            if not self.include_variants:
                filters["is_variant"] = 0

            return frappe.db.count("Product Master", filters)
        except Exception:
            return 0

    def _get_category_product_count(self) -> int:
        """Get count of products in category"""
        try:
            return frappe.db.count(
                "Product Classification",
                filters={"category": self.filter_product_category}
            )
        except Exception:
            return 0

    def _get_channel_product_count(self) -> int:
        """Get count of products assigned to channel"""
        try:
            return frappe.db.count(
                "Product Channel",
                filters={"channel": self.filter_channel}
            )
        except Exception:
            return 0

    def _get_filtered_product_count(self) -> int:
        """Get count of products matching filter query"""
        try:
            filters = json.loads(self.filter_query)
            if not self.include_variants:
                filters["is_variant"] = 0
            return frappe.db.count("Product Master", filters)
        except Exception:
            return 0

    def get_queue_position(self) -> int:
        """Get position in processing queue"""
        queued_count = frappe.db.count(
            "AI Enrichment Job",
            filters={
                "status": "Queued",
                "docstatus": 1,
                "creation": ["<", self.creation]
            }
        )
        return queued_count + 1

    def get_products_to_process(self) -> List[str]:
        """Get list of product names to process"""
        products = []

        if self.selection_method == "Manual Selection":
            products = [p.product for p in self.products]

        elif self.selection_method == "All Products":
            filters = {}
            if not self.include_variants:
                filters["is_variant"] = 0
            products = frappe.get_all("Product Master", filters=filters, pluck="name")

        elif self.selection_method == "Product Family":
            products = self._get_family_products()

        elif self.selection_method == "Product Category":
            products = self._get_category_products()

        elif self.selection_method == "Channel":
            products = self._get_channel_products()

        elif self.selection_method == "Filter Query":
            products = self._get_filtered_products()

        # Apply max_products limit
        if self.max_products and self.max_products > 0:
            products = products[:self.max_products]

        return products

    def _get_family_products(self) -> List[str]:
        """Get products in family and sub-families"""
        families = [self.filter_product_family]
        descendants = frappe.get_all(
            "Product Family",
            filters={"parent_family": self.filter_product_family},
            pluck="name"
        )
        families.extend(descendants)

        filters = {"product_family": ["in", families]}
        if not self.include_variants:
            filters["is_variant"] = 0

        return frappe.get_all("Product Master", filters=filters, pluck="name")

    def _get_category_products(self) -> List[str]:
        """Get products in category"""
        return frappe.get_all(
            "Product Classification",
            filters={"category": self.filter_product_category},
            pluck="parent"
        )

    def _get_channel_products(self) -> List[str]:
        """Get products assigned to channel"""
        return frappe.get_all(
            "Product Channel",
            filters={"channel": self.filter_channel},
            pluck="parent"
        )

    def _get_filtered_products(self) -> List[str]:
        """Get products matching filter query"""
        filters = json.loads(self.filter_query)
        if not self.include_variants:
            filters["is_variant"] = 0
        return frappe.get_all("Product Master", filters=filters, pluck="name")

    def update_progress(
        self,
        processed: int = 0,
        successful: int = 0,
        failed: int = 0,
        skipped: int = 0,
        pending_approval: int = 0,
        current_batch: int = 0
    ):
        """Update job progress counters"""
        self.db_set({
            "processed_count": self.processed_count + processed,
            "successful_count": self.successful_count + successful,
            "failed_count": self.failed_count + failed,
            "skipped_count": self.skipped_count + skipped,
            "pending_approval_count": self.pending_approval_count + pending_approval,
            "current_batch": current_batch,
            "progress_percent": (
                ((self.processed_count + processed) / self.total_products * 100)
                if self.total_products > 0 else 0
            )
        })

    def update_token_usage(self, input_tokens: int = 0, output_tokens: int = 0):
        """Update token usage counters"""
        self.db_set({
            "input_tokens": self.input_tokens + input_tokens,
            "output_tokens": self.output_tokens + output_tokens,
            "total_tokens_used": self.total_tokens_used + input_tokens + output_tokens
        })

    def mark_started(self):
        """Mark job as started"""
        self.db_set({
            "status": "Processing",
            "started_at": now_datetime(),
            "worker_id": frappe.local.site
        })
        self.create_pim_event("Started", f"AI Enrichment Job '{self.job_name}' started processing")

    def mark_completed(self):
        """Mark job as completed"""
        completed_at = now_datetime()
        duration = (completed_at - self.started_at).total_seconds() if self.started_at else 0
        avg_time = duration / self.processed_count if self.processed_count > 0 else 0

        # Determine final status
        if self.failed_count == 0:
            status = "Completed"
        elif self.successful_count > 0:
            status = "Partially Completed"
        else:
            status = "Failed"

        # Estimate cost based on tokens and provider
        estimated_cost = self._estimate_cost()

        self.db_set({
            "status": status,
            "completed_at": completed_at,
            "duration_seconds": int(duration),
            "average_time_per_product": flt(avg_time, 2),
            "estimated_cost": estimated_cost,
            "cost_per_product": (
                estimated_cost / self.successful_count
                if self.successful_count > 0 else 0
            ),
            "progress_percent": 100
        })

        self.create_pim_event("Completed", f"AI Enrichment Job '{self.job_name}' completed with status: {status}")

        # Send notification if enabled
        if self.notify_on_completion:
            self.send_completion_notification()

    def mark_failed(self, error: str):
        """Mark job as failed"""
        self.db_set({
            "status": "Failed",
            "completed_at": now_datetime(),
            "last_error": error[:500] if error else None
        })
        self.create_pim_event("Failed", f"AI Enrichment Job '{self.job_name}' failed: {error[:200]}")

    def log_error(self, product: str, error: str, details: Optional[Dict] = None):
        """Log an error for a product"""
        error_entry = {
            "timestamp": str(now_datetime()),
            "product": product,
            "error": error,
            "details": details
        }

        try:
            error_log = json.loads(self.error_log or "[]")
        except (json.JSONDecodeError, TypeError):
            error_log = []

        error_log.append(error_entry)

        # Keep only last 100 errors
        if len(error_log) > 100:
            error_log = error_log[-100:]

        self.db_set({
            "error_log": json.dumps(error_log),
            "last_error": error[:500]
        })

    def log_processing(self, product: str, action: str, details: Optional[Dict] = None):
        """Log processing activity"""
        log_entry = {
            "timestamp": str(now_datetime()),
            "product": product,
            "action": action,
            "details": details
        }

        try:
            processing_log = json.loads(self.processing_log or "[]")
        except (json.JSONDecodeError, TypeError):
            processing_log = []

        processing_log.append(log_entry)

        # Keep only last 500 entries
        if len(processing_log) > 500:
            processing_log = processing_log[-500:]

        self.db_set("processing_log", json.dumps(processing_log))

    def _estimate_cost(self) -> float:
        """Estimate API cost based on token usage and provider"""
        # Approximate pricing per 1M tokens (as of 2024)
        pricing = {
            "Anthropic": {"input": 15.0, "output": 75.0},  # Claude 3 Sonnet
            "OpenAI": {"input": 10.0, "output": 30.0},     # GPT-4 Turbo
            "Google Gemini": {"input": 0.5, "output": 1.5}, # Gemini Pro
            "Azure OpenAI": {"input": 10.0, "output": 30.0},
            "AWS Bedrock": {"input": 15.0, "output": 75.0}
        }

        rates = pricing.get(self.ai_provider, {"input": 10.0, "output": 30.0})
        input_cost = (self.input_tokens / 1_000_000) * rates["input"]
        output_cost = (self.output_tokens / 1_000_000) * rates["output"]

        return round(input_cost + output_cost, 4)

    def send_completion_notification(self):
        """Send notification on job completion"""
        if not self.notification_users:
            return

        users = [u.strip() for u in self.notification_users.split(",") if u.strip()]

        for user in users:
            try:
                frappe.sendmail(
                    recipients=[user],
                    subject=_("AI Enrichment Job {0} - {1}").format(self.name, self.status),
                    message=self._get_notification_message(),
                    now=True
                )
            except Exception as e:
                frappe.log_error(f"Failed to send notification to {user}: {str(e)}")

    def _get_notification_message(self) -> str:
        """Generate notification email message"""
        return f"""
        <h3>AI Enrichment Job: {self.job_name}</h3>
        <p><strong>Status:</strong> {self.status}</p>
        <p><strong>Type:</strong> {self.job_type}</p>

        <h4>Results:</h4>
        <ul>
            <li>Total Products: {self.total_products}</li>
            <li>Processed: {self.processed_count}</li>
            <li>Successful: {self.successful_count}</li>
            <li>Failed: {self.failed_count}</li>
            <li>Skipped: {self.skipped_count}</li>
            <li>Pending Approval: {self.pending_approval_count}</li>
        </ul>

        <h4>Execution:</h4>
        <ul>
            <li>Duration: {self.duration_seconds or 0} seconds</li>
            <li>Avg Time/Product: {self.average_time_per_product or 0:.2f}s</li>
            <li>Tokens Used: {self.total_tokens_used or 0}</li>
            <li>Estimated Cost: ${self.estimated_cost or 0:.4f}</li>
        </ul>

        <p><a href="{frappe.utils.get_url()}/app/ai-enrichment-job/{self.name}">View Job Details</a></p>
        """

    def create_pim_event(self, event_type: str, summary: str):
        """Create a PIM Event for this job"""
        try:
            frappe.get_doc({
                "doctype": "PIM Event",
                "event_type": event_type,
                "event_category": "AI",
                "event_timestamp": now_datetime(),
                "reference_doctype": "AI Enrichment Job",
                "reference_docname": self.name,
                "triggered_by": frappe.session.user,
                "trigger_method": "System",
                "event_summary": summary,
                "correlation_id": self.correlation_id
            }).insert(ignore_permissions=True)
        except Exception:
            pass  # Don't fail if PIM Event creation fails

    @frappe.whitelist()
    def retry_failed(self):
        """Retry failed products in this job"""
        if self.status not in ("Completed", "Partially Completed", "Failed"):
            frappe.throw(_("Can only retry jobs that have completed or failed"))

        # Create a new job with failed products
        failed_products = self._get_failed_products()

        if not failed_products:
            frappe.throw(_("No failed products to retry"))

        new_job = frappe.copy_doc(self)
        new_job.name = None
        new_job.status = "Draft"
        new_job.selection_method = "Manual Selection"
        new_job.products = []

        for product in failed_products:
            new_job.append("products", {"product": product})

        # Reset counters
        new_job.total_products = 0
        new_job.processed_count = 0
        new_job.successful_count = 0
        new_job.failed_count = 0
        new_job.skipped_count = 0
        new_job.progress_percent = 0
        new_job.pending_approval_count = 0
        new_job.started_at = None
        new_job.completed_at = None
        new_job.duration_seconds = None
        new_job.average_time_per_product = None
        new_job.total_tokens_used = 0
        new_job.input_tokens = 0
        new_job.output_tokens = 0
        new_job.estimated_cost = 0
        new_job.cost_per_product = 0
        new_job.error_log = None
        new_job.processing_log = None
        new_job.last_error = None
        new_job.correlation_id = str(uuid.uuid4())

        new_job.insert()

        return {"job": new_job.name, "products": len(failed_products)}

    def _get_failed_products(self) -> List[str]:
        """Get list of products that failed processing"""
        try:
            error_log = json.loads(self.error_log or "[]")
            return list(set([e.get("product") for e in error_log if e.get("product")]))
        except (json.JSONDecodeError, TypeError):
            return []

    @frappe.whitelist()
    def cancel_processing(self):
        """Cancel a running job"""
        if self.status != "Processing":
            frappe.throw(_("Can only cancel jobs that are currently processing"))

        self.db_set("status", "Cancelled")
        self.create_pim_event("Cancelled", f"AI Enrichment Job '{self.job_name}' was cancelled during processing")

        return {"status": "Cancelled"}


# API Functions

@frappe.whitelist()
def get_enrichment_jobs(
    status: Optional[str] = None,
    job_type: Optional[str] = None,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """Get list of enrichment jobs

    Args:
        status: Filter by status
        job_type: Filter by job type
        limit: Maximum results to return

    Returns:
        List of job summaries
    """
    filters = {"docstatus": ["!=", 2]}  # Exclude cancelled

    if status:
        filters["status"] = status
    if job_type:
        filters["job_type"] = job_type

    return frappe.get_all(
        "AI Enrichment Job",
        filters=filters,
        fields=[
            "name", "job_name", "job_type", "status", "priority",
            "ai_provider", "total_products", "processed_count",
            "successful_count", "failed_count", "progress_percent",
            "created_by", "creation", "started_at", "completed_at"
        ],
        order_by="creation desc",
        limit_page_length=limit
    )


@frappe.whitelist()
def get_job_statistics() -> Dict[str, Any]:
    """Get overall AI enrichment job statistics

    Returns:
        Dict with job statistics
    """
    stats = {
        "total_jobs": frappe.db.count("AI Enrichment Job"),
        "queued": frappe.db.count("AI Enrichment Job", {"status": "Queued", "docstatus": 1}),
        "processing": frappe.db.count("AI Enrichment Job", {"status": "Processing", "docstatus": 1}),
        "completed": frappe.db.count("AI Enrichment Job", {"status": "Completed", "docstatus": 1}),
        "failed": frappe.db.count("AI Enrichment Job", {"status": "Failed", "docstatus": 1}),
        "products_enriched": 0,
        "total_tokens": 0,
        "total_cost": 0
    }

    # Aggregate statistics
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

    return stats


@frappe.whitelist()
def create_enrichment_job(
    job_name: str,
    job_type: str,
    products: Optional[str] = None,
    ai_provider: str = "Anthropic",
    prompt_template: Optional[str] = None,
    custom_prompt: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """Create a new AI enrichment job

    Args:
        job_name: Name for the job
        job_type: Type of enrichment
        products: JSON list of product names (for manual selection)
        ai_provider: AI provider to use
        prompt_template: Prompt template to use
        custom_prompt: Custom prompt text
        **kwargs: Additional job settings

    Returns:
        Dict with new job details
    """
    job = frappe.new_doc("AI Enrichment Job")
    job.job_name = job_name
    job.job_type = job_type
    job.ai_provider = ai_provider
    job.prompt_template = prompt_template
    job.custom_prompt = custom_prompt

    # Handle product selection
    if products:
        product_list = json.loads(products) if isinstance(products, str) else products
        job.selection_method = "Manual Selection"
        for product in product_list:
            job.append("products", {"product": product})
    else:
        job.selection_method = kwargs.get("selection_method", "All Products")

    # Apply additional settings
    for key, value in kwargs.items():
        if hasattr(job, key):
            setattr(job, key, value)

    job.insert()

    return {
        "job": job.name,
        "status": job.status,
        "total_products": job.get_product_count()
    }


@frappe.whitelist()
def submit_job(job: str) -> Dict[str, Any]:
    """Submit an enrichment job for processing

    Args:
        job: Job name

    Returns:
        Dict with submission status
    """
    doc = frappe.get_doc("AI Enrichment Job", job)

    if doc.docstatus != 0:
        frappe.throw(_("Job has already been submitted"))

    doc.submit()

    return {
        "job": job,
        "status": doc.status,
        "total_products": doc.total_products,
        "queue_position": doc.queue_position
    }


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


@frappe.whitelist()
def get_ai_providers() -> List[Dict[str, str]]:
    """Get available AI providers

    Returns:
        List of AI provider options
    """
    return [
        {"value": "Anthropic", "label": _("Anthropic (Claude)")},
        {"value": "OpenAI", "label": _("OpenAI (GPT)")},
        {"value": "Google Gemini", "label": _("Google Gemini")},
        {"value": "Azure OpenAI", "label": _("Azure OpenAI")},
        {"value": "AWS Bedrock", "label": _("AWS Bedrock")},
        {"value": "Custom", "label": _("Custom Provider")}
    ]
