"""Search Rank Tracker Service

This module provides services for monitoring product search visibility and rankings
across marketplace channels. It tracks keyword positions, organic rankings, and
search performance metrics for digital shelf analytics.

The service supports:
- Keyword rank tracking across multiple channels
- Historical rank data storage and trend analysis
- Rank change detection and alerting
- Scheduled automated tracking
- Channel-specific search scraping/API integration
- Competitive rank analysis

Key Concepts:
- Keyword: A search term used to find products on a marketplace
- Rank: The position of a product in search results for a keyword
- SERP: Search Engine Results Page - the list of products returned for a search
- Share of Search: Percentage of keywords where product ranks in top positions

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


# =============================================================================
# Constants and Enums
# =============================================================================

class RankTrackingMethod(Enum):
    """Methods for obtaining search rank data."""
    API = "api"
    SCRAPING = "scraping"
    BROWSER_AUTOMATION = "browser_automation"
    CHANNEL_FEED = "channel_feed"
    MANUAL = "manual"


class RankChangeType(Enum):
    """Types of rank changes."""
    IMPROVED = "improved"
    DECLINED = "declined"
    NO_CHANGE = "no_change"
    NEW_RANKING = "new_ranking"
    LOST_RANKING = "lost_ranking"
    REGAINED = "regained"


class RankAlertSeverity(Enum):
    """Severity levels for rank change alerts."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SearchResultType(Enum):
    """Types of search result positions."""
    ORGANIC = "organic"
    SPONSORED = "sponsored"
    RECOMMENDED = "recommended"
    BEST_SELLER = "best_seller"
    FEATURED = "featured"


# Rank thresholds for visibility tiers
RANK_TIERS = {
    "top_3": 3,
    "top_10": 10,
    "first_page": 20,
    "second_page": 40,
    "third_page": 60,
    "beyond": float("inf")
}

# Channel-specific search API endpoints (for reference)
CHANNEL_SEARCH_CONFIG = {
    "amazon": {
        "search_url": "https://www.amazon.{domain}/s",
        "results_per_page": 48,
        "max_pages": 5,
        "rate_limit_per_minute": 10
    },
    "shopify": {
        "search_url": "{store_url}/search",
        "results_per_page": 24,
        "max_pages": 10,
        "rate_limit_per_minute": 30
    },
    "google_shopping": {
        "search_url": "https://www.google.com/shopping",
        "results_per_page": 30,
        "max_pages": 3,
        "rate_limit_per_minute": 5
    },
    "trendyol": {
        "search_url": "https://www.trendyol.com/sr",
        "results_per_page": 24,
        "max_pages": 10,
        "rate_limit_per_minute": 15
    },
    "hepsiburada": {
        "search_url": "https://www.hepsiburada.com/ara",
        "results_per_page": 36,
        "max_pages": 10,
        "rate_limit_per_minute": 15
    }
}


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class KeywordConfig:
    """Configuration for tracking a keyword."""
    keyword: str
    is_primary: bool = False
    track_organic: bool = True
    track_sponsored: bool = False
    target_rank: int = 10
    alert_threshold: int = 20
    category_filter: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "keyword": self.keyword,
            "is_primary": self.is_primary,
            "track_organic": self.track_organic,
            "track_sponsored": self.track_sponsored,
            "target_rank": self.target_rank,
            "alert_threshold": self.alert_threshold,
            "category_filter": self.category_filter,
        }


@dataclass
class RankResult:
    """Result of a single rank check."""
    keyword: str
    rank: Optional[int]
    page: int = 1
    result_type: SearchResultType = SearchResultType.ORGANIC
    total_results: int = 0
    found: bool = False
    url: Optional[str] = None
    title: Optional[str] = None
    price: Optional[float] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "keyword": self.keyword,
            "rank": self.rank,
            "page": self.page,
            "result_type": self.result_type.value,
            "total_results": self.total_results,
            "found": self.found,
            "url": self.url,
            "title": self.title,
            "price": self.price,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class RankChange:
    """Represents a change in rank between two tracking periods."""
    keyword: str
    previous_rank: Optional[int]
    current_rank: Optional[int]
    change_amount: int = 0
    change_type: RankChangeType = RankChangeType.NO_CHANGE
    severity: RankAlertSeverity = RankAlertSeverity.LOW

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "keyword": self.keyword,
            "previous_rank": self.previous_rank,
            "current_rank": self.current_rank,
            "change_amount": self.change_amount,
            "change_type": self.change_type.value,
            "severity": self.severity.value,
        }


