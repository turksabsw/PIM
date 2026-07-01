"""
Amazon Channel Adapter (SP-API)

Provides adapters for Amazon Seller Central (3P) and Vendor Central (1P)
selling models using the Amazon Selling Partner API (SP-API).

Features:
- Dual adapter support: AmazonSellerAdapter (3P) and AmazonVendorAdapter (1P)
- SP-API rate limiting with per-endpoint quota tracking
- LWA (Login with Amazon) OAuth token management
- Batch listing operations for efficient publishing
- Comprehensive product validation against Amazon requirements
- Attribute mapping to Amazon catalog format

Note: frappe imports are deferred to function/method level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import hashlib
import hmac
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
# Amazon-Specific Constants
# =============================================================================

class AmazonMarketplace(str, Enum):
    """Amazon marketplace identifiers"""
    US = "ATVPDKIKX0DER"
    CA = "A2EUQ1WTGCTBG2"
    MX = "A1AM78C64UM0Y8"
    BR = "A2Q3Y263D00KWC"
    UK = "A1F83G8C2ARO7P"
    DE = "A1PA6795UKMFR9"
    FR = "A13V1IB3VIYBER"
    IT = "APJ6JRA9NG5V4"
    ES = "A1RKKUPIHCS9HS"
    NL = "A1805IZSGTT6HS"
    SE = "A2NODRKZP88ZB9"
    PL = "A1C3SOZRARQ6R3"
    TR = "A33AVAJ2PDY3EV"
    AE = "A2VIGQ35RCS4UG"
    SA = "A17E79C6D8DWNP"
    IN = "A21TJRUUN4KGV"
    SG = "A19VAU5U5O7RUS"
    AU = "A39IBJ37TRP1C6"
    JP = "A1VC38T7YXB528"


class AmazonCondition(str, Enum):
    """Amazon product condition types"""
    NEW = "New"
    REFURBISHED = "Refurbished"
    USED_LIKE_NEW = "UsedLikeNew"
    USED_VERY_GOOD = "UsedVeryGood"
    USED_GOOD = "UsedGood"
    USED_ACCEPTABLE = "UsedAcceptable"
    COLLECTIBLE_LIKE_NEW = "CollectibleLikeNew"
    COLLECTIBLE_VERY_GOOD = "CollectibleVeryGood"
    COLLECTIBLE_GOOD = "CollectibleGood"
    COLLECTIBLE_ACCEPTABLE = "CollectibleAcceptable"


class AmazonFulfillmentChannel(str, Enum):
    """Amazon fulfillment channel types"""
    AFN = "AMAZON_NA"  # Fulfilled by Amazon (FBA)
    MFN = "DEFAULT"     # Merchant Fulfilled Network


# SP-API rate limits per endpoint (requests per second)
SPAPI_RATE_LIMITS = {
    "listings": 5.0,
    "catalog": 10.0,
    "feeds": 2.0,
    "reports": 0.5,
    "pricing": 5.0,
    "orders": 2.0,
    "inventory": 5.0,
    "default": 1.0,
}

# SP-API endpoint burst limits
SPAPI_BURST_LIMITS = {
    "listings": 10,
    "catalog": 20,
    "feeds": 15,
    "reports": 15,
    "pricing": 20,
    "orders": 30,
    "inventory": 10,
    "default": 5,
}


# =============================================================================
# Amazon-Specific Data Classes
# =============================================================================

@dataclass
class AmazonQuotaState:
    """Tracks SP-API quota state per endpoint"""
    endpoint: str
    requests_made: int = 0
    requests_limit: int = 100
    burst_remaining: int = 10
    window_start: datetime = field(default_factory=datetime.now)
    window_duration: int = 1  # seconds (for rate limit calculation)
    retry_after: datetime = None
    last_request: datetime = None

    def is_limited(self) -> bool:
        """Check if currently rate limited"""
        if self.retry_after and datetime.now() < self.retry_after:
            return True

        # Reset window if expired
        if datetime.now() > self.window_start + timedelta(seconds=self.window_duration):
            rate_limit = SPAPI_RATE_LIMITS.get(self.endpoint, SPAPI_RATE_LIMITS["default"])
            self.requests_made = 0
            self.burst_remaining = SPAPI_BURST_LIMITS.get(
                self.endpoint, SPAPI_BURST_LIMITS["default"]
            )
            self.window_start = datetime.now()
            return False

        return self.burst_remaining <= 0

    def record_request(self) -> None:
        """Record a request for rate limiting"""
        self.requests_made += 1
        self.burst_remaining = max(0, self.burst_remaining - 1)
        self.last_request = datetime.now()

    def wait_time(self) -> float:
        """Calculate wait time before next request"""
        if self.retry_after:
            delta = self.retry_after - datetime.now()
            if delta.total_seconds() > 0:
                return delta.total_seconds()

        if self.is_limited():
            # Calculate based on rate limit
            rate_limit = SPAPI_RATE_LIMITS.get(self.endpoint, SPAPI_RATE_LIMITS["default"])
            return 1.0 / rate_limit

        return 0


@dataclass
class AmazonToken:
    """LWA OAuth token with expiration tracking"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 3600
    obtained_at: datetime = field(default_factory=datetime.now)

    def is_expired(self) -> bool:
        """Check if token is expired or about to expire (5 min buffer)"""
        expiration = self.obtained_at + timedelta(seconds=self.expires_in - 300)
        return datetime.now() >= expiration


