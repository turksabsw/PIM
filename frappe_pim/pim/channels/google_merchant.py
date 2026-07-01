"""
Google Merchant Center Channel Adapter

Provides a comprehensive adapter for Google Merchant Center product syndication
using the Google Content API for Shopping (google-api-python-client).

Features:
- Content API for Shopping v2.1 for product management
- OAuth2/Service Account authentication support
- Quota-based rate limiting with exponential backoff
- Product validation against Google Shopping requirements
- Attribute mapping to Google product format
- Batch operations for large catalog updates
- Multi-country/multi-language support

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
# Google Merchant Center Constants
# =============================================================================

class GoogleProductAvailability(str, Enum):
    """Google product availability values"""
    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    PREORDER = "preorder"
    BACKORDER = "backorder"


class GoogleProductCondition(str, Enum):
    """Google product condition values"""
    NEW = "new"
    REFURBISHED = "refurbished"
    USED = "used"


class GoogleProductChannel(str, Enum):
    """Google product channel values"""
    ONLINE = "online"
    LOCAL = "local"


class GoogleAgeGroup(str, Enum):
    """Google product age group for apparel"""
    NEWBORN = "newborn"
    INFANT = "infant"
    TODDLER = "toddler"
    KIDS = "kids"
    ADULT = "adult"


class GoogleGender(str, Enum):
    """Google product gender for apparel"""
    MALE = "male"
    FEMALE = "female"
    UNISEX = "unisex"


# Google Content API version
GOOGLE_API_VERSION = "v2.1"
GOOGLE_API_SERVICE_NAME = "content"

# Google rate limit configuration (quota-based)
# Default quotas per project:
# - products.insert/update: 7200 per hour
# - products.get: 7200 per hour
# - products.list: 600 per hour
# - products.custombatch: 7200 per hour (up to 1000 entries per request)
GOOGLE_RATE_LIMITS = {
    "products_insert": {
        "requests_per_hour": 7200,
        "requests_per_second": 2,
    },
    "products_custombatch": {
        "requests_per_hour": 7200,
        "requests_per_second": 2,
        "max_entries_per_batch": 1000,
    },
    "products_list": {
        "requests_per_hour": 600,
        "requests_per_second": 0.17,
    },
}

# Required fields for Google Shopping products
GOOGLE_REQUIRED_FIELDS = {
    "offerId",  # Unique product identifier
    "title",  # Product title
    "description",  # Product description
    "link",  # URL to product page
    "imageLink",  # Main product image URL
    "availability",  # Stock status
    "price",  # Product price with currency
}

# Recommended fields for better listings
GOOGLE_RECOMMENDED_FIELDS = {
    "gtin",  # Global Trade Item Number
    "brand",  # Brand name
    "mpn",  # Manufacturer Part Number (required if no GTIN)
    "condition",  # new/refurbished/used
    "googleProductCategory",  # Google's taxonomy category ID
    "productType",  # Your own product categorization
    "additionalImageLinks",  # Additional product images
    "salePrice",  # Sale price if on sale
    "salePriceEffectiveDate",  # Sale period
    "shipping",  # Shipping details
    "shippingWeight",  # For shipping calculation
    "color",  # Product color
    "size",  # Product size
    "material",  # Product material
    "pattern",  # Product pattern
    "ageGroup",  # For apparel
    "gender",  # For apparel
}

# Field length limits
GOOGLE_FIELD_LIMITS = {
    "offerId": 50,
    "title": 150,
    "description": 5000,
    "link": 2000,
    "imageLink": 2000,
    "brand": 70,
    "mpn": 70,
    "color": 100,
    "size": 100,
    "material": 200,
    "pattern": 100,
    "productType": 750,
}

# PIM to Google Merchant field mappings
PIM_TO_GOOGLE_FIELDS = {
    "item_code": "offerId",
    "item_name": "title",
    "pim_title": "title",
    "pim_description": "description",
    "description": "description",
    "website_url": "link",
    "image": "imageLink",
    "barcode": "gtin",
    "gtin": "gtin",
    "brand": "brand",
    "manufacturer_part_no": "mpn",
    "standard_rate": "price",
    "weight_per_unit": "shippingWeight",
    "net_weight": "shippingWeight",
    "item_group": "productType",
    "country_of_origin": "originCountry",
    "color": "color",
    "size": "sizes",
    "material": "material",
}


# =============================================================================
# Google Merchant Center Data Classes
# =============================================================================

@dataclass
class GoogleRateLimitState:
    """Tracks Google API quota-based rate limit state"""
    requests_made_this_hour: int = 0
    requests_limit_per_hour: int = 7200
    hour_start: datetime = field(default_factory=datetime.now)
    last_request: datetime = None
    retry_after: datetime = None
    consecutive_errors: int = 0

    # Minimum interval between requests (to avoid bursts)
    min_request_interval: float = 0.5  # 2 requests per second

    def is_limited(self) -> bool:
        """Check if currently rate limited"""
        if self.retry_after and datetime.now() < self.retry_after:
            return True

        # Reset hour window if expired
        if datetime.now() > self.hour_start + timedelta(hours=1):
            self.requests_made_this_hour = 0
            self.hour_start = datetime.now()
            return False

        return self.requests_made_this_hour >= self.requests_limit_per_hour

    def record_request(self) -> None:
        """Record that a request was made"""
        # Reset if hour window expired
        if datetime.now() > self.hour_start + timedelta(hours=1):
            self.requests_made_this_hour = 0
            self.hour_start = datetime.now()

        self.requests_made_this_hour += 1
        self.last_request = datetime.now()

    def wait_time(self) -> float:
        """Calculate wait time before next request"""
        if self.retry_after:
            delta = self.retry_after - datetime.now()
            if delta.total_seconds() > 0:
                return delta.total_seconds()

        # Enforce minimum interval between requests
        if self.last_request:
            elapsed = (datetime.now() - self.last_request).total_seconds()
            if elapsed < self.min_request_interval:
                return self.min_request_interval - elapsed

        if self.is_limited():
            # Wait until next hour window
            window_end = self.hour_start + timedelta(hours=1)
            delta = window_end - datetime.now()
            return max(0, delta.total_seconds())

        return 0


@dataclass
class GoogleBatchJob:
    """Tracks a Google Merchant batch operation"""
    job_id: str
    merchant_id: str
    operation_type: str  # insert, update, delete
    status: str  # pending, completed, failed, partial
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime = None
    total_entries: int = 0
    successful_entries: int = 0
    failed_entries: int = 0
    errors: List[Dict] = field(default_factory=list)


# =============================================================================
# Google Merchant Center Adapter
# =============================================================================

class GoogleMerchantAdapter(ChannelAdapter):
    """
    Google Merchant Center channel adapter for product syndication.

    Uses the Google Content API for Shopping (v2.1) for product management
    with support for batch operations and multi-country targeting.

    Features:
    - Content API for Shopping integration
    - OAuth2 and Service Account authentication
    - Quota-based rate limiting
    - Batch product operations (up to 1000 per request)
    - Multi-country and multi-language support
    - Automatic validation against Google Shopping requirements
    """

    channel_code: str = "google_merchant"
    channel_name: str = "Google Merchant Center"

    # Rate limiting settings
    default_requests_per_minute: int = 120  # 2/second
    default_requests_per_second: float = 2.0
    max_retry_attempts: int = 5
    base_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 120.0

    def __init__(self, channel_doc: Any = None):
        """Initialize Google Merchant Center adapter.

        Args:
            channel_doc: Channel Frappe document with Google credentials
        """
        super().__init__(channel_doc)
        self._rate_limit_state: GoogleRateLimitState = None
        self._service = None
        self._merchant_id: str = None
        self._target_country: str = "US"
        self._content_language: str = "en"
        self._job_tracker: Dict[str, GoogleBatchJob] = {}

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def merchant_id(self) -> str:
        """Get the Google Merchant Center ID."""
        if self._merchant_id:
            return self._merchant_id

        # Get from config or channel document
        self._merchant_id = str(self.config.get("merchant_id", ""))
        return self._merchant_id

    @property
    def target_country(self) -> str:
        """Get the target country for products."""
        return self.config.get("target_country", "US")

    @property
    def content_language(self) -> str:
        """Get the content language for products."""
        return self.config.get("content_language", "en")

    @property
    def rate_limit_state(self) -> GoogleRateLimitState:
        """Get current rate limit state."""
        if self._rate_limit_state is None:
            self._rate_limit_state = GoogleRateLimitState()
        return self._rate_limit_state

    # =========================================================================
    # Authentication Methods
    # =========================================================================

    def _get_google_credentials(self) -> Dict:
        """Get Google-specific credentials.

        Supports both OAuth2 and Service Account authentication.

        Returns:
            Dictionary with credential information:
            - service_account_json: Service account key file contents (JSON)
            - client_id: OAuth2 client ID
            - client_secret: OAuth2 client secret
            - refresh_token: OAuth2 refresh token
        """
        credentials = self.credentials

        return {
            "service_account_json": credentials.get("service_account_json"),
            "client_id": credentials.get("api_key"),
            "client_secret": credentials.get("api_secret"),
            "refresh_token": credentials.get("refresh_token"),
        }

    def _build_service(self):
        """Build the Google Content API service client.

        Returns:
            Google API service resource

        Raises:
            AuthenticationError: If credentials are invalid or missing
        """
        try:
            from googleapiclient.discovery import build
            from google.oauth2 import service_account
            from google.oauth2.credentials import Credentials
        except ImportError:
            raise AuthenticationError(
                "google-api-python-client or google-auth not installed",
                channel=self.channel_code,
            )

        if self._service is not None:
            return self._service

        creds = self._get_google_credentials()

        try:
            # Try Service Account first
            if creds.get("service_account_json"):
                service_info = creds["service_account_json"]
                if isinstance(service_info, str):
                    service_info = json.loads(service_info)

                credentials = service_account.Credentials.from_service_account_info(
                    service_info,
                    scopes=["https://www.googleapis.com/auth/content"]
                )
            # Fall back to OAuth2
            elif creds.get("client_id") and creds.get("refresh_token"):
                credentials = Credentials(
                    token=None,
                    refresh_token=creds["refresh_token"],
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=creds["client_id"],
                    client_secret=creds.get("client_secret", ""),
                )
            else:
                raise AuthenticationError(
                    "No valid Google credentials configured. "
                    "Provide either service_account_json or OAuth2 credentials.",
                    channel=self.channel_code,
                )

            self._service = build(
                GOOGLE_API_SERVICE_NAME,
                GOOGLE_API_VERSION,
                credentials=credentials,
                cache_discovery=False,
            )

            return self._service

        except json.JSONDecodeError as e:
            raise AuthenticationError(
                f"Invalid service account JSON: {str(e)}",
                channel=self.channel_code,
            )
        except Exception as e:
            raise AuthenticationError(
                f"Failed to build Google API service: {str(e)}",
                channel=self.channel_code,
            )

    # =========================================================================
    # Rate Limiting Methods
    # =========================================================================

    def handle_rate_limiting(self, response: Any = None) -> None:
        """Handle Google API rate limiting from response.

        Parses error responses for quota exceeded errors and updates
        internal rate limit state accordingly.

        Args:
            response: API response or exception

        Raises:
            RateLimitError: If quota exceeded and cannot proceed
        """
        if response is None:
            return

        # Check for HttpError with quota exceeded
        if hasattr(response, 'resp') and hasattr(response.resp, 'status'):
            status_code = response.resp.status

            if status_code == 429:  # Too Many Requests
                # Parse Retry-After header if available
                retry_after = 60  # Default to 60 seconds
                if hasattr(response.resp, 'get'):
                    retry_after = int(response.resp.get("Retry-After", 60))

                self.rate_limit_state.retry_after = datetime.now() + timedelta(seconds=retry_after)
                self.rate_limit_state.consecutive_errors += 1

                raise RateLimitError(
                    "Google API quota exceeded",
                    channel=self.channel_code,
                    retry_after=retry_after,
                    details={
                        "status_code": status_code,
                        "retry_after": retry_after,
                    },
                )

            if status_code == 403:  # Could be quota or permission error
                # Check if it's a quota error
                try:
                    error_content = response.content
                    if "quotaExceeded" in str(error_content) or "rateLimitExceeded" in str(error_content):
                        retry_after = 60
                        self.rate_limit_state.retry_after = datetime.now() + timedelta(seconds=retry_after)
                        self.rate_limit_state.consecutive_errors += 1

                        raise RateLimitError(
                            "Google API quota exceeded (403)",
                            channel=self.channel_code,
                            retry_after=retry_after,
                        )
                except (AttributeError, TypeError):
                    pass

        # Record successful request
        self.rate_limit_state.record_request()

    def _wait_for_rate_limit(self) -> None:
        """Wait if rate limited.

        Raises:
            RateLimitError: If wait time exceeds maximum
        """
        wait_time = self.rate_limit_state.wait_time()

        if wait_time > 0:
            if wait_time > self.max_backoff_seconds:
                raise RateLimitError(
                    f"Google API rate limit wait time ({wait_time}s) exceeds maximum",
                    channel=self.channel_code,
                    retry_after=int(wait_time),
                )
            time.sleep(wait_time)

    def _execute_api_call(self, request) -> Any:
        """Execute a Google API call with rate limiting and retries.

        Args:
            request: Google API request object

        Returns:
            API response

        Raises:
            RateLimitError: If rate limit exceeded after retries
            AuthenticationError: If authentication fails
            PublishError: If request fails
        """
        from googleapiclient.errors import HttpError

        self._wait_for_rate_limit()

        last_error = None

        for attempt in range(self.max_retry_attempts):
            try:
                self.rate_limit_state.record_request()
                response = request.execute()
                self.rate_limit_state.consecutive_errors = 0
                return response

            except HttpError as e:
                last_error = e
                status_code = e.resp.status

                # Handle rate limiting
                if status_code in (429, 403):
                    try:
                        self.handle_rate_limiting(e)
                    except RateLimitError:
                        if attempt < self.max_retry_attempts - 1:
                            backoff = self._calculate_backoff(attempt)
                            time.sleep(backoff)
                            continue
                        raise

                # Handle authentication errors
                if status_code in (401, 403):
                    error_content = str(e.content) if hasattr(e, 'content') else str(e)
                    if "unauthorized" in error_content.lower() or "permission" in error_content.lower():
                        raise AuthenticationError(
                            f"Google API authentication failed: {error_content}",
                            channel=self.channel_code,
                        )

                # Retry on transient errors
                if status_code in (500, 502, 503, 504):
                    if attempt < self.max_retry_attempts - 1:
                        backoff = self._calculate_backoff(attempt)
                        time.sleep(backoff)
                        continue

                raise PublishError(
                    f"Google API error (HTTP {status_code}): {str(e)}",
                    channel=self.channel_code,
                    details={"status_code": status_code},
                )

            except Exception as e:
                last_error = e
                if attempt < self.max_retry_attempts - 1:
                    backoff = self._calculate_backoff(attempt)
                    time.sleep(backoff)
                else:
                    raise PublishError(
                        f"Google API request failed: {str(e)}",
                        channel=self.channel_code,
                    )

        raise PublishError(
            f"Google API request failed after {self.max_retry_attempts} attempts: {last_error}",
            channel=self.channel_code,
        )

    # =========================================================================
    # Validation Methods
    # =========================================================================

    def validate_product(self, product: Dict) -> ValidationResult:
        """Validate a product against Google Merchant Center requirements.

        Checks required fields, field length limits, identifier requirements,
        and other Google Shopping-specific requirements.

        Args:
            product: Product data dictionary in PIM format

        Returns:
            ValidationResult with validation status and any errors/warnings
        """
        errors = []
        warnings = []
        product_id = product.get("item_code", product.get("offerId", "unknown"))

        # Check for required fields
        required_field_checks = [
            ("offerId", ["item_code", "offerId", "sku"]),
            ("title", ["pim_title", "item_name", "title"]),
            ("description", ["pim_description", "description"]),
            ("link", ["website_url", "link", "product_url"]),
            ("imageLink", ["image", "imageLink", "image_url"]),
            ("availability", ["availability", "stock_status"]),
            ("price", ["standard_rate", "price"]),
        ]

        for google_field, pim_fields in required_field_checks:
            value = None
            for pim_field in pim_fields:
                value = product.get(pim_field)
                if value:
                    break

            if not value:
                errors.append({
                    "field": google_field,
                    "message": f"Required field '{google_field}' is missing",
                    "rule": "required",
                })

        # Check identifier requirements (GTIN or brand+MPN)
        gtin = product.get("barcode") or product.get("gtin")
        brand = product.get("brand")
        mpn = product.get("manufacturer_part_no") or product.get("mpn")

        if not gtin and not (brand and mpn):
            warnings.append({
                "field": "identifier",
                "message": "Either GTIN or Brand+MPN is strongly recommended for product visibility",
                "rule": "identifier_requirement",
            })

        # Validate GTIN if provided
        if gtin:
            gtin_error = self._validate_gtin(gtin)
            if gtin_error:
                errors.append(gtin_error)

        # Check field length limits
        for field_name, max_length in GOOGLE_FIELD_LIMITS.items():
            # Check both PIM and Google field names
            value = product.get(field_name)
            if not value:
                for pim_field, google_field in PIM_TO_GOOGLE_FIELDS.items():
                    if google_field == field_name:
                        value = product.get(pim_field)
                        break

            if value and isinstance(value, str) and len(value) > max_length:
                errors.append({
                    "field": field_name,
                    "message": f"Field '{field_name}' exceeds maximum length of {max_length} characters",
                    "value": f"{len(value)} characters",
                    "rule": "max_length",
                })

        # Validate price if provided
        price = product.get("standard_rate") or product.get("price")
        if price is not None:
            try:
                price_val = float(price) if not isinstance(price, dict) else price.get("value", 0)
                if price_val < 0:
                    errors.append({
                        "field": "price",
                        "message": "Price cannot be negative",
                        "value": str(price),
                        "rule": "non_negative",
                    })
            except (ValueError, TypeError):
                errors.append({
                    "field": "price",
                    "message": "Price must be a valid number",
                    "value": str(price),
                    "rule": "numeric",
                })

        # Validate availability if provided
        availability = product.get("availability") or product.get("stock_status")
        if availability:
            valid_availability = [e.value for e in GoogleProductAvailability]
            availability_lower = str(availability).lower().replace(" ", "_")
            if availability_lower not in valid_availability:
                warnings.append({
                    "field": "availability",
                    "message": f"Availability '{availability}' may not be recognized. "
                              f"Valid values: {', '.join(valid_availability)}",
                    "value": availability,
                    "rule": "valid_availability",
                })

        # Validate condition if provided
        condition = product.get("condition")
        if condition:
            valid_conditions = [e.value for e in GoogleProductCondition]
            if str(condition).lower() not in valid_conditions:
                warnings.append({
                    "field": "condition",
                    "message": f"Condition '{condition}' may not be recognized. "
                              f"Valid values: {', '.join(valid_conditions)}",
                    "value": condition,
                    "rule": "valid_condition",
                })

        # Validate image URL format
        image_url = product.get("image") or product.get("imageLink")
        if image_url:
            image_error = self._validate_image_url(image_url)
            if image_error:
                errors.append(image_error)

        # Check for recommended fields
        for field_name in GOOGLE_RECOMMENDED_FIELDS:
            if field_name not in product and field_name not in GOOGLE_REQUIRED_FIELDS:
                # Check PIM field mappings
                found = False
                for pim_field, google_field in PIM_TO_GOOGLE_FIELDS.items():
                    if google_field == field_name and pim_field in product:
                        found = True
                        break

                if not found and field_name in {"gtin", "brand", "mpn", "googleProductCategory"}:
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

    def _validate_gtin(self, gtin: str) -> Optional[Dict]:
        """Validate GTIN format and checksum.

        Args:
            gtin: GTIN/barcode string

        Returns:
            Error dict if invalid, None if valid
        """
        gtin = str(gtin).replace(" ", "").replace("-", "")

        # Valid GTIN lengths: 8, 12, 13, 14
        valid_lengths = {8, 12, 13, 14}

        if len(gtin) not in valid_lengths:
            return {
                "field": "gtin",
                "message": f"GTIN length {len(gtin)} is invalid. Expected 8, 12, 13, or 14 digits",
                "value": gtin,
                "rule": "gtin_length",
            }

        if not gtin.isdigit():
            return {
                "field": "gtin",
                "message": "GTIN must contain only digits",
                "value": gtin,
                "rule": "gtin_format",
            }

        # Validate check digit
        if not self._validate_gtin_checksum(gtin):
            return {
                "field": "gtin",
                "message": "GTIN check digit is invalid",
                "value": gtin,
                "rule": "gtin_checksum",
            }

        return None

    def _validate_gtin_checksum(self, gtin: str) -> bool:
        """Validate GTIN checksum using GS1 algorithm.

        Args:
            gtin: GTIN string (must be all digits)

        Returns:
            True if checksum is valid, False otherwise
        """
        try:
            # Pad to 14 digits for calculation
            gtin = gtin.zfill(14)
            digits = [int(d) for d in gtin]

            # Calculate checksum
            total = 0
            for i, digit in enumerate(digits[:-1]):
                if i % 2 == 0:
                    total += digit * 3
                else:
                    total += digit

            check_digit = (10 - (total % 10)) % 10
            return check_digit == digits[-1]
        except (ValueError, IndexError):
            return False

    def _validate_image_url(self, url: str) -> Optional[Dict]:
        """Validate image URL format.

        Args:
            url: Image URL string

        Returns:
            Error dict if invalid, None if valid
        """
        if not url:
            return None

        url = str(url).strip()

        # Check for valid URL scheme
        if not (url.startswith("http://") or url.startswith("https://")):
            return {
                "field": "imageLink",
                "message": "Image URL must start with http:// or https://",
                "value": url[:100],
                "rule": "url_scheme",
            }

        # Check for common image extensions (warning only if missing)
        valid_extensions = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
        has_valid_ext = any(url.lower().endswith(ext) or f"{ext}?" in url.lower()
                          for ext in valid_extensions)

        if not has_valid_ext and "?" not in url:
            # This is just informational, not an error
            pass

        # Check URL length
        if len(url) > GOOGLE_FIELD_LIMITS.get("imageLink", 2000):
            return {
                "field": "imageLink",
                "message": f"Image URL exceeds maximum length of {GOOGLE_FIELD_LIMITS['imageLink']} characters",
                "value": f"{len(url)} characters",
                "rule": "max_length",
            }

        return None

    # =========================================================================
    # Mapping Methods
    # =========================================================================

    def map_attributes(self, product: Dict) -> MappingResult:
        """Map PIM product attributes to Google Merchant Center format.

        Converts internal field names to Google's expected Content API
        format including nested structures for price and shipping.

        Args:
            product: Product data dictionary in PIM format

        Returns:
            MappingResult with mapped data and unmapped fields
        """
        product_id = product.get("item_code", product.get("offerId", "unknown"))
        mapped_data = {}
        unmapped_fields = []

        # Offer ID (required, unique identifier)
        offer_id = product.get("item_code") or product.get("offerId") or product.get("sku")
        if offer_id:
            mapped_data["offerId"] = str(offer_id)[:50]

        # Title (required)
        title = product.get("pim_title") or product.get("item_name") or product.get("title")
        if title:
            mapped_data["title"] = str(title)[:150]

        # Description (required)
        description = product.get("pim_description") or product.get("description")
        if description:
            # Remove HTML tags for Google (plain text preferred)
            description = self._strip_html(description)
            mapped_data["description"] = str(description)[:5000]

        # Link (required) - URL to product page
        link = product.get("website_url") or product.get("link") or product.get("product_url")
        if link:
            mapped_data["link"] = str(link)

        # Image Link (required)
        image = product.get("image") or product.get("imageLink") or product.get("image_url")
        if image:
            if isinstance(image, list):
                mapped_data["imageLink"] = str(image[0])
                if len(image) > 1:
                    mapped_data["additionalImageLinks"] = [str(img) for img in image[1:10]]
            else:
                mapped_data["imageLink"] = str(image)

        # Availability (required)
        availability = product.get("availability") or product.get("stock_status")
        if availability:
            mapped_data["availability"] = self._map_availability(availability)
        else:
            # Default to in_stock
            mapped_data["availability"] = GoogleProductAvailability.IN_STOCK.value

        # Price (required)
        price = product.get("standard_rate") or product.get("price")
        currency = product.get("currency") or self.config.get("currency", "USD")
        if price is not None:
            mapped_data["price"] = self._format_price(price, currency)

        # Sale price
        sale_price = product.get("sale_price")
        if sale_price is not None:
            mapped_data["salePrice"] = self._format_price(sale_price, currency)

            # Sale price effective date
            sale_start = product.get("sale_start_date")
            sale_end = product.get("sale_end_date")
            if sale_start and sale_end:
                mapped_data["salePriceEffectiveDate"] = f"{sale_start}/{sale_end}"

        # Identifiers
        gtin = product.get("barcode") or product.get("gtin")
        if gtin:
            gtin_clean = str(gtin).replace(" ", "").replace("-", "")
            if gtin_clean.isdigit() and len(gtin_clean) in {8, 12, 13, 14}:
                mapped_data["gtin"] = gtin_clean

        brand = product.get("brand")
        if brand:
            mapped_data["brand"] = str(brand)[:70]

        mpn = product.get("manufacturer_part_no") or product.get("mpn")
        if mpn:
            mapped_data["mpn"] = str(mpn)[:70]

        # Condition
        condition = product.get("condition")
        if condition:
            mapped_data["condition"] = self._map_condition(condition)
        else:
            mapped_data["condition"] = GoogleProductCondition.NEW.value

        # Product type/category
        product_type = product.get("item_group") or product.get("productType")
        if product_type:
            mapped_data["productType"] = str(product_type)[:750]

        google_category = product.get("googleProductCategory") or product.get("google_product_category_id")
        if google_category:
            mapped_data["googleProductCategory"] = str(google_category)

        # Apparel-specific fields
        color = product.get("color")
        if color:
            mapped_data["color"] = str(color)[:100]

        size = product.get("size")
        if size:
            if isinstance(size, list):
                mapped_data["sizes"] = [str(s) for s in size]
            else:
                mapped_data["sizes"] = [str(size)]

        material = product.get("material")
        if material:
            mapped_data["material"] = str(material)[:200]

        pattern = product.get("pattern")
        if pattern:
            mapped_data["pattern"] = str(pattern)[:100]

        age_group = product.get("age_group")
        if age_group:
            mapped_data["ageGroup"] = self._map_age_group(age_group)

        gender = product.get("gender")
        if gender:
            mapped_data["gender"] = self._map_gender(gender)

        # Weight for shipping
        weight = product.get("weight_per_unit") or product.get("net_weight") or product.get("weight")
        weight_unit = product.get("weight_unit", "kg")
        if weight:
            mapped_data["shippingWeight"] = self._format_weight(weight, weight_unit)

        # Channel and targeting
        mapped_data["channel"] = GoogleProductChannel.ONLINE.value
        mapped_data["targetCountry"] = self.target_country
        mapped_data["contentLanguage"] = self.content_language

        # Custom labels (for segmentation in Google Ads)
        for i in range(5):
            label_key = f"custom_label_{i}"
            label_value = product.get(label_key)
            if label_value:
                mapped_data[f"customLabel{i}"] = str(label_value)[:100]

        # Track unmapped fields
        mapped_pim_fields = set(PIM_TO_GOOGLE_FIELDS.keys())
        mapped_pim_fields.update({
            "offerId", "title", "description", "link", "imageLink", "image_url",
            "availability", "stock_status", "price", "standard_rate", "sale_price",
            "sale_start_date", "sale_end_date", "barcode", "gtin", "brand", "mpn",
            "manufacturer_part_no", "condition", "productType", "item_group",
            "googleProductCategory", "google_product_category_id", "color", "size",
            "material", "pattern", "age_group", "gender", "weight", "weight_unit",
            "currency", "website_url", "product_url",
        })
        mapped_pim_fields.update({f"custom_label_{i}" for i in range(5)})

        for field_name in product.keys():
            if field_name not in mapped_pim_fields and not field_name.startswith("_"):
                unmapped_fields.append(field_name)

        return MappingResult(
            product=product_id,
            mapped_data=mapped_data,
            unmapped_fields=unmapped_fields,
            channel=self.channel_code,
        )

    def _strip_html(self, text: str) -> str:
        """Strip HTML tags from text.

        Args:
            text: Text potentially containing HTML

        Returns:
            Plain text with HTML removed
        """
        import re
        # Remove HTML tags
        clean = re.sub(r'<[^>]+>', '', str(text))
        # Normalize whitespace
        clean = re.sub(r'\s+', ' ', clean).strip()
        return clean

    def _format_price(self, price: Any, currency: str = "USD") -> Dict:
        """Format price for Google API.

        Args:
            price: Price value (number or dict)
            currency: Currency code

        Returns:
            Price dict with value and currency
        """
        if isinstance(price, dict):
            return {
                "value": str(price.get("value", 0)),
                "currency": price.get("currency", currency),
            }

        try:
            value = float(price)
            return {
                "value": f"{value:.2f}",
                "currency": currency,
            }
        except (ValueError, TypeError):
            return {
                "value": "0.00",
                "currency": currency,
            }

    def _format_weight(self, weight: Any, unit: str = "kg") -> Dict:
        """Format weight for Google API.

        Args:
            weight: Weight value
            unit: Weight unit

        Returns:
            Weight dict with value and unit
        """
        unit_mapping = {
            "kg": "kg",
            "kilograms": "kg",
            "g": "g",
            "grams": "g",
            "lb": "lb",
            "lbs": "lb",
            "pounds": "lb",
            "oz": "oz",
            "ounces": "oz",
        }

        google_unit = unit_mapping.get(str(unit).lower(), "kg")

        try:
            value = float(weight)
            return {
                "value": f"{value:.3f}",
                "unit": google_unit,
            }
        except (ValueError, TypeError):
            return {
                "value": "0",
                "unit": google_unit,
            }

    def _map_availability(self, availability: str) -> str:
        """Map availability value to Google format.

        Args:
            availability: Availability string

        Returns:
            Google availability value
        """
        availability = str(availability).lower().replace(" ", "_").replace("-", "_")

        mapping = {
            "in_stock": GoogleProductAvailability.IN_STOCK.value,
            "instock": GoogleProductAvailability.IN_STOCK.value,
            "available": GoogleProductAvailability.IN_STOCK.value,
            "out_of_stock": GoogleProductAvailability.OUT_OF_STOCK.value,
            "outofstock": GoogleProductAvailability.OUT_OF_STOCK.value,
            "unavailable": GoogleProductAvailability.OUT_OF_STOCK.value,
            "preorder": GoogleProductAvailability.PREORDER.value,
            "pre_order": GoogleProductAvailability.PREORDER.value,
            "backorder": GoogleProductAvailability.BACKORDER.value,
            "back_order": GoogleProductAvailability.BACKORDER.value,
        }

        return mapping.get(availability, GoogleProductAvailability.IN_STOCK.value)

    def _map_condition(self, condition: str) -> str:
        """Map condition value to Google format.

        Args:
            condition: Condition string

        Returns:
            Google condition value
        """
        condition = str(condition).lower()

        mapping = {
            "new": GoogleProductCondition.NEW.value,
            "refurbished": GoogleProductCondition.REFURBISHED.value,
            "renewed": GoogleProductCondition.REFURBISHED.value,
            "used": GoogleProductCondition.USED.value,
        }

        return mapping.get(condition, GoogleProductCondition.NEW.value)

    def _map_age_group(self, age_group: str) -> str:
        """Map age group value to Google format.

        Args:
            age_group: Age group string

        Returns:
            Google age group value
        """
        age_group = str(age_group).lower()

        mapping = {
            "newborn": GoogleAgeGroup.NEWBORN.value,
            "infant": GoogleAgeGroup.INFANT.value,
            "baby": GoogleAgeGroup.INFANT.value,
            "toddler": GoogleAgeGroup.TODDLER.value,
            "kids": GoogleAgeGroup.KIDS.value,
            "children": GoogleAgeGroup.KIDS.value,
            "adult": GoogleAgeGroup.ADULT.value,
            "adults": GoogleAgeGroup.ADULT.value,
        }

        return mapping.get(age_group, GoogleAgeGroup.ADULT.value)

    def _map_gender(self, gender: str) -> str:
        """Map gender value to Google format.

        Args:
            gender: Gender string

        Returns:
            Google gender value
        """
        gender = str(gender).lower()

        mapping = {
            "male": GoogleGender.MALE.value,
            "men": GoogleGender.MALE.value,
            "man": GoogleGender.MALE.value,
            "female": GoogleGender.FEMALE.value,
            "women": GoogleGender.FEMALE.value,
            "woman": GoogleGender.FEMALE.value,
            "unisex": GoogleGender.UNISEX.value,
        }

        return mapping.get(gender, GoogleGender.UNISEX.value)

    # =========================================================================
    # Payload Generation
    # =========================================================================

    def generate_payload(self, products: List[Dict]) -> Dict:
        """Generate Content API batch payload for products.

        Creates the batch request structure compatible with Google's
        products.custombatch endpoint.

        Args:
            products: List of mapped product data dictionaries

        Returns:
            Dictionary with batch entries ready for API submission
        """
        batch_id = str(uuid.uuid4())

        payload = {
            "entries": [],
            "_metadata": {
                "batch_id": batch_id,
                "created_at": datetime.now().isoformat(),
                "product_count": len(products),
                "merchant_id": self.merchant_id,
            },
        }

        for idx, product in enumerate(products):
            entry = {
                "batchId": idx,
                "merchantId": self.merchant_id,
                "method": "insert",  # insert or update based on existence
                "product": product,
            }
            payload["entries"].append(entry)

        return payload

    # =========================================================================
    # Publishing Methods
    # =========================================================================

    def publish(self, products: List[Dict]) -> PublishResult:
        """Publish products to Google Merchant Center.

        Handles the complete publishing workflow including validation,
        mapping, and batch API submission.

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

            # Map products to Google format
            mapped_products = []
            for product in products:
                mapping_result = self.map_attributes(product)
                mapped_products.append(mapping_result.mapped_data)

            # Build service
            service = self._build_service()

            # Process in batches (max 1000 per batch)
            max_batch_size = GOOGLE_RATE_LIMITS["products_custombatch"]["max_entries_per_batch"]
            external_ids = []

            for batch_start in range(0, len(mapped_products), max_batch_size):
                batch_end = min(batch_start + max_batch_size, len(mapped_products))
                batch_products = mapped_products[batch_start:batch_end]

                # Generate payload for this batch
                payload = self.generate_payload(batch_products)

                try:
                    # Submit batch
                    result = self._submit_batch(service, payload)

                    for entry_result in result.get("entries", []):
                        products_submitted += 1

                        if "errors" in entry_result and entry_result["errors"]:
                            products_failed += 1
                            for error in entry_result["errors"]["errors"]:
                                errors.append({
                                    "batch_id": entry_result.get("batchId"),
                                    "message": error.get("message", "Unknown error"),
                                    "domain": error.get("domain"),
                                    "reason": error.get("reason"),
                                })
                        elif entry_result.get("product"):
                            products_succeeded += 1
                            product_data = entry_result["product"]
                            if product_data.get("id"):
                                external_ids.append(product_data["id"])

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
                    products_failed += len(batch_products)
                    products_submitted += len(batch_products)
                    errors.append({"message": f"Batch submission error: {str(e)}"})

            # Determine final status
            if products_failed == 0:
                status = PublishStatus.COMPLETED
                success = True
            elif products_succeeded > 0:
                status = PublishStatus.PARTIAL
                success = True  # Partial success
            else:
                status = PublishStatus.FAILED
                success = False

            # Track job
            self._job_tracker[job_id] = GoogleBatchJob(
                job_id=job_id,
                merchant_id=self.merchant_id,
                operation_type="insert",
                status="completed" if success else "failed",
                completed_at=datetime.now(),
                total_entries=products_submitted,
                successful_entries=products_succeeded,
                failed_entries=products_failed,
                errors=errors,
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

    def _submit_batch(self, service, payload: Dict) -> Dict:
        """Submit a batch of products to Google Merchant Center.

        Args:
            service: Google API service object
            payload: Batch payload with entries

        Returns:
            Batch response from API
        """
        request = service.products().custombatch(body={"entries": payload["entries"]})
        return self._execute_api_call(request)

    # =========================================================================
    # Status Methods
    # =========================================================================

    def get_status(self, job_id: str) -> StatusResult:
        """Check the status of a publish job.

        For Google Merchant Center, batch operations return synchronously,
        so this primarily checks our internal job tracker.

        Args:
            job_id: The job ID from publish()

        Returns:
            StatusResult with current job status and progress
        """
        # Check internal job tracker
        if job_id in self._job_tracker:
            job = self._job_tracker[job_id]

            status_mapping = {
                "pending": PublishStatus.PENDING,
                "completed": PublishStatus.COMPLETED,
                "failed": PublishStatus.FAILED,
                "partial": PublishStatus.PARTIAL,
            }

            progress = 1.0 if job.status == "completed" else 0.5
            if job.total_entries > 0:
                progress = job.successful_entries / job.total_entries

            return StatusResult(
                job_id=job_id,
                status=status_mapping.get(job.status, PublishStatus.IN_PROGRESS),
                progress=progress,
                products_processed=job.successful_entries + job.failed_entries,
                products_total=job.total_entries,
                errors=job.errors,
                channel=self.channel_code,
                completed_at=job.completed_at,
            )

        # Job not found, assume completed
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
        """Test the connection to Google Merchant Center.

        Returns:
            Dictionary with connection status and account info
        """
        import frappe

        try:
            if not self.merchant_id:
                return {
                    "success": False,
                    "message": "Merchant ID is not configured",
                }

            service = self._build_service()

            # Try to get account info
            request = service.accounts().get(
                merchantId=self.merchant_id,
                accountId=self.merchant_id,
            )
            account = self._execute_api_call(request)

            return {
                "success": True,
                "message": "Connection successful",
                "account_name": account.get("name"),
                "account_id": account.get("id"),
                "website_url": account.get("websiteUrl"),
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

    def get_product(self, product_id: str) -> Optional[Dict]:
        """Retrieve a product from Google Merchant Center.

        Args:
            product_id: The product ID (offerId) to retrieve

        Returns:
            Product data dict if found, None otherwise
        """
        try:
            service = self._build_service()

            # Product ID format: online:en:US:SKU123
            full_id = f"online:{self.content_language}:{self.target_country}:{product_id}"

            request = service.products().get(
                merchantId=self.merchant_id,
                productId=full_id,
            )
            return self._execute_api_call(request)

        except Exception:
            return None

    def delete_product(self, product_id: str) -> bool:
        """Delete a product from Google Merchant Center.

        Args:
            product_id: The product ID (offerId) to delete

        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            service = self._build_service()

            # Product ID format: online:en:US:SKU123
            full_id = f"online:{self.content_language}:{self.target_country}:{product_id}"

            request = service.products().delete(
                merchantId=self.merchant_id,
                productId=full_id,
            )
            self._execute_api_call(request)
            return True

        except Exception:
            return False

    def list_products(self, max_results: int = 250, page_token: str = None) -> Dict:
        """List products in Google Merchant Center.

        Args:
            max_results: Maximum number of products to return
            page_token: Token for pagination

        Returns:
            Dict with products list and next page token
        """
        try:
            service = self._build_service()

            request = service.products().list(
                merchantId=self.merchant_id,
                maxResults=min(max_results, 250),
                pageToken=page_token,
            )
            response = self._execute_api_call(request)

            return {
                "products": response.get("resources", []),
                "next_page_token": response.get("nextPageToken"),
            }

        except Exception as e:
            return {
                "products": [],
                "error": str(e),
            }


# =============================================================================
# Register Adapter
# =============================================================================

register_adapter("google_merchant", GoogleMerchantAdapter)
register_adapter("google", GoogleMerchantAdapter)
register_adapter("google_shopping", GoogleMerchantAdapter)
register_adapter("merchant_center", GoogleMerchantAdapter)
