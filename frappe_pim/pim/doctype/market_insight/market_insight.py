"""
Market Insight Controller
Manages market trends and insights linked to products and categories
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today, now_datetime


class MarketInsight(Document):
    def validate(self):
        self.validate_dates()
        self.validate_links()
        self.validate_metrics()
        self.set_created_by()

    def validate_dates(self):
        """Validate date field consistency"""
        # Check valid_from is not after valid_to
        if self.valid_from and self.valid_to:
            if getdate(self.valid_from) > getdate(self.valid_to):
                frappe.throw(
                    _("Valid From date cannot be after Valid To date"),
                    title=_("Invalid Date Range")
                )

        # Check next_review_date is not in the past (for new documents)
        if self.is_new() and self.next_review_date:
            if getdate(self.next_review_date) < getdate(today()):
                frappe.msgprint(
                    _("Next Review Date is in the past. Consider updating it."),
                    indicator="orange",
                    title=_("Review Date Warning")
                )

    def validate_links(self):
        """Ensure at least one product/category link for non-draft insights"""
        if self.status != "Draft":
            has_link = (
                self.linked_product or
                self.linked_product_family or
                self.linked_category or
                self.linked_brand
            )
            if not has_link:
                frappe.msgprint(
                    _("Consider linking this insight to a product, family, category, or brand."),
                    indicator="blue",
                    title=_("Missing Link")
                )

    def validate_metrics(self):
        """Validate quantitative metrics"""
        # Market growth rate should be reasonable
        if self.market_growth_rate is not None:
            if self.market_growth_rate < -100:
                frappe.throw(
                    _("Market growth rate cannot be less than -100%"),
                    title=_("Invalid Growth Rate")
                )
            if self.market_growth_rate > 1000:
                frappe.msgprint(
                    _("Market growth rate seems unusually high. Please verify."),
                    indicator="orange",
                    title=_("Growth Rate Warning")
                )

    def set_created_by(self):
        """Set the created_by_user field"""
        if self.is_new() and not self.created_by_user:
            self.created_by_user = frappe.session.user

    def before_save(self):
        """Prepare data before saving"""
        self.update_timestamps()
        self.auto_set_status()

    def update_timestamps(self):
        """Update date fields based on status changes"""
        if self.has_value_changed("status"):
            # Track verification
            if self.status == "Active" and self.confidence_level == "Verified":
                self.last_verified_date = today()

    def auto_set_status(self):
        """Auto-adjust status based on dates if needed"""
        # Check if insight has expired
        if self.valid_to and self.status not in ["Draft", "Archived"]:
            if getdate(self.valid_to) < getdate(today()):
                frappe.msgprint(
                    _("This insight has passed its validity date. Consider archiving it."),
                    indicator="orange",
                    title=_("Expired Insight")
                )

    def on_update(self):
        """Handle post-update actions"""
        self.invalidate_cache()
        self.check_review_due()

    def on_trash(self):
        """Cleanup before deletion"""
        self.invalidate_cache()

    def invalidate_cache(self):
        """Clear relevant caches"""
        try:
            frappe.cache().delete_key(f"pim:market_insight:{self.name}")
            if self.linked_product:
                frappe.cache().delete_key(f"pim:product_insights:{self.linked_product}")
            if self.linked_product_family:
                frappe.cache().delete_key(f"pim:family_insights:{self.linked_product_family}")
            if self.linked_category:
                frappe.cache().delete_key(f"pim:category_insights:{self.linked_category}")
        except Exception:
            pass

    def check_review_due(self):
        """Check if review is due and notify"""
        if self.next_review_date and self.assigned_to:
            days_until_review = (getdate(self.next_review_date) - getdate(today())).days
            if days_until_review <= 7 and days_until_review >= 0:
                frappe.msgprint(
                    _("Review due in {0} days for this insight").format(days_until_review),
                    indicator="blue"
                )

    @frappe.whitelist()
    def assign_to_user(self, user):
        """Assign this insight to a user for monitoring"""
        if not frappe.db.exists("User", user):
            frappe.throw(_("Invalid user: {0}").format(user))

        self.assigned_to = user
        self.save()

        return {
            "status": "success",
            "message": _("Insight assigned to {0}").format(user)
        }

    @frappe.whitelist()
    def mark_verified(self):
        """Mark the insight as verified"""
        self.confidence_level = "Verified"
        self.last_verified_date = today()
        self.save()

        return {
            "status": "success",
            "message": _("Insight marked as verified")
        }

    @frappe.whitelist()
    def archive_insight(self, notes=None):
        """Archive the insight"""
        if notes:
            existing_notes = self.internal_notes or ""
            self.internal_notes = f"{existing_notes}\n\n[Archived on {today()}]\n{notes}"

        self.status = "Archived"
        self.save()

        return {
            "status": "success",
            "message": _("Insight archived successfully")
        }

    @frappe.whitelist()
    def update_action_status(self, action_status, action_notes=None):
        """Update the action status for this insight"""
        valid_statuses = ["Not Started", "In Progress", "Completed", "Deferred", "Not Applicable"]
        if action_status not in valid_statuses:
            frappe.throw(_("Invalid action status: {0}").format(action_status))

        self.action_status = action_status
        if action_notes:
            self.action_notes = action_notes
        self.save()

        return {
            "status": "success",
            "message": _("Action status updated to {0}").format(action_status)
        }


@frappe.whitelist()
def get_market_insights(
    product=None,
    product_family=None,
    category=None,
    brand=None,
    insight_type=None,
    status=None,
    impact_level=None,
    limit=20,
    offset=0
):
    """Get market insights with optional filtering

    Args:
        product: Filter by linked product
        product_family: Filter by product family
        category: Filter by linked category
        brand: Filter by linked brand
        insight_type: Filter by insight type
        status: Filter by status
        impact_level: Filter by impact level
        limit: Maximum results to return
        offset: Results offset for pagination
    """
    filters = {}
    if product:
        filters["linked_product"] = product
    if product_family:
        filters["linked_product_family"] = product_family
    if category:
        filters["linked_category"] = category
    if brand:
        filters["linked_brand"] = brand
    if insight_type:
        filters["insight_type"] = insight_type
    if status:
        filters["status"] = status
    if impact_level:
        filters["impact_level"] = impact_level

    return frappe.get_all(
        "Market Insight",
        filters=filters,
        fields=[
            "name", "title", "insight_type", "status", "impact_level",
            "linked_product", "linked_product_family", "linked_category",
            "trend_direction", "confidence_level", "valid_from", "valid_to",
            "action_priority", "action_status", "assigned_to",
            "creation", "modified"
        ],
        order_by="creation desc",
        limit_start=offset,
        limit_page_length=limit
    )


@frappe.whitelist()
def get_product_market_insights(product):
    """Get all market insights related to a specific product

    Args:
        product: Product name to get insights for
    """
    if not product:
        frappe.throw(_("Product is required"))

    # Get product family for broader insights
    product_family = frappe.db.get_value("Product Master", product, "product_family")

    # Get insights linked directly to product or its family
    conditions = ["status != 'Archived'"]
    params = []

    if product_family:
        conditions.append("(linked_product = %s OR linked_product_family = %s)")
        params.extend([product, product_family])
    else:
        conditions.append("linked_product = %s")
        params.append(product)

    where_clause = " AND ".join(conditions)

    return frappe.db.sql(f"""
        SELECT
            name, title, insight_type, status, impact_level,
            trend_direction, confidence_level, summary,
            action_priority, action_status, valid_from, valid_to,
            creation
        FROM `tabMarket Insight`
        WHERE {where_clause}
        ORDER BY impact_level DESC, creation DESC
    """, params, as_dict=True)


@frappe.whitelist()
def get_insight_statistics(
    product=None,
    product_family=None,
    category=None
):
    """Get market insight statistics

    Args:
        product: Product name to get statistics for
        product_family: Product family name to get statistics for
        category: Category name to get statistics for
    """
    conditions = ["status != 'Archived'"]
    params = []

    if product:
        conditions.append("linked_product = %s")
        params.append(product)
    elif product_family:
        conditions.append("linked_product_family = %s")
        params.append(product_family)
    elif category:
        conditions.append("linked_category = %s")
        params.append(category)

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    stats = frappe.db.sql(f"""
        SELECT
            COUNT(*) as total_insights,
            SUM(CASE WHEN insight_type = 'Market Trend' THEN 1 ELSE 0 END) as market_trends,
            SUM(CASE WHEN insight_type = 'Consumer Trend' THEN 1 ELSE 0 END) as consumer_trends,
            SUM(CASE WHEN insight_type = 'Competitive Intelligence' THEN 1 ELSE 0 END) as competitive_intel,
            SUM(CASE WHEN status = 'Active' THEN 1 ELSE 0 END) as active_count,
            SUM(CASE WHEN status = 'Actionable' THEN 1 ELSE 0 END) as actionable_count,
            SUM(CASE WHEN impact_level = 'High' THEN 1 ELSE 0 END) as high_impact,
            SUM(CASE WHEN impact_level = 'Critical' THEN 1 ELSE 0 END) as critical_impact,
            SUM(CASE WHEN trend_direction = 'Upward' THEN 1 ELSE 0 END) as upward_trends,
            SUM(CASE WHEN trend_direction = 'Downward' THEN 1 ELSE 0 END) as downward_trends
        FROM `tabMarket Insight`
        WHERE {where_clause}
    """, params, as_dict=True)

    return stats[0] if stats else {}


@frappe.whitelist()
def get_actionable_insights(user=None, limit=10):
    """Get actionable insights requiring attention

    Args:
        user: Filter by assigned user (default: current user)
        limit: Maximum results to return
    """
    if user is None:
        user = frappe.session.user

    filters = {
        "status": ["in", ["Actionable", "Active"]],
        "action_status": ["in", ["Not Started", "In Progress"]]
    }

    if user and user != "Administrator":
        filters["assigned_to"] = user

    return frappe.get_all(
        "Market Insight",
        filters=filters,
        fields=[
            "name", "title", "insight_type", "status", "impact_level",
            "linked_product", "linked_product_family", "linked_category",
            "action_priority", "action_status", "next_review_date",
            "creation"
        ],
        order_by="FIELD(impact_level, 'Critical', 'High', 'Medium', 'Low'), creation desc",
        limit_page_length=limit
    )


@frappe.whitelist()
def get_insights_due_for_review(days_ahead=7, limit=20):
    """Get insights due for review within specified days

    Args:
        days_ahead: Number of days to look ahead (default: 7)
        limit: Maximum results to return
    """
    from frappe.utils import add_days

    review_date_limit = add_days(today(), days_ahead)

    return frappe.get_all(
        "Market Insight",
        filters={
            "status": ["not in", ["Draft", "Archived"]],
            "next_review_date": ["<=", review_date_limit],
            "next_review_date": [">=", today()]
        },
        fields=[
            "name", "title", "insight_type", "status", "impact_level",
            "next_review_date", "assigned_to", "confidence_level",
            "linked_product", "linked_product_family"
        ],
        order_by="next_review_date asc",
        limit_page_length=limit
    )


@frappe.whitelist()
def get_high_impact_insights(limit=10):
    """Get high and critical impact insights

    Args:
        limit: Maximum results to return
    """
    return frappe.get_all(
        "Market Insight",
        filters={
            "status": ["not in", ["Draft", "Archived"]],
            "impact_level": ["in", ["High", "Critical"]]
        },
        fields=[
            "name", "title", "insight_type", "status", "impact_level",
            "trend_direction", "action_priority", "action_status",
            "linked_product", "linked_product_family", "linked_category",
            "potential_opportunities", "potential_threats",
            "creation"
        ],
        order_by="FIELD(impact_level, 'Critical', 'High'), creation desc",
        limit_page_length=limit
    )


@frappe.whitelist()
def bulk_update_status(insight_list, new_status, notes=None):
    """Update status for multiple insight records

    Args:
        insight_list: JSON string of list of insight names
        new_status: New status to set
        notes: Optional notes for the status change
    """
    import json

    if isinstance(insight_list, str):
        insight_list = json.loads(insight_list)

    valid_statuses = ["Draft", "Active", "Under Review", "Actionable", "Monitoring", "Archived"]
    if new_status not in valid_statuses:
        frappe.throw(_("Invalid status: {0}").format(new_status))

    updated = []
    for insight_name in insight_list:
        try:
            doc = frappe.get_doc("Market Insight", insight_name)
            doc.status = new_status
            if notes and new_status == "Archived":
                existing_notes = doc.internal_notes or ""
                doc.internal_notes = f"{existing_notes}\n\n[Status changed to {new_status} on {today()}]\n{notes}"
            doc.save()
            updated.append(insight_name)
        except Exception as e:
            frappe.log_error(
                message=f"Error updating insight {insight_name}: {str(e)}",
                title="Bulk Status Update Error"
            )

    return {
        "status": "success",
        "updated_count": len(updated),
        "updated": updated
    }