@dataclass
class TrackingResult:
    """Result of a complete tracking run for a product/channel."""
    product: str
    channel: str
    success: bool
    keywords_tracked: int = 0
    keywords_ranked: int = 0
    avg_rank: Optional[float] = None
    best_rank: Optional[int] = None
    worst_rank: Optional[int] = None
    top_3_count: int = 0
    top_10_count: int = 0
    first_page_count: int = 0
    share_of_search: float = 0.0
    rank_results: List[RankResult] = field(default_factory=list)
    rank_changes: List[RankChange] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    tracking_method: RankTrackingMethod = RankTrackingMethod.API
    timestamp: datetime = field(default_factory=datetime.utcnow)
    duration_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "product": self.product,
            "channel": self.channel,
            "success": self.success,
            "keywords_tracked": self.keywords_tracked,
            "keywords_ranked": self.keywords_ranked,
            "avg_rank": self.avg_rank,
            "best_rank": self.best_rank,
            "worst_rank": self.worst_rank,
            "top_3_count": self.top_3_count,
            "top_10_count": self.top_10_count,
            "first_page_count": self.first_page_count,
            "share_of_search": self.share_of_search,
            "rank_results": [r.to_dict() for r in self.rank_results],
            "rank_changes": [c.to_dict() for c in self.rank_changes],
            "errors": self.errors,
            "tracking_method": self.tracking_method.value,
            "timestamp": self.timestamp.isoformat(),
            "duration_ms": self.duration_ms,
        }


@dataclass
class TrendData:
    """Trend data for a keyword over time."""
    keyword: str
    product: str
    channel: str
    data_points: List[Dict[str, Any]] = field(default_factory=list)
    avg_rank: Optional[float] = None
    rank_volatility: float = 0.0
    trend_direction: str = "stable"
    best_rank: Optional[int] = None
    worst_rank: Optional[int] = None
    days_in_top_10: int = 0
    days_on_first_page: int = 0
    total_days: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "keyword": self.keyword,
            "product": self.product,
            "channel": self.channel,
            "data_points": self.data_points,
            "avg_rank": self.avg_rank,
            "rank_volatility": self.rank_volatility,
            "trend_direction": self.trend_direction,
            "best_rank": self.best_rank,
            "worst_rank": self.worst_rank,
            "days_in_top_10": self.days_in_top_10,
            "days_on_first_page": self.days_on_first_page,
            "total_days": self.total_days,
        }


# =============================================================================
# Search Rank Tracker Service
# =============================================================================

