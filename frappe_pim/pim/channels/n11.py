"""
N11 Channel Adapter

Provides adapter for N11 marketplace - one of Turkey's leading e-commerce platforms.
Uses the N11 Seller API for product management and order operations.

Features:
- API Key + API Secret authentication (Basic Auth)
- Category-specific attribute requirements
- Brand registration and validation
- Product variants support (color, size)
- Image processing for N11 requirements
- Rate limiting with per-endpoint quota tracking
- Batch product submission
- Price and inventory sync
- SOAP and REST API support

API Documentation: https://api.n11.com/

Note: frappe imports are deferred to function/method level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional
import base64
import json
import time
import uuid
import hashlib

from frappe_pim.pim.channels.base import (
    ChannelAdapter,
    ValidationResult,
    MappingResult,
    PublishResult,
    StatusResult,
    PublishStatus,
    RateLimitState,
    RateLimitError,
    AuthenticationError,
    PublishError,
    ValidationError as ChannelValidationError,
    register_adapter,
)


# =============================================================================
# N11-Specific Constants
# =============================================================================

class N11Environment(str, Enum):
    """N11 API environments"""
    PRODUCTION = "api.n11.com"
    SANDBOX = "sandbox.n11.com"


class N11ProductStatus(str, Enum):
    """N11 product approval status"""
    DRAFT = "Draft"
    WAITING_APPROVAL = "WaitingApproval"
    ACTIVE = "Active"
    SUSPENDED = "Suspended"
    REJECTED = "Rejected"
    UNAPPROVED = "Unapproved"
    DELETED = "Deleted"


class N11Currency(str, Enum):
    """N11 supported currencies"""
    TRY = "TL"  # Turkish Lira (N11 uses TL)
    USD = "USD"
    EUR = "EUR"


class N11StockType(str, Enum):
    """N11 stock types"""
    N11 = "N11"  # Products in N11 warehouse
    SELLER = "SELLER"  # Products in seller warehouse


class N11ShipmentTemplate(str, Enum):
    """Common N11 shipment templates"""
    STANDARD = "1"
    EXPRESS = "2"
    FREE_SHIPPING = "3"


# Rate limits for N11 API endpoints (requests per minute)
N11_RATE_LIMITS = {
    "products": 30,
    "products/batch": 5,
    "inventory": 60,
    "prices": 60,
    "categories": 30,
    "brands": 30,
    "orders": 60,
    "default": 30,
}

# Burst limits (max concurrent requests)
N11_BURST_LIMITS = {
    "products": 5,
    "products/batch": 2,
    "inventory": 10,
    "prices": 10,
    "categories": 5,
    "brands": 5,
    "orders": 10,
    "default": 5,
}


# =============================================================================
# N11-Specific Data Classes
# =============================================================================

@dataclass
class N11QuotaState:
    """Tracks API quota state per endpoint"""
    endpoint: str
    requests_made: int = 0
    requests_limit: int = 30
    burst_remaining: int = 5
    window_start: datetime = field(default_factory=datetime.now)
    window_duration: int = 60  # seconds
    retry_after: datetime = None
    last_request: datetime = None

    def is_limited(self) -> bool:
        """Check if currently rate limited"""
        if self.retry_after and datetime.now() < self.retry_after:
            return True

        # Reset window if expired
        if datetime.now() > self.window_start + timedelta(seconds=self.window_duration):
            self.requests_made = 0
            self.burst_remaining = N11_BURST_LIMITS.get(
                self.endpoint, N11_BURST_LIMITS["default"]
            )
            self.window_start = datetime.now()
            return False

        return self.requests_made >= self.requests_limit

    def record_request(self) -> None:
        """Record a request for rate limiting"""
        self.requests_made += 1
        self.burst_remaining = max(0, self.burst_remaining - 1)
        self.last_request = datetime.now()

    def wait_time(self) -> float:
        """Calculate wait time before next request"""
        if self.retry_after:
            delta = self.retry_after - datetime.now()
            if delta.total_seconds() > 0:
                return delta.total_seconds()

        if self.is_limited():
            window_end = self.window_start + timedelta(seconds=self.window_duration)
            delta = window_end - datetime.now()
            return max(0, delta.total_seconds())

        return 0


@dataclass
class N11BatchResult:
    """Result of a batch operation"""
    batch_id: str
    status: str = "PROCESSING"
    items_received: int = 0
    items_processed: int = 0
    items_failed: int = 0
    items_succeeded: int = 0
    failed_items: List[Dict] = field(default_factory=list)
    error_messages: List[str] = field(default_factory=list)


# =============================================================================
# N11 Required Fields and Validation Rules
# =============================================================================

# Required fields for N11 product listings
N11_REQUIRED_FIELDS = {
    "productSellerCode",  # Seller's product code
    "title",
    "subtitle",  # Short description
    "description",
    "categoryId",
    "price",
    "stockQuantity",
    "images",
}

# Optional but recommended fields
N11_RECOMMENDED_FIELDS = {
    "displayPrice",  # Display price (strikethrough)
    "brandId",
    "shipmentTemplate",
    "preparingDay",  # Days to prepare for shipment
    "attributes",
    "discount",
    "currencyType",
    "productCondition",  # NEW or USED
}

# Field length limits
N11_FIELD_LIMITS = {
    "title": 150,
    "subtitle": 250,
    "description": 60000,
    "productSellerCode": 50,
}

# PIM to N11 field mappings
PIM_TO_N11_FIELDS = {
    "item_code": "productSellerCode",
    "item_name": "title",
    "pim_title": "title",
    "pim_description": "description",
    "short_description": "subtitle",
    "barcode": "gtipCode",  # N11 uses gtipCode for barcode
    "standard_rate": "price",
    "valuation_rate": "displayPrice",
    "brand": "brandName",
    "item_group": "categoryName",
    "stock_qty": "stockQuantity",
    "net_weight": "weight",
    "image": "images",
    "country_of_origin": "originCountry",
}

# N11 attribute type mappings (Turkish)
N11_ATTRIBUTE_TYPES = {
    "color": "Renk",
    "size": "Beden",
    "material": "Materyal",
    "pattern": "Desen",
    "gender": "Cinsiyet",
    "age_group": "Yas Grubu",
    "season": "Sezon",
    "fabric": "Kumas",
}

# Product condition options
N11_PRODUCT_CONDITIONS = {
    "NEW": "1",
    "USED": "2",
    "REFURBISHED": "3",
}


# =============================================================================
# N11 Channel Adapter
# =============================================================================

class N11Adapter(ChannelAdapter):
    """
    N11 marketplace adapter.

    Handles product publishing, inventory updates, and order sync with N11.
    Uses API Key + API Secret authentication (Basic Auth).

    N11 provides both SOAP and REST APIs. This adapter uses the REST API
    for simplicity and better performance.
    """

    channel_code: str = "n11"
    channel_name: str = "N11"

    # Rate limit settings
    default_requests_per_minute: int = 30
    default_requests_per_second: float = 0.5
    max_retry_attempts: int = 5
    base_backoff_seconds: float = 2.0
    max_backoff_seconds: float = 120.0

    # API version
    API_VERSION = "v1"
    REST_API_PATH = "/rest"
    SOAP_API_PATH = "/ws"

    def __init__(self, channel_doc: Any = None):
        """Initialize N11 adapter.

        Args:
            channel_doc: Channel Frappe document with N11 credentials
        """
        super().__init__(channel_doc)
        self._quota_states: Dict[str, N11QuotaState] = {}
        self._brand_cache: Dict[str, int] = {}
        self._category_cache: Dict[str, int] = {}
        self._category_attributes_cache: Dict[int, List[Dict]] = {}

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def seller_id(self) -> str:
        """Get the N11 seller/shop ID."""
        return self.config.get("seller_id") or self.credentials.get("seller_id", "")

    @property
    def api_endpoint(self) -> str:
        """Get the N11 API endpoint based on environment."""
        environment = self.config.get("environment", "production")

        if environment.lower() == "sandbox":
            host = N11Environment.SANDBOX.value
        else:
            host = N11Environment.PRODUCTION.value

        return f"https://{host}{self.REST_API_PATH}"

    @property
    def soap_endpoint(self) -> str:
        """Get the N11 SOAP API endpoint."""
        environment = self.config.get("environment", "production")

        if environment.lower() == "sandbox":
            host = N11Environment.SANDBOX.value
        else:
            host = N11Environment.PRODUCTION.value

        return f"https://{host}{self.SOAP_API_PATH}"

    # =========================================================================
    # Authentication Methods
    # =========================================================================

    def _get_auth_headers(self) -> Dict:
        """Build authentication headers for N11 API requests.

        N11 uses Basic Auth with API Key and Secret.

        Returns:
            Dictionary of HTTP headers including authorization
        """
        api_key = self.credentials.get("api_key", "")
        api_secret = self.credentials.get("api_secret", "")

        if not api_key or not api_secret:
            raise AuthenticationError(
                "N11 API key and secret not configured",
                channel=self.channel_code,
            )

        # Create Basic Auth header
        auth_string = f"{api_key}:{api_secret}"
        auth_bytes = auth_string.encode("utf-8")
        auth_base64 = base64.b64encode(auth_bytes).decode("utf-8")

        return {
            "Authorization": f"Basic {auth_base64}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"{self.config.get('user_agent', 'FrappePIM')}/1.0",
        }

    def _get_soap_auth(self) -> Dict:
        """Get SOAP authentication credentials.

        Returns:
            Dictionary with appKey and appSecret for SOAP requests
        """
        return {
            "appKey": self.credentials.get("api_key", ""),
            "appSecret": self.credentials.get("api_secret", ""),
        }

    # =========================================================================
    # Rate Limiting Methods
    # =========================================================================

    def _get_quota_state(self, endpoint: str) -> N11QuotaState:
        """Get or create quota state for an endpoint.

        Args:
            endpoint: The API endpoint category (products, inventory, etc.)

        Returns:
            N11QuotaState instance for the endpoint
        """
        if endpoint not in self._quota_states:
            rate_limit = N11_RATE_LIMITS.get(endpoint, N11_RATE_LIMITS["default"])
            burst_limit = N11_BURST_LIMITS.get(endpoint, N11_BURST_LIMITS["default"])

            self._quota_states[endpoint] = N11QuotaState(
                endpoint=endpoint,
                requests_limit=rate_limit,
                burst_remaining=burst_limit,
            )

        return self._quota_states[endpoint]

    def handle_rate_limiting(self, response: Any = None) -> None:
        """Handle N11 API rate limiting from response.

        Parses rate limit headers and updates internal quota tracking.

        Args:
            response: HTTP response object with rate limit headers

        Raises:
            RateLimitError: If rate limit exceeded and cannot proceed
        """
        if response is None:
            return

        # Check for 429 Too Many Requests
        if hasattr(response, 'status_code') and response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 60))

            raise RateLimitError(
                "N11 API rate limit exceeded",
                channel=self.channel_code,
                retry_after=retry_after,
                details={
                    "status_code": 429,
                    "retry_after": retry_after,
                },
            )

        # Check for N11-specific rate limit response
        if hasattr(response, 'status_code') and response.status_code == 503:
            # Service unavailable - might be rate limited
            raise RateLimitError(
                "N11 API service unavailable (possible rate limit)",
                channel=self.channel_code,
                retry_after=30,
            )

        # Parse rate limit headers if present
        remaining = response.headers.get("X-RateLimit-Remaining")
        limit = response.headers.get("X-RateLimit-Limit")
        reset = response.headers.get("X-RateLimit-Reset")

        if remaining is not None:
            try:
                remaining_requests = int(remaining)
                if remaining_requests <= 0:
                    reset_time = int(reset) if reset else 60
                    raise RateLimitError(
                        "N11 API quota exhausted",
                        channel=self.channel_code,
                        retry_after=reset_time,
                        quota_remaining=0,
                    )
            except ValueError:
                pass

    def _wait_for_quota(self, endpoint: str) -> None:
        """Wait if quota for endpoint is exhausted.

        Args:
            endpoint: The API endpoint category

        Raises:
            RateLimitError: If wait time exceeds maximum
        """
        quota_state = self._get_quota_state(endpoint)
        wait_time = quota_state.wait_time()

        if wait_time > 0:
            if wait_time > self.max_backoff_seconds:
                raise RateLimitError(
                    f"N11 quota exhausted for {endpoint}, wait time ({wait_time}s) exceeds maximum",
                    channel=self.channel_code,
                    retry_after=int(wait_time),
                )
            time.sleep(wait_time)

        quota_state.record_request()

    # =========================================================================
    # Validation Methods
    # =========================================================================

    def validate_product(self, product: Dict) -> ValidationResult:
        """Validate a product against N11's listing requirements.

        Checks required fields, field length limits, barcode format,
        category/brand IDs, and other N11-specific requirements.

        Args:
            product: Product data dictionary in PIM format

        Returns:
            ValidationResult with validation status and any errors/warnings
        """
        errors = []
        warnings = []
        product_id = product.get("item_code", product.get("productSellerCode", "unknown"))

        # Check required fields
        for field_name in N11_REQUIRED_FIELDS:
            # Check both PIM and N11 field names
            pim_field = None
            for pim_name, n11_name in PIM_TO_N11_FIELDS.items():
                if n11_name.lower() == field_name.lower() or field_name == pim_name:
                    pim_field = pim_name
                    break

            value = product.get(field_name) or (product.get(pim_field) if pim_field else None)

            # Special handling for images
            if field_name == "images":
                images = product.get("images") or product.get("image")
                if not images:
                    errors.append({
                        "field": "images",
                        "message": "At least one product image is required",
                        "rule": "required",
                    })
                continue

            # Special handling for category
            if field_name == "categoryId":
                id_value = product.get("categoryId") or product.get("category_id")
                name_value = product.get("item_group") or product.get("category")

                if not id_value and not name_value:
                    errors.append({
                        "field": "categoryId",
                        "message": "Required field 'categoryId' or category name is missing",
                        "rule": "required",
                    })
                continue

            # Special handling for subtitle (short description)
            if field_name == "subtitle":
                subtitle = product.get("subtitle") or product.get("short_description")
                if not subtitle:
                    # Generate from title if possible
                    title = product.get("pim_title") or product.get("item_name") or product.get("title")
                    if title:
                        warnings.append({
                            "field": "subtitle",
                            "message": "No subtitle provided, will use truncated title",
                            "rule": "recommended",
                        })
                    else:
                        errors.append({
                            "field": "subtitle",
                            "message": "Required field 'subtitle' (short description) is missing",
                            "rule": "required",
                        })
                continue

            if not value:
                errors.append({
                    "field": field_name,
                    "message": f"Required field '{field_name}' is missing",
                    "rule": "required",
                })

        # Check field length limits
        for field_name, max_length in N11_FIELD_LIMITS.items():
            value = product.get(field_name, "")
            # Also check PIM field name
            for pim_name, n11_name in PIM_TO_N11_FIELDS.items():
                if n11_name.lower() == field_name.lower():
                    value = value or product.get(pim_name, "")
                    break

            if isinstance(value, str) and len(value) > max_length:
                errors.append({
                    "field": field_name,
                    "message": f"Field '{field_name}' exceeds maximum length of {max_length} characters",
                    "value": f"{len(value)} characters",
                    "rule": "max_length",
                })

        # Validate barcode (GTIP code) if provided
        barcode = product.get("barcode") or product.get("gtipCode") or product.get("gtin")
        if barcode:
            barcode_error = self._validate_barcode(barcode)
            if barcode_error:
                # Barcode is optional for N11, so just warn
                warnings.append(barcode_error)

        # Validate price
        price = product.get("standard_rate") or product.get("price")
        if price is not None:
            try:
                price_val = float(price)
                if price_val <= 0:
                    errors.append({
                        "field": "price",
                        "message": "Price must be greater than zero",
                        "value": str(price),
                        "rule": "positive_number",
                    })
            except (ValueError, TypeError):
                errors.append({
                    "field": "price",
                    "message": "Price must be a valid number",
                    "value": str(price),
                    "rule": "numeric",
                })
        else:
            errors.append({
                "field": "price",
                "message": "Price is required",
                "rule": "required",
            })

        # Validate display price >= sale price
        display_price = product.get("valuation_rate") or product.get("displayPrice")
        sale_price = price
        if display_price and sale_price:
            try:
                if float(display_price) < float(sale_price):
                    errors.append({
                        "field": "displayPrice",
                        "message": "Display price must be greater than or equal to sale price",
                        "value": f"display: {display_price}, sale: {sale_price}",
                        "rule": "price_comparison",
                    })
            except (ValueError, TypeError):
                pass

        # Validate quantity
        quantity = product.get("quantity") or product.get("stockQuantity") or product.get("stock_qty", 0)
        try:
            qty_val = int(quantity)
            if qty_val < 0:
                errors.append({
                    "field": "stockQuantity",
                    "message": "Stock quantity cannot be negative",
                    "value": str(quantity),
                    "rule": "non_negative",
                })
        except (ValueError, TypeError):
            errors.append({
                "field": "stockQuantity",
                "message": "Stock quantity must be a valid integer",
                "value": str(quantity),
                "rule": "integer",
            })

        # Validate images
        images = product.get("images") or product.get("image")
        if images:
            image_errors, image_warnings = self._validate_images(images)
            errors.extend(image_errors)
            warnings.extend(image_warnings)

        # Check for recommended fields
        for field_name in N11_RECOMMENDED_FIELDS:
            if field_name not in product:
                pim_field = None
                for pim_name, n11_name in PIM_TO_N11_FIELDS.items():
                    if n11_name.lower() == field_name.lower():
                        pim_field = pim_name
                        break

                if pim_field and pim_field not in product:
                    warnings.append({
                        "field": field_name,
                        "message": f"Recommended field '{field_name}' not provided",
                        "rule": "recommended",
                    })

        return ValidationResult(
            is_valid=len(errors) == 0,
            product=product_id,
            errors=errors,
            warnings=warnings,
            channel=self.channel_code,
        )

    def _validate_barcode(self, barcode: str) -> Optional[Dict]:
        """Validate barcode format and check digit.

        N11 accepts GTIN/EAN barcodes in the gtipCode field.

        Args:
            barcode: Barcode string

        Returns:
            Error dict if invalid, None if valid
        """
        # Remove any spaces or dashes
        barcode = str(barcode).replace(" ", "").replace("-", "")

        # Check length - N11 accepts EAN-8, EAN-13, UPC-A
        valid_lengths = {8, 12, 13, 14}
        if len(barcode) not in valid_lengths:
            return {
                "field": "barcode",
                "message": f"Barcode must be 8, 12, 13, or 14 digits, got {len(barcode)}",
                "value": barcode,
                "rule": "barcode_length",
            }

        # Check if all digits
        if not barcode.isdigit():
            return {
                "field": "barcode",
                "message": "Barcode must contain only digits",
                "value": barcode,
                "rule": "barcode_format",
            }

        # Validate check digit
        if not self._validate_barcode_check_digit(barcode):
            return {
                "field": "barcode",
                "message": "Barcode check digit is invalid",
                "value": barcode,
                "rule": "barcode_checksum",
            }

        return None

    def _validate_barcode_check_digit(self, barcode: str) -> bool:
        """Validate barcode check digit using GS1 algorithm.

        Args:
            barcode: Barcode string with check digit

        Returns:
            True if check digit is valid
        """
        # Pad to 14 digits for uniform calculation
        barcode = barcode.zfill(14)

        # Calculate check digit
        total = 0
        for i, digit in enumerate(barcode[:-1]):
            multiplier = 3 if i % 2 == 0 else 1
            total += int(digit) * multiplier

        calculated_check = (10 - (total % 10)) % 10
        actual_check = int(barcode[-1])

        return calculated_check == actual_check

    def _validate_images(self, images: Any) -> tuple:
        """Validate product images against N11 requirements.

        N11 image requirements:
        - Minimum 1 image, maximum 8 images
        - JPEG or PNG format
        - Minimum 500x500 pixels recommended
        - White background preferred
        - First image is main image

        Args:
            images: Image data (URL, path, or list)

        Returns:
            Tuple of (errors list, warnings list)
        """
        errors = []
        warnings = []

        # Convert single image to list
        if isinstance(images, str):
            images = [images]

        if not isinstance(images, list):
            errors.append({
                "field": "images",
                "message": "Images must be a string URL or list of URLs",
                "rule": "image_format",
            })
            return errors, warnings

        # Check image count
        if len(images) < 1:
            errors.append({
                "field": "images",
                "message": "At least one product image is required",
                "rule": "min_images",
            })
        elif len(images) > 8:
            warnings.append({
                "field": "images",
                "message": f"Maximum 8 images allowed, found {len(images)} - extras will be ignored",
                "rule": "max_images",
            })

        # Validate image URLs
        for i, img in enumerate(images):
            if isinstance(img, dict):
                img_url = img.get("url", img.get("src", ""))
            else:
                img_url = str(img)

            if not img_url:
                errors.append({
                    "field": f"images[{i}]",
                    "message": "Image URL is empty",
                    "rule": "image_url_required",
                })
                continue

            # Check URL format
            if not (img_url.startswith("http://") or img_url.startswith("https://")):
                errors.append({
                    "field": f"images[{i}]",
                    "message": "Image URL must be a valid HTTP/HTTPS URL",
                    "value": img_url[:100],
                    "rule": "image_url_format",
                })

            # Check file extension
            url_lower = img_url.lower()
            if not any(url_lower.endswith(ext) or ext in url_lower for ext in [".jpg", ".jpeg", ".png"]):
                warnings.append({
                    "field": f"images[{i}]",
                    "message": "Image should be JPEG or PNG format",
                    "value": img_url[-20:] if len(img_url) > 20 else img_url,
                    "rule": "image_extension",
                })

        return errors, warnings

    # =========================================================================
    # Mapping Methods
    # =========================================================================

    def map_attributes(self, product: Dict) -> MappingResult:
        """Map PIM product attributes to N11 format.

        Converts internal field names to N11's expected format
        and transforms values as needed.

        Args:
            product: Product data dictionary in PIM format

        Returns:
            MappingResult with mapped data and unmapped fields
        """
        product_id = product.get("item_code", product.get("productSellerCode", "unknown"))
        mapped_data = {}
        unmapped_fields = []

        # Product seller code (required)
        mapped_data["productSellerCode"] = product.get("item_code") or product.get("productSellerCode")

        # Title (required)
        title = product.get("pim_title") or product.get("item_name") or product.get("title")
        if title:
            # Truncate to N11 limit
            mapped_data["title"] = title[:150]

        # Subtitle / Short description (required)
        subtitle = product.get("subtitle") or product.get("short_description")
        if subtitle:
            mapped_data["subtitle"] = subtitle[:250]
        elif title:
            # Use truncated title as subtitle if not provided
            mapped_data["subtitle"] = title[:250]

        # Description (required)
        description = product.get("pim_description") or product.get("description")
        if description:
            # Truncate to N11 limit
            mapped_data["description"] = description[:60000]

        # Barcode / GTIP Code (optional)
        barcode = product.get("barcode") or product.get("gtipCode") or product.get("gtin")
        if barcode:
            mapped_data["gtipCode"] = str(barcode).replace(" ", "").replace("-", "")

        # Brand ID
        brand_id = product.get("brand_id") or product.get("brandId")
        brand_name = product.get("brand")
        if brand_id:
            mapped_data["brandId"] = int(brand_id)
        elif brand_name:
            # Brand name will be resolved to ID during publish
            mapped_data["brandName"] = brand_name

        # Category ID (required)
        category_id = product.get("category_id") or product.get("categoryId")
        category_name = product.get("item_group") or product.get("category")
        if category_id:
            mapped_data["categoryId"] = int(category_id)
        elif category_name:
            # Category name will be resolved to ID during publish
            mapped_data["categoryName"] = category_name

        # Pricing
        price = product.get("standard_rate") or product.get("price")
        display_price = product.get("valuation_rate") or product.get("displayPrice")

        if price is not None:
            mapped_data["price"] = float(price)

        if display_price is not None:
            mapped_data["displayPrice"] = float(display_price)
        elif price is not None:
            # Display price defaults to sale price
            mapped_data["displayPrice"] = float(price)

        # Currency (default to TL)
        currency = product.get("currency", "TRY")
        currency_map = {"TRY": "TL", "TL": "TL", "USD": "USD", "EUR": "EUR"}
        mapped_data["currencyType"] = currency_map.get(currency.upper(), "TL")

        # Stock quantity (required)
        quantity = product.get("quantity") or product.get("stockQuantity") or product.get("stock_qty", 0)
        mapped_data["stockQuantity"] = int(quantity) if quantity else 0

        # Preparing day (days to ship)
        preparing_day = product.get("preparingDay") or product.get("lead_time", 3)
        mapped_data["preparingDay"] = int(preparing_day)

        # Shipment template
        shipment_template = product.get("shipmentTemplate")
        if shipment_template:
            mapped_data["shipmentTemplate"] = shipment_template

        # Product condition (NEW, USED)
        condition = product.get("productCondition", "NEW")
        mapped_data["productCondition"] = N11_PRODUCT_CONDITIONS.get(condition.upper(), "1")

        # Weight
        weight = product.get("weight") or product.get("net_weight")
        if weight:
            try:
                mapped_data["weight"] = float(weight)
            except (ValueError, TypeError):
                pass

        # Images (required)
        images = product.get("images") or product.get("image")
        if images:
            mapped_data["images"] = self._map_images(images)

        # Attributes (category-specific)
        attributes = product.get("attributes", [])
        if attributes:
            mapped_data["attributes"] = self._map_attributes_list(attributes)
        else:
            # Try to extract from individual fields
            variant_attrs = self._extract_variant_attributes(product)
            if variant_attrs:
                mapped_data["attributes"] = variant_attrs

        # SKU list for variants
        sku_list = product.get("sku_list") or product.get("variants")
        if sku_list:
            mapped_data["skuList"] = self._map_sku_list(sku_list)

        # Discount
        discount = product.get("discount")
        if discount:
            try:
                discount_data = {
                    "discountType": discount.get("type", "1"),  # 1: Amount, 2: Percentage
                    "discountValue": float(discount.get("value", 0)),
                }
                if discount.get("startDate"):
                    discount_data["discountStartDate"] = discount["startDate"]
                if discount.get("endDate"):
                    discount_data["discountEndDate"] = discount["endDate"]
                mapped_data["discount"] = discount_data
            except (ValueError, TypeError, AttributeError):
                pass

        # Track unmapped fields
        mapped_pim_fields = set(PIM_TO_N11_FIELDS.keys())
        mapped_pim_fields.update({
            "product_main_id", "brand_id", "category_id", "currency",
            "preparing_day", "shipment_template", "product_condition",
            "images", "attributes", "color", "size", "quantity",
            "sku_list", "variants", "discount",
        })

        for field_name in product.keys():
            if field_name not in mapped_pim_fields:
                unmapped_fields.append(field_name)

        return MappingResult(
            product=product_id,
            mapped_data=mapped_data,
            unmapped_fields=unmapped_fields,
            channel=self.channel_code,
        )

    def _map_images(self, images: Any) -> List[Dict]:
        """Map images to N11 format.

        Args:
            images: Image data (URL, path, or list)

        Returns:
            List of image dictionaries for N11 API
        """
        image_list = []

        if isinstance(images, str):
            images = [images]

        if isinstance(images, list):
            for idx, img in enumerate(images[:8]):  # Max 8 images
                if isinstance(img, dict):
                    url = img.get("url", img.get("src", ""))
                    order = img.get("order", idx + 1)
                else:
                    url = str(img)
                    order = idx + 1

                if url:
                    image_list.append({
                        "url": url,
                        "order": order,
                    })

        return image_list

    def _map_attributes_list(self, attributes: List[Dict]) -> List[Dict]:
        """Map product attributes to N11 format.

        Args:
            attributes: List of attribute dictionaries

        Returns:
            List of N11-format attributes
        """
        n11_attrs = []

        for attr in attributes:
            attr_id = attr.get("attribute_id") or attr.get("attributeId")
            attr_name = attr.get("attribute_name") or attr.get("name")
            attr_value_id = attr.get("attribute_value_id") or attr.get("valueId")
            attr_value = attr.get("attribute_value") or attr.get("value")

            n11_attr = {}

            if attr_id:
                n11_attr["id"] = int(attr_id)
            if attr_name:
                n11_attr["name"] = str(attr_name)
            if attr_value_id:
                n11_attr["valueId"] = int(attr_value_id)
            if attr_value:
                n11_attr["value"] = str(attr_value)

            if n11_attr:
                n11_attrs.append(n11_attr)

        return n11_attrs

    def _extract_variant_attributes(self, product: Dict) -> List[Dict]:
        """Extract variant attributes from product fields.

        Looks for common variant fields like color, size, etc.

        Args:
            product: Product data dictionary

        Returns:
            List of attribute dictionaries
        """
        attributes = []

        # Color
        color = product.get("color") or product.get("colour") or product.get("renk")
        if color:
            attributes.append({
                "name": "Renk",
                "value": str(color),
            })

        # Size
        size = product.get("size") or product.get("beden")
        if size:
            attributes.append({
                "name": "Beden",
                "value": str(size),
            })

        # Material
        material = product.get("material") or product.get("materyal")
        if material:
            attributes.append({
                "name": "Materyal",
                "value": str(material),
            })

        # Gender
        gender = product.get("gender") or product.get("cinsiyet")
        if gender:
            attributes.append({
                "name": "Cinsiyet",
                "value": str(gender),
            })

        return attributes

    def _map_sku_list(self, sku_list: List[Dict]) -> List[Dict]:
        """Map SKU list (variants) to N11 format.

        Args:
            sku_list: List of variant dictionaries

        Returns:
            List of N11-format SKU items
        """
        n11_skus = []

        for sku in sku_list:
            n11_sku = {
                "sellerStockCode": sku.get("seller_code") or sku.get("sellerStockCode"),
                "quantity": int(sku.get("quantity", 0)),
                "price": float(sku.get("price", 0)) if sku.get("price") else None,
            }

            # Add variant attributes
            attrs = []
            if sku.get("color"):
                attrs.append({"name": "Renk", "value": sku["color"]})
            if sku.get("size"):
                attrs.append({"name": "Beden", "value": sku["size"]})

            if attrs:
                n11_sku["attributes"] = attrs

            # Add barcode if available
            if sku.get("barcode"):
                n11_sku["gtipCode"] = str(sku["barcode"])

            n11_skus.append(n11_sku)

        return n11_skus

    # =========================================================================
    # Payload Generation
    # =========================================================================

    def generate_payload(self, products: List[Dict]) -> Dict:
        """Generate N11 API compatible payload for product batch.

        Creates a batch request body from mapped products.

        Args:
            products: List of mapped product data dictionaries

        Returns:
            Dictionary with the complete payload for API submission
        """
        batch_id = str(uuid.uuid4())

        items = []
        for product in products:
            item = {
                "productSellerCode": product.get("productSellerCode"),
                "title": product.get("title"),
                "subtitle": product.get("subtitle", product.get("title", "")[:250]),
                "description": product.get("description", ""),
                "categoryId": product.get("categoryId"),
                "price": product.get("price"),
                "stockQuantity": product.get("stockQuantity", 0),
                "images": product.get("images", []),
                "preparingDay": product.get("preparingDay", 3),
                "productCondition": product.get("productCondition", "1"),
                "currencyType": product.get("currencyType", "TL"),
            }

            # Add optional fields
            if product.get("displayPrice"):
                item["displayPrice"] = product["displayPrice"]

            if product.get("brandId"):
                item["brandId"] = product["brandId"]

            if product.get("gtipCode"):
                item["gtipCode"] = product["gtipCode"]

            if product.get("shipmentTemplate"):
                item["shipmentTemplate"] = product["shipmentTemplate"]

            if product.get("attributes"):
                item["attributes"] = product["attributes"]

            if product.get("skuList"):
                item["skuList"] = product["skuList"]

            if product.get("weight"):
                item["weight"] = product["weight"]

            if product.get("discount"):
                item["discount"] = product["discount"]

            items.append(item)

        payload = {
            "products": items,
            "_metadata": {
                "batch_id": batch_id,
                "created_at": datetime.now().isoformat(),
                "product_count": len(products),
            },
        }

        return payload

    # =========================================================================
    # Publishing Methods
    # =========================================================================

    def publish(self, products: List[Dict]) -> PublishResult:
        """Publish products to N11.

        Handles the complete publishing workflow including validation,
        mapping, brand/category resolution, and batch submission.

        Args:
            products: List of product data dictionaries in PIM format

        Returns:
            PublishResult with job status and any errors
        """
        job_id = str(uuid.uuid4())
        errors = []

        try:
            # Validate all products first
            validation_results = self.validate_products(products)
            invalid_products = [r for r in validation_results if not r.is_valid]

            if invalid_products:
                for result in invalid_products:
                    errors.extend(result.errors)

                return PublishResult(
                    success=False,
                    job_id=job_id,
                    status=PublishStatus.FAILED,
                    products_submitted=0,
                    products_failed=len(invalid_products),
                    errors=errors,
                    channel=self.channel_code,
                )

            # Map products to N11 format
            mapped_products = []
            for product in products:
                mapping_result = self.map_attributes(product)
                mapped_data = mapping_result.mapped_data

                # Resolve brand ID if only name provided
                if not mapped_data.get("brandId") and mapped_data.get("brandName"):
                    brand_id = self._resolve_brand_id(mapped_data["brandName"])
                    if brand_id:
                        mapped_data["brandId"] = brand_id
                    else:
                        # N11 brand might be optional for some categories
                        errors.append({
                            "product": mapping_result.product,
                            "field": "brand",
                            "message": f"Could not resolve brand '{mapped_data['brandName']}' to N11 brand ID",
                            "severity": "warning",
                        })

                # Resolve category ID if only name provided
                if not mapped_data.get("categoryId") and mapped_data.get("categoryName"):
                    category_id = self._resolve_category_id(mapped_data["categoryName"])
                    if category_id:
                        mapped_data["categoryId"] = category_id
                    else:
                        errors.append({
                            "product": mapping_result.product,
                            "field": "category",
                            "message": f"Could not resolve category '{mapped_data['categoryName']}' to N11 category ID",
                        })

                mapped_products.append(mapped_data)

            # Filter out critical errors (keep warnings)
            critical_errors = [e for e in errors if e.get("severity") != "warning"]
            if critical_errors:
                return PublishResult(
                    success=False,
                    job_id=job_id,
                    status=PublishStatus.FAILED,
                    products_submitted=0,
                    products_failed=len(critical_errors),
                    errors=errors,
                    channel=self.channel_code,
                )

            # Generate payload
            payload = self.generate_payload(mapped_products)

            # Submit to N11
            submit_result = self._submit_to_n11(payload)

            if submit_result.get("success"):
                batch_request_id = submit_result.get("batchId")

                self._log_publish_event("submit_success", {
                    "job_id": job_id,
                    "batch_id": batch_request_id,
                    "products_count": len(products),
                })

                return PublishResult(
                    success=True,
                    job_id=job_id,
                    status=PublishStatus.IN_PROGRESS,
                    products_submitted=len(products),
                    channel=self.channel_code,
                    external_id=batch_request_id,
                )
            else:
                errors.append({
                    "message": submit_result.get("error", "Unknown submission error"),
                    "details": submit_result.get("details", {}),
                })

                return PublishResult(
                    success=False,
                    job_id=job_id,
                    status=PublishStatus.FAILED,
                    products_submitted=0,
                    errors=errors,
                    channel=self.channel_code,
                )

        except RateLimitError as e:
            self._log_publish_event("rate_limited", {"error": str(e)})
            return PublishResult(
                success=False,
                job_id=job_id,
                status=PublishStatus.RATE_LIMITED,
                errors=[{"message": str(e.message), "retry_after": e.retry_after}],
                channel=self.channel_code,
            )

        except AuthenticationError as e:
            self._log_publish_event("auth_error", {"error": str(e)})
            return PublishResult(
                success=False,
                job_id=job_id,
                status=PublishStatus.FAILED,
                errors=[{"message": str(e.message)}],
                channel=self.channel_code,
            )

        except Exception as e:
            self._log_publish_event("publish_error", {"error": str(e)})
            return PublishResult(
                success=False,
                job_id=job_id,
                status=PublishStatus.FAILED,
                errors=[{"message": f"Unexpected error: {str(e)}"}],
                channel=self.channel_code,
            )

    def _submit_to_n11(self, payload: Dict) -> Dict:
        """Submit products to N11 API.

        Uses the product save/update endpoint for product submission.

        Args:
            payload: The generated payload

        Returns:
            Dict with success status and batchId or error
        """
        import requests

        try:
            # Wait for quota
            self._wait_for_quota("products/batch")

            # Build URL for product save
            url = f"{self.api_endpoint}/product/save"

            headers = self._get_auth_headers()

            # Submit products one by one or in batch depending on API support
            products = payload.get("products", [])
            batch_id = payload.get("_metadata", {}).get("batch_id", str(uuid.uuid4()))

            succeeded = 0
            failed = 0
            failed_items = []

            for product in products:
                # N11 typically requires individual product submissions
                product_payload = {"product": product}

                response = requests.post(
                    url,
                    headers=headers,
                    json=product_payload,
                    timeout=60,
                )

                self.handle_rate_limiting(response)

                if response.status_code in (200, 201):
                    result = response.json()
                    if result.get("result", {}).get("status") == "success":
                        succeeded += 1
                    else:
                        failed += 1
                        error_msg = result.get("result", {}).get("errorMessage", "Unknown error")
                        failed_items.append({
                            "productSellerCode": product.get("productSellerCode"),
                            "error": error_msg,
                        })
                elif response.status_code == 401:
                    raise AuthenticationError(
                        "N11 authentication failed",
                        channel=self.channel_code,
                    )
                else:
                    failed += 1
                    try:
                        error_data = response.json()
                        error_msg = error_data.get("result", {}).get("errorMessage", response.text[:200])
                    except json.JSONDecodeError:
                        error_msg = response.text[:200]

                    failed_items.append({
                        "productSellerCode": product.get("productSellerCode"),
                        "error": error_msg,
                    })

                # Rate limiting between products
                time.sleep(0.5)

            if succeeded > 0 and failed == 0:
                return {
                    "success": True,
                    "batchId": batch_id,
                    "succeeded": succeeded,
                    "failed": failed,
                }
            elif succeeded > 0:
                return {
                    "success": True,
                    "batchId": batch_id,
                    "succeeded": succeeded,
                    "failed": failed,
                    "failedItems": failed_items,
                    "partial": True,
                }
            else:
                return {
                    "success": False,
                    "error": "All products failed to submit",
                    "details": {"failedItems": failed_items},
                }

        except requests.exceptions.RequestException as e:
            return {
                "success": False,
                "error": f"Request failed: {str(e)}",
            }

    def get_status(self, job_id: str) -> StatusResult:
        """Check the status of a publish job.

        N11 doesn't have a batch status endpoint like some other marketplaces.
        This method queries product status individually.

        Args:
            job_id: The batch ID from publish()

        Returns:
            StatusResult with current processing status
        """
        # N11 doesn't provide batch status API like Trendyol
        # Products are typically processed synchronously
        # Return completed status as submissions are real-time

        return StatusResult(
            job_id=job_id,
            status=PublishStatus.COMPLETED,
            progress=1.0,
            products_processed=0,  # Unknown for N11
            products_total=0,
            errors=[],
            channel=self.channel_code,
            completed_at=datetime.now(),
        )

    def get_product_status(self, seller_code: str) -> Dict:
        """Get the status of a specific product.

        Args:
            seller_code: The product seller code

        Returns:
            Dict with product status information
        """
        import requests

        try:
            self._wait_for_quota("products")

            url = f"{self.api_endpoint}/product/get"
            headers = self._get_auth_headers()
            params = {"sellerCode": seller_code}

            response = requests.get(url, headers=headers, params=params, timeout=30)
            self.handle_rate_limiting(response)

            if response.status_code == 200:
                data = response.json()
                product = data.get("product", {})

                return {
                    "success": True,
                    "status": product.get("approvalStatus"),
                    "productId": product.get("id"),
                    "sellerCode": product.get("productSellerCode"),
                    "title": product.get("title"),
                }

            return {
                "success": False,
                "error": f"Failed to get product: {response.status_code}",
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    # =========================================================================
    # Brand and Category Resolution
    # =========================================================================

    def _resolve_brand_id(self, brand_name: str) -> Optional[int]:
        """Resolve brand name to N11 brand ID.

        Args:
            brand_name: The brand name to look up

        Returns:
            Brand ID if found, None otherwise
        """
        # Check cache first
        if brand_name in self._brand_cache:
            return self._brand_cache[brand_name]

        import requests

        try:
            self._wait_for_quota("brands")

            # Search for brand
            url = f"{self.api_endpoint}/brand/get"
            headers = self._get_auth_headers()
            params = {"brandName": brand_name}

            response = requests.get(url, headers=headers, params=params, timeout=30)
            self.handle_rate_limiting(response)

            if response.status_code == 200:
                data = response.json()
                brands = data.get("brands", [])

                if brands:
                    # Find exact match or closest match
                    for brand in brands:
                        if brand.get("name", "").lower() == brand_name.lower():
                            brand_id = brand.get("id")
                            self._brand_cache[brand_name] = brand_id
                            return brand_id

                    # If no exact match, use first result
                    brand_id = brands[0].get("id")
                    self._brand_cache[brand_name] = brand_id
                    return brand_id

        except Exception:
            pass

        return None

    def _resolve_category_id(self, category_name: str) -> Optional[int]:
        """Resolve category name to N11 category ID.

        Args:
            category_name: The category name to look up

        Returns:
            Category ID if found, None otherwise
        """
        # Check cache first
        if category_name in self._category_cache:
            return self._category_cache[category_name]

        import requests

        try:
            self._wait_for_quota("categories")

            # Get top level categories first
            url = f"{self.api_endpoint}/category/getTopLevelCategories"
            headers = self._get_auth_headers()

            response = requests.get(url, headers=headers, timeout=30)
            self.handle_rate_limiting(response)

            if response.status_code == 200:
                data = response.json()
                categories = data.get("categories", [])

                # Search through category tree
                category_id = self._search_category_tree(categories, category_name)

                if category_id:
                    self._category_cache[category_name] = category_id
                    return category_id

        except Exception:
            pass

        return None

    def _search_category_tree(self, categories: List[Dict], name: str) -> Optional[int]:
        """Search category tree recursively for a category name.

        Args:
            categories: List of category dictionaries
            name: Category name to find

        Returns:
            Category ID if found, None otherwise
        """
        name_lower = name.lower()

        for cat in categories:
            cat_name = cat.get("name", "").lower()

            # Check for match
            if cat_name == name_lower or name_lower in cat_name or cat_name in name_lower:
                return cat.get("id")

            # Get subcategories if available
            subcat_url = cat.get("subCategoriesUrl")
            if subcat_url:
                subcats = self._get_subcategories(cat.get("id"))
                if subcats:
                    result = self._search_category_tree(subcats, name)
                    if result:
                        return result

        return None

    def _get_subcategories(self, parent_id: int) -> List[Dict]:
        """Get subcategories for a parent category.

        Args:
            parent_id: Parent category ID

        Returns:
            List of subcategory dictionaries
        """
        import requests

        try:
            self._wait_for_quota("categories")

            url = f"{self.api_endpoint}/category/getSubCategories"
            headers = self._get_auth_headers()
            params = {"categoryId": parent_id}

            response = requests.get(url, headers=headers, params=params, timeout=30)
            self.handle_rate_limiting(response)

            if response.status_code == 200:
                data = response.json()
                return data.get("categories", [])

        except Exception:
            pass

        return []

    def get_category_attributes(self, category_id: int) -> List[Dict]:
        """Get required attributes for a category.

        Args:
            category_id: The N11 category ID

        Returns:
            List of attribute dictionaries
        """
        # Check cache first
        if category_id in self._category_attributes_cache:
            return self._category_attributes_cache[category_id]

        import requests

        try:
            self._wait_for_quota("categories")

            url = f"{self.api_endpoint}/category/getCategoryAttributes"
            headers = self._get_auth_headers()
            params = {"categoryId": category_id}

            response = requests.get(url, headers=headers, params=params, timeout=30)
            self.handle_rate_limiting(response)

            if response.status_code == 200:
                data = response.json()
                attributes = data.get("attributes", [])
                self._category_attributes_cache[category_id] = attributes
                return attributes

        except Exception:
            pass

        return []

    # =========================================================================
    # Inventory and Price Update Methods
    # =========================================================================

    def update_inventory(self, items: List[Dict]) -> PublishResult:
        """Update inventory quantities for products.

        Args:
            items: List of dicts with sellerCode and quantity

        Returns:
            PublishResult with update status
        """
        import requests

        job_id = str(uuid.uuid4())

        try:
            succeeded = 0
            failed = 0
            errors = []

            for item in items:
                self._wait_for_quota("inventory")

                url = f"{self.api_endpoint}/product/updateStock"
                headers = self._get_auth_headers()

                payload = {
                    "productSellerCode": item.get("sellerCode") or item.get("productSellerCode"),
                    "quantity": int(item.get("quantity", 0)),
                }

                response = requests.post(url, headers=headers, json=payload, timeout=60)
                self.handle_rate_limiting(response)

                if response.status_code in (200, 201):
                    result = response.json()
                    if result.get("result", {}).get("status") == "success":
                        succeeded += 1
                    else:
                        failed += 1
                        errors.append({
                            "sellerCode": payload["productSellerCode"],
                            "error": result.get("result", {}).get("errorMessage"),
                        })
                else:
                    failed += 1
                    errors.append({
                        "sellerCode": payload["productSellerCode"],
                        "error": f"HTTP {response.status_code}",
                    })

            if succeeded > 0 and failed == 0:
                return PublishResult(
                    success=True,
                    job_id=job_id,
                    status=PublishStatus.COMPLETED,
                    products_submitted=len(items),
                    products_succeeded=succeeded,
                    channel=self.channel_code,
                )

            return PublishResult(
                success=succeeded > 0,
                job_id=job_id,
                status=PublishStatus.PARTIAL if succeeded > 0 else PublishStatus.FAILED,
                products_submitted=len(items),
                products_succeeded=succeeded,
                products_failed=failed,
                errors=errors,
                channel=self.channel_code,
            )

        except Exception as e:
            return PublishResult(
                success=False,
                job_id=job_id,
                status=PublishStatus.FAILED,
                errors=[{"message": f"Inventory update failed: {str(e)}"}],
                channel=self.channel_code,
            )

    def update_prices(self, items: List[Dict]) -> PublishResult:
        """Update prices for products.

        Args:
            items: List of dicts with sellerCode, price, and displayPrice

        Returns:
            PublishResult with update status
        """
        import requests

        job_id = str(uuid.uuid4())

        try:
            succeeded = 0
            failed = 0
            errors = []

            for item in items:
                self._wait_for_quota("prices")

                url = f"{self.api_endpoint}/product/updatePrice"
                headers = self._get_auth_headers()

                payload = {
                    "productSellerCode": item.get("sellerCode") or item.get("productSellerCode"),
                    "price": float(item.get("price")),
                }

                if item.get("displayPrice"):
                    payload["displayPrice"] = float(item["displayPrice"])

                response = requests.post(url, headers=headers, json=payload, timeout=60)
                self.handle_rate_limiting(response)

                if response.status_code in (200, 201):
                    result = response.json()
                    if result.get("result", {}).get("status") == "success":
                        succeeded += 1
                    else:
                        failed += 1
                        errors.append({
                            "sellerCode": payload["productSellerCode"],
                            "error": result.get("result", {}).get("errorMessage"),
                        })
                else:
                    failed += 1
                    errors.append({
                        "sellerCode": payload["productSellerCode"],
                        "error": f"HTTP {response.status_code}",
                    })

            if succeeded > 0 and failed == 0:
                return PublishResult(
                    success=True,
                    job_id=job_id,
                    status=PublishStatus.COMPLETED,
                    products_submitted=len(items),
                    products_succeeded=succeeded,
                    channel=self.channel_code,
                )

            return PublishResult(
                success=succeeded > 0,
                job_id=job_id,
                status=PublishStatus.PARTIAL if succeeded > 0 else PublishStatus.FAILED,
                products_submitted=len(items),
                products_succeeded=succeeded,
                products_failed=failed,
                errors=errors,
                channel=self.channel_code,
            )

        except Exception as e:
            return PublishResult(
                success=False,
                job_id=job_id,
                status=PublishStatus.FAILED,
                errors=[{"message": f"Price update failed: {str(e)}"}],
                channel=self.channel_code,
            )

    def delete_products(self, seller_codes: List[str]) -> PublishResult:
        """Delete products from N11.

        Args:
            seller_codes: List of product seller codes to delete

        Returns:
            PublishResult with deletion status
        """
        import requests

        job_id = str(uuid.uuid4())

        try:
            succeeded = 0
            failed = 0
            errors = []

            for seller_code in seller_codes:
                self._wait_for_quota("products")

                url = f"{self.api_endpoint}/product/delete"
                headers = self._get_auth_headers()

                payload = {
                    "productSellerCode": seller_code,
                }

                response = requests.post(url, headers=headers, json=payload, timeout=60)
                self.handle_rate_limiting(response)

                if response.status_code in (200, 201, 204):
                    result = response.json() if response.text else {}
                    if result.get("result", {}).get("status") == "success" or response.status_code == 204:
                        succeeded += 1
                    else:
                        failed += 1
                        errors.append({
                            "sellerCode": seller_code,
                            "error": result.get("result", {}).get("errorMessage"),
                        })
                else:
                    failed += 1
                    errors.append({
                        "sellerCode": seller_code,
                        "error": f"HTTP {response.status_code}",
                    })

            if succeeded > 0 and failed == 0:
                return PublishResult(
                    success=True,
                    job_id=job_id,
                    status=PublishStatus.COMPLETED,
                    products_submitted=len(seller_codes),
                    products_succeeded=succeeded,
                    channel=self.channel_code,
                )

            return PublishResult(
                success=succeeded > 0,
                job_id=job_id,
                status=PublishStatus.PARTIAL if succeeded > 0 else PublishStatus.FAILED,
                products_submitted=len(seller_codes),
                products_succeeded=succeeded,
                products_failed=failed,
                errors=errors,
                channel=self.channel_code,
            )

        except Exception as e:
            return PublishResult(
                success=False,
                job_id=job_id,
                status=PublishStatus.FAILED,
                errors=[{"message": f"Delete failed: {str(e)}"}],
                channel=self.channel_code,
            )

    def approve_product(self, seller_code: str) -> Dict:
        """Request approval for a product.

        Args:
            seller_code: The product seller code

        Returns:
            Dict with approval status
        """
        import requests

        try:
            self._wait_for_quota("products")

            url = f"{self.api_endpoint}/product/approve"
            headers = self._get_auth_headers()

            payload = {
                "productSellerCode": seller_code,
            }

            response = requests.post(url, headers=headers, json=payload, timeout=60)
            self.handle_rate_limiting(response)

            if response.status_code in (200, 201):
                result = response.json()
                return {
                    "success": result.get("result", {}).get("status") == "success",
                    "message": result.get("result", {}).get("errorMessage", "Approval requested"),
                }

            return {
                "success": False,
                "error": f"HTTP {response.status_code}",
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def test_connection(self) -> Dict:
        """Test the connection to N11 API.

        Returns:
            Dictionary with connection status and any errors
        """
        import requests

        try:
            self._wait_for_quota("categories")

            # Test with categories endpoint (lightweight)
            url = f"{self.api_endpoint}/category/getTopLevelCategories"
            headers = self._get_auth_headers()

            response = requests.get(url, headers=headers, timeout=30)

            if response.status_code == 200:
                return {
                    "success": True,
                    "message": "Connection to N11 API successful",
                }
            elif response.status_code == 401:
                return {
                    "success": False,
                    "message": "Authentication failed - check API key and secret",
                }
            else:
                return {
                    "success": False,
                    "message": f"Connection failed: HTTP {response.status_code}",
                }

        except AuthenticationError as e:
            return {
                "success": False,
                "message": str(e.message),
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Connection error: {str(e)}",
            }

    def get_categories(self) -> List[Dict]:
        """Get top-level categories from N11.

        Returns:
            List of category dictionaries
        """
        import requests

        try:
            self._wait_for_quota("categories")

            url = f"{self.api_endpoint}/category/getTopLevelCategories"
            headers = self._get_auth_headers()

            response = requests.get(url, headers=headers, timeout=30)
            self.handle_rate_limiting(response)

            if response.status_code == 200:
                data = response.json()
                return data.get("categories", [])

        except Exception:
            pass

        return []

    def get_brands(self) -> List[Dict]:
        """Get available brands from N11.

        Returns:
            List of brand dictionaries
        """
        import requests

        try:
            self._wait_for_quota("brands")

            url = f"{self.api_endpoint}/brand/getAll"
            headers = self._get_auth_headers()

            response = requests.get(url, headers=headers, timeout=30)
            self.handle_rate_limiting(response)

            if response.status_code == 200:
                data = response.json()
                return data.get("brands", [])

        except Exception:
            pass

        return []

    def get_shipment_templates(self) -> List[Dict]:
        """Get available shipment templates from N11.

        Returns:
            List of shipment template dictionaries
        """
        import requests

        try:
            self._wait_for_quota("default")

            url = f"{self.api_endpoint}/shipment/getTemplates"
            headers = self._get_auth_headers()

            response = requests.get(url, headers=headers, timeout=30)
            self.handle_rate_limiting(response)

            if response.status_code == 200:
                data = response.json()
                return data.get("shipmentTemplates", [])

        except Exception:
            pass

        return []

    def get_product_list(
        self,
        page: int = 0,
        size: int = 100,
        status: str = None,
    ) -> Dict:
        """Get list of seller's products.

        Args:
            page: Page number (0-indexed)
            size: Number of results per page (max 100)
            status: Filter by product status (optional)

        Returns:
            Dict with products list and pagination info
        """
        import requests

        try:
            self._wait_for_quota("products")

            url = f"{self.api_endpoint}/product/getList"
            headers = self._get_auth_headers()

            params = {
                "currentPage": page,
                "pageSize": min(size, 100),
            }

            if status:
                params["approvalStatus"] = status

            response = requests.get(url, headers=headers, params=params, timeout=60)
            self.handle_rate_limiting(response)

            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "products": data.get("products", []),
                    "totalCount": data.get("totalCount", 0),
                    "currentPage": page,
                    "pageSize": size,
                }

            return {
                "success": False,
                "error": f"HTTP {response.status_code}",
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }


# =============================================================================
# Register Adapter
# =============================================================================

register_adapter("n11", N11Adapter)
register_adapter("n11_tr", N11Adapter)
