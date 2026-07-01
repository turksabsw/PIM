"""
Product Score Controller
Manages product scoring with hierarchy breakdown for display priority and quality tracking
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, getdate, today, flt
import json


class ProductScore(Document):
    def validate(self):
        self.validate_linked_product()
        self.validate_scores()
        self.validate_weights()
        self.validate_dates()
        self.set_hierarchy_fields()
        self.calculate_total_weight()

    def validate_linked_product(self):
        """Validate product exists and is active"""
        if not self.linked_product:
            return

        product = frappe.db.get_value(
            "Product Master",
            self.linked_product,
            ["status", "product_family", "brand"],
            as_dict=True
        )

        if not product:
            frappe.throw(
                _("Linked product {0} does not exist").format(self.linked_product),
                title=_("Invalid Product")
            )

    def validate_scores(self):
        """Validate score values are within acceptable range (0-100)"""
        score_fields = [
            "overall_score", "manual_score", "content_completeness_score",
            "content_quality_score", "media_completeness_score", "media_quality_score",
            "seo_score", "seo_meta_title_score", "translation_coverage_score",
            "translation_quality_score", "attribute_completeness_score",
            "attribute_quality_score", "data_accuracy_score", "data_consistency_score",
            "market_performance_score", "customer_satisfaction_score",
            "competitive_position_score", "feedback_sentiment_score"
        ]

        for field in score_fields:
            value = getattr(self, field, None)
            if value is not None:
                if flt(value) < 0:
                    setattr(self, field, 0)
                    frappe.msgprint(
                        _("Score field {0} was negative, set to 0").format(field),
                        indicator="orange"
                    )
                elif flt(value) > 100:
                    setattr(self, field, 100)
                    frappe.msgprint(
                        _("Score field {0} exceeded 100, capped at 100").format(field),
                        indicator="orange"
                    )

    def validate_weights(self):
        """Validate weight values"""
        weight_fields = [
            "content_weight", "media_weight", "seo_weight",
            "translation_weight", "attribute_weight", "market_weight"
        ]

        for field in weight_fields:
            value = getattr(self, field, None)
            if value is not None:
                if flt(value) < 0:
                    setattr(self, field, 0)
                elif flt(value) > 100:
                    setattr(self, field, 100)

    def validate_dates(self):
        """Validate date fields"""
        if self.valid_from and self.valid_until:
            if getdate(self.valid_from) > getdate(self.valid_until):
                frappe.throw(
                    _("Valid From date cannot be after Valid Until date"),
                    title=_("Invalid Date Range")
                )

        if self.valid_until:
            if getdate(self.valid_until) < getdate(today()):
                self.status = "Expired"

    def set_hierarchy_fields(self):
        """Auto-populate hierarchy fields from linked product"""
        if not self.linked_product:
            return

        product = frappe.db.get_value(
            "Product Master",
            self.linked_product,
            ["product_family", "brand"],
            as_dict=True
        )

        if product:
            self.linked_product_family = product.get("product_family")
            self.linked_brand = product.get("brand")

            # Get category from product family
        if self.linked_product_family:
            try:
                self.linked_category = frappe.db.get_value(
                    "Product Family",
                    self.linked_product_family,
                    "category"
                ) or ""
            except Exception:
                self.linked_category = ""

            # Get collection if linked (optional - depends on Product Master having this field)
            try:
                self.linked_collection = frappe.db.get_value(
                    "Product Master",
                    self.linked_product,
                    "product_collection"
                )
            except Exception:
                pass

    def calculate_total_weight(self):
        """Calculate sum of all weights"""
        self.total_weight = flt(
            flt(self.content_weight or 0) +
            flt(self.media_weight or 0) +
            flt(self.seo_weight or 0) +
            flt(self.translation_weight or 0) +
            flt(self.attribute_weight or 0) +
            flt(self.market_weight or 0)
        )

        if self.total_weight != 100 and not self.use_custom_weights:
            frappe.msgprint(
                _("Total weights ({0}%) do not sum to 100%. Please adjust weights.").format(
                    self.total_weight
                ),
                indicator="orange",
                title=_("Weight Warning")
            )

    def before_save(self):
        """Prepare data before saving"""
        self.apply_manual_override()
        self.calculate_weighted_score()
        self.track_score_change()
        self.update_calculated_date()
        self.generate_improvement_recommendations()

    def apply_manual_override(self):
        """Apply manual score override if enabled"""
        if self.manual_override and self.manual_score is not None:
            self.overall_score = self.manual_score

    def calculate_weighted_score(self):
        """Calculate weighted score based on component scores and weights"""
        if self.manual_override:
            self.weighted_score = self.overall_score
            return

        total_weight = flt(self.total_weight) or 100
        if total_weight == 0:
            total_weight = 100

        # Calculate weighted sum of component scores
        content_score = (flt(self.content_completeness_score or 0) + flt(self.content_quality_score or 0)) / 2
        media_score = (flt(self.media_completeness_score or 0) + flt(self.media_quality_score or 0)) / 2
        seo_score_avg = (flt(self.seo_score or 0) + flt(self.seo_meta_title_score or 0)) / 2
        translation_score = (flt(self.translation_coverage_score or 0) + flt(self.translation_quality_score or 0)) / 2
        attribute_score = (flt(self.attribute_completeness_score or 0) + flt(self.attribute_quality_score or 0)) / 2
        market_score = (
            flt(self.market_performance_score or 0) +
            flt(self.customer_satisfaction_score or 0) +
            flt(self.competitive_position_score or 0) +
            flt(self.feedback_sentiment_score or 0)
        ) / 4

        weighted_sum = (
            (content_score * flt(self.content_weight or 0)) +
            (media_score * flt(self.media_weight or 0)) +
            (seo_score_avg * flt(self.seo_weight or 0)) +
            (translation_score * flt(self.translation_weight or 0)) +
            (attribute_score * flt(self.attribute_weight or 0)) +
            (market_score * flt(self.market_weight or 0))
        )

        self.weighted_score = flt(weighted_sum / total_weight, 2)

    def track_score_change(self):
        """Track score changes for history"""
        if self.is_new():
            self.previous_score = 0
            self.score_change = self.overall_score
        else:
            old_doc = self.get_doc_before_save()
            if old_doc and hasattr(old_doc, "overall_score"):
                self.previous_score = old_doc.overall_score
                self.score_change = flt(self.overall_score) - flt(self.previous_score)

        # Update history
        self.update_score_history()

    def update_score_history(self):
        """Maintain score history as JSON"""
        try:
            history = json.loads(self.score_history or "[]")
        except (json.JSONDecodeError, TypeError):
            history = []

        # Add current score to history
        history_entry = {
            "date": str(now_datetime()),
            "overall_score": flt(self.overall_score),
            "weighted_score": flt(self.weighted_score),
            "method": self.calculation_method or "Automatic"
        }

        # Keep only last 50 entries
        history.append(history_entry)
        if len(history) > 50:
            history = history[-50:]

        self.score_history = json.dumps(history)
        self.recalculation_count = (self.recalculation_count or 0) + 1

    def update_calculated_date(self):
        """Update calculated date"""
        self.calculated_date = now_datetime()

    def generate_improvement_recommendations(self):
        """Generate recommendations to improve the score"""
        recommendations = []
        priority_improvements = []

        # Check each component score
        score_components = [
            ("content_completeness_score", "Content Completeness", 70),
            ("media_completeness_score", "Media Completeness", 70),
            ("seo_score", "SEO", 70),
            ("translation_coverage_score", "Translation Coverage", 70),
            ("attribute_completeness_score", "Attribute Completeness", 80),
            ("customer_satisfaction_score", "Customer Satisfaction", 70),
        ]

        improvement_count = 0
        for field, label, threshold in score_components:
            score = flt(getattr(self, field, 0))
            if score < threshold:
                gap = threshold - score
                recommendations.append(
                    f"- **{label}**: Current score {score:.0f}%, "
                    f"target {threshold}% (gap: {gap:.0f}%)"
                )
                if improvement_count < 3:
                    priority_improvements.append(f"{label}: +{gap:.0f}%")
                    improvement_count += 1

        if recommendations:
            self.improvement_recommendations = "\n".join(recommendations)
            self.priority_improvements = ", ".join(priority_improvements)
        else:
            self.improvement_recommendations = "No critical improvements needed. Good job!"
            self.priority_improvements = ""

    def on_update(self):
        """Handle post-update actions"""
        self.ensure_single_current_score()
        self.update_hierarchy_rankings()
        self.invalidate_cache()

    def ensure_single_current_score(self):
        """Ensure only one score is marked as current per product"""
        if self.is_current:
            # Mark all other scores for this product as not current
            frappe.db.sql("""
                UPDATE `tabProduct Score`
                SET is_current = 0
                WHERE linked_product = %s
                AND name != %s
                AND is_current = 1
            """, (self.linked_product, self.name))

    def update_hierarchy_rankings(self):
        """Update family and category rankings"""
        try:
            # Update family ranking
            if self.linked_product_family:
                family_scores = frappe.get_all(
                    "Product Score",
                    filters={
                        "linked_product_family": self.linked_product_family,
                        "is_current": 1,
                        "status": "Active"
                    },
                    fields=["name", "overall_score", "linked_product"],
                    order_by="overall_score desc"
                )

                self.family_total_products = len(family_scores)

                # Calculate average
                if family_scores:
                    total_score = sum(flt(s.overall_score) for s in family_scores)
                    self.family_avg_score = flt(total_score / len(family_scores), 2)

                    # Find rank
                    for idx, score in enumerate(family_scores):
                        if score.name == self.name:
                            self.family_rank = idx + 1
                            break

                    # Calculate percentile
                    if self.family_rank and self.family_total_products:
                        self.family_percentile = flt(
                            ((self.family_total_products - self.family_rank + 1) /
                             self.family_total_products) * 100, 2
                        )

            # Update category ranking
            if self.linked_category:
                category_scores = frappe.get_all(
                    "Product Score",
                    filters={
                        "linked_category": self.linked_category,
                        "is_current": 1,
                        "status": "Active"
                    },
                    fields=["name", "overall_score", "linked_product"],
                    order_by="overall_score desc"
                )

                self.category_total_products = len(category_scores)

                if category_scores:
                    total_score = sum(flt(s.overall_score) for s in category_scores)
                    self.category_avg_score = flt(total_score / len(category_scores), 2)

                    for idx, score in enumerate(category_scores):
                        if score.name == self.name:
                            self.category_rank = idx + 1
                            break

                    if self.category_rank and self.category_total_products:
                        self.category_percentile = flt(
                            ((self.category_total_products - self.category_rank + 1) /
                             self.category_total_products) * 100, 2
                        )

            # Update overall percentile
            all_scores = frappe.db.count(
                "Product Score",
                filters={"is_current": 1, "status": "Active"}
            )
            if all_scores > 0:
                higher_scores = frappe.db.count(
                    "Product Score",
                    filters={
                        "is_current": 1,
                        "status": "Active",
                        "overall_score": [">", self.overall_score]
                    }
                )
                self.overall_percentile = flt(
                    ((all_scores - higher_scores) / all_scores) * 100, 2
                )

            # Save ranking updates without triggering another on_update
            frappe.db.set_value("Product Score", self.name, {
                "family_avg_score": self.family_avg_score,
                "family_rank": self.family_rank,
                "family_total_products": self.family_total_products,
                "family_percentile": self.family_percentile,
                "category_avg_score": self.category_avg_score,
                "category_rank": self.category_rank,
                "category_total_products": self.category_total_products,
                "category_percentile": self.category_percentile,
                "overall_percentile": self.overall_percentile
            }, update_modified=False)

        except Exception as e:
            frappe.log_error(
                message=f"Error updating hierarchy rankings: {str(e)}",
                title="PIM Score Ranking Error"
            )

    def invalidate_cache(self):
        """Clear relevant caches"""
        try:
            frappe.cache().delete_key(f"pim:product_score:{self.name}")
            if self.linked_product:
                frappe.cache().delete_key(f"pim:product_scores:{self.linked_product}")
            if self.linked_product_family:
                frappe.cache().delete_key(f"pim:family_scores:{self.linked_product_family}")
        except Exception:
            pass

    def on_trash(self):
        """Cleanup before deletion"""
        self.invalidate_cache()

    @frappe.whitelist()
    def recalculate_score(self):
        """Recalculate the product score"""
        self.calculation_method = "Manual"
        self.save()
        return {
            "status": "success",
            "message": _("Score recalculated successfully"),
            "overall_score": self.overall_score,
            "weighted_score": self.weighted_score
        }

    @frappe.whitelist()
    def set_manual_score(self, score):
        """Set a manual score override"""
        score = flt(score)
        if score < 0 or score > 100:
            frappe.throw(_("Score must be between 0 and 100"))

        self.manual_override = 1
        self.manual_score = score
        self.overall_score = score
        self.calculation_method = "Manual"
        self.save()

        return {
            "status": "success",
            "message": _("Manual score set to {0}").format(score)
        }


@frappe.whitelist()
def get_product_score(product):
    """Get the current score for a product

    Args:
        product: Product Master name
    """
    score = frappe.get_all(
        "Product Score",
        filters={
            "linked_product": product,
            "is_current": 1,
            "status": "Active"
        },
        fields=["*"],
        limit=1
    )

    return score[0] if score else None


@frappe.whitelist()
def get_product_scores(
    product=None,
    product_family=None,
    category=None,
    brand=None,
    score_type=None,
    status=None,
    min_score=None,
    max_score=None,
    only_current=True,
    limit=50,
    offset=0
):
    """Get product scores with optional filtering

    Args:
        product: Filter by linked product
        product_family: Filter by product family
        category: Filter by category
        brand: Filter by brand
        score_type: Filter by score type
        status: Filter by status
        min_score: Minimum overall score
        max_score: Maximum overall score
        only_current: Only return current scores
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
    if score_type:
        filters["score_type"] = score_type
    if status:
        filters["status"] = status
    if only_current:
        filters["is_current"] = 1

    if min_score is not None:
        filters["overall_score"] = [">=", flt(min_score)]
    if max_score is not None:
        if "overall_score" in filters:
            filters["overall_score"] = ["between", [flt(min_score or 0), flt(max_score)]]
        else:
            filters["overall_score"] = ["<=", flt(max_score)]

    return frappe.get_all(
        "Product Score",
        filters=filters,
        fields=[
            "name", "linked_product", "score_type", "status", "is_current",
            "overall_score", "weighted_score", "manual_override",
            "linked_product_family", "linked_category", "linked_brand",
            "family_rank", "category_rank", "overall_percentile",
            "calculated_date", "creation", "modified"
        ],
        order_by="overall_score desc",
        limit_start=offset,
        limit_page_length=limit
    )


