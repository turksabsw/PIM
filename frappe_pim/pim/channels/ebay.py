"""
eBay Channel Adapter

Provides adapters for eBay Marketplace integration using the eBay Sell APIs
(Inventory API, Fulfillment API, Account API).

Features:
- Support for all eBay global marketplaces (US, UK, DE, AU, CA, FR, IT, ES, etc.)
- OAuth 2.0 authentication with token refresh
- Rate limiting with per-resource quota tracking
- Bulk listing operations via Inventory API
- Comprehensive product validation against eBay requirements
- Attribute mapping to eBay catalog format
- Support for both fixed-price and auction listings
- Fulfillment policies and shipping configurations

Note: frappe imports are deferred to function/method level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional
import hashlib
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
# eBay-Specific Constants
# =============================================================================

class EbayMarketplace(str, Enum):
    """eBay marketplace identifiers (Global IDs)"""
    US = "EBAY_US"
    UK = "EBAY_GB"
    DE = "EBAY_DE"
    AU = "EBAY_AU"
    CA = "EBAY_CA"
    FR = "EBAY_FR"
    IT = "EBAY_IT"
    ES = "EBAY_ES"
    AT = "EBAY_AT"
    BE_FR = "EBAY_BE_FR"
    BE_NL = "EBAY_BE_NL"
    CH = "EBAY_CH"
    IE = "EBAY_IE"
    NL = "EBAY_NL"
    PL = "EBAY_PL"
    SG = "EBAY_SG"
    HK = "EBAY_HK"
    PH = "EBAY_PH"
    MY = "EBAY_MY"
    MOTORS_US = "EBAY_MOTORS_US"


class EbayCondition(str, Enum):
    """eBay item condition IDs"""
    NEW = "NEW"
    NEW_OTHER = "NEW_OTHER"
    NEW_WITH_DEFECTS = "NEW_WITH_DEFECTS"
    CERTIFIED_REFURBISHED = "CERTIFIED_REFURBISHED"
    SELLER_REFURBISHED = "SELLER_REFURBISHED"
    LIKE_NEW = "LIKE_NEW"
    VERY_GOOD = "VERY_GOOD"
    GOOD = "GOOD"
    ACCEPTABLE = "ACCEPTABLE"
    FOR_PARTS = "FOR_PARTS_OR_NOT_WORKING"


# eBay condition ID mapping (numeric IDs used in API)
EBAY_CONDITION_IDS = {
    "NEW": 1000,
    "NEW_OTHER": 1500,
    "NEW_WITH_DEFECTS": 1750,
    "CERTIFIED_REFURBISHED": 2000,
    "SELLER_REFURBISHED": 2500,
    "LIKE_NEW": 2750,
    "VERY_GOOD": 3000,
    "GOOD": 4000,
    "ACCEPTABLE": 5000,
    "FOR_PARTS_OR_NOT_WORKING": 7000,
}


class EbayListingFormat(str, Enum):
    """eBay listing format types"""
    FIXED_PRICE = "FIXED_PRICE"
    AUCTION = "AUCTION"


class EbayListingStatus(str, Enum):
    """eBay listing status"""
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    EBAY_ENDED = "EBAY_ENDED"
    OUT_OF_STOCK = "OUT_OF_STOCK"


class EbayFulfillmentType(str, Enum):
    """eBay fulfillment type"""
    SHIP_TO_HOME = "SHIP_TO_HOME"
    PICKUP = "PICKUP"
    FULFILLMENT_BY_EBAY = "FULFILLMENT_BY_EBAY"


# eBay API rate limits per resource (calls per day)
EBAY_RATE_LIMITS = {
    "inventory_item": 5000,
    "offer": 5000,
    "listing": 5000,
    "fulfillment": 5000,
    "account": 5000,
    "default": 5000,
}

# eBay API calls per second limits
EBAY_CALLS_PER_SECOND = {
    "inventory_item": 5,
    "offer": 5,
    "listing": 5,
    "fulfillment": 5,
    "account": 5,
    "default": 5,
}


# =============================================================================
# eBay-Specific Data Classes
# =============================================================================

@dataclass
class EbayQuotaState:
    """Tracks eBay API quota state per resource"""
    resource: str
    calls_made: int = 0
    daily_limit: int = 5000
    calls_per_second: int = 5
    last_second_calls: int = 0
    last_second_start: datetime = field(default_factory=datetime.now)
    window_start: datetime = field(default_factory=datetime.now)
    retry_after: datetime = None
    last_request: datetime = None

    def is_limited(self) -> bool:
        """Check if currently rate limited"""
        if self.retry_after and datetime.now() < self.retry_after:
            return True

        # Reset daily window if expired
        now = datetime.now()
        if now.date() > self.window_start.date():
            self.calls_made = 0
            self.window_start = now
            return False

        # Check per-second limit
        if (now - self.last_second_start).total_seconds() >= 1:
            self.last_second_calls = 0
            self.last_second_start = now

        return (self.calls_made >= self.daily_limit or
                self.last_second_calls >= self.calls_per_second)

    def record_request(self) -> None:
        """Record a request for rate limiting"""
        now = datetime.now()
        self.calls_made += 1
        self.last_request = now

        # Reset per-second counter if needed
        if (now - self.last_second_start).total_seconds() >= 1:
            self.last_second_calls = 0
            self.last_second_start = now

        self.last_second_calls += 1

    def wait_time(self) -> float:
        """Calculate wait time before next request"""
        if self.retry_after:
            delta = self.retry_after - datetime.now()
            if delta.total_seconds() > 0:
                return delta.total_seconds()

        # If per-second limit reached, wait for next second
        if self.last_second_calls >= self.calls_per_second:
            delta = (self.last_second_start + timedelta(seconds=1)) - datetime.now()
            return max(0, delta.total_seconds())

        return 0


@dataclass
class EbayToken:
    """eBay OAuth token with expiration tracking"""
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 7200  # Default 2 hours
    refresh_token: str = None
    refresh_token_expires_in: int = 47304000  # ~18 months
    obtained_at: datetime = field(default_factory=datetime.now)

    def is_expired(self) -> bool:
        """Check if token is expired or about to expire (5 min buffer)"""
        expiration = self.obtained_at + timedelta(seconds=self.expires_in - 300)
        return datetime.now() >= expiration

    def needs_refresh(self) -> bool:
        """Check if token needs refresh (10 min before expiry)"""
        refresh_time = self.obtained_at + timedelta(seconds=self.expires_in - 600)
        return datetime.now() >= refresh_time


# =============================================================================
# eBay Required Fields and Validation Rules
# =============================================================================

# Required fields for eBay inventory items
EBAY_REQUIRED_FIELDS = {
    "sku",
    "title",
    "description",
    "condition",
    "availability",
}

# Required for offers
EBAY_OFFER_REQUIRED = {
    "sku",
    "marketplaceId",
    "format",
    "listingPolicies",
    "pricingSummary",
}

# Optional but recommended fields
EBAY_RECOMMENDED_FIELDS = {
    "product.title",
    "product.description",
    "product.brand",
    "product.mpn",
    "product.imageUrls",
    "product.upc",
    "product.ean",
    "product.isbn",
}

# Field length limits
EBAY_FIELD_LIMITS = {
    "sku": 50,
    "title": 80,
    "description": 500000,  # HTML supported
    "brand": 65,
    "mpn": 65,
}

# PIM to eBay field mappings
PIM_TO_EBAY_FIELDS = {
    "item_code": "sku",
    "item_name": "product.title",
    "brand": "product.brand",
    "description": "product.description",
    "pim_title": "product.title",
    "pim_description": "product.description",
    "barcode": "product.upc",
    "standard_rate": "pricingSummary.price.value",
    "image": "product.imageUrls",
    "manufacturer": "product.brand",
    "manufacturer_part_number": "product.mpn",
    "country_of_origin": "packageWeightAndSize.shipFromCountry",
    "weight_per_unit": "packageWeightAndSize.weight.value",
    "short_description": "product.subtitle",
}

# eBay marketplace site IDs
EBAY_SITE_IDS = {
    "EBAY_US": 0,
    "EBAY_GB": 3,
    "EBAY_DE": 77,
    "EBAY_AU": 15,
    "EBAY_CA": 2,
    "EBAY_FR": 71,
    "EBAY_IT": 101,
    "EBAY_ES": 186,
    "EBAY_AT": 16,
    "EBAY_CH": 193,
    "EBAY_IE": 205,
    "EBAY_NL": 146,
    "EBAY_PL": 212,
    "EBAY_SG": 216,
    "EBAY_HK": 201,
}


# =============================================================================
# eBay Adapter Implementation
# =============================================================================

class EbayAdapter(ChannelAdapter):
    """
    eBay Marketplace adapter for seller integration.

    Uses eBay Sell APIs for:
    - Inventory Item management (Inventory API)
    - Offer management and publishing
    - Listing management
    - Order fulfillment

    Supports all eBay global marketplaces.
    """

    channel_code: str = "ebay"
    channel_name: str = "eBay"

    # eBay-specific settings
    default_requests_per_minute: int = 300  # 5 per second
    default_requests_per_second: float = 5.0
    max_retry_attempts: int = 5
    base_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 120.0

    # API endpoints
    API_ENDPOINTS = {
        "production": "https://api.ebay.com",
        "sandbox": "https://api.sandbox.ebay.com",
    }

    AUTH_ENDPOINTS = {
        "production": "https://api.ebay.com/identity/v1/oauth2/token",
        "sandbox": "https://api.sandbox.ebay.com/identity/v1/oauth2/token",
    }

    def __init__(self, channel_doc: Any = None):
        """Initialize eBay adapter.

        Args:
            channel_doc: Channel Frappe document with eBay credentials
        """
        super().__init__(channel_doc)
        self._token: Optional[EbayToken] = None
        self._quota_states: Dict[str, EbayQuotaState] = {}
        self._marketplace: str = None
        self._environment: str = None

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def marketplace(self) -> str:
        """Get the eBay marketplace ID."""
        if self._marketplace:
            return self._marketplace

        # Get from channel config or default to US
        marketplace = self.config.get("marketplace", "EBAY_US")
        try:
            self._marketplace = EbayMarketplace[marketplace.replace("EBAY_", "")].value
        except KeyError:
            # Try direct value
            if marketplace in [m.value for m in EbayMarketplace]:
                self._marketplace = marketplace
            else:
                self._marketplace = EbayMarketplace.US.value

        return self._marketplace

    @property
    def environment(self) -> str:
        """Get the API environment (production or sandbox)."""
        if self._environment:
            return self._environment

        self._environment = self.config.get("environment", "production").lower()
        if self._environment not in ("production", "sandbox"):
            self._environment = "production"

        return self._environment

    @property
    def api_endpoint(self) -> str:
        """Get the API endpoint for the configured environment."""
        return self.API_ENDPOINTS.get(self.environment, self.API_ENDPOINTS["production"])

    @property
    def auth_endpoint(self) -> str:
        """Get the authentication endpoint."""
        return self.AUTH_ENDPOINTS.get(self.environment, self.AUTH_ENDPOINTS["production"])

    # =========================================================================
    # Authentication Methods
    # =========================================================================

    def _get_ebay_credentials(self) -> Dict:
        """Get eBay-specific credentials from channel document.

        Returns:
            Dictionary with:
            - client_id: eBay App ID (Client ID)
            - client_secret: eBay Cert ID (Client Secret)
            - refresh_token: OAuth refresh token
            - dev_id: eBay Dev ID (optional)
        """
        credentials = self.credentials

        ebay_creds = {
            "client_id": credentials.get("api_key"),
            "client_secret": credentials.get("api_secret"),
            "refresh_token": credentials.get("refresh_token"),
            "dev_id": credentials.get("dev_id"),
        }

        return ebay_creds

    def _get_access_token(self) -> str:
        """Get a valid eBay access token, refreshing if necessary.

        Returns:
            Valid access token string

        Raises:
            AuthenticationError: If token request fails
        """
        import requests

        # Return cached token if still valid
        if self._token and not self._token.is_expired():
            return self._token.access_token

        ebay_creds = self._get_ebay_credentials()

        if not ebay_creds.get("client_id") or not ebay_creds.get("client_secret"):
            raise AuthenticationError(
                "eBay client ID and secret not configured",
                channel=self.channel_code,
            )

        # Check if we have a refresh token
        refresh_token = ebay_creds.get("refresh_token")
        if not refresh_token:
            raise AuthenticationError(
                "eBay refresh token not configured. OAuth consent required.",
                channel=self.channel_code,
            )

        # Request new access token using refresh token
        import base64
        auth_string = f"{ebay_creds['client_id']}:{ebay_creds['client_secret']}"
        auth_header = base64.b64encode(auth_string.encode()).decode()

        headers = {
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": "https://api.ebay.com/oauth/api_scope/sell.inventory "
                     "https://api.ebay.com/oauth/api_scope/sell.fulfillment "
                     "https://api.ebay.com/oauth/api_scope/sell.account",
        }

        try:
            response = requests.post(
                self.auth_endpoint,
                headers=headers,
                data=data,
                timeout=30,
            )

            if response.status_code != 200:
                error_data = response.json() if response.text else {}
                raise AuthenticationError(
                    f"eBay token refresh failed: {response.status_code} - "
                    f"{error_data.get('error_description', response.text)}",
                    channel=self.channel_code,
                )

            token_response = response.json()
            self._token = EbayToken(
                access_token=token_response["access_token"],
                token_type=token_response.get("token_type", "Bearer"),
                expires_in=token_response.get("expires_in", 7200),
                refresh_token=refresh_token,
            )

            return self._token.access_token

        except requests.exceptions.RequestException as e:
            raise AuthenticationError(
                f"Failed to connect to eBay token endpoint: {str(e)}",
                channel=self.channel_code,
            )

    def _get_auth_headers(self) -> Dict:
        """Build authentication headers for eBay API requests.

        Returns:
            Dictionary of HTTP headers including authorization
        """
        access_token = self._get_access_token()

        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-EBAY-C-MARKETPLACE-ID": self.marketplace,
            "Content-Language": self._get_content_language(),
        }

    def _get_content_language(self) -> str:
        """Get content language header based on marketplace.

        Returns:
            Content language string (e.g., 'en-US', 'de-DE')
        """
        language_map = {
            "EBAY_US": "en-US",
            "EBAY_GB": "en-GB",
            "EBAY_DE": "de-DE",
            "EBAY_AU": "en-AU",
            "EBAY_CA": "en-CA",
            "EBAY_FR": "fr-FR",
            "EBAY_IT": "it-IT",
            "EBAY_ES": "es-ES",
            "EBAY_AT": "de-AT",
            "EBAY_CH": "de-CH",
            "EBAY_NL": "nl-NL",
            "EBAY_PL": "pl-PL",
        }
        return language_map.get(self.marketplace, "en-US")

    # =========================================================================
    # Rate Limiting Methods
    # =========================================================================

    def _get_quota_state(self, resource: str) -> EbayQuotaState:
        """Get or create quota state for a resource.

        Args:
            resource: The API resource category (inventory_item, offer, etc.)

        Returns:
            EbayQuotaState instance for the resource
        """
        if resource not in self._quota_states:
            daily_limit = EBAY_RATE_LIMITS.get(resource, EBAY_RATE_LIMITS["default"])
            calls_per_second = EBAY_CALLS_PER_SECOND.get(
                resource, EBAY_CALLS_PER_SECOND["default"]
            )

            self._quota_states[resource] = EbayQuotaState(
                resource=resource,
                daily_limit=daily_limit,
                calls_per_second=calls_per_second,
            )

        return self._quota_states[resource]

    def handle_rate_limiting(self, response: Any = None) -> None:
        """Handle eBay API rate limiting from response headers.

        Parses X-RateLimit headers and updates internal quota tracking.

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
                "eBay API rate limit exceeded",
                channel=self.channel_code,
                retry_after=retry_after,
                details={
                    "status_code": 429,
                    "retry_after": retry_after,
                },
            )

        # Parse eBay rate limit headers
        if hasattr(response, 'headers'):
            remaining = response.headers.get("X-RateLimit-Remaining")
            limit = response.headers.get("X-RateLimit-Limit")
            reset = response.headers.get("X-RateLimit-Reset")

            if remaining is not None and int(remaining) == 0:
                reset_time = int(reset) if reset else 60
                raise RateLimitError(
                    "eBay API rate limit exhausted",
                    channel=self.channel_code,
                    retry_after=reset_time,
                    quota_remaining=0,
                )

    def _wait_for_quota(self, resource: str) -> None:
        """Wait if quota for resource is exhausted.

        Args:
            resource: The API resource category

        Raises:
            RateLimitError: If wait time exceeds maximum
        """
        quota_state = self._get_quota_state(resource)
        wait_time = quota_state.wait_time()

        if wait_time > 0:
            if wait_time > self.max_backoff_seconds:
                raise RateLimitError(
                    f"eBay API quota exhausted for {resource}, "
                    f"wait time ({wait_time}s) exceeds maximum",
                    channel=self.channel_code,
                    retry_after=int(wait_time),
                )
            time.sleep(wait_time)

        quota_state.record_request()

    # =========================================================================
    # Validation Methods
    # =========================================================================

    def validate_product(self, product: Dict) -> ValidationResult:
        """Validate a product against eBay's listing requirements.

        Checks required fields, field length limits, GTIN format,
        and other eBay-specific requirements.

        Args:
            product: Product data dictionary in PIM format

        Returns:
            ValidationResult with validation status and any errors/warnings
        """
        errors = []
        warnings = []
        product_id = product.get("item_code", product.get("sku", "unknown"))

        # Check required fields (SKU)
        sku = product.get("item_code") or product.get("sku")
        if not sku:
            errors.append({
                "field": "sku",
                "message": "SKU is required for eBay listings",
                "rule": "required",
            })
        elif len(str(sku)) > EBAY_FIELD_LIMITS["sku"]:
            errors.append({
                "field": "sku",
                "message": f"SKU exceeds maximum length of {EBAY_FIELD_LIMITS['sku']} characters",
                "value": str(sku),
                "rule": "max_length",
            })

        # Check title (required)
        title = product.get("pim_title") or product.get("item_name")
        if not title:
            errors.append({
                "field": "title",
                "message": "Product title is required for eBay listings",
                "rule": "required",
            })
        elif len(str(title)) > EBAY_FIELD_LIMITS["title"]:
            errors.append({
                "field": "title",
                "message": f"Title exceeds eBay's maximum of {EBAY_FIELD_LIMITS['title']} characters",
                "value": f"{len(str(title))} characters",
                "rule": "max_length",
            })

        # Check description
        description = product.get("pim_description") or product.get("description")
        if not description:
            warnings.append({
                "field": "description",
                "message": "Product description is recommended for better visibility",
                "rule": "recommended",
            })
        elif len(str(description)) > EBAY_FIELD_LIMITS["description"]:
            errors.append({
                "field": "description",
                "message": f"Description exceeds maximum length",
                "value": f"{len(str(description))} characters",
                "rule": "max_length",
            })

        # Validate condition
        condition = product.get("condition", "NEW")
        valid_conditions = [c.value for c in EbayCondition]
        if condition.upper() not in valid_conditions:
            warnings.append({
                "field": "condition",
                "message": f"Condition '{condition}' may need mapping to eBay condition",
                "value": condition,
                "rule": "valid_condition",
            })

        # Validate GTIN (UPC/EAN/ISBN) if provided
        gtin = product.get("barcode") or product.get("gtin") or product.get("upc") or product.get("ean")
        if gtin:
            gtin_error = self._validate_gtin(gtin)
            if gtin_error:
                errors.append(gtin_error)
        else:
            # eBay strongly recommends product identifiers
            warnings.append({
                "field": "productIdentifier",
                "message": "UPC/EAN/ISBN is strongly recommended for eBay catalog matching",
                "rule": "recommended",
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
                # eBay minimum price check (varies by category)
                if price_val < 0.99:
                    warnings.append({
                        "field": "price",
                        "message": "Very low prices may have limited visibility on eBay",
                        "value": str(price),
                        "rule": "min_price_warning",
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
                "message": "Price is required for eBay listings",
                "rule": "required",
            })

        # Check brand and MPN
        brand = product.get("brand") or product.get("manufacturer")
        mpn = product.get("manufacturer_part_number") or product.get("mpn")

        if not brand:
            warnings.append({
                "field": "brand",
                "message": "Brand is recommended for better catalog matching",
                "rule": "recommended",
            })
        elif len(str(brand)) > EBAY_FIELD_LIMITS["brand"]:
            errors.append({
                "field": "brand",
                "message": f"Brand exceeds maximum of {EBAY_FIELD_LIMITS['brand']} characters",
                "rule": "max_length",
            })

        if not mpn and brand:
            warnings.append({
                "field": "mpn",
                "message": "MPN is recommended when brand is provided",
                "rule": "recommended",
            })

        # Validate images
        images = product.get("images") or product.get("image")
        if images:
            image_warnings = self._validate_images(images)
            warnings.extend(image_warnings)
        else:
            errors.append({
                "field": "imageUrls",
                "message": "At least one product image is required for eBay listings",
                "rule": "required",
            })

        # Check quantity
        quantity = product.get("quantity") or product.get("stock_qty", 0)
        try:
            qty = int(quantity) if quantity else 0
            if qty < 0:
                errors.append({
                    "field": "quantity",
                    "message": "Quantity cannot be negative",
                    "value": str(quantity),
                    "rule": "non_negative",
                })
        except (ValueError, TypeError):
            errors.append({
                "field": "quantity",
                "message": "Quantity must be a valid integer",
                "value": str(quantity),
                "rule": "integer",
            })

        return ValidationResult(
            is_valid=len(errors) == 0,
            product=product_id,
            errors=errors,
            warnings=warnings,
            channel=self.channel_code,
        )

    def _validate_gtin(self, gtin: str) -> Optional[Dict]:
        """Validate GTIN format and check digit.

        Args:
            gtin: GTIN string (UPC, EAN, ISBN)

        Returns:
            Error dict if invalid, None if valid
        """
        # Remove any spaces or dashes
        gtin = str(gtin).replace(" ", "").replace("-", "")

        # Check length - eBay accepts UPC-A (12), EAN-13 (13), ISBN-10 (10), ISBN-13 (13)
        valid_lengths = {10, 12, 13, 14}
        if len(gtin) not in valid_lengths:
            return {
                "field": "productIdentifier",
                "message": f"GTIN must be 10, 12, 13, or 14 digits, got {len(gtin)}",
                "value": gtin,
                "rule": "gtin_length",
            }

        # Check if all digits (ISBN-10 can have X as check digit)
        if len(gtin) == 10:
            if not (gtin[:-1].isdigit() and (gtin[-1].isdigit() or gtin[-1].upper() == 'X')):
                return {
                    "field": "productIdentifier",
                    "message": "ISBN-10 format is invalid",
                    "value": gtin,
                    "rule": "gtin_format",
                }
        elif not gtin.isdigit():
            return {
                "field": "productIdentifier",
                "message": "GTIN must contain only digits",
                "value": gtin,
                "rule": "gtin_format",
            }

        # Validate check digit for UPC/EAN
        if len(gtin) in (12, 13, 14):
            if not self._validate_gtin_check_digit(gtin):
                return {
                    "field": "productIdentifier",
                    "message": "GTIN check digit is invalid",
                    "value": gtin,
                    "rule": "gtin_checksum",
                }

        return None

    def _validate_gtin_check_digit(self, gtin: str) -> bool:
        """Validate GTIN check digit using GS1 algorithm.

        Args:
            gtin: GTIN string with check digit

        Returns:
            True if check digit is valid
        """
        # Pad to 14 digits
        gtin = gtin.zfill(14)

        # Calculate check digit
        total = 0
        for i, digit in enumerate(gtin[:-1]):
            multiplier = 3 if i % 2 == 0 else 1
            total += int(digit) * multiplier

        calculated_check = (10 - (total % 10)) % 10
        actual_check = int(gtin[-1])

        return calculated_check == actual_check

    def _validate_images(self, images: Any) -> List[Dict]:
        """Validate product images against eBay requirements.

        eBay image requirements:
        - Minimum 500x500 pixels
        - Maximum 12 images
        - JPEG, PNG, GIF, or TIFF format
        - Main image should be on white background

        Args:
            images: Image data (URL, path, or list)

        Returns:
            List of warning dicts for image issues
        """
        warnings = []

        # Convert single image to list
        if isinstance(images, str):
            images = [images]

        if isinstance(images, list):
            if len(images) > 12:
                warnings.append({
                    "field": "imageUrls",
                    "message": f"eBay allows maximum 12 images, got {len(images)}. Extra images will be ignored.",
                    "rule": "max_images",
                })

            # Check image URLs
            for i, img in enumerate(images[:12]):
                if isinstance(img, str):
                    if not (img.startswith("http://") or img.startswith("https://")):
                        warnings.append({
                            "field": f"image_{i}",
                            "message": "Image URL should be an absolute HTTP/HTTPS URL",
                            "value": img[:50],
                            "rule": "image_url",
                        })

                    # Check for supported formats
                    lower_url = img.lower()
                    if not any(lower_url.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.tiff']):
                        warnings.append({
                            "field": f"image_{i}",
                            "message": "Image format may not be supported (use JPEG, PNG, GIF, or TIFF)",
                            "value": img[-20:] if len(img) > 20 else img,
                            "rule": "image_format",
                        })

        return warnings

    # =========================================================================
    # Mapping Methods
    # =========================================================================

    def map_attributes(self, product: Dict) -> MappingResult:
        """Map PIM product attributes to eBay Inventory API format.

        Converts internal field names to eBay's expected format
        and transforms values as needed.

        Args:
            product: Product data dictionary in PIM format

        Returns:
            MappingResult with mapped data and unmapped fields
        """
        product_id = product.get("item_code", product.get("sku", "unknown"))
        mapped_data = {}
        unmapped_fields = []

        # Build eBay inventory item structure
        sku = product.get("item_code") or product.get("sku")
        mapped_data["sku"] = sku

        # Product section
        product_section = {}

        # Title
        title = product.get("pim_title") or product.get("item_name")
        if title:
            product_section["title"] = title[:80]  # eBay limit

        # Description
        description = product.get("pim_description") or product.get("description")
        if description:
            product_section["description"] = description

        # Brand and MPN
        brand = product.get("brand") or product.get("manufacturer")
        if brand:
            product_section["brand"] = brand[:65]

        mpn = product.get("manufacturer_part_number") or product.get("mpn")
        if mpn:
            product_section["mpn"] = mpn[:65]

        # Product identifiers (UPC/EAN/ISBN)
        gtin = product.get("barcode") or product.get("gtin") or product.get("upc")
        ean = product.get("ean")
        isbn = product.get("isbn")

        if gtin:
            gtin_str = str(gtin).replace(" ", "").replace("-", "")
            if len(gtin_str) == 12:
                product_section["upc"] = [gtin_str]
            elif len(gtin_str) == 13:
                product_section["ean"] = [gtin_str]
        if ean and "ean" not in product_section:
            product_section["ean"] = [str(ean).replace(" ", "").replace("-", "")]
        if isbn:
            product_section["isbn"] = [str(isbn).replace(" ", "").replace("-", "")]

        # Images
        images = product.get("images") or product.get("image")
        if images:
            if isinstance(images, str):
                images = [images]
            product_section["imageUrls"] = images[:12]  # eBay max

        # Subtitle (optional)
        short_desc = product.get("short_description")
        if short_desc:
            product_section["subtitle"] = short_desc[:55]  # eBay subtitle limit

        # Aspects (item specifics)
        aspects = {}
        if brand:
            aspects["Brand"] = [brand]
        if mpn:
            aspects["MPN"] = [mpn]

        # Add custom attributes as aspects
        custom_attrs = product.get("attributes") or {}
        for key, value in custom_attrs.items():
            if value:
                aspects[key] = [str(value)] if not isinstance(value, list) else value

        if aspects:
            product_section["aspects"] = aspects

        mapped_data["product"] = product_section

        # Condition
        condition = product.get("condition", "NEW")
        try:
            ebay_condition = EbayCondition[condition.upper().replace(" ", "_").replace("-", "_")]
            mapped_data["condition"] = ebay_condition.value
            mapped_data["conditionId"] = EBAY_CONDITION_IDS.get(ebay_condition.value, 1000)
        except KeyError:
            mapped_data["condition"] = EbayCondition.NEW.value
            mapped_data["conditionId"] = 1000

        # Condition description (for non-new items)
        if condition.upper() != "NEW":
            condition_desc = product.get("condition_description")
            if condition_desc:
                mapped_data["conditionDescription"] = condition_desc[:1000]

        # Availability section
        quantity = product.get("quantity") or product.get("stock_qty", 0)
        mapped_data["availability"] = {
            "shipToLocationAvailability": {
                "quantity": int(quantity) if quantity else 0,
            }
        }

        # Package weight and size
        weight = product.get("weight_per_unit") or product.get("net_weight")
        if weight:
            weight_unit = product.get("weight_uom", "KILOGRAM")
            mapped_data["packageWeightAndSize"] = {
                "weight": {
                    "value": float(weight),
                    "unit": self._convert_weight_unit(weight_unit),
                }
            }

            # Add dimensions if available
            length = product.get("length")
            width = product.get("width")
            height = product.get("height")
            if length and width and height:
                dim_unit = product.get("dimension_uom", "CENTIMETER")
                mapped_data["packageWeightAndSize"]["dimensions"] = {
                    "length": float(length),
                    "width": float(width),
                    "height": float(height),
                    "unit": self._convert_dimension_unit(dim_unit),
                }

        # Offer section (for publishing)
        price = product.get("standard_rate") or product.get("price")
        if price is not None:
            currency = self._get_marketplace_currency()
            mapped_data["pricingSummary"] = {
                "price": {
                    "value": str(round(float(price), 2)),
                    "currency": currency,
                }
            }

        # Listing format
        listing_format = product.get("listing_format", "FIXED_PRICE")
        try:
            mapped_data["format"] = EbayListingFormat[listing_format.upper()].value
        except KeyError:
            mapped_data["format"] = EbayListingFormat.FIXED_PRICE.value

        # Marketplace
        mapped_data["marketplaceId"] = self.marketplace

        # Track unmapped fields
        known_fields = set(PIM_TO_EBAY_FIELDS.keys())
        known_fields.update({
            "condition", "condition_description", "listing_format",
            "quantity", "stock_qty", "currency", "images", "attributes",
            "length", "width", "height", "dimension_uom", "weight_uom",
            "ean", "isbn"
        })

        for pim_field in product.keys():
            if pim_field not in known_fields:
                unmapped_fields.append(pim_field)

        return MappingResult(
            product=product_id,
            mapped_data=mapped_data,
            unmapped_fields=unmapped_fields,
            channel=self.channel_code,
        )

    def _convert_weight_unit(self, unit: str) -> str:
        """Convert weight unit to eBay format.

        Args:
            unit: Weight unit from PIM

        Returns:
            eBay-compatible weight unit
        """
        unit_mapping = {
            "kg": "KILOGRAM",
            "kilogram": "KILOGRAM",
            "kilograms": "KILOGRAM",
            "g": "GRAM",
            "gram": "GRAM",
            "grams": "GRAM",
            "lb": "POUND",
            "lbs": "POUND",
            "pound": "POUND",
            "pounds": "POUND",
            "oz": "OUNCE",
            "ounce": "OUNCE",
            "ounces": "OUNCE",
        }

        return unit_mapping.get(unit.lower(), "KILOGRAM")

    def _convert_dimension_unit(self, unit: str) -> str:
        """Convert dimension unit to eBay format.

        Args:
            unit: Dimension unit from PIM

        Returns:
            eBay-compatible dimension unit
        """
        unit_mapping = {
            "cm": "CENTIMETER",
            "centimeter": "CENTIMETER",
            "centimeters": "CENTIMETER",
            "m": "METER",
            "meter": "METER",
            "meters": "METER",
            "in": "INCH",
            "inch": "INCH",
            "inches": "INCH",
            "ft": "FEET",
            "feet": "FEET",
            "foot": "FEET",
        }

        return unit_mapping.get(unit.lower(), "CENTIMETER")

    def _get_marketplace_currency(self) -> str:
        """Get the default currency for the marketplace.

        Returns:
            Currency code string
        """
        currency_map = {
            "EBAY_US": "USD",
            "EBAY_GB": "GBP",
            "EBAY_DE": "EUR",
            "EBAY_AU": "AUD",
            "EBAY_CA": "CAD",
            "EBAY_FR": "EUR",
            "EBAY_IT": "EUR",
            "EBAY_ES": "EUR",
            "EBAY_AT": "EUR",
            "EBAY_CH": "CHF",
            "EBAY_NL": "EUR",
            "EBAY_PL": "PLN",
            "EBAY_SG": "SGD",
            "EBAY_HK": "HKD",
        }
        return currency_map.get(self.marketplace, "USD")

    # =========================================================================
    # Payload Generation
    # =========================================================================

    def generate_payload(self, products: List[Dict]) -> Dict:
        """Generate eBay API compatible payload for inventory items.

        Creates inventory item requests for the Inventory API.

        Args:
            products: List of mapped product data dictionaries

        Returns:
            Dictionary with the complete payload for API submission
        """
        batch_id = str(uuid.uuid4())

        # Build requests array for bulk inventory update
        requests = []
        for product in products:
            request = {
                "sku": product.get("sku"),
                "product": product.get("product", {}),
                "condition": product.get("condition", "NEW"),
                "availability": product.get("availability", {}),
            }

            # Add optional fields
            if "packageWeightAndSize" in product:
                request["packageWeightAndSize"] = product["packageWeightAndSize"]

            if "conditionDescription" in product:
                request["conditionDescription"] = product["conditionDescription"]

            requests.append(request)

        payload = {
            "requests": requests,
            "_metadata": {
                "batch_id": batch_id,
                "created_at": datetime.now().isoformat(),
                "product_count": len(products),
                "marketplace": self.marketplace,
            },
        }

        return payload

    # =========================================================================
    # Publishing Methods
    # =========================================================================

    def publish(self, products: List[Dict]) -> PublishResult:
        """Publish products to eBay Marketplace.

        Handles the complete publishing workflow:
        1. Validate all products
        2. Map to eBay format
        3. Create/update inventory items
        4. Create offers for each item
        5. Publish offers to make items live

        Args:
            products: List of product data dictionaries in PIM format

        Returns:
            PublishResult with job status and any errors
        """
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
                    products_failed += 1

                # Continue with valid products
                valid_indices = [i for i, r in enumerate(validation_results) if r.is_valid]
                products = [products[i] for i in valid_indices]

                if not products:
                    return PublishResult(
                        success=False,
                        job_id=job_id,
                        status=PublishStatus.FAILED,
                        products_submitted=0,
                        products_failed=products_failed,
                        errors=errors,
                        channel=self.channel_code,
                    )

            # Map products to eBay format
            mapped_products = []
            for product in products:
                mapping_result = self.map_attributes(product)
                mapped_products.append(mapping_result.mapped_data)

            # Create/update inventory items
            inventory_result = self._create_inventory_items(mapped_products)

            if not inventory_result.get("success"):
                errors.append({
                    "message": inventory_result.get("error", "Failed to create inventory items"),
                    "details": inventory_result.get("details", {}),
                })

            # Track successful inventory items
            successful_skus = inventory_result.get("successful_skus", [])
            failed_skus = inventory_result.get("failed_skus", [])

            products_succeeded = len(successful_skus)
            products_failed += len(failed_skus)
            products_submitted = len(mapped_products)

            # Add errors for failed items
            for sku_error in inventory_result.get("errors", []):
                errors.append(sku_error)

            # Create and publish offers for successful items
            if successful_skus:
                offer_result = self._create_and_publish_offers(
                    [p for p in mapped_products if p.get("sku") in successful_skus]
                )

                if not offer_result.get("success"):
                    # Partial success - inventory created but offers failed
                    errors.append({
                        "message": offer_result.get("error", "Failed to publish offers"),
                        "details": offer_result.get("details", {}),
                    })

                # Add offer errors
                for offer_error in offer_result.get("errors", []):
                    errors.append(offer_error)

            self._log_publish_event("submit_complete", {
                "job_id": job_id,
                "products_submitted": products_submitted,
                "products_succeeded": products_succeeded,
                "products_failed": products_failed,
            })

            return PublishResult(
                success=products_succeeded > 0,
                job_id=job_id,
                status=PublishStatus.COMPLETED if products_failed == 0 else PublishStatus.PARTIAL,
                products_submitted=products_submitted,
                products_succeeded=products_succeeded,
                products_failed=products_failed,
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

    def _create_inventory_items(self, products: List[Dict]) -> Dict:
        """Create or update inventory items via eBay Inventory API.

        Args:
            products: List of mapped product data

        Returns:
            Dict with success status, successful/failed SKUs, and errors
        """
        import requests

        successful_skus = []
        failed_skus = []
        errors = []

        for product in products:
            try:
                self._wait_for_quota("inventory_item")

                sku = product.get("sku")
                inventory_url = f"{self.api_endpoint}/sell/inventory/v1/inventory_item/{sku}"
                headers = self._get_auth_headers()

                # Build inventory item payload
                payload = {
                    "product": product.get("product", {}),
                    "condition": product.get("condition", "NEW"),
                    "availability": product.get("availability", {}),
                }

                if "packageWeightAndSize" in product:
                    payload["packageWeightAndSize"] = product["packageWeightAndSize"]

                if "conditionDescription" in product:
                    payload["conditionDescription"] = product["conditionDescription"]

                response = requests.put(
                    inventory_url,
                    headers=headers,
                    json=payload,
                    timeout=30,
                )

                self.handle_rate_limiting(response)

                if response.status_code in (200, 201, 204):
                    successful_skus.append(sku)
                else:
                    failed_skus.append(sku)
                    error_data = response.json() if response.text else {}
                    errors.append({
                        "sku": sku,
                        "message": error_data.get("message", f"HTTP {response.status_code}"),
                        "details": error_data.get("errors", []),
                    })

            except Exception as e:
                sku = product.get("sku", "unknown")
                failed_skus.append(sku)
                errors.append({
                    "sku": sku,
                    "message": str(e),
                })

        return {
            "success": len(failed_skus) == 0,
            "successful_skus": successful_skus,
            "failed_skus": failed_skus,
            "errors": errors,
        }

    def _create_and_publish_offers(self, products: List[Dict]) -> Dict:
        """Create offers and publish them to make listings live.

        Args:
            products: List of mapped product data with successful inventory items

        Returns:
            Dict with success status and errors
        """
        import requests

        successful_offers = []
        errors = []

        for product in products:
            try:
                sku = product.get("sku")

                # Create offer
                offer_result = self._create_offer(product)

                if offer_result.get("success"):
                    offer_id = offer_result.get("offer_id")

                    # Publish the offer
                    publish_result = self._publish_offer(offer_id)

                    if publish_result.get("success"):
                        successful_offers.append(sku)
                    else:
                        errors.append({
                            "sku": sku,
                            "message": publish_result.get("error", "Failed to publish offer"),
                            "offer_id": offer_id,
                        })
                else:
                    errors.append({
                        "sku": sku,
                        "message": offer_result.get("error", "Failed to create offer"),
                    })

            except Exception as e:
                errors.append({
                    "sku": product.get("sku", "unknown"),
                    "message": str(e),
                })

        return {
            "success": len(errors) == 0,
            "successful_offers": successful_offers,
            "errors": errors,
        }

    def _create_offer(self, product: Dict) -> Dict:
        """Create an offer for an inventory item.

        Args:
            product: Mapped product data

        Returns:
            Dict with success status and offer_id
        """
        import requests

        try:
            self._wait_for_quota("offer")

            offer_url = f"{self.api_endpoint}/sell/inventory/v1/offer"
            headers = self._get_auth_headers()

            payload = {
                "sku": product.get("sku"),
                "marketplaceId": self.marketplace,
                "format": product.get("format", "FIXED_PRICE"),
                "pricingSummary": product.get("pricingSummary", {}),
            }

            # Add listing policies if configured
            listing_policies = self._get_listing_policies()
            if listing_policies:
                payload["listingPolicies"] = listing_policies

            # Category ID (required for eBay)
            category_id = product.get("categoryId") or self.config.get("default_category_id")
            if category_id:
                payload["categoryId"] = str(category_id)

            response = requests.post(
                offer_url,
                headers=headers,
                json=payload,
                timeout=30,
            )

            self.handle_rate_limiting(response)

            if response.status_code in (200, 201):
                result = response.json()
                return {
                    "success": True,
                    "offer_id": result.get("offerId"),
                }
            else:
                error_data = response.json() if response.text else {}
                return {
                    "success": False,
                    "error": error_data.get("message", f"HTTP {response.status_code}"),
                }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def _publish_offer(self, offer_id: str) -> Dict:
        """Publish an offer to make the listing live.

        Args:
            offer_id: The offer ID to publish

        Returns:
            Dict with success status
        """
        import requests

        try:
            self._wait_for_quota("offer")

            publish_url = f"{self.api_endpoint}/sell/inventory/v1/offer/{offer_id}/publish"
            headers = self._get_auth_headers()

            response = requests.post(
                publish_url,
                headers=headers,
                timeout=30,
            )

            self.handle_rate_limiting(response)

            if response.status_code in (200, 201):
                result = response.json()
                return {
                    "success": True,
                    "listing_id": result.get("listingId"),
                }
            else:
                error_data = response.json() if response.text else {}
                return {
                    "success": False,
                    "error": error_data.get("message", f"HTTP {response.status_code}"),
                }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def _get_listing_policies(self) -> Optional[Dict]:
        """Get listing policies from channel configuration.

        Returns:
            Dict with fulfillment, payment, and return policy IDs
        """
        policies = {}

        fulfillment_policy = self.config.get("fulfillment_policy_id")
        if fulfillment_policy:
            policies["fulfillmentPolicyId"] = fulfillment_policy

        payment_policy = self.config.get("payment_policy_id")
        if payment_policy:
            policies["paymentPolicyId"] = payment_policy

        return_policy = self.config.get("return_policy_id")
        if return_policy:
            policies["returnPolicyId"] = return_policy

        return policies if policies else None

    def get_status(self, job_id: str) -> StatusResult:
        """Check the status of a publish job.

        For eBay, publishing is synchronous, so this returns completed status
        for valid job IDs or retrieves listing status.

        Args:
            job_id: The job ID from publish() or a listing ID

        Returns:
            StatusResult with current job status and progress
        """
        # For eBay, publishing is synchronous
        # This method can be used to check listing status

        return StatusResult(
            job_id=job_id,
            status=PublishStatus.COMPLETED,
            progress=1.0,
            channel=self.channel_code,
            completed_at=datetime.now(),
        )

    # =========================================================================
    # Additional Methods
    # =========================================================================

    def update_inventory(self, sku: str, quantity: int) -> Dict:
        """Update inventory quantity for a single SKU.

        Args:
            sku: Product SKU
            quantity: New quantity

        Returns:
            Dict with success status
        """
        import requests

        try:
            self._wait_for_quota("inventory_item")

            inventory_url = f"{self.api_endpoint}/sell/inventory/v1/inventory_item/{sku}"
            headers = self._get_auth_headers()

            # Get current inventory item
            response = requests.get(inventory_url, headers=headers, timeout=30)

            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"Inventory item not found: {sku}",
                }

            current_item = response.json()

            # Update availability
            current_item["availability"] = {
                "shipToLocationAvailability": {
                    "quantity": quantity,
                }
            }

            # Update inventory item
            response = requests.put(
                inventory_url,
                headers=headers,
                json=current_item,
                timeout=30,
            )

            self.handle_rate_limiting(response)

            if response.status_code in (200, 201, 204):
                return {"success": True}
            else:
                return {
                    "success": False,
                    "error": f"Inventory update failed: {response.status_code}",
                }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def update_price(self, sku: str, price: float, currency: str = None) -> Dict:
        """Update price for a single SKU.

        Args:
            sku: Product SKU
            price: New price
            currency: Currency code (defaults to marketplace currency)

        Returns:
            Dict with success status
        """
        import requests

        try:
            self._wait_for_quota("offer")

            if currency is None:
                currency = self._get_marketplace_currency()

            # First, get the offer for this SKU
            offers_url = f"{self.api_endpoint}/sell/inventory/v1/offer"
            headers = self._get_auth_headers()

            response = requests.get(
                offers_url,
                headers=headers,
                params={"sku": sku, "marketplace_id": self.marketplace},
                timeout=30,
            )

            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"Could not find offer for SKU: {sku}",
                }

            offers_data = response.json()
            offers = offers_data.get("offers", [])

            if not offers:
                return {
                    "success": False,
                    "error": f"No active offer found for SKU: {sku}",
                }

            offer_id = offers[0].get("offerId")

            # Update the offer price
            offer_url = f"{self.api_endpoint}/sell/inventory/v1/offer/{offer_id}"

            offer_update = offers[0].copy()
            offer_update["pricingSummary"] = {
                "price": {
                    "value": str(round(price, 2)),
                    "currency": currency,
                }
            }

            response = requests.put(
                offer_url,
                headers=headers,
                json=offer_update,
                timeout=30,
            )

            self.handle_rate_limiting(response)

            if response.status_code in (200, 204):
                return {"success": True}
            else:
                return {
                    "success": False,
                    "error": f"Price update failed: {response.status_code}",
                }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def end_listing(self, sku: str) -> Dict:
        """End/withdraw a listing.

        Args:
            sku: Product SKU to end listing for

        Returns:
            Dict with success status
        """
        import requests

        try:
            self._wait_for_quota("offer")

            # Get the offer for this SKU
            offers_url = f"{self.api_endpoint}/sell/inventory/v1/offer"
            headers = self._get_auth_headers()

            response = requests.get(
                offers_url,
                headers=headers,
                params={"sku": sku, "marketplace_id": self.marketplace},
                timeout=30,
            )

            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"Could not find offer for SKU: {sku}",
                }

            offers_data = response.json()
            offers = offers_data.get("offers", [])

            if not offers:
                return {
                    "success": False,
                    "error": f"No active offer found for SKU: {sku}",
                }

            offer_id = offers[0].get("offerId")

            # Withdraw the offer
            withdraw_url = f"{self.api_endpoint}/sell/inventory/v1/offer/{offer_id}/withdraw"

            response = requests.post(
                withdraw_url,
                headers=headers,
                timeout=30,
            )

            self.handle_rate_limiting(response)

            if response.status_code in (200, 204):
                return {"success": True}
            else:
                return {
                    "success": False,
                    "error": f"Listing withdrawal failed: {response.status_code}",
                }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def delete_inventory_item(self, sku: str) -> Dict:
        """Delete an inventory item.

        Args:
            sku: Product SKU to delete

        Returns:
            Dict with success status
        """
        import requests

        try:
            self._wait_for_quota("inventory_item")

            inventory_url = f"{self.api_endpoint}/sell/inventory/v1/inventory_item/{sku}"
            headers = self._get_auth_headers()

            response = requests.delete(
                inventory_url,
                headers=headers,
                timeout=30,
            )

            self.handle_rate_limiting(response)

            if response.status_code in (200, 204):
                return {"success": True}
            elif response.status_code == 404:
                return {
                    "success": False,
                    "error": "Inventory item not found",
                }
            else:
                return {
                    "success": False,
                    "error": f"Delete failed: {response.status_code}",
                }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def get_inventory_item(self, sku: str) -> Dict:
        """Get inventory item details by SKU.

        Args:
            sku: Product SKU

        Returns:
            Dict with item data or error
        """
        import requests

        try:
            self._wait_for_quota("inventory_item")

            inventory_url = f"{self.api_endpoint}/sell/inventory/v1/inventory_item/{sku}"
            headers = self._get_auth_headers()

            response = requests.get(
                inventory_url,
                headers=headers,
                timeout=30,
            )

            self.handle_rate_limiting(response)

            if response.status_code == 200:
                return {
                    "success": True,
                    "data": response.json(),
                }
            elif response.status_code == 404:
                return {
                    "success": False,
                    "error": "Inventory item not found",
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to get item: {response.status_code}",
                }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def get_offers(self, sku: str = None) -> Dict:
        """Get offers, optionally filtered by SKU.

        Args:
            sku: Optional SKU to filter by

        Returns:
            Dict with offers data or error
        """
        import requests

        try:
            self._wait_for_quota("offer")

            offers_url = f"{self.api_endpoint}/sell/inventory/v1/offer"
            headers = self._get_auth_headers()

            params = {"marketplace_id": self.marketplace}
            if sku:
                params["sku"] = sku

            response = requests.get(
                offers_url,
                headers=headers,
                params=params,
                timeout=30,
            )

            self.handle_rate_limiting(response)

            if response.status_code == 200:
                return {
                    "success": True,
                    "data": response.json(),
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to get offers: {response.status_code}",
                }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }


# =============================================================================
# Register Adapter
# =============================================================================

register_adapter("ebay", EbayAdapter)
register_adapter("ebay_us", EbayAdapter)
register_adapter("ebay_uk", EbayAdapter)
register_adapter("ebay_de", EbayAdapter)
register_adapter("ebay_au", EbayAdapter)
register_adapter("ebay_marketplace", EbayAdapter)
