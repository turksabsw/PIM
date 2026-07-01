"""
Hepsiburada Channel Adapter

Provides adapter for Hepsiburada marketplace - one of Turkey's largest e-commerce platforms.
Uses the Hepsiburada Merchant API for product management and order operations.

Features:
- API Key + Merchant ID authentication
- Category-specific attribute requirements
- Brand registration and validation
- Product variants support (color, size)
- Image processing for Hepsiburada requirements
- Rate limiting with per-endpoint quota tracking
- Batch product submission
- Price and inventory sync
- Listing quality scoring

API Documentation: https://developers.hepsiburada.com/

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
import hmac

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
# Hepsiburada-Specific Constants
# =============================================================================

class HepsiburadaEnvironment(str, Enum):
    """Hepsiburada API environments"""
    PRODUCTION = "mpop.hepsiburada.com"
    SANDBOX = "mpop-sit.hepsiburada.com"


class HepsiburadaProductStatus(str, Enum):
    """Hepsiburada product approval status"""
    DRAFT = "Draft"
    WAITING_APPROVAL = "WaitingApproval"
    APPROVED = "Approved"
    REJECTED = "Rejected"
    SUSPENDED = "Suspended"
    PASSIVE = "Passive"
    ACTIVE = "Active"
    DELETED = "Deleted"


class HepsiburadaCurrency(str, Enum):
    """Hepsiburada supported currencies"""
    TRY = "TRY"  # Turkish Lira
    USD = "USD"
    EUR = "EUR"


class HepsiburadaVatRate(int, Enum):
    """Hepsiburada VAT rate percentages"""
    ZERO = 0
    ONE = 1
    EIGHT = 8
    TEN = 10
    EIGHTEEN = 18
    TWENTY = 20


class HepsiburadaListingType(str, Enum):
    """Hepsiburada listing types"""
    SIMPLE = "Simple"  # Single product
    VARIANT = "Variant"  # Product with variants
    BUNDLE = "Bundle"  # Product bundle


# Rate limits for Hepsiburada API endpoints (requests per minute)
HEPSIBURADA_RATE_LIMITS = {
    "products": 60,
    "products/batch": 10,
    "inventory": 120,
    "prices": 120,
    "categories": 30,
    "brands": 30,
    "listings": 60,
    "orders": 60,
    "default": 30,
}

# Burst limits (max concurrent requests)
HEPSIBURADA_BURST_LIMITS = {
    "products": 10,
    "products/batch": 3,
    "inventory": 20,
    "prices": 20,
    "categories": 5,
    "brands": 5,
    "listings": 10,
    "orders": 10,
    "default": 5,
}


# =============================================================================
# Hepsiburada-Specific Data Classes
# =============================================================================

@dataclass
class HepsiburadaQuotaState:
    """Tracks API quota state per endpoint"""
    endpoint: str
    requests_made: int = 0
    requests_limit: int = 60
    burst_remaining: int = 10
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
            self.burst_remaining = HEPSIBURADA_BURST_LIMITS.get(
                self.endpoint, HEPSIBURADA_BURST_LIMITS["default"]
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
class HepsiburadaBatchResult:
    """Result of a batch operation"""
    tracking_id: str
    status: str = "PROCESSING"
    items_received: int = 0
    items_processed: int = 0
    items_failed: int = 0
    items_succeeded: int = 0
    failed_items: List[Dict] = field(default_factory=list)
    error_messages: List[str] = field(default_factory=list)


# =============================================================================
# Hepsiburada Required Fields and Validation Rules
# =============================================================================

# Required fields for Hepsiburada product listings
HEPSIBURADA_REQUIRED_FIELDS = {
    "merchantSku",  # Seller's product code
    "productName",  # Product title
    "categoryId",
    "price",
    "availableStock",
    "images",
    "barcode",  # Required for most categories
}

# Optional but recommended fields
HEPSIBURADA_RECOMMENDED_FIELDS = {
    "description",
    "brandId",
    "tax",  # VAT rate
    "listPrice",  # Original price (for discount display)
    "maxPurchaseQuantity",
    "attributes",
    "deliveryDuration",  # Days to deliver
    "deliveryOption",
    "warranty",
    "domesticDelivery",
    "internationalDelivery",
}

# Field length limits
HEPSIBURADA_FIELD_LIMITS = {
    "productName": 255,
    "description": 50000,
    "merchantSku": 100,
    "warranty": 500,
}

# PIM to Hepsiburada field mappings
PIM_TO_HEPSIBURADA_FIELDS = {
    "item_code": "merchantSku",
    "item_name": "productName",
    "pim_title": "productName",
    "pim_description": "description",
    "barcode": "barcode",
    "gtin": "barcode",
    "standard_rate": "price",
    "valuation_rate": "listPrice",
    "brand": "brandName",
    "item_group": "categoryName",
    "stock_qty": "availableStock",
    "net_weight": "weight",
    "image": "images",
    "country_of_origin": "countryOfOrigin",
    "warranty_period": "warranty",
}

# Hepsiburada attribute type mappings (Turkish)
HEPSIBURADA_ATTRIBUTE_TYPES = {
    "color": "Renk",
    "size": "Beden",
    "material": "Materyal",
    "pattern": "Desen",
    "gender": "Cinsiyet",
    "age_group": "Yas Grubu",
    "season": "Sezon",
    "fabric": "Kumas",
    "model": "Model",
    "capacity": "Kapasite",
}

# Delivery option types
HEPSIBURADA_DELIVERY_OPTIONS = {
    "STANDARD": "1",
    "FAST": "2",
    "SAME_DAY": "3",
    "CARGO": "4",
}


# =============================================================================
# Hepsiburada Channel Adapter
# =============================================================================

class HepsiburadaAdapter(ChannelAdapter):
    """
    Hepsiburada marketplace adapter.

    Handles product publishing, inventory updates, and order sync with Hepsiburada.
    Uses API Key + Merchant ID authentication with HMAC signature.

    Hepsiburada is one of Turkey's largest e-commerce platforms, offering
    both marketplace and fulfillment services (HepsiBurada Fulfillment - HBF).
    """

    channel_code: str = "hepsiburada"
    channel_name: str = "Hepsiburada"

    # Rate limit settings
    default_requests_per_minute: int = 60
    default_requests_per_second: float = 1.0
    max_retry_attempts: int = 5
    base_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 120.0

    # API version
    API_VERSION = "v1"
    LISTING_API_PATH = "/product/api/products"
    INVENTORY_API_PATH = "/stock/api"
    CATEGORY_API_PATH = "/product/api/categories"

    def __init__(self, channel_doc: Any = None):
        """Initialize Hepsiburada adapter.

        Args:
            channel_doc: Channel Frappe document with Hepsiburada credentials
        """
        super().__init__(channel_doc)
        self._quota_states: Dict[str, HepsiburadaQuotaState] = {}
        self._brand_cache: Dict[str, int] = {}
        self._category_cache: Dict[str, int] = {}
        self._category_attributes_cache: Dict[int, List[Dict]] = {}

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def merchant_id(self) -> str:
        """Get the Hepsiburada merchant/seller ID."""
        return self.config.get("merchant_id") or self.credentials.get("merchant_id", "")

    @property
    def api_endpoint(self) -> str:
        """Get the Hepsiburada API endpoint based on environment."""
        environment = self.config.get("environment", "production")

        if environment.lower() == "sandbox":
            host = HepsiburadaEnvironment.SANDBOX.value
        else:
            host = HepsiburadaEnvironment.PRODUCTION.value

        return f"https://{host}"

    @property
    def listing_api_url(self) -> str:
        """Get the listing API URL."""
        return f"{self.api_endpoint}{self.LISTING_API_PATH}"

    @property
    def inventory_api_url(self) -> str:
        """Get the inventory API URL."""
        return f"{self.api_endpoint}{self.INVENTORY_API_PATH}"

    @property
    def category_api_url(self) -> str:
        """Get the category API URL."""
        return f"{self.api_endpoint}{self.CATEGORY_API_PATH}"

    # =========================================================================
    # Authentication Methods
    # =========================================================================

    def _get_auth_headers(self) -> Dict:
        """Build authentication headers for Hepsiburada API requests.

        Hepsiburada uses API Key authentication with optional HMAC signature.

        Returns:
            Dictionary of HTTP headers including authorization
        """
        api_key = self.credentials.get("api_key", "")
        api_secret = self.credentials.get("api_secret", "")

        if not api_key:
            raise AuthenticationError(
                "Hepsiburada API key not configured",
                channel=self.channel_code,
            )

        # Create Basic Auth header with API key and secret
        if api_secret:
            auth_string = f"{api_key}:{api_secret}"
            auth_bytes = auth_string.encode("utf-8")
            auth_base64 = base64.b64encode(auth_bytes).decode("utf-8")
            auth_header = f"Basic {auth_base64}"
        else:
            auth_header = f"Bearer {api_key}"

        headers = {
            "Authorization": auth_header,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"{self.config.get('user_agent', 'FrappePIM')}/1.0",
        }

        # Add merchant ID header if available
        if self.merchant_id:
            headers["X-Merchant-Id"] = self.merchant_id

        return headers

    def _generate_signature(self, data: str, timestamp: str) -> str:
        """Generate HMAC signature for request authentication.

        Args:
            data: Request data to sign
            timestamp: Request timestamp

        Returns:
            HMAC signature string
        """
        api_secret = self.credentials.get("api_secret", "")

        if not api_secret:
            return ""

        message = f"{timestamp}{data}"
        signature = hmac.new(
            api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        return signature

    # =========================================================================
    # Rate Limiting Methods
    # =========================================================================

    def _get_quota_state(self, endpoint: str) -> HepsiburadaQuotaState:
        """Get or create quota state for an endpoint.

        Args:
            endpoint: The API endpoint category (products, inventory, etc.)

        Returns:
            HepsiburadaQuotaState instance for the endpoint
        """
        if endpoint not in self._quota_states:
            rate_limit = HEPSIBURADA_RATE_LIMITS.get(endpoint, HEPSIBURADA_RATE_LIMITS["default"])
            burst_limit = HEPSIBURADA_BURST_LIMITS.get(endpoint, HEPSIBURADA_BURST_LIMITS["default"])

            self._quota_states[endpoint] = HepsiburadaQuotaState(
                endpoint=endpoint,
                requests_limit=rate_limit,
                burst_remaining=burst_limit,
            )

        return self._quota_states[endpoint]

    def handle_rate_limiting(self, response: Any = None) -> None:
        """Handle Hepsiburada API rate limiting from response.

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
                "Hepsiburada API rate limit exceeded",
                channel=self.channel_code,
                retry_after=retry_after,
                details={
                    "status_code": 429,
                    "retry_after": retry_after,
                },
            )

        # Check for 503 Service Unavailable
        if hasattr(response, 'status_code') and response.status_code == 503:
            raise RateLimitError(
                "Hepsiburada API service unavailable (possible rate limit)",
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
                        "Hepsiburada API quota exhausted",
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
                    f"Hepsiburada quota exhausted for {endpoint}, wait time ({wait_time}s) exceeds maximum",
                    channel=self.channel_code,
                    retry_after=int(wait_time),
                )
            time.sleep(wait_time)

        quota_state.record_request()

    # =========================================================================
    # Validation Methods
    # =========================================================================

    def validate_product(self, product: Dict) -> ValidationResult:
        """Validate a product against Hepsiburada's listing requirements.

        Checks required fields, field length limits, barcode format,
        category/brand IDs, and other Hepsiburada-specific requirements.

        Args:
            product: Product data dictionary in PIM format

        Returns:
            ValidationResult with validation status and any errors/warnings
        """
        errors = []
        warnings = []
        product_id = product.get("item_code", product.get("merchantSku", "unknown"))

        # Check required fields
        for field_name in HEPSIBURADA_REQUIRED_FIELDS:
            # Check both PIM and Hepsiburada field names
            pim_field = None
            for pim_name, hb_name in PIM_TO_HEPSIBURADA_FIELDS.items():
                if hb_name.lower() == field_name.lower() or field_name == pim_name:
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

            if not value:
                errors.append({
                    "field": field_name,
                    "message": f"Required field '{field_name}' is missing",
                    "rule": "required",
                })

        # Check field length limits
        for field_name, max_length in HEPSIBURADA_FIELD_LIMITS.items():
            value = product.get(field_name, "")
            # Also check PIM field name
            for pim_name, hb_name in PIM_TO_HEPSIBURADA_FIELDS.items():
                if hb_name.lower() == field_name.lower():
                    value = value or product.get(pim_name, "")
                    break

            if isinstance(value, str) and len(value) > max_length:
                errors.append({
                    "field": field_name,
                    "message": f"Field '{field_name}' exceeds maximum length of {max_length} characters",
                    "value": f"{len(value)} characters",
                    "rule": "max_length",
                })

        # Validate barcode (required for most categories)
        barcode = product.get("barcode") or product.get("gtin")
        if barcode:
            barcode_error = self._validate_barcode(barcode)
            if barcode_error:
                errors.append(barcode_error)
        else:
            # Barcode is required for most categories
            errors.append({
                "field": "barcode",
                "message": "Barcode (GTIN/EAN/UPC) is required for Hepsiburada listings",
                "rule": "required",
            })

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

        # Validate list price >= sale price
        list_price = product.get("valuation_rate") or product.get("listPrice")
        sale_price = price
        if list_price and sale_price:
            try:
                if float(list_price) < float(sale_price):
                    errors.append({
                        "field": "listPrice",
                        "message": "List price must be greater than or equal to sale price",
                        "value": f"list: {list_price}, sale: {sale_price}",
                        "rule": "price_comparison",
                    })
            except (ValueError, TypeError):
                pass

        # Validate quantity
        quantity = product.get("quantity") or product.get("availableStock") or product.get("stock_qty", 0)
        try:
            qty_val = int(quantity)
            if qty_val < 0:
                errors.append({
                    "field": "availableStock",
                    "message": "Stock quantity cannot be negative",
                    "value": str(quantity),
                    "rule": "non_negative",
                })
        except (ValueError, TypeError):
            errors.append({
                "field": "availableStock",
                "message": "Stock quantity must be a valid integer",
                "value": str(quantity),
                "rule": "integer",
            })

        # Validate VAT rate
        vat_rate = product.get("tax") or product.get("vat_rate", 18)
        valid_vat_rates = [e.value for e in HepsiburadaVatRate]
        if vat_rate not in valid_vat_rates:
            warnings.append({
                "field": "tax",
                "message": f"VAT rate {vat_rate} is not standard, using default 18%",
                "rule": "vat_rate_standard",
            })

        # Validate images
        images = product.get("images") or product.get("image")
        if images:
            image_errors, image_warnings = self._validate_images(images)
            errors.extend(image_errors)
            warnings.extend(image_warnings)

        # Check for recommended fields
        for field_name in HEPSIBURADA_RECOMMENDED_FIELDS:
            if field_name not in product:
                pim_field = None
                for pim_name, hb_name in PIM_TO_HEPSIBURADA_FIELDS.items():
                    if hb_name.lower() == field_name.lower():
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

        Hepsiburada requires valid GTIN (EAN-13, UPC-A, etc.)

        Args:
            barcode: Barcode string

        Returns:
            Error dict if invalid, None if valid
        """
        # Remove any spaces or dashes
        barcode = str(barcode).replace(" ", "").replace("-", "")

        # Check length - Hepsiburada accepts EAN-8, EAN-13, UPC-A, GTIN-14
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
        """Validate product images against Hepsiburada requirements.

        Hepsiburada image requirements:
        - Minimum 1 image, maximum 8 images
        - JPEG or PNG format
        - Minimum 500x500 pixels
        - White background preferred
        - First image is main image
        - No watermarks or promotional text

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
        """Map PIM product attributes to Hepsiburada format.

        Converts internal field names to Hepsiburada's expected format
        and transforms values as needed.

        Args:
            product: Product data dictionary in PIM format

        Returns:
            MappingResult with mapped data and unmapped fields
        """
        product_id = product.get("item_code", product.get("merchantSku", "unknown"))
        mapped_data = {}
        unmapped_fields = []

        # Merchant SKU (required)
        mapped_data["merchantSku"] = product.get("item_code") or product.get("merchantSku")

        # Product name (required)
        product_name = product.get("pim_title") or product.get("item_name") or product.get("productName")
        if product_name:
            # Truncate to Hepsiburada limit
            mapped_data["productName"] = product_name[:255]

        # Description
        description = product.get("pim_description") or product.get("description")
        if description:
            # Truncate to Hepsiburada limit
            mapped_data["description"] = description[:50000]

        # Barcode (required)
        barcode = product.get("barcode") or product.get("gtin")
        if barcode:
            mapped_data["barcode"] = str(barcode).replace(" ", "").replace("-", "")

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
        list_price = product.get("valuation_rate") or product.get("listPrice")

        if price is not None:
            mapped_data["price"] = float(price)

        if list_price is not None:
            mapped_data["listPrice"] = float(list_price)
        elif price is not None:
            # List price defaults to sale price
            mapped_data["listPrice"] = float(price)

        # Currency (Hepsiburada defaults to TRY)
        currency = product.get("currency", "TRY")
        if currency.upper() in [c.value for c in HepsiburadaCurrency]:
            mapped_data["currency"] = currency.upper()
        else:
            mapped_data["currency"] = HepsiburadaCurrency.TRY.value

        # Stock quantity (required)
        quantity = product.get("quantity") or product.get("availableStock") or product.get("stock_qty", 0)
        mapped_data["availableStock"] = int(quantity) if quantity else 0

        # VAT rate (tax, default to 18%)
        vat_rate = product.get("tax") or product.get("vat_rate", 18)
        mapped_data["tax"] = int(vat_rate)

        # Delivery duration (days)
        delivery_duration = product.get("deliveryDuration") or product.get("lead_time", 3)
        mapped_data["deliveryDuration"] = int(delivery_duration)

        # Max purchase quantity
        max_qty = product.get("maxPurchaseQuantity")
        if max_qty:
            mapped_data["maxPurchaseQuantity"] = int(max_qty)

        # Warranty
        warranty = product.get("warranty") or product.get("warranty_period")
        if warranty:
            mapped_data["warranty"] = str(warranty)[:500]

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

        # Variants (for variant products)
        variants = product.get("variants") or product.get("sku_list")
        if variants:
            mapped_data["variants"] = self._map_variants(variants)
            mapped_data["listingType"] = HepsiburadaListingType.VARIANT.value
        else:
            mapped_data["listingType"] = HepsiburadaListingType.SIMPLE.value

        # Track unmapped fields
        mapped_pim_fields = set(PIM_TO_HEPSIBURADA_FIELDS.keys())
        mapped_pim_fields.update({
            "product_main_id", "brand_id", "category_id", "currency",
            "delivery_duration", "max_purchase_quantity", "warranty",
            "images", "attributes", "color", "size", "quantity",
            "variants", "sku_list", "tax", "vat_rate",
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
        """Map images to Hepsiburada format.

        Args:
            images: Image data (URL, path, or list)

        Returns:
            List of image dictionaries for Hepsiburada API
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
        """Map product attributes to Hepsiburada format.

        Args:
            attributes: List of attribute dictionaries

        Returns:
            List of Hepsiburada-format attributes
        """
        hb_attrs = []

        for attr in attributes:
            attr_id = attr.get("attribute_id") or attr.get("attributeId")
            attr_name = attr.get("attribute_name") or attr.get("name")
            attr_value_id = attr.get("attribute_value_id") or attr.get("valueId")
            attr_value = attr.get("attribute_value") or attr.get("value")

            hb_attr = {}

            if attr_id:
                hb_attr["attributeId"] = str(attr_id)
            if attr_name:
                hb_attr["attributeName"] = str(attr_name)
            if attr_value_id:
                hb_attr["attributeValueId"] = str(attr_value_id)
            if attr_value:
                hb_attr["attributeValue"] = str(attr_value)

            if hb_attr:
                hb_attrs.append(hb_attr)

        return hb_attrs

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
                "attributeName": "Renk",
                "attributeValue": str(color),
            })

        # Size
        size = product.get("size") or product.get("beden")
        if size:
            attributes.append({
                "attributeName": "Beden",
                "attributeValue": str(size),
            })

        # Material
        material = product.get("material") or product.get("materyal")
        if material:
            attributes.append({
                "attributeName": "Materyal",
                "attributeValue": str(material),
            })

        # Gender
        gender = product.get("gender") or product.get("cinsiyet")
        if gender:
            attributes.append({
                "attributeName": "Cinsiyet",
                "attributeValue": str(gender),
            })

        # Model
        model = product.get("model")
        if model:
            attributes.append({
                "attributeName": "Model",
                "attributeValue": str(model),
            })

        return attributes

    def _map_variants(self, variants: List[Dict]) -> List[Dict]:
        """Map variants to Hepsiburada format.

        Args:
            variants: List of variant dictionaries

        Returns:
            List of Hepsiburada-format variant items
        """
        hb_variants = []

        for variant in variants:
            hb_variant = {
                "merchantSku": variant.get("sku") or variant.get("merchantSku") or variant.get("seller_code"),
                "barcode": str(variant.get("barcode", "")).replace(" ", "").replace("-", ""),
                "price": float(variant.get("price", 0)) if variant.get("price") else None,
                "availableStock": int(variant.get("quantity", 0)),
            }

            # Add variant attributes
            attrs = []
            if variant.get("color"):
                attrs.append({"attributeName": "Renk", "attributeValue": variant["color"]})
            if variant.get("size"):
                attrs.append({"attributeName": "Beden", "attributeValue": variant["size"]})

            if attrs:
                hb_variant["attributes"] = attrs

            # Add list price if available
            if variant.get("listPrice"):
                hb_variant["listPrice"] = float(variant["listPrice"])

            hb_variants.append(hb_variant)

        return hb_variants

    # =========================================================================
    # Payload Generation
    # =========================================================================

    def generate_payload(self, products: List[Dict]) -> Dict:
        """Generate Hepsiburada API compatible payload for product batch.

        Creates a batch request body from mapped products.

        Args:
            products: List of mapped product data dictionaries

        Returns:
            Dictionary with the complete payload for API submission
        """
        tracking_id = str(uuid.uuid4())

        items = []
        for product in products:
            item = {
                "merchantSku": product.get("merchantSku"),
                "productName": product.get("productName"),
                "categoryId": product.get("categoryId"),
                "barcode": product.get("barcode"),
                "price": product.get("price"),
                "availableStock": product.get("availableStock", 0),
                "tax": product.get("tax", 18),
            }

            # Add optional fields
            if product.get("description"):
                item["description"] = product["description"]

            if product.get("brandId"):
                item["brandId"] = product["brandId"]

            if product.get("listPrice"):
                item["listPrice"] = product["listPrice"]

            if product.get("images"):
                item["images"] = product["images"]

            if product.get("attributes"):
                item["attributes"] = product["attributes"]

            if product.get("variants"):
                item["variants"] = product["variants"]

            if product.get("listingType"):
                item["listingType"] = product["listingType"]

            if product.get("deliveryDuration"):
                item["deliveryDuration"] = product["deliveryDuration"]

            if product.get("maxPurchaseQuantity"):
                item["maxPurchaseQuantity"] = product["maxPurchaseQuantity"]

            if product.get("warranty"):
                item["warranty"] = product["warranty"]

            if product.get("weight"):
                item["weight"] = product["weight"]

            items.append(item)

        payload = {
            "listings": items,
            "_metadata": {
                "tracking_id": tracking_id,
                "created_at": datetime.now().isoformat(),
                "product_count": len(products),
            },
        }

        return payload

    # =========================================================================
    # Publishing Methods
    # =========================================================================

    def publish(self, products: List[Dict]) -> PublishResult:
        """Publish products to Hepsiburada.

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

            # Map products to Hepsiburada format
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
                        # Hepsiburada brand might be optional for some categories
                        errors.append({
                            "product": mapping_result.product,
                            "field": "brand",
                            "message": f"Could not resolve brand '{mapped_data['brandName']}' to Hepsiburada brand ID",
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
                            "message": f"Could not resolve category '{mapped_data['categoryName']}' to Hepsiburada category ID",
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

            # Submit to Hepsiburada
            submit_result = self._submit_to_hepsiburada(payload)

            if submit_result.get("success"):
                tracking_id = submit_result.get("trackingId")

                self._log_publish_event("submit_success", {
                    "job_id": job_id,
                    "tracking_id": tracking_id,
                    "products_count": len(products),
                })

                return PublishResult(
                    success=True,
                    job_id=job_id,
                    status=PublishStatus.IN_PROGRESS,
                    products_submitted=len(products),
                    channel=self.channel_code,
                    external_id=tracking_id,
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

    def _submit_to_hepsiburada(self, payload: Dict) -> Dict:
        """Submit products to Hepsiburada API.

        Uses the listing API for product submission.

        Args:
            payload: The generated payload

        Returns:
            Dict with success status and trackingId or error
        """
        import requests

        try:
            # Wait for quota
            self._wait_for_quota("products/batch")

            # Build URL for product import
            url = f"{self.listing_api_url}/import"

            headers = self._get_auth_headers()

            # Submit products
            listings = payload.get("listings", [])
            tracking_id = payload.get("_metadata", {}).get("tracking_id", str(uuid.uuid4()))

            response = requests.post(
                url,
                headers=headers,
                json={"listings": listings},
                timeout=120,
            )

            self.handle_rate_limiting(response)

            if response.status_code in (200, 201, 202):
                result = response.json() if response.text else {}
                return {
                    "success": True,
                    "trackingId": result.get("trackingId", tracking_id),
                }

            elif response.status_code == 400:
                # Validation error from Hepsiburada
                try:
                    error_data = response.json()
                    return {
                        "success": False,
                        "error": "Validation failed",
                        "details": error_data,
                    }
                except json.JSONDecodeError:
                    return {
                        "success": False,
                        "error": f"Bad request: {response.text[:500]}",
                    }

            elif response.status_code == 401:
                raise AuthenticationError(
                    "Hepsiburada authentication failed",
                    channel=self.channel_code,
                )

            else:
                return {
                    "success": False,
                    "error": f"Request failed with status {response.status_code}",
                    "details": {"response": response.text[:500]},
                }

        except requests.exceptions.RequestException as e:
            return {
                "success": False,
                "error": f"Request failed: {str(e)}",
            }

    def get_status(self, job_id: str) -> StatusResult:
        """Check the status of a batch request.

        Args:
            job_id: The tracking ID from publish()

        Returns:
            StatusResult with current processing status
        """
        import requests

        try:
            self._wait_for_quota("products")

            # Hepsiburada tracking status endpoint
            url = f"{self.listing_api_url}/import/status/{job_id}"
            headers = self._get_auth_headers()

            response = requests.get(url, headers=headers, timeout=30)
            self.handle_rate_limiting(response)

            if response.status_code != 200:
                return StatusResult(
                    job_id=job_id,
                    status=PublishStatus.FAILED,
                    errors=[{"message": f"Failed to get status: {response.status_code}"}],
                    channel=self.channel_code,
                )

            data = response.json()
            batch_status = data.get("status", "").upper()

            # Map Hepsiburada status to our status
            status_mapping = {
                "COMPLETED": PublishStatus.COMPLETED,
                "SUCCESS": PublishStatus.COMPLETED,
                "PROCESSING": PublishStatus.IN_PROGRESS,
                "IN_PROGRESS": PublishStatus.IN_PROGRESS,
                "PENDING": PublishStatus.PENDING,
                "FAILED": PublishStatus.FAILED,
                "PARTIAL": PublishStatus.PARTIAL,
            }

            status = status_mapping.get(batch_status, PublishStatus.IN_PROGRESS)

            # Get error details for failed items
            errors = []
            results = data.get("results", [])
            failed_count = 0
            success_count = 0

            for item in results:
                if item.get("status") == "FAILED":
                    failed_count += 1
                    error_message = item.get("errorMessage") or item.get("message", "Unknown error")
                    errors.append({
                        "merchantSku": item.get("merchantSku"),
                        "message": error_message,
                    })
                elif item.get("status") in ("SUCCESS", "COMPLETED"):
                    success_count += 1

            total_items = len(results) if results else data.get("totalCount", 0)
            processed = failed_count + success_count

            # Calculate progress
            progress = processed / total_items if total_items > 0 else 0.0

            return StatusResult(
                job_id=job_id,
                status=status,
                progress=progress,
                products_processed=processed,
                products_total=total_items,
                errors=errors,
                channel=self.channel_code,
                completed_at=datetime.now() if status == PublishStatus.COMPLETED else None,
            )

        except Exception as e:
            return StatusResult(
                job_id=job_id,
                status=PublishStatus.FAILED,
                errors=[{"message": f"Status check failed: {str(e)}"}],
                channel=self.channel_code,
            )

    def get_listing_status(self, merchant_sku: str) -> Dict:
        """Get the status of a specific listing.

        Args:
            merchant_sku: The merchant SKU

        Returns:
            Dict with listing status information
        """
        import requests

        try:
            self._wait_for_quota("listings")

            url = f"{self.listing_api_url}/listing"
            headers = self._get_auth_headers()
            params = {"merchantSku": merchant_sku}

            response = requests.get(url, headers=headers, params=params, timeout=30)
            self.handle_rate_limiting(response)

            if response.status_code == 200:
                data = response.json()

                return {
                    "success": True,
                    "status": data.get("status"),
                    "listingId": data.get("listingId"),
                    "merchantSku": data.get("merchantSku"),
                    "productName": data.get("productName"),
                    "price": data.get("price"),
                    "availableStock": data.get("availableStock"),
                }

            return {
                "success": False,
                "error": f"Failed to get listing: {response.status_code}",
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
        """Resolve brand name to Hepsiburada brand ID.

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
            url = f"{self.api_endpoint}/product/api/brands"
            headers = self._get_auth_headers()
            params = {"name": brand_name}

            response = requests.get(url, headers=headers, params=params, timeout=30)
            self.handle_rate_limiting(response)

            if response.status_code == 200:
                data = response.json()
                brands = data.get("brands", data.get("data", []))

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
        """Resolve category name to Hepsiburada category ID.

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

            # Get all categories and search
            url = f"{self.category_api_url}/get-all"
            headers = self._get_auth_headers()

            response = requests.get(url, headers=headers, timeout=30)
            self.handle_rate_limiting(response)

            if response.status_code == 200:
                data = response.json()
                categories = data.get("categories", data.get("data", []))

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
                return cat.get("id") or cat.get("categoryId")

            # Search subcategories
            subcats = cat.get("subCategories", cat.get("children", []))
            if subcats:
                result = self._search_category_tree(subcats, name)
                if result:
                    return result

        return None

    def get_category_attributes(self, category_id: int) -> List[Dict]:
        """Get required attributes for a category.

        Args:
            category_id: The Hepsiburada category ID

        Returns:
            List of attribute dictionaries
        """
        # Check cache first
        if category_id in self._category_attributes_cache:
            return self._category_attributes_cache[category_id]

        import requests

        try:
            self._wait_for_quota("categories")

            url = f"{self.category_api_url}/{category_id}/attributes"
            headers = self._get_auth_headers()

            response = requests.get(url, headers=headers, timeout=30)
            self.handle_rate_limiting(response)

            if response.status_code == 200:
                data = response.json()
                attributes = data.get("attributes", data.get("data", []))
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
            items: List of dicts with merchantSku and availableStock

        Returns:
            PublishResult with update status
        """
        import requests

        job_id = str(uuid.uuid4())

        try:
            self._wait_for_quota("inventory")

            url = f"{self.inventory_api_url}/stocks"
            headers = self._get_auth_headers()

            # Format items for API
            inventory_items = []
            for item in items:
                inventory_items.append({
                    "merchantSku": item.get("merchantSku") or item.get("sku"),
                    "availableStock": int(item.get("availableStock") or item.get("quantity", 0)),
                })

            payload = {"stocks": inventory_items}

            response = requests.post(url, headers=headers, json=payload, timeout=60)
            self.handle_rate_limiting(response)

            if response.status_code in (200, 201, 202):
                result = response.json() if response.text else {}
                return PublishResult(
                    success=True,
                    job_id=job_id,
                    status=PublishStatus.COMPLETED,
                    products_submitted=len(items),
                    products_succeeded=len(items),
                    channel=self.channel_code,
                    external_id=result.get("trackingId"),
                )

            return PublishResult(
                success=False,
                job_id=job_id,
                status=PublishStatus.FAILED,
                errors=[{"message": f"Update failed: {response.status_code}"}],
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
            items: List of dicts with merchantSku, price, and listPrice

        Returns:
            PublishResult with update status
        """
        import requests

        job_id = str(uuid.uuid4())

        try:
            self._wait_for_quota("prices")

            url = f"{self.listing_api_url}/prices"
            headers = self._get_auth_headers()

            # Format items for API
            price_items = []
            for item in items:
                price_item = {
                    "merchantSku": item.get("merchantSku") or item.get("sku"),
                    "price": float(item.get("price")),
                }

                if item.get("listPrice"):
                    price_item["listPrice"] = float(item["listPrice"])

                price_items.append(price_item)

            payload = {"prices": price_items}

            response = requests.post(url, headers=headers, json=payload, timeout=60)
            self.handle_rate_limiting(response)

            if response.status_code in (200, 201, 202):
                result = response.json() if response.text else {}
                return PublishResult(
                    success=True,
                    job_id=job_id,
                    status=PublishStatus.COMPLETED,
                    products_submitted=len(items),
                    products_succeeded=len(items),
                    channel=self.channel_code,
                    external_id=result.get("trackingId"),
                )

            return PublishResult(
                success=False,
                job_id=job_id,
                status=PublishStatus.FAILED,
                errors=[{"message": f"Update failed: {response.status_code}"}],
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

    def delete_listings(self, merchant_skus: List[str]) -> PublishResult:
        """Delete listings from Hepsiburada.

        Args:
            merchant_skus: List of merchant SKUs to delete

        Returns:
            PublishResult with deletion status
        """
        import requests

        job_id = str(uuid.uuid4())

        try:
            succeeded = 0
            failed = 0
            errors = []

            for merchant_sku in merchant_skus:
                self._wait_for_quota("products")

                url = f"{self.listing_api_url}/listing"
                headers = self._get_auth_headers()
                params = {"merchantSku": merchant_sku}

                response = requests.delete(url, headers=headers, params=params, timeout=60)
                self.handle_rate_limiting(response)

                if response.status_code in (200, 201, 204):
                    succeeded += 1
                else:
                    failed += 1
                    errors.append({
                        "merchantSku": merchant_sku,
                        "error": f"HTTP {response.status_code}",
                    })

            if succeeded > 0 and failed == 0:
                return PublishResult(
                    success=True,
                    job_id=job_id,
                    status=PublishStatus.COMPLETED,
                    products_submitted=len(merchant_skus),
                    products_succeeded=succeeded,
                    channel=self.channel_code,
                )

            return PublishResult(
                success=succeeded > 0,
                job_id=job_id,
                status=PublishStatus.PARTIAL if succeeded > 0 else PublishStatus.FAILED,
                products_submitted=len(merchant_skus),
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

    def activate_listing(self, merchant_sku: str) -> Dict:
        """Activate a listing.

        Args:
            merchant_sku: The merchant SKU

        Returns:
            Dict with activation status
        """
        import requests

        try:
            self._wait_for_quota("listings")

            url = f"{self.listing_api_url}/listing/activate"
            headers = self._get_auth_headers()
            payload = {"merchantSku": merchant_sku}

            response = requests.post(url, headers=headers, json=payload, timeout=60)
            self.handle_rate_limiting(response)

            if response.status_code in (200, 201):
                return {
                    "success": True,
                    "message": "Listing activated",
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

    def deactivate_listing(self, merchant_sku: str) -> Dict:
        """Deactivate a listing.

        Args:
            merchant_sku: The merchant SKU

        Returns:
            Dict with deactivation status
        """
        import requests

        try:
            self._wait_for_quota("listings")

            url = f"{self.listing_api_url}/listing/deactivate"
            headers = self._get_auth_headers()
            payload = {"merchantSku": merchant_sku}

            response = requests.post(url, headers=headers, json=payload, timeout=60)
            self.handle_rate_limiting(response)

            if response.status_code in (200, 201):
                return {
                    "success": True,
                    "message": "Listing deactivated",
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
        """Test the connection to Hepsiburada API.

        Returns:
            Dictionary with connection status and any errors
        """
        import requests

        try:
            self._wait_for_quota("categories")

            # Test with categories endpoint (lightweight)
            url = f"{self.category_api_url}/get-all"
            headers = self._get_auth_headers()
            params = {"page": 0, "size": 1}

            response = requests.get(url, headers=headers, params=params, timeout=30)

            if response.status_code == 200:
                return {
                    "success": True,
                    "message": "Connection to Hepsiburada API successful",
                }
            elif response.status_code == 401:
                return {
                    "success": False,
                    "message": "Authentication failed - check API key and secret",
                }
            elif response.status_code == 403:
                return {
                    "success": False,
                    "message": "Access denied - check merchant ID and permissions",
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

    def get_categories(self, page: int = 0, size: int = 100) -> List[Dict]:
        """Get categories from Hepsiburada.

        Args:
            page: Page number (0-indexed)
            size: Number of results per page

        Returns:
            List of category dictionaries
        """
        import requests

        try:
            self._wait_for_quota("categories")

            url = f"{self.category_api_url}/get-all"
            headers = self._get_auth_headers()
            params = {"page": page, "size": size}

            response = requests.get(url, headers=headers, params=params, timeout=30)
            self.handle_rate_limiting(response)

            if response.status_code == 200:
                data = response.json()
                return data.get("categories", data.get("data", []))

        except Exception:
            pass

        return []

    def get_brands(self, page: int = 0, size: int = 100) -> List[Dict]:
        """Get available brands from Hepsiburada.

        Args:
            page: Page number (0-indexed)
            size: Number of results per page

        Returns:
            List of brand dictionaries
        """
        import requests

        try:
            self._wait_for_quota("brands")

            url = f"{self.api_endpoint}/product/api/brands"
            headers = self._get_auth_headers()
            params = {"page": page, "size": size}

            response = requests.get(url, headers=headers, params=params, timeout=30)
            self.handle_rate_limiting(response)

            if response.status_code == 200:
                data = response.json()
                return data.get("brands", data.get("data", []))

        except Exception:
            pass

        return []

    def get_listings(
        self,
        page: int = 0,
        size: int = 100,
        status: str = None,
    ) -> Dict:
        """Get merchant's listings.

        Args:
            page: Page number (0-indexed)
            size: Number of results per page (max 100)
            status: Filter by listing status (optional)

        Returns:
            Dict with listings and pagination info
        """
        import requests

        try:
            self._wait_for_quota("listings")

            url = f"{self.listing_api_url}/listings"
            headers = self._get_auth_headers()

            params = {
                "page": page,
                "size": min(size, 100),
            }

            if status:
                params["status"] = status

            response = requests.get(url, headers=headers, params=params, timeout=60)
            self.handle_rate_limiting(response)

            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "listings": data.get("listings", data.get("data", [])),
                    "totalCount": data.get("totalCount", 0),
                    "page": page,
                    "size": size,
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

    def get_listing_quality_score(self, merchant_sku: str) -> Dict:
        """Get listing quality score for a product.

        Hepsiburada provides listing quality scores based on
        completeness, images, description, etc.

        Args:
            merchant_sku: The merchant SKU

        Returns:
            Dict with quality score information
        """
        import requests

        try:
            self._wait_for_quota("listings")

            url = f"{self.listing_api_url}/quality-score"
            headers = self._get_auth_headers()
            params = {"merchantSku": merchant_sku}

            response = requests.get(url, headers=headers, params=params, timeout=30)
            self.handle_rate_limiting(response)

            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "merchantSku": merchant_sku,
                    "qualityScore": data.get("qualityScore"),
                    "issues": data.get("issues", []),
                    "recommendations": data.get("recommendations", []),
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

register_adapter("hepsiburada", HepsiburadaAdapter)
register_adapter("hepsiburada_tr", HepsiburadaAdapter)
register_adapter("hb", HepsiburadaAdapter)
