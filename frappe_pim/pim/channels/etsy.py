"""
Etsy Channel Adapter

Provides a comprehensive adapter for Etsy Marketplace product syndication
using the Etsy Open API v3.

Features:
- Etsy Open API v3 integration
- OAuth 2.0 authentication with PKCE
- Comprehensive product validation
- Attribute mapping to Etsy listing format
- Listing management and inventory sync
- Taxonomy and shipping profile support

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
# Etsy-Specific Constants
# =============================================================================

class EtsyListingState(str, Enum):
    """Etsy listing state values"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    DRAFT = "draft"
    SOLD_OUT = "sold_out"
    REMOVED = "removed"


class EtsyListingType(str, Enum):
    """Etsy listing type values"""
    PHYSICAL = "physical"
    DOWNLOAD = "download"
    BOTH = "both"


class EtsyWhoMade(str, Enum):
    """Etsy who made values"""
    I_DID = "i_did"
    COLLECTIVE = "collective"
    SOMEONE_ELSE = "someone_else"


class EtsyWhenMade(str, Enum):
    """Etsy when made values"""
    MADE_TO_ORDER = "made_to_order"
    Y_2020_2024 = "2020_2024"
    Y_2010_2019 = "2010_2019"
    Y_2005_2009 = "2005_2009"
    BEFORE_2005 = "before_2005"
    Y_2000_2004 = "2000_2004"
    Y_1990S = "1990s"
    Y_1980S = "1980s"
    Y_1970S = "1970s"
    Y_1960S = "1960s"
    Y_1950S = "1950s"
    Y_1940S = "1940s"
    Y_1930S = "1930s"
    Y_1920S = "1920s"
    Y_1910S = "1910s"
    Y_1900S = "1900s"
    Y_1800S = "1800s"
    Y_1700S = "1700s"
    BEFORE_1700 = "before_1700"


# Etsy API endpoints
ETSY_API_BASE_URL = "https://openapi.etsy.com/v3"
ETSY_AUTH_URL = "https://www.etsy.com/oauth/connect"
ETSY_TOKEN_URL = "https://api.etsy.com/v3/public/oauth/token"

# Etsy rate limit configuration
# 10,000 requests per day, with burst limits
ETSY_RATE_LIMITS = {
    "default": {
        "requests_per_second": 5,
        "requests_per_minute": 100,
        "daily_limit": 10000,
    },
    "listings": {
        "requests_per_second": 3,
        "requests_per_minute": 60,
        "daily_limit": 5000,
    },
}

# Required fields for Etsy listings
ETSY_REQUIRED_FIELDS = {
    "title",
    "description",
    "price",
    "quantity",
    "taxonomy_id",
    "who_made",
    "when_made",
    "is_supply",
}

# Recommended fields
ETSY_RECOMMENDED_FIELDS = {
    "tags",
    "materials",
    "images",
    "shipping_profile_id",
    "sku",
}

# Field length limits
ETSY_FIELD_LIMITS = {
    "title": 140,
    "description": 100000,
    "sku": 32,
    "tag": 20,
    "tags_count": 13,
    "materials_count": 13,
}

# PIM to Etsy field mappings
PIM_TO_ETSY_FIELDS = {
    "item_code": "sku",
    "item_name": "title",
    "pim_title": "title",
    "pim_description": "description",
    "description": "description",
    "standard_rate": "price",
    "stock_qty": "quantity",
    "image": "images",
}


# =============================================================================
# Etsy-Specific Data Classes
# =============================================================================

@dataclass
class EtsyToken:
    """Etsy OAuth token with expiration tracking"""
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 3600
    refresh_token: str = None
    obtained_at: datetime = field(default_factory=datetime.now)

    def is_expired(self) -> bool:
        """Check if token is expired (5 min buffer)"""
        expiration = self.obtained_at + timedelta(seconds=self.expires_in - 300)
        return datetime.now() >= expiration


