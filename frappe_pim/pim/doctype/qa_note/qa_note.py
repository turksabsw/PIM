# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

"""QA Note DocType for storing Q&A agent responses.

This module provides the QA Note DocType controller for managing AI-generated
and manual Q&A responses related to products.
"""


def get_qa_note_controller():
    """Get the QA Note Document class.

    Returns:
        Document: The QA Note Document class.
    """
    import frappe
    from frappe.model.document import Document
    from frappe.utils import now, today, getdate

    class QANote(Document):
        """QA Note Document controller.

        Handles validation, status updates, and usage tracking for Q&A notes.
        """

        def validate(self):
            """Validate the QA Note before saving."""
            self.validate_dates()
            self.validate_product_links()
            self.validate_verification()
            self.validate_ai_fields()
            self.set_defaults()

        def validate_dates(self):
            """Validate date fields."""
            if self.valid_from and self.valid_to:
                if getdate(self.valid_from) > getdate(self.valid_to):
                    frappe.throw("Valid From date cannot be after Valid To date")

            if self.valid_to and getdate(self.valid_to) < getdate(today()):
                # Auto-update status to Outdated if validity period has passed
                if self.status not in ("Outdated", "Archived"):
                    self.status = "Outdated"

        def validate_product_links(self):
            """Validate product link relationships."""
            # If variant is specified, product should also be specified
            if self.linked_variant and not self.linked_product:
                # Try to auto-populate product from variant
                variant_doc = frappe.get_doc("Product Variant", self.linked_variant)
                if variant_doc.product:
                    self.linked_product = variant_doc.product
                else:
                    frappe.throw("Product must be specified when linking to a variant")

            # If both product and family are specified, ensure consistency
            if self.linked_product and self.linked_product_family:
                product_doc = frappe.get_doc("Product Master", self.linked_product)
                if product_doc.product_family != self.linked_product_family:
                    frappe.msgprint(
                        f"Note: Product Family ({self.linked_product_family}) does not match "
                        f"the product's family ({product_doc.product_family})",
                        indicator="orange"
                    )

        def validate_verification(self):
            """Validate verification fields."""
            if self.is_verified:
                if not self.verified_by:
                    self.verified_by = frappe.session.user
                if not self.verified_date:
                    self.verified_date = today()
                # Auto-update status to Verified if currently Draft or Active
                if self.status in ("Draft", "Active"):
                    self.status = "Verified"
            else:
                # Clear verification fields if not verified
                self.verified_by = None
                self.verified_date = None

        def validate_ai_fields(self):
            """Validate AI-related fields."""
            if self.generation_method == "Manual":
                # Clear AI-specific fields for manual entries
                pass  # Keep values for reference if they exist

            if self.ai_confidence:
                if self.ai_confidence < 0:
                    self.ai_confidence = 0
                elif self.ai_confidence > 100:
                    self.ai_confidence = 100

            if self.tokens_used and self.tokens_used < 0:
                self.tokens_used = 0

            if self.generation_time and self.generation_time < 0:
                self.generation_time = 0

        def set_defaults(self):
            """Set default values."""
            if not self.asked_date:
                self.asked_date = now()

            if not self.language:
                # Try to get default language from site settings
                self.language = frappe.db.get_single_value("System Settings", "language") or "en"

            # Auto-generate title if not provided
            if not self.note_title and self.question:
                # Use first 50 chars of question as title
                self.note_title = self.question[:50] + ("..." if len(self.question) > 50 else "")

        def on_update(self):
            """Actions after saving."""
            self.clear_cache()

        def after_insert(self):
            """Actions after inserting a new QA Note."""
            self.clear_cache()

        def on_trash(self):
            """Actions before deleting."""
            self.clear_cache()

        def clear_cache(self):
            """Clear related caches."""
            frappe.cache().hdel("qa_notes_cache", self.linked_product or "global")
            if self.linked_product_family:
                frappe.cache().hdel("qa_notes_cache", f"family_{self.linked_product_family}")

        def increment_view_count(self):
            """Increment the view count."""
            self.db_set("view_count", (self.view_count or 0) + 1)
            self.db_set("last_viewed", now())

        def increment_helpful(self):
            """Increment the helpful count."""
            self.db_set("helpful_count", (self.helpful_count or 0) + 1)
            self.db_set("feedback_count", (self.feedback_count or 0) + 1)

        def increment_not_helpful(self):
            """Increment the not helpful count."""
            self.db_set("not_helpful_count", (self.not_helpful_count or 0) + 1)
            self.db_set("feedback_count", (self.feedback_count or 0) + 1)

        def mark_reviewed(self, notes=None):
            """Mark the Q&A as reviewed.

            Args:
                notes: Optional notes about the review.
            """
            self.db_set("last_reviewed", today())
            if notes:
                current_notes = self.internal_notes or ""
                updated_notes = f"{current_notes}\n\n[{today()}] Review: {notes}" if current_notes else f"[{today()}] Review: {notes}"
                self.db_set("internal_notes", updated_notes)

        def duplicate(self, new_product=None):
            """Create a duplicate of this QA Note.

            Args:
                new_product: Optional new product to link to.

            Returns:
                str: Name of the new QA Note.
            """
            new_doc = frappe.copy_doc(self)
            new_doc.status = "Draft"
            new_doc.is_verified = 0
            new_doc.verified_by = None
            new_doc.verified_date = None
            new_doc.view_count = 0
            new_doc.reuse_count = 0
            new_doc.export_count = 0
            new_doc.helpful_count = 0
            new_doc.not_helpful_count = 0
            new_doc.feedback_count = 0
            new_doc.last_viewed = None

            if new_product:
                new_doc.linked_product = new_product
                new_doc.linked_variant = None

            new_doc.insert()

            # Increment reuse count on original
            self.db_set("reuse_count", (self.reuse_count or 0) + 1)

            return new_doc.name

    return QANote


