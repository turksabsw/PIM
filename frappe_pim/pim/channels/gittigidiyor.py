"""
GittiGidiyor Channel Adapter

Provides a comprehensive adapter for GittiGidiyor marketplace product syndication
using the GittiGidiyor Partner API (REST).

Features:
- GittiGidiyor REST API integration
- API Key/Secret authentication with HMAC signature
- Rate limiting with configurable limits
- Comprehensive product validation against GittiGidiyor requirements
- Attribute mapping to GittiGidiyor product format
- Support for single and batch product operations
- Category and catalog management
- Stock and price synchronization
- Auction and fixed-price listing support

Note: GittiGidiyor was acquired by eBay and uses similar patterns.
frappe imports are deferred to function/method level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional
import json
import time
import uuid
import hashlib
import hmac
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
# GittiGidiyor-Specific Constants
# =============================================================================

class GittiGidiyorListingType(str, Enum):
    """GittiGidiyor listing type values"""
    FIXED_PRICE = "fixedPrice"
    AUCTION = "auction"
    STORE_FIXED_PRICE = "storeFixedPrice"


class GittiGidiyorProductStatus(str, Enum):
    """GittiGidiyor product status values"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING = "pending"
    SUSPENDED = "suspended"
    ENDED = "ended"


class GittiGidiyorCurrency(str, Enum):
    """GittiGidiyor currency values"""
    TRY = "TRY"
    USD = "USD"
    EUR = "EUR"


# GittiGidiyor API endpoints
GITTIGIDIYOR_API_BASE_URL = "https://dev.gittigidiyor.com:8443/listingapi/ws"
GITTIGIDIYOR_PRODUCTION_URL = "https://api.gittigidiyor.com/listingapi/ws"

# GittiGidiyor rate limit configuration
GITTIGIDIYOR_RATE_LIMITS = {
    "default": {
        "requests_per_minute": 40,
        "requests_per_second": 1,
        "burst_limit": 5,
    },
    "product_create": {
        "requests_per_minute": 20,
        "requests_per_second": 0.5,
        "burst_limit": 3,
    },
    "search": {
        "requests_per_minute": 60,
        "requests_per_second": 2,
        "burst_limit": 10,
    },
}

# Required fields for GittiGidiyor products
GITTIGIDIYOR_REQUIRED_FIELDS = {
    "title",
    "description",
    "categoryCode",
    "startPrice",
    "buyNowPrice",
    "listingDays",
    "format",
    "stockQuantity",
}

# Recommended fields
GITTIGIDIYOR_RECOMMENDED_FIELDS = {
    "subtitle",
    "productCode",
    "cargoDetail",
    "itemSpecifics",
    "photos",
    "shippingDetail",
}

# Field length limits
GITTIGIDIYOR_FIELD_LIMITS = {
    "title": 120,
    "subtitle": 55,
    "description": 500000,
    "productCode": 50,
}

# PIM to GittiGidiyor field mappings
PIM_TO_GITTIGIDIYOR_FIELDS = {
    "item_code": "productCode",
    "item_name": "title",
    "pim_title": "title",
    "pim_description": "description",
    "description": "description",
    "pim_short_description": "subtitle",
    "barcode": "barcode",
    "gtin": "barcode",
    "standard_rate": "buyNowPrice",
    "price": "buyNowPrice",
    "stock_qty": "stockQuantity",
    "actual_qty": "stockQuantity",
    "brand": "brand",
    "item_group": "categoryCode",
    "image": "photos",
}


# =============================================================================
# GittiGidiyor-Specific Data Classes
# =============================================================================

@dataclass
class GittiGidiyorRateLimitState:
    """Tracks GittiGidiyor rate limit state"""
    requests_made: int = 0
    requests_limit: int = 40
    window_start: datetime = field(default_factory=datetime.now)
    window_duration: int = 60
    retry_after: datetime = None
    last_request: datetime = None
    burst_count: int = 0
    burst_window_start: datetime = field(default_factory=datetime.now)
    endpoint_type: str = "default"

    def is_limited(self) -> bool:
        """Check if currently rate limited"""
        if self.retry_after and datetime.now() < self.retry_after:
            return True

        if datetime.now() > self.window_start + timedelta(seconds=self.window_duration):
            self.requests_made = 0
            self.window_start = datetime.now()
            return False

        if datetime.now() > self.burst_window_start + timedelta(seconds=1):
            self.burst_count = 0
            self.burst_window_start = datetime.now()

        limits = GITTIGIDIYOR_RATE_LIMITS.get(self.endpoint_type, GITTIGIDIYOR_RATE_LIMITS["default"])
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
            limits = GITTIGIDIYOR_RATE_LIMITS.get(self.endpoint_type, GITTIGIDIYOR_RATE_LIMITS["default"])
            if self.burst_count >= limits["burst_limit"]:
                burst_end = self.burst_window_start + timedelta(seconds=1)
                delta = burst_end - datetime.now()
                return max(0, delta.total_seconds())

            window_end = self.window_start + timedelta(seconds=self.window_duration)
            delta = window_end - datetime.now()
            return max(0, delta.total_seconds())

        return 0


