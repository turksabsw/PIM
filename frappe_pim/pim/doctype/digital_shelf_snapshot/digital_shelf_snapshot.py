# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

"""
Digital Shelf Snapshot DocType Controller

Captures and stores point-in-time PDP (Product Detail Page) data from
marketplace channels for digital shelf analytics and monitoring.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from frappe.types import DF


def _get_frappe():
    """Deferred import of frappe module."""
    import frappe
    return frappe


class DigitalShelfSnapshot:
    """Controller for Digital Shelf Snapshot DocType."""

    # DocType field declarations for type hints
    if TYPE_CHECKING:
        product: DF.Link
        channel: DF.Link
        snapshot_timestamp: DF.Datetime
        snapshot_type: DF.Literal["Scheduled", "Manual", "Event Triggered", "Alert Response"]
        external_product_id: DF.Data
        pdp_title: DF.Data
        pdp_brand: DF.Data
        pdp_url: DF.Data
        pdp_category: DF.Data
        pdp_bullet_count: DF.Int
        pdp_image_count: DF.Int
        pdp_short_description: DF.SmallText
        pdp_long_description: DF.Text
        pdp_bullet_points: DF.Text
        current_price: DF.Currency
        list_price: DF.Currency
        price_currency: DF.Link
        discount_percentage: DF.Percent
        price_per_unit: DF.Currency
        price_unit: DF.Data
        has_promotion: DF.Check
        promotion_details: DF.SmallText
        in_stock: DF.Check
        stock_status: DF.Literal["In Stock", "Out of Stock", "Limited Stock", "Backorder", "Preorder", "Discontinued", "Unknown"]
        estimated_delivery: DF.Data
        has_buy_box: DF.Check
        buy_box_seller: DF.Data
        buy_box_price: DF.Currency
        total_offers: DF.Int
        fulfillment_type: DF.Literal["", "FBA", "FBM", "Prime", "Fulfilled by Channel", "Seller Fulfilled", "Dropship"]
        average_rating: DF.Float
        total_reviews: DF.Int
        total_ratings: DF.Int
        rating_5_star: DF.Int
        rating_4_star: DF.Int
        rating_3_star: DF.Int
        rating_2_star: DF.Int
        rating_1_star: DF.Int
        recent_reviews_summary: DF.Text
        primary_keyword: DF.Data
        primary_keyword_rank: DF.Int
        primary_keyword_page: DF.Int
        category_rank: DF.Int
        category_for_rank: DF.Data
        best_seller_rank: DF.Int
        search_rankings_json: DF.JSON
        content_score: DF.Percent
        title_length: DF.Int
        description_length: DF.Int
        has_a_plus_content: DF.Check
        has_video: DF.Check
        has_size_guide: DF.Check
        has_comparison_chart: DF.Check
        content_issues: DF.SmallText
        competitor_count: DF.Int
        lowest_competitor_price: DF.Currency
        highest_competitor_price: DF.Currency
        avg_competitor_price: DF.Currency
        price_position: DF.Literal["", "Lowest", "Below Average", "Average", "Above Average", "Highest"]
        competitor_data_json: DF.JSON
        has_changes: DF.Check
        previous_snapshot: DF.Link
        price_change: DF.Currency
        price_change_pct: DF.Percent
        rank_change: DF.Int
        rating_change: DF.Float
        changes_summary: DF.SmallText
        raw_html: DF.Code
        raw_api_response: DF.JSON
        capture_method: DF.Literal["API", "Web Scraping", "Browser Automation", "Manual Entry", "Channel Feed"]
        capture_duration_ms: DF.Int
        capture_errors: DF.SmallText
        data_completeness: DF.Percent

    def validate(self):
        """Validate the snapshot before saving."""
        self._validate_timestamp()
        self._calculate_derived_fields()
        self._detect_changes()
        self._calculate_content_score()
        self._calculate_data_completeness()

    def before_insert(self):
        """Actions before inserting a new snapshot."""
        frappe = _get_frappe()

        # Set snapshot timestamp if not provided
        if not self.snapshot_timestamp:
            self.snapshot_timestamp = frappe.utils.now_datetime()

        # Find and link to previous snapshot
        self._link_previous_snapshot()

    def after_insert(self):
        """Actions after inserting a new snapshot."""
        self._create_alerts_if_needed()

    def _validate_timestamp(self):
        """Validate that snapshot timestamp is not in the future."""
        frappe = _get_frappe()

        if self.snapshot_timestamp:
            now = frappe.utils.now_datetime()
            snapshot_time = frappe.utils.get_datetime(self.snapshot_timestamp)

            # Allow small tolerance for clock skew (5 minutes)
            if snapshot_time > now:
                tolerance = frappe.utils.add_to_date(now, minutes=5)
                if snapshot_time > tolerance:
                    frappe.throw(
                        frappe._("Snapshot timestamp cannot be in the future"),
                        frappe.ValidationError
                    )

    def _calculate_derived_fields(self):
        """Calculate derived fields from captured data."""
        # Calculate discount percentage if prices are available
        if self.list_price and self.current_price and self.list_price > 0:
            self.discount_percentage = (
                (self.list_price - self.current_price) / self.list_price * 100
            )

        # Calculate title length
        if self.pdp_title:
            self.title_length = len(self.pdp_title)

        # Calculate description length
        if self.pdp_long_description:
            self.description_length = len(self.pdp_long_description)
        elif self.pdp_short_description:
            self.description_length = len(self.pdp_short_description)

        # Calculate bullet count from bullet points text
        if self.pdp_bullet_points and not self.pdp_bullet_count:
            bullets = [b.strip() for b in self.pdp_bullet_points.split('\n') if b.strip()]
            self.pdp_bullet_count = len(bullets)

        # Calculate price position if competitor data is available
        self._calculate_price_position()

    def _calculate_price_position(self):
        """Calculate price position relative to competitors."""
        if not self.current_price:
            self.price_position = ""
            return

        if self.lowest_competitor_price and self.highest_competitor_price:
            if self.current_price <= self.lowest_competitor_price:
                self.price_position = "Lowest"
            elif self.current_price >= self.highest_competitor_price:
                self.price_position = "Highest"
            elif self.avg_competitor_price:
                if self.current_price < self.avg_competitor_price * 0.95:
                    self.price_position = "Below Average"
                elif self.current_price > self.avg_competitor_price * 1.05:
                    self.price_position = "Above Average"
                else:
                    self.price_position = "Average"

    def _link_previous_snapshot(self):
        """Find and link to the previous snapshot for the same product/channel."""
        frappe = _get_frappe()

        if not self.product or not self.channel:
            return

        # Find the most recent snapshot for this product/channel
        previous = frappe.get_all(
            "Digital Shelf Snapshot",
            filters={
                "product": self.product,
                "channel": self.channel,
                "name": ["!=", self.name or ""]
            },
            fields=["name"],
            order_by="snapshot_timestamp desc",
            limit=1
        )

        if previous:
            self.previous_snapshot = previous[0].name

    def _detect_changes(self):
        """Detect changes from the previous snapshot."""
        frappe = _get_frappe()

        if not self.previous_snapshot:
            self.has_changes = False
            self.changes_summary = ""
            return

        try:
            prev = frappe.get_doc("Digital Shelf Snapshot", self.previous_snapshot)
        except frappe.DoesNotExistError:
            self.has_changes = False
            return

        changes = []

        # Price changes
        if prev.current_price and self.current_price:
            self.price_change = self.current_price - prev.current_price
            if prev.current_price > 0:
                self.price_change_pct = (self.price_change / prev.current_price) * 100

            if abs(self.price_change) > 0.01:
                direction = "increased" if self.price_change > 0 else "decreased"
                changes.append(f"Price {direction} by {abs(self.price_change_pct):.1f}%")

        # Rank changes (negative change means improvement)
        if prev.primary_keyword_rank and self.primary_keyword_rank:
            self.rank_change = self.primary_keyword_rank - prev.primary_keyword_rank
            if self.rank_change != 0:
                direction = "dropped" if self.rank_change > 0 else "improved"
                changes.append(f"Search rank {direction} by {abs(self.rank_change)} positions")

        # Rating changes
        if prev.average_rating and self.average_rating:
            self.rating_change = self.average_rating - prev.average_rating
            if abs(self.rating_change) >= 0.1:
                direction = "increased" if self.rating_change > 0 else "decreased"
                changes.append(f"Rating {direction} by {abs(self.rating_change):.1f}")

        # Stock status changes
        if prev.in_stock != self.in_stock:
            status = "now in stock" if self.in_stock else "now out of stock"
            changes.append(f"Product is {status}")

        # Buy box changes
        if prev.has_buy_box != self.has_buy_box:
            status = "gained" if self.has_buy_box else "lost"
            changes.append(f"{status.capitalize()} buy box")

        # Title changes
        if prev.pdp_title and self.pdp_title and prev.pdp_title != self.pdp_title:
            changes.append("Title changed")

        # Content changes
        if prev.has_a_plus_content != self.has_a_plus_content:
            status = "added" if self.has_a_plus_content else "removed"
            changes.append(f"A+ content {status}")

        self.has_changes = len(changes) > 0
        self.changes_summary = "; ".join(changes) if changes else ""

    def _calculate_content_score(self):
        """Calculate content quality/completeness score."""
        score_factors = []

        # Title quality (max 25 points)
        if self.pdp_title:
            title_len = len(self.pdp_title)
            if 50 <= title_len <= 200:
                score_factors.append(25)
            elif 30 <= title_len < 50 or 200 < title_len <= 250:
                score_factors.append(15)
            elif title_len > 0:
                score_factors.append(5)

        # Description quality (max 25 points)
        if self.pdp_long_description:
            desc_len = len(self.pdp_long_description)
            if desc_len >= 1000:
                score_factors.append(25)
            elif desc_len >= 500:
                score_factors.append(20)
            elif desc_len >= 200:
                score_factors.append(10)
            elif desc_len > 0:
                score_factors.append(5)
        elif self.pdp_short_description:
            score_factors.append(10)

        # Bullet points (max 15 points)
        if self.pdp_bullet_count:
            if self.pdp_bullet_count >= 5:
                score_factors.append(15)
            elif self.pdp_bullet_count >= 3:
                score_factors.append(10)
            elif self.pdp_bullet_count >= 1:
                score_factors.append(5)

        # Images (max 15 points)
        if self.pdp_image_count:
            if self.pdp_image_count >= 7:
                score_factors.append(15)
            elif self.pdp_image_count >= 4:
                score_factors.append(10)
            elif self.pdp_image_count >= 1:
                score_factors.append(5)

        # Enhanced content (max 20 points)
        enhanced_score = 0
        if self.has_a_plus_content:
            enhanced_score += 10
        if self.has_video:
            enhanced_score += 5
        if self.has_comparison_chart:
            enhanced_score += 3
        if self.has_size_guide:
            enhanced_score += 2
        score_factors.append(min(enhanced_score, 20))

        # Calculate total score
        self.content_score = sum(score_factors)

        # Identify content issues
        issues = []
        if not self.pdp_title:
            issues.append("Missing title")
        elif self.title_length and self.title_length < 30:
            issues.append("Title too short")

        if not self.pdp_long_description and not self.pdp_short_description:
            issues.append("Missing description")

        if not self.pdp_bullet_count or self.pdp_bullet_count < 3:
            issues.append("Insufficient bullet points")

        if not self.pdp_image_count or self.pdp_image_count < 3:
            issues.append("Insufficient images")

        if not self.has_a_plus_content:
            issues.append("No enhanced content")

        self.content_issues = "; ".join(issues) if issues else ""

    def _calculate_data_completeness(self):
        """Calculate what percentage of snapshot fields were captured."""
        # Define important fields to check
        important_fields = [
            "pdp_title", "pdp_brand", "pdp_url", "pdp_category",
            "pdp_short_description", "pdp_long_description", "pdp_bullet_points",
            "pdp_image_count", "current_price", "price_currency",
            "in_stock", "stock_status", "average_rating", "total_reviews",
            "primary_keyword_rank"
        ]

        captured = 0
        for field in important_fields:
            value = getattr(self, field, None)
            if value not in (None, "", 0):
                captured += 1

        self.data_completeness = (captured / len(important_fields)) * 100

    def _create_alerts_if_needed(self):
        """Create alerts for significant changes that need attention."""
        frappe = _get_frappe()

        if not self.has_changes:
            return

        alerts = []

        # Alert on buy box loss
        if self.previous_snapshot:
            try:
                prev = frappe.get_doc("Digital Shelf Snapshot", self.previous_snapshot)
                if prev.has_buy_box and not self.has_buy_box:
                    alerts.append({
                        "type": "buy_box_lost",
                        "severity": "high",
                        "message": f"Lost buy box for {self.product} on {self.channel}"
                    })
            except frappe.DoesNotExistError:
                pass

        # Alert on significant price drop by competitor
        if self.price_change_pct and self.price_change_pct < -10:
            alerts.append({
                "type": "price_drop",
                "severity": "medium",
                "message": f"Price dropped {abs(self.price_change_pct):.1f}% for {self.product}"
            })

        # Alert on out of stock
        if not self.in_stock and self.stock_status == "Out of Stock":
            alerts.append({
                "type": "out_of_stock",
                "severity": "high",
                "message": f"{self.product} is out of stock on {self.channel}"
            })

        # Alert on low rating
        if self.average_rating and self.average_rating < 3.5:
            alerts.append({
                "type": "low_rating",
                "severity": "medium",
                "message": f"{self.product} has low rating ({self.average_rating}) on {self.channel}"
            })

        # Log alerts (in production, these would create actual alert documents)
        for alert in alerts:
            frappe.log_error(
                title=f"Digital Shelf Alert: {alert['type']}",
                message=alert["message"]
            )

    def get_trend_data(self, days: int = 30) -> dict:
        """
        Get trend data for this product/channel over the specified period.

        Args:
            days: Number of days to look back

        Returns:
            Dictionary with trend data arrays
        """
        frappe = _get_frappe()

        from_date = frappe.utils.add_to_date(
            frappe.utils.now_datetime(),
            days=-days
        )

        snapshots = frappe.get_all(
            "Digital Shelf Snapshot",
            filters={
                "product": self.product,
                "channel": self.channel,
                "snapshot_timestamp": [">=", from_date]
            },
            fields=[
                "snapshot_timestamp", "current_price", "average_rating",
                "total_reviews", "primary_keyword_rank", "content_score",
                "has_buy_box", "in_stock"
            ],
            order_by="snapshot_timestamp asc"
        )

        return {
            "timestamps": [s.snapshot_timestamp for s in snapshots],
            "prices": [s.current_price for s in snapshots],
            "ratings": [s.average_rating for s in snapshots],
            "reviews": [s.total_reviews for s in snapshots],
            "ranks": [s.primary_keyword_rank for s in snapshots],
            "content_scores": [s.content_score for s in snapshots],
            "buy_box": [s.has_buy_box for s in snapshots],
            "in_stock": [s.in_stock for s in snapshots]
        }


# =============================================================================
# API Functions
# =============================================================================

def create_snapshot(
    product: str,
    channel: str,
    data: dict,
    snapshot_type: str = "API",
    capture_method: str = "API"
) -> str:
    """
    Create a new digital shelf snapshot.

    Args:
        product: Product Master name
        channel: Channel name
        data: Dictionary of snapshot data
        snapshot_type: Type of snapshot trigger
        capture_method: How the data was captured

    Returns:
        Name of the created snapshot document
    """
    frappe = _get_frappe()

    doc = frappe.new_doc("Digital Shelf Snapshot")
    doc.product = product
    doc.channel = channel
    doc.snapshot_type = snapshot_type
    doc.capture_method = capture_method
    doc.snapshot_timestamp = frappe.utils.now_datetime()

    # Set data fields
    for field, value in data.items():
        if hasattr(doc, field):
            setattr(doc, field, value)

    doc.insert(ignore_permissions=True)

    return doc.name


def get_latest_snapshot(product: str, channel: str) -> Optional[dict]:
    """
    Get the most recent snapshot for a product/channel combination.

    Args:
        product: Product Master name
        channel: Channel name

    Returns:
        Snapshot data dictionary or None
    """
    frappe = _get_frappe()

    snapshots = frappe.get_all(
        "Digital Shelf Snapshot",
        filters={
            "product": product,
            "channel": channel
        },
        fields=["name"],
        order_by="snapshot_timestamp desc",
        limit=1
    )

    if snapshots:
        return frappe.get_doc("Digital Shelf Snapshot", snapshots[0].name).as_dict()

    return None


def get_product_shelf_status(product: str) -> dict:
    """
    Get the current shelf status across all channels for a product.

    Args:
        product: Product Master name

    Returns:
        Dictionary with channel-wise status
    """
    frappe = _get_frappe()

    # Get latest snapshot per channel using a subquery approach
    latest_per_channel = frappe.db.sql("""
        SELECT dss.*
        FROM `tabDigital Shelf Snapshot` dss
        INNER JOIN (
            SELECT channel, MAX(snapshot_timestamp) as max_ts
            FROM `tabDigital Shelf Snapshot`
            WHERE product = %s
            GROUP BY channel
        ) latest ON dss.channel = latest.channel
            AND dss.snapshot_timestamp = latest.max_ts
            AND dss.product = %s
    """, (product, product), as_dict=True)

    result = {
        "product": product,
        "channels": {},
        "summary": {
            "total_channels": 0,
            "in_stock_count": 0,
            "buy_box_count": 0,
            "avg_rating": 0,
            "avg_content_score": 0
        }
    }

    ratings = []
    content_scores = []

    for snapshot in latest_per_channel:
        channel_name = snapshot.get("channel")
        result["channels"][channel_name] = {
            "snapshot_name": snapshot.get("name"),
            "timestamp": snapshot.get("snapshot_timestamp"),
            "current_price": snapshot.get("current_price"),
            "in_stock": snapshot.get("in_stock"),
            "has_buy_box": snapshot.get("has_buy_box"),
            "average_rating": snapshot.get("average_rating"),
            "total_reviews": snapshot.get("total_reviews"),
            "primary_keyword_rank": snapshot.get("primary_keyword_rank"),
            "content_score": snapshot.get("content_score")
        }

        result["summary"]["total_channels"] += 1
        if snapshot.get("in_stock"):
            result["summary"]["in_stock_count"] += 1
        if snapshot.get("has_buy_box"):
            result["summary"]["buy_box_count"] += 1
        if snapshot.get("average_rating"):
            ratings.append(snapshot.get("average_rating"))
        if snapshot.get("content_score"):
            content_scores.append(snapshot.get("content_score"))

    if ratings:
        result["summary"]["avg_rating"] = sum(ratings) / len(ratings)
    if content_scores:
        result["summary"]["avg_content_score"] = sum(content_scores) / len(content_scores)

    return result


def compare_snapshots(snapshot_1: str, snapshot_2: str) -> dict:
    """
    Compare two snapshots and return the differences.

    Args:
        snapshot_1: First snapshot name (older)
        snapshot_2: Second snapshot name (newer)

    Returns:
        Dictionary of differences
    """
    frappe = _get_frappe()

    doc1 = frappe.get_doc("Digital Shelf Snapshot", snapshot_1)
    doc2 = frappe.get_doc("Digital Shelf Snapshot", snapshot_2)

    compare_fields = [
        "pdp_title", "current_price", "list_price", "discount_percentage",
        "in_stock", "stock_status", "has_buy_box", "buy_box_seller",
        "average_rating", "total_reviews", "primary_keyword_rank",
        "category_rank", "best_seller_rank", "content_score",
        "pdp_image_count", "pdp_bullet_count", "has_a_plus_content",
        "has_video"
    ]

    differences = {}
    for field in compare_fields:
        val1 = getattr(doc1, field, None)
        val2 = getattr(doc2, field, None)

        if val1 != val2:
            differences[field] = {
                "before": val1,
                "after": val2
            }

            # Calculate change for numeric fields
            if isinstance(val1, (int, float)) and isinstance(val2, (int, float)):
                if val1 and val1 != 0:
                    differences[field]["change"] = val2 - val1
                    differences[field]["change_pct"] = ((val2 - val1) / val1) * 100

    return {
        "snapshot_1": snapshot_1,
        "snapshot_2": snapshot_2,
        "timestamp_1": doc1.snapshot_timestamp,
        "timestamp_2": doc2.snapshot_timestamp,
        "differences": differences,
        "total_changes": len(differences)
    }


def get_snapshot_history(
    product: str,
    channel: str,
    limit: int = 100,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None
) -> list:
    """
    Get snapshot history for a product/channel.

    Args:
        product: Product Master name
        channel: Channel name
        limit: Maximum number of snapshots to return
        from_date: Start date filter
        to_date: End date filter

    Returns:
        List of snapshot summaries
    """
    frappe = _get_frappe()

    filters = {
        "product": product,
        "channel": channel
    }

    if from_date:
        filters["snapshot_timestamp"] = [">=", from_date]
    if to_date:
        if "snapshot_timestamp" in filters:
            filters["snapshot_timestamp"] = ["between", [from_date, to_date]]
        else:
            filters["snapshot_timestamp"] = ["<=", to_date]

    return frappe.get_all(
        "Digital Shelf Snapshot",
        filters=filters,
        fields=[
            "name", "snapshot_timestamp", "snapshot_type",
            "current_price", "in_stock", "has_buy_box",
            "average_rating", "total_reviews", "primary_keyword_rank",
            "content_score", "has_changes", "changes_summary"
        ],
        order_by="snapshot_timestamp desc",
        limit=limit
    )


def get_channel_shelf_overview(channel: str) -> dict:
    """
    Get an overview of all products' shelf status on a specific channel.

    Args:
        channel: Channel name

    Returns:
        Dictionary with channel overview statistics
    """
    frappe = _get_frappe()

    # Get latest snapshots for all products on this channel
    latest_snapshots = frappe.db.sql("""
        SELECT dss.*
        FROM `tabDigital Shelf Snapshot` dss
        INNER JOIN (
            SELECT product, MAX(snapshot_timestamp) as max_ts
            FROM `tabDigital Shelf Snapshot`
            WHERE channel = %s
            GROUP BY product
        ) latest ON dss.product = latest.product
            AND dss.snapshot_timestamp = latest.max_ts
            AND dss.channel = %s
    """, (channel, channel), as_dict=True)

    overview = {
        "channel": channel,
        "total_products": len(latest_snapshots),
        "in_stock": 0,
        "out_of_stock": 0,
        "own_buy_box": 0,
        "lost_buy_box": 0,
        "avg_rating": 0,
        "low_rating_products": 0,
        "avg_content_score": 0,
        "low_content_products": 0,
        "price_alerts": 0,
        "products": []
    }

    ratings = []
    content_scores = []

    for snapshot in latest_snapshots:
        if snapshot.get("in_stock"):
            overview["in_stock"] += 1
        else:
            overview["out_of_stock"] += 1

        if snapshot.get("has_buy_box"):
            overview["own_buy_box"] += 1
        else:
            overview["lost_buy_box"] += 1

        rating = snapshot.get("average_rating")
        if rating:
            ratings.append(rating)
            if rating < 3.5:
                overview["low_rating_products"] += 1

        content = snapshot.get("content_score")
        if content:
            content_scores.append(content)
            if content < 70:
                overview["low_content_products"] += 1

        overview["products"].append({
            "product": snapshot.get("product"),
            "name": snapshot.get("name"),
            "current_price": snapshot.get("current_price"),
            "in_stock": snapshot.get("in_stock"),
            "has_buy_box": snapshot.get("has_buy_box"),
            "average_rating": rating,
            "content_score": content,
            "primary_keyword_rank": snapshot.get("primary_keyword_rank")
        })

    if ratings:
        overview["avg_rating"] = sum(ratings) / len(ratings)
    if content_scores:
        overview["avg_content_score"] = sum(content_scores) / len(content_scores)

    return overview


# =============================================================================
# Whitelist Registration
# =============================================================================

def _wrap_for_whitelist():
    """Register API functions with frappe.whitelist()."""
    frappe = _get_frappe()

    global create_snapshot, get_latest_snapshot, get_product_shelf_status
    global compare_snapshots, get_snapshot_history, get_channel_shelf_overview

    create_snapshot = frappe.whitelist()(create_snapshot)
    get_latest_snapshot = frappe.whitelist()(get_latest_snapshot)
    get_product_shelf_status = frappe.whitelist()(get_product_shelf_status)
    compare_snapshots = frappe.whitelist()(compare_snapshots)
    get_snapshot_history = frappe.whitelist()(get_snapshot_history)
    get_channel_shelf_overview = frappe.whitelist()(get_channel_shelf_overview)


# Register on module load
try:
    _wrap_for_whitelist()
except Exception:
    pass  # Will be registered when frappe is available