# Create the class for Frappe to use
QANote = get_qa_note_controller()


# API Functions
@__import__("frappe").whitelist()
def get_qa_notes(filters=None, limit=20, offset=0, order_by="modified desc"):
    """Get QA Notes with optional filtering.

    Args:
        filters: Dict of field filters.
        limit: Maximum number of records to return.
        offset: Number of records to skip.
        order_by: Field to order by.

    Returns:
        list: List of QA Note records.
    """
    import frappe
    from frappe.utils import cint

    try:
        filters = filters or {}
        limit = cint(limit)
        offset = cint(offset)

        qa_notes = frappe.get_all(
            "QA Note",
            filters=filters,
            fields=[
                "name", "note_title", "question", "answer_summary",
                "linked_product", "linked_product_family", "status",
                "question_type", "generation_method", "is_verified",
                "quality_rating", "view_count", "helpful_count",
                "created", "modified"
            ],
            order_by=order_by,
            limit_page_length=limit,
            start=offset
        )

        return qa_notes

    except Exception as e:
        frappe.log_error(
            message=f"Error fetching QA Notes: {str(e)}",
            title="QA Note API Error"
        )
        return []


@__import__("frappe").whitelist()
def get_product_qa_notes(product, include_family=True, status=None, limit=50):
    """Get QA Notes for a specific product.

    Args:
        product: Product Master name.
        include_family: Include family-level Q&As.
        status: Filter by status (optional).
        limit: Maximum number of records.

    Returns:
        list: List of QA Notes for the product.
    """
    import frappe
    from frappe.utils import cint

    try:
        limit = cint(limit)
        filters = [["linked_product", "=", product]]

        if status:
            filters.append(["status", "=", status])

        qa_notes = frappe.get_all(
            "QA Note",
            filters=filters,
            fields=[
                "name", "note_title", "question", "answer", "answer_summary",
                "question_type", "generation_method", "is_verified",
                "quality_rating", "view_count", "helpful_count",
                "created", "modified"
            ],
            order_by="is_featured desc, helpful_count desc, modified desc",
            limit_page_length=limit
        )

        # Include family-level Q&As
        if include_family:
            product_doc = frappe.get_doc("Product Master", product)
            if product_doc.product_family:
                family_filters = [
                    ["linked_product_family", "=", product_doc.product_family],
                    ["linked_product", "is", "not set"]
                ]
                if status:
                    family_filters.append(["status", "=", status])

                family_qa_notes = frappe.get_all(
                    "QA Note",
                    filters=family_filters,
                    fields=[
                        "name", "note_title", "question", "answer", "answer_summary",
                        "question_type", "generation_method", "is_verified",
                        "quality_rating", "view_count", "helpful_count",
                        "created", "modified"
                    ],
                    order_by="is_featured desc, helpful_count desc, modified desc",
                    limit_page_length=limit
                )

                # Mark family-level Q&As
                for qa in family_qa_notes:
                    qa["is_family_level"] = True

                qa_notes.extend(family_qa_notes)

        return qa_notes

    except Exception as e:
        frappe.log_error(
            message=f"Error fetching product QA Notes: {str(e)}",
            title="QA Note API Error"
        )
        return []


