"""
Competitor Analysis Controller
Manages competitor product comparisons and market intelligence
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today


class CompetitorAnalysis(Document):
    def validate(self):
        self.validate_linked_product()
        self.validate_dates()
        self.validate_ratings()
        self.set_product_family()
        self.calculate_price_difference()

    def validate_linked_product(self):
        """Validate product exists"""
        if self.linked_product:
            if not frappe.db.exists("Product Master", self.linked_product):
                frappe.throw(
                    _("Linked product {0} does not exist").format(self.linked_product),
                    title=_("Invalid Product")
                )

    def validate_dates(self):
        """Validate date fields"""
        if self.analysis_date:
            if getdate(self.analysis_date) > getdate(today()):
                frappe.msgprint(
                    _("Analysis date is in the future. Please verify."),
                    indicator="orange",
                    title=_("Future Date")
                )

        if self.follow_up_date and self.analysis_date:
            if getdate(self.follow_up_date) < getdate(self.analysis_date):
                frappe.throw(
                    _("Follow-up date cannot be before analysis date"),
                    title=_("Invalid Date")
                )

    def validate_ratings(self):
        """Ensure ratings are within valid range (0-5)"""
        rating_fields = [
            "quality_rating_ours", "quality_rating_competitor",
            "value_rating_ours", "value_rating_competitor",
            "features_rating_ours", "features_rating_competitor"
        ]

        for field in rating_fields:
            value = self.get(field)
            if value is not None and (value < 0 or value > 5):
                frappe.throw(
                    _("{0} must be between 0 and 5").format(
                        self.meta.get_label(field)
                    ),
                    title=_("Invalid Rating")
                )

    def set_product_family(self):
        """Auto-populate product family from linked product"""
        if self.linked_product and not self.linked_product_family:
            self.linked_product_family = frappe.db.get_value(
                "Product Master",
                self.linked_product,
                "product_family"
            )

    def calculate_price_difference(self):
        """Calculate price difference between our product and competitor"""
        if self.our_price is not None and self.competitor_price is not None:
            self.price_difference = self.our_price - self.competitor_price

            if self.competitor_price > 0:
                self.price_difference_percent = (
                    (self.our_price - self.competitor_price) / self.competitor_price
                ) * 100

            # Auto-set price position
            if self.price_difference > 0:
                self.price_position = "Higher"
            elif self.price_difference < 0:
                self.price_position = "Lower"
            else:
                self.price_position = "Similar"

    def before_save(self):
        """Prepare data before saving"""
        self.set_analyst_if_empty()
        self.check_staleness()

    def set_analyst_if_empty(self):
        """Set analyst to current user if not specified"""
        if not self.analyst:
            self.analyst = frappe.session.user

    def check_staleness(self):
        """Check if analysis might be outdated"""
        if self.analysis_date and self.analysis_status not in ["Outdated", "Archived"]:
            from frappe.utils import date_diff
            days_old = date_diff(today(), self.analysis_date)
            if days_old > 90:
                frappe.msgprint(
                    _("This analysis is {0} days old. Consider updating or marking as outdated.").format(days_old),
                    indicator="orange",
                    title=_("Potentially Outdated")
                )

    def on_update(self):
        """Handle post-update actions"""
        self.update_product_analysis_count()
        self.invalidate_cache()

    def on_trash(self):
        """Cleanup before deletion"""
        self.update_product_analysis_count()
        self.invalidate_cache()

    def update_product_analysis_count(self):
        """Update analysis statistics on the linked product"""
        if self.linked_product:
            try:
                # Count analyses for this product
                count = frappe.db.count(
                    "Competitor Analysis",
                    filters={
                        "linked_product": self.linked_product,
                        "analysis_status": ["not in", ["Archived", "Outdated"]]
                    }
                )
                # Clear cache for product's competitor analyses
                frappe.cache().delete_key(f"pim:competitor_analyses:{self.linked_product}")
            except Exception as e:
                frappe.log_error(
                    message=f"Error updating analysis count: {str(e)}",
                    title="PIM Competitor Analysis Error"
                )

    def invalidate_cache(self):
        """Clear relevant caches"""
        try:
            frappe.cache().delete_key(f"pim:competitor_analysis:{self.name}")
            if self.linked_product:
                frappe.cache().delete_key(f"pim:competitor_analyses:{self.linked_product}")
            if self.competitor_name:
                frappe.cache().delete_key(f"pim:competitor:{self.competitor_name}")
        except Exception:
            pass

    @frappe.whitelist()
    def mark_outdated(self, reason=None):
        """Mark this analysis as outdated"""
        self.analysis_status = "Outdated"
        if reason:
            self.internal_notes = (self.internal_notes or "") + f"\n\nMarked outdated: {reason}"
        self.save()

        return {
            "status": "success",
            "message": _("Analysis marked as outdated")
        }

    @frappe.whitelist()
    def create_follow_up(self):
        """Create a new analysis record for follow-up"""
        new_doc = frappe.copy_doc(self)
        new_doc.analysis_status = "Draft"
        new_doc.analysis_date = today()
        new_doc.internal_notes = _("Follow-up analysis from {0}").format(self.name)
        new_doc.insert()

        return {
            "status": "success",
            "message": _("Follow-up analysis created"),
            "new_analysis": new_doc.name
        }


@frappe.whitelist()
def get_product_competitor_analyses(
    product=None,
    product_family=None,
    competitor_name=None,
    status=None,
    threat_level=None,
    limit=20,
    offset=0
):
    """Get competitor analyses with optional filtering

    Args:
        product: Filter by linked product
        product_family: Filter by product family
        competitor_name: Filter by competitor name
        status: Filter by analysis status
        threat_level: Filter by competitive threat level
        limit: Maximum results to return
        offset: Results offset for pagination
    """
    filters = {}
    if product:
        filters["linked_product"] = product
    if product_family:
        filters["linked_product_family"] = product_family
    if competitor_name:
        filters["competitor_name"] = ["like", f"%{competitor_name}%"]
    if status:
        filters["analysis_status"] = status
    if threat_level:
        filters["competitive_threat_level"] = threat_level

    return frappe.get_all(
        "Competitor Analysis",
        filters=filters,
        fields=[
            "name", "title", "competitor_name", "competitor_product_name",
            "linked_product", "analysis_status", "analysis_date",
            "competitive_threat_level", "price_position", "customer_perception",
            "our_price", "competitor_price", "price_difference_percent",
            "creation", "modified"
        ],
        order_by="modified desc",
        limit_start=offset,
        limit_page_length=limit
    )


@frappe.whitelist()
def get_competitor_statistics(product=None, product_family=None):
    """Get competitor analysis statistics for a product or product family

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
            COUNT(*) as total_analyses,
            COUNT(DISTINCT competitor_name) as unique_competitors,
            SUM(CASE WHEN competitive_threat_level = 'Critical' THEN 1 ELSE 0 END) as critical_threats,
            SUM(CASE WHEN competitive_threat_level = 'High' THEN 1 ELSE 0 END) as high_threats,
            SUM(CASE WHEN price_position = 'Higher' THEN 1 ELSE 0 END) as priced_higher,
            SUM(CASE WHEN price_position = 'Lower' THEN 1 ELSE 0 END) as priced_lower,
            AVG(price_difference_percent) as avg_price_diff_percent,
            SUM(CASE WHEN analysis_status = 'Outdated' THEN 1 ELSE 0 END) as outdated_count
        FROM `tabCompetitor Analysis`
        WHERE {where_clause}
    """, params, as_dict=True)

    return stats[0] if stats else {}


@frappe.whitelist()
def get_competitors_list(product=None, product_family=None):
    """Get list of unique competitors for a product or product family

    Args:
        product: Product name to get competitors for
        product_family: Product family name to get competitors for
    """
    filters = {}
    if product:
        filters["linked_product"] = product
    elif product_family:
        filters["linked_product_family"] = product_family

    # Get unique competitor names with their analysis count
    competitors = frappe.db.sql("""
        SELECT
            competitor_name,
            COUNT(*) as analysis_count,
            MAX(analysis_date) as latest_analysis,
            GROUP_CONCAT(DISTINCT competitive_threat_level) as threat_levels
        FROM `tabCompetitor Analysis`
        WHERE linked_product = %(product)s OR linked_product_family = %(product_family)s
        GROUP BY competitor_name
        ORDER BY analysis_count DESC
    """, {"product": product, "product_family": product_family}, as_dict=True)

    return competitors


@frappe.whitelist()
def get_high_threat_competitors(limit=10):
    """Get competitor analyses with high or critical threat levels

    Args:
        limit: Maximum results to return
    """
    return frappe.get_all(
        "Competitor Analysis",
        filters={
            "analysis_status": ["not in", ["Archived", "Outdated"]],
            "competitive_threat_level": ["in", ["High", "Critical"]]
        },
        fields=[
            "name", "title", "competitor_name", "competitor_product_name",
            "linked_product", "competitive_threat_level", "price_position",
            "priority_actions", "follow_up_date", "analysis_date"
        ],
        order_by="competitive_threat_level desc, modified desc",
        limit_page_length=limit
    )


@frappe.whitelist()
def bulk_update_status(analysis_list, new_status):
    """Update status for multiple competitor analysis records

    Args:
        analysis_list: JSON string of list of analysis names
        new_status: New status to set
    """
    import json

    if isinstance(analysis_list, str):
        analysis_list = json.loads(analysis_list)

    valid_statuses = ["Draft", "In Progress", "Completed", "Outdated", "Archived"]
    if new_status not in valid_statuses:
        frappe.throw(_("Invalid status: {0}").format(new_status))

    updated = []
    for analysis_name in analysis_list:
        try:
            doc = frappe.get_doc("Competitor Analysis", analysis_name)
            doc.analysis_status = new_status
            doc.save()
            updated.append(analysis_name)
        except Exception as e:
            frappe.log_error(
                message=f"Error updating analysis {analysis_name}: {str(e)}",
                title="Bulk Status Update Error"
            )

    return {
        "status": "success",
        "updated_count": len(updated),
        "updated": updated
    }
