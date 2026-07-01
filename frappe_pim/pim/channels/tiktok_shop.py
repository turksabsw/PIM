"""
TikTok Shop Channel Adapter

Provides a comprehensive adapter for TikTok Shop product syndication
using the TikTok Shop Open Platform API.

Features:
- TikTok Shop Open Platform API integration
- App key and secret authentication with signatures
- Comprehensive product validation
- Attribute mapping to TikTok Shop format
- Product and inventory management
- Category and brand support

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
import hmac
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
# TikTok Shop-Specific Constants
# =============================================================================

class TikTokProductStatus(str, Enum):
    """TikTok Shop product status values"""
    PENDING = 0  # Pending review
    LIVE = 1  # Live
    SUSPENDED = 2  # Suspended
    DELETED = 3  # Deleted
    DRAFT = 4  # Draft


class TikTokWarehouseType(str, Enum):
    """TikTok Shop warehouse types"""
    SELLER = "SELLER"
    TIKTOK = "TIKTOK_FULFILLMENT"


class TikTokProductCondition(str, Enum):
    """TikTok Shop product condition"""
    NEW = "NEW"
    USED = "USED"
    REFURBISHED = "REFURBISHED"


# TikTok Shop API endpoints by region
TIKTOK_API_ENDPOINTS = {
    "US": "https://open-api.tiktokglobalshop.com",
    "UK": "https://open-api.tiktokglobalshop.com",
    "ID": "https://open-api.tiktokglobalshop.com",
    "MY": "https://open-api.tiktokglobalshop.com",
    "TH": "https://open-api.tiktokglobalshop.com",
    "VN": "https://open-api.tiktokglobalshop.com",
    "PH": "https://open-api.tiktokglobalshop.com",
    "SG": "https://open-api.tiktokglobalshop.com",
}

# TikTok Shop rate limit configuration
TIKTOK_RATE_LIMITS = {
    "default": {
        "requests_per_second": 10,
        "requests_per_minute": 600,
        "daily_limit": 50000,
    },
    "products": {
        "requests_per_second": 5,
        "requests_per_minute": 300,
        "daily_limit": 20000,
    },
}

# Required fields for TikTok Shop products
TIKTOK_REQUIRED_FIELDS = {
    "product_name",
    "description",
    "category_id",
    "images",
    "skus",  # At least one SKU with price and quantity
}

# Recommended fields
TIKTOK_RECOMMENDED_FIELDS = {
    "brand_id",
    "package_weight",
    "package_dimensions",
    "product_attributes",
    "certifications",
}

# Field length limits
TIKTOK_FIELD_LIMITS = {
    "product_name": 255,
    "description": 10000,
    "sku_seller_sku": 100,
}

# PIM to TikTok field mappings
PIM_TO_TIKTOK_FIELDS = {
    "item_code": "seller_sku",
    "item_name": "product_name",
    "pim_title": "product_name",
    "pim_description": "description",
    "description": "description",
    "brand": "brand_id",
    "standard_rate": "original_price",
    "barcode": "identifier_code",
    "gtin": "identifier_code",
    "stock_qty": "quantity",
    "image": "images",
    "weight_per_unit": "package_weight",
}


# =============================================================================
# TikTok Shop-Specific Data Classes
# =============================================================================

@dataclass
class TikTokToken:
    """TikTok Shop access token with expiration tracking"""
    access_token: str
    refresh_token: str = None
    expires_in: int = 86400  # 24 hours
    obtained_at: datetime = field(default_factory=datetime.now)

    def is_expired(self) -> bool:
        """Check if token is expired (1 hour buffer)"""
        expiration = self.obtained_at + timedelta(seconds=self.expires_in - 3600)
        return datetime.now() >= expiration


@dataclass
class TikTokRateLimitState:
    """Tracks TikTok Shop rate limit state"""
    requests_made: int = 0
    requests_limit: int = 600
    window_start: datetime = field(default_factory=datetime.now)
    window_duration: int = 60
    retry_after: datetime = None
    last_request: datetime = None
    daily_requests: int = 0
    daily_limit: int = 50000
    day_start: datetime = field(default_factory=datetime.now)
    endpoint_type: str = "default"

    def is_limited(self) -> bool:
        """Check if currently rate limited"""
        if self.retry_after and datetime.now() < self.retry_after:
            return True

        if datetime.now().date() > self.day_start.date():
            self.daily_requests = 0
            self.day_start = datetime.now()

        if datetime.now() > self.window_start + timedelta(seconds=self.window_duration):
            self.requests_made = 0
            self.window_start = datetime.now()
            return False

        limits = TIKTOK_RATE_LIMITS.get(self.endpoint_type, TIKTOK_RATE_LIMITS["default"])
        return (self.requests_made >= limits["requests_per_minute"] or
                self.daily_requests >= limits["daily_limit"])

    def record_request(self) -> None:
        """Record a request"""
        now = datetime.now()

        if now.date() > self.day_start.date():
            self.daily_requests = 0
            self.day_start = now

        if now > self.window_start + timedelta(seconds=self.window_duration):
            self.requests_made = 0
            self.window_start = now

        self.requests_made += 1
        self.daily_requests += 1
        self.last_request = now

    def wait_time(self) -> float:
        """Calculate wait time"""
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
class TikTokProductJob:
    """Tracks a TikTok Shop product operation"""
    job_id: str
    product_id: str = None
    operation_type: str = "CREATE"
    status: str = "PENDING"
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime = None
    items_total: int = 0
    items_succeeded: int = 0
    items_failed: int = 0
    errors: List[Dict] = field(default_factory=list)


# =============================================================================
# TikTok Shop Adapter
# =============================================================================

class TikTokShopAdapter(ChannelAdapter):
    """
    TikTok Shop channel adapter for product syndication.

    Uses the TikTok Shop Open Platform API for product management
    with support for multi-region operations.

    Features:
    - App key/secret authentication with HMAC signatures
    - Product creation and updates
    - SKU and inventory management
    - Category and attribute support
    - Multi-region marketplace support
    """

    channel_code: str = "tiktok_shop"
    channel_name: str = "TikTok Shop"

    # Rate limiting settings
    default_requests_per_minute: int = 600
    default_requests_per_second: float = 10.0
    max_retry_attempts: int = 5
    base_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 120.0

    # API version
    api_version: str = "202309"

    def __init__(self, channel_doc: Any = None):
        """Initialize TikTok Shop adapter."""
        super().__init__(channel_doc)
        self._token: Optional[TikTokToken] = None
        self._rate_limit_state: TikTokRateLimitState = None
        self._shop_id: str = None
        self._region: str = "US"
        self._job_tracker: Dict[str, TikTokProductJob] = {}

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def api_base_url(self) -> str:
        """Get the TikTok Shop API base URL."""
        region = self.config.get("region", "US").upper()
        return TIKTOK_API_ENDPOINTS.get(region, TIKTOK_API_ENDPOINTS["US"])

    @property
    def shop_id(self) -> str:
        """Get the TikTok Shop ID."""
        if self._shop_id:
            return self._shop_id

        self._shop_id = self.config.get("shop_id") or self.config.get("seller_id", "")
        return self._shop_id

    @property
    def rate_limit_state(self) -> TikTokRateLimitState:
        """Get current rate limit state."""
        if self._rate_limit_state is None:
            self._rate_limit_state = TikTokRateLimitState()
        return self._rate_limit_state

    # =========================================================================
    # Authentication Methods
    # =========================================================================

    def _get_tiktok_credentials(self) -> Dict:
        """Get TikTok Shop-specific credentials."""
        credentials = self.credentials

        return {
            "app_key": credentials.get("api_key") or credentials.get("app_key"),
            "app_secret": credentials.get("api_secret") or credentials.get("app_secret"),
            "access_token": credentials.get("access_token"),
        }

    def _generate_signature(self, path: str, params: Dict, body: str = "") -> str:
        """Generate HMAC-SHA256 signature for TikTok API.

        Args:
            path: API path
            params: Query parameters
            body: Request body as string

        Returns:
            Signature string
        """
        creds = self._get_tiktok_credentials()
        app_secret = creds.get("app_secret", "")

        # Sort parameters alphabetically
        sorted_params = sorted(params.items())
        param_string = "".join(f"{k}{v}" for k, v in sorted_params)

        # Build sign string
        sign_string = f"{app_secret}{path}{param_string}{body}{app_secret}"

        # Generate HMAC-SHA256
        signature = hmac.new(
            app_secret.encode(),
            sign_string.encode(),
            hashlib.sha256
        ).hexdigest()

        return signature

    def _get_auth_params(self, path: str, body: str = "") -> Dict:
        """Get authentication parameters for API requests."""
        creds = self._get_tiktok_credentials()

        if not creds.get("app_key"):
            raise AuthenticationError(
                "TikTok Shop app_key is required",
                channel=self.channel_code,
            )

        timestamp = str(int(time.time()))

        params = {
            "app_key": creds["app_key"],
            "timestamp": timestamp,
            "version": self.api_version,
        }

        if creds.get("access_token"):
            params["access_token"] = creds["access_token"]

        if self.shop_id:
            params["shop_id"] = self.shop_id

        # Generate signature
        params["sign"] = self._generate_signature(path, params, body)

        return params

    def _get_auth_headers(self) -> Dict:
        """Build headers for TikTok API requests."""
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # =========================================================================
    # Rate Limiting Methods
    # =========================================================================

    def handle_rate_limiting(self, response: Any = None) -> None:
        """Handle TikTok rate limiting from response."""
        if response is None:
            return

        status_code = getattr(response, 'status_code', None)

        if status_code == 429:
            retry_after = 60
            self.rate_limit_state.retry_after = datetime.now() + timedelta(seconds=retry_after)

            raise RateLimitError(
                "TikTok Shop API rate limit exceeded",
                channel=self.channel_code,
                retry_after=retry_after,
            )

        # Check for rate limit error in response
        if isinstance(response, dict):
            code = response.get("code")
            if code == 3:  # Rate limit exceeded
                self.rate_limit_state.retry_after = datetime.now() + timedelta(seconds=60)
                raise RateLimitError(
                    "TikTok Shop API rate limit exceeded",
                    channel=self.channel_code,
                    retry_after=60,
                )

    def _wait_for_rate_limit(self) -> None:
        """Wait if rate limited."""
        wait_time = self.rate_limit_state.wait_time()

        if wait_time > 0:
            if wait_time > self.max_backoff_seconds:
                raise RateLimitError(
                    f"TikTok rate limit wait time ({wait_time}s) exceeds maximum",
                    channel=self.channel_code,
                    retry_after=int(wait_time),
                )
            time.sleep(wait_time)

    # =========================================================================
    # API Request Methods
    # =========================================================================

    def _make_api_request(self, method: str, path: str,
                          data: Dict = None, params: Dict = None,
                          endpoint_type: str = "default") -> Dict:
        """Make a request to the TikTok Shop API."""
        import requests

        self.rate_limit_state.endpoint_type = endpoint_type
        self._wait_for_rate_limit()

        body = json.dumps(data) if data else ""

        auth_params = self._get_auth_params(path, body)
        if params:
            auth_params.update(params)

        url = f"{self.api_base_url}{path}"

        last_error = None

        for attempt in range(self.max_retry_attempts):
            try:
                self.rate_limit_state.record_request()
                headers = self._get_auth_headers()

                if method.upper() == "GET":
                    response = requests.get(
                        url, headers=headers, params=auth_params,
                        timeout=self.config.get("timeout", 30)
                    )
                elif method.upper() == "POST":
                    response = requests.post(
                        url, headers=headers, params=auth_params, data=body,
                        timeout=self.config.get("timeout", 60)
                    )
                elif method.upper() == "PUT":
                    response = requests.put(
                        url, headers=headers, params=auth_params, data=body,
                        timeout=self.config.get("timeout", 30)
                    )
                elif method.upper() == "DELETE":
                    response = requests.delete(
                        url, headers=headers, params=auth_params,
                        timeout=self.config.get("timeout", 30)
                    )
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                self.handle_rate_limiting(response)

                result = response.json()

                # Check for error in response
                code = result.get("code")
                if code != 0:
                    message = result.get("message", "Unknown error")

                    if code in (1001, 1002):  # Auth errors
                        raise AuthenticationError(
                            f"TikTok authentication failed: {message}",
                            channel=self.channel_code,
                        )

                    if code == 3:  # Rate limit
                        self.handle_rate_limiting(result)

                    raise PublishError(
                        f"TikTok Shop API error: {message}",
                        channel=self.channel_code,
                    )

                return result.get("data", {})

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
            f"TikTok Shop API request failed: {last_error}",
            channel=self.channel_code,
        )

    # =========================================================================
    # Validation Methods
    # =========================================================================

    def validate_product(self, product: Dict) -> ValidationResult:
        """Validate a product against TikTok Shop requirements."""
        errors = []
        warnings = []
        product_id = product.get("item_code", product.get("seller_sku", "unknown"))

        # Check required fields
        for field_name in TIKTOK_REQUIRED_FIELDS:
            pim_field = None
            for pim_name, tt_name in PIM_TO_TIKTOK_FIELDS.items():
                if tt_name == field_name:
                    pim_field = pim_name
                    break

            value = product.get(field_name)
            if pim_field:
                value = value or product.get(pim_field)

            if not value and field_name not in ("skus",):
                errors.append({
                    "field": field_name,
                    "message": f"Required field '{field_name}' is missing",
                    "rule": "required",
                })

        # Validate product name
        name = product.get("product_name") or product.get("pim_title") or product.get("item_name")
        if name:
            if len(str(name)) > TIKTOK_FIELD_LIMITS["product_name"]:
                errors.append({
                    "field": "product_name",
                    "message": f"Product name exceeds {TIKTOK_FIELD_LIMITS['product_name']} characters",
                    "rule": "max_length",
                })
        else:
            errors.append({
                "field": "product_name",
                "message": "Product name is required",
                "rule": "required",
            })

        # Validate description
        description = product.get("description") or product.get("pim_description")
        if not description:
            errors.append({
                "field": "description",
                "message": "Description is required for TikTok Shop",
                "rule": "required",
            })

        # Validate category_id
        category_id = product.get("category_id") or product.get("tiktok_category_id")
        if not category_id:
            errors.append({
                "field": "category_id",
                "message": "Category ID is required for TikTok Shop",
                "rule": "required",
            })

        # Validate price
        price = product.get("original_price") or product.get("standard_rate") or product.get("price")
        if price is not None:
            try:
                price_val = float(price)
                if price_val <= 0:
                    errors.append({
                        "field": "original_price",
                        "message": "Price must be greater than 0",
                        "rule": "positive_price",
                    })
            except (ValueError, TypeError):
                errors.append({
                    "field": "original_price",
                    "message": "Price must be a valid number",
                    "rule": "numeric",
                })
        else:
            errors.append({
                "field": "original_price",
                "message": "Price is required",
                "rule": "required",
            })

        # Validate images
        images = product.get("images") or product.get("image")
        if not images:
            errors.append({
                "field": "images",
                "message": "At least one product image is required",
                "rule": "required",
            })

        # Check recommended fields
        for field_name in TIKTOK_RECOMMENDED_FIELDS:
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
        """Map PIM product attributes to TikTok Shop format."""
        product_id = product.get("item_code", product.get("seller_sku", "unknown"))
        mapped_data = {}
        unmapped_fields = []

        # Product name (required)
        name = product.get("pim_title") or product.get("product_name") or product.get("item_name")
        if name:
            mapped_data["product_name"] = str(name)[:TIKTOK_FIELD_LIMITS["product_name"]]

        # Description (required)
        description = product.get("pim_description") or product.get("description")
        if description:
            mapped_data["description"] = str(description)[:TIKTOK_FIELD_LIMITS["description"]]

        # Category ID (required)
        category_id = product.get("category_id") or product.get("tiktok_category_id")
        if category_id:
            mapped_data["category_id"] = str(category_id)

        # Brand ID
        brand_id = product.get("brand_id") or product.get("tiktok_brand_id")
        if brand_id:
            mapped_data["brand_id"] = str(brand_id)

        # Images (required)
        images = product.get("images") or product.get("image")
        if images:
            image_list = []
            if isinstance(images, str):
                image_list.append({"url": images})
            elif isinstance(images, list):
                for img in images[:9]:  # Max 9 images
                    if isinstance(img, str):
                        image_list.append({"url": img})
                    elif isinstance(img, dict):
                        url = img.get("url") or img.get("src")
                        if url:
                            image_list.append({"url": url})
            mapped_data["images"] = image_list

        # SKU information
        sku = product.get("item_code") or product.get("seller_sku") or product.get("sku")
        price = product.get("original_price") or product.get("standard_rate") or product.get("price")
        quantity = product.get("quantity") or product.get("stock_qty")

        sku_data = {}

        if sku:
            sku_data["seller_sku"] = str(sku)[:TIKTOK_FIELD_LIMITS["sku_seller_sku"]]

        if price is not None:
            # TikTok Shop expects price in cents
            sku_data["original_price"] = str(int(float(price) * 100))

        if quantity is not None:
            sku_data["quantity"] = max(0, int(quantity))

        # Identifier code (GTIN/barcode)
        gtin = product.get("identifier_code") or product.get("gtin") or product.get("barcode")
        if gtin:
            sku_data["identifier_code"] = str(gtin).strip()

        if sku_data:
            mapped_data["skus"] = [sku_data]

        # Package weight
        weight = product.get("package_weight") or product.get("weight_per_unit")
        if weight is not None:
            mapped_data["package_weight"] = {
                "value": str(float(weight)),
                "unit": product.get("weight_unit", "KILOGRAM").upper(),
            }

        # Package dimensions
        length = product.get("package_length")
        width = product.get("package_width")
        height = product.get("package_height")
        if length and width and height:
            mapped_data["package_dimensions"] = {
                "length": str(float(length)),
                "width": str(float(width)),
                "height": str(float(height)),
                "unit": product.get("dimension_unit", "CENTIMETER").upper(),
            }

        # Product attributes
        attributes = product.get("product_attributes") or product.get("tiktok_attributes")
        if attributes and isinstance(attributes, list):
            mapped_data["product_attributes"] = attributes

        # Track unmapped fields
        mapped_pim_fields = set(PIM_TO_TIKTOK_FIELDS.keys())
        mapped_pim_fields.update({
            "product_name", "description", "category_id", "tiktok_category_id",
            "brand_id", "tiktok_brand_id", "images", "seller_sku", "sku",
            "original_price", "price", "quantity", "stock_qty",
            "identifier_code", "gtin", "barcode", "package_weight",
            "weight_unit", "package_length", "package_width", "package_height",
            "dimension_unit", "product_attributes", "tiktok_attributes",
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
        """Generate TikTok Shop API payload for products."""
        return {
            "products": products,
            "_metadata": {
                "batch_id": str(uuid.uuid4()),
                "created_at": datetime.now().isoformat(),
                "product_count": len(products),
            },
        }

    # =========================================================================
    # Publishing Methods
    # =========================================================================

    def publish(self, products: List[Dict]) -> PublishResult:
        """Publish products to TikTok Shop."""
        job_id = str(uuid.uuid4())
        errors = []
        products_succeeded = 0
        products_failed = 0
        product_ids = []

        try:
            if not self.shop_id:
                return PublishResult(
                    success=False,
                    job_id=job_id,
                    status=PublishStatus.FAILED,
                    errors=[{"message": "TikTok Shop ID not configured"}],
                    channel=self.channel_code,
                )

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

            # Create products one by one
            for product in mapped_products:
                try:
                    result = self._make_api_request(
                        "POST",
                        "/api/products",
                        data=product,
                        endpoint_type="products",
                    )

                    product_id = result.get("product_id")
                    if product_id:
                        product_ids.append(str(product_id))
                        products_succeeded += 1
                    else:
                        products_failed += 1
                        errors.append({
                            "sku": product.get("skus", [{}])[0].get("seller_sku"),
                            "message": "No product ID returned",
                        })

                except Exception as e:
                    products_failed += 1
                    errors.append({
                        "sku": product.get("skus", [{}])[0].get("seller_sku"),
                        "message": str(e),
                    })

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
                "products_succeeded": products_succeeded,
                "products_failed": products_failed,
            })

            return PublishResult(
                success=success,
                job_id=job_id,
                status=status,
                products_submitted=len(products),
                products_succeeded=products_succeeded,
                products_failed=products_failed,
                errors=errors,
                channel=self.channel_code,
                external_id=",".join(product_ids) if product_ids else None,
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
        """Check the status of a publish job."""
        if job_id in self._job_tracker:
            job = self._job_tracker[job_id]
            return StatusResult(
                job_id=job_id,
                status=PublishStatus.COMPLETED if job.status == "COMPLETED" else PublishStatus.FAILED,
                progress=1.0,
                products_total=job.items_total,
                products_processed=job.items_succeeded + job.items_failed,
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
        """Test the connection to TikTok Shop."""
        try:
            if not self.shop_id:
                return {
                    "success": False,
                    "message": "TikTok Shop ID is not configured",
                }

            result = self._make_api_request(
                "GET",
                "/api/shops",
            )

            shops = result.get("shops", [])
            shop_name = shops[0].get("shop_name") if shops else "Unknown"

            return {
                "success": True,
                "message": "Connection successful",
                "shop_id": self.shop_id,
                "shop_name": shop_name,
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

    def get_categories(self) -> List[Dict]:
        """Retrieve TikTok Shop categories."""
        try:
            result = self._make_api_request("GET", "/api/products/categories")
            return result.get("categories", [])
        except Exception:
            return []

    def get_brands(self, category_id: str = None) -> List[Dict]:
        """Retrieve TikTok Shop brands."""
        try:
            params = {}
            if category_id:
                params["category_id"] = category_id

            result = self._make_api_request(
                "GET",
                "/api/products/brands",
                params=params,
            )
            return result.get("brands", [])
        except Exception:
            return []


# =============================================================================
# Register Adapter
# =============================================================================

register_adapter("tiktok_shop", TikTokShopAdapter)
register_adapter("tiktok", TikTokShopAdapter)
register_adapter("tt_shop", TikTokShopAdapter)
