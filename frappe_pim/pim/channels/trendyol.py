"""
Trendyol Channel Adapter

Provides a comprehensive adapter for Trendyol marketplace product syndication
using the Trendyol Integration API.

Features:
- Trendyol Integration API (REST) integration
- Supplier ID based authentication with API credentials
- Rate limiting with configurable limits
- Comprehensive product validation against Trendyol requirements
- Attribute mapping to Trendyol product format
- Support for single and batch product operations
- Category and brand management
- Stock and price synchronization

Note: frappe imports are deferred to function/method level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import json
import time
import uuid
import base64

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
# Trendyol-Specific Constants
# =============================================================================

class TrendyolProductStatus(str, Enum):
    """Trendyol product status values"""
    WAITING = "waiting"
    APPROVED = "approved"
    REJECTED = "rejected"
    ON_SALE = "onSale"
    SUSPENDED = "suspended"


class TrendyolCurrency(str, Enum):
    """Trendyol currency values"""
    TRY = "TRY"
    USD = "USD"
    EUR = "EUR"


# Trendyol API endpoints
TRENDYOL_API_BASE_URL = "https://api.trendyol.com/sapigw"
TRENDYOL_API_STAGING_URL = "https://stageapi.trendyol.com/stagesapigw"

# Trendyol rate limit configuration
# Default: 50 requests per minute for most endpoints
TRENDYOL_RATE_LIMITS = {
    "default": {
        "requests_per_minute": 50,
        "requests_per_second": 2,
        "burst_limit": 10,
    },
    "product_create": {
        "requests_per_minute": 30,
        "requests_per_second": 1,
        "burst_limit": 5,
    },
    "batch": {
        "requests_per_minute": 20,
        "requests_per_second": 0.5,
        "burst_limit": 3,
    },
}

# Required fields for Trendyol products
TRENDYOL_REQUIRED_FIELDS = {
    "barcode",
    "title",
    "productMainId",
    "brandId",
    "categoryId",
    "quantity",
    "stockCode",
    "listPrice",
    "salePrice",
    "currencyType",
    "images",
}

# Recommended fields for better listings
TRENDYOL_RECOMMENDED_FIELDS = {
    "description",
    "vatRate",
    "cargoCompanyId",
    "attributes",
    "dimensionalWeight",
}

# Field length limits
TRENDYOL_FIELD_LIMITS = {
    "title": 200,
    "description": 30000,
    "productMainId": 100,
    "stockCode": 100,
    "barcode": 40,
}

# PIM to Trendyol field mappings
PIM_TO_TRENDYOL_FIELDS = {
    "item_code": "stockCode",
    "item_name": "title",
    "pim_title": "title",
    "pim_description": "description",
    "description": "description",
    "barcode": "barcode",
    "gtin": "barcode",
    "standard_rate": "listPrice",
    "price": "listPrice",
    "sale_price": "salePrice",
    "stock_qty": "quantity",
    "actual_qty": "quantity",
    "brand": "brandId",
    "item_group": "categoryId",
    "weight_per_unit": "dimensionalWeight",
    "image": "images",
}


# =============================================================================
# Trendyol-Specific Data Classes
# =============================================================================

@dataclass
class TrendyolRateLimitState:
    """Tracks Trendyol rate limit state"""
    requests_made: int = 0
    requests_limit: int = 50
    window_start: datetime = field(default_factory=datetime.now)
    window_duration: int = 60  # seconds
    retry_after: datetime = None
    last_request: datetime = None
    burst_count: int = 0
    burst_window_start: datetime = field(default_factory=datetime.now)
    endpoint_type: str = "default"

    def is_limited(self) -> bool:
        """Check if currently rate limited"""
        if self.retry_after and datetime.now() < self.retry_after:
            return True

        # Reset minute window if expired
        if datetime.now() > self.window_start + timedelta(seconds=self.window_duration):
            self.requests_made = 0
            self.window_start = datetime.now()
            return False

        # Reset burst window if expired (1 second)
        if datetime.now() > self.burst_window_start + timedelta(seconds=1):
            self.burst_count = 0
            self.burst_window_start = datetime.now()

        limits = TRENDYOL_RATE_LIMITS.get(self.endpoint_type, TRENDYOL_RATE_LIMITS["default"])
        return (self.requests_made >= limits["requests_per_minute"] or
                self.burst_count >= limits["burst_limit"])

    def record_request(self) -> None:
        """Record that a request was made"""
        now = datetime.now()

        if now > self.window_start + timedelta(seconds=self.window_duration):
            self.requests_made = 0
            self.window_start = now

        if now > self.burst_window_start + timedelta(seconds=1):
            self.burst_count = 0
            self.burst_window_start = now

        self.requests_made += 1
        self.burst_count += 1
        self.last_request = now

    def wait_time(self) -> float:
        """Calculate wait time before next request"""
        if self.retry_after:
            delta = self.retry_after - datetime.now()
            if delta.total_seconds() > 0:
                return delta.total_seconds()

        if self.is_limited():
            limits = TRENDYOL_RATE_LIMITS.get(self.endpoint_type, TRENDYOL_RATE_LIMITS["default"])
            if self.burst_count >= limits["burst_limit"]:
                burst_end = self.burst_window_start + timedelta(seconds=1)
                delta = burst_end - datetime.now()
                return max(0, delta.total_seconds())

            window_end = self.window_start + timedelta(seconds=self.window_duration)
            delta = window_end - datetime.now()
            return max(0, delta.total_seconds())

        return 0


@dataclass
class TrendyolBatchJob:
    """Tracks a Trendyol batch job"""
    job_id: str
    batch_request_id: str = None
    operation_type: str = "CREATE"  # CREATE, UPDATE, PRICE_STOCK
    status: str = "PENDING"
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime = None
    products_total: int = 0
    products_processed: int = 0
    products_succeeded: int = 0
    products_failed: int = 0
    errors: List[Dict] = field(default_factory=list)


# =============================================================================
# Trendyol Adapter
# =============================================================================

class TrendyolAdapter(ChannelAdapter):
    """
    Trendyol channel adapter for product syndication.

    Uses the Trendyol Integration API for product management with
    support for batch operations and async status checking.

    Features:
    - REST API with Basic Auth (API Key:Secret)
    - Batch product creation/update
    - Async batch status checking
    - Stock and price synchronization
    - Category and brand ID mapping
    - Image URL validation
    """

    channel_code: str = "trendyol"
    channel_name: str = "Trendyol"

    # Rate limiting settings
    default_requests_per_minute: int = 50
    default_requests_per_second: float = 2.0
    max_retry_attempts: int = 5
    base_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 120.0

    # Batch size for bulk operations
    batch_size: int = 100

    def __init__(self, channel_doc: Any = None):
        """Initialize Trendyol adapter.

        Args:
            channel_doc: Channel Frappe document with Trendyol credentials
        """
        super().__init__(channel_doc)
        self._rate_limit_state: TrendyolRateLimitState = None
        self._supplier_id: str = None
        self._api_base_url: str = TRENDYOL_API_BASE_URL
        self._job_tracker: Dict[str, TrendyolBatchJob] = {}

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def supplier_id(self) -> str:
        """Get the Trendyol Supplier ID."""
        if self._supplier_id:
            return self._supplier_id

        self._supplier_id = self.config.get("supplier_id") or self.config.get("seller_id", "")
        return self._supplier_id

    @property
    def api_base_url(self) -> str:
        """Get the Trendyol API base URL."""
        if self.config.get("use_staging"):
            return TRENDYOL_API_STAGING_URL
        return self._api_base_url

    @property
    def rate_limit_state(self) -> TrendyolRateLimitState:
        """Get current rate limit state."""
        if self._rate_limit_state is None:
            self._rate_limit_state = TrendyolRateLimitState()
        return self._rate_limit_state

    # =========================================================================
    # Authentication Methods
    # =========================================================================

    def _get_trendyol_credentials(self) -> Dict:
        """Get Trendyol-specific credentials.

        Returns:
            Dictionary with:
            - api_key: Trendyol API key
            - api_secret: Trendyol API secret
            - supplier_id: Trendyol Supplier ID
        """
        credentials = self.credentials

        return {
            "api_key": credentials.get("api_key"),
            "api_secret": credentials.get("api_secret") or credentials.get("secret_key"),
            "supplier_id": self.supplier_id,
        }

    def _get_auth_headers(self) -> Dict:
        """Build authentication headers for Trendyol API requests.

        Returns:
            Dictionary of HTTP headers including Basic Auth
        """
        creds = self._get_trendyol_credentials()

        api_key = creds.get("api_key", "")
        api_secret = creds.get("api_secret", "")

        if not api_key or not api_secret:
            raise AuthenticationError(
                "Trendyol API key and secret are required",
                channel=self.channel_code,
            )

        # Basic Auth: base64(api_key:api_secret)
        auth_string = f"{api_key}:{api_secret}"
        encoded = base64.b64encode(auth_string.encode()).decode()

        return {
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"{api_key} - SelfIntegration",
        }

    # =========================================================================
    # Rate Limiting Methods
    # =========================================================================

    def handle_rate_limiting(self, response: Any = None) -> None:
        """Handle Trendyol rate limiting from response.

        Args:
            response: HTTP response object

        Raises:
            RateLimitError: If rate limit exceeded and cannot proceed
        """
        if response is None:
            return

        status_code = None
        if hasattr(response, 'status_code'):
            status_code = response.status_code
        elif isinstance(response, dict) and 'status_code' in response:
            status_code = response['status_code']

        if status_code == 429:
            retry_after = 60  # Default wait time

            if hasattr(response, 'headers'):
                retry_after = int(response.headers.get("Retry-After", 60))
            elif isinstance(response, dict) and 'headers' in response:
                retry_after = int(response.get('headers', {}).get("Retry-After", 60))

            self.rate_limit_state.retry_after = datetime.now() + timedelta(seconds=retry_after)

            raise RateLimitError(
                "Trendyol API rate limit exceeded",
                channel=self.channel_code,
                retry_after=retry_after,
                details={"status_code": 429, "retry_after": retry_after},
            )

        # Handle server errors as soft rate limit
        if status_code in (502, 503, 504):
            self.rate_limit_state.retry_after = datetime.now() + timedelta(seconds=10)

    def _wait_for_rate_limit(self) -> None:
        """Wait if rate limited.

        Raises:
            RateLimitError: If wait time exceeds maximum
        """
        wait_time = self.rate_limit_state.wait_time()

        if wait_time > 0:
            if wait_time > self.max_backoff_seconds:
                raise RateLimitError(
                    f"Trendyol rate limit wait time ({wait_time}s) exceeds maximum",
                    channel=self.channel_code,
                    retry_after=int(wait_time),
                )
            time.sleep(wait_time)

    # =========================================================================
    # API Request Methods
    # =========================================================================

    def _make_api_request(self, method: str, endpoint: str,
                          data: Dict = None, params: Dict = None,
                          endpoint_type: str = "default") -> Dict:
        """Make a request to the Trendyol API.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint (e.g., 'products')
            data: Request body data
            params: Query parameters
            endpoint_type: Type of endpoint for rate limiting

        Returns:
            API response data

        Raises:
            AuthenticationError: If authentication fails
            RateLimitError: If rate limit exceeded
            PublishError: If request fails
        """
        import requests

        self.rate_limit_state.endpoint_type = endpoint_type
        self._wait_for_rate_limit()

        # Build URL
        url = f"{self.api_base_url}/{endpoint}"

        last_error = None

        for attempt in range(self.max_retry_attempts):
            try:
                self.rate_limit_state.record_request()

                headers = self._get_auth_headers()

                if method.upper() == "GET":
                    response = requests.get(
                        url, headers=headers, params=params,
                        timeout=self.config.get("timeout", 30)
                    )
                elif method.upper() == "POST":
                    response = requests.post(
                        url, headers=headers, json=data,
                        timeout=self.config.get("timeout", 30)
                    )
                elif method.upper() == "PUT":
                    response = requests.put(
                        url, headers=headers, json=data,
                        timeout=self.config.get("timeout", 30)
                    )
                elif method.upper() == "DELETE":
                    response = requests.delete(
                        url, headers=headers, params=params,
                        timeout=self.config.get("timeout", 30)
                    )
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                # Handle rate limiting from response
                self.handle_rate_limiting(response)

                # Check for auth errors
                if response.status_code in (401, 403):
                    raise AuthenticationError(
                        f"Trendyol authentication failed: HTTP {response.status_code}",
                        channel=self.channel_code,
                    )

                # Check for success
                if response.status_code in (200, 201, 202):
                    try:
                        return response.json()
                    except Exception:
                        return {"success": True}

                # Handle other errors
                error_message = "Unknown error"
                try:
                    error_data = response.json()
                    if "errors" in error_data:
                        error_message = str(error_data["errors"])
                    elif "message" in error_data:
                        error_message = error_data["message"]
                    else:
                        error_message = str(error_data)
                except Exception:
                    error_message = response.text or f"HTTP {response.status_code}"

                raise PublishError(
                    f"Trendyol API error: {error_message}",
                    channel=self.channel_code,
                    details={"status_code": response.status_code, "response": response.text},
                )

            except RateLimitError:
                backoff = self._calculate_backoff(attempt)
                time.sleep(backoff)
                last_error = RateLimitError(
                    "Rate limit exceeded after retries",
                    channel=self.channel_code,
                )

            except AuthenticationError:
                raise

            except Exception as e:
                last_error = e
                if attempt < self.max_retry_attempts - 1:
                    backoff = self._calculate_backoff(attempt)
                    time.sleep(backoff)

        if isinstance(last_error, RateLimitError):
            raise last_error
        raise PublishError(
            f"Trendyol API request failed after {self.max_retry_attempts} attempts: {last_error}",
            channel=self.channel_code,
        )

    # =========================================================================
    # Validation Methods
    # =========================================================================

    def validate_product(self, product: Dict) -> ValidationResult:
        """Validate a product against Trendyol's requirements.

        Args:
            product: Product data dictionary in PIM format

        Returns:
            ValidationResult with validation status and any errors/warnings
        """
        errors = []
        warnings = []
        product_id = product.get("item_code", product.get("stockCode", "unknown"))

        # Check required fields
        for field_name in TRENDYOL_REQUIRED_FIELDS:
            pim_field = None
            for pim_name, ty_name in PIM_TO_TRENDYOL_FIELDS.items():
                if ty_name == field_name:
                    pim_field = pim_name
                    break

            value = product.get(field_name)
            if pim_field:
                value = value or product.get(pim_field)

            if not value and field_name not in ("brandId", "categoryId", "images"):
                errors.append({
                    "field": field_name,
                    "message": f"Required field '{field_name}' is missing",
                    "rule": "required",
                })

        # Validate barcode (GTIN)
        barcode = product.get("barcode") or product.get("gtin")
        if barcode:
            barcode_str = str(barcode).strip()
            if len(barcode_str) not in (8, 12, 13, 14):
                errors.append({
                    "field": "barcode",
                    "message": "Barcode must be a valid GTIN (8, 12, 13, or 14 digits)",
                    "value": barcode_str,
                    "rule": "gtin_format",
                })
            elif not barcode_str.isdigit():
                errors.append({
                    "field": "barcode",
                    "message": "Barcode must contain only digits",
                    "value": barcode_str,
                    "rule": "gtin_digits",
                })
        else:
            errors.append({
                "field": "barcode",
                "message": "Barcode (GTIN) is required for Trendyol",
                "rule": "required",
            })

        # Validate title length
        title = product.get("pim_title") or product.get("title") or product.get("item_name")
        if title:
            if len(str(title)) > TRENDYOL_FIELD_LIMITS["title"]:
                errors.append({
                    "field": "title",
                    "message": f"Title exceeds maximum length of {TRENDYOL_FIELD_LIMITS['title']} characters",
                    "value": f"{len(str(title))} characters",
                    "rule": "max_length",
                })
        else:
            errors.append({
                "field": "title",
                "message": "Product title is required",
                "rule": "required",
            })

        # Validate prices
        list_price = product.get("listPrice") or product.get("standard_rate") or product.get("price")
        sale_price = product.get("salePrice") or product.get("sale_price")

        if list_price is not None:
            try:
                list_val = float(list_price)
                if list_val <= 0:
                    errors.append({
                        "field": "listPrice",
                        "message": "List price must be greater than 0",
                        "value": str(list_price),
                        "rule": "positive_price",
                    })
            except (ValueError, TypeError):
                errors.append({
                    "field": "listPrice",
                    "message": "List price must be a valid number",
                    "value": str(list_price),
                    "rule": "numeric",
                })

        if sale_price is not None:
            try:
                sale_val = float(sale_price)
                if sale_val <= 0:
                    errors.append({
                        "field": "salePrice",
                        "message": "Sale price must be greater than 0",
                        "value": str(sale_price),
                        "rule": "positive_price",
                    })
                if list_price is not None:
                    list_val = float(list_price)
                    if sale_val > list_val:
                        errors.append({
                            "field": "salePrice",
                            "message": "Sale price cannot be greater than list price",
                            "value": str(sale_price),
                            "rule": "sale_price_logic",
                        })
            except (ValueError, TypeError):
                errors.append({
                    "field": "salePrice",
                    "message": "Sale price must be a valid number",
                    "value": str(sale_price),
                    "rule": "numeric",
                })

        # Validate quantity
        quantity = product.get("quantity") or product.get("stock_qty") or product.get("actual_qty")
        if quantity is not None:
            try:
                qty_val = int(quantity)
                if qty_val < 0:
                    errors.append({
                        "field": "quantity",
                        "message": "Quantity cannot be negative",
                        "value": str(quantity),
                        "rule": "non_negative",
                    })
            except (ValueError, TypeError):
                errors.append({
                    "field": "quantity",
                    "message": "Quantity must be an integer",
                    "value": str(quantity),
                    "rule": "integer",
                })

        # Validate images
        images = product.get("images") or product.get("image")
        if images:
            image_warnings = self._validate_images(images)
            warnings.extend(image_warnings)
        else:
            errors.append({
                "field": "images",
                "message": "At least one product image is required",
                "rule": "required",
            })

        # Validate brandId and categoryId
        brand_id = product.get("brandId") or product.get("brand_id")
        if not brand_id:
            warnings.append({
                "field": "brandId",
                "message": "Brand ID should be provided for better listing quality",
                "rule": "recommended",
            })

        category_id = product.get("categoryId") or product.get("category_id")
        if not category_id:
            warnings.append({
                "field": "categoryId",
                "message": "Category ID should be provided for better listing quality",
                "rule": "recommended",
            })

        # Check for recommended fields
        for field_name in TRENDYOL_RECOMMENDED_FIELDS:
            if field_name not in TRENDYOL_REQUIRED_FIELDS:
                value = product.get(field_name)
                if not value:
                    pim_field = None
                    for pim_name, ty_name in PIM_TO_TRENDYOL_FIELDS.items():
                        if ty_name == field_name:
                            pim_field = pim_name
                            break
                    if pim_field:
                        value = product.get(pim_field)
                    if not value:
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

    def _validate_images(self, images: Any) -> List[Dict]:
        """Validate product images for Trendyol.

        Args:
            images: Image data (URL, list of URLs, or list of dicts)

        Returns:
            List of warning dicts for image issues
        """
        warnings = []

        if isinstance(images, str):
            images = [{"url": images}]
        elif isinstance(images, list) and images and isinstance(images[0], str):
            images = [{"url": img} for img in images]

        if isinstance(images, list):
            # Trendyol recommends 1-8 images
            if len(images) > 8:
                warnings.append({
                    "field": "images",
                    "message": "Trendyol recommends maximum 8 images per product",
                    "value": str(len(images)),
                    "rule": "image_count",
                })

            for i, img in enumerate(images[:8]):
                img_url = img if isinstance(img, str) else img.get("url", "")
                if img_url:
                    # Must be HTTPS and accessible
                    if not img_url.startswith("https://"):
                        warnings.append({
                            "field": "images",
                            "message": f"Image {i+1} must use HTTPS URL",
                            "value": img_url[:100],
                            "rule": "image_https",
                        })
                    # Check for valid image extensions
                    valid_extensions = (".jpg", ".jpeg", ".png", ".webp")
                    if not any(img_url.lower().endswith(ext) for ext in valid_extensions):
                        warnings.append({
                            "field": "images",
                            "message": f"Image {i+1} should be JPG, PNG, or WebP format",
                            "value": img_url[:100],
                            "rule": "image_format",
                        })

        return warnings

    # =========================================================================
    # Mapping Methods
    # =========================================================================

    def map_attributes(self, product: Dict) -> MappingResult:
        """Map PIM product attributes to Trendyol format.

        Args:
            product: Product data dictionary in PIM format

        Returns:
            MappingResult with mapped data and unmapped fields
        """
        product_id = product.get("item_code", product.get("stockCode", "unknown"))
        mapped_data = {}
        unmapped_fields = []

        # Barcode (required)
        barcode = product.get("barcode") or product.get("gtin")
        if barcode:
            mapped_data["barcode"] = str(barcode).strip()

        # Title (required)
        title = product.get("pim_title") or product.get("title") or product.get("item_name")
        if title:
            mapped_data["title"] = str(title)[:TRENDYOL_FIELD_LIMITS["title"]]

        # Product Main ID (for grouping variants)
        product_main_id = (product.get("productMainId") or
                         product.get("product_main_id") or
                         product.get("item_code"))
        if product_main_id:
            mapped_data["productMainId"] = str(product_main_id)[:TRENDYOL_FIELD_LIMITS["productMainId"]]

        # Stock Code (required)
        stock_code = product.get("stockCode") or product.get("stock_code") or product.get("item_code")
        if stock_code:
            mapped_data["stockCode"] = str(stock_code)[:TRENDYOL_FIELD_LIMITS["stockCode"]]

        # Brand ID (required)
        brand_id = product.get("brandId") or product.get("brand_id") or product.get("trendyol_brand_id")
        if brand_id:
            mapped_data["brandId"] = int(brand_id)

        # Category ID (required)
        category_id = product.get("categoryId") or product.get("category_id") or product.get("trendyol_category_id")
        if category_id:
            mapped_data["categoryId"] = int(category_id)

        # Description
        description = product.get("pim_description") or product.get("description")
        if description:
            mapped_data["description"] = str(description)[:TRENDYOL_FIELD_LIMITS["description"]]

        # Pricing
        list_price = product.get("listPrice") or product.get("standard_rate") or product.get("price")
        if list_price is not None:
            mapped_data["listPrice"] = float(list_price)

        sale_price = product.get("salePrice") or product.get("sale_price")
        if sale_price is not None:
            mapped_data["salePrice"] = float(sale_price)
        elif list_price is not None:
            mapped_data["salePrice"] = float(list_price)

        # Currency
        currency = product.get("currencyType") or product.get("currency")
        if currency:
            currency_upper = str(currency).upper()
            if currency_upper in ("TRY", "TL", "LIRA"):
                mapped_data["currencyType"] = TrendyolCurrency.TRY.value
            elif currency_upper in ("USD", "DOLLAR"):
                mapped_data["currencyType"] = TrendyolCurrency.USD.value
            elif currency_upper in ("EUR", "EURO"):
                mapped_data["currencyType"] = TrendyolCurrency.EUR.value
            else:
                mapped_data["currencyType"] = TrendyolCurrency.TRY.value
        else:
            mapped_data["currencyType"] = TrendyolCurrency.TRY.value

        # Quantity
        quantity = product.get("quantity") or product.get("stock_qty") or product.get("actual_qty")
        if quantity is not None:
            mapped_data["quantity"] = max(0, int(quantity))
        else:
            mapped_data["quantity"] = 0

        # VAT Rate
        vat_rate = product.get("vatRate") or product.get("vat_rate") or product.get("tax_rate")
        if vat_rate is not None:
            mapped_data["vatRate"] = int(vat_rate)
        else:
            mapped_data["vatRate"] = 18  # Default Turkish VAT

        # Cargo Company ID
        cargo_company = product.get("cargoCompanyId") or product.get("cargo_company_id")
        if cargo_company:
            mapped_data["cargoCompanyId"] = int(cargo_company)

        # Dimensional Weight
        weight = (product.get("dimensionalWeight") or
                 product.get("weight_per_unit") or
                 product.get("weight"))
        if weight is not None:
            mapped_data["dimensionalWeight"] = float(weight)

        # Images
        images = self._map_images(product)
        if images:
            mapped_data["images"] = images

        # Attributes
        attributes = self._map_attributes_for_trendyol(product)
        if attributes:
            mapped_data["attributes"] = attributes

        # Track unmapped fields
        mapped_pim_fields = set(PIM_TO_TRENDYOL_FIELDS.keys())
        mapped_pim_fields.update({
            "barcode", "gtin", "title", "pim_title", "item_name",
            "productMainId", "product_main_id", "stockCode", "stock_code",
            "brandId", "brand_id", "trendyol_brand_id",
            "categoryId", "category_id", "trendyol_category_id",
            "description", "pim_description", "listPrice", "standard_rate", "price",
            "salePrice", "sale_price", "currencyType", "currency",
            "quantity", "stock_qty", "actual_qty", "vatRate", "vat_rate", "tax_rate",
            "cargoCompanyId", "cargo_company_id", "dimensionalWeight", "weight_per_unit",
            "weight", "images", "image", "attributes",
        })

        for field_name in product.keys():
            if field_name not in mapped_pim_fields and not field_name.startswith("_"):
                unmapped_fields.append(field_name)

        return MappingResult(
            product=product_id,
            mapped_data=mapped_data,
            unmapped_fields=unmapped_fields,
            channel=self.channel_code,
        )

    def _map_images(self, product: Dict) -> List[Dict]:
        """Map images to Trendyol format.

        Args:
            product: Product data dictionary

        Returns:
            List of image dictionaries with url
        """
        images = []
        image_data = product.get("images") or product.get("image")

        if image_data:
            if isinstance(image_data, str):
                images.append({"url": image_data})
            elif isinstance(image_data, list):
                for img in image_data[:8]:  # Max 8 images
                    if isinstance(img, str):
                        images.append({"url": img})
                    elif isinstance(img, dict):
                        img_url = img.get("url") or img.get("src")
                        if img_url:
                            images.append({"url": img_url})

        return images

    def _map_attributes_for_trendyol(self, product: Dict) -> List[Dict]:
        """Map product attributes to Trendyol format.

        Args:
            product: Product data dictionary

        Returns:
            List of attribute dictionaries
        """
        attributes = []
        attr_data = product.get("attributes") or product.get("trendyol_attributes")

        if attr_data and isinstance(attr_data, list):
            for attr in attr_data:
                if isinstance(attr, dict):
                    ty_attr = {}

                    # Attribute ID
                    if "attributeId" in attr:
                        ty_attr["attributeId"] = int(attr["attributeId"])
                    elif "attribute_id" in attr:
                        ty_attr["attributeId"] = int(attr["attribute_id"])

                    # Attribute Value ID (for predefined values)
                    if "attributeValueId" in attr:
                        ty_attr["attributeValueId"] = int(attr["attributeValueId"])
                    elif "attribute_value_id" in attr:
                        ty_attr["attributeValueId"] = int(attr["attribute_value_id"])

                    # Custom Value (for free-text attributes)
                    if "customAttributeValue" in attr:
                        ty_attr["customAttributeValue"] = str(attr["customAttributeValue"])
                    elif "custom_value" in attr:
                        ty_attr["customAttributeValue"] = str(attr["custom_value"])
                    elif "value" in attr and "attributeValueId" not in ty_attr:
                        ty_attr["customAttributeValue"] = str(attr["value"])

                    if ty_attr.get("attributeId"):
                        attributes.append(ty_attr)

        return attributes

    # =========================================================================
    # Payload Generation
    # =========================================================================

    def generate_payload(self, products: List[Dict]) -> Dict:
        """Generate Trendyol API payload for products.

        Args:
            products: List of mapped product data dictionaries

        Returns:
            Dictionary with products ready for API calls
        """
        payload = {
            "items": products,
            "_metadata": {
                "batch_id": str(uuid.uuid4()),
                "created_at": datetime.now().isoformat(),
                "product_count": len(products),
            },
        }

        return payload

    # =========================================================================
    # Publishing Methods
    # =========================================================================

    def publish(self, products: List[Dict]) -> PublishResult:
        """Publish products to Trendyol.

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

            # Map products to Trendyol format
            mapped_products = []
            for product in products:
                mapping_result = self.map_attributes(product)
                mapped_products.append(mapping_result.mapped_data)

            # Generate payload
            payload = self.generate_payload(mapped_products)

            # Submit to Trendyol API
            result = self._submit_batch(payload, job_id)
            return result

        except AuthenticationError as e:
            self._log_publish_event("auth_error", {"job_id": job_id, "error": str(e)})
            return PublishResult(
                success=False,
                job_id=job_id,
                status=PublishStatus.FAILED,
                errors=[{"message": str(e.message)}],
                channel=self.channel_code,
            )

        except Exception as e:
            self._log_publish_event("publish_error", {"job_id": job_id, "error": str(e)})
            return PublishResult(
                success=False,
                job_id=job_id,
                status=PublishStatus.FAILED,
                errors=[{"message": f"Unexpected error: {str(e)}"}],
                channel=self.channel_code,
            )

    def _submit_batch(self, payload: Dict, job_id: str) -> PublishResult:
        """Submit products to Trendyol as a batch.

        Args:
            payload: Payload with items list
            job_id: Job ID for tracking

        Returns:
            PublishResult with batch operation status
        """
        items = payload.get("items", [])
        products_total = len(items)
        errors = []

        try:
            # Trendyol batch endpoint
            endpoint = f"suppliers/{self.supplier_id}/v2/products"

            result = self._make_api_request(
                "POST",
                endpoint,
                data={"items": items},
                endpoint_type="batch",
            )

            batch_request_id = result.get("batchRequestId")

            # Track job
            self._job_tracker[job_id] = TrendyolBatchJob(
                job_id=job_id,
                batch_request_id=batch_request_id,
                operation_type="CREATE",
                status="PENDING",
                products_total=products_total,
            )

            self._log_publish_event("submit_success", {
                "job_id": job_id,
                "batch_request_id": batch_request_id,
                "products_total": products_total,
            })

            return PublishResult(
                success=True,
                job_id=job_id,
                status=PublishStatus.IN_PROGRESS,
                products_submitted=products_total,
                channel=self.channel_code,
                external_id=batch_request_id,
            )

        except RateLimitError as e:
            return PublishResult(
                success=False,
                job_id=job_id,
                status=PublishStatus.RATE_LIMITED,
                products_submitted=0,
                errors=[{"message": str(e.message), "retry_after": e.retry_after}],
                channel=self.channel_code,
            )

        except Exception as e:
            errors.append({"message": f"Batch submit failed: {str(e)}"})

            return PublishResult(
                success=False,
                job_id=job_id,
                status=PublishStatus.FAILED,
                products_submitted=products_total,
                products_failed=products_total,
                errors=errors,
                channel=self.channel_code,
            )

    # =========================================================================
    # Status Methods
    # =========================================================================

    def get_status(self, job_id: str) -> StatusResult:
        """Check the status of a publish job.

        Args:
            job_id: The job ID from publish()

        Returns:
            StatusResult with current job status and progress
        """
        # Check our internal tracker
        if job_id not in self._job_tracker:
            return StatusResult(
                job_id=job_id,
                status=PublishStatus.COMPLETED,
                progress=1.0,
                channel=self.channel_code,
            )

        job = self._job_tracker[job_id]
        batch_request_id = job.batch_request_id

        if not batch_request_id:
            return StatusResult(
                job_id=job_id,
                status=PublishStatus.FAILED,
                errors=[{"message": "No batch request ID available"}],
                channel=self.channel_code,
            )

        try:
            # Query Trendyol batch status endpoint
            endpoint = f"suppliers/{self.supplier_id}/products/batch-requests/{batch_request_id}"

            result = self._make_api_request("GET", endpoint)

            # Parse status
            batch_status = result.get("status", "").lower()
            items = result.get("items", [])

            products_processed = len(items)
            products_succeeded = sum(1 for item in items if item.get("status") == "SUCCESS")
            products_failed = sum(1 for item in items if item.get("status") == "FAILED")

            errors = []
            for item in items:
                if item.get("status") == "FAILED":
                    errors.append({
                        "barcode": item.get("barcode"),
                        "message": str(item.get("failureReasons", [])),
                    })

            # Map Trendyol status to our status
            if batch_status == "completed":
                if products_failed == 0:
                    status = PublishStatus.COMPLETED
                elif products_succeeded > 0:
                    status = PublishStatus.PARTIAL
                else:
                    status = PublishStatus.FAILED
            elif batch_status in ("processing", "in_progress"):
                status = PublishStatus.IN_PROGRESS
            elif batch_status == "failed":
                status = PublishStatus.FAILED
            else:
                status = PublishStatus.PENDING

            # Update tracker
            job.status = status.value.upper()
            job.products_processed = products_processed
            job.products_succeeded = products_succeeded
            job.products_failed = products_failed
            job.errors = errors
            if status in (PublishStatus.COMPLETED, PublishStatus.PARTIAL, PublishStatus.FAILED):
                job.completed_at = datetime.now()

            progress = 1.0 if status in (PublishStatus.COMPLETED, PublishStatus.PARTIAL, PublishStatus.FAILED) else 0.5

            return StatusResult(
                job_id=job_id,
                status=status,
                progress=progress,
                products_total=job.products_total,
                products_processed=products_processed,
                errors=errors,
                channel=self.channel_code,
                completed_at=job.completed_at,
            )

        except Exception as e:
            return StatusResult(
                job_id=job_id,
                status=PublishStatus.PENDING,
                errors=[{"message": f"Status check failed: {str(e)}"}],
                channel=self.channel_code,
            )

    # =========================================================================
    # Additional Methods
    # =========================================================================

    def test_connection(self) -> Dict:
        """Test the connection to Trendyol.

        Returns:
            Dictionary with connection status
        """
        try:
            if not self.supplier_id:
                return {
                    "success": False,
                    "message": "Supplier ID is not configured",
                }

            # Try to get supplier info
            endpoint = f"suppliers/{self.supplier_id}/addresses"
            result = self._make_api_request("GET", endpoint)

            if result is not None:
                return {
                    "success": True,
                    "message": "Connection successful",
                    "supplier_id": self.supplier_id,
                }
            else:
                return {
                    "success": False,
                    "message": "Could not retrieve supplier information",
                }

        except AuthenticationError as e:
            return {
                "success": False,
                "message": str(e.message),
            }
        except Exception as e:
            return {
                "success": False,
                "message": str(e),
            }

    def get_brands(self, name_filter: str = None, page: int = 0, size: int = 100) -> List[Dict]:
        """Retrieve brands from Trendyol.

        Args:
            name_filter: Optional filter by brand name
            page: Page number (0-indexed)
            size: Page size

        Returns:
            List of brand dictionaries
        """
        try:
            params = {"page": page, "size": size}
            if name_filter:
                params["name"] = name_filter

            result = self._make_api_request(
                "GET",
                "brands",
                params=params,
            )
            return result.get("brands", [])
        except Exception:
            return []

    def get_categories(self) -> List[Dict]:
        """Retrieve category tree from Trendyol.

        Returns:
            List of category dictionaries
        """
        try:
            result = self._make_api_request("GET", "product-categories")
            return result.get("categories", [])
        except Exception:
            return []

    def get_category_attributes(self, category_id: int) -> List[Dict]:
        """Retrieve attributes for a category.

        Args:
            category_id: Trendyol category ID

        Returns:
            List of attribute dictionaries
        """
        try:
            result = self._make_api_request(
                "GET",
                f"product-categories/{category_id}/attributes"
            )
            return result.get("categoryAttributes", [])
        except Exception:
            return []

    def update_price_and_stock(self, items: List[Dict]) -> PublishResult:
        """Update price and stock for existing products.

        Args:
            items: List of items with barcode, quantity, salePrice, listPrice

        Returns:
            PublishResult with operation status
        """
        job_id = str(uuid.uuid4())

        try:
            endpoint = f"suppliers/{self.supplier_id}/products/price-and-inventory"

            result = self._make_api_request(
                "POST",
                endpoint,
                data={"items": items},
                endpoint_type="product_create",
            )

            batch_request_id = result.get("batchRequestId")

            return PublishResult(
                success=True,
                job_id=job_id,
                status=PublishStatus.IN_PROGRESS,
                products_submitted=len(items),
                channel=self.channel_code,
                external_id=batch_request_id,
            )

        except Exception as e:
            return PublishResult(
                success=False,
                job_id=job_id,
                status=PublishStatus.FAILED,
                errors=[{"message": str(e)}],
                channel=self.channel_code,
            )


# =============================================================================
# Register Adapter
# =============================================================================

register_adapter("trendyol", TrendyolAdapter)
register_adapter("ty", TrendyolAdapter)  # Short alias