@frappe.whitelist()
def get_score_statistics(product_family=None, category=None, brand=None):
    """Get score statistics for a hierarchy level

    Args:
        product_family: Product family to get statistics for
        category: Category to get statistics for
        brand: Brand to get statistics for
    """
    conditions = ["is_current = 1", "status = 'Active'"]
    params = []

    if product_family:
        conditions.append("linked_product_family = %s")
        params.append(product_family)
    elif category:
        conditions.append("linked_category = %s")
        params.append(category)
    elif brand:
        conditions.append("linked_brand = %s")
        params.append(brand)

    where_clause = " AND ".join(conditions)

    stats = frappe.db.sql(f"""
        SELECT
            COUNT(*) as total_products,
            AVG(overall_score) as avg_score,
            MIN(overall_score) as min_score,
            MAX(overall_score) as max_score,
            STDDEV(overall_score) as std_dev,
            SUM(CASE WHEN overall_score >= 80 THEN 1 ELSE 0 END) as high_score_count,
            SUM(CASE WHEN overall_score >= 50 AND overall_score < 80 THEN 1 ELSE 0 END) as medium_score_count,
            SUM(CASE WHEN overall_score < 50 THEN 1 ELSE 0 END) as low_score_count,
            AVG(content_completeness_score) as avg_content_score,
            AVG(media_completeness_score) as avg_media_score,
            AVG(seo_score) as avg_seo_score,
            AVG(attribute_completeness_score) as avg_attribute_score
        FROM `tabProduct Score`
        WHERE {where_clause}
    """, params, as_dict=True)

    return stats[0] if stats else {}