@__import__("frappe").whitelist()
def search_qa_notes(query, filters=None, limit=20):
    """Search QA Notes by question or answer content.

    Args:
        query: Search query string.
        filters: Additional filters.
        limit: Maximum number of results.

    Returns:
        list: List of matching QA Notes.
    """
    import frappe
    from frappe.utils import cint

    try:
        limit = cint(limit)
        search_filters = filters or {}

        qa_notes = frappe.get_all(
            "QA Note",
            filters=search_filters,
            or_filters=[
                ["question", "like", f"%{query}%"],
                ["answer", "like", f"%{query}%"],
                ["note_title", "like", f"%{query}%"],
                ["tags", "like", f"%{query}%"]
            ],
            fields=[
                "name", "note_title", "question", "answer_summary",
                "linked_product", "status", "is_verified",
                "helpful_count", "modified"
            ],
            order_by="is_featured desc, helpful_count desc, modified desc",
            limit_page_length=limit
        )

        return qa_notes

    except Exception as e:
        frappe.log_error(
            message=f"Error searching QA Notes: {str(e)}",
            title="QA Note API Error"
        )
        return []


@__import__("frappe").whitelist()
def get_qa_statistics(product=None, product_family=None):
    """Get statistics about QA Notes.

    Args:
        product: Optional product filter.
        product_family: Optional product family filter.

    Returns:
        dict: Statistics about QA Notes.
    """
    import frappe

    try:
        filters = {}
        if product:
            filters["linked_product"] = product
        if product_family:
            filters["linked_product_family"] = product_family

        total = frappe.db.count("QA Note", filters=filters)

        # Count by status
        status_counts = {}
        for status in ["Draft", "Active", "Verified", "Outdated", "Archived"]:
            count_filters = {**filters, "status": status}
            status_counts[status.lower()] = frappe.db.count("QA Note", filters=count_filters)

        # Count by generation method
        method_counts = {}
        for method in ["Manual", "AI", "Hybrid", "Imported"]:
            count_filters = {**filters, "generation_method": method}
            method_counts[method.lower()] = frappe.db.count("QA Note", filters=count_filters)

        # Verified count
        verified_count = frappe.db.count("QA Note", filters={**filters, "is_verified": 1})

        # Featured count
        featured_count = frappe.db.count("QA Note", filters={**filters, "is_featured": 1})

        # Average stats
        avg_stats = frappe.db.sql("""
            SELECT
                AVG(view_count) as avg_views,
                AVG(helpful_count) as avg_helpful,
                AVG(quality_rating) as avg_rating,
                SUM(view_count) as total_views,
                SUM(helpful_count) as total_helpful
            FROM `tabQA Note`
            WHERE 1=1
            {product_filter}
            {family_filter}
        """.format(
            product_filter=f"AND linked_product = '{product}'" if product else "",
            family_filter=f"AND linked_product_family = '{product_family}'" if product_family else ""
        ), as_dict=True)

        return {
            "total": total,
            "by_status": status_counts,
            "by_generation_method": method_counts,
            "verified_count": verified_count,
            "featured_count": featured_count,
            "verified_percentage": round((verified_count / total * 100) if total > 0 else 0, 1),
            "avg_views": round(avg_stats[0].get("avg_views") or 0, 1) if avg_stats else 0,
            "avg_helpful": round(avg_stats[0].get("avg_helpful") or 0, 1) if avg_stats else 0,
            "avg_rating": round(avg_stats[0].get("avg_rating") or 0, 1) if avg_stats else 0,
            "total_views": avg_stats[0].get("total_views") or 0 if avg_stats else 0,
            "total_helpful": avg_stats[0].get("total_helpful") or 0 if avg_stats else 0
        }

    except Exception as e:
        frappe.log_error(
            message=f"Error getting QA statistics: {str(e)}",
            title="QA Note API Error"
        )
        return {"total": 0, "error": str(e)}


@__import__("frappe").whitelist()
def record_feedback(qa_note, is_helpful):
    """Record user feedback on a QA Note.

    Args:
        qa_note: Name of the QA Note.
        is_helpful: Boolean indicating if the answer was helpful.

    Returns:
        dict: Updated feedback counts.
    """
    import frappe
    from frappe.utils import cint

    try:
        is_helpful = cint(is_helpful)
        doc = frappe.get_doc("QA Note", qa_note)

        if is_helpful:
            doc.increment_helpful()
        else:
            doc.increment_not_helpful()

        return {
            "helpful_count": doc.helpful_count,
            "not_helpful_count": doc.not_helpful_count,
            "feedback_count": doc.feedback_count
        }

    except Exception as e:
        frappe.log_error(
            message=f"Error recording feedback: {str(e)}",
            title="QA Note API Error"
        )
        return {"error": str(e)}


@__import__("frappe").whitelist()
def record_view(qa_note):
    """Record a view of a QA Note.

    Args:
        qa_note: Name of the QA Note.

    Returns:
        dict: Updated view count.
    """
    import frappe

    try:
        doc = frappe.get_doc("QA Note", qa_note)
        doc.increment_view_count()
        return {"view_count": doc.view_count}

    except Exception as e:
        frappe.log_error(
            message=f"Error recording view: {str(e)}",
            title="QA Note API Error"
        )
        return {"error": str(e)}