class SearchRankTrackerService:
    """Service for tracking product search rankings across channels.

    This service provides high-level operations for search rank monitoring,
    including rank tracking, trend analysis, and alert generation.

    Attributes:
        product: Product name to track
        channel: Channel name to track on
        keywords: List of keywords to track
    """

    def __init__(
        self,
        product: Optional[str] = None,
        channel: Optional[str] = None,
        keywords: Optional[List[KeywordConfig]] = None
    ):
        """Initialize the search rank tracker service.

        Args:
            product: Product name to track
            channel: Channel name to track on
            keywords: List of keyword configurations
        """
        self.product = product
        self.channel = channel
        self.keywords = keywords or []
        self._channel_config = None

    @property
    def channel_config(self) -> Dict[str, Any]:
        """Get channel-specific configuration for search tracking."""
        if self._channel_config is None:
            self._channel_config = self._load_channel_config()
        return self._channel_config

    def _load_channel_config(self) -> Dict[str, Any]:
        """Load channel configuration from settings or defaults."""
        import frappe

        if not self.channel:
            return {}

        # Get channel type code
        try:
            channel_doc = frappe.get_doc("Channel", self.channel)
            channel_type = getattr(channel_doc, "channel_type", "").lower()
        except Exception:
            channel_type = self.channel.lower()

        # Return channel-specific config or empty dict
        return CHANNEL_SEARCH_CONFIG.get(channel_type, {})

    def track_keywords(
        self,
        product_identifier: Optional[str] = None,
        max_pages: int = 3,
        tracking_method: RankTrackingMethod = RankTrackingMethod.API
    ) -> TrackingResult:
        """Track rankings for all configured keywords.

        Args:
            product_identifier: Identifier to search for (SKU, GTIN, ASIN, etc.)
            max_pages: Maximum pages to search
            tracking_method: Method to use for tracking

        Returns:
            TrackingResult with complete tracking data
        """
        import frappe
        import time

        start_time = time.time()

        result = TrackingResult(
            product=self.product or "",
            channel=self.channel or "",
            success=True,
            tracking_method=tracking_method,
        )

        if not self.keywords:
            result.success = False
            result.errors.append("No keywords configured for tracking")
            return result

        # Get product identifier if not provided
        if not product_identifier and self.product:
            product_identifier = self._get_product_identifier()

        rank_results = []
        ranks_found = []

        for keyword_config in self.keywords:
            try:
                rank_result = self._track_single_keyword(
                    keyword=keyword_config.keyword,
                    product_identifier=product_identifier,
                    max_pages=max_pages,
                    tracking_method=tracking_method,
                    track_sponsored=keyword_config.track_sponsored,
                    category_filter=keyword_config.category_filter
                )
                rank_results.append(rank_result)

                if rank_result.found and rank_result.rank:
                    ranks_found.append(rank_result.rank)

                    # Count visibility tiers
                    if rank_result.rank <= 3:
                        result.top_3_count += 1
                    if rank_result.rank <= 10:
                        result.top_10_count += 1
                    if rank_result.rank <= RANK_TIERS["first_page"]:
                        result.first_page_count += 1

            except Exception as e:
                result.errors.append(f"Error tracking '{keyword_config.keyword}': {str(e)}")
                frappe.log_error(
                    message=f"Keyword tracking error: {str(e)}",
                    title=f"Search Rank Tracker - {keyword_config.keyword}"
                )

        # Calculate aggregate metrics
        result.rank_results = rank_results
        result.keywords_tracked = len(rank_results)
        result.keywords_ranked = len(ranks_found)

        if ranks_found:
            result.avg_rank = sum(ranks_found) / len(ranks_found)
            result.best_rank = min(ranks_found)
            result.worst_rank = max(ranks_found)

        if result.keywords_tracked > 0:
            result.share_of_search = (result.first_page_count / result.keywords_tracked) * 100

        # Detect rank changes from previous tracking
        result.rank_changes = self._detect_rank_changes(rank_results)

        # Calculate duration
        result.duration_ms = int((time.time() - start_time) * 1000)

        # Save results
        self._save_tracking_results(result)

        return result

    def _track_single_keyword(
        self,
        keyword: str,
        product_identifier: Optional[str] = None,
        max_pages: int = 3,
        tracking_method: RankTrackingMethod = RankTrackingMethod.API,
        track_sponsored: bool = False,
        category_filter: Optional[str] = None
    ) -> RankResult:
        """Track ranking for a single keyword.

        Args:
            keyword: Search keyword
            product_identifier: Product identifier to find
            max_pages: Maximum pages to search
            tracking_method: Method to use for tracking
            track_sponsored: Whether to track sponsored positions
            category_filter: Optional category to filter by

        Returns:
            RankResult with rank data
        """
        result = RankResult(
            keyword=keyword,
            rank=None,
            found=False,
        )

        if tracking_method == RankTrackingMethod.API:
            result = self._track_via_api(
                keyword, product_identifier, max_pages,
                track_sponsored, category_filter
            )
        elif tracking_method == RankTrackingMethod.SCRAPING:
            result = self._track_via_scraping(
                keyword, product_identifier, max_pages,
                track_sponsored, category_filter
            )
        elif tracking_method == RankTrackingMethod.CHANNEL_FEED:
            result = self._track_via_channel_feed(keyword, product_identifier)
        else:
            # Manual or browser automation - return empty result
            result.found = False

        return result

    def _track_via_api(
        self,
        keyword: str,
        product_identifier: Optional[str],
        max_pages: int,
        track_sponsored: bool,
        category_filter: Optional[str]
    ) -> RankResult:
        """Track ranking using channel API.

        This method uses the channel adapter's search capabilities
        to find product rankings.
        """
        import frappe

        result = RankResult(keyword=keyword, rank=None, found=False)

        try:
            # Get channel adapter
            from frappe_pim.pim.channels.base import get_adapter

            if not self.channel:
                return result

            channel_doc = frappe.get_doc("Channel", self.channel)
            channel_type = getattr(channel_doc, "channel_type", "").lower()

            # Check if adapter has search capability
            try:
                adapter = get_adapter(channel_type, channel_doc)
            except Exception:
                # Channel adapter not available, return empty result
                return result

            # Search using adapter if it has search method
            if hasattr(adapter, 'search_products'):
                search_results = adapter.search_products(
                    query=keyword,
                    max_results=max_pages * 50,
                    category=category_filter
                )

                # Find our product in results
                position = 1
                for item in search_results.get("results", []):
                    item_id = item.get("id") or item.get("sku") or item.get("asin")
                    if item_id and product_identifier and item_id == product_identifier:
                        result.rank = position
                        result.found = True
                        result.page = (position - 1) // 24 + 1  # Approximate page
                        result.url = item.get("url")
                        result.title = item.get("title")
                        result.price = item.get("price")
                        result.total_results = search_results.get("total", 0)
                        break
                    position += 1

        except Exception as e:
            frappe.log_error(
                message=f"API tracking error for '{keyword}': {str(e)}",
                title="Search Rank Tracker API Error"
            )

        return result

    def _track_via_scraping(
        self,
        keyword: str,
        product_identifier: Optional[str],
        max_pages: int,
        track_sponsored: bool,
        category_filter: Optional[str]
    ) -> RankResult:
        """Track ranking via web scraping.

        Note: Web scraping should be used carefully and may violate
        terms of service of some platforms. This is a placeholder
        implementation.
        """
        import frappe

        result = RankResult(keyword=keyword, rank=None, found=False)

        # Scraping implementation would go here
        # This is intentionally not fully implemented as scraping
        # may violate marketplace terms of service

        frappe.log_error(
            message="Web scraping is not fully implemented",
            title="Search Rank Tracker - Scraping"
        )

        return result

    def _track_via_channel_feed(
        self,
        keyword: str,
        product_identifier: Optional[str]
    ) -> RankResult:
        """Track ranking from channel feed data.

        Uses previously downloaded channel data to determine rankings.
        """
        result = RankResult(keyword=keyword, rank=None, found=False)

        # Channel feed tracking would use stored feed data
        # This is a placeholder for future implementation

        return result

    def _get_product_identifier(self) -> Optional[str]:
        """Get the identifier to use for searching this product."""
        import frappe

        if not self.product:
            return None

        try:
            # Try to get Product Master document
            product_doc = frappe.get_doc("Product Master", self.product)

            # Return the first available identifier
            for field in ["sku", "gtin", "barcode", "asin", "item_code"]:
                value = getattr(product_doc, field, None)
                if value:
                    return value

            return self.product
        except Exception:
            return self.product

    def _detect_rank_changes(
        self,
        current_results: List[RankResult]
    ) -> List[RankChange]:
        """Detect rank changes from previous tracking run.

        Args:
            current_results: Current rank results

        Returns:
            List of RankChange objects
        """
        import frappe

        changes = []

        if not self.product or not self.channel:
            return changes

        # Get previous tracking data
        previous_data = self._get_previous_rankings()

        for result in current_results:
            keyword = result.keyword
            current_rank = result.rank if result.found else None
            previous_rank = previous_data.get(keyword)

            change = RankChange(
                keyword=keyword,
                previous_rank=previous_rank,
                current_rank=current_rank,
            )

            # Determine change type and amount
            if previous_rank is None and current_rank is not None:
                change.change_type = RankChangeType.NEW_RANKING
                change.change_amount = 0
                change.severity = RankAlertSeverity.LOW
            elif previous_rank is not None and current_rank is None:
                change.change_type = RankChangeType.LOST_RANKING
                change.change_amount = 0
                change.severity = RankAlertSeverity.HIGH
            elif previous_rank is not None and current_rank is not None:
                change.change_amount = previous_rank - current_rank
                if change.change_amount > 0:
                    change.change_type = RankChangeType.IMPROVED
                    change.severity = RankAlertSeverity.LOW
                elif change.change_amount < 0:
                    change.change_type = RankChangeType.DECLINED
                    # Determine severity based on how much rank dropped
                    if abs(change.change_amount) >= 20:
                        change.severity = RankAlertSeverity.CRITICAL
                    elif abs(change.change_amount) >= 10:
                        change.severity = RankAlertSeverity.HIGH
                    elif abs(change.change_amount) >= 5:
                        change.severity = RankAlertSeverity.MEDIUM
                    else:
                        change.severity = RankAlertSeverity.LOW
                else:
                    change.change_type = RankChangeType.NO_CHANGE
                    change.severity = RankAlertSeverity.LOW

            changes.append(change)

        return changes

    def _get_previous_rankings(self) -> Dict[str, int]:
        """Get the most recent rankings for comparison."""
        import frappe

        rankings = {}

        if not self.product or not self.channel:
            return rankings

        try:
            # Get latest snapshot with search rankings
            snapshots = frappe.get_all(
                "Digital Shelf Snapshot",
                filters={
                    "product": self.product,
                    "channel": self.channel,
                    "search_rankings_json": ["is", "set"]
                },
                fields=["search_rankings_json"],
                order_by="snapshot_timestamp desc",
                limit=1
            )

            if snapshots and snapshots[0].search_rankings_json:
                import json
                rankings_data = json.loads(snapshots[0].search_rankings_json)
                if isinstance(rankings_data, list):
                    for item in rankings_data:
                        if isinstance(item, dict) and "keyword" in item and "rank" in item:
                            rankings[item["keyword"]] = item["rank"]

        except Exception:
            pass

        return rankings

    def _save_tracking_results(self, result: TrackingResult) -> Optional[str]:
        """Save tracking results to Digital Shelf Snapshot.

        Args:
            result: TrackingResult to save

        Returns:
            Snapshot document name if saved
        """
        import frappe
        import json

        if not result.product or not result.channel:
            return None

        try:
            # Prepare search rankings JSON
            rankings_json = []
            for rank_result in result.rank_results:
                rankings_json.append({
                    "keyword": rank_result.keyword,
                    "rank": rank_result.rank,
                    "page": rank_result.page,
                    "found": rank_result.found,
                    "result_type": rank_result.result_type.value,
                })

            # Get primary keyword info
            primary_keyword = None
            primary_rank = None
            primary_page = None

            for kw in self.keywords:
                if kw.is_primary:
                    for rr in result.rank_results:
                        if rr.keyword == kw.keyword:
                            primary_keyword = kw.keyword
                            primary_rank = rr.rank
                            primary_page = rr.page
                            break
                    break

            # If no primary keyword set, use first with rank
            if not primary_keyword and result.rank_results:
                for rr in result.rank_results:
                    if rr.found and rr.rank:
                        primary_keyword = rr.keyword
                        primary_rank = rr.rank
                        primary_page = rr.page
                        break

            # Create or update snapshot
            snapshot_data = {
                "product": result.product,
                "channel": result.channel,
                "snapshot_type": "Scheduled",
                "capture_method": result.tracking_method.value.upper(),
                "snapshot_timestamp": result.timestamp,
                "primary_keyword": primary_keyword,
                "primary_keyword_rank": primary_rank,
                "primary_keyword_page": primary_page,
                "search_rankings_json": json.dumps(rankings_json),
                "capture_duration_ms": result.duration_ms,
            }

            if result.errors:
                snapshot_data["capture_errors"] = "; ".join(result.errors[:3])

            # Create snapshot document
            doc = frappe.new_doc("Digital Shelf Snapshot")
            for field, value in snapshot_data.items():
                if hasattr(doc, field):
                    setattr(doc, field, value)

            doc.insert(ignore_permissions=True)
            frappe.db.commit()

            return doc.name

        except Exception as e:
            frappe.log_error(
                message=f"Failed to save tracking results: {str(e)}",
                title="Search Rank Tracker - Save Error"
            )
            return None

    def get_rank_trends(
        self,
        keyword: str,
        days: int = 30
    ) -> TrendData:
        """Get historical rank trend data for a keyword.

        Args:
            keyword: Keyword to get trends for
            days: Number of days of history

        Returns:
            TrendData with trend analysis
        """
        import frappe
        import json

        trend = TrendData(
            keyword=keyword,
            product=self.product or "",
            channel=self.channel or "",
        )

        if not self.product or not self.channel:
            return trend

        try:
            from_date = frappe.utils.add_to_date(
                frappe.utils.now_datetime(),
                days=-days
            )

            # Get historical snapshots
            snapshots = frappe.get_all(
                "Digital Shelf Snapshot",
                filters={
                    "product": self.product,
                    "channel": self.channel,
                    "snapshot_timestamp": [">=", from_date]
                },
                fields=["snapshot_timestamp", "search_rankings_json", "primary_keyword_rank"],
                order_by="snapshot_timestamp asc"
            )

            ranks = []
            data_points = []

            for snapshot in snapshots:
                rank = None

                # Try to get rank from search_rankings_json
                if snapshot.search_rankings_json:
                    try:
                        rankings = json.loads(snapshot.search_rankings_json)
                        for item in rankings:
                            if item.get("keyword") == keyword:
                                rank = item.get("rank")
                                break
                    except (json.JSONDecodeError, TypeError):
                        pass

                # Fallback to primary_keyword_rank if matches
                if rank is None and snapshot.primary_keyword_rank:
                    rank = snapshot.primary_keyword_rank

                data_points.append({
                    "date": snapshot.snapshot_timestamp,
                    "rank": rank,
                })

                if rank is not None:
                    ranks.append(rank)

            trend.data_points = data_points
            trend.total_days = len(set(dp["date"].date() if hasattr(dp["date"], "date") else dp["date"] for dp in data_points))

            if ranks:
                trend.avg_rank = sum(ranks) / len(ranks)
                trend.best_rank = min(ranks)
                trend.worst_rank = max(ranks)

                # Calculate volatility (standard deviation)
                if len(ranks) > 1:
                    mean = trend.avg_rank
                    variance = sum((r - mean) ** 2 for r in ranks) / len(ranks)
                    trend.rank_volatility = variance ** 0.5

                # Count days in top positions
                trend.days_in_top_10 = sum(1 for r in ranks if r <= 10)
                trend.days_on_first_page = sum(1 for r in ranks if r <= 20)

                # Determine trend direction
                if len(ranks) >= 3:
                    first_third = sum(ranks[:len(ranks)//3]) / (len(ranks)//3)
                    last_third = sum(ranks[-len(ranks)//3:]) / (len(ranks)//3)

                    if last_third < first_third - 3:
                        trend.trend_direction = "improving"
                    elif last_third > first_third + 3:
                        trend.trend_direction = "declining"
                    else:
                        trend.trend_direction = "stable"

        except Exception as e:
            frappe.log_error(
                message=f"Error getting trend data: {str(e)}",
                title="Search Rank Tracker - Trend Error"
            )

        return trend

    def create_rank_alert(
        self,
        change: RankChange,
        message: Optional[str] = None
    ) -> Optional[str]:
        """Create an alert for a significant rank change.

        Args:
            change: RankChange that triggered the alert
            message: Optional custom message

        Returns:
            Alert log name if created
        """
        import frappe

        if change.severity == RankAlertSeverity.LOW:
            return None

        try:
            if not message:
                if change.change_type == RankChangeType.LOST_RANKING:
                    message = f"Product lost ranking for '{change.keyword}'"
                elif change.change_type == RankChangeType.DECLINED:
                    message = (
                        f"Rank dropped {abs(change.change_amount)} positions "
                        f"for '{change.keyword}' (#{change.previous_rank} → #{change.current_rank})"
                    )
                else:
                    message = f"Rank change detected for '{change.keyword}'"

            # Log as error for visibility
            frappe.log_error(
                message=f"""
Product: {self.product}
Channel: {self.channel}
Keyword: {change.keyword}
Change: {change.change_type.value}
Previous Rank: {change.previous_rank}
Current Rank: {change.current_rank}
Severity: {change.severity.value}

{message}
                """,
                title=f"Search Rank Alert: {change.severity.value.upper()}"
            )

            return "alert_created"

        except Exception:
            return None


# =============================================================================
# Public API Functions
# =============================================================================

def track_product_rankings(
    product: str,
    channel: str,
    keywords: Optional[List[str]] = None,
    max_pages: int = 3,
    async_track: bool = False
) -> Dict[str, Any]:
    """Track search rankings for a product on a channel.

    This is the main API function for triggering rank tracking.

    Args:
        product: Product Master name
        channel: Channel name
        keywords: List of keywords to track (uses product keywords if not provided)
        max_pages: Maximum pages to search
        async_track: If True, run as background job

    Returns:
        Dictionary with tracking results or job ID
    """
    import frappe

    if async_track:
        job = frappe.enqueue(
            "frappe_pim.pim.services.search_rank_tracker._track_rankings_job",
            queue="long",
            timeout=1800,
            product=product,
            channel=channel,
            keywords=keywords,
            max_pages=max_pages
        )
        return {
            "success": True,
            "job_id": job.id if hasattr(job, "id") else str(job),
            "status": "queued"
        }

    # Build keyword configs
    keyword_configs = []
    if keywords:
        for i, kw in enumerate(keywords):
            keyword_configs.append(KeywordConfig(
                keyword=kw,
                is_primary=(i == 0)
            ))
    else:
        # Get keywords from product
        keyword_configs = _get_product_keywords(product)

    service = SearchRankTrackerService(
        product=product,
        channel=channel,
        keywords=keyword_configs
    )

    result = service.track_keywords(max_pages=max_pages)
    return result.to_dict()


def get_product_rank_history(
    product: str,
    channel: str,
    keyword: Optional[str] = None,
    days: int = 30
) -> Dict[str, Any]:
    """Get historical rank data for a product.

    Args:
        product: Product Master name
        channel: Channel name
        keyword: Specific keyword (uses primary if not provided)
        days: Number of days of history

    Returns:
        Dictionary with historical rank data
    """
    import frappe
    import json

    result = {
        "product": product,
        "channel": channel,
        "days": days,
        "history": [],
        "summary": {}
    }

    try:
        from_date = frappe.utils.add_to_date(
            frappe.utils.now_datetime(),
            days=-days
        )

        snapshots = frappe.get_all(
            "Digital Shelf Snapshot",
            filters={
                "product": product,
                "channel": channel,
                "snapshot_timestamp": [">=", from_date]
            },
            fields=[
                "name", "snapshot_timestamp", "primary_keyword",
                "primary_keyword_rank", "primary_keyword_page",
                "search_rankings_json"
            ],
            order_by="snapshot_timestamp desc"
        )

        ranks = []
        for snapshot in snapshots:
            entry = {
                "date": snapshot.snapshot_timestamp,
                "primary_keyword": snapshot.primary_keyword,
                "primary_rank": snapshot.primary_keyword_rank,
                "primary_page": snapshot.primary_keyword_page,
            }

            # Get specific keyword if requested
            if keyword and snapshot.search_rankings_json:
                try:
                    rankings = json.loads(snapshot.search_rankings_json)
                    for item in rankings:
                        if item.get("keyword") == keyword:
                            entry["keyword_rank"] = item.get("rank")
                            if item.get("rank"):
                                ranks.append(item.get("rank"))
                            break
                except (json.JSONDecodeError, TypeError):
                    pass
            elif snapshot.primary_keyword_rank:
                ranks.append(snapshot.primary_keyword_rank)

            result["history"].append(entry)

        # Calculate summary
        if ranks:
            result["summary"] = {
                "avg_rank": sum(ranks) / len(ranks),
                "best_rank": min(ranks),
                "worst_rank": max(ranks),
                "data_points": len(ranks),
                "in_top_10_pct": (sum(1 for r in ranks if r <= 10) / len(ranks)) * 100,
                "in_first_page_pct": (sum(1 for r in ranks if r <= 20) / len(ranks)) * 100,
            }

    except Exception as e:
        frappe.log_error(
            message=f"Error getting rank history: {str(e)}",
            title="Search Rank Tracker - History Error"
        )

    return result


def get_rank_trends(
    product: str,
    channel: str,
    keyword: str,
    days: int = 30
) -> Dict[str, Any]:
    """Get trend analysis for a keyword's rankings.

    Args:
        product: Product Master name
        channel: Channel name
        keyword: Keyword to analyze
        days: Number of days of history

    Returns:
        Dictionary with trend analysis
    """
    service = SearchRankTrackerService(product=product, channel=channel)
    trend = service.get_rank_trends(keyword=keyword, days=days)
    return trend.to_dict()


def compare_channel_rankings(
    product: str,
    channels: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Compare rankings for a product across multiple channels.

    Args:
        product: Product Master name
        channels: List of channels (uses all channels if not provided)

    Returns:
        Dictionary with cross-channel comparison
    """
    import frappe
    import json

    result = {
        "product": product,
        "channels": {},
        "summary": {
            "best_channel": None,
            "worst_channel": None,
            "avg_rank_by_channel": {}
        }
    }

    try:
        if not channels:
            # Get all channels with snapshots for this product
            channels = frappe.get_all(
                "Digital Shelf Snapshot",
                filters={"product": product},
                pluck="channel",
                distinct=True
            )

        for channel in channels:
            # Get latest snapshot for each channel
            snapshots = frappe.get_all(
                "Digital Shelf Snapshot",
                filters={
                    "product": product,
                    "channel": channel
                },
                fields=[
                    "primary_keyword", "primary_keyword_rank",
                    "search_rankings_json"
                ],
                order_by="snapshot_timestamp desc",
                limit=1
            )

            if snapshots:
                snapshot = snapshots[0]
                channel_data = {
                    "primary_keyword": snapshot.primary_keyword,
                    "primary_rank": snapshot.primary_keyword_rank,
                    "keywords": []
                }

                if snapshot.search_rankings_json:
                    try:
                        rankings = json.loads(snapshot.search_rankings_json)
                        channel_data["keywords"] = rankings
                    except (json.JSONDecodeError, TypeError):
                        pass

                result["channels"][channel] = channel_data

                if snapshot.primary_keyword_rank:
                    result["summary"]["avg_rank_by_channel"][channel] = snapshot.primary_keyword_rank

        # Determine best/worst channels
        if result["summary"]["avg_rank_by_channel"]:
            best = min(
                result["summary"]["avg_rank_by_channel"].items(),
                key=lambda x: x[1]
            )
            worst = max(
                result["summary"]["avg_rank_by_channel"].items(),
                key=lambda x: x[1]
            )
            result["summary"]["best_channel"] = best[0]
            result["summary"]["worst_channel"] = worst[0]

    except Exception as e:
        frappe.log_error(
            message=f"Error comparing channel rankings: {str(e)}",
            title="Search Rank Tracker - Compare Error"
        )

    return result


def get_share_of_search(
    product: str,
    channel: str,
    threshold_rank: int = 20
) -> Dict[str, Any]:
    """Calculate share of search for a product.

    Share of search = percentage of tracked keywords where
    product ranks within threshold.

    Args:
        product: Product Master name
        channel: Channel name
        threshold_rank: Maximum rank to count as "visible"

    Returns:
        Dictionary with share of search metrics
    """
    import frappe
    import json

    result = {
        "product": product,
        "channel": channel,
        "threshold_rank": threshold_rank,
        "share_of_search": 0.0,
        "keywords_total": 0,
        "keywords_visible": 0,
        "keywords_top_3": 0,
        "keywords_top_10": 0,
        "keyword_details": []
    }

    try:
        # Get latest snapshot
        snapshots = frappe.get_all(
            "Digital Shelf Snapshot",
            filters={
                "product": product,
                "channel": channel
            },
            fields=["search_rankings_json"],
            order_by="snapshot_timestamp desc",
            limit=1
        )

        if snapshots and snapshots[0].search_rankings_json:
            rankings = json.loads(snapshots[0].search_rankings_json)

            for item in rankings:
                rank = item.get("rank")
                result["keywords_total"] += 1

                keyword_detail = {
                    "keyword": item.get("keyword"),
                    "rank": rank,
                    "visible": False
                }

                if rank is not None:
                    if rank <= threshold_rank:
                        result["keywords_visible"] += 1
                        keyword_detail["visible"] = True
                    if rank <= 3:
                        result["keywords_top_3"] += 1
                    if rank <= 10:
                        result["keywords_top_10"] += 1

                result["keyword_details"].append(keyword_detail)

            if result["keywords_total"] > 0:
                result["share_of_search"] = (
                    result["keywords_visible"] / result["keywords_total"]
                ) * 100

    except Exception as e:
        frappe.log_error(
            message=f"Error calculating share of search: {str(e)}",
            title="Search Rank Tracker - SOS Error"
        )

    return result


def schedule_rank_tracking(
    product: str,
    channel: str,
    keywords: List[str],
    frequency: str = "daily"
) -> Dict[str, Any]:
    """Schedule automated rank tracking for a product.

    Args:
        product: Product Master name
        channel: Channel name
        keywords: Keywords to track
        frequency: Tracking frequency (hourly, daily, weekly)

    Returns:
        Dictionary with schedule confirmation
    """
    import frappe

    # For now, this creates a note that would need to be implemented
    # with Frappe's scheduler hooks
    result = {
        "success": True,
        "product": product,
        "channel": channel,
        "keywords": keywords,
        "frequency": frequency,
        "message": f"Rank tracking scheduled ({frequency})"
    }

    try:
        # Store tracking configuration
        # In production, this would create a DocType entry
        # that the scheduled task reads from
        frappe.cache.set_value(
            f"rank_tracking:{product}:{channel}",
            {
                "keywords": keywords,
                "frequency": frequency,
                "enabled": True,
                "created": datetime.utcnow().isoformat()
            },
            expires_in_sec=86400 * 30  # 30 days
        )

    except Exception as e:
        result["success"] = False
        result["error"] = str(e)

    return result


# =============================================================================
# Helper Functions (Private)
# =============================================================================

def _get_product_keywords(product: str) -> List[KeywordConfig]:
    """Get tracking keywords configured for a product.

    Args:
        product: Product Master name

    Returns:
        List of KeywordConfig objects
    """
    import frappe

    keywords = []

    try:
        # Try to get keywords from product document
        product_doc = frappe.get_doc("Product Master", product)

        # Check for search_keywords field
        if hasattr(product_doc, "search_keywords") and product_doc.search_keywords:
            kw_list = [kw.strip() for kw in product_doc.search_keywords.split(",")]
            for i, kw in enumerate(kw_list):
                if kw:
                    keywords.append(KeywordConfig(
                        keyword=kw,
                        is_primary=(i == 0)
                    ))

        # Fallback to product name/title as keyword
        if not keywords:
            title = getattr(product_doc, "pim_title", None) or getattr(product_doc, "item_name", None)
            if title:
                keywords.append(KeywordConfig(
                    keyword=title,
                    is_primary=True
                ))

    except Exception:
        pass

    return keywords


def _track_rankings_job(
    product: str,
    channel: str,
    keywords: Optional[List[str]] = None,
    max_pages: int = 3
) -> Dict[str, Any]:
    """Background job for rank tracking.

    Args:
        product: Product Master name
        channel: Channel name
        keywords: Keywords to track
        max_pages: Maximum pages to search

    Returns:
        Tracking result dictionary
    """
    return track_product_rankings(
        product=product,
        channel=channel,
        keywords=keywords,
        max_pages=max_pages,
        async_track=False
    )


def scheduled_rank_tracking():
    """Scheduled task to run rank tracking for all configured products.

    This function should be called by Frappe's scheduler.
    """
    import frappe

    try:
        # Get all products with tracking enabled
        # In production, this would query a DocType with tracking configs
        tracked_products = frappe.cache.get_keys("rank_tracking:*")

        for key in tracked_products:
            try:
                config = frappe.cache.get_value(key)
                if config and config.get("enabled"):
                    parts = key.split(":")
                    if len(parts) >= 3:
                        product = parts[1]
                        channel = parts[2]
                        keywords = config.get("keywords", [])

                        track_product_rankings(
                            product=product,
                            channel=channel,
                            keywords=keywords,
                            async_track=True
                        )

            except Exception as e:
                frappe.log_error(
                    message=f"Error tracking {key}: {str(e)}",
                    title="Scheduled Rank Tracking Error"
                )

    except Exception as e:
        frappe.log_error(
            message=f"Scheduled rank tracking failed: {str(e)}",
            title="Scheduled Rank Tracking Error"
        )


# =============================================================================
# Frappe API Wrappers
# =============================================================================

def _wrap_for_whitelist():
    """Wrap functions for Frappe whitelist at runtime."""
    import frappe

    functions = [
        "track_product_rankings",
        "get_product_rank_history",
        "get_rank_trends",
        "compare_channel_rankings",
        "get_share_of_search",
        "schedule_rank_tracking",
    ]

    module = __import__(__name__)
    for name in __name__.split(".")[1:]:
        module = getattr(module, name)

    for func_name in functions:
        func = getattr(module, func_name)
        if not getattr(func, "_whitelisted", False):
            whitelisted = frappe.whitelist()(func)
            setattr(module, func_name, whitelisted)


# Apply whitelist decorators when module is loaded in Frappe context
try:
    _wrap_for_whitelist()
except Exception:
    pass  # Not in Frappe context
