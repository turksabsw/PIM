"""
Walmart Channel Adapter

Provides a comprehensive adapter for Walmart Marketplace product syndication
using the Walmart Marketplace API.

Features:
- Walmart Marketplace API integration
- OAuth 2.0 authentication with client credentials
- Comprehensive product validation against Walmart requirements
- Attribute mapping to Walmart product format
- Feed-based bulk operations with async status checking
- Item management and inventory synchronization

Note: frappe imports are deferred to function/method level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional
import json
import time
import uuid
import base64
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
# Walmart-Specific Constants
# =============================================================================

class WalmartProductStatus(str, Enum):
    """Walmart product lifecycle status values"""
    PUBLISHED = "PUBLISHED"
    UNPUBLISHED = "UNPUBLISHED"
    STAGE = "STAGE"
    RETIRED = "RETIRED"


class WalmartFulfillmentType(str, Enum):
    """Walmart fulfillment types"""
    SELLER = "SELLER"  # Seller fulfilled
    WFS = "WFS"  # Walmart Fulfillment Services


class WalmartCondition(str, Enum):
    """Walmart product condition types"""
    NEW = "New"
    REFURBISHED = "Refurbished"
    USED_LIKE_NEW = "Used - Like New"
    USED_VERY_GOOD = "Used - Very Good"
    USED_GOOD = "Used - Good"
    USED_ACCEPTABLE = "Used - Acceptable"


# Walmart API endpoints
WALMART_API_BASE_URL = "https://marketplace.walmartapis.com"
WALMART_SANDBOX_URL = "https://sandbox.walmartapis.com"
WALMART_AUTH_URL = "https://marketplace.walmartapis.com/v3/token"

# Walmart rate limit configuration
# Production: 20 calls/second for most endpoints
WALMART_RATE_LIMITS = {
    "default": {
        "requests_per_second": 20,
        "requests_per_minute": 1200,
        "burst_limit": 40,
    },
    "feed": {
        "requests_per_second": 5,
        "requests_per_minute": 300,
        "burst_limit": 10,
    },
    "bulk": {
        "requests_per_second": 2,
        "requests_per_minute": 120,
        "burst_limit": 5,
    },
}

# Required fields for Walmart products
WALMART_REQUIRED_FIELDS = {
    "sku",
    "productName",
    "productId",
    "productIdType",
    "price",
    "brand",
    "shortDescription",
}

# Recommended fields
WALMART_RECOMMENDED_FIELDS = {
    "longDescription",
    "mainImage",
    "productCategory",
    "shippingWeight",
    "swatchImages",
    "additionalProductAttributes",
}

# Field length limits
WALMART_FIELD_LIMITS = {
    "productName": 200,
    "sku": 50,
    "shortDescription": 1000,
    "longDescription": 4000,
    "brand": 60,
}

# PIM to Walmart field mappings
PIM_TO_WALMART_FIELDS = {
    "item_code": "sku",
    "item_name": "productName",
    "pim_title": "productName",
    "pim_description": "longDescription",
    "description": "shortDescription",
    "brand": "brand",
    "standard_rate": "price",
    "barcode": "productId",
    "gtin": "productId",
    "weight_per_unit": "shippingWeight",
    "image": "mainImage",
    "item_group": "productCategory",
}


# =============================================================================
# Walmart-Specific Data Classes
# =============================================================================

@dataclass
class WalmartToken:
    """Walmart OAuth token with expiration tracking"""
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 900  # 15 minutes
    obtained_at: datetime = field(default_factory=datetime.now)

    def is_expired(self) -> bool:
        """Check if token is expired or about to expire (2 min buffer)"""
        expiration = self.obtained_at + timedelta(seconds=self.expires_in - 120)
        return datetime.now() >= expiration


@dataclass
class WalmartRateLimitState:
    """Tracks Walmart rate limit state"""
    requests_made: int = 0
    requests_limit: int = 1200
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

        limits = WALMART_RATE_LIMITS.get(self.endpoint_type, WALMART_RATE_LIMITS["default"])
        return (self.requests_made >= limits["requests_per_minute"] or
                self.burst_count >= limits["burst_limit"])

    def record_request(self) -> None:
        """Record a request for rate limiting"""
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
            limits = WALMART_RATE_LIMITS.get(self.endpoint_type, WALMART_RATE_LIMITS["default"])
            if self.burst_count >= limits["burst_limit"]:
                burst_end = self.burst_window_start + timedelta(seconds=1)
                delta = burst_end - datetime.now()
                return max(0, delta.total_seconds())

            window_end = self.window_start + timedelta(seconds=self.window_duration)
            delta = window_end - datetime.now()
            return max(0, delta.total_seconds())

        return 0


@dataclass
class WalmartFeedJob:
    """Tracks a Walmart feed job"""
    job_id: str
    feed_id: str = None
    feed_type: str = "item"
    status: str = "RECEIVED"
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime = None
    items_total: int = 0
    items_received: int = 0
    items_succeeded: int = 0
    items_failed: int = 0
    errors: List[Dict] = field(default_factory=list)


# =============================================================================
# Walmart Adapter
# =============================================================================

class WalmartAdapter(ChannelAdapter):
    """
    Walmart Marketplace channel adapter for product syndication.

    Uses the Walmart Marketplace API for product management with
    support for feed-based bulk operations.

    Features:
    - OAuth 2.0 client credentials authentication
    - Feed-based bulk item creation/update
    - Async feed status checking
    - Inventory and price synchronization
    - Rich product attribute support
    """

    channel_code: str = "walmart"
    channel_name: str = "Walmart Marketplace"

    # Rate limiting settings
    default_requests_per_minute: int = 1200
    default_requests_per_second: float = 20.0
    max_retry_attempts: int = 5
    base_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 120.0

    # API version
    api_version: str = "v3"

    def __init__(self, channel_doc: Any = None):
        """Initialize Walmart adapter.

        Args:
            channel_doc: Channel Frappe document with Walmart credentials
        """
        super().__init__(channel_doc)
        self._token: Optional[WalmartToken] = None
        self._rate_limit_state: WalmartRateLimitState = None
        self._api_base_url: str = WALMART_API_BASE_URL
        self._job_tracker: Dict[str, WalmartFeedJob] = {}

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def api_base_url(self) -> str:
        """Get the Walmart API base URL."""
        if self.config.get("use_sandbox"):
            return WALMART_SANDBOX_URL
        return self._api_base_url

    @property
    def rate_limit_state(self) -> WalmartRateLimitState:
        """Get current rate limit state."""
        if self._rate_limit_state is None:
            self._rate_limit_state = WalmartRateLimitState()
        return self._rate_limit_state

    # =========================================================================
    # Authentication Methods
    # =========================================================================

    def _get_walmart_credentials(self) -> Dict:
        """Get Walmart-specific credentials.

        Returns:
            Dictionary with client_id and client_secret
        """
        credentials = self.credentials

        return {
            "client_id": credentials.get("api_key") or credentials.get("client_id"),
            "client_secret": credentials.get("api_secret") or credentials.get("client_secret"),
        }

    def _get_access_token(self) -> str:
        """Get a valid OAuth access token.

        Returns:
            Valid access token string

        Raises:
            AuthenticationError: If token request fails
        """
        import requests

        if self._token and not self._token.is_expired():
            return self._token.access_token

        creds = self._get_walmart_credentials()

        if not creds.get("client_id") or not creds.get("client_secret"):
            raise AuthenticationError(
                "Walmart client_id and client_secret are required",
                channel=self.channel_code,
            )

        auth_string = f"{creds['client_id']}:{creds['client_secret']}"
        encoded = base64.b64encode(auth_string.encode()).decode()

        headers = {
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "WM_SVC.NAME": "Frappe PIM",
            "WM_QOS.CORRELATION_ID": str(uuid.uuid4()),
        }

        try:
            response = requests.post(
                WALMART_AUTH_URL,
                headers=headers,
                data={"grant_type": "client_credentials"},
                timeout=30,
            )

            if response.status_code != 200:
                raise AuthenticationError(
                    f"Walmart OAuth failed: {response.status_code} - {response.text}",
                    channel=self.channel_code,
                )

            token_data = response.json()
            self._token = WalmartToken(
                access_token=token_data["access_token"],
                token_type=token_data.get("token_type", "Bearer"),
                expires_in=int(token_data.get("expires_in", 900)),
            )

            return self._token.access_token

        except requests.exceptions.RequestException as e:
            raise AuthenticationError(
                f"Failed to connect to Walmart OAuth: {str(e)}",
                channel=self.channel_code,
            )

    def _get_auth_headers(self) -> Dict:
        """Build authentication headers for Walmart API requests.

        Returns:
            Dictionary of HTTP headers
        """
        access_token = self._get_access_token()
        correlation_id = str(uuid.uuid4())

        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "WM_SVC.NAME": "Frappe PIM",
            "WM_QOS.CORRELATION_ID": correlation_id,
            "WM_SEC.ACCESS_TOKEN": access_token,
        }

    # =========================================================================
    # Rate Limiting Methods
    # =========================================================================

    def handle_rate_limiting(self, response: Any = None) -> None:
        """Handle Walmart rate limiting from response.

        Args:
            response: HTTP response object

        Raises:
            RateLimitError: If rate limit exceeded
        """
        if response is None:
            return

        status_code = getattr(response, 'status_code', None)

        if status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 60))
            self.rate_limit_state.retry_after = datetime.now() + timedelta(seconds=retry_after)

            raise RateLimitError(
                "Walmart API rate limit exceeded",
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
                    f"Walmart rate limit wait time ({wait_time}s) exceeds maximum",
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
        """Make a request to the Walmart API.

        Args:
            method: HTTP method
            endpoint: API endpoint
            data: Request body data
            params: Query parameters
            endpoint_type: Type of endpoint for rate limiting

        Returns:
            API response data
        """
        import requests

        self.rate_limit_state.endpoint_type = endpoint_type
        self._wait_for_rate_limit()

        url = f"{self.api_base_url}/{self.api_version}/{endpoint}"

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
                        timeout=self.config.get("timeout", 60)
                    )
                elif method.upper() == "PUT":
                    response = requests.put(
                        url, headers=headers, json=data,
                        timeout=self.config.get("timeout", 30)
                    )
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                self.handle_rate_limiting(response)

                if response.status_code in (401, 403):
                    self._token = None
                    raise AuthenticationError(
                        f"Walmart authentication failed: HTTP {response.status_code}",
                        channel=self.channel_code,
                    )

                if response.status_code in (200, 201, 202):
                    try:
                        return response.json()
                    except Exception:
                        return {"success": True}

                error_message = "Unknown error"
                try:
                    error_data = response.json()
                    if "errors" in error_data:
                        error_message = str(error_data["errors"])
                    elif "message" in error_data:
                        error_message = error_data["message"]
                except Exception:
                    error_message = response.text or f"HTTP {response.status_code}"

                raise PublishError(
                    f"Walmart API error: {error_message}",
                    channel=self.channel_code,
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
            f"Walmart API request failed: {last_error}",
            channel=self.channel_code,
        )

    # =========================================================================
    # Validation Methods
    # =========================================================================

    def validate_product(self, product: Dict) -> ValidationResult:
        """Validate a product against Walmart's requirements.

        Args:
            product: Product data dictionary

        Returns:
            ValidationResult with validation status
        """
        errors = []
        warnings = []
        product_id = product.get("item_code", product.get("sku", "unknown"))

        # Check required fields
        for field_name in WALMART_REQUIRED_FIELDS:
            pim_field = None
            for pim_name, wm_name in PIM_TO_WALMART_FIELDS.items():
                if wm_name == field_name:
                    pim_field = pim_name
                    break

            value = product.get(field_name)
            if pim_field:
                value = value or product.get(pim_field)

            if not value and field_name not in ("productIdType",):
                errors.append({
                    "field": field_name,
                    "message": f"Required field '{field_name}' is missing",
                    "rule": "required",
                })

        # Validate product ID (GTIN)
        product_id_val = product.get("productId") or product.get("barcode") or product.get("gtin")
        if product_id_val:
            gtin_str = str(product_id_val).strip()
            if len(gtin_str) not in (8, 12, 13, 14):
                errors.append({
                    "field": "productId",
                    "message": "Product ID must be a valid GTIN (8, 12, 13, or 14 digits)",
                    "value": gtin_str,
                    "rule": "gtin_format",
                })
        else:
            errors.append({
                "field": "productId",
                "message": "GTIN is required for Walmart listings",
                "rule": "required",
            })

        # Validate title length
        title = product.get("productName") or product.get("pim_title") or product.get("item_name")
        if title:
            if len(str(title)) > WALMART_FIELD_LIMITS["productName"]:
                errors.append({
                    "field": "productName",
                    "message": f"Product name exceeds {WALMART_FIELD_LIMITS['productName']} characters",
                    "rule": "max_length",
                })

        # Validate price
        price = product.get("price") or product.get("standard_rate")
        if price is not None:
            try:
                price_val = float(price)
                if price_val <= 0:
                    errors.append({
                        "field": "price",
                        "message": "Price must be greater than 0",
                        "rule": "positive_price",
                    })
            except (ValueError, TypeError):
                errors.append({
                    "field": "price",
                    "message": "Price must be a valid number",
                    "rule": "numeric",
                })

        # Check recommended fields
        for field_name in WALMART_RECOMMENDED_FIELDS:
            if field_name not in product:
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

    # =========================================================================
    # Mapping Methods
    # =========================================================================

    def map_attributes(self, product: Dict) -> MappingResult:
        """Map PIM product attributes to Walmart format.

        Args:
            product: Product data dictionary

        Returns:
            MappingResult with mapped data
        """
        product_id = product.get("item_code", product.get("sku", "unknown"))
        mapped_data = {}
        unmapped_fields = []

        # SKU (required)
        sku = product.get("item_code") or product.get("sku")
        if sku:
            mapped_data["sku"] = str(sku)[:WALMART_FIELD_LIMITS["sku"]]

        # Product Name (required)
        title = product.get("pim_title") or product.get("productName") or product.get("item_name")
        if title:
            mapped_data["productName"] = str(title)[:WALMART_FIELD_LIMITS["productName"]]

        # Product ID / GTIN (required)
        gtin = product.get("barcode") or product.get("gtin") or product.get("productId")
        if gtin:
            gtin_str = str(gtin).strip()
            mapped_data["productId"] = gtin_str

            # Determine ID type
            if len(gtin_str) == 12:
                mapped_data["productIdType"] = "UPC"
            elif len(gtin_str) == 13:
                mapped_data["productIdType"] = "EAN"
            elif len(gtin_str) == 14:
                mapped_data["productIdType"] = "GTIN"
            else:
                mapped_data["productIdType"] = "GTIN"

        # Brand (required)
        brand = product.get("brand")
        if brand:
            mapped_data["brand"] = str(brand)[:WALMART_FIELD_LIMITS["brand"]]

        # Descriptions
        short_desc = product.get("shortDescription") or product.get("description")
        if short_desc:
            mapped_data["shortDescription"] = str(short_desc)[:WALMART_FIELD_LIMITS["shortDescription"]]

        long_desc = product.get("longDescription") or product.get("pim_description")
        if long_desc:
            mapped_data["longDescription"] = str(long_desc)[:WALMART_FIELD_LIMITS["longDescription"]]

        # Price
        price = product.get("price") or product.get("standard_rate")
        if price is not None:
            mapped_data["price"] = {
                "currency": product.get("currency", "USD"),
                "amount": float(price),
            }

        # Shipping weight
        weight = product.get("shippingWeight") or product.get("weight_per_unit")
        if weight is not None:
            mapped_data["shippingWeight"] = {
                "value": float(weight),
                "unit": product.get("weight_unit", "lb").upper(),
            }

        # Main image
        image = product.get("mainImage") or product.get("image")
        if image:
            if isinstance(image, str):
                mapped_data["mainImage"] = {"url": image}
            elif isinstance(image, list) and image:
                mapped_data["mainImage"] = {"url": image[0] if isinstance(image[0], str) else image[0].get("url")}

        # Category
        category = product.get("productCategory") or product.get("item_group")
        if category:
            mapped_data["productCategory"] = str(category)

        # Condition
        condition = product.get("condition", "New")
        try:
            mapped_data["condition"] = WalmartCondition[condition.upper().replace(" ", "_").replace("-", "_")].value
        except KeyError:
            mapped_data["condition"] = WalmartCondition.NEW.value

        # Fulfillment
        fulfillment = product.get("fulfillmentType", "SELLER")
        try:
            mapped_data["fulfillmentType"] = WalmartFulfillmentType[fulfillment.upper()].value
        except KeyError:
            mapped_data["fulfillmentType"] = WalmartFulfillmentType.SELLER.value

        # Track unmapped fields
        mapped_pim_fields = set(PIM_TO_WALMART_FIELDS.keys())
        mapped_pim_fields.update({
            "productName", "productId", "productIdType", "shortDescription",
            "longDescription", "shippingWeight", "mainImage", "productCategory",
            "condition", "fulfillmentType", "currency", "weight_unit",
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

    # =========================================================================
    # Payload Generation
    # =========================================================================

    def generate_payload(self, products: List[Dict]) -> Dict:
        """Generate Walmart API payload for products.

        Args:
            products: List of mapped product data

        Returns:
            Dictionary with products ready for API
        """
        items = []
        for product in products:
            item = {
                "sku": product.get("sku"),
                "productIdentifiers": {
                    "productId": product.get("productId"),
                    "productIdType": product.get("productIdType", "GTIN"),
                },
            }

            if "productName" in product:
                item["productName"] = product["productName"]
            if "brand" in product:
                item["brand"] = product["brand"]
            if "shortDescription" in product:
                item["shortDescription"] = product["shortDescription"]
            if "longDescription" in product:
                item["longDescription"] = product["longDescription"]
            if "price" in product:
                item["price"] = product["price"]
            if "shippingWeight" in product:
                item["shippingWeight"] = product["shippingWeight"]
            if "mainImage" in product:
                item["mainImage"] = product["mainImage"]
            if "productCategory" in product:
                item["productCategory"] = product["productCategory"]
            if "condition" in product:
                item["condition"] = product["condition"]

            items.append(item)

        return {
            "ItemFeedHeader": {
                "version": "1.0",
                "subCategory": "item_spec",
            },
            "Item": items,
            "_metadata": {
                "feed_id": str(uuid.uuid4()),
                "created_at": datetime.now().isoformat(),
                "product_count": len(items),
            },
        }

    # =========================================================================
    # Publishing Methods
    # =========================================================================

    def publish(self, products: List[Dict]) -> PublishResult:
        """Publish products to Walmart.

        Args:
            products: List of product data dictionaries

        Returns:
            PublishResult with job status
        """
        job_id = str(uuid.uuid4())
        errors = []

        try:
            # Validate all products
            validation_results = self.validate_products(products)
            invalid_products = [r for r in validation_results if not r.is_valid]

            if invalid_products:
                for result in invalid_products:
                    errors.extend(result.errors)

                return PublishResult(
                    success=False,
                    job_id=job_id,
                    status=PublishStatus.FAILED,
                    products_failed=len(invalid_products),
                    errors=errors,
                    channel=self.channel_code,
                )

            # Map products
            mapped_products = []
            for product in products:
                mapping_result = self.map_attributes(product)
                mapped_products.append(mapping_result.mapped_data)

            # Generate payload
            payload = self.generate_payload(mapped_products)

            # Submit feed
            result = self._make_api_request(
                "POST",
                "feeds",
                data=payload,
                params={"feedType": "item"},
                endpoint_type="feed",
            )

            feed_id = result.get("feedId")

            self._job_tracker[job_id] = WalmartFeedJob(
                job_id=job_id,
                feed_id=feed_id,
                items_total=len(products),
            )

            self._log_publish_event("submit_success", {
                "job_id": job_id,
                "feed_id": feed_id,
                "products_count": len(products),
            })

            return PublishResult(
                success=True,
                job_id=job_id,
                status=PublishStatus.IN_PROGRESS,
                products_submitted=len(products),
                channel=self.channel_code,
                external_id=feed_id,
            )

        except AuthenticationError as e:
            return PublishResult(
                success=False,
                job_id=job_id,
                status=PublishStatus.FAILED,
                errors=[{"message": str(e.message)}],
                channel=self.channel_code,
            )

        except Exception as e:
            return PublishResult(
                success=False,
                job_id=job_id,
                status=PublishStatus.FAILED,
                errors=[{"message": f"Unexpected error: {str(e)}"}],
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
            StatusResult with current status
        """
        if job_id not in self._job_tracker:
            return StatusResult(
                job_id=job_id,
                status=PublishStatus.COMPLETED,
                progress=1.0,
                channel=self.channel_code,
            )

        job = self._job_tracker[job_id]
        feed_id = job.feed_id

        if not feed_id:
            return StatusResult(
                job_id=job_id,
                status=PublishStatus.FAILED,
                errors=[{"message": "No feed ID available"}],
                channel=self.channel_code,
            )

        try:
            result = self._make_api_request(
                "GET",
                f"feeds/{feed_id}",
                params={"includeDetails": "true"},
            )

            feed_status = result.get("feedStatus", "").upper()

            status_mapping = {
                "RECEIVED": PublishStatus.PENDING,
                "INPROGRESS": PublishStatus.IN_PROGRESS,
                "PROCESSED": PublishStatus.COMPLETED,
                "ERROR": PublishStatus.FAILED,
            }

            status = status_mapping.get(feed_status, PublishStatus.IN_PROGRESS)

            items_received = result.get("itemsReceived", 0)
            items_succeeded = result.get("itemsSucceeded", 0)
            items_failed = result.get("itemsFailed", 0)

            errors = []
            for item_detail in result.get("itemDetails", {}).get("itemIngestionStatus", []):
                if item_detail.get("ingestionStatus") == "FAILURE":
                    errors.append({
                        "sku": item_detail.get("sku"),
                        "message": str(item_detail.get("ingestionErrors", [])),
                    })

            if status == PublishStatus.COMPLETED and items_failed > 0:
                status = PublishStatus.PARTIAL

            job.status = feed_status
            job.items_received = items_received
            job.items_succeeded = items_succeeded
            job.items_failed = items_failed
            job.errors = errors

            if status in (PublishStatus.COMPLETED, PublishStatus.PARTIAL, PublishStatus.FAILED):
                job.completed_at = datetime.now()

            progress = 1.0 if status in (PublishStatus.COMPLETED, PublishStatus.PARTIAL) else 0.5

            return StatusResult(
                job_id=job_id,
                status=status,
                progress=progress,
                products_total=job.items_total,
                products_processed=items_succeeded + items_failed,
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
        """Test the connection to Walmart.

        Returns:
            Dictionary with connection status
        """
        try:
            self._get_access_token()
            return {
                "success": True,
                "message": "Connection successful",
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


# =============================================================================
# Register Adapter
# =============================================================================

register_adapter("walmart", WalmartAdapter)
register_adapter("wmt", WalmartAdapter)