@__import__("frappe").whitelist()
def get_featured_qa_notes(product=None, limit=10):
    """Get featured QA Notes.

    Args:
        product: Optional product filter.
        limit: Maximum number of results.

    Returns:
        list: List of featured QA Notes.
    """
    import frappe
    from frappe.utils import cint

    try:
        limit = cint(limit)
        filters = {"is_featured": 1, "status": ["in", ["Active", "Verified"]]}

        if product:
            filters["linked_product"] = product

        qa_notes = frappe.get_all(
            "QA Note",
            filters=filters,
            fields=[
                "name", "note_title", "question", "answer_summary",
                "linked_product", "quality_rating", "helpful_count",
                "modified"
            ],
            order_by="helpful_count desc, modified desc",
            limit_page_length=limit
        )

        return qa_notes

    except Exception as e:
        frappe.log_error(
            message=f"Error fetching featured QA Notes: {str(e)}",
            title="QA Note API Error"
        )
        return []


@__import__("frappe").whitelist()
def get_qa_notes_needing_review(days=30, limit=50):
    """Get QA Notes that need review.

    Args:
        days: Days since last review to consider stale.
        limit: Maximum number of results.

    Returns:
        list: List of QA Notes needing review.
    """
    import frappe
    from frappe.utils import cint, add_days, today, getdate

    try:
        limit = cint(limit)
        days = cint(days)
        cutoff_date = add_days(today(), -days)

        qa_notes = frappe.get_all(
            "QA Note",
            filters=[
                ["status", "not in", ["Archived", "Outdated"]],
                ["review_date", "<=", today()]
            ],
            or_filters=[
                ["last_reviewed", "is", "not set"],
                ["last_reviewed", "<", cutoff_date]
            ],
            fields=[
                "name", "note_title", "linked_product",
                "last_reviewed", "review_date", "status",
                "is_verified", "modified"
            ],
            order_by="review_date asc, modified asc",
            limit_page_length=limit
        )

        return qa_notes

    except Exception as e:
        frappe.log_error(
            message=f"Error fetching QA Notes needing review: {str(e)}",
            title="QA Note API Error"
        )
        return []


@__import__("frappe").whitelist()
def bulk_update_status(qa_notes, new_status):
    """Bulk update status for multiple QA Notes.

    Args:
        qa_notes: List of QA Note names or comma-separated string.
        new_status: New status to set.

    Returns:
        dict: Summary of updates.
    """
    import frappe
    import json

    try:
        if isinstance(qa_notes, str):
            try:
                qa_notes = json.loads(qa_notes)
            except json.JSONDecodeError:
                qa_notes = [n.strip() for n in qa_notes.split(",")]

        valid_statuses = ["Draft", "Active", "Verified", "Outdated", "Archived"]
        if new_status not in valid_statuses:
            frappe.throw(f"Invalid status: {new_status}. Must be one of {valid_statuses}")

        updated = 0
        failed = 0

        for qa_note_name in qa_notes:
            try:
                frappe.db.set_value("QA Note", qa_note_name, "status", new_status)
                updated += 1
            except Exception:
                failed += 1

        frappe.db.commit()

        return {
            "updated": updated,
            "failed": failed,
            "total": len(qa_notes)
        }

    except Exception as e:
        frappe.log_error(
            message=f"Error bulk updating QA Notes: {str(e)}",
            title="QA Note API Error"
        )
        return {"error": str(e)}


@__import__("frappe").whitelist()
def create_qa_note_from_ai(
    product,
    question,
    answer,
    model=None,
    confidence=None,
    tokens=None,
    generation_time=None,
    context_used=None
):
    """Create a QA Note from AI generation.

    Args:
        product: Product Master name.
        question: The question asked.
        answer: The AI-generated answer.
        model: AI model used.
        confidence: AI confidence score.
        tokens: Tokens used.
        generation_time: Time taken to generate.
        context_used: Context/product data used.

    Returns:
        str: Name of the created QA Note.
    """
    import frappe
    from frappe.utils import now, cint, flt

    try:
        doc = frappe.new_doc("QA Note")
        doc.linked_product = product
        doc.question = question
        doc.answer = answer
        doc.generation_method = "AI"
        doc.status = "Draft"
        doc.visibility = "Internal"
        doc.asked_date = now()
        doc.generation_timestamp = now()

        if model:
            doc.ai_model = model
        if confidence:
            doc.ai_confidence = flt(confidence)
        if tokens:
            doc.tokens_used = cint(tokens)
        if generation_time:
            doc.generation_time = flt(generation_time)
        if context_used:
            doc.context_used = context_used

        # Auto-generate title
        doc.note_title = question[:50] + ("..." if len(question) > 50 else "")

        doc.insert(ignore_permissions=True)

        return doc.name

    except Exception as e:
        frappe.log_error(
            message=f"Error creating AI QA Note: {str(e)}",
            title="QA Note API Error"
        )
        return None
