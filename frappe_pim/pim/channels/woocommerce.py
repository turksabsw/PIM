"""
WooCommerce Channel Adapter

Provides a comprehensive adapter for WooCommerce product syndication using
the WooCommerce REST API via the woocommerce-python library.

Features:
- WooCommerce REST API v3 (wc/v3) integration
- Consumer key/secret authentication (OAuth 1.0a or Basic Auth)
- Rate limiting with configurable limits
- Comprehensive product validation against WooCommerce requirements
- Attribute mapping to WooCommerce product format
- Support for simple, variable, and grouped products
- Image/gallery management
- Category and tag assignment
- Custom attributes and variations

Note: frappe imports are deferred to function/method level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union
import json
import time
import uuid

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
# WooCommerce-Specific Constants
# =============================================================================

class WooCommerceProductStatus(str, Enum):
    """WooCommerce product status values"""
    PUBLISH = "publish"
    DRAFT = "draft"
    PENDING = "pending"
    PRIVATE = "private"


class WooCommerceProductType(str, Enum):
    """WooCommerce product type values"""
    SIMPLE = "simple"
    GROUPED = "grouped"
    EXTERNAL = "external"
    VARIABLE = "variable"


class WooCommerceStockStatus(str, Enum):
    """WooCommerce stock status values"""
    INSTOCK = "instock"
    OUTOFSTOCK = "outofstock"
    ONBACKORDER = "onbackorder"


class WooCommerceTaxStatus(str, Enum):
    """WooCommerce tax status values"""
    TAXABLE = "taxable"
    SHIPPING = "shipping"
    NONE = "none"


# WooCommerce rate limit configuration
# Default: 10 requests per second for most hosts
WOOCOMMERCE_RATE_LIMITS = {
    "default": {
        "requests_per_second": 10,
        "requests_per_minute": 600,
        "burst_limit": 25,
    },
    "shared_hosting": {
        "requests_per_second": 2,
        "requests_per_minute": 120,
        "burst_limit": 5,
    },
}

# WooCommerce API version
WOOCOMMERCE_API_VERSION = "wc/v3"

# Required fields for WooCommerce products
WOOCOMMERCE_REQUIRED_FIELDS = {
    "name",  # Product name is required
}

# Recommended fields for better listings
WOOCOMMERCE_RECOMMENDED_FIELDS = {
    "description",
    "short_description",
    "sku",
    "regular_price",
    "sale_price",
    "categories",
    "images",
    "manage_stock",
    "stock_quantity",
    "weight",
    "dimensions",
}

# Field length limits (WooCommerce is flexible, but these are recommendations)
WOOCOMMERCE_FIELD_LIMITS = {
    "name": 200,
    "sku": 100,
    "slug": 200,
    "button_text": 32,  # External product button text
}

# PIM to WooCommerce field mappings
PIM_TO_WOOCOMMERCE_FIELDS = {
    "item_code": "sku",
    "item_name": "name",
    "pim_title": "name",
    "pim_description": "description",
    "description": "description",
    "pim_short_description": "short_description",
    "short_description": "short_description",
    "standard_rate": "regular_price",
    "price": "regular_price",
    "sale_price": "sale_price",
    "barcode": "sku",  # WooCommerce uses SKU, can store barcode in custom field
    "gtin": "global_unique_id",
    "weight_per_unit": "weight",
    "net_weight": "weight",
    "item_group": "categories",
    "brand": "brands",  # Requires WooCommerce Brands extension
    "image": "images",
}


# =============================================================================
# WooCommerce-Specific Data Classes
# =============================================================================

@dataclass
class WooCommerceRateLimitState:
    """Tracks WooCommerce rate limit state"""
    requests_made: int = 0
    requests_limit: int = 600  # Per minute
    window_start: datetime = field(default_factory=datetime.now)
    window_duration: int = 60  # seconds
    retry_after: datetime = None
    last_request: datetime = None
    burst_count: int = 0
    burst_window_start: datetime = field(default_factory=datetime.now)

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

        return (self.requests_made >= self.requests_limit or
                self.burst_count >= WOOCOMMERCE_RATE_LIMITS["default"]["burst_limit"])

    def record_request(self) -> None:
        """Record that a request was made"""
        now = datetime.now()

        # Reset windows if needed
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
            # If burst limited, wait for next second
            if self.burst_count >= WOOCOMMERCE_RATE_LIMITS["default"]["burst_limit"]:
                burst_end = self.burst_window_start + timedelta(seconds=1)
                delta = burst_end - datetime.now()
                return max(0, delta.total_seconds())

            # If minute limited, wait for window reset
            window_end = self.window_start + timedelta(seconds=self.window_duration)
            delta = window_end - datetime.now()
            return max(0, delta.total_seconds())

        return 0


@dataclass
class WooCommerceJob:
    """Tracks a WooCommerce publish job"""
    job_id: str
    operation_type: str  # CREATE, UPDATE, BATCH
    status: str  # PENDING, RUNNING, COMPLETED, FAILED
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime = None
    products_total: int = 0
    products_processed: int = 0
    products_succeeded: int = 0
    products_failed: int = 0
    errors: List[Dict] = field(default_factory=list)
    external_ids: List[int] = field(default_factory=list)


# =============================================================================
# WooCommerce Adapter
# =============================================================================

class WooCommerceAdapter(ChannelAdapter):
    """
    WooCommerce channel adapter for product syndication.

    Uses the WooCommerce REST API (wc/v3) for product management with
    support for simple, variable, and grouped products.

    Features:
    - REST API v3 with OAuth 1.0a or Basic Auth
    - Batch operations for efficient bulk updates
    - Product, variation, and inventory management
    - Category, tag, and attribute support
    - Image/gallery management
    - Custom meta fields
    """

    channel_code: str = "woocommerce"
    channel_name: str = "WooCommerce"

    # Rate limiting settings
    default_requests_per_minute: int = 600
    default_requests_per_second: float = 10.0
    max_retry_attempts: int = 5
    base_backoff_seconds: float = 0.5
    max_backoff_seconds: float = 60.0

    # Batch size for bulk operations
    batch_size: int = 100

    def __init__(self, channel_doc: Any = None):
        """Initialize WooCommerce adapter.

        Args:
            channel_doc: Channel Frappe document with WooCommerce credentials
        """
        super().__init__(channel_doc)
        self._rate_limit_state: WooCommerceRateLimitState = None
        self._api_client = None
        self._store_url: str = None
        self._api_version: str = WOOCOMMERCE_API_VERSION
        self._job_tracker: Dict[str, WooCommerceJob] = {}

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def store_url(self) -> str:
        """Get the WooCommerce store URL."""
        if self._store_url:
            return self._store_url

        # Get from config or channel document
        url = self.config.get("store_url") or self.config.get("base_url", "")

        # Normalize URL
        url = url.rstrip("/")
        if url and not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        self._store_url = url
        return self._store_url

    @property
    def api_url(self) -> str:
        """Get the WooCommerce REST API base URL."""
        return f"{self.store_url}/wp-json/{self._api_version}"

    @property
    def rate_limit_state(self) -> WooCommerceRateLimitState:
        """Get current rate limit state."""
        if self._rate_limit_state is None:
            self._rate_limit_state = WooCommerceRateLimitState()
        return self._rate_limit_state

    @property
    def api_client(self):
        """Get or create WooCommerce API client."""
        if self._api_client is None:
            self._api_client = self._create_api_client()
        return self._api_client

    # =========================================================================
    # Authentication Methods
    # =========================================================================

    def _get_woocommerce_credentials(self) -> Dict:
        """Get WooCommerce-specific credentials.

        Returns:
            Dictionary with:
            - consumer_key: WooCommerce REST API consumer key
            - consumer_secret: WooCommerce REST API consumer secret
        """
        credentials = self.credentials

        return {
            "consumer_key": credentials.get("api_key") or credentials.get("consumer_key"),
            "consumer_secret": credentials.get("api_secret") or credentials.get("consumer_secret"),
        }

    def _create_api_client(self):
        """Create WooCommerce API client using woocommerce-python library.

        Returns:
            WooCommerce API client instance

        Raises:
            AuthenticationError: If credentials are missing
        """
        try:
            from woocommerce import API as WooCommerceAPI
        except ImportError:
            raise PublishError(
                "woocommerce package not installed. Install with: pip install woocommerce",
                channel=self.channel_code,
            )

        creds = self._get_woocommerce_credentials()

        if not creds.get("consumer_key") or not creds.get("consumer_secret"):
            raise AuthenticationError(
                "WooCommerce consumer key and secret are required",
                channel=self.channel_code,
            )

        if not self.store_url:
            raise AuthenticationError(
                "WooCommerce store URL is required",
                channel=self.channel_code,
            )

        # Determine if we should use basic auth (for HTTPS) or OAuth (for HTTP)
        use_basic_auth = self.store_url.startswith("https://")

        return WooCommerceAPI(
            url=self.store_url,
            consumer_key=creds["consumer_key"],
            consumer_secret=creds["consumer_secret"],
            version=self._api_version,
            timeout=self.config.get("timeout", 30),
            query_string_auth=not use_basic_auth,  # Use OAuth for HTTP
        )

    def _get_auth_headers(self) -> Dict:
        """Build authentication headers for manual API requests.

        Note: The woocommerce-python library handles auth automatically,
        but this method is provided for custom requests.

        Returns:
            Dictionary of HTTP headers
        """
        import base64

        creds = self._get_woocommerce_credentials()
        consumer_key = creds.get("consumer_key", "")
        consumer_secret = creds.get("consumer_secret", "")

        # Basic auth for HTTPS
        if self.store_url and self.store_url.startswith("https://"):
            credentials = f"{consumer_key}:{consumer_secret}"
            encoded = base64.b64encode(credentials.encode()).decode()
            return {
                "Authorization": f"Basic {encoded}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }

        # For HTTP, credentials go in query string (handled by library)
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # =========================================================================
    # Rate Limiting Methods
    # =========================================================================

    def handle_rate_limiting(self, response: Any = None) -> None:
        """Handle WooCommerce rate limiting from response.

        Parses response headers and status codes to detect rate limiting.

        Args:
            response: HTTP response object or API response

        Raises:
            RateLimitError: If rate limit exceeded and cannot proceed
        """
        if response is None:
            return

        # Check for 429 Too Many Requests
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
                "WooCommerce API rate limit exceeded",
                channel=self.channel_code,
                retry_after=retry_after,
                details={
                    "status_code": 429,
                    "retry_after": retry_after,
                },
            )

        # Check for server errors that might indicate overload
        if status_code in (502, 503, 504):
            # Treat as soft rate limit
            self.rate_limit_state.retry_after = datetime.now() + timedelta(seconds=5)

    def _wait_for_rate_limit(self) -> None:
        """Wait if rate limited.

        Raises:
            RateLimitError: If wait time exceeds maximum
        """
        wait_time = self.rate_limit_state.wait_time()

        if wait_time > 0:
            if wait_time > self.max_backoff_seconds:
                raise RateLimitError(
                    f"WooCommerce rate limit wait time ({wait_time}s) exceeds maximum",
                    channel=self.channel_code,
                    retry_after=int(wait_time),
                )
            time.sleep(wait_time)

    # =========================================================================
    # API Request Methods
    # =========================================================================

    def _make_api_request(self, method: str, endpoint: str,
                          data: Dict = None, params: Dict = None) -> Dict:
        """Make a request to the WooCommerce REST API.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint (e.g., 'products')
            data: Request body data
            params: Query parameters

        Returns:
            API response data

        Raises:
            AuthenticationError: If authentication fails
            RateLimitError: If rate limit exceeded
            PublishError: If request fails
        """
        self._wait_for_rate_limit()

        last_error = None

        for attempt in range(self.max_retry_attempts):
            try:
                self.rate_limit_state.record_request()

                # Use the woocommerce-python client
                if method.upper() == "GET":
                    response = self.api_client.get(endpoint, params=params)
                elif method.upper() == "POST":
                    response = self.api_client.post(endpoint, data or {})
                elif method.upper() == "PUT":
                    response = self.api_client.put(endpoint, data or {})
                elif method.upper() == "DELETE":
                    response = self.api_client.delete(endpoint, params=params)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                # Handle rate limiting from response
                self.handle_rate_limiting(response)

                # Check for auth errors
                if response.status_code in (401, 403):
                    raise AuthenticationError(
                        f"WooCommerce authentication failed: HTTP {response.status_code}",
                        channel=self.channel_code,
                    )

                # Check for not found
                if response.status_code == 404:
                    raise PublishError(
                        f"WooCommerce resource not found: {endpoint}",
                        channel=self.channel_code,
                        details={"endpoint": endpoint},
                    )

                # Check for success
                if response.status_code in (200, 201):
                    return response.json()

                # Handle other errors
                error_message = "Unknown error"
                try:
                    error_data = response.json()
                    error_message = error_data.get("message", str(error_data))
                except Exception:
                    error_message = response.text or f"HTTP {response.status_code}"

                raise PublishError(
                    f"WooCommerce API error: {error_message}",
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
            f"WooCommerce API request failed after {self.max_retry_attempts} attempts: {last_error}",
            channel=self.channel_code,
        )

    # =========================================================================
    # Validation Methods
    # =========================================================================

    def validate_product(self, product: Dict) -> ValidationResult:
        """Validate a product against WooCommerce's requirements.

        Checks required fields, field length limits, price validation,
        and other WooCommerce-specific requirements.

        Args:
            product: Product data dictionary in PIM format

        Returns:
            ValidationResult with validation status and any errors/warnings
        """
        errors = []
        warnings = []
        product_id = product.get("item_code", product.get("sku", "unknown"))

        # Check required fields
        for field_name in WOOCOMMERCE_REQUIRED_FIELDS:
            # Check both PIM and WooCommerce field names
            pim_field = None
            for pim_name, wc_name in PIM_TO_WOOCOMMERCE_FIELDS.items():
                if wc_name == field_name or field_name == pim_name:
                    pim_field = pim_name
                    break

            value = product.get(field_name) or product.get(pim_field)

            if not value:
                errors.append({
                    "field": field_name,
                    "message": f"Required field '{field_name}' is missing",
                    "rule": "required",
                })

        # Check field length limits
        for field_name, max_length in WOOCOMMERCE_FIELD_LIMITS.items():
            value = product.get(field_name) or ""
            if isinstance(value, str) and len(value) > max_length:
                warnings.append({
                    "field": field_name,
                    "message": f"Field '{field_name}' exceeds recommended length of {max_length} characters",
                    "value": f"{len(value)} characters",
                    "rule": "max_length",
                })

        # Validate SKU if provided
        sku = product.get("item_code") or product.get("sku")
        if sku:
            if len(str(sku)) > WOOCOMMERCE_FIELD_LIMITS.get("sku", 100):
                errors.append({
                    "field": "sku",
                    "message": f"SKU exceeds maximum length of {WOOCOMMERCE_FIELD_LIMITS['sku']} characters",
                    "value": str(sku),
                    "rule": "max_length",
                })
            # Check for special characters that might cause issues
            if any(c in str(sku) for c in ['<', '>', '"', '&']):
                warnings.append({
                    "field": "sku",
                    "message": "SKU contains special characters that may cause issues",
                    "value": str(sku),
                    "rule": "special_chars",
                })

        # Validate regular price if provided
        regular_price = product.get("standard_rate") or product.get("regular_price") or product.get("price")
        if regular_price is not None:
            try:
                price_val = float(regular_price)
                if price_val < 0:
                    errors.append({
                        "field": "regular_price",
                        "message": "Regular price cannot be negative",
                        "value": str(regular_price),
                        "rule": "non_negative",
                    })
            except (ValueError, TypeError):
                errors.append({
                    "field": "regular_price",
                    "message": "Regular price must be a valid number",
                    "value": str(regular_price),
                    "rule": "numeric",
                })

        # Validate sale price if provided
        sale_price = product.get("sale_price")
        if sale_price is not None and regular_price is not None:
            try:
                sale_val = float(sale_price)
                regular_val = float(regular_price)
                if sale_val >= regular_val:
                    warnings.append({
                        "field": "sale_price",
                        "message": "Sale price should be less than regular price",
                        "value": str(sale_price),
                        "rule": "sale_price_logic",
                    })
                if sale_val < 0:
                    errors.append({
                        "field": "sale_price",
                        "message": "Sale price cannot be negative",
                        "value": str(sale_price),
                        "rule": "non_negative",
                    })
            except (ValueError, TypeError):
                pass

        # Validate stock quantity if manage_stock is true
        manage_stock = product.get("manage_stock", False)
        stock_quantity = product.get("stock_quantity") or product.get("stock_qty")
        if manage_stock and stock_quantity is not None:
            try:
                stock_val = int(stock_quantity)
                if stock_val < 0:
                    warnings.append({
                        "field": "stock_quantity",
                        "message": "Stock quantity is negative (backorder?)",
                        "value": str(stock_quantity),
                        "rule": "negative_stock",
                    })
            except (ValueError, TypeError):
                errors.append({
                    "field": "stock_quantity",
                    "message": "Stock quantity must be an integer",
                    "value": str(stock_quantity),
                    "rule": "integer",
                })

        # Validate weight if provided
        weight = product.get("weight_per_unit") or product.get("weight") or product.get("net_weight")
        if weight is not None:
            try:
                weight_val = float(weight)
                if weight_val < 0:
                    errors.append({
                        "field": "weight",
                        "message": "Weight cannot be negative",
                        "value": str(weight),
                        "rule": "non_negative",
                    })
            except (ValueError, TypeError):
                errors.append({
                    "field": "weight",
                    "message": "Weight must be a valid number",
                    "value": str(weight),
                    "rule": "numeric",
                })

        # Validate dimensions if provided
        for dim in ["length", "width", "height"]:
            dim_value = product.get(dim)
            if dim_value is not None:
                try:
                    dim_val = float(dim_value)
                    if dim_val < 0:
                        errors.append({
                            "field": dim,
                            "message": f"{dim.capitalize()} cannot be negative",
                            "value": str(dim_value),
                            "rule": "non_negative",
                        })
                except (ValueError, TypeError):
                    errors.append({
                        "field": dim,
                        "message": f"{dim.capitalize()} must be a valid number",
                        "value": str(dim_value),
                        "rule": "numeric",
                    })

        # Check for recommended fields
        for field_name in WOOCOMMERCE_RECOMMENDED_FIELDS:
            if field_name not in WOOCOMMERCE_REQUIRED_FIELDS:
                pim_field = None
                for pim_name, wc_name in PIM_TO_WOOCOMMERCE_FIELDS.items():
                    if wc_name == field_name:
                        pim_field = pim_name
                        break

                value = product.get(field_name)
                if pim_field:
                    value = value or product.get(pim_field)

                if not value:
                    warnings.append({
                        "field": field_name,
                        "message": f"Recommended field '{field_name}' not provided",
                        "rule": "recommended",
                    })

        # Validate images if provided
        images = product.get("images") or product.get("image")
        if images:
            image_warnings = self._validate_images(images)
            warnings.extend(image_warnings)

        return ValidationResult(
            is_valid=len(errors) == 0,
            product=product_id,
            errors=errors,
            warnings=warnings,
            channel=self.channel_code,
        )

    def _validate_images(self, images: Any) -> List[Dict]:
        """Validate product images.

        Args:
            images: Image data (URL, list of URLs, or list of dicts)

        Returns:
            List of warning dicts for image issues
        """
        warnings = []

        if isinstance(images, str):
            images = [images]

        if isinstance(images, list):
            # WooCommerce doesn't have a strict image limit, but many images can slow things down
            if len(images) > 50:
                warnings.append({
                    "field": "images",
                    "message": "Large number of images may impact performance",
                    "value": str(len(images)),
                    "rule": "image_count",
                })

            for i, img in enumerate(images[:10]):  # Check first 10
                img_url = img if isinstance(img, str) else img.get("src", "")
                if img_url and not img_url.startswith(("http://", "https://")):
                    warnings.append({
                        "field": "images",
                        "message": f"Image {i+1} URL may not be accessible",
                        "value": img_url[:100],
                        "rule": "image_url",
                    })

        return warnings

    # =========================================================================
    # Mapping Methods
    # =========================================================================

    def map_attributes(self, product: Dict) -> MappingResult:
        """Map PIM product attributes to WooCommerce format.

        Converts internal field names to WooCommerce's expected REST API
        format including proper nested structures for variations.

        Args:
            product: Product data dictionary in PIM format

        Returns:
            MappingResult with mapped data and unmapped fields
        """
        product_id = product.get("item_code", product.get("sku", "unknown"))
        mapped_data = {}
        unmapped_fields = []

        # Map basic product fields
        # Name/Title
        name = product.get("pim_title") or product.get("item_name") or product.get("name")
        if name:
            mapped_data["name"] = str(name)

        # Slug (URL handle)
        slug = product.get("slug") or product.get("handle")
        if slug:
            mapped_data["slug"] = str(slug).lower().replace(" ", "-")

        # SKU
        sku = product.get("item_code") or product.get("sku")
        if sku:
            mapped_data["sku"] = str(sku)

        # Description
        description = product.get("pim_description") or product.get("description")
        if description:
            mapped_data["description"] = str(description)

        # Short description
        short_desc = (product.get("pim_short_description") or
                     product.get("short_description") or
                     product.get("web_long_description"))
        if short_desc:
            mapped_data["short_description"] = str(short_desc)

        # Type
        product_type = product.get("product_type", "simple")
        if isinstance(product_type, str):
            type_mapping = {
                "simple": WooCommerceProductType.SIMPLE.value,
                "variable": WooCommerceProductType.VARIABLE.value,
                "grouped": WooCommerceProductType.GROUPED.value,
                "external": WooCommerceProductType.EXTERNAL.value,
            }
            mapped_data["type"] = type_mapping.get(product_type.lower(), WooCommerceProductType.SIMPLE.value)
        else:
            mapped_data["type"] = WooCommerceProductType.SIMPLE.value

        # Status
        status = product.get("status") or product.get("custom_pim_status")
        if status:
            status_upper = str(status).upper()
            if status_upper in ("PUBLISH", "PUBLISHED", "ACTIVE", "ENABLED"):
                mapped_data["status"] = WooCommerceProductStatus.PUBLISH.value
            elif status_upper in ("DRAFT", "INACTIVE"):
                mapped_data["status"] = WooCommerceProductStatus.DRAFT.value
            elif status_upper == "PENDING":
                mapped_data["status"] = WooCommerceProductStatus.PENDING.value
            elif status_upper == "PRIVATE":
                mapped_data["status"] = WooCommerceProductStatus.PRIVATE.value
            else:
                mapped_data["status"] = WooCommerceProductStatus.PUBLISH.value
        else:
            mapped_data["status"] = WooCommerceProductStatus.PUBLISH.value

        # Pricing
        regular_price = product.get("standard_rate") or product.get("regular_price") or product.get("price")
        if regular_price is not None:
            mapped_data["regular_price"] = str(float(regular_price))

        sale_price = product.get("sale_price")
        if sale_price is not None:
            mapped_data["sale_price"] = str(float(sale_price))

        # Sale dates
        sale_from = product.get("date_on_sale_from") or product.get("sale_start_date")
        if sale_from:
            mapped_data["date_on_sale_from"] = str(sale_from)

        sale_to = product.get("date_on_sale_to") or product.get("sale_end_date")
        if sale_to:
            mapped_data["date_on_sale_to"] = str(sale_to)

        # Inventory
        manage_stock = product.get("manage_stock", True)
        mapped_data["manage_stock"] = bool(manage_stock)

        if manage_stock:
            stock_qty = product.get("stock_quantity") or product.get("stock_qty") or product.get("actual_qty")
            if stock_qty is not None:
                mapped_data["stock_quantity"] = int(stock_qty)

            stock_status = product.get("stock_status")
            if stock_status:
                status_lower = str(stock_status).lower()
                if status_lower in ("instock", "in_stock", "in stock"):
                    mapped_data["stock_status"] = WooCommerceStockStatus.INSTOCK.value
                elif status_lower in ("outofstock", "out_of_stock", "out of stock"):
                    mapped_data["stock_status"] = WooCommerceStockStatus.OUTOFSTOCK.value
                elif status_lower in ("onbackorder", "backorder"):
                    mapped_data["stock_status"] = WooCommerceStockStatus.ONBACKORDER.value
            else:
                # Auto-determine from quantity
                if stock_qty is not None and int(stock_qty) > 0:
                    mapped_data["stock_status"] = WooCommerceStockStatus.INSTOCK.value
                elif stock_qty is not None:
                    mapped_data["stock_status"] = WooCommerceStockStatus.OUTOFSTOCK.value

        backorders = product.get("backorders", "no")
        if backorders:
            backorders_lower = str(backorders).lower()
            if backorders_lower in ("yes", "true", "1", "allow"):
                mapped_data["backorders"] = "yes"
            elif backorders_lower in ("notify", "notify_customer"):
                mapped_data["backorders"] = "notify"
            else:
                mapped_data["backorders"] = "no"

        # Weight and dimensions
        weight = product.get("weight_per_unit") or product.get("weight") or product.get("net_weight")
        if weight is not None:
            mapped_data["weight"] = str(float(weight))

        dimensions = {}
        length = product.get("length")
        if length is not None:
            dimensions["length"] = str(float(length))
        width = product.get("width")
        if width is not None:
            dimensions["width"] = str(float(width))
        height = product.get("height")
        if height is not None:
            dimensions["height"] = str(float(height))
        if dimensions:
            mapped_data["dimensions"] = dimensions

        # Tax
        taxable = product.get("taxable", True)
        if taxable:
            mapped_data["tax_status"] = WooCommerceTaxStatus.TAXABLE.value
        else:
            mapped_data["tax_status"] = WooCommerceTaxStatus.NONE.value

        tax_class = product.get("tax_class", "")
        if tax_class:
            mapped_data["tax_class"] = str(tax_class)

        # Shipping
        shipping_class = product.get("shipping_class")
        if shipping_class:
            mapped_data["shipping_class"] = str(shipping_class)

        virtual = product.get("virtual", False)
        mapped_data["virtual"] = bool(virtual)

        downloadable = product.get("downloadable", False)
        mapped_data["downloadable"] = bool(downloadable)

        # Categories
        categories = self._map_categories(product)
        if categories:
            mapped_data["categories"] = categories

        # Tags
        tags = self._map_tags(product)
        if tags:
            mapped_data["tags"] = tags

        # Images
        images = self._map_images(product)
        if images:
            mapped_data["images"] = images

        # Attributes
        attributes = self._map_attributes(product)
        if attributes:
            mapped_data["attributes"] = attributes

        # Meta data for custom fields
        meta_data = self._map_meta_data(product)
        if meta_data:
            mapped_data["meta_data"] = meta_data

        # WooCommerce product ID for updates
        if "woocommerce_id" in product:
            mapped_data["id"] = int(product["woocommerce_id"])
        elif "external_id" in product:
            mapped_data["id"] = int(product["external_id"])

        # Track unmapped fields
        mapped_pim_fields = set(PIM_TO_WOOCOMMERCE_FIELDS.keys())
        mapped_pim_fields.update({
            "name", "slug", "handle", "sku", "description", "short_description",
            "status", "custom_pim_status", "regular_price", "price", "standard_rate",
            "sale_price", "date_on_sale_from", "date_on_sale_to",
            "sale_start_date", "sale_end_date", "manage_stock",
            "stock_quantity", "stock_qty", "actual_qty", "stock_status",
            "backorders", "weight", "weight_per_unit", "net_weight",
            "length", "width", "height", "taxable", "tax_class", "tax_status",
            "shipping_class", "virtual", "downloadable", "categories",
            "item_group", "tags", "images", "image", "attributes",
            "woocommerce_id", "external_id", "product_type",
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

    def _map_categories(self, product: Dict) -> List[Dict]:
        """Map product categories to WooCommerce format.

        Args:
            product: Product data dictionary

        Returns:
            List of category dictionaries with id or name
        """
        categories = []

        # Get categories from product
        cat_data = product.get("categories") or product.get("item_group")

        if cat_data:
            if isinstance(cat_data, str):
                # Comma-separated category names/IDs
                for cat in cat_data.split(","):
                    cat = cat.strip()
                    if cat:
                        # Try to use as ID if numeric
                        if cat.isdigit():
                            categories.append({"id": int(cat)})
                        else:
                            categories.append({"name": cat})
            elif isinstance(cat_data, list):
                for cat in cat_data:
                    if isinstance(cat, dict):
                        categories.append(cat)
                    elif isinstance(cat, int):
                        categories.append({"id": cat})
                    elif isinstance(cat, str):
                        if cat.isdigit():
                            categories.append({"id": int(cat)})
                        else:
                            categories.append({"name": cat})
            elif isinstance(cat_data, int):
                categories.append({"id": cat_data})

        return categories

    def _map_tags(self, product: Dict) -> List[Dict]:
        """Map product tags to WooCommerce format.

        Args:
            product: Product data dictionary

        Returns:
            List of tag dictionaries with id or name
        """
        tags = []

        tag_data = product.get("tags")

        if tag_data:
            if isinstance(tag_data, str):
                for tag in tag_data.split(","):
                    tag = tag.strip()
                    if tag:
                        if tag.isdigit():
                            tags.append({"id": int(tag)})
                        else:
                            tags.append({"name": tag})
            elif isinstance(tag_data, list):
                for tag in tag_data:
                    if isinstance(tag, dict):
                        tags.append(tag)
                    elif isinstance(tag, int):
                        tags.append({"id": tag})
                    elif isinstance(tag, str):
                        if tag.isdigit():
                            tags.append({"id": int(tag)})
                        else:
                            tags.append({"name": tag})

        return tags

    def _map_images(self, product: Dict) -> List[Dict]:
        """Map images to WooCommerce format.

        Args:
            product: Product data dictionary

        Returns:
            List of image dictionaries
        """
        images = []

        image_data = product.get("images") or product.get("image")

        if image_data:
            if isinstance(image_data, str):
                # Single image URL
                if image_data.startswith(("http://", "https://")):
                    images.append({"src": image_data})
            elif isinstance(image_data, list):
                for i, img in enumerate(image_data):
                    if isinstance(img, str):
                        if img.startswith(("http://", "https://")):
                            images.append({"src": img})
                    elif isinstance(img, dict):
                        image_entry = {}
                        # Map common image properties
                        if "src" in img:
                            image_entry["src"] = img["src"]
                        elif "url" in img:
                            image_entry["src"] = img["url"]
                        if "id" in img:
                            image_entry["id"] = img["id"]
                        if "alt" in img:
                            image_entry["alt"] = img["alt"]
                        elif "alt_text" in img:
                            image_entry["alt"] = img["alt_text"]
                        if "name" in img:
                            image_entry["name"] = img["name"]
                        if image_entry:
                            images.append(image_entry)

        return images

    def _map_attributes(self, product: Dict) -> List[Dict]:
        """Map product attributes to WooCommerce format.

        Args:
            product: Product data dictionary

        Returns:
            List of attribute dictionaries
        """
        attributes = []

        attr_data = product.get("attributes")

        if attr_data and isinstance(attr_data, list):
            for attr in attr_data:
                if isinstance(attr, dict):
                    wc_attr = {
                        "name": attr.get("name", ""),
                        "visible": attr.get("visible", True),
                        "variation": attr.get("variation", False),
                    }

                    # Handle attribute ID for global attributes
                    if "id" in attr:
                        wc_attr["id"] = int(attr["id"])

                    # Handle options/values
                    options = attr.get("options") or attr.get("values")
                    if options:
                        if isinstance(options, str):
                            wc_attr["options"] = [o.strip() for o in options.split(",")]
                        elif isinstance(options, list):
                            wc_attr["options"] = [str(o) for o in options]

                    if wc_attr.get("name") or wc_attr.get("id"):
                        attributes.append(wc_attr)

        return attributes

    def _map_meta_data(self, product: Dict) -> List[Dict]:
        """Map custom fields to WooCommerce meta data.

        Args:
            product: Product data dictionary

        Returns:
            List of meta data dictionaries
        """
        meta_data = []

        # Map GTIN/barcode to meta
        gtin = product.get("gtin") or product.get("barcode")
        if gtin:
            meta_data.append({
                "key": "_global_unique_id",
                "value": str(gtin),
            })

        # Map brand to meta (if not using WooCommerce Brands plugin)
        brand = product.get("brand")
        if brand:
            meta_data.append({
                "key": "_brand",
                "value": str(brand),
            })

        # Map PIM-specific fields
        pim_fields = {
            "custom_pim_completeness": "_pim_completeness",
            "custom_pim_data_quality_score": "_pim_quality_score",
            "custom_pim_source_system": "_pim_source",
        }

        for pim_field, meta_key in pim_fields.items():
            if pim_field in product and product[pim_field] is not None:
                meta_data.append({
                    "key": meta_key,
                    "value": str(product[pim_field]),
                })

        # Include any existing meta_data from product
        existing_meta = product.get("meta_data")
        if existing_meta and isinstance(existing_meta, list):
            meta_data.extend(existing_meta)

        return meta_data

    # =========================================================================
    # Payload Generation
    # =========================================================================

    def generate_payload(self, products: List[Dict]) -> Dict:
        """Generate WooCommerce REST API payloads for products.

        Creates product structures compatible with WooCommerce's
        products endpoint for create and update operations.

        Args:
            products: List of mapped product data dictionaries

        Returns:
            Dictionary with products ready for REST API calls
        """
        payload = {
            "products": products,
            "batch": {
                "create": [],
                "update": [],
            },
            "_metadata": {
                "batch_id": str(uuid.uuid4()),
                "created_at": datetime.now().isoformat(),
                "product_count": len(products),
            },
        }

        # Separate products into create and update based on presence of ID
        for product in products:
            if product.get("id"):
                payload["batch"]["update"].append(product)
            else:
                payload["batch"]["create"].append(product)

        return payload

    # =========================================================================
    # Publishing Methods
    # =========================================================================

    def publish(self, products: List[Dict]) -> PublishResult:
        """Publish products to WooCommerce.

        Handles the complete publishing workflow including validation,
        mapping, and REST API submission with batch support.

        Args:
            products: List of product data dictionaries in PIM format

        Returns:
            PublishResult with job status and any errors
        """
        import frappe

        job_id = str(uuid.uuid4())
        errors = []
        products_submitted = 0
        products_succeeded = 0
        products_failed = 0
        external_ids = []

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

            # Map products to WooCommerce format
            mapped_products = []
            for product in products:
                mapping_result = self.map_attributes(product)
                mapped_products.append(mapping_result.mapped_data)

            # Generate payload
            payload = self.generate_payload(mapped_products)

            # Use batch API if multiple products
            if len(mapped_products) > 1:
                result = self._batch_publish(payload, job_id)
                return result

            # Single product publish
            for product_data in mapped_products:
                try:
                    result = self._submit_product(product_data)

                    if result.get("success"):
                        products_succeeded += 1
                        if result.get("product_id"):
                            external_ids.append(str(result["product_id"]))
                    else:
                        products_failed += 1
                        errors.append(result.get("error", {"message": "Unknown error"}))

                    products_submitted += 1

                except RateLimitError as e:
                    self._log_publish_event("rate_limited", {
                        "job_id": job_id,
                        "products_submitted": products_submitted,
                        "error": str(e),
                    })

                    return PublishResult(
                        success=False,
                        job_id=job_id,
                        status=PublishStatus.RATE_LIMITED,
                        products_submitted=products_submitted,
                        products_succeeded=products_succeeded,
                        products_failed=products_failed,
                        errors=errors + [{"message": str(e.message), "retry_after": e.retry_after}],
                        channel=self.channel_code,
                    )

                except Exception as e:
                    products_failed += 1
                    products_submitted += 1
                    errors.append({"message": str(e)})

            # Determine final status
            if products_failed == 0:
                status = PublishStatus.COMPLETED
                success = True
            elif products_succeeded > 0:
                status = PublishStatus.PARTIAL
                success = True
            else:
                status = PublishStatus.FAILED
                success = False

            self._log_publish_event("submit_complete", {
                "job_id": job_id,
                "products_submitted": products_submitted,
                "products_succeeded": products_succeeded,
                "products_failed": products_failed,
            })

            return PublishResult(
                success=success,
                job_id=job_id,
                status=status,
                products_submitted=products_submitted,
                products_succeeded=products_succeeded,
                products_failed=products_failed,
                errors=errors,
                channel=self.channel_code,
                external_id=",".join(external_ids) if external_ids else None,
            )

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

    def _submit_product(self, product_data: Dict) -> Dict:
        """Submit a single product to WooCommerce.

        Args:
            product_data: Product data in WooCommerce format

        Returns:
            Dict with success status and product_id or error
        """
        is_update = "id" in product_data

        try:
            if is_update:
                product_id = product_data.pop("id")
                result = self._make_api_request(
                    "PUT",
                    f"products/{product_id}",
                    data=product_data,
                )
            else:
                result = self._make_api_request(
                    "POST",
                    "products",
                    data=product_data,
                )

            return {
                "success": True,
                "product_id": result.get("id"),
                "permalink": result.get("permalink"),
                "sku": result.get("sku"),
            }

        except PublishError as e:
            return {
                "success": False,
                "error": {
                    "message": str(e.message),
                    "details": e.details,
                },
            }

    def _batch_publish(self, payload: Dict, job_id: str) -> PublishResult:
        """Publish products using WooCommerce batch API.

        Args:
            payload: Payload with batch create/update lists
            job_id: Job ID for tracking

        Returns:
            PublishResult with batch operation status
        """
        errors = []
        products_succeeded = 0
        products_failed = 0
        external_ids = []

        batch_data = payload.get("batch", {})
        create_products = batch_data.get("create", [])
        update_products = batch_data.get("update", [])

        # Process in chunks of batch_size
        all_products = []
        for product in create_products:
            all_products.append(("create", product))
        for product in update_products:
            all_products.append(("update", product))

        # Submit batch requests
        for i in range(0, len(all_products), self.batch_size):
            chunk = all_products[i:i + self.batch_size]

            batch_request = {"create": [], "update": []}
            for op_type, product in chunk:
                if op_type == "create":
                    batch_request["create"].append(product)
                else:
                    batch_request["update"].append(product)

            try:
                result = self._make_api_request(
                    "POST",
                    "products/batch",
                    data=batch_request,
                )

                # Process created products
                for created in result.get("create", []):
                    if created.get("id"):
                        products_succeeded += 1
                        external_ids.append(str(created["id"]))
                    elif created.get("error"):
                        products_failed += 1
                        errors.append({
                            "message": created["error"].get("message", "Create failed"),
                            "code": created["error"].get("code"),
                        })

                # Process updated products
                for updated in result.get("update", []):
                    if updated.get("id") and not updated.get("error"):
                        products_succeeded += 1
                        external_ids.append(str(updated["id"]))
                    elif updated.get("error"):
                        products_failed += 1
                        errors.append({
                            "message": updated["error"].get("message", "Update failed"),
                            "code": updated["error"].get("code"),
                        })

            except RateLimitError as e:
                return PublishResult(
                    success=False,
                    job_id=job_id,
                    status=PublishStatus.RATE_LIMITED,
                    products_submitted=len(all_products),
                    products_succeeded=products_succeeded,
                    products_failed=products_failed + (len(chunk) - products_succeeded),
                    errors=errors + [{"message": str(e.message), "retry_after": e.retry_after}],
                    channel=self.channel_code,
                )

            except Exception as e:
                products_failed += len(chunk)
                errors.append({"message": f"Batch request failed: {str(e)}"})

        # Determine final status
        products_submitted = len(all_products)

        if products_failed == 0:
            status = PublishStatus.COMPLETED
            success = True
        elif products_succeeded > 0:
            status = PublishStatus.PARTIAL
            success = True
        else:
            status = PublishStatus.FAILED
            success = False

        # Track job
        self._job_tracker[job_id] = WooCommerceJob(
            job_id=job_id,
            operation_type="BATCH",
            status="COMPLETED" if success else "FAILED",
            products_total=products_submitted,
            products_processed=products_submitted,
            products_succeeded=products_succeeded,
            products_failed=products_failed,
            errors=errors,
            external_ids=[int(eid) for eid in external_ids],
            completed_at=datetime.now(),
        )

        return PublishResult(
            success=success,
            job_id=job_id,
            status=status,
            products_submitted=products_submitted,
            products_succeeded=products_succeeded,
            products_failed=products_failed,
            errors=errors,
            channel=self.channel_code,
            external_id=",".join(external_ids) if external_ids else None,
        )

    # =========================================================================
    # Status Methods
    # =========================================================================

    def get_status(self, job_id: str) -> StatusResult:
        """Check the status of a publish job.

        For WooCommerce, operations are synchronous, so this primarily
        returns the tracked status from our internal job tracker.

        Args:
            job_id: The job ID from publish()

        Returns:
            StatusResult with current job status and progress
        """
        # Check our internal tracker
        if job_id in self._job_tracker:
            job = self._job_tracker[job_id]

            status_mapping = {
                "PENDING": PublishStatus.PENDING,
                "RUNNING": PublishStatus.IN_PROGRESS,
                "COMPLETED": PublishStatus.COMPLETED,
                "FAILED": PublishStatus.FAILED,
            }

            progress = 1.0 if job.status == "COMPLETED" else 0.0
            if job.products_total > 0:
                progress = job.products_processed / job.products_total

            return StatusResult(
                job_id=job_id,
                status=status_mapping.get(job.status, PublishStatus.COMPLETED),
                progress=progress,
                products_total=job.products_total,
                products_processed=job.products_processed,
                errors=job.errors,
                channel=self.channel_code,
                completed_at=job.completed_at,
            )

        # For synchronous operations without tracking, return completed
        return StatusResult(
            job_id=job_id,
            status=PublishStatus.COMPLETED,
            progress=1.0,
            channel=self.channel_code,
        )

    # =========================================================================
    # Additional Methods
    # =========================================================================

    def test_connection(self) -> Dict:
        """Test the connection to WooCommerce.

        Returns:
            Dictionary with connection status and store info
        """
        import frappe

        try:
            if not self.store_url:
                return {
                    "success": False,
                    "message": "Store URL is not configured",
                }

            # Try to get system status
            result = self._make_api_request("GET", "system_status")

            if result:
                return {
                    "success": True,
                    "message": "Connection successful",
                    "woocommerce_version": result.get("environment", {}).get("version"),
                    "wordpress_version": result.get("environment", {}).get("wp_version"),
                    "store_url": self.store_url,
                }
            else:
                return {
                    "success": False,
                    "message": "Could not retrieve store information",
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

    def get_product_by_sku(self, sku: str) -> Optional[Dict]:
        """Retrieve a product from WooCommerce by SKU.

        Args:
            sku: The product SKU to search for

        Returns:
            Product data dict if found, None otherwise
        """
        try:
            result = self._make_api_request(
                "GET",
                "products",
                params={"sku": sku},
            )

            if result and isinstance(result, list) and len(result) > 0:
                return result[0]
            return None

        except Exception:
            return None

    def get_product_by_id(self, product_id: int) -> Optional[Dict]:
        """Retrieve a product from WooCommerce by ID.

        Args:
            product_id: The WooCommerce product ID

        Returns:
            Product data dict if found, None otherwise
        """
        try:
            result = self._make_api_request(
                "GET",
                f"products/{product_id}",
            )
            return result
        except Exception:
            return None

    def delete_product(self, product_id: int, force: bool = False) -> bool:
        """Delete a product from WooCommerce.

        Args:
            product_id: The WooCommerce product ID
            force: If True, permanently delete; if False, move to trash

        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            params = {"force": "true"} if force else None
            self._make_api_request(
                "DELETE",
                f"products/{product_id}",
                params=params,
            )
            return True
        except Exception:
            return False

    def get_categories(self, per_page: int = 100) -> List[Dict]:
        """Retrieve product categories from WooCommerce.

        Args:
            per_page: Number of categories to retrieve

        Returns:
            List of category dictionaries
        """
        try:
            result = self._make_api_request(
                "GET",
                "products/categories",
                params={"per_page": per_page},
            )
            return result if isinstance(result, list) else []
        except Exception:
            return []

    def get_tags(self, per_page: int = 100) -> List[Dict]:
        """Retrieve product tags from WooCommerce.

        Args:
            per_page: Number of tags to retrieve

        Returns:
            List of tag dictionaries
        """
        try:
            result = self._make_api_request(
                "GET",
                "products/tags",
                params={"per_page": per_page},
            )
            return result if isinstance(result, list) else []
        except Exception:
            return []


# =============================================================================
# Register Adapter
# =============================================================================

register_adapter("woocommerce", WooCommerceAdapter)
register_adapter("woo", WooCommerceAdapter)  # Short alias