@frappe.whitelist()
def get_top_products(
    product_family=None,
    category=None,
    brand=None,
    limit=10
):
    """Get top-scoring products for a hierarchy level

    Args:
        product_family: Filter by product family
        category: Filter by category
        brand: Filter by brand
        limit: Maximum results to return
    """
    filters = {
        "is_current": 1,
        "status": "Active"
    }

    if product_family:
        filters["linked_product_family"] = product_family
    if category:
        filters["linked_category"] = category
    if brand:
        filters["linked_brand"] = brand

    return frappe.get_all(
        "Product Score",
        filters=filters,
        fields=[
            "name", "linked_product", "overall_score", "weighted_score",
            "family_rank", "category_rank", "overall_percentile",
            "content_completeness_score", "media_completeness_score",
            "seo_score", "attribute_completeness_score"
        ],
        order_by="overall_score desc",
        limit_page_length=limit
    )


@frappe.whitelist()
def get_low_score_products(threshold=50, limit=20):
    """Get products with scores below threshold for improvement

    Args:
        threshold: Score threshold (default 50)
        limit: Maximum results to return
    """
    return frappe.get_all(
        "Product Score",
        filters={
            "is_current": 1,
            "status": "Active",
            "overall_score": ["<", flt(threshold)]
        },
        fields=[
            "name", "linked_product", "overall_score", "weighted_score",
            "linked_product_family", "linked_category",
            "priority_improvements", "improvement_recommendations"
        ],
        order_by="overall_score asc",
        limit_page_length=limit
    )