# =============================================================================
# Amazon Required Fields and Validation Rules
# =============================================================================

# Required fields for Amazon product listings
AMAZON_REQUIRED_FIELDS = {
    "sku",
    "title",
    "product_type",
    "brand",
}

# Optional but recommended fields
AMAZON_RECOMMENDED_FIELDS = {
    "description",
    "bullet_points",
    "images",
    "price",
    "condition",
    "gtin",  # EAN/UPC/ISBN
    "manufacturer",
    "part_number",
}

# Field length limits
AMAZON_FIELD_LIMITS = {
    "sku": 40,
    "title": 200,
    "brand": 50,
    "description": 2000,
    "bullet_point": 500,
    "search_term": 250,
}

# PIM to Amazon field mappings
PIM_TO_AMAZON_FIELDS = {
    "item_code": "seller_sku",
    "item_name": "title",
    "brand": "brand",
    "description": "product_description",
    "pim_title": "item_name",
    "pim_description": "product_description",
    "barcode": "external_product_id",
    "standard_rate": "price",
    "image": "main_image",
    "manufacturer": "manufacturer",
    "manufacturer_part_number": "part_number",
    "country_of_origin": "country_of_origin",
    "weight_per_unit": "item_weight",
    "net_weight": "item_weight",
}


# =============================================================================
# Base Amazon Adapter
# =============================================================================

