"""
Meta Commerce Channel Adapter

Provides a comprehensive adapter for Meta Commerce (Facebook & Instagram Shops)
product syndication using the Meta Commerce Manager API.

Features:
- Meta Graph API integration for Commerce
- Facebook and Instagram Shops support
- Catalog management with batch operations
- Product feed integration
- Comprehensive validation and attribute mapping

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
# Meta Commerce-Specific Constants
# =============================================================================

class MetaProductAvailability(str, Enum):
    """Meta product availability values"""
    IN_STOCK = "in stock"
    OUT_OF_STOCK = "out of stock"
    PREORDER = "preorder"
    AVAILABLE_FOR_ORDER = "available for order"
    DISCONTINUED = "discontinued"


class MetaProductCondition(str, Enum):
    """Meta product condition values"""
    NEW = "new"
    REFURBISHED = "refurbished"
    USED = "used"


class MetaAgeGroup(str, Enum):
    """Meta product age group values"""
    ADULT = "adult"
    ALL_AGES = "all ages"
    TEEN = "teen"
    KIDS = "kids"
    TODDLER = "toddler"
    INFANT = "infant"
    NEWBORN = "newborn"


class MetaGender(str, Enum):
    """Meta product gender values"""
    FEMALE = "female"
    MALE = "male"
    UNISEX = "unisex"


# Meta Graph API endpoints
META_GRAPH_API_URL = "https://graph.facebook.com"
META_GRAPH_API_VERSION = "v18.0"

# Meta rate limit configuration
META_RATE_LIMITS = {
    "default": {
        "requests_per_hour": 4800,
        "requests_per_minute": 200,
        "burst_limit": 50,
    },
    "catalog": {
        "requests_per_hour": 2400,
        "requests_per_minute": 100,
        "burst_limit": 25,
    },
    "batch": {
        "requests_per_hour": 1200,
        "requests_per_minute": 60,
        "burst_limit": 10,
    },
}

# Required fields for Meta Commerce products
META_REQUIRED_FIELDS = {
    "id",  # Retailer ID / SKU
    "title",
    "description",
    "availability",
    "price",
    "link",
    "image_link",
    "brand",
}

# Recommended fields
META_RECOMMENDED_FIELDS = {
    "condition",
    "gtin",
    "mpn",
    "google_product_category",
    "fb_product_category",
    "additional_image_link",
    "sale_price",
}

# Field length limits
META_FIELD_LIMITS = {
    "id": 100,
    "title": 200,
    "description": 9999,
    "brand": 100,
    "link": 2000,
    "image_link": 2000,
}

# PIM to Meta field mappings
PIM_TO_META_FIELDS = {
    "item_code": "id",
    "item_name": "title",
    "pim_title": "title",
    "pim_description": "description",
    "description": "description",
    "brand": "brand",
    "standard_rate": "price",
    "barcode": "gtin",
    "gtin": "gtin",
    "manufacturer_part_number": "mpn",
    "stock_qty": "quantity_to_sell_on_facebook",
    "image": "image_link",
    "product_link": "link",
}


# =============================================================================
# Meta Commerce-Specific Data Classes
# =============================================================================

@dataclass
class MetaRateLimitState:
    """Tracks Meta rate limit state"""
    requests_made: int = 0
    requests_limit: int = 200
    window_start: datetime = field(default_factory=datetime.now)
    window_duration: int = 60
    retry_after: datetime = None
    last_request: datetime = None
    hourly_requests: int = 0
    hour_start: datetime = field(default_factory=datetime.now)
    endpoint_type: str = "default"

    def is_limited(self) -> bool:
        """Check if currently rate limited"""
        if self.retry_after and datetime.now() < self.retry_after:
            return True

        # Reset hourly window
        if datetime.now() > self.hour_start + timedelta(hours=1):
            self.hourly_requests = 0
            self.hour_start = datetime.now()

        # Reset minute window
        if datetime.now() > self.window_start + timedelta(seconds=self.window_duration):
            self.requests_made = 0
            self.window_start = datetime.now()
            return False

        limits = META_RATE_LIMITS.get(self.endpoint_type, META_RATE_LIMITS["default"])
        return (self.requests_made >= limits["requests_per_minute"] or
                self.hourly_requests >= limits["requests_per_hour"])

    def record_request(self) -> None:
        """Record a request"""
        now = datetime.now()

        if now > self.hour_start + timedelta(hours=1):
            self.hourly_requests = 0
            self.hour_start = now

        if now > self.window_start + timedelta(seconds=self.window_duration):
            self.requests_made = 0
            self.window_start = now

        self.requests_made += 1
        self.hourly_requests += 1
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
class MetaBatchJob:
    """Tracks a Meta batch operation job"""
    job_id: str
    handle: str = None
    operation_type: str = "UPDATE"
    status: str = "IN_PROGRESS"
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime = None
    items_total: int = 0
    items_succeeded: int = 0
    items_failed: int = 0
    errors: List[Dict] = field(default_factory=list)


# =============================================================================
# Meta Commerce Adapter
# =============================================================================

class MetaCommerceAdapter(ChannelAdapter):
    """
    Meta Commerce channel adapter for product syndication.

    Uses the Meta Graph API for Commerce Manager catalog management
    supporting both Facebook and Instagram Shops.

    Features:
    - Graph API with access token authentication
    - Catalog product management
    - Batch operations for bulk updates
    - Product set management
    - Availability and pricing sync
    """

    channel_code: str = "meta_commerce"
    channel_name: str = "Meta Commerce (Facebook/Instagram Shops)"

    # Rate limiting settings
    default_requests_per_minute: int = 200
    default_requests_per_second: float = 3.0
    max_retry_attempts: int = 5
    base_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 120.0

    def __init__(self, channel_doc: Any = None):
        """Initialize Meta Commerce adapter."""
        super().__init__(channel_doc)
        self._rate_limit_state: MetaRateLimitState = None
        self._catalog_id: str = None
        self._business_id: str = None
        self._job_tracker: Dict[str, MetaBatchJob] = {}

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def api_base_url(self) -> str:
        """Get the Meta Graph API base URL."""
        return f"{META_GRAPH_API_URL}/{META_GRAPH_API_VERSION}"

    @property
    def catalog_id(self) -> str:
        """Get the Meta catalog ID."""
        if self._catalog_id:
            return self._catalog_id

        self._catalog_id = self.config.get("catalog_id") or self.config.get("fb_catalog_id", "")
        return self._catalog_id

    @property
    def business_id(self) -> str:
        """Get the Meta business ID."""
        if self._business_id:
            return self._business_id

        self._business_id = self.config.get("business_id") or self.config.get("fb_business_id", "")
        return self._business_id

    @property
    def rate_limit_state(self) -> MetaRateLimitState:
        """Get current rate limit state."""
        if self._rate_limit_state is None:
            self._rate_limit_state = MetaRateLimitState()
        return self._rate_limit_state

    # =========================================================================
    # Authentication Methods
    # =========================================================================

    def _get_meta_credentials(self) -> Dict:
        """Get Meta-specific credentials."""
        credentials = self.credentials

        return {
            "access_token": credentials.get("access_token") or credentials.get("api_key"),
            "app_id": self.config.get("app_id"),
            "app_secret": credentials.get("api_secret"),
        }

    def _get_auth_params(self) -> Dict:
        """Get authentication parameters for API requests."""
        creds = self._get_meta_credentials()

        access_token = creds.get("access_token")
        if not access_token:
            raise AuthenticationError(
                "Meta access token is required",
                channel=self.channel_code,
            )

        return {"access_token": access_token}

    def _get_auth_headers(self) -> Dict:
        """Build headers for Meta API requests."""
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # =========================================================================
    # Rate Limiting Methods
    # =========================================================================

    def handle_rate_limiting(self, response: Any = None) -> None:
        """Handle Meta rate limiting from response."""
        if response is None:
            return

        status_code = getattr(response, 'status_code', None)

        if status_code == 429:
            retry_after = 60
            self.rate_limit_state.retry_after = datetime.now() + timedelta(seconds=retry_after)

            raise RateLimitError(
                "Meta API rate limit exceeded",
                channel=self.channel_code,
                retry_after=retry_after,
            )

        # Check for rate limit error in response
        if isinstance(response, dict) and "error" in response:
            error = response.get("error", {})
            if error.get("code") == 4:  # Rate limit error
                self.rate_limit_state.retry_after = datetime.now() + timedelta(seconds=60)
                raise RateLimitError(
                    "Meta API rate limit exceeded",
                    channel=self.channel_code,
                    retry_after=60,
                )

    def _wait_for_rate_limit(self) -> None:
        """Wait if rate limited."""
        wait_time = self.rate_limit_state.wait_time()

        if wait_time > 0:
            if wait_time > self.max_backoff_seconds:
                raise RateLimitError(
                    f"Meta rate limit wait time ({wait_time}s) exceeds maximum",
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
        """Make a request to the Meta Graph API."""
        import requests

        self.rate_limit_state.endpoint_type = endpoint_type
        self._wait_for_rate_limit()

        url = f"{self.api_base_url}/{endpoint}"

        # Add auth params
        if params is None:
            params = {}
        params.update(self._get_auth_params())

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
                    if data:
                        response = requests.post(
                            url, headers=headers, params=params, json=data,
                            timeout=self.config.get("timeout", 60)
                        )
                    else:
                        response = requests.post(
                            url, headers=headers, params=params,
                            timeout=self.config.get("timeout", 60)
                        )
                elif method.upper() == "DELETE":
                    response = requests.delete(
                        url, headers=headers, params=params,
                        timeout=self.config.get("timeout", 30)
                    )
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                self.handle_rate_limiting(response)

                result = response.json()

                # Check for error in response
                if "error" in result:
                    error = result["error"]
                    error_code = error.get("code")

                    if error_code in (190, 102):  # Access token errors
                        raise AuthenticationError(
                            f"Meta authentication failed: {error.get('message')}",
                            channel=self.channel_code,
                        )

                    if error_code == 4:  # Rate limit
                        self.handle_rate_limiting(result)

                    raise PublishError(
                        f"Meta API error: {error.get('message')}",
                        channel=self.channel_code,
                    )

                return result

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
            f"Meta API request failed: {last_error}",
            channel=self.channel_code,
        )

    # =========================================================================
    # Validation Methods
    # =========================================================================

    def validate_product(self, product: Dict) -> ValidationResult:
        """Validate a product against Meta Commerce requirements."""
        errors = []
        warnings = []
        product_id = product.get("item_code", product.get("id", "unknown"))

        # Check required fields
        for field_name in META_REQUIRED_FIELDS:
            pim_field = None
            for pim_name, meta_name in PIM_TO_META_FIELDS.items():
                if meta_name == field_name:
                    pim_field = pim_name
                    break

            value = product.get(field_name)
            if pim_field:
                value = value or product.get(pim_field)

            if not value:
                errors.append({
                    "field": field_name,
                    "message": f"Required field '{field_name}' is missing",
                    "rule": "required",
                })

        # Validate title
        title = product.get("title") or product.get("pim_title") or product.get("item_name")
        if title:
            if len(str(title)) > META_FIELD_LIMITS["title"]:
                errors.append({
                    "field": "title",
                    "message": f"Title exceeds {META_FIELD_LIMITS['title']} characters",
                    "rule": "max_length",
                })

        # Validate link URL
        link = product.get("link") or product.get("product_link")
        if link:
            if not link.startswith(("http://", "https://")):
                errors.append({
                    "field": "link",
                    "message": "Product link must be a valid URL",
                    "rule": "url_format",
                })

        # Validate image link
        image_link = product.get("image_link") or product.get("image")
        if image_link:
            img_url = image_link if isinstance(image_link, str) else image_link[0] if isinstance(image_link, list) else None
            if img_url and not img_url.startswith(("http://", "https://")):
                errors.append({
                    "field": "image_link",
                    "message": "Image link must be a valid URL",
                    "rule": "url_format",
                })

        # Validate price
        price = product.get("price") or product.get("standard_rate")
        if price is not None:
            try:
                # Price format should be "10.00 USD"
                if isinstance(price, (int, float)):
                    pass  # Valid
                elif isinstance(price, str):
                    float(price.split()[0])  # Extract numeric part
            except (ValueError, TypeError, IndexError):
                errors.append({
                    "field": "price",
                    "message": "Price must be a valid number or format like '10.00 USD'",
                    "rule": "price_format",
                })

        # Check recommended fields
        for field_name in META_RECOMMENDED_FIELDS:
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
        """Map PIM product attributes to Meta Commerce format."""
        product_id = product.get("item_code", product.get("id", "unknown"))
        mapped_data = {}
        unmapped_fields = []

        # Retailer ID (required)
        sku = product.get("item_code") or product.get("id")
        if sku:
            mapped_data["id"] = str(sku)[:META_FIELD_LIMITS["id"]]

        # Title (required)
        title = product.get("pim_title") or product.get("title") or product.get("item_name")
        if title:
            mapped_data["title"] = str(title)[:META_FIELD_LIMITS["title"]]

        # Description (required)
        description = product.get("pim_description") or product.get("description")
        if description:
            mapped_data["description"] = str(description)[:META_FIELD_LIMITS["description"]]

        # Brand (required)
        brand = product.get("brand")
        if brand:
            mapped_data["brand"] = str(brand)[:META_FIELD_LIMITS["brand"]]

        # Link (required)
        link = product.get("link") or product.get("product_link")
        if link:
            mapped_data["link"] = str(link)[:META_FIELD_LIMITS["link"]]

        # Image link (required)
        image = product.get("image_link") or product.get("image")
        if image:
            if isinstance(image, str):
                mapped_data["image_link"] = image
            elif isinstance(image, list) and image:
                mapped_data["image_link"] = image[0] if isinstance(image[0], str) else image[0].get("url", "")
                if len(image) > 1:
                    additional = []
                    for img in image[1:10]:  # Max 10 additional images
                        if isinstance(img, str):
                            additional.append(img)
                        elif isinstance(img, dict):
                            additional.append(img.get("url", ""))
                    if additional:
                        mapped_data["additional_image_link"] = ",".join(additional)

        # Price (required)
        price = product.get("price") or product.get("standard_rate")
        if price is not None:
            currency = product.get("currency", "USD")
            if isinstance(price, (int, float)):
                mapped_data["price"] = f"{float(price):.2f} {currency}"
            else:
                mapped_data["price"] = str(price)

        # Sale price
        sale_price = product.get("sale_price")
        if sale_price is not None:
            currency = product.get("currency", "USD")
            if isinstance(sale_price, (int, float)):
                mapped_data["sale_price"] = f"{float(sale_price):.2f} {currency}"
            else:
                mapped_data["sale_price"] = str(sale_price)

        # Availability (required)
        quantity = product.get("quantity") or product.get("stock_qty")
        availability = product.get("availability")
        if availability:
            try:
                mapped_data["availability"] = MetaProductAvailability[availability.upper().replace(" ", "_")].value
            except KeyError:
                mapped_data["availability"] = MetaProductAvailability.IN_STOCK.value
        elif quantity is not None:
            if int(quantity) > 0:
                mapped_data["availability"] = MetaProductAvailability.IN_STOCK.value
            else:
                mapped_data["availability"] = MetaProductAvailability.OUT_OF_STOCK.value
        else:
            mapped_data["availability"] = MetaProductAvailability.IN_STOCK.value

        # Quantity to sell
        if quantity is not None:
            mapped_data["quantity_to_sell_on_facebook"] = max(0, int(quantity))

        # Condition
        condition = product.get("condition", "new")
        try:
            mapped_data["condition"] = MetaProductCondition[condition.upper()].value
        except KeyError:
            mapped_data["condition"] = MetaProductCondition.NEW.value

        # GTIN
        gtin = product.get("gtin") or product.get("barcode")
        if gtin:
            mapped_data["gtin"] = str(gtin).strip()

        # MPN
        mpn = product.get("mpn") or product.get("manufacturer_part_number")
        if mpn:
            mapped_data["mpn"] = str(mpn)

        # Google Product Category
        google_cat = product.get("google_product_category")
        if google_cat:
            mapped_data["google_product_category"] = str(google_cat)

        # Facebook Product Category
        fb_cat = product.get("fb_product_category")
        if fb_cat:
            mapped_data["fb_product_category"] = str(fb_cat)

        # Age group
        age_group = product.get("age_group")
        if age_group:
            try:
                mapped_data["age_group"] = MetaAgeGroup[age_group.upper().replace(" ", "_")].value
            except KeyError:
                pass

        # Gender
        gender = product.get("gender")
        if gender:
            try:
                mapped_data["gender"] = MetaGender[gender.upper()].value
            except KeyError:
                pass

        # Track unmapped fields
        mapped_pim_fields = set(PIM_TO_META_FIELDS.keys())
        mapped_pim_fields.update({
            "id", "title", "description", "brand", "link", "product_link",
            "image_link", "image", "price", "sale_price", "currency",
            "availability", "quantity", "stock_qty", "condition", "gtin",
            "barcode", "mpn", "manufacturer_part_number", "google_product_category",
            "fb_product_category", "age_group", "gender",
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
        """Generate Meta Commerce API payload for products."""
        requests_list = []

        for product in products:
            request = {
                "method": "UPDATE",
                "retailer_id": product.get("id"),
                "data": product,
            }
            requests_list.append(request)

        return {
            "requests": requests_list,
            "_metadata": {
                "batch_id": str(uuid.uuid4()),
                "created_at": datetime.now().isoformat(),
                "product_count": len(requests_list),
            },
        }

    # =========================================================================
    # Publishing Methods
    # =========================================================================

    def publish(self, products: List[Dict]) -> PublishResult:
        """Publish products to Meta Commerce."""
        job_id = str(uuid.uuid4())
        errors = []
        products_succeeded = 0
        products_failed = 0

        try:
            if not self.catalog_id:
                return PublishResult(
                    success=False,
                    job_id=job_id,
                    status=PublishStatus.FAILED,
                    errors=[{"message": "Meta catalog ID not configured"}],
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

            # Submit batch request
            result = self._make_api_request(
                "POST",
                f"{self.catalog_id}/batch",
                data={"requests": json.dumps(payload["requests"])},
                endpoint_type="batch",
            )

            # Check for handles (async batch)
            handles = result.get("handles", [])

            if handles:
                self._job_tracker[job_id] = MetaBatchJob(
                    job_id=job_id,
                    handle=handles[0] if handles else None,
                    items_total=len(products),
                )

            products_succeeded = result.get("num_processed", len(products))
            products_failed = result.get("num_failed", 0)

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
                status=PublishStatus.COMPLETED if job.status == "COMPLETED" else PublishStatus.IN_PROGRESS,
                progress=1.0 if job.status == "COMPLETED" else 0.5,
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
        """Test the connection to Meta Commerce."""
        try:
            if not self.catalog_id:
                return {
                    "success": False,
                    "message": "Meta catalog ID is not configured",
                }

            result = self._make_api_request("GET", self.catalog_id)

            catalog_name = result.get("name", "Unknown")

            return {
                "success": True,
                "message": "Connection successful",
                "catalog_id": self.catalog_id,
                "catalog_name": catalog_name,
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

register_adapter("meta_commerce", MetaCommerceAdapter)
register_adapter("facebook_commerce", MetaCommerceAdapter)
register_adapter("facebook_shops", MetaCommerceAdapter)
register_adapter("instagram_shopping", MetaCommerceAdapter)