@frappe.whitelist()
def bulk_recalculate_scores(product_family=None, category=None, brand=None):
    """Bulk recalculate scores for a group of products

    Args:
        product_family: Recalculate for this product family
        category: Recalculate for this category
        brand: Recalculate for this brand
    """
    filters = {
        "is_current": 1,
        "status": "Active"
    }

    if product_family:
        filters["linked_product_family"] = product_family
    elif category:
        filters["linked_category"] = category
    elif brand:
        filters["linked_brand"] = brand
    else:
        frappe.throw(_("Please specify a product family, category, or brand"))

    scores = frappe.get_all(
        "Product Score",
        filters=filters,
        fields=["name"]
    )

    recalculated = []
    for score in scores:
        try:
            doc = frappe.get_doc("Product Score", score.name)
            doc.calculation_method = "Batch"
            doc.save()
            recalculated.append(score.name)
        except Exception as e:
            frappe.log_error(
                message=f"Error recalculating score {score.name}: {str(e)}",
                title="Bulk Score Recalculation Error"
            )

    return {
        "status": "success",
        "recalculated_count": len(recalculated),
        "recalculated": recalculated
    }


@frappe.whitelist()
def create_score_for_product(product, calculate=True):
    """Create a new product score for a product

    Args:
        product: Product Master name
        calculate: Whether to calculate scores automatically
    """
    if not frappe.db.exists("Product Master", product):
        frappe.throw(_("Product {0} does not exist").format(product))

    # Check if current score already exists
    existing = frappe.get_all(
        "Product Score",
        filters={
            "linked_product": product,
            "is_current": 1
        },
        limit=1
    )

    if existing:
        frappe.msgprint(
            _("A current score already exists for this product. Creating a new score will replace it."),
            indicator="orange"
        )

    doc = frappe.new_doc("Product Score")
    doc.linked_product = product
    doc.score_type = "Overall"
    doc.calculation_method = "API"
    doc.is_current = 1
    doc.status = "Active"

    if calculate:
        # Import scoring utility if available
        try:
            from frappe_pim.pim.utils.scoring import calculate_product_score
            scores = calculate_product_score(product)
            for field, value in scores.items():
                if hasattr(doc, field):
                    setattr(doc, field, value)
        except ImportError:
            # Set default scores if utility not available
            doc.overall_score = 0

    doc.insert()

    return {
        "status": "success",
        "score_name": doc.name,
        "overall_score": doc.overall_score
    }