class AmazonBaseAdapter(ChannelAdapter):
    """
    Base class for Amazon adapters providing common functionality.

    Handles SP-API authentication, rate limiting, and core operations
    shared between Seller Central (3P) and Vendor Central (1P) models.
    """

    channel_code: str = "amazon"
    channel_name: str = "Amazon"

    # SP-API specific settings
    default_requests_per_minute: int = 60
    default_requests_per_second: float = 1.0
    max_retry_attempts: int = 5
    base_backoff_seconds: float = 0.5
    max_backoff_seconds: float = 120.0

    # API endpoints
    SPAPI_ENDPOINT = "https://sellingpartnerapi-na.amazon.com"
    LWA_ENDPOINT = "https://api.amazon.com/auth/o2/token"

    def __init__(self, channel_doc: Any = None):
        """Initialize Amazon adapter.

        Args:
            channel_doc: Channel Frappe document with Amazon credentials
        """
        super().__init__(channel_doc)
        self._token: Optional[AmazonToken] = None
        self._quota_states: Dict[str, AmazonQuotaState] = {}
        self._marketplace_id: str = None

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def marketplace_id(self) -> str:
        """Get the Amazon marketplace ID."""
        if self._marketplace_id:
            return self._marketplace_id

        # Get from channel config or default to US
        marketplace = self.config.get("marketplace", "US")
        try:
            self._marketplace_id = AmazonMarketplace[marketplace.upper()].value
        except KeyError:
            self._marketplace_id = AmazonMarketplace.US.value

        return self._marketplace_id

    @property
    def api_endpoint(self) -> str:
        """Get the SP-API endpoint for the configured region."""
        region = self.config.get("region", "na")

        endpoints = {
            "na": "https://sellingpartnerapi-na.amazon.com",
            "eu": "https://sellingpartnerapi-eu.amazon.com",
            "fe": "https://sellingpartnerapi-fe.amazon.com",
        }

        return endpoints.get(region.lower(), endpoints["na"])

    # =========================================================================
    # Authentication Methods
    # =========================================================================

    def _get_amazon_credentials(self) -> Dict:
        """Get Amazon-specific credentials from channel document.

        Returns:
            Dictionary with:
            - client_id: LWA app client ID
            - client_secret: LWA app client secret
            - refresh_token: LWA refresh token
            - aws_access_key: AWS access key (for STS)
            - aws_secret_key: AWS secret key (for STS)
            - role_arn: IAM role ARN (for STS)
        """
        credentials = self.credentials

        # Get additional Amazon-specific credentials
        amazon_creds = {
            "client_id": credentials.get("api_key"),  # LWA client ID
            "client_secret": credentials.get("api_secret"),  # LWA client secret
            "refresh_token": credentials.get("refresh_token"),
        }

        # Get AWS credentials from config
        amazon_creds.update({
            "aws_access_key": self.config.get("aws_access_key"),
            "aws_secret_key": self.config.get("aws_secret_key"),
            "role_arn": self.config.get("role_arn"),
        })

        return amazon_creds

    def _get_access_token(self) -> str:
        """Get a valid LWA access token, refreshing if necessary.

        Returns:
            Valid access token string

        Raises:
            AuthenticationError: If token refresh fails
        """
        import requests

        # Return cached token if still valid
        if self._token and not self._token.is_expired():
            return self._token.access_token

        amazon_creds = self._get_amazon_credentials()

        if not amazon_creds.get("refresh_token"):
            raise AuthenticationError(
                "Amazon refresh token not configured",
                channel=self.channel_code,
            )

        # Request new access token
        token_data = {
            "grant_type": "refresh_token",
            "refresh_token": amazon_creds["refresh_token"],
            "client_id": amazon_creds["client_id"],
            "client_secret": amazon_creds["client_secret"],
        }

        try:
            response = requests.post(
                self.LWA_ENDPOINT,
                data=token_data,
                timeout=30,
            )

            if response.status_code != 200:
                raise AuthenticationError(
                    f"LWA token refresh failed: {response.status_code} - {response.text}",
                    channel=self.channel_code,
                )

            token_response = response.json()
            self._token = AmazonToken(
                access_token=token_response["access_token"],
                token_type=token_response.get("token_type", "bearer"),
                expires_in=token_response.get("expires_in", 3600),
            )

            return self._token.access_token

        except requests.exceptions.RequestException as e:
            raise AuthenticationError(
                f"Failed to connect to LWA endpoint: {str(e)}",
                channel=self.channel_code,
            )

    def _get_auth_headers(self) -> Dict:
        """Build authentication headers for SP-API requests.

        Returns:
            Dictionary of HTTP headers including authorization
        """
        access_token = self._get_access_token()

        return {
            "x-amz-access-token": access_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # =========================================================================
    # Rate Limiting Methods
    # =========================================================================

    def _get_quota_state(self, endpoint: str) -> AmazonQuotaState:
        """Get or create quota state for an endpoint.

        Args:
            endpoint: The API endpoint category (listings, feeds, etc.)

        Returns:
            AmazonQuotaState instance for the endpoint
        """
        if endpoint not in self._quota_states:
            rate_limit = SPAPI_RATE_LIMITS.get(endpoint, SPAPI_RATE_LIMITS["default"])
            burst_limit = SPAPI_BURST_LIMITS.get(endpoint, SPAPI_BURST_LIMITS["default"])

            self._quota_states[endpoint] = AmazonQuotaState(
                endpoint=endpoint,
                burst_remaining=burst_limit,
            )

        return self._quota_states[endpoint]

    def handle_rate_limiting(self, response: Any = None) -> None:
        """Handle SP-API rate limiting from response headers.

        Parses x-amzn-RateLimit-Limit and Retry-After headers and
        updates internal quota tracking.

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
                "Amazon SP-API rate limit exceeded",
                channel=self.channel_code,
                retry_after=retry_after,
                details={
                    "status_code": 429,
                    "retry_after": retry_after,
                },
            )

        # Parse rate limit headers
        rate_limit = response.headers.get("x-amzn-RateLimit-Limit")

        if rate_limit:
            try:
                # Update quota state
                # Header format: "0.0167" (requests per second)
                requests_per_second = float(rate_limit)
                # This is informational - actual enforcement is server-side
            except ValueError:
                pass

    def _wait_for_quota(self, endpoint: str) -> None:
        """Wait if quota for endpoint is exhausted.

        Args:
            endpoint: The API endpoint category

        Raises:
            RateLimitError: If wait time exceeds maximum
        """
        quota_state = self._get_quota_state(endpoint)
        wait_time = quota_state.wait_time()

        if wait_time > 0:
            if wait_time > self.max_backoff_seconds:
                raise RateLimitError(
                    f"SP-API quota exhausted for {endpoint}, wait time ({wait_time}s) exceeds maximum",
                    channel=self.channel_code,
                    retry_after=int(wait_time),
                )
            time.sleep(wait_time)

        quota_state.record_request()

    # =========================================================================
    # Validation Methods
    # =========================================================================

    def validate_product(self, product: Dict) -> ValidationResult:
        """Validate a product against Amazon's listing requirements.

        Checks required fields, field length limits, GTIN format,
        and other Amazon-specific requirements.

        Args:
            product: Product data dictionary in PIM format

        Returns:
            ValidationResult with validation status and any errors/warnings
        """
        errors = []
        warnings = []
        product_id = product.get("item_code", product.get("sku", "unknown"))

        # Check required fields
        for field_name in AMAZON_REQUIRED_FIELDS:
            # Check both PIM and Amazon field names
            pim_field = None
            for pim_name, amazon_name in PIM_TO_AMAZON_FIELDS.items():
                if amazon_name == field_name or field_name == pim_name:
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
        for field_name, max_length in AMAZON_FIELD_LIMITS.items():
            value = product.get(field_name) or ""
            if isinstance(value, str) and len(value) > max_length:
                errors.append({
                    "field": field_name,
                    "message": f"Field '{field_name}' exceeds maximum length of {max_length} characters",
                    "value": f"{len(value)} characters",
                    "rule": "max_length",
                })

        # Validate GTIN if provided
        gtin = product.get("barcode") or product.get("gtin")
        if gtin:
            gtin_error = self._validate_gtin(gtin)
            if gtin_error:
                errors.append(gtin_error)
        else:
            warnings.append({
                "field": "gtin",
                "message": "GTIN (UPC/EAN/ISBN) not provided - listing may have reduced visibility",
                "rule": "recommended",
            })

        # Validate price if provided
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
            except (ValueError, TypeError):
                errors.append({
                    "field": "price",
                    "message": "Price must be a valid number",
                    "value": str(price),
                    "rule": "numeric",
                })

        # Check for recommended fields
        for field_name in AMAZON_RECOMMENDED_FIELDS:
            if field_name not in product and field_name not in AMAZON_REQUIRED_FIELDS:
                pim_field = None
                for pim_name, amazon_name in PIM_TO_AMAZON_FIELDS.items():
                    if amazon_name == field_name:
                        pim_field = pim_name
                        break

                if pim_field and pim_field not in product:
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

    def _validate_gtin(self, gtin: str) -> Optional[Dict]:
        """Validate GTIN format and check digit.

        Args:
            gtin: GTIN string (UPC-A, EAN-13, etc.)

        Returns:
            Error dict if invalid, None if valid
        """
        # Remove any spaces or dashes
        gtin = str(gtin).replace(" ", "").replace("-", "")

        # Check length
        valid_lengths = {8, 12, 13, 14}
        if len(gtin) not in valid_lengths:
            return {
                "field": "gtin",
                "message": f"GTIN must be 8, 12, 13, or 14 digits, got {len(gtin)}",
                "value": gtin,
                "rule": "gtin_length",
            }

        # Check if all digits
        if not gtin.isdigit():
            return {
                "field": "gtin",
                "message": "GTIN must contain only digits",
                "value": gtin,
                "rule": "gtin_format",
            }

        # Validate check digit
        if not self._validate_gtin_check_digit(gtin):
            return {
                "field": "gtin",
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
        """Validate product images against Amazon requirements.

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
            # Check image count
            if len(images) < 1:
                warnings.append({
                    "field": "images",
                    "message": "At least one product image is recommended",
                    "rule": "min_images",
                })

            # Check for main image
            # Amazon requires at least a main product image

        return warnings

    # =========================================================================
    # Mapping Methods
    # =========================================================================

    def map_attributes(self, product: Dict) -> MappingResult:
        """Map PIM product attributes to Amazon catalog format.

        Converts internal field names to Amazon's expected format
        and transforms values as needed.

        Args:
            product: Product data dictionary in PIM format

        Returns:
            MappingResult with mapped data and unmapped fields
        """
        product_id = product.get("item_code", product.get("sku", "unknown"))
        mapped_data = {}
        unmapped_fields = []

        # Map known fields
        for pim_field, amazon_field in PIM_TO_AMAZON_FIELDS.items():
            if pim_field in product:
                value = product[pim_field]
                if value is not None:
                    mapped_data[amazon_field] = value

        # Add SKU (required)
        if "seller_sku" not in mapped_data:
            mapped_data["seller_sku"] = product.get("item_code", product.get("sku"))

        # Add title
        if "title" not in mapped_data and "item_name" not in mapped_data:
            title = product.get("pim_title") or product.get("item_name")
            if title:
                mapped_data["item_name"] = title

        # Map condition
        condition = product.get("condition", "New")
        try:
            mapped_data["condition_type"] = AmazonCondition[condition.upper().replace(" ", "_")].value
        except KeyError:
            mapped_data["condition_type"] = AmazonCondition.NEW.value

        # Map fulfillment channel
        fulfillment = product.get("fulfillment_channel", "MFN")
        try:
            mapped_data["fulfillment_channel"] = AmazonFulfillmentChannel[fulfillment.upper()].value
        except KeyError:
            mapped_data["fulfillment_channel"] = AmazonFulfillmentChannel.MFN.value

        # Map price
        price = product.get("standard_rate") or product.get("price")
        if price is not None:
            currency = product.get("currency", "USD")
            mapped_data["price"] = {
                "amount": float(price),
                "currency": currency,
            }

        # Map quantity
        quantity = product.get("quantity") or product.get("stock_qty", 0)
        mapped_data["quantity"] = int(quantity) if quantity else 0

        # Map GTIN
        gtin = product.get("barcode") or product.get("gtin")
        if gtin:
            # Determine GTIN type
            gtin_str = str(gtin).replace(" ", "").replace("-", "")
            gtin_type = "EAN" if len(gtin_str) == 13 else "UPC" if len(gtin_str) == 12 else "GTIN"
            mapped_data["external_product_id"] = gtin_str
            mapped_data["external_product_id_type"] = gtin_type

        # Map bullet points
        bullet_points = product.get("bullet_points", [])
        if isinstance(bullet_points, str):
            bullet_points = [bp.strip() for bp in bullet_points.split("\n") if bp.strip()]
        if bullet_points:
            mapped_data["bullet_points"] = bullet_points[:5]  # Amazon allows max 5

        # Map images
        images = product.get("images") or product.get("image")
        if images:
            if isinstance(images, str):
                images = [images]
            mapped_data["images"] = [{"url": img, "variant": "MAIN" if i == 0 else f"PT0{i}"}
                                      for i, img in enumerate(images[:9])]  # Max 9 images

        # Track unmapped fields
        mapped_pim_fields = set(PIM_TO_AMAZON_FIELDS.keys())
        mapped_pim_fields.update({"condition", "fulfillment_channel", "quantity", "stock_qty",
                                   "currency", "bullet_points", "images"})

        for field in product.keys():
            if field not in mapped_pim_fields:
                unmapped_fields.append(field)

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
        """Generate SP-API compatible payload for product listings.

        Creates a feed document or API request body from mapped products.

        Args:
            products: List of mapped product data dictionaries

        Returns:
            Dictionary with the complete payload for API submission
        """
        feed_id = str(uuid.uuid4())

        # Generate listings items
        messages = []
        for i, product in enumerate(products, 1):
            message = {
                "messageId": i,
                "sku": product.get("seller_sku"),
                "operationType": "UPDATE",  # Can be UPDATE, DELETE, PARTIAL_UPDATE
                "productType": product.get("product_type", "PRODUCT"),
                "attributes": self._build_attributes_payload(product),
            }
            messages.append(message)

        payload = {
            "header": {
                "sellerId": self.credentials.get("seller_id"),
                "version": "2.0",
                "issueLocale": "en_US",
            },
            "messages": messages,
            "marketplaceIds": [self.marketplace_id],
            "_metadata": {
                "feed_id": feed_id,
                "created_at": datetime.now().isoformat(),
                "product_count": len(products),
            },
        }

        return payload

    def _build_attributes_payload(self, product: Dict) -> Dict:
        """Build the attributes section of a listing payload.

        Args:
            product: Mapped product data

        Returns:
            Attributes dictionary for SP-API
        """
        attributes = {}

        # Item name (title)
        if "item_name" in product:
            attributes["item_name"] = [{"value": product["item_name"], "marketplace_id": self.marketplace_id}]

        # Brand
        if "brand" in product:
            attributes["brand"] = [{"value": product["brand"], "marketplace_id": self.marketplace_id}]

        # Description
        if "product_description" in product:
            attributes["product_description"] = [{"value": product["product_description"], "marketplace_id": self.marketplace_id}]

        # Bullet points
        if "bullet_points" in product:
            attributes["bullet_point"] = [
                {"value": bp, "marketplace_id": self.marketplace_id}
                for bp in product["bullet_points"]
            ]

        # External product ID (GTIN)
        if "external_product_id" in product:
            attributes["externally_assigned_product_identifier"] = [{
                "value": product["external_product_id"],
                "type": product.get("external_product_id_type", "EAN"),
                "marketplace_id": self.marketplace_id,
            }]

        # Manufacturer
        if "manufacturer" in product:
            attributes["manufacturer"] = [{"value": product["manufacturer"], "marketplace_id": self.marketplace_id}]

        # Part number
        if "part_number" in product:
            attributes["part_number"] = [{"value": product["part_number"], "marketplace_id": self.marketplace_id}]

        # Country of origin
        if "country_of_origin" in product:
            attributes["country_of_origin"] = [{"value": product["country_of_origin"], "marketplace_id": self.marketplace_id}]

        # Item weight
        if "item_weight" in product:
            weight = product["item_weight"]
            if isinstance(weight, (int, float)):
                attributes["item_weight"] = [{"value": weight, "unit": "kilograms", "marketplace_id": self.marketplace_id}]

        # Images
        if "images" in product:
            main_image = None
            other_images = []

            for img in product["images"]:
                if img.get("variant") == "MAIN":
                    main_image = img.get("url")
                else:
                    other_images.append(img.get("url"))

            if main_image:
                attributes["main_product_image_locator"] = [{"value": main_image, "marketplace_id": self.marketplace_id}]

            if other_images:
                attributes["other_product_image_locator_1"] = [{"value": other_images[0], "marketplace_id": self.marketplace_id}]

        return attributes

    # =========================================================================
    # Abstract Method - To be implemented by subclasses
    # =========================================================================

    def publish(self, products: List[Dict]) -> PublishResult:
        """Publish products to Amazon.

        This base implementation provides the common workflow.
        Subclasses (Seller/Vendor) override specific API calls.

        Args:
            products: List of product data dictionaries in PIM format

        Returns:
            PublishResult with job status and any errors
        """
        import frappe

        job_id = str(uuid.uuid4())
        errors = []
        products_submitted = 0

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

            # Map products to Amazon format
            mapped_products = []
            for product in products:
                mapping_result = self.map_attributes(product)
                mapped_products.append(mapping_result.mapped_data)

            # Generate payload
            payload = self.generate_payload(mapped_products)

            # Submit to Amazon (subclass implementation)
            submit_result = self._submit_to_amazon(payload)

            if submit_result.get("success"):
                products_submitted = len(products)

                self._log_publish_event("submit_success", {
                    "job_id": job_id,
                    "feed_id": submit_result.get("feed_id"),
                    "products_count": products_submitted,
                })

                return PublishResult(
                    success=True,
                    job_id=job_id,
                    status=PublishStatus.IN_PROGRESS,
                    products_submitted=products_submitted,
                    channel=self.channel_code,
                    external_id=submit_result.get("feed_id"),
                )
            else:
                errors.append({
                    "message": submit_result.get("error", "Unknown submission error"),
                    "details": submit_result.get("details", {}),
                })

                return PublishResult(
                    success=False,
                    job_id=job_id,
                    status=PublishStatus.FAILED,
                    products_submitted=0,
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

    def _submit_to_amazon(self, payload: Dict) -> Dict:
        """Submit payload to Amazon SP-API.

        To be overridden by subclasses for specific API endpoints.

        Args:
            payload: The generated payload

        Returns:
            Dict with success status and feed_id or error
        """
        raise NotImplementedError("Subclasses must implement _submit_to_amazon")

    def get_status(self, job_id: str) -> StatusResult:
        """Check the status of a publish job.

        Args:
            job_id: The job ID or feed ID from publish()

        Returns:
            StatusResult with current job status and progress
        """
        raise NotImplementedError("Subclasses must implement get_status")


# =============================================================================
# Amazon Seller Adapter (3P)
# =============================================================================

class AmazonSellerAdapter(AmazonBaseAdapter):
    """
    Amazon Seller Central adapter for 3P (third-party) selling.

    Uses SP-API endpoints for:
    - Listings Items API for product creation/updates
    - Feeds API for bulk operations
    - Catalog Items API for product search/matching
    """

    channel_code: str = "amazon_seller"
    channel_name: str = "Amazon Seller Central (3P)"

    def _submit_to_amazon(self, payload: Dict) -> Dict:
        """Submit products via Feeds API for Seller Central.

        Uses the JSON_LISTINGS_FEED feed type for product submissions.

        Args:
            payload: The generated payload

        Returns:
            Dict with success status and feed_id or error
        """
        import requests

        try:
            # Wait for quota
            self._wait_for_quota("feeds")

            # Create feed document
            feed_url = f"{self.api_endpoint}/feeds/2021-06-30/feeds"

            headers = self._get_auth_headers()

            # First, create the feed
            create_response = requests.post(
                feed_url,
                headers=headers,
                json={
                    "feedType": "JSON_LISTINGS_FEED",
                    "marketplaceIds": [self.marketplace_id],
                },
                timeout=30,
            )

            self.handle_rate_limiting(create_response)

            if create_response.status_code not in (200, 201):
                return {
                    "success": False,
                    "error": f"Failed to create feed: {create_response.status_code}",
                    "details": {"response": create_response.text},
                }

            feed_data = create_response.json()
            feed_id = feed_data.get("feedId")
            upload_url = feed_data.get("feedDocumentId")

            # Upload the feed document
            if upload_url:
                self._wait_for_quota("feeds")

                # Get upload destination
                doc_url = f"{self.api_endpoint}/feeds/2021-06-30/documents/{upload_url}"
                doc_response = requests.get(doc_url, headers=headers, timeout=30)

                if doc_response.status_code == 200:
                    doc_data = doc_response.json()
                    presigned_url = doc_data.get("url")

                    if presigned_url:
                        # Upload payload to S3
                        upload_response = requests.put(
                            presigned_url,
                            data=json.dumps(payload),
                            headers={"Content-Type": "application/json"},
                            timeout=60,
                        )

                        if upload_response.status_code not in (200, 201):
                            return {
                                "success": False,
                                "error": "Failed to upload feed document",
                                "details": {"status": upload_response.status_code},
                            }

            return {
                "success": True,
                "feed_id": feed_id,
            }

        except requests.exceptions.RequestException as e:
            return {
                "success": False,
                "error": f"Request failed: {str(e)}",
            }

    def get_status(self, job_id: str) -> StatusResult:
        """Check feed processing status.

        Args:
            job_id: The feed ID from publish()

        Returns:
            StatusResult with current processing status
        """
        import requests

        try:
            self._wait_for_quota("feeds")

            feed_url = f"{self.api_endpoint}/feeds/2021-06-30/feeds/{job_id}"
            headers = self._get_auth_headers()

            response = requests.get(feed_url, headers=headers, timeout=30)
            self.handle_rate_limiting(response)

            if response.status_code != 200:
                return StatusResult(
                    job_id=job_id,
                    status=PublishStatus.FAILED,
                    errors=[{"message": f"Failed to get status: {response.status_code}"}],
                    channel=self.channel_code,
                )

            feed_data = response.json()
            processing_status = feed_data.get("processingStatus", "").upper()

            # Map Amazon status to our status
            status_mapping = {
                "CANCELLED": PublishStatus.CANCELLED,
                "DONE": PublishStatus.COMPLETED,
                "FATAL": PublishStatus.FAILED,
                "IN_PROGRESS": PublishStatus.IN_PROGRESS,
                "IN_QUEUE": PublishStatus.PENDING,
            }

            status = status_mapping.get(processing_status, PublishStatus.IN_PROGRESS)

            # Get result document for error details
            errors = []
            if status in (PublishStatus.COMPLETED, PublishStatus.FAILED):
                result_doc_id = feed_data.get("resultFeedDocumentId")
                if result_doc_id:
                    errors = self._get_feed_errors(result_doc_id)

            return StatusResult(
                job_id=job_id,
                status=status,
                progress=1.0 if status == PublishStatus.COMPLETED else 0.5,
                errors=errors,
                channel=self.channel_code,
                completed_at=datetime.now() if status == PublishStatus.COMPLETED else None,
            )

        except Exception as e:
            return StatusResult(
                job_id=job_id,
                status=PublishStatus.FAILED,
                errors=[{"message": f"Status check failed: {str(e)}"}],
                channel=self.channel_code,
            )

    def _get_feed_errors(self, result_doc_id: str) -> List[Dict]:
        """Retrieve errors from feed result document.

        Args:
            result_doc_id: The result document ID

        Returns:
            List of error dictionaries
        """
        import requests

        errors = []

        try:
            self._wait_for_quota("feeds")

            doc_url = f"{self.api_endpoint}/feeds/2021-06-30/documents/{result_doc_id}"
            headers = self._get_auth_headers()

            response = requests.get(doc_url, headers=headers, timeout=30)

            if response.status_code == 200:
                doc_data = response.json()
                presigned_url = doc_data.get("url")

                if presigned_url:
                    result_response = requests.get(presigned_url, timeout=60)
                    if result_response.status_code == 200:
                        try:
                            result_data = result_response.json()
                            for message in result_data.get("messages", []):
                                if message.get("status") == "ERROR":
                                    errors.append({
                                        "sku": message.get("sku"),
                                        "message": message.get("errors", [{}])[0].get("message", "Unknown error"),
                                        "code": message.get("errors", [{}])[0].get("code"),
                                    })
                        except json.JSONDecodeError:
                            pass

        except Exception:
            pass

        return errors


# =============================================================================
# Amazon Vendor Adapter (1P)
# =============================================================================

class AmazonVendorAdapter(AmazonBaseAdapter):
    """
    Amazon Vendor Central adapter for 1P (first-party) selling.

    Uses SP-API Vendor Direct Fulfillment endpoints for:
    - Vendor Direct Fulfillment Orders
    - Vendor Direct Fulfillment Shipping
    - Vendor Direct Fulfillment Inventory

    Also uses Vendor Retail Analytics API for performance data.
    """

    channel_code: str = "amazon_vendor"
    channel_name: str = "Amazon Vendor Central (1P)"

    # Vendor-specific endpoints
    VENDOR_API_VERSION = "v1"

    def _submit_to_amazon(self, payload: Dict) -> Dict:
        """Submit products via Vendor API.

        For Vendor Central, product catalog is managed by Amazon.
        This typically involves catalog contributions and inventory updates.

        Args:
            payload: The generated payload

        Returns:
            Dict with success status and submission ID or error
        """
        import requests

        try:
            # Wait for quota
            self._wait_for_quota("feeds")

            # Vendor catalog submissions use different endpoint
            catalog_url = f"{self.api_endpoint}/vendor/directFulfillment/transactions/2021-12-28/transactions"

            headers = self._get_auth_headers()

            # Submit catalog contribution
            response = requests.post(
                catalog_url,
                headers=headers,
                json={
                    "transactionType": "CATALOG_CONTRIBUTION",
                    "transactionId": payload.get("_metadata", {}).get("feed_id"),
                    "payload": payload,
                },
                timeout=60,
            )

            self.handle_rate_limiting(response)

            if response.status_code not in (200, 201, 202):
                return {
                    "success": False,
                    "error": f"Vendor submission failed: {response.status_code}",
                    "details": {"response": response.text},
                }

            result = response.json()

            return {
                "success": True,
                "feed_id": result.get("transactionId", payload.get("_metadata", {}).get("feed_id")),
            }

        except requests.exceptions.RequestException as e:
            return {
                "success": False,
                "error": f"Request failed: {str(e)}",
            }

    def get_status(self, job_id: str) -> StatusResult:
        """Check vendor transaction status.

        Args:
            job_id: The transaction ID from publish()

        Returns:
            StatusResult with current processing status
        """
        import requests

        try:
            self._wait_for_quota("feeds")

            status_url = f"{self.api_endpoint}/vendor/directFulfillment/transactions/2021-12-28/transactions/{job_id}"
            headers = self._get_auth_headers()

            response = requests.get(status_url, headers=headers, timeout=30)
            self.handle_rate_limiting(response)

            if response.status_code != 200:
                return StatusResult(
                    job_id=job_id,
                    status=PublishStatus.FAILED,
                    errors=[{"message": f"Failed to get status: {response.status_code}"}],
                    channel=self.channel_code,
                )

            data = response.json()
            transaction_status = data.get("status", "").upper()

            # Map vendor status to our status
            status_mapping = {
                "PROCESSING": PublishStatus.IN_PROGRESS,
                "SUCCESS": PublishStatus.COMPLETED,
                "FAILURE": PublishStatus.FAILED,
            }

            status = status_mapping.get(transaction_status, PublishStatus.IN_PROGRESS)

            errors = []
            if status == PublishStatus.FAILED:
                for error in data.get("errors", []):
                    errors.append({
                        "code": error.get("code"),
                        "message": error.get("message"),
                    })

            return StatusResult(
                job_id=job_id,
                status=status,
                progress=1.0 if status == PublishStatus.COMPLETED else 0.5,
                errors=errors,
                channel=self.channel_code,
                completed_at=datetime.now() if status == PublishStatus.COMPLETED else None,
            )

        except Exception as e:
            return StatusResult(
                job_id=job_id,
                status=PublishStatus.FAILED,
                errors=[{"message": f"Status check failed: {str(e)}"}],
                channel=self.channel_code,
            )

    def map_attributes(self, product: Dict) -> MappingResult:
        """Map PIM product attributes to Vendor Central format.

        Vendor Central has different attribute requirements than Seller Central,
        including additional supply chain fields.

        Args:
            product: Product data dictionary in PIM format

        Returns:
            MappingResult with mapped data and unmapped fields
        """
        # Start with base mapping
        result = super().map_attributes(product)

        # Add vendor-specific fields
        mapped_data = result.mapped_data

        # Vendor-specific fields
        mapped_data["vendor_code"] = product.get("vendor_code", self.credentials.get("vendor_code"))

        # Cost/pricing for 1P model
        if "cost" in product:
            mapped_data["unit_cost"] = {
                "amount": float(product["cost"]),
                "currency": product.get("currency", "USD"),
            }

        # Case pack information
        if "case_quantity" in product:
            mapped_data["case_pack_quantity"] = int(product["case_quantity"])

        # Lead time
        if "lead_time_days" in product:
            mapped_data["lead_time_days"] = int(product["lead_time_days"])

        # ASIN if already assigned
        if "asin" in product:
            mapped_data["asin"] = product["asin"]

        return MappingResult(
            product=result.product,
            mapped_data=mapped_data,
            unmapped_fields=result.unmapped_fields,
            channel=self.channel_code,
        )


# =============================================================================
# Unified Amazon Adapter (Auto-selects based on config)
# =============================================================================

class AmazonAdapter(AmazonBaseAdapter):
    """
    Unified Amazon adapter that auto-selects 1P or 3P based on configuration.

    Use this adapter when you want automatic selection of the appropriate
    selling model based on the channel document configuration.
    """

    channel_code: str = "amazon"
    channel_name: str = "Amazon"

    def __init__(self, channel_doc: Any = None):
        """Initialize and determine selling model.

        Args:
            channel_doc: Channel Frappe document with Amazon configuration
        """
        super().__init__(channel_doc)
        self._delegate: AmazonBaseAdapter = None

    @property
    def delegate(self) -> AmazonBaseAdapter:
        """Get the appropriate adapter based on selling model config."""
        if self._delegate is None:
            selling_model = self.config.get("selling_model", "3P").upper()

            if selling_model in ("1P", "VENDOR"):
                self._delegate = AmazonVendorAdapter(self.channel)
            else:
                self._delegate = AmazonSellerAdapter(self.channel)

        return self._delegate

    def _submit_to_amazon(self, payload: Dict) -> Dict:
        """Delegate to appropriate adapter."""
        return self.delegate._submit_to_amazon(payload)

    def get_status(self, job_id: str) -> StatusResult:
        """Delegate to appropriate adapter."""
        return self.delegate.get_status(job_id)

    def map_attributes(self, product: Dict) -> MappingResult:
        """Delegate to appropriate adapter for model-specific mapping."""
        return self.delegate.map_attributes(product)


# =============================================================================
# Register Adapters
# =============================================================================

register_adapter("amazon", AmazonAdapter)
register_adapter("amazon_seller", AmazonSellerAdapter)
register_adapter("amazon_vendor", AmazonVendorAdapter)
register_adapter("amazon_3p", AmazonSellerAdapter)
register_adapter("amazon_1p", AmazonVendorAdapter)
