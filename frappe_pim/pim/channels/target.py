"""
Target Plus Channel Adapter

Provides a comprehensive adapter for Target Plus Marketplace product syndication
using the Target Partners API.

Features:
- Target Partners API integration
- OAuth 2.0 authentication
- Comprehensive product validation against Target requirements
- Attribute mapping to Target product format
- Item feed submission with async status checking
- Inventory and pricing management

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
# Target-Specific Constants
# =============================================================================

class TargetItemStatus(str, Enum):
    """Target item status values"""
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    PENDING = "PENDING"
    REJECTED = "REJECTED"


class TargetFulfillmentType(str, Enum):
    """Target fulfillment types"""
    SELLER = "SELLER_FULFILLED"
    TARGET = "TARGET_FULFILLED"


class TargetCondition(str, Enum):
    """Target item condition types"""
    NEW = "NEW"
    REFURBISHED = "REFURBISHED"
    OPEN_BOX = "OPEN_BOX"


# Target API endpoints
TARGET_API_BASE_URL = "https://api.target.com/partners/v1"
TARGET_SANDBOX_URL = "https://api-sandbox.target.com/partners/v1"
TARGET_AUTH_URL = "https://oauth.target.com/v1/token"

# Target rate limit configuration
TARGET_RATE_LIMITS = {
    "default": {
        "requests_per_second": 10,
        "requests_per_minute": 600,
        "burst_limit": 20,
    },
    "items": {
        "requests_per_second": 5,
        "requests_per_minute": 300,
        "burst_limit": 10,
    },
    "feeds": {
        "requests_per_second": 2,
        "requests_per_minute": 60,
        "burst_limit": 5,
    },
}

# Required fields for Target products
TARGET_REQUIRED_FIELDS = {
    "tcin",  # Target Item Number
    "title",
    "description",
    "brand",
    "price",
    "upc",
}

# Recommended fields
TARGET_RECOMMENDED_FIELDS = {
    "images",
    "category",
    "item_type",
    "item_subtype",
    "shipping_weight",
    "dimensions",
}

# Field length limits
TARGET_FIELD_LIMITS = {
    "title": 200,
    "description": 4000,
    "brand": 100,
    "tcin": 20,
}

# PIM to Target field mappings
PIM_TO_TARGET_FIELDS = {
    "item_code": "partner_sku",
    "item_name": "title",
    "pim_title": "title",
    "pim_description": "description",
    "description": "description",
    "brand": "brand",
    "standard_rate": "price",
    "barcode": "upc",
    "gtin": "upc",
    "weight_per_unit": "shipping_weight",
    "image": "images",
    "item_group": "category",
}


# =============================================================================
# Target-Specific Data Classes
# =============================================================================

@dataclass
class TargetToken:
    """Target OAuth token with expiration tracking"""
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 3600
    obtained_at: datetime = field(default_factory=datetime.now)

    def is_expired(self) -> bool:
        """Check if token is expired (5 min buffer)"""
        expiration = self.obtained_at + timedelta(seconds=self.expires_in - 300)
        return datetime.now() >= expiration


@dataclass
class TargetRateLimitState:
    """Tracks Target rate limit state"""
    requests_made: int = 0
    requests_limit: int = 600
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

        limits = TARGET_RATE_LIMITS.get(self.endpoint_type, TARGET_RATE_LIMITS["default"])
        return (self.requests_made >= limits["requests_per_minute"] or
                self.burst_count >= limits["burst_limit"])

    def record_request(self) -> None:
        """Record a request"""
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
        """Calculate wait time"""
        if self.retry_after:
            delta = self.retry_after - datetime.now()
            if delta.total_seconds() > 0:
                return delta.total_seconds()

        if self.is_limited():
            limits = TARGET_RATE_LIMITS.get(self.endpoint_type, TARGET_RATE_LIMITS["default"])
            if self.burst_count >= limits["burst_limit"]:
                burst_end = self.burst_window_start + timedelta(seconds=1)
                delta = burst_end - datetime.now()
                return max(0, delta.total_seconds())

            window_end = self.window_start + timedelta(seconds=self.window_duration)
            delta = window_end - datetime.now()
            return max(0, delta.total_seconds())

        return 0


@dataclass
class TargetFeedJob:
    """Tracks a Target feed job"""
    job_id: str
    feed_id: str = None
    feed_type: str = "ITEM"
    status: str = "SUBMITTED"
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime = None
    items_total: int = 0
    items_succeeded: int = 0
    items_failed: int = 0
    errors: List[Dict] = field(default_factory=list)


# =============================================================================
# Target Adapter
# =============================================================================

class TargetAdapter(ChannelAdapter):
    """
    Target Plus channel adapter for product syndication.

    Uses the Target Partners API for product management with
    support for feed-based bulk operations.

    Features:
    - OAuth 2.0 authentication
    - Item feed submission
    - Async feed status checking
    - Inventory and price management
    - Category and attribute mapping
    """

    channel_code: str = "target"
    channel_name: str = "Target Plus"

    # Rate limiting settings
    default_requests_per_minute: int = 600
    default_requests_per_second: float = 10.0
    max_retry_attempts: int = 5
    base_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 120.0

    def __init__(self, channel_doc: Any = None):
        """Initialize Target adapter."""
        super().__init__(channel_doc)
        self._token: Optional[TargetToken] = None
        self._rate_limit_state: TargetRateLimitState = None
        self._seller_id: str = None
        self._job_tracker: Dict[str, TargetFeedJob] = {}

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def api_base_url(self) -> str:
        """Get the Target API base URL."""
        if self.config.get("use_sandbox"):
            return TARGET_SANDBOX_URL
        return TARGET_API_BASE_URL

    @property
    def seller_id(self) -> str:
        """Get the Target seller ID."""
        if self._seller_id:
            return self._seller_id

        self._seller_id = self.config.get("seller_id") or self.config.get("partner_id", "")
        return self._seller_id

    @property
    def rate_limit_state(self) -> TargetRateLimitState:
        """Get current rate limit state."""
        if self._rate_limit_state is None:
            self._rate_limit_state = TargetRateLimitState()
        return self._rate_limit_state

    # =========================================================================
    # Authentication Methods
    # =========================================================================

    def _get_target_credentials(self) -> Dict:
        """Get Target-specific credentials."""
        credentials = self.credentials

        return {
            "client_id": credentials.get("api_key") or credentials.get("client_id"),
            "client_secret": credentials.get("api_secret") or credentials.get("client_secret"),
        }

    def _get_access_token(self) -> str:
        """Get a valid OAuth access token."""
        import requests

        if self._token and not self._token.is_expired():
            return self._token.access_token

        creds = self._get_target_credentials()

        if not creds.get("client_id") or not creds.get("client_secret"):
            raise AuthenticationError(
                "Target client_id and client_secret are required",
                channel=self.channel_code,
            )

        auth_string = f"{creds['client_id']}:{creds['client_secret']}"
        encoded = base64.b64encode(auth_string.encode()).decode()

        headers = {
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        try:
            response = requests.post(
                TARGET_AUTH_URL,
                headers=headers,
                data={"grant_type": "client_credentials"},
                timeout=30,
            )

            if response.status_code != 200:
                raise AuthenticationError(
                    f"Target OAuth failed: {response.status_code}",
                    channel=self.channel_code,
                )

            token_data = response.json()
            self._token = TargetToken(
                access_token=token_data["access_token"],
                expires_in=int(token_data.get("expires_in", 3600)),
            )

            return self._token.access_token

        except requests.exceptions.RequestException as e:
            raise AuthenticationError(
                f"Failed to connect to Target OAuth: {str(e)}",
                channel=self.channel_code,
            )

    def _get_auth_headers(self) -> Dict:
        """Build authentication headers for Target API requests."""
        access_token = self._get_access_token()

        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # =========================================================================
    # Rate Limiting Methods
    # =========================================================================

    def handle_rate_limiting(self, response: Any = None) -> None:
        """Handle Target rate limiting from response."""
        if response is None:
            return

        status_code = getattr(response, 'status_code', None)

        if status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 60))
            self.rate_limit_state.retry_after = datetime.now() + timedelta(seconds=retry_after)

            raise RateLimitError(
                "Target API rate limit exceeded",
                channel=self.channel_code,
                retry_after=retry_after,
            )

    def _wait_for_rate_limit(self) -> None:
        """Wait if rate limited."""
        wait_time = self.rate_limit_state.wait_time()

        if wait_time > 0:
            if wait_time > self.max_backoff_seconds:
                raise RateLimitError(
                    f"Target rate limit wait time ({wait_time}s) exceeds maximum",
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
        """Make a request to the Target API."""
        import requests

        self.rate_limit_state.endpoint_type = endpoint_type
        self._wait_for_rate_limit()

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
                        f"Target authentication failed: HTTP {response.status_code}",
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
                    f"Target API error: {error_message}",
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
            f"Target API request failed: {last_error}",
            channel=self.channel_code,
        )

    # =========================================================================
    # Validation Methods
    # =========================================================================

    def validate_product(self, product: Dict) -> ValidationResult:
        """Validate a product against Target's requirements."""
        errors = []
        warnings = []
        product_id = product.get("item_code", product.get("partner_sku", "unknown"))

        # Check required fields
        for field_name in TARGET_REQUIRED_FIELDS:
            pim_field = None
            for pim_name, target_name in PIM_TO_TARGET_FIELDS.items():
                if target_name == field_name:
                    pim_field = pim_name
                    break

            value = product.get(field_name)
            if pim_field:
                value = value or product.get(pim_field)

            if not value and field_name not in ("tcin",):  # TCIN may be assigned
                errors.append({
                    "field": field_name,
                    "message": f"Required field '{field_name}' is missing",
                    "rule": "required",
                })

        # Validate UPC
        upc = product.get("upc") or product.get("barcode") or product.get("gtin")
        if upc:
            upc_str = str(upc).strip()
            if len(upc_str) not in (12, 13, 14):
                errors.append({
                    "field": "upc",
                    "message": "UPC must be 12, 13, or 14 digits",
                    "rule": "upc_format",
                })
        else:
            errors.append({
                "field": "upc",
                "message": "UPC is required for Target listings",
                "rule": "required",
            })

        # Validate title
        title = product.get("title") or product.get("pim_title") or product.get("item_name")
        if title:
            if len(str(title)) > TARGET_FIELD_LIMITS["title"]:
                errors.append({
                    "field": "title",
                    "message": f"Title exceeds {TARGET_FIELD_LIMITS['title']} characters",
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
        for field_name in TARGET_RECOMMENDED_FIELDS:
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
        """Map PIM product attributes to Target format."""
        product_id = product.get("item_code", product.get("partner_sku", "unknown"))
        mapped_data = {}
        unmapped_fields = []

        # Partner SKU
        sku = product.get("item_code") or product.get("partner_sku")
        if sku:
            mapped_data["partner_sku"] = str(sku)

        # TCIN (if available)
        tcin = product.get("tcin") or product.get("target_tcin")
        if tcin:
            mapped_data["tcin"] = str(tcin)[:TARGET_FIELD_LIMITS["tcin"]]

        # Title
        title = product.get("pim_title") or product.get("title") or product.get("item_name")
        if title:
            mapped_data["title"] = str(title)[:TARGET_FIELD_LIMITS["title"]]

        # Description
        description = product.get("pim_description") or product.get("description")
        if description:
            mapped_data["description"] = str(description)[:TARGET_FIELD_LIMITS["description"]]

        # Brand
        brand = product.get("brand")
        if brand:
            mapped_data["brand"] = str(brand)[:TARGET_FIELD_LIMITS["brand"]]

        # UPC
        upc = product.get("upc") or product.get("barcode") or product.get("gtin")
        if upc:
            mapped_data["upc"] = str(upc).strip()

        # Price
        price = product.get("price") or product.get("standard_rate")
        if price is not None:
            mapped_data["price"] = {
                "value": float(price),
                "currency": product.get("currency", "USD"),
            }

        # Quantity
        quantity = product.get("quantity") or product.get("stock_qty")
        if quantity is not None:
            mapped_data["quantity"] = max(0, int(quantity))
        else:
            mapped_data["quantity"] = 0

        # Category
        category = product.get("category") or product.get("item_group")
        if category:
            mapped_data["category"] = str(category)

        # Condition
        condition = product.get("condition", "NEW")
        try:
            mapped_data["condition"] = TargetCondition[condition.upper().replace(" ", "_")].value
        except KeyError:
            mapped_data["condition"] = TargetCondition.NEW.value

        # Fulfillment type
        fulfillment = product.get("fulfillment_type", "SELLER_FULFILLED")
        try:
            mapped_data["fulfillment_type"] = TargetFulfillmentType[fulfillment.upper().replace("_FULFILLED", "")].value
        except KeyError:
            mapped_data["fulfillment_type"] = TargetFulfillmentType.SELLER.value

        # Images
        images = product.get("images") or product.get("image")
        if images:
            image_urls = []
            if isinstance(images, str):
                image_urls.append({"url": images, "type": "PRIMARY"})
            elif isinstance(images, list):
                for i, img in enumerate(images[:8]):
                    if isinstance(img, str):
                        img_type = "PRIMARY" if i == 0 else "ALTERNATE"
                        image_urls.append({"url": img, "type": img_type})
                    elif isinstance(img, dict):
                        url = img.get("url") or img.get("src")
                        if url:
                            img_type = img.get("type", "PRIMARY" if i == 0 else "ALTERNATE")
                            image_urls.append({"url": url, "type": img_type})
            mapped_data["images"] = image_urls

        # Shipping weight
        weight = product.get("shipping_weight") or product.get("weight_per_unit")
        if weight is not None:
            mapped_data["shipping_weight"] = {
                "value": float(weight),
                "unit": product.get("weight_unit", "lb").upper(),
            }

        # Track unmapped fields
        mapped_pim_fields = set(PIM_TO_TARGET_FIELDS.keys())
        mapped_pim_fields.update({
            "partner_sku", "tcin", "target_tcin", "title", "description",
            "brand", "upc", "price", "quantity", "stock_qty", "category",
            "condition", "fulfillment_type", "images", "shipping_weight",
            "weight_per_unit", "currency", "weight_unit",
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
        """Generate Target API payload for products."""
        items = []

        for product in products:
            item = {
                "partner_sku": product.get("partner_sku"),
            }

            if "tcin" in product:
                item["tcin"] = product["tcin"]
            if "title" in product:
                item["title"] = product["title"]
            if "description" in product:
                item["description"] = product["description"]
            if "brand" in product:
                item["brand"] = product["brand"]
            if "upc" in product:
                item["upc"] = product["upc"]
            if "price" in product:
                item["price"] = product["price"]
            if "quantity" in product:
                item["quantity"] = product["quantity"]
            if "category" in product:
                item["category"] = product["category"]
            if "condition" in product:
                item["condition"] = product["condition"]
            if "fulfillment_type" in product:
                item["fulfillment_type"] = product["fulfillment_type"]
            if "images" in product:
                item["images"] = product["images"]

            items.append(item)

        return {
            "items": items,
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
        """Publish products to Target."""
        job_id = str(uuid.uuid4())
        errors = []

        try:
            if not self.seller_id:
                return PublishResult(
                    success=False,
                    job_id=job_id,
                    status=PublishStatus.FAILED,
                    errors=[{"message": "Target seller ID not configured"}],
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

            # Generate payload
            payload = self.generate_payload(mapped_products)

            # Submit feed
            result = self._make_api_request(
                "POST",
                f"sellers/{self.seller_id}/items/feed",
                data=payload,
                endpoint_type="feeds",
            )

            feed_id = result.get("feed_id") or result.get("feedId")

            self._job_tracker[job_id] = TargetFeedJob(
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
        """Check the status of a publish job."""
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
                f"sellers/{self.seller_id}/items/feed/{feed_id}",
            )

            feed_status = result.get("status", "").upper()

            status_mapping = {
                "SUBMITTED": PublishStatus.PENDING,
                "PROCESSING": PublishStatus.IN_PROGRESS,
                "COMPLETED": PublishStatus.COMPLETED,
                "FAILED": PublishStatus.FAILED,
                "PARTIAL": PublishStatus.PARTIAL,
            }

            status = status_mapping.get(feed_status, PublishStatus.IN_PROGRESS)

            items_succeeded = result.get("items_succeeded", 0)
            items_failed = result.get("items_failed", 0)

            errors = []
            for error in result.get("errors", []):
                errors.append({
                    "sku": error.get("partner_sku"),
                    "message": error.get("message"),
                })

            job.status = feed_status
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
        """Test the connection to Target."""
        try:
            self._get_access_token()
            return {
                "success": True,
                "message": "Connection successful",
                "seller_id": self.seller_id,
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

register_adapter("target", TargetAdapter)
register_adapter("target_plus", TargetAdapter)