@dataclass
class GittiGidiyorJob:
    """Tracks a GittiGidiyor operation job"""
    job_id: str
    operation_type: str = "CREATE"
    status: str = "PENDING"
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime = None
    products_total: int = 0
    products_processed: int = 0
    products_succeeded: int = 0
    products_failed: int = 0
    errors: List[Dict] = field(default_factory=list)
    listing_ids: List[str] = field(default_factory=list)


# =============================================================================
# GittiGidiyor Adapter
# =============================================================================

class GittiGidiyorAdapter(ChannelAdapter):
    """
    GittiGidiyor channel adapter for product syndication.

    Uses the GittiGidiyor Partner REST API for product management
    with HMAC signature authentication.

    Features:
    - REST API with HMAC-SHA256 signature
    - Fixed-price and auction listing support
    - Product create/update operations
    - Stock and price synchronization
    - Category and catalog management
    - Image management
    - Shipping configuration
    """

    channel_code: str = "gittigidiyor"
    channel_name: str = "GittiGidiyor"

    # Rate limiting settings
    default_requests_per_minute: int = 40
    default_requests_per_second: float = 1.0
    max_retry_attempts: int = 5
    base_backoff_seconds: float = 2.0
    max_backoff_seconds: float = 120.0

    # Batch size for bulk operations
    batch_size: int = 10

    def __init__(self, channel_doc: Any = None):
        """Initialize GittiGidiyor adapter.

        Args:
            channel_doc: Channel Frappe document with GittiGidiyor credentials
        """
        super().__init__(channel_doc)
        self._rate_limit_state: GittiGidiyorRateLimitState = None
        self._api_base_url: str = GITTIGIDIYOR_PRODUCTION_URL
        self._job_tracker: Dict[str, GittiGidiyorJob] = {}

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def api_base_url(self) -> str:
        """Get the GittiGidiyor API base URL."""
        if self.config.get("use_staging"):
            return GITTIGIDIYOR_API_BASE_URL
        return self._api_base_url

    @property
    def rate_limit_state(self) -> GittiGidiyorRateLimitState:
        """Get current rate limit state."""
        if self._rate_limit_state is None:
            self._rate_limit_state = GittiGidiyorRateLimitState()
        return self._rate_limit_state

    # =========================================================================
    # Authentication Methods
    # =========================================================================

    def _get_gittigidiyor_credentials(self) -> Dict:
        """Get GittiGidiyor-specific credentials.

        Returns:
            Dictionary with:
            - api_key: GittiGidiyor API key (developer key)
            - api_secret: GittiGidiyor API secret (security key)
            - username: GittiGidiyor seller username
            - password: GittiGidiyor seller password
        """
        credentials = self.credentials

        return {
            "api_key": credentials.get("api_key"),
            "api_secret": credentials.get("api_secret"),
            "username": credentials.get("username") or self.config.get("username"),
            "password": credentials.get("access_token") or credentials.get("password") or self.config.get("password"),
            "lang": self.config.get("language", "tr"),
        }

    def _generate_signature(self, timestamp: str, method: str) -> str:
        """Generate HMAC-SHA256 signature for API request.

        Args:
            timestamp: Unix timestamp in milliseconds
            method: API method name

        Returns:
            Base64 encoded signature
        """
        creds = self._get_gittigidiyor_credentials()
        api_key = creds.get("api_key", "")
        api_secret = creds.get("api_secret", "")

        if not api_key or not api_secret:
            raise AuthenticationError(
                "GittiGidiyor API key and secret are required",
                channel=self.channel_code,
            )

        # Signature = Base64(HMAC-SHA256(apiKey + method + timestamp, secretKey))
        message = f"{api_key}{method}{timestamp}"
        signature = hmac.new(
            api_secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).digest()

        return base64.b64encode(signature).decode('utf-8')

    def _get_auth_headers(self, method: str) -> Dict:
        """Build authentication headers for GittiGidiyor API requests.

        Args:
            method: API method name

        Returns:
            Dictionary of HTTP headers
        """
        creds = self._get_gittigidiyor_credentials()
        timestamp = str(int(time.time() * 1000))

        signature = self._generate_signature(timestamp, method)

        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "apikey": creds.get("api_key", ""),
            "sign": signature,
            "time": timestamp,
            "lang": creds.get("lang", "tr"),
        }

    def _get_auth_body(self) -> Dict:
        """Get authentication body for API requests.

        Returns:
            Dictionary with nick (username) and pass (password)
        """
        creds = self._get_gittigidiyor_credentials()

        username = creds.get("username")
        password = creds.get("password")

        if not username or not password:
            raise AuthenticationError(
                "GittiGidiyor username and password are required",
                channel=self.channel_code,
            )

        return {
            "nick": username,
            "pass": password,
        }

    # =========================================================================
    # Rate Limiting Methods
    # =========================================================================

    def handle_rate_limiting(self, response: Any = None) -> None:
        """Handle GittiGidiyor rate limiting from response.

        Args:
            response: HTTP response object

        Raises:
            RateLimitError: If rate limit exceeded
        """
        if response is None:
            return

        status_code = None
        if hasattr(response, 'status_code'):
            status_code = response.status_code
        elif isinstance(response, dict) and 'status_code' in response:
            status_code = response['status_code']

        if status_code == 429:
            retry_after = 60

            if hasattr(response, 'headers'):
                retry_after = int(response.headers.get("Retry-After", 60))

            self.rate_limit_state.retry_after = datetime.now() + timedelta(seconds=retry_after)

            raise RateLimitError(
                "GittiGidiyor API rate limit exceeded",
                channel=self.channel_code,
                retry_after=retry_after,
            )

        if status_code in (502, 503, 504):
            self.rate_limit_state.retry_after = datetime.now() + timedelta(seconds=10)

    def _wait_for_rate_limit(self) -> None:
        """Wait if rate limited."""
        wait_time = self.rate_limit_state.wait_time()

        if wait_time > 0:
            if wait_time > self.max_backoff_seconds:
                raise RateLimitError(
                    f"GittiGidiyor rate limit wait time ({wait_time}s) exceeds maximum",
                    channel=self.channel_code,
                    retry_after=int(wait_time),
                )
            time.sleep(wait_time)

    # =========================================================================
    # API Request Methods
    # =========================================================================

    def _make_api_request(self, method_name: str, data: Dict = None,
                          endpoint_type: str = "default") -> Dict:
        """Make a request to the GittiGidiyor API.

        Args:
            method_name: API method name
            data: Request body data
            endpoint_type: Type of endpoint for rate limiting

        Returns:
            API response data
        """
        import requests

        self.rate_limit_state.endpoint_type = endpoint_type
        self._wait_for_rate_limit()

        url = f"{self.api_base_url}/{method_name}"

        # Build request body with authentication
        request_body = self._get_auth_body()
        if data:
            request_body.update(data)

        last_error = None

        for attempt in range(self.max_retry_attempts):
            try:
                self.rate_limit_state.record_request()

                headers = self._get_auth_headers(method_name)

                response = requests.post(
                    url,
                    headers=headers,
                    json=request_body,
                    timeout=self.config.get("timeout", 30),
                )

                self.handle_rate_limiting(response)

                if response.status_code in (401, 403):
                    raise AuthenticationError(
                        f"GittiGidiyor authentication failed: HTTP {response.status_code}",
                        channel=self.channel_code,
                    )

                if response.status_code in (200, 201, 202):
                    result = response.json()

                    # Check for API-level errors in response
                    if result.get("ackCode") == "failure":
                        error_message = result.get("responseMessage", "Unknown error")
                        errors = result.get("errors", [])
                        if errors:
                            error_message = "; ".join(
                                e.get("errorMessage", str(e)) for e in errors
                            )
                        raise PublishError(
                            f"GittiGidiyor API error: {error_message}",
                            channel=self.channel_code,
                            details={"errors": errors},
                        )

                    return result

                error_message = "Unknown error"
                try:
                    error_data = response.json()
                    if "responseMessage" in error_data:
                        error_message = error_data["responseMessage"]
                    elif "errors" in error_data:
                        error_message = str(error_data["errors"])
                    else:
                        error_message = str(error_data)
                except Exception:
                    error_message = response.text or f"HTTP {response.status_code}"

                raise PublishError(
                    f"GittiGidiyor API error: {error_message}",
                    channel=self.channel_code,
                    details={"status_code": response.status_code},
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
            f"GittiGidiyor API request failed after {self.max_retry_attempts} attempts: {last_error}",
            channel=self.channel_code,
        )

    # =========================================================================
    # Validation Methods
    # =========================================================================

    def validate_product(self, product: Dict) -> ValidationResult:
        """Validate a product against GittiGidiyor's requirements.

        Args:
            product: Product data dictionary in PIM format

        Returns:
            ValidationResult with validation status and any errors/warnings
        """
        errors = []
        warnings = []
        product_id = product.get("item_code", product.get("productCode", "unknown"))

        # Check required fields
        for field_name in GITTIGIDIYOR_REQUIRED_FIELDS:
            pim_field = None
            for pim_name, gg_name in PIM_TO_GITTIGIDIYOR_FIELDS.items():
                if gg_name == field_name:
                    pim_field = pim_name
                    break

            value = product.get(field_name)
            if pim_field:
                value = value or product.get(pim_field)

            # Some fields have defaults or can be inferred
            if not value and field_name not in ("categoryCode", "format", "listingDays"):
                errors.append({
                    "field": field_name,
                    "message": f"Required field '{field_name}' is missing",
                    "rule": "required",
                })

        # Validate title
        title = product.get("title") or product.get("pim_title") or product.get("item_name")
        if title:
            if len(str(title)) > GITTIGIDIYOR_FIELD_LIMITS["title"]:
                errors.append({
                    "field": "title",
                    "message": f"Title exceeds maximum length of {GITTIGIDIYOR_FIELD_LIMITS['title']}",
                    "value": f"{len(str(title))} characters",
                    "rule": "max_length",
                })
        else:
            errors.append({
                "field": "title",
                "message": "Product title is required",
                "rule": "required",
            })

        # Validate description
        description = product.get("description") or product.get("pim_description")
        if description:
            if len(str(description)) > GITTIGIDIYOR_FIELD_LIMITS["description"]:
                warnings.append({
                    "field": "description",
                    "message": f"Description exceeds recommended length",
                    "value": f"{len(str(description))} characters",
                    "rule": "max_length",
                })
        else:
            errors.append({
                "field": "description",
                "message": "Product description is required",
                "rule": "required",
            })

        # Validate buy now price
        buy_now_price = product.get("buyNowPrice") or product.get("price") or product.get("standard_rate")
        if buy_now_price is not None:
            try:
                price_val = float(buy_now_price)
                if price_val <= 0:
                    errors.append({
                        "field": "buyNowPrice",
                        "message": "Buy now price must be greater than 0",
                        "value": str(buy_now_price),
                        "rule": "positive_price",
                    })
            except (ValueError, TypeError):
                errors.append({
                    "field": "buyNowPrice",
                    "message": "Buy now price must be a valid number",
                    "value": str(buy_now_price),
                    "rule": "numeric",
                })
        else:
            errors.append({
                "field": "buyNowPrice",
                "message": "Buy now price is required",
                "rule": "required",
            })

        # Validate start price (for auctions)
        start_price = product.get("startPrice")
        if start_price is not None:
            try:
                price_val = float(start_price)
                if price_val <= 0:
                    errors.append({
                        "field": "startPrice",
                        "message": "Start price must be greater than 0",
                        "value": str(start_price),
                        "rule": "positive_price",
                    })
                if buy_now_price is not None:
                    buy_val = float(buy_now_price)
                    if price_val > buy_val:
                        warnings.append({
                            "field": "startPrice",
                            "message": "Start price is higher than buy now price",
                            "value": str(start_price),
                            "rule": "price_logic",
                        })
            except (ValueError, TypeError):
                errors.append({
                    "field": "startPrice",
                    "message": "Start price must be a valid number",
                    "value": str(start_price),
                    "rule": "numeric",
                })

        # Validate stock
        stock = product.get("stockQuantity") or product.get("stock_qty") or product.get("actual_qty")
        if stock is not None:
            try:
                stock_val = int(stock)
                if stock_val < 0:
                    errors.append({
                        "field": "stockQuantity",
                        "message": "Stock cannot be negative",
                        "value": str(stock),
                        "rule": "non_negative",
                    })
            except (ValueError, TypeError):
                errors.append({
                    "field": "stockQuantity",
                    "message": "Stock must be an integer",
                    "value": str(stock),
                    "rule": "integer",
                })
        else:
            errors.append({
                "field": "stockQuantity",
                "message": "Stock quantity is required",
                "rule": "required",
            })

        # Validate photos
        photos = product.get("photos") or product.get("images") or product.get("image")
        if photos:
            image_warnings = self._validate_images(photos)
            warnings.extend(image_warnings)
        else:
            warnings.append({
                "field": "photos",
                "message": "Product photos are recommended for better listing visibility",
                "rule": "recommended",
            })

        # Validate category
        category = product.get("categoryCode") or product.get("category_code") or product.get("gittigidiyor_category_id")
        if not category:
            warnings.append({
                "field": "categoryCode",
                "message": "Category code should be provided",
                "rule": "recommended",
            })

        # Check for recommended fields
        for field_name in GITTIGIDIYOR_RECOMMENDED_FIELDS:
            if field_name not in GITTIGIDIYOR_REQUIRED_FIELDS:
                value = product.get(field_name)
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
        """Validate product images for GittiGidiyor.

        Args:
            images: Image data

        Returns:
            List of warning dicts for image issues
        """
        warnings = []

        if isinstance(images, str):
            images = [{"url": images}]
        elif isinstance(images, list) and images and isinstance(images[0], str):
            images = [{"url": img} for img in images]

        if isinstance(images, list):
            # GittiGidiyor supports up to 12 images
            if len(images) > 12:
                warnings.append({
                    "field": "photos",
                    "message": "GittiGidiyor supports maximum 12 images per listing",
                    "value": str(len(images)),
                    "rule": "image_count",
                })

            for i, img in enumerate(images[:12]):
                img_url = img if isinstance(img, str) else img.get("url", "")
                if img_url:
                    if not img_url.startswith(("http://", "https://")):
                        warnings.append({
                            "field": "photos",
                            "message": f"Image {i+1} must be a valid URL",
                            "value": img_url[:100],
                            "rule": "image_url",
                        })

        return warnings

    # =========================================================================
    # Mapping Methods
    # =========================================================================

    def map_attributes(self, product: Dict) -> MappingResult:
        """Map PIM product attributes to GittiGidiyor format.

        Args:
            product: Product data dictionary in PIM format

        Returns:
            MappingResult with mapped data and unmapped fields
        """
        product_id = product.get("item_code", product.get("productCode", "unknown"))
        mapped_data = {}
        unmapped_fields = []

        # Product Code
        product_code = product.get("productCode") or product.get("product_code") or product.get("item_code")
        if product_code:
            mapped_data["productCode"] = str(product_code)[:GITTIGIDIYOR_FIELD_LIMITS["productCode"]]

        # Title (required)
        title = product.get("title") or product.get("pim_title") or product.get("item_name")
        if title:
            mapped_data["title"] = str(title)[:GITTIGIDIYOR_FIELD_LIMITS["title"]]

        # Subtitle
        subtitle = product.get("subtitle") or product.get("pim_short_description")
        if subtitle:
            mapped_data["subtitle"] = str(subtitle)[:GITTIGIDIYOR_FIELD_LIMITS["subtitle"]]

        # Description (required)
        description = product.get("description") or product.get("pim_description")
        if description:
            mapped_data["description"] = str(description)[:GITTIGIDIYOR_FIELD_LIMITS["description"]]

        # Category Code (required)
        category = (product.get("categoryCode") or
                   product.get("category_code") or
                   product.get("gittigidiyor_category_id"))
        if category:
            mapped_data["categoryCode"] = str(category)

        # Listing Format
        listing_format = product.get("format") or product.get("listing_format")
        if listing_format:
            format_lower = str(listing_format).lower()
            if format_lower in ("auction", "mezat"):
                mapped_data["format"] = GittiGidiyorListingType.AUCTION.value
            elif format_lower in ("store", "store_fixed_price", "magaza"):
                mapped_data["format"] = GittiGidiyorListingType.STORE_FIXED_PRICE.value
            else:
                mapped_data["format"] = GittiGidiyorListingType.FIXED_PRICE.value
        else:
            mapped_data["format"] = GittiGidiyorListingType.FIXED_PRICE.value

        # Pricing
        buy_now_price = product.get("buyNowPrice") or product.get("price") or product.get("standard_rate")
        if buy_now_price is not None:
            mapped_data["buyNowPrice"] = float(buy_now_price)

        start_price = product.get("startPrice") or product.get("start_price")
        if start_price is not None:
            mapped_data["startPrice"] = float(start_price)
        elif buy_now_price is not None:
            # For fixed price listings, start price = buy now price
            mapped_data["startPrice"] = float(buy_now_price)

        # Currency
        currency = product.get("currency") or product.get("currencyType")
        if currency:
            currency_upper = str(currency).upper()
            if currency_upper in ("TRY", "TL", "LIRA"):
                mapped_data["currency"] = GittiGidiyorCurrency.TRY.value
            elif currency_upper in ("USD", "DOLLAR"):
                mapped_data["currency"] = GittiGidiyorCurrency.USD.value
            elif currency_upper in ("EUR", "EURO"):
                mapped_data["currency"] = GittiGidiyorCurrency.EUR.value
            else:
                mapped_data["currency"] = GittiGidiyorCurrency.TRY.value
        else:
            mapped_data["currency"] = GittiGidiyorCurrency.TRY.value

        # Stock Quantity
        stock = product.get("stockQuantity") or product.get("stock_qty") or product.get("actual_qty")
        if stock is not None:
            mapped_data["stockQuantity"] = max(0, int(stock))
        else:
            mapped_data["stockQuantity"] = 0

        # Listing Days (duration)
        listing_days = product.get("listingDays") or product.get("listing_days")
        if listing_days is not None:
            mapped_data["listingDays"] = int(listing_days)
        else:
            # Default: 30 days for fixed price, 7 for auction
            if mapped_data.get("format") == GittiGidiyorListingType.AUCTION.value:
                mapped_data["listingDays"] = 7
            else:
                mapped_data["listingDays"] = 30

        # Photos
        photos = self._map_photos(product)
        if photos:
            mapped_data["photos"] = {"photo": photos}

        # Cargo Detail
        cargo_detail = self._map_cargo_detail(product)
        if cargo_detail:
            mapped_data["cargoDetail"] = cargo_detail

        # Item Specifics (attributes)
        item_specifics = self._map_item_specifics(product)
        if item_specifics:
            mapped_data["itemSpecifics"] = {"itemSpecific": item_specifics}

        # Shipping Detail
        shipping_detail = self._map_shipping_detail(product)
        if shipping_detail:
            mapped_data["shippingDetail"] = shipping_detail

        # Listing ID (for updates)
        listing_id = product.get("listingId") or product.get("listing_id") or product.get("gittigidiyor_listing_id")
        if listing_id:
            mapped_data["listingId"] = str(listing_id)

        # Bold title option
        bold_title = product.get("boldTitle") or product.get("bold_title")
        if bold_title is not None:
            mapped_data["boldTitle"] = bool(bold_title)

        # Track unmapped fields
        mapped_pim_fields = set(PIM_TO_GITTIGIDIYOR_FIELDS.keys())
        mapped_pim_fields.update({
            "productCode", "product_code", "title", "pim_title", "item_name",
            "subtitle", "pim_short_description", "description", "pim_description",
            "categoryCode", "category_code", "gittigidiyor_category_id",
            "format", "listing_format", "buyNowPrice", "price", "standard_rate",
            "startPrice", "start_price", "currency", "currencyType",
            "stockQuantity", "stock_qty", "actual_qty",
            "listingDays", "listing_days", "photos", "images", "image",
            "cargoDetail", "cargo_detail", "itemSpecifics", "attributes",
            "shippingDetail", "shipping_detail",
            "listingId", "listing_id", "gittigidiyor_listing_id",
            "boldTitle", "bold_title",
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

    def _map_photos(self, product: Dict) -> List[Dict]:
        """Map photos to GittiGidiyor format.

        Args:
            product: Product data dictionary

        Returns:
            List of photo dictionaries
        """
        photos = []
        image_data = product.get("photos") or product.get("images") or product.get("image")

        if image_data:
            if isinstance(image_data, str):
                photos.append({"url": image_data, "order": 1})
            elif isinstance(image_data, list):
                for i, img in enumerate(image_data[:12]):
                    if isinstance(img, str):
                        photos.append({"url": img, "order": i + 1})
                    elif isinstance(img, dict):
                        img_url = img.get("url") or img.get("src")
                        if img_url:
                            photos.append({
                                "url": img_url,
                                "order": img.get("order", i + 1),
                            })

        return photos

    def _map_cargo_detail(self, product: Dict) -> Optional[Dict]:
        """Map cargo detail to GittiGidiyor format.

        Args:
            product: Product data dictionary

        Returns:
            Cargo detail dictionary or None
        """
        cargo_detail = product.get("cargoDetail") or product.get("cargo_detail")
        if cargo_detail and isinstance(cargo_detail, dict):
            return cargo_detail

        # Build from individual fields
        cargo = {}

        cargo_company = product.get("cargoCompany") or product.get("cargo_company")
        if cargo_company:
            cargo["cargoCompany"] = str(cargo_company)

        cargo_cost = product.get("cargoCost") or product.get("cargo_cost") or product.get("shipping_cost")
        if cargo_cost is not None:
            cargo["cargoCost"] = float(cargo_cost)

        free_shipping = product.get("freeShipping") or product.get("free_shipping")
        if free_shipping is not None:
            cargo["freeShipping"] = bool(free_shipping)

        city_price = product.get("cityPrice") or product.get("city_price")
        if city_price is not None:
            cargo["cityPrice"] = float(city_price)

        country_price = product.get("countryPrice") or product.get("country_price")
        if country_price is not None:
            cargo["countryPrice"] = float(country_price)

        return cargo if cargo else None

    def _map_item_specifics(self, product: Dict) -> List[Dict]:
        """Map item specifics (attributes) to GittiGidiyor format.

        Args:
            product: Product data dictionary

        Returns:
            List of item specific dictionaries
        """
        specifics = []

        existing_specifics = product.get("itemSpecifics") or product.get("attributes")
        if existing_specifics and isinstance(existing_specifics, list):
            for spec in existing_specifics:
                if isinstance(spec, dict):
                    specific = {}
                    if "id" in spec:
                        specific["id"] = int(spec["id"])
                    if "name" in spec:
                        specific["name"] = str(spec["name"])
                    if "value" in spec:
                        specific["value"] = str(spec["value"])
                    if "valueId" in spec:
                        specific["valueId"] = int(spec["valueId"])

                    if specific.get("id") or specific.get("name"):
                        specifics.append(specific)

        # Map common attributes
        common_attrs = {
            "brand": product.get("brand"),
            "model": product.get("model"),
            "color": product.get("color"),
            "size": product.get("size"),
            "material": product.get("material"),
            "barcode": product.get("barcode") or product.get("gtin"),
        }

        for name, value in common_attrs.items():
            if value and not any(s.get("name") == name for s in specifics):
                specifics.append({"name": name, "value": str(value)})

        return specifics

    def _map_shipping_detail(self, product: Dict) -> Optional[Dict]:
        """Map shipping detail to GittiGidiyor format.

        Args:
            product: Product data dictionary

        Returns:
            Shipping detail dictionary or None
        """
        shipping_detail = product.get("shippingDetail") or product.get("shipping_detail")
        if shipping_detail and isinstance(shipping_detail, dict):
            return shipping_detail

        shipping = {}

        handling_time = product.get("handlingTime") or product.get("handling_time") or product.get("dispatch_time")
        if handling_time is not None:
            shipping["handlingTime"] = int(handling_time)

        return shipping if shipping else None

    # =========================================================================
    # Payload Generation
    # =========================================================================

    def generate_payload(self, products: List[Dict]) -> Dict:
        """Generate GittiGidiyor API payload for products.

        Args:
            products: List of mapped product data dictionaries

        Returns:
            Dictionary with products ready for API calls
        """
        payload = {
            "listings": products,
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
        """Publish products to GittiGidiyor.

        Args:
            products: List of product data dictionaries in PIM format

        Returns:
            PublishResult with job status and any errors
        """
        job_id = str(uuid.uuid4())
        errors = []
        products_succeeded = 0
        products_failed = 0
        listing_ids = []

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

            # Map and publish products one by one
            for product in products:
                mapping_result = self.map_attributes(product)
                mapped_data = mapping_result.mapped_data

                try:
                    result = self._create_or_update_listing(mapped_data)

                    if result.get("success"):
                        products_succeeded += 1
                        if result.get("listingId"):
                            listing_ids.append(str(result["listingId"]))
                    else:
                        products_failed += 1
                        errors.append(result.get("error", {"message": "Unknown error"}))

                except RateLimitError as e:
                    self._log_publish_event("rate_limited", {
                        "job_id": job_id,
                        "products_succeeded": products_succeeded,
                        "error": str(e),
                    })

                    self._job_tracker[job_id] = GittiGidiyorJob(
                        job_id=job_id,
                        status="RATE_LIMITED",
                        products_total=len(products),
                        products_processed=products_succeeded + products_failed,
                        products_succeeded=products_succeeded,
                        products_failed=products_failed,
                        errors=errors,
                        listing_ids=listing_ids,
                    )

                    return PublishResult(
                        success=False,
                        job_id=job_id,
                        status=PublishStatus.RATE_LIMITED,
                        products_submitted=products_succeeded + products_failed,
                        products_succeeded=products_succeeded,
                        products_failed=products_failed,
                        errors=errors + [{"message": str(e.message), "retry_after": e.retry_after}],
                        channel=self.channel_code,
                    )

                except Exception as e:
                    products_failed += 1
                    errors.append({"message": str(e)})

            # Determine final status
            products_submitted = products_succeeded + products_failed

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
            self._job_tracker[job_id] = GittiGidiyorJob(
                job_id=job_id,
                status=status.value.upper(),
                products_total=len(products),
                products_processed=products_submitted,
                products_succeeded=products_succeeded,
                products_failed=products_failed,
                errors=errors,
                listing_ids=listing_ids,
                completed_at=datetime.now(),
            )

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
                external_id=",".join(listing_ids) if listing_ids else None,
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

    def _create_or_update_listing(self, listing_data: Dict) -> Dict:
        """Create or update a listing on GittiGidiyor.

        Args:
            listing_data: Listing data in GittiGidiyor format

        Returns:
            Dict with success status and listingId or error
        """
        is_update = "listingId" in listing_data

        try:
            if is_update:
                response = self._make_api_request(
                    "updateProduct",
                    data={"product": listing_data},
                    endpoint_type="product_create",
                )
            else:
                response = self._make_api_request(
                    "insertProduct",
                    data={"product": listing_data},
                    endpoint_type="product_create",
                )

            listing_id = None
            if response.get("ackCode") == "success":
                if "product" in response:
                    listing_id = response["product"].get("listingId")
                elif "listingId" in response:
                    listing_id = response["listingId"]

                return {
                    "success": True,
                    "listingId": listing_id,
                }
            else:
                return {
                    "success": False,
                    "error": {
                        "message": response.get("responseMessage", "Unknown error"),
                    },
                }

        except PublishError as e:
            return {
                "success": False,
                "error": {
                    "message": str(e.message),
                    "details": e.details,
                },
            }

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
        if job_id in self._job_tracker:
            job = self._job_tracker[job_id]

            status_mapping = {
                "PENDING": PublishStatus.PENDING,
                "COMPLETED": PublishStatus.COMPLETED,
                "FAILED": PublishStatus.FAILED,
                "PARTIAL": PublishStatus.PARTIAL,
                "RATE_LIMITED": PublishStatus.RATE_LIMITED,
            }

            progress = 1.0 if job.status in ("COMPLETED", "PARTIAL", "FAILED") else 0.0
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
        """Test the connection to GittiGidiyor.

        Returns:
            Dictionary with connection status
        """
        try:
            response = self._make_api_request(
                "getCategories",
                data={"categoryCode": ""},
                endpoint_type="search",
            )

            if response.get("ackCode") == "success":
                return {
                    "success": True,
                    "message": "Connection successful",
                }
            else:
                return {
                    "success": True,
                    "message": "Connection established",
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

    def get_categories(self, parent_code: str = None) -> List[Dict]:
        """Retrieve categories from GittiGidiyor.

        Args:
            parent_code: Parent category code (None for top level)

        Returns:
            List of category dictionaries
        """
        try:
            response = self._make_api_request(
                "getCategories",
                data={"categoryCode": parent_code or ""},
                endpoint_type="search",
            )

            categories = []
            if response.get("categories"):
                for cat in response["categories"].get("category", []):
                    categories.append({
                        "code": cat.get("categoryCode"),
                        "name": cat.get("categoryName"),
                        "parentCode": cat.get("parentCategoryCode"),
                        "hasChildren": cat.get("hasChildren", False),
                    })

            return categories
        except Exception:
            return []

    def get_category_attributes(self, category_code: str) -> List[Dict]:
        """Retrieve attributes for a category.

        Args:
            category_code: GittiGidiyor category code

        Returns:
            List of attribute dictionaries
        """
        try:
            response = self._make_api_request(
                "getCategoryAttributes",
                data={"categoryCode": category_code},
                endpoint_type="search",
            )

            attributes = []
            if response.get("categoryAttributes"):
                for attr in response["categoryAttributes"].get("attribute", []):
                    attributes.append({
                        "id": attr.get("id"),
                        "name": attr.get("name"),
                        "required": attr.get("required", False),
                        "multiSelect": attr.get("multiSelect", False),
                        "values": [
                            {"id": v.get("id"), "name": v.get("value")}
                            for v in attr.get("values", {}).get("value", [])
                        ] if attr.get("values") else [],
                    })

            return attributes
        except Exception:
            return []

    def get_listing_by_product_code(self, product_code: str) -> Optional[Dict]:
        """Retrieve a listing from GittiGidiyor by product code.

        Args:
            product_code: The product code

        Returns:
            Listing data dict if found, None otherwise
        """
        try:
            response = self._make_api_request(
                "getProducts",
                data={
                    "productCode": product_code,
                    "startOffSet": 0,
                    "rowCount": 1,
                },
                endpoint_type="search",
            )

            if response.get("products") and response["products"].get("product"):
                products = response["products"]["product"]
                if products:
                    product = products[0] if isinstance(products, list) else products
                    return {
                        "listingId": product.get("listingId"),
                        "title": product.get("title"),
                        "productCode": product.get("productCode"),
                        "buyNowPrice": product.get("buyNowPrice"),
                        "status": product.get("status"),
                    }

            return None
        except Exception:
            return None

    def update_stock(self, items: List[Dict]) -> PublishResult:
        """Update stock for existing listings.

        Args:
            items: List of items with productCode and stockQuantity

        Returns:
            PublishResult with operation status
        """
        job_id = str(uuid.uuid4())
        errors = []
        succeeded = 0
        failed = 0

        try:
            for item in items:
                try:
                    response = self._make_api_request(
                        "updateStockAndPrice",
                        data={
                            "productCode": item.get("productCode"),
                            "stockQuantity": item.get("stockQuantity", 0),
                        },
                        endpoint_type="product_create",
                    )

                    if response.get("ackCode") == "success":
                        succeeded += 1
                    else:
                        failed += 1
                        errors.append({
                            "productCode": item.get("productCode"),
                            "message": response.get("responseMessage", "Update failed"),
                        })

                except Exception as e:
                    failed += 1
                    errors.append({
                        "productCode": item.get("productCode"),
                        "message": str(e),
                    })

            status = PublishStatus.COMPLETED if failed == 0 else (
                PublishStatus.PARTIAL if succeeded > 0 else PublishStatus.FAILED
            )

            return PublishResult(
                success=failed == 0 or succeeded > 0,
                job_id=job_id,
                status=status,
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
                errors=[{"message": str(e)}],
                channel=self.channel_code,
            )

    def end_listing(self, listing_id: str) -> bool:
        """End a listing.

        Args:
            listing_id: The listing ID to end

        Returns:
            True if successful
        """
        try:
            response = self._make_api_request(
                "endProduct",
                data={"listingId": listing_id},
                endpoint_type="product_create",
            )
            return response.get("ackCode") == "success"
        except Exception:
            return False

    def relist(self, listing_id: str, listing_days: int = 30) -> bool:
        """Relist an ended listing.

        Args:
            listing_id: The listing ID to relist
            listing_days: Duration in days

        Returns:
            True if successful
        """
        try:
            response = self._make_api_request(
                "relistProduct",
                data={
                    "listingId": listing_id,
                    "listingDays": listing_days,
                },
                endpoint_type="product_create",
            )
            return response.get("ackCode") == "success"
        except Exception:
            return False


# =============================================================================
# Register Adapter
# =============================================================================

register_adapter("gittigidiyor", GittiGidiyorAdapter)
register_adapter("gg", GittiGidiyorAdapter)  # Short alias
