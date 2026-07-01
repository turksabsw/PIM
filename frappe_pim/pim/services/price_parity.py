"""Price Parity Monitor Service

This module provides services for monitoring price parity across marketplace channels.
It tracks product prices, detects price discrepancies, monitors competitive pricing,
and generates alerts for significant price changes.

The service supports:
- Cross-channel price monitoring and comparison
- Price parity scoring (how aligned prices are across channels)
- Competitive price tracking
- Price history and trend analysis
- MAP (Minimum Advertised Price) violation detection
- Price change detection and alerting
- Currency conversion for international channels

Key Concepts:
- Price Parity: Consistency of product pricing across different channels
- MAP: Minimum Advertised Price - the lowest price a retailer can advertise
- Buy Box Price: The price displayed in the marketplace buy box
- List Price: The original/full price before discounts
- Sale Price: The current discounted/promotional price

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


# =============================================================================
# Constants and Enums
# =============================================================================

class ParityStatus(Enum):
    """Overall parity status across channels."""
    EXCELLENT = "excellent"  # < 1% variance
    GOOD = "good"            # 1-3% variance
    FAIR = "fair"            # 3-5% variance
    POOR = "poor"            # 5-10% variance
    CRITICAL = "critical"    # > 10% variance


class PriceChangeType(Enum):
    """Types of price changes."""
    INCREASE = "increase"
    DECREASE = "decrease"
    NO_CHANGE = "no_change"
    NEW_PRICE = "new_price"
    PRICE_REMOVED = "price_removed"


class AlertSeverity(Enum):
    """Severity levels for price alerts."""
    INFO = "info"
    WARNING = "warning"
    HIGH = "high"
    CRITICAL = "critical"


class PriceType(Enum):
    """Types of prices tracked."""
    LIST_PRICE = "list_price"
    SALE_PRICE = "sale_price"
    BUY_BOX_PRICE = "buy_box_price"
    MAP_PRICE = "map_price"
    WHOLESALE_PRICE = "wholesale_price"
    COMPETITOR_PRICE = "competitor_price"


class ViolationType(Enum):
    """Types of pricing policy violations."""
    MAP_VIOLATION = "map_violation"
    MSRP_VIOLATION = "msrp_violation"
    CHANNEL_CONFLICT = "channel_conflict"
    UNAUTHORIZED_DISCOUNT = "unauthorized_discount"
    PRICE_EROSION = "price_erosion"


# Price variance thresholds for parity status
PARITY_THRESHOLDS = {
    "excellent": 1.0,   # 1%
    "good": 3.0,        # 3%
    "fair": 5.0,        # 5%
    "poor": 10.0,       # 10%
    "critical": float("inf")
}

# Currency conversion rates (fallback - should use live rates in production)
CURRENCY_FALLBACK_RATES = {
    "USD": 1.0,
    "EUR": 1.08,
    "GBP": 1.27,
    "TRY": 0.032,
    "JPY": 0.0067,
    "CAD": 0.74,
    "AUD": 0.65,
    "MXN": 0.058,
    "BRL": 0.20,
}

# Channel-specific price monitoring config
CHANNEL_PRICE_CONFIG = {
    "amazon": {
        "supports_buy_box": True,
        "supports_offers": True,
        "currency": "USD",
        "update_frequency_hours": 4,
    },
    "shopify": {
        "supports_buy_box": False,
        "supports_offers": False,
        "currency": "USD",
        "update_frequency_hours": 6,
    },
    "trendyol": {
        "supports_buy_box": True,
        "supports_offers": True,
        "currency": "TRY",
        "update_frequency_hours": 4,
    },
    "hepsiburada": {
        "supports_buy_box": True,
        "supports_offers": True,
        "currency": "TRY",
        "update_frequency_hours": 4,
    },
    "google_shopping": {
        "supports_buy_box": False,
        "supports_offers": True,
        "currency": "USD",
        "update_frequency_hours": 12,
    },
    "walmart": {
        "supports_buy_box": True,
        "supports_offers": True,
        "currency": "USD",
        "update_frequency_hours": 4,
    },
    "ebay": {
        "supports_buy_box": False,
        "supports_offers": True,
        "currency": "USD",
        "update_frequency_hours": 6,
    },
}


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class PricePoint:
    """A single price observation for a product on a channel."""
    channel: str
    price: float
    currency: str = "USD"
    price_type: PriceType = PriceType.SALE_PRICE
    list_price: Optional[float] = None
    discount_percent: Optional[float] = None
    is_buy_box_winner: Optional[bool] = None
    seller: Optional[str] = None
    offers_count: Optional[int] = None
    lowest_offer: Optional[float] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    source: str = "api"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "channel": self.channel,
            "price": self.price,
            "currency": self.currency,
            "price_type": self.price_type.value,
            "list_price": self.list_price,
            "discount_percent": self.discount_percent,
            "is_buy_box_winner": self.is_buy_box_winner,
            "seller": self.seller,
            "offers_count": self.offers_count,
            "lowest_offer": self.lowest_offer,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
        }

    def to_base_currency(self, target_currency: str = "USD") -> float:
        """Convert price to target currency for comparison."""
        if self.currency == target_currency:
            return self.price

        # Get conversion rate
        source_rate = CURRENCY_FALLBACK_RATES.get(self.currency, 1.0)
        target_rate = CURRENCY_FALLBACK_RATES.get(target_currency, 1.0)

        # Convert to USD first, then to target
        usd_price = self.price * source_rate
        return usd_price / target_rate


@dataclass
class PriceComparison:
    """Comparison of prices between two channels or time periods."""
    reference_channel: str
    compare_channel: str
    reference_price: float
    compare_price: float
    difference: float = 0.0
    difference_percent: float = 0.0
    currency: str = "USD"
    is_parity: bool = True

    def __post_init__(self):
        """Calculate differences after initialization."""
        if self.reference_price > 0:
            self.difference = self.compare_price - self.reference_price
            self.difference_percent = (self.difference / self.reference_price) * 100
            self.is_parity = abs(self.difference_percent) < PARITY_THRESHOLDS["good"]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "reference_channel": self.reference_channel,
            "compare_channel": self.compare_channel,
            "reference_price": self.reference_price,
            "compare_price": self.compare_price,
            "difference": round(self.difference, 2),
            "difference_percent": round(self.difference_percent, 2),
            "currency": self.currency,
            "is_parity": self.is_parity,
        }


@dataclass
class PriceChange:
    """Represents a price change for a product on a channel."""
    channel: str
    previous_price: Optional[float]
    current_price: Optional[float]
    change_amount: float = 0.0
    change_percent: float = 0.0
    change_type: PriceChangeType = PriceChangeType.NO_CHANGE
    severity: AlertSeverity = AlertSeverity.INFO
    currency: str = "USD"

    def __post_init__(self):
        """Calculate change metrics after initialization."""
        if self.previous_price is None and self.current_price is not None:
            self.change_type = PriceChangeType.NEW_PRICE
            self.change_amount = 0
            self.change_percent = 0
        elif self.previous_price is not None and self.current_price is None:
            self.change_type = PriceChangeType.PRICE_REMOVED
            self.change_amount = 0
            self.change_percent = 0
        elif self.previous_price is not None and self.current_price is not None:
            self.change_amount = self.current_price - self.previous_price
            if self.previous_price > 0:
                self.change_percent = (self.change_amount / self.previous_price) * 100

            if self.change_amount > 0:
                self.change_type = PriceChangeType.INCREASE
            elif self.change_amount < 0:
                self.change_type = PriceChangeType.DECREASE
            else:
                self.change_type = PriceChangeType.NO_CHANGE

            # Determine severity based on change magnitude
            abs_percent = abs(self.change_percent)
            if abs_percent >= 20:
                self.severity = AlertSeverity.CRITICAL
            elif abs_percent >= 10:
                self.severity = AlertSeverity.HIGH
            elif abs_percent >= 5:
                self.severity = AlertSeverity.WARNING
            else:
                self.severity = AlertSeverity.INFO

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "channel": self.channel,
            "previous_price": self.previous_price,
            "current_price": self.current_price,
            "change_amount": round(self.change_amount, 2),
            "change_percent": round(self.change_percent, 2),
            "change_type": self.change_type.value,
            "severity": self.severity.value,
            "currency": self.currency,
        }


@dataclass
class PriceViolation:
    """Represents a pricing policy violation."""
    channel: str
    violation_type: ViolationType
    current_price: float
    threshold_price: float
    variance: float
    severity: AlertSeverity
    description: str
    detected_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "channel": self.channel,
            "violation_type": self.violation_type.value,
            "current_price": self.current_price,
            "threshold_price": self.threshold_price,
            "variance": round(self.variance, 2),
            "severity": self.severity.value,
            "description": self.description,
            "detected_at": self.detected_at.isoformat(),
        }


@dataclass
class ParityResult:
    """Result of a price parity analysis across channels."""
    product: str
    base_currency: str = "USD"
    status: ParityStatus = ParityStatus.GOOD
    parity_score: float = 100.0
    price_variance: float = 0.0
    avg_price: float = 0.0
    min_price: float = 0.0
    max_price: float = 0.0
    price_spread: float = 0.0
    channels_monitored: int = 0
    channels_with_prices: int = 0
    price_points: List[PricePoint] = field(default_factory=list)
    comparisons: List[PriceComparison] = field(default_factory=list)
    price_changes: List[PriceChange] = field(default_factory=list)
    violations: List[PriceViolation] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    duration_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "product": self.product,
            "base_currency": self.base_currency,
            "status": self.status.value,
            "parity_score": round(self.parity_score, 2),
            "price_variance": round(self.price_variance, 2),
            "avg_price": round(self.avg_price, 2),
            "min_price": round(self.min_price, 2),
            "max_price": round(self.max_price, 2),
            "price_spread": round(self.price_spread, 2),
            "channels_monitored": self.channels_monitored,
            "channels_with_prices": self.channels_with_prices,
            "price_points": [p.to_dict() for p in self.price_points],
            "comparisons": [c.to_dict() for c in self.comparisons],
            "price_changes": [c.to_dict() for c in self.price_changes],
            "violations": [v.to_dict() for v in self.violations],
            "errors": self.errors,
            "timestamp": self.timestamp.isoformat(),
            "duration_ms": self.duration_ms,
        }


@dataclass
class PriceTrend:
    """Price trend data over time for a product/channel."""
    product: str
    channel: str
    data_points: List[Dict[str, Any]] = field(default_factory=list)
    avg_price: Optional[float] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    price_volatility: float = 0.0
    trend_direction: str = "stable"
    total_days: int = 0
    days_on_promotion: int = 0
    avg_discount_percent: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "product": self.product,
            "channel": self.channel,
            "data_points": self.data_points,
            "avg_price": round(self.avg_price, 2) if self.avg_price else None,
            "min_price": round(self.min_price, 2) if self.min_price else None,
            "max_price": round(self.max_price, 2) if self.max_price else None,
            "price_volatility": round(self.price_volatility, 2),
            "trend_direction": self.trend_direction,
            "total_days": self.total_days,
            "days_on_promotion": self.days_on_promotion,
            "avg_discount_percent": round(self.avg_discount_percent, 2),
        }


@dataclass
class CompetitorPrice:
    """Competitive price information for a product."""
    product: str
    channel: str
    competitor_name: str
    competitor_price: float
    our_price: float
    difference: float = 0.0
    difference_percent: float = 0.0
    competitor_is_cheaper: bool = False
    is_buy_box_winner: bool = False
    last_updated: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self):
        """Calculate difference after initialization."""
        if self.our_price > 0:
            self.difference = self.competitor_price - self.our_price
            self.difference_percent = (self.difference / self.our_price) * 100
            self.competitor_is_cheaper = self.competitor_price < self.our_price

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "product": self.product,
            "channel": self.channel,
            "competitor_name": self.competitor_name,
            "competitor_price": round(self.competitor_price, 2),
            "our_price": round(self.our_price, 2),
            "difference": round(self.difference, 2),
            "difference_percent": round(self.difference_percent, 2),
            "competitor_is_cheaper": self.competitor_is_cheaper,
            "is_buy_box_winner": self.is_buy_box_winner,
            "last_updated": self.last_updated.isoformat(),
        }


# =============================================================================
# Price Parity Monitor Service
# =============================================================================

class PriceParityMonitorService:
    """Service for monitoring price parity across channels.

    This service provides high-level operations for price monitoring,
    including cross-channel comparison, parity scoring, violation detection,
    and competitive analysis.

    Attributes:
        product: Product name to monitor
        channels: List of channels to monitor
        base_currency: Currency for price comparisons
        map_price: Optional MAP (Minimum Advertised Price)
        msrp_price: Optional MSRP (Manufacturer's Suggested Retail Price)
    """

    def __init__(
        self,
        product: Optional[str] = None,
        channels: Optional[List[str]] = None,
        base_currency: str = "USD",
        map_price: Optional[float] = None,
        msrp_price: Optional[float] = None
    ):
        """Initialize the price parity monitor service.

        Args:
            product: Product name to monitor
            channels: List of channel names to monitor
            base_currency: Currency for comparisons
            map_price: Minimum Advertised Price
            msrp_price: Manufacturer's Suggested Retail Price
        """
        self.product = product
        self.channels = channels or []
        self.base_currency = base_currency
        self.map_price = map_price
        self.msrp_price = msrp_price
        self._price_cache: Dict[str, PricePoint] = {}

    def monitor_prices(
        self,
        include_competitors: bool = True,
        check_violations: bool = True
    ) -> ParityResult:
        """Monitor prices across all configured channels.

        Args:
            include_competitors: Whether to include competitor prices
            check_violations: Whether to check for policy violations

        Returns:
            ParityResult with complete price monitoring data
        """
        import frappe
        import time

        start_time = time.time()

        result = ParityResult(
            product=self.product or "",
            base_currency=self.base_currency,
        )

        if not self.product:
            result.errors.append("No product specified for monitoring")
            return result

        if not self.channels:
            self.channels = self._get_configured_channels()

        result.channels_monitored = len(self.channels)

        # Collect price points from all channels
        price_points = []
        normalized_prices = []

        for channel in self.channels:
            try:
                price_point = self._get_channel_price(
                    channel,
                    include_competitors=include_competitors
                )
                if price_point:
                    price_points.append(price_point)

                    # Normalize to base currency
                    normalized_price = price_point.to_base_currency(self.base_currency)
                    normalized_prices.append(normalized_price)

                    self._price_cache[channel] = price_point

            except Exception as e:
                result.errors.append(f"Error getting price from {channel}: {str(e)}")
                frappe.log_error(
                    message=f"Price monitoring error for {channel}: {str(e)}",
                    title=f"Price Parity Monitor - {channel}"
                )

        result.price_points = price_points
        result.channels_with_prices = len(price_points)

        # Calculate aggregate metrics
        if normalized_prices:
            result.avg_price = sum(normalized_prices) / len(normalized_prices)
            result.min_price = min(normalized_prices)
            result.max_price = max(normalized_prices)
            result.price_spread = result.max_price - result.min_price

            # Calculate variance (coefficient of variation)
            if result.avg_price > 0:
                variance = sum((p - result.avg_price) ** 2 for p in normalized_prices) / len(normalized_prices)
                std_dev = variance ** 0.5
                result.price_variance = (std_dev / result.avg_price) * 100

            # Determine parity status and score
            result.status = self._determine_parity_status(result.price_variance)
            result.parity_score = self._calculate_parity_score(result.price_variance)

            # Generate channel comparisons
            result.comparisons = self._generate_comparisons(price_points)

        # Detect price changes from previous monitoring
        result.price_changes = self._detect_price_changes(price_points)

        # Check for violations if requested
        if check_violations:
            result.violations = self._check_violations(price_points)

        # Save results
        self._save_monitoring_results(result)

        # Calculate duration
        result.duration_ms = int((time.time() - start_time) * 1000)

        return result

    def _get_channel_price(
        self,
        channel: str,
        include_competitors: bool = True
    ) -> Optional[PricePoint]:
        """Get current price for a product on a channel.

        Args:
            channel: Channel name
            include_competitors: Whether to include competitor info

        Returns:
            PricePoint if price found, None otherwise
        """
        import frappe

        try:
            # First, try to get from recent Digital Shelf Snapshot
            snapshots = frappe.get_all(
                "Digital Shelf Snapshot",
                filters={
                    "product": self.product,
                    "channel": channel,
                    "current_price": [">", 0]
                },
                fields=[
                    "current_price", "list_price", "currency",
                    "discount_percent", "is_buy_box_winner",
                    "buy_box_seller", "offers_count", "snapshot_timestamp"
                ],
                order_by="snapshot_timestamp desc",
                limit=1
            )

            if snapshots:
                snapshot = snapshots[0]
                return PricePoint(
                    channel=channel,
                    price=snapshot.current_price,
                    currency=snapshot.currency or "USD",
                    price_type=PriceType.SALE_PRICE,
                    list_price=snapshot.list_price,
                    discount_percent=snapshot.discount_percent,
                    is_buy_box_winner=snapshot.is_buy_box_winner,
                    seller=snapshot.buy_box_seller,
                    offers_count=snapshot.offers_count,
                    timestamp=snapshot.snapshot_timestamp,
                    source="snapshot"
                )

            # Try to get live price via channel adapter
            return self._fetch_live_price(channel)

        except Exception as e:
            frappe.log_error(
                message=f"Error getting channel price: {str(e)}",
                title=f"Price Parity - {channel}"
            )
            return None

    def _fetch_live_price(self, channel: str) -> Optional[PricePoint]:
        """Fetch live price from channel API.

        Args:
            channel: Channel name

        Returns:
            PricePoint if price fetched, None otherwise
        """
        import frappe

        try:
            from frappe_pim.pim.channels.base import get_adapter

            channel_doc = frappe.get_doc("Channel", channel)
            channel_type = getattr(channel_doc, "channel_type", "").lower()

            try:
                adapter = get_adapter(channel_type, channel_doc)
            except Exception:
                return None

            # Check if adapter has get_product_price method
            if hasattr(adapter, 'get_product_price'):
                price_data = adapter.get_product_price(self.product)
                if price_data:
                    return PricePoint(
                        channel=channel,
                        price=price_data.get("price", 0),
                        currency=price_data.get("currency", "USD"),
                        price_type=PriceType.SALE_PRICE,
                        list_price=price_data.get("list_price"),
                        discount_percent=price_data.get("discount_percent"),
                        is_buy_box_winner=price_data.get("is_buy_box_winner"),
                        seller=price_data.get("seller"),
                        offers_count=price_data.get("offers_count"),
                        source="api"
                    )

        except Exception as e:
            frappe.log_error(
                message=f"Error fetching live price: {str(e)}",
                title=f"Price Parity - Live Fetch"
            )

        return None

    def _get_configured_channels(self) -> List[str]:
        """Get channels configured for the product.

        Returns:
            List of channel names
        """
        import frappe

        channels = []

        try:
            # Get channels from product publish history
            channel_names = frappe.get_all(
                "Channel Publish Log",
                filters={"product": self.product},
                pluck="channel",
                distinct=True
            )
            channels.extend(channel_names)

            # Also get channels with price snapshots
            snapshot_channels = frappe.get_all(
                "Digital Shelf Snapshot",
                filters={"product": self.product},
                pluck="channel",
                distinct=True
            )
            for ch in snapshot_channels:
                if ch not in channels:
                    channels.append(ch)

        except Exception:
            pass

        return channels

    def _determine_parity_status(self, variance: float) -> ParityStatus:
        """Determine parity status from price variance.

        Args:
            variance: Price variance percentage

        Returns:
            ParityStatus enum value
        """
        if variance < PARITY_THRESHOLDS["excellent"]:
            return ParityStatus.EXCELLENT
        elif variance < PARITY_THRESHOLDS["good"]:
            return ParityStatus.GOOD
        elif variance < PARITY_THRESHOLDS["fair"]:
            return ParityStatus.FAIR
        elif variance < PARITY_THRESHOLDS["poor"]:
            return ParityStatus.POOR
        else:
            return ParityStatus.CRITICAL

    def _calculate_parity_score(self, variance: float) -> float:
        """Calculate parity score from variance (0-100).

        Args:
            variance: Price variance percentage

        Returns:
            Parity score (100 = perfect parity)
        """
        if variance <= 0:
            return 100.0
        elif variance >= 20:
            return 0.0
        else:
            # Linear decay from 100 to 0 as variance goes from 0 to 20
            return max(0, 100 - (variance * 5))

    def _generate_comparisons(
        self,
        price_points: List[PricePoint]
    ) -> List[PriceComparison]:
        """Generate pairwise comparisons between channels.

        Args:
            price_points: List of price points to compare

        Returns:
            List of PriceComparison objects
        """
        comparisons = []

        if len(price_points) < 2:
            return comparisons

        # Use first channel as reference
        reference = price_points[0]
        ref_price = reference.to_base_currency(self.base_currency)

        for i in range(1, len(price_points)):
            compare = price_points[i]
            comp_price = compare.to_base_currency(self.base_currency)

            comparison = PriceComparison(
                reference_channel=reference.channel,
                compare_channel=compare.channel,
                reference_price=ref_price,
                compare_price=comp_price,
                currency=self.base_currency
            )
            comparisons.append(comparison)

        return comparisons

    def _detect_price_changes(
        self,
        current_prices: List[PricePoint]
    ) -> List[PriceChange]:
        """Detect price changes from previous monitoring.

        Args:
            current_prices: Current price points

        Returns:
            List of PriceChange objects
        """
        import frappe

        changes = []

        if not self.product:
            return changes

        # Get previous prices
        previous_prices = self._get_previous_prices()

        for price_point in current_prices:
            channel = price_point.channel
            current_price = price_point.to_base_currency(self.base_currency)
            previous_price = previous_prices.get(channel)

            change = PriceChange(
                channel=channel,
                previous_price=previous_price,
                current_price=current_price,
                currency=self.base_currency
            )

            changes.append(change)

        return changes

    def _get_previous_prices(self) -> Dict[str, float]:
        """Get prices from previous monitoring run.

        Returns:
            Dictionary mapping channel to previous price
        """
        import frappe
        import json

        prices = {}

        if not self.product:
            return prices

        try:
            # Get latest snapshot for each channel
            for channel in self.channels:
                snapshots = frappe.get_all(
                    "Digital Shelf Snapshot",
                    filters={
                        "product": self.product,
                        "channel": channel,
                        "current_price": [">", 0]
                    },
                    fields=["current_price", "currency"],
                    order_by="snapshot_timestamp desc",
                    limit=2  # Get last 2 to find previous
                )

                if len(snapshots) >= 2:
                    # Second most recent is previous
                    prev = snapshots[1]
                    # Normalize to base currency
                    rate = CURRENCY_FALLBACK_RATES.get(prev.currency or "USD", 1.0)
                    base_rate = CURRENCY_FALLBACK_RATES.get(self.base_currency, 1.0)
                    prices[channel] = (prev.current_price * rate) / base_rate

        except Exception:
            pass

        return prices

    def _check_violations(
        self,
        price_points: List[PricePoint]
    ) -> List[PriceViolation]:
        """Check for pricing policy violations.

        Args:
            price_points: Price points to check

        Returns:
            List of PriceViolation objects
        """
        violations = []

        for price_point in price_points:
            normalized_price = price_point.to_base_currency(self.base_currency)

            # Check MAP violation
            if self.map_price and normalized_price < self.map_price:
                variance = ((self.map_price - normalized_price) / self.map_price) * 100
                severity = AlertSeverity.CRITICAL if variance > 10 else AlertSeverity.HIGH

                violations.append(PriceViolation(
                    channel=price_point.channel,
                    violation_type=ViolationType.MAP_VIOLATION,
                    current_price=normalized_price,
                    threshold_price=self.map_price,
                    variance=variance,
                    severity=severity,
                    description=f"Price {variance:.1f}% below MAP ({self.base_currency} {self.map_price})"
                ))

            # Check MSRP violation (selling above MSRP)
            if self.msrp_price and normalized_price > self.msrp_price * 1.1:  # 10% above MSRP
                variance = ((normalized_price - self.msrp_price) / self.msrp_price) * 100
                severity = AlertSeverity.WARNING

                violations.append(PriceViolation(
                    channel=price_point.channel,
                    violation_type=ViolationType.MSRP_VIOLATION,
                    current_price=normalized_price,
                    threshold_price=self.msrp_price,
                    variance=variance,
                    severity=severity,
                    description=f"Price {variance:.1f}% above MSRP ({self.base_currency} {self.msrp_price})"
                ))

        # Check for channel conflict (significant price differences)
        if len(price_points) >= 2:
            prices = [p.to_base_currency(self.base_currency) for p in price_points]
            min_price = min(prices)
            max_price = max(prices)

            if min_price > 0:
                spread_percent = ((max_price - min_price) / min_price) * 100

                if spread_percent > 15:  # More than 15% spread
                    severity = AlertSeverity.HIGH if spread_percent > 25 else AlertSeverity.WARNING

                    # Find channels with extreme prices
                    for pp in price_points:
                        pp_price = pp.to_base_currency(self.base_currency)
                        if pp_price == min_price or pp_price == max_price:
                            violations.append(PriceViolation(
                                channel=pp.channel,
                                violation_type=ViolationType.CHANNEL_CONFLICT,
                                current_price=pp_price,
                                threshold_price=sum(prices) / len(prices),
                                variance=spread_percent,
                                severity=severity,
                                description=f"Price spread of {spread_percent:.1f}% across channels"
                            ))
                            break  # Only add one violation for channel conflict

        return violations

    def _save_monitoring_results(self, result: ParityResult) -> Optional[str]:
        """Save monitoring results.

        Args:
            result: ParityResult to save

        Returns:
            Saved document name if successful
        """
        import frappe
        import json

        if not result.product:
            return None

        try:
            # Update Digital Shelf Snapshots with parity data
            # For now, log the result for visibility
            if result.violations:
                frappe.log_error(
                    message=f"""
Price Parity Alert for {result.product}

Status: {result.status.value}
Parity Score: {result.parity_score:.1f}
Price Variance: {result.price_variance:.2f}%
Channels: {result.channels_with_prices} / {result.channels_monitored}

Violations:
{chr(10).join(f"- {v.channel}: {v.description}" for v in result.violations)}
                    """,
                    title=f"Price Parity Alert - {result.product}"
                )

            return "saved"

        except Exception as e:
            frappe.log_error(
                message=f"Failed to save monitoring results: {str(e)}",
                title="Price Parity - Save Error"
            )
            return None

    def get_price_history(
        self,
        channel: str,
        days: int = 30
    ) -> PriceTrend:
        """Get price history for a product on a channel.

        Args:
            channel: Channel name
            days: Number of days of history

        Returns:
            PriceTrend with historical data
        """
        import frappe

        trend = PriceTrend(
            product=self.product or "",
            channel=channel,
        )

        if not self.product:
            return trend

        try:
            from_date = frappe.utils.add_to_date(
                frappe.utils.now_datetime(),
                days=-days
            )

            snapshots = frappe.get_all(
                "Digital Shelf Snapshot",
                filters={
                    "product": self.product,
                    "channel": channel,
                    "snapshot_timestamp": [">=", from_date],
                    "current_price": [">", 0]
                },
                fields=[
                    "snapshot_timestamp", "current_price", "list_price",
                    "currency", "discount_percent"
                ],
                order_by="snapshot_timestamp asc"
            )

            prices = []
            discounts = []
            data_points = []

            for snapshot in snapshots:
                # Normalize price
                rate = CURRENCY_FALLBACK_RATES.get(snapshot.currency or "USD", 1.0)
                base_rate = CURRENCY_FALLBACK_RATES.get(self.base_currency, 1.0)
                normalized_price = (snapshot.current_price * rate) / base_rate

                prices.append(normalized_price)

                if snapshot.discount_percent:
                    discounts.append(snapshot.discount_percent)

                data_points.append({
                    "date": snapshot.snapshot_timestamp,
                    "price": normalized_price,
                    "list_price": snapshot.list_price,
                    "discount_percent": snapshot.discount_percent,
                })

            trend.data_points = data_points
            trend.total_days = len(set(
                dp["date"].date() if hasattr(dp["date"], "date") else dp["date"]
                for dp in data_points
            ))

            if prices:
                trend.avg_price = sum(prices) / len(prices)
                trend.min_price = min(prices)
                trend.max_price = max(prices)

                # Calculate volatility
                if len(prices) > 1:
                    mean = trend.avg_price
                    variance = sum((p - mean) ** 2 for p in prices) / len(prices)
                    trend.price_volatility = variance ** 0.5

                # Determine trend direction
                if len(prices) >= 3:
                    first_third = sum(prices[:len(prices)//3]) / (len(prices)//3)
                    last_third = sum(prices[-len(prices)//3:]) / (len(prices)//3)

                    if last_third > first_third * 1.05:
                        trend.trend_direction = "increasing"
                    elif last_third < first_third * 0.95:
                        trend.trend_direction = "decreasing"
                    else:
                        trend.trend_direction = "stable"

            if discounts:
                trend.days_on_promotion = len([d for d in discounts if d > 0])
                trend.avg_discount_percent = sum(discounts) / len(discounts)

        except Exception as e:
            frappe.log_error(
                message=f"Error getting price history: {str(e)}",
                title="Price Parity - History Error"
            )

        return trend

    def get_competitor_prices(
        self,
        channel: str,
        max_competitors: int = 10
    ) -> List[CompetitorPrice]:
        """Get competitor prices for a product on a channel.

        Args:
            channel: Channel name
            max_competitors: Maximum competitors to return

        Returns:
            List of CompetitorPrice objects
        """
        import frappe
        import json

        competitors = []

        if not self.product:
            return competitors

        try:
            # Get our current price
            our_price = 0.0
            if channel in self._price_cache:
                our_price = self._price_cache[channel].to_base_currency(self.base_currency)
            else:
                price_point = self._get_channel_price(channel)
                if price_point:
                    our_price = price_point.to_base_currency(self.base_currency)

            # Get competitor data from snapshots
            snapshots = frappe.get_all(
                "Digital Shelf Snapshot",
                filters={
                    "product": self.product,
                    "channel": channel,
                    "competitor_prices_json": ["is", "set"]
                },
                fields=["competitor_prices_json", "snapshot_timestamp"],
                order_by="snapshot_timestamp desc",
                limit=1
            )

            if snapshots and snapshots[0].competitor_prices_json:
                try:
                    competitor_data = json.loads(snapshots[0].competitor_prices_json)

                    for comp in competitor_data[:max_competitors]:
                        if isinstance(comp, dict) and "price" in comp:
                            competitors.append(CompetitorPrice(
                                product=self.product,
                                channel=channel,
                                competitor_name=comp.get("seller", "Unknown"),
                                competitor_price=comp.get("price", 0),
                                our_price=our_price,
                                is_buy_box_winner=comp.get("is_buy_box_winner", False),
                            ))

                except (json.JSONDecodeError, TypeError):
                    pass

        except Exception as e:
            frappe.log_error(
                message=f"Error getting competitor prices: {str(e)}",
                title="Price Parity - Competitors Error"
            )

        return competitors

    def create_price_alert(
        self,
        change: PriceChange,
        message: Optional[str] = None
    ) -> Optional[str]:
        """Create an alert for a significant price change.

        Args:
            change: PriceChange that triggered the alert
            message: Optional custom message

        Returns:
            Alert identifier if created
        """
        import frappe

        if change.severity == AlertSeverity.INFO:
            return None

        try:
            if not message:
                if change.change_type == PriceChangeType.INCREASE:
                    message = (
                        f"Price increased {change.change_percent:.1f}% on {change.channel} "
                        f"({change.currency} {change.previous_price} -> {change.current_price})"
                    )
                elif change.change_type == PriceChangeType.DECREASE:
                    message = (
                        f"Price decreased {abs(change.change_percent):.1f}% on {change.channel} "
                        f"({change.currency} {change.previous_price} -> {change.current_price})"
                    )
                else:
                    message = f"Price change detected on {change.channel}"

            frappe.log_error(
                message=f"""
Product: {self.product}
Channel: {change.channel}
Change Type: {change.change_type.value}
Previous Price: {change.currency} {change.previous_price}
Current Price: {change.currency} {change.current_price}
Change: {change.change_percent:+.1f}%
Severity: {change.severity.value}

{message}
                """,
                title=f"Price Alert: {change.severity.value.upper()}"
            )

            return "alert_created"

        except Exception:
            return None


# =============================================================================
# Public API Functions
# =============================================================================

def monitor_product_prices(
    product: str,
    channels: Optional[List[str]] = None,
    base_currency: str = "USD",
    map_price: Optional[float] = None,
    async_monitor: bool = False
) -> Dict[str, Any]:
    """Monitor prices for a product across channels.

    This is the main API function for triggering price monitoring.

    Args:
        product: Product Master name
        channels: List of channels to monitor (uses configured if not provided)
        base_currency: Currency for comparisons
        map_price: Optional MAP to check against
        async_monitor: If True, run as background job

    Returns:
        Dictionary with monitoring results or job ID
    """
    import frappe

    if async_monitor:
        job = frappe.enqueue(
            "frappe_pim.pim.services.price_parity._monitor_prices_job",
            queue="long",
            timeout=1800,
            product=product,
            channels=channels,
            base_currency=base_currency,
            map_price=map_price
        )
        return {
            "success": True,
            "job_id": job.id if hasattr(job, "id") else str(job),
            "status": "queued"
        }

    service = PriceParityMonitorService(
        product=product,
        channels=channels,
        base_currency=base_currency,
        map_price=map_price
    )

    result = service.monitor_prices()
    return result.to_dict()


def get_price_parity_status(
    product: str,
    channels: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Get current price parity status for a product.

    Args:
        product: Product Master name
        channels: Specific channels to check

    Returns:
        Dictionary with parity status
    """
    service = PriceParityMonitorService(product=product, channels=channels)
    result = service.monitor_prices(include_competitors=False, check_violations=False)

    return {
        "product": product,
        "status": result.status.value,
        "parity_score": result.parity_score,
        "price_variance": result.price_variance,
        "channels_monitored": result.channels_monitored,
        "channels_with_prices": result.channels_with_prices,
        "avg_price": result.avg_price,
        "min_price": result.min_price,
        "max_price": result.max_price,
    }


def get_price_history(
    product: str,
    channel: str,
    days: int = 30
) -> Dict[str, Any]:
    """Get price history for a product on a channel.

    Args:
        product: Product Master name
        channel: Channel name
        days: Number of days of history

    Returns:
        Dictionary with price history data
    """
    service = PriceParityMonitorService(product=product)
    trend = service.get_price_history(channel=channel, days=days)
    return trend.to_dict()


def get_price_trends(
    product: str,
    channels: Optional[List[str]] = None,
    days: int = 30
) -> Dict[str, Any]:
    """Get price trends across multiple channels.

    Args:
        product: Product Master name
        channels: Channels to analyze
        days: Number of days of history

    Returns:
        Dictionary with cross-channel price trends
    """
    import frappe

    result = {
        "product": product,
        "days": days,
        "channels": {},
        "summary": {
            "most_volatile_channel": None,
            "most_stable_channel": None,
            "overall_trend": "stable"
        }
    }

    service = PriceParityMonitorService(product=product, channels=channels)

    if not channels:
        channels = service._get_configured_channels()

    volatilities = {}
    all_trends = []

    for channel in channels:
        try:
            trend = service.get_price_history(channel=channel, days=days)
            result["channels"][channel] = trend.to_dict()

            volatilities[channel] = trend.price_volatility

            if trend.trend_direction == "increasing":
                all_trends.append(1)
            elif trend.trend_direction == "decreasing":
                all_trends.append(-1)
            else:
                all_trends.append(0)

        except Exception as e:
            frappe.log_error(
                message=f"Error getting trend for {channel}: {str(e)}",
                title="Price Trends Error"
            )

    # Determine most/least volatile
    if volatilities:
        result["summary"]["most_volatile_channel"] = max(volatilities, key=volatilities.get)
        result["summary"]["most_stable_channel"] = min(volatilities, key=volatilities.get)

    # Determine overall trend
    if all_trends:
        avg_trend = sum(all_trends) / len(all_trends)
        if avg_trend > 0.3:
            result["summary"]["overall_trend"] = "increasing"
        elif avg_trend < -0.3:
            result["summary"]["overall_trend"] = "decreasing"
        else:
            result["summary"]["overall_trend"] = "stable"

    return result


def compare_channel_prices(
    product: str,
    reference_channel: str,
    compare_channels: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Compare prices between a reference channel and others.

    Args:
        product: Product Master name
        reference_channel: Channel to use as reference
        compare_channels: Channels to compare against

    Returns:
        Dictionary with price comparisons
    """
    import frappe

    result = {
        "product": product,
        "reference_channel": reference_channel,
        "reference_price": None,
        "comparisons": [],
        "summary": {
            "cheapest_channel": None,
            "most_expensive_channel": None,
            "avg_difference_percent": 0.0
        }
    }

    service = PriceParityMonitorService(product=product)

    # Get reference price
    ref_point = service._get_channel_price(reference_channel)
    if not ref_point:
        result["error"] = f"Could not get price from {reference_channel}"
        return result

    ref_price = ref_point.to_base_currency("USD")
    result["reference_price"] = ref_price

    if not compare_channels:
        compare_channels = [c for c in service._get_configured_channels() if c != reference_channel]

    comparisons = []
    differences = []
    prices = {reference_channel: ref_price}

    for channel in compare_channels:
        try:
            price_point = service._get_channel_price(channel)
            if price_point:
                comp_price = price_point.to_base_currency("USD")
                prices[channel] = comp_price

                comparison = PriceComparison(
                    reference_channel=reference_channel,
                    compare_channel=channel,
                    reference_price=ref_price,
                    compare_price=comp_price,
                    currency="USD"
                )
                comparisons.append(comparison.to_dict())
                differences.append(comparison.difference_percent)

        except Exception as e:
            frappe.log_error(
                message=f"Error comparing {channel}: {str(e)}",
                title="Price Compare Error"
            )

    result["comparisons"] = comparisons

    if prices:
        result["summary"]["cheapest_channel"] = min(prices, key=prices.get)
        result["summary"]["most_expensive_channel"] = max(prices, key=prices.get)

    if differences:
        result["summary"]["avg_difference_percent"] = sum(abs(d) for d in differences) / len(differences)

    return result


def get_competitor_analysis(
    product: str,
    channel: str,
    max_competitors: int = 10
) -> Dict[str, Any]:
    """Get competitor price analysis for a product.

    Args:
        product: Product Master name
        channel: Channel to analyze
        max_competitors: Maximum competitors to return

    Returns:
        Dictionary with competitor analysis
    """
    service = PriceParityMonitorService(product=product)
    competitors = service.get_competitor_prices(channel=channel, max_competitors=max_competitors)

    result = {
        "product": product,
        "channel": channel,
        "our_price": None,
        "competitors": [c.to_dict() for c in competitors],
        "summary": {
            "competitor_count": len(competitors),
            "competitors_cheaper": 0,
            "competitors_more_expensive": 0,
            "avg_competitor_price": 0.0,
            "min_competitor_price": None,
            "max_competitor_price": None,
            "price_position": "unknown"
        }
    }

    if competitors:
        result["our_price"] = competitors[0].our_price

        prices = [c.competitor_price for c in competitors]
        result["summary"]["avg_competitor_price"] = sum(prices) / len(prices)
        result["summary"]["min_competitor_price"] = min(prices)
        result["summary"]["max_competitor_price"] = max(prices)
        result["summary"]["competitors_cheaper"] = sum(1 for c in competitors if c.competitor_is_cheaper)
        result["summary"]["competitors_more_expensive"] = len(competitors) - result["summary"]["competitors_cheaper"]

        our_price = competitors[0].our_price
        if our_price:
            if our_price <= result["summary"]["min_competitor_price"]:
                result["summary"]["price_position"] = "lowest"
            elif our_price >= result["summary"]["max_competitor_price"]:
                result["summary"]["price_position"] = "highest"
            else:
                result["summary"]["price_position"] = "middle"

    return result


def check_map_violations(
    product: str,
    map_price: float,
    channels: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Check for MAP violations across channels.

    Args:
        product: Product Master name
        map_price: Minimum Advertised Price
        channels: Channels to check

    Returns:
        Dictionary with violation results
    """
    service = PriceParityMonitorService(
        product=product,
        channels=channels,
        map_price=map_price
    )

    result = service.monitor_prices(include_competitors=False, check_violations=True)

    map_violations = [
        v.to_dict() for v in result.violations
        if v.violation_type == ViolationType.MAP_VIOLATION
    ]

    return {
        "product": product,
        "map_price": map_price,
        "channels_checked": result.channels_monitored,
        "violations_found": len(map_violations),
        "violations": map_violations,
        "compliant_channels": result.channels_with_prices - len(map_violations)
    }


def get_price_alerts(
    product: Optional[str] = None,
    channel: Optional[str] = None,
    severity: Optional[str] = None,
    days: int = 7
) -> Dict[str, Any]:
    """Get recent price alerts.

    Args:
        product: Optional filter by product
        channel: Optional filter by channel
        severity: Optional filter by severity
        days: Number of days to look back

    Returns:
        Dictionary with alert data
    """
    import frappe

    result = {
        "alerts": [],
        "summary": {
            "total": 0,
            "by_severity": {},
            "by_channel": {}
        }
    }

    try:
        filters = {
            "creation": [">=", frappe.utils.add_to_date(frappe.utils.now_datetime(), days=-days)],
            "title": ["like", "%Price Alert%"]
        }

        if product:
            filters["message"] = ["like", f"%{product}%"]

        logs = frappe.get_all(
            "Error Log",
            filters=filters,
            fields=["name", "title", "message", "creation"],
            order_by="creation desc",
            limit=100
        )

        for log in logs:
            # Parse alert info from log
            alert = {
                "id": log.name,
                "title": log.title,
                "message": log.message,
                "created": log.creation,
            }

            # Extract severity from title
            if "CRITICAL" in log.title:
                alert["severity"] = "critical"
            elif "HIGH" in log.title:
                alert["severity"] = "high"
            elif "WARNING" in log.title:
                alert["severity"] = "warning"
            else:
                alert["severity"] = "info"

            if severity and alert["severity"] != severity:
                continue

            result["alerts"].append(alert)

            # Update summary
            sev = alert["severity"]
            result["summary"]["by_severity"][sev] = result["summary"]["by_severity"].get(sev, 0) + 1

        result["summary"]["total"] = len(result["alerts"])

    except Exception as e:
        frappe.log_error(
            message=f"Error getting price alerts: {str(e)}",
            title="Price Alerts Error"
        )

    return result


def schedule_price_monitoring(
    product: str,
    channels: List[str],
    frequency: str = "daily",
    map_price: Optional[float] = None
) -> Dict[str, Any]:
    """Schedule automated price monitoring for a product.

    Args:
        product: Product Master name
        channels: Channels to monitor
        frequency: Monitoring frequency (hourly, daily, weekly)
        map_price: Optional MAP to check

    Returns:
        Dictionary with schedule confirmation
    """
    import frappe

    result = {
        "success": True,
        "product": product,
        "channels": channels,
        "frequency": frequency,
        "map_price": map_price,
        "message": f"Price monitoring scheduled ({frequency})"
    }

    try:
        # Store monitoring configuration
        frappe.cache.set_value(
            f"price_monitoring:{product}",
            {
                "channels": channels,
                "frequency": frequency,
                "map_price": map_price,
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

def _monitor_prices_job(
    product: str,
    channels: Optional[List[str]] = None,
    base_currency: str = "USD",
    map_price: Optional[float] = None
) -> Dict[str, Any]:
    """Background job for price monitoring.

    Args:
        product: Product Master name
        channels: Channels to monitor
        base_currency: Currency for comparisons
        map_price: Optional MAP

    Returns:
        Monitoring result dictionary
    """
    return monitor_product_prices(
        product=product,
        channels=channels,
        base_currency=base_currency,
        map_price=map_price,
        async_monitor=False
    )


def scheduled_price_monitoring():
    """Scheduled task to run price monitoring for all configured products.

    This function should be called by Frappe's scheduler.
    """
    import frappe

    try:
        # Get all products with monitoring enabled
        monitored_products = frappe.cache.get_keys("price_monitoring:*")

        for key in monitored_products:
            try:
                config = frappe.cache.get_value(key)
                if config and config.get("enabled"):
                    product = key.split(":", 1)[1]
                    channels = config.get("channels", [])
                    map_price = config.get("map_price")

                    monitor_product_prices(
                        product=product,
                        channels=channels,
                        map_price=map_price,
                        async_monitor=True
                    )

            except Exception as e:
                frappe.log_error(
                    message=f"Error monitoring {key}: {str(e)}",
                    title="Scheduled Price Monitoring Error"
                )

    except Exception as e:
        frappe.log_error(
            message=f"Scheduled price monitoring failed: {str(e)}",
            title="Scheduled Price Monitoring Error"
        )


def _get_live_currency_rate(from_currency: str, to_currency: str) -> float:
    """Get live currency conversion rate.

    Args:
        from_currency: Source currency code
        to_currency: Target currency code

    Returns:
        Conversion rate
    """
    import frappe

    if from_currency == to_currency:
        return 1.0

    try:
        # Try to get from Frappe's Currency Exchange
        rate = frappe.db.get_value(
            "Currency Exchange",
            filters={
                "from_currency": from_currency,
                "to_currency": to_currency,
            },
            fieldname="exchange_rate"
        )

        if rate:
            return rate

    except Exception:
        pass

    # Fallback to static rates
    from_rate = CURRENCY_FALLBACK_RATES.get(from_currency, 1.0)
    to_rate = CURRENCY_FALLBACK_RATES.get(to_currency, 1.0)

    return from_rate / to_rate


# =============================================================================
# Frappe API Wrappers
# =============================================================================

def _wrap_for_whitelist():
    """Wrap functions for Frappe whitelist at runtime."""
    import frappe

    functions = [
        "monitor_product_prices",
        "get_price_parity_status",
        "get_price_history",
        "get_price_trends",
        "compare_channel_prices",
        "get_competitor_analysis",
        "check_map_violations",
        "get_price_alerts",
        "schedule_price_monitoring",
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