@dataclass
class EtsyRateLimitState:
    """Tracks Etsy rate limit state"""
    requests_made: int = 0
    requests_limit: int = 100
    window_start: datetime = field(default_factory=datetime.now)
    window_duration: int = 60
    retry_after: datetime = None
    last_request: datetime = None
    daily_requests: int = 0
    daily_limit: int = 10000
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

        limits = ETSY_RATE_LIMITS.get(self.endpoint_type, ETSY_RATE_LIMITS["default"])
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
class EtsyListingJob:
    """Tracks an Etsy listing operation"""
    job_id: str
    listing_id: int = None
    operation_type: str = "CREATE"
    status: str = "PENDING"
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime = None
    items_total: int = 0
    items_succeeded: int = 0
    items_failed: int = 0
    errors: List[Dict] = field(default_factory=list)


# =============================================================================
# Etsy Adapter
# =============================================================================

class EtsyAdapter(ChannelAdapter):
    """
    Etsy channel adapter for product syndication.

    Uses the Etsy Open API v3 for listing management with
    support for variants and inventory tracking.

    Features:
    - OAuth 2.0 with PKCE authentication
    - Listing creation and updates
    - Variant/option management
    - Inventory quantity sync
    - Taxonomy and shipping profile support
    """

    channel_code: str = "etsy"
    channel_name: str = "Etsy"

    # Rate limiting settings
    default_requests_per_minute: int = 100
    default_requests_per_second: float = 5.0
    max_retry_attempts: int = 5
    base_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 120.0

    def __init__(self, channel_doc: Any = None):
        """Initialize Etsy adapter."""
        super().__init__(channel_doc)
        self._token: Optional[EtsyToken] = None
        self._rate_limit_state: EtsyRateLimitState = None
        self._shop_id: str = None
        self._job_tracker: Dict[str, EtsyListingJob] = {}

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def shop_id(self) -> str:
        """Get the Etsy shop ID."""
        if self._shop_id:
            return self._shop_id

        self._shop_id = self.config.get("shop_id") or self.config.get("etsy_shop_id", "")
        return self._shop_id

    @property
    def rate_limit_state(self) -> EtsyRateLimitState:
        """Get current rate limit state."""
        if self._rate_limit_state is None:
            self._rate_limit_state = EtsyRateLimitState()
        return self._rate_limit_state

    # =========================================================================
    # Authentication Methods
    # =========================================================================

    def _get_etsy_credentials(self) -> Dict:
        """Get Etsy-specific credentials."""
        credentials = self.credentials

        return {
            "api_key": credentials.get("api_key") or credentials.get("keystring"),
            "access_token": credentials.get("access_token"),
            "refresh_token": credentials.get("refresh_token"),
        }

    def _get_access_token(self) -> str:
        """Get a valid OAuth access token."""
        import requests

        if self._token and not self._token.is_expired():
            return self._token.access_token

        creds = self._get_etsy_credentials()

        # If we have a valid access token, use it
        if creds.get("access_token"):
            self._token = EtsyToken(
                access_token=creds["access_token"],
                refresh_token=creds.get("refresh_token"),
            )
            return self._token.access_token

        # Try to refresh token
        if creds.get("refresh_token"):
            try:
                response = requests.post(
                    ETSY_TOKEN_URL,
                    data={
                        "grant_type": "refresh_token",
                        "client_id": creds["api_key"],
                        "refresh_token": creds["refresh_token"],
                    },
                    timeout=30,
                )

                if response.status_code == 200:
                    token_data = response.json()
                    self._token = EtsyToken(
                        access_token=token_data["access_token"],
                        refresh_token=token_data.get("refresh_token", creds["refresh_token"]),
                        expires_in=int(token_data.get("expires_in", 3600)),
                    )
                    return self._token.access_token
            except Exception:
                pass

        raise AuthenticationError(
            "Etsy access token not available or refresh failed",
            channel=self.channel_code,
        )

    def _get_auth_headers(self) -> Dict:
        """Build authentication headers for Etsy API requests."""
        access_token = self._get_access_token()
        creds = self._get_etsy_credentials()

        return {
            "Authorization": f"Bearer {access_token}",
            "x-api-key": creds.get("api_key", ""),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # =========================================================================
    # Rate Limiting Methods
    # =========================================================================

    def handle_rate_limiting(self, response: Any = None) -> None:
        """Handle Etsy rate limiting from response."""
        if response is None:
            return

        status_code = getattr(response, 'status_code', None)

        if status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 60))
            self.rate_limit_state.retry_after = datetime.now() + timedelta(seconds=retry_after)

            raise RateLimitError(
                "Etsy API rate limit exceeded",
                channel=self.channel_code,
                retry_after=retry_after,
            )

        # Parse rate limit headers
        remaining = response.headers.get("X-RateLimit-Remaining")
        if remaining:
            try:
                self.rate_limit_state.requests_made = (
                    self.rate_limit_state.requests_limit - int(remaining)
                )
            except ValueError:
                pass

    def _wait_for_rate_limit(self) -> None:
        """Wait if rate limited."""
        wait_time = self.rate_limit_state.wait_time()

        if wait_time > 0:
            if wait_time > self.max_backoff_seconds:
                raise RateLimitError(
                    f"Etsy rate limit wait time ({wait_time}s) exceeds maximum",
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
        """Make a request to the Etsy API."""
        import requests

        self.rate_limit_state.endpoint_type = endpoint_type
        self._wait_for_rate_limit()

        url = f"{ETSY_API_BASE_URL}/{endpoint}"

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
                elif method.upper() == "PATCH":
                    response = requests.patch(
                        url, headers=headers, json=data,
                        timeout=self.config.get("timeout", 30)
                    )
                elif method.upper() == "DELETE":
                    response = requests.delete(
                        url, headers=headers,
                        timeout=self.config.get("timeout", 30)
                    )
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                self.handle_rate_limiting(response)

                if response.status_code in (401, 403):
                    self._token = None
                    raise AuthenticationError(
                        f"Etsy authentication failed: HTTP {response.status_code}",
                        channel=self.channel_code,
                    )

                if response.status_code in (200, 201, 204):
                    if response.status_code == 204:
                        return {"success": True}
                    try:
                        return response.json()
                    except Exception:
                        return {"success": True}

                error_message = "Unknown error"
                try:
                    error_data = response.json()
                    if "error" in error_data:
                        error_message = str(error_data["error"])
                    elif "errors" in error_data:
                        error_message = str(error_data["errors"])
                except Exception:
                    error_message = response.text or f"HTTP {response.status_code}"

                raise PublishError(
                    f"Etsy API error: {error_message}",
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
            f"Etsy API request failed: {last_error}",
            channel=self.channel_code,
        )

    # =========================================================================
    # Validation Methods
    # =========================================================================

    def validate_product(self, product: Dict) -> ValidationResult:
        """Validate a product against Etsy's requirements."""
        errors = []
        warnings = []
        product_id = product.get("item_code", product.get("sku", "unknown"))

        # Check required fields
        for field_name in ETSY_REQUIRED_FIELDS:
            pim_field = None
            for pim_name, etsy_name in PIM_TO_ETSY_FIELDS.items():
                if etsy_name == field_name:
                    pim_field = pim_name
                    break

            value = product.get(field_name)
            if pim_field:
                value = value or product.get(pim_field)

            # Skip fields that have defaults
            if not value and field_name not in ("who_made", "when_made", "is_supply"):
                errors.append({
                    "field": field_name,
                    "message": f"Required field '{field_name}' is missing",
                    "rule": "required",
                })

        # Validate title length
        title = product.get("title") or product.get("pim_title") or product.get("item_name")
        if title:
            if len(str(title)) > ETSY_FIELD_LIMITS["title"]:
                errors.append({
                    "field": "title",
                    "message": f"Title exceeds {ETSY_FIELD_LIMITS['title']} characters",
                    "rule": "max_length",
                })
        else:
            errors.append({
                "field": "title",
                "message": "Title is required",
                "rule": "required",
            })

        # Validate description
        description = product.get("description") or product.get("pim_description")
        if not description:
            errors.append({
                "field": "description",
                "message": "Description is required for Etsy listings",
                "rule": "required",
            })

        # Validate price
        price = product.get("price") or product.get("standard_rate")
        if price is not None:
            try:
                price_val = float(price)
                if price_val < 0.20:
                    errors.append({
                        "field": "price",
                        "message": "Etsy minimum price is $0.20",
                        "rule": "min_price",
                    })
            except (ValueError, TypeError):
                errors.append({
                    "field": "price",
                    "message": "Price must be a valid number",
                    "rule": "numeric",
                })
        else:
            errors.append({
                "field": "price",
                "message": "Price is required",
                "rule": "required",
            })

        # Validate quantity
        quantity = product.get("quantity") or product.get("stock_qty")
        if quantity is not None:
            try:
                qty_val = int(quantity)
                if qty_val < 0:
                    errors.append({
                        "field": "quantity",
                        "message": "Quantity cannot be negative",
                        "rule": "non_negative",
                    })
            except (ValueError, TypeError):
                errors.append({
                    "field": "quantity",
                    "message": "Quantity must be an integer",
                    "rule": "integer",
                })

        # Validate tags
        tags = product.get("tags")
        if tags:
            tag_list = tags if isinstance(tags, list) else [t.strip() for t in str(tags).split(",")]
            if len(tag_list) > ETSY_FIELD_LIMITS["tags_count"]:
                warnings.append({
                    "field": "tags",
                    "message": f"Maximum {ETSY_FIELD_LIMITS['tags_count']} tags allowed, extras will be ignored",
                    "rule": "max_tags",
                })
            for tag in tag_list:
                if len(str(tag)) > ETSY_FIELD_LIMITS["tag"]:
                    errors.append({
                        "field": "tags",
                        "message": f"Tag '{tag[:20]}...' exceeds {ETSY_FIELD_LIMITS['tag']} characters",
                        "rule": "tag_length",
                    })

        # Check recommended fields
        for field_name in ETSY_RECOMMENDED_FIELDS:
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
        """Map PIM product attributes to Etsy format."""
        product_id = product.get("item_code", product.get("sku", "unknown"))
        mapped_data = {}
        unmapped_fields = []

        # Title (required)
        title = product.get("pim_title") or product.get("title") or product.get("item_name")
        if title:
            mapped_data["title"] = str(title)[:ETSY_FIELD_LIMITS["title"]]

        # Description (required)
        description = product.get("pim_description") or product.get("description")
        if description:
            mapped_data["description"] = str(description)

        # Price (required) - in cents for USD
        price = product.get("price") or product.get("standard_rate")
        if price is not None:
            price_val = float(price)
            mapped_data["price"] = {
                "amount": int(price_val * 100),  # Convert to cents
                "divisor": 100,
                "currency_code": product.get("currency", "USD"),
            }

        # Quantity (required)
        quantity = product.get("quantity") or product.get("stock_qty")
        if quantity is not None:
            mapped_data["quantity"] = max(0, int(quantity))
        else:
            mapped_data["quantity"] = 0

        # SKU
        sku = product.get("item_code") or product.get("sku")
        if sku:
            mapped_data["sku"] = str(sku)[:ETSY_FIELD_LIMITS["sku"]]

        # Taxonomy ID
        taxonomy_id = product.get("taxonomy_id") or product.get("etsy_taxonomy_id")
        if taxonomy_id:
            mapped_data["taxonomy_id"] = int(taxonomy_id)

        # Shipping profile ID
        shipping_profile_id = product.get("shipping_profile_id") or product.get("etsy_shipping_profile_id")
        if shipping_profile_id:
            mapped_data["shipping_profile_id"] = int(shipping_profile_id)

        # Who made (required)
        who_made = product.get("who_made", "i_did")
        try:
            mapped_data["who_made"] = EtsyWhoMade[who_made.upper()].value
        except KeyError:
            mapped_data["who_made"] = EtsyWhoMade.I_DID.value

        # When made (required)
        when_made = product.get("when_made", "made_to_order")
        try:
            mapped_data["when_made"] = EtsyWhenMade[when_made.upper().replace("-", "_")].value
        except KeyError:
            mapped_data["when_made"] = EtsyWhenMade.MADE_TO_ORDER.value

        # Is supply (required)
        is_supply = product.get("is_supply", False)
        mapped_data["is_supply"] = bool(is_supply)

        # Listing type
        listing_type = product.get("listing_type", "physical")
        try:
            mapped_data["type"] = EtsyListingType[listing_type.upper()].value
        except KeyError:
            mapped_data["type"] = EtsyListingType.PHYSICAL.value

        # Tags (max 13)
        tags = product.get("tags")
        if tags:
            if isinstance(tags, str):
                tag_list = [t.strip()[:ETSY_FIELD_LIMITS["tag"]] for t in tags.split(",") if t.strip()]
            else:
                tag_list = [str(t).strip()[:ETSY_FIELD_LIMITS["tag"]] for t in tags if t]
            mapped_data["tags"] = tag_list[:ETSY_FIELD_LIMITS["tags_count"]]

        # Materials (max 13)
        materials = product.get("materials")
        if materials:
            if isinstance(materials, str):
                mat_list = [m.strip() for m in materials.split(",") if m.strip()]
            else:
                mat_list = [str(m).strip() for m in materials if m]
            mapped_data["materials"] = mat_list[:ETSY_FIELD_LIMITS["materials_count"]]

        # Images
        images = product.get("images") or product.get("image")
        if images:
            image_urls = []
            if isinstance(images, str):
                image_urls.append(images)
            elif isinstance(images, list):
                for img in images[:10]:  # Etsy allows up to 10 images
                    if isinstance(img, str):
                        image_urls.append(img)
                    elif isinstance(img, dict):
                        url = img.get("url") or img.get("src")
                        if url:
                            image_urls.append(url)
            mapped_data["image_urls"] = image_urls

        # Track unmapped fields
        mapped_pim_fields = set(PIM_TO_ETSY_FIELDS.keys())
        mapped_pim_fields.update({
            "title", "description", "price", "quantity", "sku",
            "taxonomy_id", "etsy_taxonomy_id", "shipping_profile_id",
            "etsy_shipping_profile_id", "who_made", "when_made",
            "is_supply", "listing_type", "type", "tags", "materials",
            "images", "currency",
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
        """Generate Etsy API payload for products."""
        listings = []

        for product in products:
            listing = {
                "title": product.get("title"),
                "description": product.get("description"),
                "quantity": product.get("quantity", 0),
                "who_made": product.get("who_made", "i_did"),
                "when_made": product.get("when_made", "made_to_order"),
                "is_supply": product.get("is_supply", False),
                "type": product.get("type", "physical"),
            }

            if "price" in product:
                listing["price"] = product["price"]
            if "sku" in product:
                listing["sku"] = product["sku"]
            if "taxonomy_id" in product:
                listing["taxonomy_id"] = product["taxonomy_id"]
            if "shipping_profile_id" in product:
                listing["shipping_profile_id"] = product["shipping_profile_id"]
            if "tags" in product:
                listing["tags"] = product["tags"]
            if "materials" in product:
                listing["materials"] = product["materials"]

            listings.append(listing)

        return {
            "listings": listings,
            "_metadata": {
                "batch_id": str(uuid.uuid4()),
                "created_at": datetime.now().isoformat(),
                "product_count": len(listings),
            },
        }

    # =========================================================================
    # Publishing Methods
    # =========================================================================

    def publish(self, products: List[Dict]) -> PublishResult:
        """Publish products to Etsy."""
        job_id = str(uuid.uuid4())
        errors = []
        products_succeeded = 0
        products_failed = 0
        listing_ids = []

        try:
            if not self.shop_id:
                return PublishResult(
                    success=False,
                    job_id=job_id,
                    status=PublishStatus.FAILED,
                    errors=[{"message": "Etsy shop ID not configured"}],
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

            # Create listings one by one
            for product in mapped_products:
                try:
                    result = self._make_api_request(
                        "POST",
                        f"application/shops/{self.shop_id}/listings",
                        data=product,
                        endpoint_type="listings",
                    )

                    listing_id = result.get("listing_id")
                    if listing_id:
                        listing_ids.append(str(listing_id))
                        products_succeeded += 1
                    else:
                        products_failed += 1
                        errors.append({
                            "sku": product.get("sku"),
                            "message": "No listing ID returned",
                        })

                except Exception as e:
                    products_failed += 1
                    errors.append({
                        "sku": product.get("sku"),
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
                external_id=",".join(listing_ids) if listing_ids else None,
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
        """Test the connection to Etsy."""
        try:
            if not self.shop_id:
                return {
                    "success": False,
                    "message": "Etsy shop ID is not configured",
                }

            result = self._make_api_request(
                "GET",
                f"application/shops/{self.shop_id}",
            )

            shop_name = result.get("shop_name", "Unknown")

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

    def get_taxonomy(self) -> List[Dict]:
        """Retrieve Etsy taxonomy (categories)."""
        try:
            result = self._make_api_request("GET", "application/seller-taxonomy/nodes")
            return result.get("results", [])
        except Exception:
            return []


# =============================================================================
# Register Adapter
# =============================================================================

register_adapter("etsy", EtsyAdapter)
