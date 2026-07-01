"""
Product Feedback Controller
Manages customer comments, complaints, and suggestions for products
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class ProductFeedback(Document):
    def validate(self):
        self.validate_linked_product()
        self.validate_customer_info()
        self.validate_dates()
        self.set_product_family()

    def validate_linked_product(self):
        """Validate product and variant associations"""
        if self.linked_product_variant:
            # Verify variant belongs to the linked product
            variant_product = frappe.db.get_value(
                "Product Variant",
                self.linked_product_variant,
                "product_master"
            )
            if variant_product and variant_product != self.linked_product:
                frappe.throw(
                    _("Selected variant does not belong to the linked product"),
                    title=_("Invalid Variant")
                )

    def validate_customer_info(self):
        """Ensure at least some customer identification"""
        has_customer_info = (
            self.customer_name or
            self.customer_email or
            self.customer_phone or
            self.linked_customer
        )
        if not has_customer_info:
            frappe.msgprint(
                _("Consider adding customer contact information for follow-up."),
                indicator="blue",
                title=_("Missing Customer Info")
            )

    def validate_dates(self):
        """Validate date fields"""
        if self.purchase_date:
            from frappe.utils import getdate, today
            if getdate(self.purchase_date) > getdate(today()):
                frappe.throw(
                    _("Purchase date cannot be in the future"),
                    title=_("Invalid Date")
                )

        if self.follow_up_required and not self.follow_up_date:
            frappe.msgprint(
                _("Please set a follow-up date when follow-up is required."),
                indicator="orange",
                title=_("Follow-up Date Missing")
            )

    def set_product_family(self):
        """Auto-populate product family from linked product"""
        if self.linked_product and not self.linked_product_family:
            self.linked_product_family = frappe.db.get_value(
                "Product Master",
                self.linked_product,
                "product_family"
            )

    def before_save(self):
        """Prepare data before saving"""
        self.update_timestamps()
        self.set_priority_from_type()

    def update_timestamps(self):
        """Update date fields based on status changes"""
        if self.has_value_changed("status"):
            # Track first response
            if self.status == "Under Review" and not self.first_response_date:
                self.first_response_date = now_datetime()

            # Track resolution
            if self.status in ["Resolved", "Closed"] and not self.resolved_date:
                self.resolved_date = now_datetime()

    def set_priority_from_type(self):
        """Set default priority based on feedback type for complaints"""
        if not self.is_new():
            return

        if self.feedback_type == "Complaint" and self.priority == "Medium":
            self.priority = "High"
        elif self.feedback_type == "Bug Report" and self.priority == "Medium":
            self.priority = "High"

    def on_update(self):
        """Handle post-update actions"""
        self.update_product_feedback_count()
        self.invalidate_cache()

    def on_trash(self):
        """Cleanup before deletion"""
        self.update_product_feedback_count()
        self.invalidate_cache()

    def update_product_feedback_count(self):
        """Update feedback statistics on the linked product"""
        if self.linked_product:
            try:
                # Count feedback by type for this product
                counts = frappe.db.sql("""
                    SELECT
                        feedback_type,
                        COUNT(*) as count,
                        AVG(CASE WHEN rating IS NOT NULL THEN rating ELSE NULL END) as avg_rating
                    FROM `tabProduct Feedback`
                    WHERE linked_product = %s
                    GROUP BY feedback_type
                """, (self.linked_product,), as_dict=True)

                # This could be used to update denormalized fields on Product Master
                # For now, just clear cache
                frappe.cache().delete_key(f"pim:product_feedback_stats:{self.linked_product}")
            except Exception as e:
                frappe.log_error(
                    message=f"Error updating feedback count: {str(e)}",
                    title="PIM Feedback Count Error"
                )

    def invalidate_cache(self):
        """Clear relevant caches"""
        try:
            frappe.cache().delete_key(f"pim:product_feedback:{self.name}")
            if self.linked_product:
                frappe.cache().delete_key(f"pim:product_feedbacks:{self.linked_product}")
        except Exception:
            pass

    @frappe.whitelist()
    def assign_to_user(self, user):
        """Assign this feedback to a user for handling"""
        if not frappe.db.exists("User", user):
            frappe.throw(_("Invalid user: {0}").format(user))

        self.assigned_to = user
        if self.status == "New":
            self.status = "Under Review"
        self.save()

        return {
            "status": "success",
            "message": _("Feedback assigned to {0}").format(user)
        }

    @frappe.whitelist()
    def mark_resolved(self, resolution_notes=None, action_taken=None):
        """Mark the feedback as resolved"""
        if resolution_notes:
            self.resolution_notes = resolution_notes
        if action_taken:
            self.action_taken = action_taken

        self.status = "Resolved"
        self.resolved_date = now_datetime()
        self.save()

        return {
            "status": "success",
            "message": _("Feedback marked as resolved")
        }


@frappe.whitelist()
def get_product_feedbacks(
    product=None,
    product_family=None,
    status=None,
    feedback_type=None,
    sentiment=None,
    limit=20,
    offset=0
):
    """Get product feedbacks with optional filtering

    Args:
        product: Filter by linked product
        product_family: Filter by product family
        status: Filter by status
        feedback_type: Filter by feedback type
        sentiment: Filter by sentiment
        limit: Maximum results to return
        offset: Results offset for pagination
    """
    filters = {}
    if product:
        filters["linked_product"] = product
    if product_family:
        filters["linked_product_family"] = product_family
    if status:
        filters["status"] = status
    if feedback_type:
        filters["feedback_type"] = feedback_type
    if sentiment:
        filters["sentiment"] = sentiment

    return frappe.get_all(
        "Product Feedback",
        filters=filters,
        fields=[
            "name", "title", "feedback_type", "status", "priority",
            "linked_product", "linked_product_variant", "customer_name",
            "rating", "sentiment", "source_channel", "assigned_to",
            "creation", "modified"
        ],
        order_by="creation desc",
        limit_start=offset,
        limit_page_length=limit
    )


@frappe.whitelist()
def get_feedback_statistics(product=None, product_family=None):
    """Get feedback statistics for a product or product family

    Args:
        product: Product name to get statistics for
        product_family: Product family name to get statistics for
    """
    conditions = []
    params = []

    if product:
        conditions.append("linked_product = %s")
        params.append(product)
    elif product_family:
        conditions.append("linked_product_family = %s")
        params.append(product_family)
    else:
        frappe.throw(_("Please provide a product or product family"))

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    stats = frappe.db.sql(f"""
        SELECT
            COUNT(*) as total_feedback,
            SUM(CASE WHEN feedback_type = 'Complaint' THEN 1 ELSE 0 END) as complaints,
            SUM(CASE WHEN feedback_type = 'Suggestion' THEN 1 ELSE 0 END) as suggestions,
            SUM(CASE WHEN feedback_type = 'Review' THEN 1 ELSE 0 END) as reviews,
            SUM(CASE WHEN status = 'New' THEN 1 ELSE 0 END) as new_count,
            SUM(CASE WHEN status = 'Resolved' THEN 1 ELSE 0 END) as resolved_count,
            AVG(CASE WHEN rating IS NOT NULL THEN rating ELSE NULL END) as avg_rating,
            SUM(CASE WHEN sentiment = 'Positive' THEN 1 ELSE 0 END) as positive_count,
            SUM(CASE WHEN sentiment = 'Negative' THEN 1 ELSE 0 END) as negative_count
        FROM `tabProduct Feedback`
        WHERE {where_clause}
    """, params, as_dict=True)

    return stats[0] if stats else {}


@frappe.whitelist()
def get_pending_feedbacks(user=None, limit=10):
    """Get pending feedbacks requiring attention

    Args:
        user: Filter by assigned user (default: current user)
        limit: Maximum results to return
    """
    if user is None:
        user = frappe.session.user

    filters = {
        "status": ["in", ["New", "Under Review", "In Progress"]],
    }

    if user and user != "Administrator":
        filters["assigned_to"] = user

    return frappe.get_all(
        "Product Feedback",
        filters=filters,
        fields=[
            "name", "title", "feedback_type", "status", "priority",
            "linked_product", "customer_name", "response_due_date",
            "creation"
        ],
        order_by="priority desc, creation desc",
        limit_page_length=limit
    )


@frappe.whitelist()
def bulk_update_status(feedback_list, new_status, resolution_notes=None):
    """Update status for multiple feedback records

    Args:
        feedback_list: JSON string of list of feedback names
        new_status: New status to set
        resolution_notes: Optional notes for resolved status
    """
    import json

    if isinstance(feedback_list, str):
        feedback_list = json.loads(feedback_list)

    valid_statuses = ["New", "Under Review", "In Progress", "Resolved", "Closed", "Rejected"]
    if new_status not in valid_statuses:
        frappe.throw(_("Invalid status: {0}").format(new_status))

    updated = []
    for feedback_name in feedback_list:
        try:
            doc = frappe.get_doc("Product Feedback", feedback_name)
            doc.status = new_status
            if resolution_notes and new_status in ["Resolved", "Closed"]:
                doc.resolution_notes = resolution_notes
            doc.save()
            updated.append(feedback_name)
        except Exception as e:
            frappe.log_error(
                message=f"Error updating feedback {feedback_name}: {str(e)}",
                title="Bulk Status Update Error"
            )

    return {
        "status": "success",
        "updated_count": len(updated),
        "updated": updated
    }
