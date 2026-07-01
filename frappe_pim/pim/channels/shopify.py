"""
Shopify Channel Adapter

Provides a comprehensive adapter for Shopify product syndication using both
GraphQL Admin API (primary) and REST Admin API for product management.

Features:
- GraphQL Admin API for efficient batch operations
- REST Admin API fallback for compatibility
- Leaky bucket rate limiting (2 requests/second for standard plans)
- Comprehensive product validation against Shopify requirements
- Attribute mapping to Shopify product/variant format
- Support for metafields, tags, and collections
- Inventory management across locations

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
# Shopify-Specific Constants
# =============================================================================

class ShopifyProductStatus(str, Enum):
    """Shopify product status values"""
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    DRAFT = "DRAFT"


class ShopifyWeightUnit(str, Enum):
    """Shopify weight unit values"""
    KILOGRAMS = "KILOGRAMS"
    GRAMS = "GRAMS"
    POUNDS = "POUNDS"
    OUNCES = "OUNCES"


class ShopifyInventoryPolicy(str, Enum):
    """Shopify inventory tracking policy"""
    CONTINUE = "CONTINUE"  # Continue selling when out of stock
    DENY = "DENY"  # Stop selling when out of stock


# Shopify rate limit configuration
SHOPIFY_RATE_LIMITS = {
    "graphql": {
        "points_per_second": 50,  # GraphQL uses cost-based throttling
        "max_points": 1000,
        "restore_rate": 50,  # Points restored per second
    },
    "rest": {
        "calls_per_second": 2,
        "bucket_size": 40,  # Leaky bucket size
    },
}

# Shopify API versions
SHOPIFY_API_VERSION = "2024-01"

# Required fields for Shopify products
SHOPIFY_REQUIRED_FIELDS = {
    "title",  # Product title is required
}

# Recommended fields for better listings
SHOPIFY_RECOMMENDED_FIELDS = {
    "description",
    "vendor",
    "product_type",
    "tags",
    "sku",
    "barcode",
    "price",
    "compare_at_price",
    "weight",
    "images",
}

# Field length limits
SHOPIFY_FIELD_LIMITS = {
    "title": 255,
    "handle": 255,
    "vendor": 255,
    "product_type": 255,
    "tags": 255,  # Per tag
    "sku": 255,
    "barcode": 255,
    "option_name": 255,
    "option_value": 255,
}

# PIM to Shopify field mappings
PIM_TO_SHOPIFY_FIELDS = {
    "item_code": "sku",
    "item_name": "title",
    "pim_title": "title",
    "pim_description": "descriptionHtml",
    "description": "descriptionHtml",
    "brand": "vendor",
    "item_group": "productType",
    "standard_rate": "price",
    "barcode": "barcode",
    "weight_per_unit": "weight",
    "net_weight": "weight",
    "country_of_origin": "countryOfOrigin",
    "image": "images",
}


# =============================================================================
# Shopify-Specific Data Classes
# =============================================================================

@dataclass
class ShopifyRateLimitState:
    """Tracks Shopify's leaky bucket rate limit state"""
    available_points: float = 1000.0  # GraphQL cost points available
    maximum_points: float = 1000.0  # Maximum bucket size
    restore_rate: float = 50.0  # Points restored per second
    last_request: datetime = field(default_factory=datetime.now)
    retry_after: datetime = None

    # REST API tracking (calls-based)
    rest_calls_remaining: int = 40
    rest_calls_limit: int = 40

    def is_limited(self) -> bool:
        """Check if currently rate limited"""
        if self.retry_after and datetime.now() < self.retry_after:
            return True

        # Restore points based on time elapsed
        self._restore_points()

        return self.available_points < 10  # Reserve minimum points

    def _restore_points(self) -> None:
        """Restore points based on elapsed time"""
        if self.last_request:
            elapsed = (datetime.now() - self.last_request).total_seconds()
            restored = elapsed * self.restore_rate
            self.available_points = min(
                self.maximum_points,
                self.available_points + restored
            )

    def record_cost(self, cost: float) -> None:
        """Record the cost of a GraphQL request"""
        self._restore_points()
        self.available_points = max(0, self.available_points - cost)
        self.last_request = datetime.now()

    def wait_time(self) -> float:
        """Calculate wait time before next request"""
        if self.retry_after:
            delta = self.retry_after - datetime.now()
            if delta.total_seconds() > 0:
                return delta.total_seconds()

        if self.is_limited():
            # Calculate time to restore enough points
            points_needed = 10 - self.available_points
            return points_needed / self.restore_rate

        return 0


@dataclass
class ShopifyJob:
    """Tracks a Shopify bulk operation job"""
    job_id: str
    operation_type: str  # PRODUCT_CREATE, PRODUCT_UPDATE
    status: str  # CREATED, RUNNING, COMPLETED, FAILED
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime = None
    object_count: int = 0
    url: str = None  # JSONL result URL when completed
    errors: List[Dict] = field(default_factory=list)


# =============================================================================
# GraphQL Queries and Mutations
# =============================================================================

GRAPHQL_CREATE_PRODUCT = """
mutation productCreate($input: ProductInput!, $media: [CreateMediaInput!]) {
  productCreate(input: $input, media: $media) {
    product {
      id
      title
      handle
      status
      variants(first: 10) {
        edges {
          node {
            id
            sku
            price
            barcode
            inventoryQuantity
          }
        }
      }
    }
    userErrors {
      field
      message
    }
  }
}
"""

GRAPHQL_UPDATE_PRODUCT = """
mutation productUpdate($input: ProductInput!) {
  productUpdate(input: $input) {
    product {
      id
      title
      handle
      status
      updatedAt
    }
    userErrors {
      field
      message
    }
  }
}
"""

GRAPHQL_GET_PRODUCT = """
query getProduct($id: ID!) {
  product(id: $id) {
    id
    title
    handle
    status
    createdAt
    updatedAt
    variants(first: 100) {
      edges {
        node {
          id
          sku
          price
          barcode
        }
      }
    }
  }
}
"""

GRAPHQL_BULK_OPERATION_STATUS = """
query bulkOperationStatus($id: ID!) {
  node(id: $id) {
    ... on BulkOperation {
      id
      status
      errorCode
      createdAt
      completedAt
      objectCount
      url
    }
  }
}
"""

GRAPHQL_PRODUCT_VARIANT_CREATE = """
mutation productVariantCreate($input: ProductVariantInput!) {
  productVariantCreate(input: $input) {
    productVariant {
      id
      sku
      price
      barcode
    }
    userErrors {
      field
      message
    }
  }
}
"""


# =============================================================================
# Shopify Adapter
# =============================================================================

class ShopifyAdapter(ChannelAdapter):
    """
    Shopify channel adapter for product syndication.

    Uses the Shopify GraphQL Admin API (2024-01) for efficient product
    management with support for bulk operations. Falls back to REST API
    for specific operations when needed.

    Features:
    - GraphQL Admin API with cost-based rate limiting
    - Bulk operation support for large catalogs
    - Product, variant, and inventory management
    - Metafield support for custom attributes
    - Multi-location inventory tracking
    """

    channel_code: str = "shopify"
    channel_name: str = "Shopify"

    # Rate limiting settings (conservative for standard plans)
    default_requests_per_minute: int = 120
    default_requests_per_second: float = 2.0
    max_retry_attempts: int = 5
    base_backoff_seconds: float = 0.5
    max_backoff_seconds: float = 60.0

    def __init__(self, channel_doc: Any = None):
        """Initialize Shopify adapter.

        Args:
            channel_doc: Channel Frappe document with Shopify credentials
        """
        super().__init__(channel_doc)
        self._rate_limit_state: ShopifyRateLimitState = None
        self._shop_domain: str = None
        self._api_version: str = SHOPIFY_API_VERSION
        self._job_tracker: Dict[str, ShopifyJob] = {}

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def shop_domain(self) -> str:
        """Get the Shopify shop domain."""
        if self._shop_domain:
            return self._shop_domain

        # Get from config or channel document
        domain = self.config.get("shop_domain") or self.config.get("base_url", "")

        # Normalize domain
        domain = domain.replace("https://", "").replace("http://", "")
        domain = domain.rstrip("/")

        # Ensure .myshopify.com format
        if domain and not domain.endswith(".myshopify.com"):
            if ".myshopify.com" not in domain:
                domain = f"{domain}.myshopify.com"

        self._shop_domain = domain
        return self._shop_domain

    @property
    def graphql_url(self) -> str:
        """Get the GraphQL Admin API endpoint."""
        return f"https://{self.shop_domain}/admin/api/{self._api_version}/graphql.json"

    @property
    def rest_url(self) -> str:
        """Get the REST Admin API base URL."""
        return f"https://{self.shop_domain}/admin/api/{self._api_version}"

    @property
    def rate_limit_state(self) -> ShopifyRateLimitState:
        """Get current rate limit state."""
        if self._rate_limit_state is None:
            self._rate_limit_state = ShopifyRateLimitState()
        return self._rate_limit_state

    # =========================================================================
    # Authentication Methods
    # =========================================================================

    def _get_shopify_credentials(self) -> Dict:
        """Get Shopify-specific credentials.

        Returns:
            Dictionary with:
            - access_token: Admin API access token
            - api_key: Optional API key (for private apps)
            - api_secret: Optional API secret (for private apps)
        """
        credentials = self.credentials

        return {
            "access_token": credentials.get("access_token") or credentials.get("api_key"),
            "api_key": credentials.get("api_key"),
            "api_secret": credentials.get("api_secret"),
        }

    def _get_auth_headers(self) -> Dict:
        """Build authentication headers for Shopify API requests.

        Returns:
            Dictionary of HTTP headers including authorization
        """
        creds = self._get_shopify_credentials()
        access_token = creds.get("access_token")

        if not access_token:
            raise AuthenticationError(
                "Shopify access token not configured",
                channel=self.channel_code,
            )

        return {
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # =========================================================================
    # Rate Limiting Methods
    # =========================================================================

    def handle_rate_limiting(self, response: Any = None) -> None:
        """Handle Shopify rate limiting from response headers.

        Parses X-Shopify-Shop-Api-Call-Limit for REST API and
        extensions.cost for GraphQL API responses.

        Args:
            response: HTTP response or GraphQL response object

        Raises:
            RateLimitError: If rate limit exceeded and cannot proceed
        """
        if response is None:
            return

        # Check for 429 Too Many Requests
        if hasattr(response, 'status_code') and response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 2))
            self.rate_limit_state.retry_after = datetime.now() + timedelta(seconds=retry_after)

            raise RateLimitError(
                "Shopify API rate limit exceeded",
                channel=self.channel_code,
                retry_after=retry_after,
                details={
                    "status_code": 429,
                    "retry_after": retry_after,
                },
            )

        # Parse REST API rate limit header
        # Format: "32/40" (calls used / bucket size)
        if hasattr(response, 'headers'):
            call_limit = response.headers.get("X-Shopify-Shop-Api-Call-Limit")
            if call_limit:
                try:
                    used, limit = call_limit.split("/")
                    self.rate_limit_state.rest_calls_remaining = int(limit) - int(used)
                    self.rate_limit_state.rest_calls_limit = int(limit)
                except ValueError:
                    pass

        # Parse GraphQL cost from response
        if isinstance(response, dict):
            extensions = response.get("extensions", {})
            cost = extensions.get("cost", {})

            throttle_status = cost.get("throttleStatus", {})
            if throttle_status:
                self.rate_limit_state.available_points = float(
                    throttle_status.get("currentlyAvailable", 1000)
                )
                self.rate_limit_state.maximum_points = float(
                    throttle_status.get("maximumAvailable", 1000)
                )
                self.rate_limit_state.restore_rate = float(
                    throttle_status.get("restoreRate", 50)
                )

            # Record actual cost
            actual_cost = cost.get("actualQueryCost")
            if actual_cost:
                self.rate_limit_state.record_cost(float(actual_cost))

    def _wait_for_rate_limit(self) -> None:
        """Wait if rate limited.

        Raises:
            RateLimitError: If wait time exceeds maximum
        """
        wait_time = self.rate_limit_state.wait_time()

        if wait_time > 0:
            if wait_time > self.max_backoff_seconds:
                raise RateLimitError(
                    f"Shopify rate limit wait time ({wait_time}s) exceeds maximum",
                    channel=self.channel_code,
                    retry_after=int(wait_time),
                )
            time.sleep(wait_time)

    # =========================================================================
    # GraphQL Methods
    # =========================================================================

    def _execute_graphql(self, query: str, variables: Dict = None) -> Dict:
        """Execute a GraphQL query against Shopify Admin API.

        Args:
            query: GraphQL query or mutation string
            variables: Optional variables for the query

        Returns:
            GraphQL response data

        Raises:
            AuthenticationError: If authentication fails
            RateLimitError: If rate limit exceeded
            PublishError: If request fails
        """
        import requests

        self._wait_for_rate_limit()

        headers = self._get_auth_headers()

        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        last_error = None

        for attempt in range(self.max_retry_attempts):
            try:
                response = requests.post(
                    self.graphql_url,
                    headers=headers,
                    json=payload,
                    timeout=self.config.get("timeout", 30),
                )

                # Handle rate limiting
                self.handle_rate_limiting(response)

                # Check for auth errors
                if response.status_code in (401, 403):
                    raise AuthenticationError(
                        f"Shopify authentication failed: HTTP {response.status_code}",
                        channel=self.channel_code,
                    )

                if response.status_code != 200:
                    raise PublishError(
                        f"Shopify API error: HTTP {response.status_code}",
                        channel=self.channel_code,
                        details={"response": response.text},
                    )

                result = response.json()

                # Handle GraphQL-level rate limiting
                self.handle_rate_limiting(result)

                # Check for GraphQL errors
                if "errors" in result:
                    errors = result["errors"]
                    # Check for throttling
                    for error in errors:
                        if "THROTTLED" in str(error.get("extensions", {})):
                            backoff = self._calculate_backoff(attempt)
                            time.sleep(backoff)
                            continue

                    raise PublishError(
                        "GraphQL query failed",
                        channel=self.channel_code,
                        details={"errors": errors},
                    )

                return result.get("data", {})

            except RateLimitError:
                backoff = self._calculate_backoff(attempt)
                time.sleep(backoff)
                last_error = RateLimitError(
                    "Rate limit exceeded after retries",
                    channel=self.channel_code,
                )

            except requests.exceptions.RequestException as e:
                last_error = e
                if attempt < self.max_retry_attempts - 1:
                    backoff = self._calculate_backoff(attempt)
                    time.sleep(backoff)

        if isinstance(last_error, RateLimitError):
            raise last_error
        raise PublishError(
            f"GraphQL request failed after {self.max_retry_attempts} attempts: {last_error}",
            channel=self.channel_code,
        )

    # =========================================================================
    # Validation Methods
    # =========================================================================

    def validate_product(self, product: Dict) -> ValidationResult:
        """Validate a product against Shopify's requirements.

        Checks required fields, field length limits, barcode format,
        and other Shopify-specific requirements.

        Args:
            product: Product data dictionary in PIM format

        Returns:
            ValidationResult with validation status and any errors/warnings
        """
        errors = []
        warnings = []
        product_id = product.get("item_code", product.get("sku", "unknown"))

        # Check required fields
        for field_name in SHOPIFY_REQUIRED_FIELDS:
            # Check both PIM and Shopify field names
            pim_field = None
            for pim_name, shopify_name in PIM_TO_SHOPIFY_FIELDS.items():
                if shopify_name == field_name or field_name == pim_name:
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
        for field_name, max_length in SHOPIFY_FIELD_LIMITS.items():
            value = product.get(field_name) or ""
            if isinstance(value, str) and len(value) > max_length:
                errors.append({
                    "field": field_name,
                    "message": f"Field '{field_name}' exceeds maximum length of {max_length} characters",
                    "value": f"{len(value)} characters",
                    "rule": "max_length",
                })

        # Validate barcode if provided
        barcode = product.get("barcode") or product.get("gtin")
        if barcode:
            barcode_error = self._validate_barcode(barcode)
            if barcode_error:
                warnings.append(barcode_error)  # Barcode is optional, so warning

        # Validate price if provided
        price = product.get("standard_rate") or product.get("price")
        if price is not None:
            try:
                price_val = float(price)
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

        # Validate compare_at_price if provided
        compare_price = product.get("compare_at_price")
        if compare_price is not None and price is not None:
            try:
                compare_val = float(compare_price)
                price_val = float(price)
                if compare_val <= price_val:
                    warnings.append({
                        "field": "compare_at_price",
                        "message": "Compare at price should be greater than price for sale display",
                        "value": str(compare_price),
                        "rule": "compare_at_price_logic",
                    })
            except (ValueError, TypeError):
                pass

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

        # Check for recommended fields
        for field_name in SHOPIFY_RECOMMENDED_FIELDS:
            if field_name not in product and field_name not in SHOPIFY_REQUIRED_FIELDS:
                pim_field = None
                for pim_name, shopify_name in PIM_TO_SHOPIFY_FIELDS.items():
                    if shopify_name == field_name:
                        pim_field = pim_name
                        break

                if pim_field and pim_field not in product:
                    if field_name not in product:
                        warnings.append({
                            "field": field_name,
                            "message": f"Recommended field '{field_name}' not provided",
                            "rule": "recommended",
                        })

        # Validate tags
        tags = product.get("tags")
        if tags:
            tag_warnings = self._validate_tags(tags)
            warnings.extend(tag_warnings)

        return ValidationResult(
            is_valid=len(errors) == 0,
            product=product_id,
            errors=errors,
            warnings=warnings,
            channel=self.channel_code,
        )

    def _validate_barcode(self, barcode: str) -> Optional[Dict]:
        """Validate barcode format.

        Args:
            barcode: Barcode string (UPC, EAN, ISBN, etc.)

        Returns:
            Warning dict if issues found, None if valid
        """
        barcode = str(barcode).replace(" ", "").replace("-", "")

        # Shopify accepts various formats
        valid_lengths = {8, 12, 13, 14}  # EAN-8, UPC-A, EAN-13, GTIN-14

        if len(barcode) not in valid_lengths:
            return {
                "field": "barcode",
                "message": f"Barcode length {len(barcode)} may not be recognized (expected 8, 12, 13, or 14 digits)",
                "value": barcode,
                "rule": "barcode_length",
            }

        if not barcode.isdigit():
            return {
                "field": "barcode",
                "message": "Barcode should contain only digits",
                "value": barcode,
                "rule": "barcode_format",
            }

        return None

    def _validate_tags(self, tags: Any) -> List[Dict]:
        """Validate product tags.

        Args:
            tags: Tags string (comma-separated) or list

        Returns:
            List of warning dicts for tag issues
        """
        warnings = []

        if isinstance(tags, str):
            tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        elif isinstance(tags, list):
            tag_list = tags
        else:
            return warnings

        # Check tag count (Shopify has no hard limit, but many tags can be problematic)
        if len(tag_list) > 250:
            warnings.append({
                "field": "tags",
                "message": "Large number of tags may impact performance",
                "value": str(len(tag_list)),
                "rule": "tag_count",
            })

        # Check individual tag length
        for tag in tag_list:
            if len(str(tag)) > SHOPIFY_FIELD_LIMITS["tags"]:
                warnings.append({
                    "field": "tags",
                    "message": f"Tag exceeds {SHOPIFY_FIELD_LIMITS['tags']} characters",
                    "value": str(tag)[:50],
                    "rule": "tag_length",
                })

        return warnings

    # =========================================================================
    # Mapping Methods
    # =========================================================================

    def map_attributes(self, product: Dict) -> MappingResult:
        """Map PIM product attributes to Shopify format.

        Converts internal field names to Shopify's expected GraphQL input
        format including proper nested structures for variants.

        Args:
            product: Product data dictionary in PIM format

        Returns:
            MappingResult with mapped data and unmapped fields
        """
        product_id = product.get("item_code", product.get("sku", "unknown"))
        mapped_data = {}
        unmapped_fields = []

        # Map basic product fields
        # Title
        title = product.get("pim_title") or product.get("item_name") or product.get("title")
        if title:
            mapped_data["title"] = str(title)

        # Description (HTML supported)
        description = product.get("pim_description") or product.get("description")
        if description:
            mapped_data["descriptionHtml"] = str(description)

        # Vendor (brand)
        vendor = product.get("brand") or product.get("vendor")
        if vendor:
            mapped_data["vendor"] = str(vendor)

        # Product type
        product_type = product.get("item_group") or product.get("product_type") or product.get("productType")
        if product_type:
            mapped_data["productType"] = str(product_type)

        # Handle (URL slug)
        handle = product.get("handle")
        if handle:
            mapped_data["handle"] = str(handle).lower().replace(" ", "-")

        # Tags
        tags = product.get("tags")
        if tags:
            if isinstance(tags, str):
                mapped_data["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
            elif isinstance(tags, list):
                mapped_data["tags"] = tags

        # Status
        status = product.get("status") or product.get("custom_pim_status")
        if status:
            status_upper = str(status).upper()
            if status_upper in ("ACTIVE", "PUBLISHED", "ENABLED"):
                mapped_data["status"] = ShopifyProductStatus.ACTIVE.value
            elif status_upper in ("ARCHIVED", "DISABLED"):
                mapped_data["status"] = ShopifyProductStatus.ARCHIVED.value
            else:
                mapped_data["status"] = ShopifyProductStatus.DRAFT.value
        else:
            mapped_data["status"] = ShopifyProductStatus.ACTIVE.value

        # SEO fields
        seo_title = product.get("seo_title") or product.get("meta_title")
        seo_description = product.get("seo_description") or product.get("meta_description")
        if seo_title or seo_description:
            mapped_data["seo"] = {}
            if seo_title:
                mapped_data["seo"]["title"] = str(seo_title)[:70]
            if seo_description:
                mapped_data["seo"]["description"] = str(seo_description)[:320]

        # Build variant data
        variant_data = self._map_variant_attributes(product)
        if variant_data:
            mapped_data["variants"] = [variant_data]

        # Map images
        images = product.get("images") or product.get("image")
        if images:
            mapped_data["images"] = self._map_images(images)

        # Map metafields for custom attributes
        metafields = self._map_metafields(product)
        if metafields:
            mapped_data["metafields"] = metafields

        # Track unmapped fields
        mapped_pim_fields = set(PIM_TO_SHOPIFY_FIELDS.keys())
        mapped_pim_fields.update({
            "title", "description", "vendor", "product_type", "productType",
            "handle", "tags", "status", "custom_pim_status", "seo_title", "meta_title",
            "seo_description", "meta_description", "images", "image",
            "sku", "price", "standard_rate", "compare_at_price", "barcode",
            "weight", "weight_per_unit", "net_weight", "weight_unit",
            "quantity", "stock_qty", "requires_shipping", "taxable",
            "inventory_policy", "country_of_origin",
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

    def _map_variant_attributes(self, product: Dict) -> Dict:
        """Map product attributes to Shopify variant format.

        Args:
            product: Product data dictionary

        Returns:
            Variant input dictionary
        """
        variant = {}

        # SKU
        sku = product.get("item_code") or product.get("sku")
        if sku:
            variant["sku"] = str(sku)

        # Price
        price = product.get("standard_rate") or product.get("price")
        if price is not None:
            variant["price"] = str(float(price))

        # Compare at price
        compare_price = product.get("compare_at_price")
        if compare_price is not None:
            variant["compareAtPrice"] = str(float(compare_price))

        # Barcode
        barcode = product.get("barcode") or product.get("gtin")
        if barcode:
            variant["barcode"] = str(barcode).replace(" ", "").replace("-", "")

        # Weight
        weight = product.get("weight_per_unit") or product.get("weight") or product.get("net_weight")
        if weight is not None:
            variant["weight"] = float(weight)

            # Weight unit
            weight_unit = product.get("weight_unit", "kg").upper()
            unit_mapping = {
                "KG": ShopifyWeightUnit.KILOGRAMS.value,
                "KILOGRAMS": ShopifyWeightUnit.KILOGRAMS.value,
                "G": ShopifyWeightUnit.GRAMS.value,
                "GRAMS": ShopifyWeightUnit.GRAMS.value,
                "LB": ShopifyWeightUnit.POUNDS.value,
                "LBS": ShopifyWeightUnit.POUNDS.value,
                "POUNDS": ShopifyWeightUnit.POUNDS.value,
                "OZ": ShopifyWeightUnit.OUNCES.value,
                "OUNCES": ShopifyWeightUnit.OUNCES.value,
            }
            variant["weightUnit"] = unit_mapping.get(weight_unit, ShopifyWeightUnit.KILOGRAMS.value)

        # Inventory management
        variant["inventoryManagement"] = "SHOPIFY"

        # Inventory policy
        inventory_policy = product.get("inventory_policy", "DENY")
        if str(inventory_policy).upper() == "CONTINUE":
            variant["inventoryPolicy"] = ShopifyInventoryPolicy.CONTINUE.value
        else:
            variant["inventoryPolicy"] = ShopifyInventoryPolicy.DENY.value

        # Requires shipping
        requires_shipping = product.get("requires_shipping", True)
        variant["requiresShipping"] = bool(requires_shipping)

        # Taxable
        taxable = product.get("taxable", True)
        variant["taxable"] = bool(taxable)

        # Country of origin
        country = product.get("country_of_origin")
        if country:
            variant["countryOfOrigin"] = str(country).upper()[:2]  # ISO country code

        return variant if variant else None

    def _map_images(self, images: Any) -> List[Dict]:
        """Map images to Shopify media input format.

        Args:
            images: Image data (URL, list of URLs, or list of dicts)

        Returns:
            List of media input dictionaries
        """
        media_list = []

        if isinstance(images, str):
            images = [images]

        if isinstance(images, list):
            for i, img in enumerate(images[:250]):  # Shopify limit
                if isinstance(img, str):
                    media_list.append({
                        "originalSource": img,
                        "mediaContentType": "IMAGE",
                    })
                elif isinstance(img, dict):
                    url = img.get("url") or img.get("src")
                    if url:
                        entry = {
                            "originalSource": url,
                            "mediaContentType": "IMAGE",
                        }
                        alt = img.get("alt") or img.get("alt_text")
                        if alt:
                            entry["alt"] = str(alt)
                        media_list.append(entry)

        return media_list

    def _map_metafields(self, product: Dict) -> List[Dict]:
        """Map custom attributes to Shopify metafields.

        Args:
            product: Product data dictionary

        Returns:
            List of metafield input dictionaries
        """
        metafields = []

        # Map specific custom fields to metafields
        custom_field_mappings = {
            "custom_field_1": ("custom", "field_1", "single_line_text_field"),
            "custom_field_2": ("custom", "field_2", "single_line_text_field"),
            "custom_pim_completeness": ("pim", "completeness", "number_decimal"),
            "custom_pim_data_quality_score": ("pim", "quality_score", "number_decimal"),
        }

        for field_name, (namespace, key, value_type) in custom_field_mappings.items():
            if field_name in product and product[field_name] is not None:
                value = product[field_name]

                # Format value based on type
                if value_type == "number_decimal":
                    value = str(float(value))
                elif value_type == "json":
                    value = json.dumps(value)
                else:
                    value = str(value)

                metafields.append({
                    "namespace": namespace,
                    "key": key,
                    "value": value,
                    "type": value_type,
                })

        return metafields

    # =========================================================================
    # Payload Generation
    # =========================================================================

    def generate_payload(self, products: List[Dict]) -> Dict:
        """Generate GraphQL mutation payloads for products.

        Creates ProductInput structures compatible with Shopify's
        productCreate and productUpdate mutations.

        Args:
            products: List of mapped product data dictionaries

        Returns:
            Dictionary with products ready for GraphQL mutations
        """
        payload = {
            "products": [],
            "_metadata": {
                "batch_id": str(uuid.uuid4()),
                "created_at": datetime.now().isoformat(),
                "product_count": len(products),
            },
        }

        for product in products:
            product_input = {
                "input": self._build_product_input(product),
            }

            # Add media if present
            if "images" in product and product["images"]:
                product_input["media"] = product["images"]

            payload["products"].append(product_input)

        return payload

    def _build_product_input(self, product: Dict) -> Dict:
        """Build ProductInput for GraphQL mutation.

        Args:
            product: Mapped product data

        Returns:
            ProductInput dictionary
        """
        input_data = {}

        # Copy simple fields
        simple_fields = ["title", "descriptionHtml", "vendor", "productType", "handle", "status"]
        for field in simple_fields:
            if field in product:
                input_data[field] = product[field]

        # Tags
        if "tags" in product:
            input_data["tags"] = product["tags"]

        # SEO
        if "seo" in product:
            input_data["seo"] = product["seo"]

        # Variants
        if "variants" in product:
            input_data["variants"] = product["variants"]

        # Metafields
        if "metafields" in product:
            input_data["metafields"] = product["metafields"]

        # Shopify product ID for updates
        if "id" in product:
            input_data["id"] = product["id"]

        return input_data

    # =========================================================================
    # Publishing Methods
    # =========================================================================

    def publish(self, products: List[Dict]) -> PublishResult:
        """Publish products to Shopify.

        Handles the complete publishing workflow including validation,
        mapping, and GraphQL mutation submission.

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

            # Map products to Shopify format
            mapped_products = []
            for product in products:
                mapping_result = self.map_attributes(product)
                mapped_products.append(mapping_result.mapped_data)

            # Generate payload
            payload = self.generate_payload(mapped_products)

            # Submit to Shopify
            external_ids = []

            for product_payload in payload["products"]:
                try:
                    result = self._submit_product(product_payload)

                    if result.get("success"):
                        products_succeeded += 1
                        if result.get("product_id"):
                            external_ids.append(result["product_id"])
                    else:
                        products_failed += 1
                        errors.append(result.get("error", {"message": "Unknown error"}))

                    products_submitted += 1

                except RateLimitError as e:
                    # If rate limited mid-batch, return partial result
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
                success = True  # Partial success
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

    def _submit_product(self, product_payload: Dict) -> Dict:
        """Submit a single product to Shopify.

        Args:
            product_payload: Product input with optional media

        Returns:
            Dict with success status and product_id or error
        """
        input_data = product_payload.get("input", {})
        media = product_payload.get("media")

        # Determine if update or create
        is_update = "id" in input_data

        if is_update:
            query = GRAPHQL_UPDATE_PRODUCT
            variables = {"input": input_data}
            operation_name = "productUpdate"
        else:
            query = GRAPHQL_CREATE_PRODUCT
            variables = {"input": input_data}
            if media:
                variables["media"] = media
            operation_name = "productCreate"

        result = self._execute_graphql(query, variables)

        operation_result = result.get(operation_name, {})
        user_errors = operation_result.get("userErrors", [])

        if user_errors:
            return {
                "success": False,
                "error": {
                    "message": user_errors[0].get("message", "Unknown error"),
                    "field": user_errors[0].get("field"),
                    "all_errors": user_errors,
                },
            }

        product_data = operation_result.get("product", {})

        return {
            "success": True,
            "product_id": product_data.get("id"),
            "handle": product_data.get("handle"),
        }

    # =========================================================================
    # Status Methods
    # =========================================================================

    def get_status(self, job_id: str) -> StatusResult:
        """Check the status of a publish job.

        For Shopify, immediate mutations return synchronously, so this
        primarily checks bulk operation status for large batches.

        Args:
            job_id: The job ID from publish() or bulk operation ID

        Returns:
            StatusResult with current job status and progress
        """
        # Check if this is a bulk operation ID
        if job_id.startswith("gid://shopify/BulkOperation/"):
            return self._get_bulk_operation_status(job_id)

        # For regular jobs, check our internal tracker
        if job_id in self._job_tracker:
            job = self._job_tracker[job_id]

            status_mapping = {
                "CREATED": PublishStatus.PENDING,
                "RUNNING": PublishStatus.IN_PROGRESS,
                "COMPLETED": PublishStatus.COMPLETED,
                "FAILED": PublishStatus.FAILED,
            }

            return StatusResult(
                job_id=job_id,
                status=status_mapping.get(job.status, PublishStatus.IN_PROGRESS),
                progress=1.0 if job.status == "COMPLETED" else 0.5,
                products_processed=job.object_count,
                errors=job.errors,
                channel=self.channel_code,
                completed_at=job.completed_at,
            )

        # For synchronous operations, return completed
        return StatusResult(
            job_id=job_id,
            status=PublishStatus.COMPLETED,
            progress=1.0,
            channel=self.channel_code,
        )

    def _get_bulk_operation_status(self, operation_id: str) -> StatusResult:
        """Check status of a Shopify bulk operation.

        Args:
            operation_id: The bulk operation GID

        Returns:
            StatusResult with operation status
        """
        try:
            result = self._execute_graphql(
                GRAPHQL_BULK_OPERATION_STATUS,
                {"id": operation_id}
            )

            node = result.get("node", {})

            if not node:
                return StatusResult(
                    job_id=operation_id,
                    status=PublishStatus.FAILED,
                    errors=[{"message": "Bulk operation not found"}],
                    channel=self.channel_code,
                )

            status_str = node.get("status", "").upper()

            status_mapping = {
                "CREATED": PublishStatus.PENDING,
                "RUNNING": PublishStatus.IN_PROGRESS,
                "COMPLETED": PublishStatus.COMPLETED,
                "FAILED": PublishStatus.FAILED,
                "CANCELLED": PublishStatus.CANCELLED,
            }

            status = status_mapping.get(status_str, PublishStatus.IN_PROGRESS)

            errors = []
            if node.get("errorCode"):
                errors.append({
                    "code": node["errorCode"],
                    "message": f"Bulk operation error: {node['errorCode']}",
                })

            completed_at = None
            if node.get("completedAt"):
                try:
                    completed_at = datetime.fromisoformat(
                        node["completedAt"].replace("Z", "+00:00")
                    )
                except ValueError:
                    pass

            return StatusResult(
                job_id=operation_id,
                status=status,
                progress=1.0 if status == PublishStatus.COMPLETED else 0.5,
                products_total=node.get("objectCount", 0),
                products_processed=node.get("objectCount", 0) if status == PublishStatus.COMPLETED else 0,
                errors=errors,
                channel=self.channel_code,
                completed_at=completed_at,
            )

        except Exception as e:
            return StatusResult(
                job_id=operation_id,
                status=PublishStatus.FAILED,
                errors=[{"message": f"Status check failed: {str(e)}"}],
                channel=self.channel_code,
            )

    # =========================================================================
    # Additional Methods
    # =========================================================================

    def test_connection(self) -> Dict:
        """Test the connection to Shopify.

        Returns:
            Dictionary with connection status and shop info
        """
        import frappe

        try:
            if not self.shop_domain:
                return {
                    "success": False,
                    "message": frappe._("Shop domain is not configured") if 'frappe' in dir() else "Shop domain is not configured",
                }

            # Query shop info to test connection
            query = """
            query {
              shop {
                name
                primaryDomain {
                  url
                }
                plan {
                  displayName
                }
              }
            }
            """

            result = self._execute_graphql(query)
            shop = result.get("shop", {})

            if shop:
                return {
                    "success": True,
                    "message": "Connection successful",
                    "shop_name": shop.get("name"),
                    "domain": shop.get("primaryDomain", {}).get("url"),
                    "plan": shop.get("plan", {}).get("displayName"),
                }
            else:
                return {
                    "success": False,
                    "message": "Could not retrieve shop information",
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
        """Retrieve a product from Shopify by SKU.

        Args:
            sku: The product SKU to search for

        Returns:
            Product data dict if found, None otherwise
        """
        query = """
        query getProductBySku($query: String!) {
          products(first: 1, query: $query) {
            edges {
              node {
                id
                title
                handle
                status
                variants(first: 1) {
                  edges {
                    node {
                      id
                      sku
                      price
                      barcode
                    }
                  }
                }
              }
            }
          }
        }
        """

        try:
            result = self._execute_graphql(query, {"query": f"sku:{sku}"})
            edges = result.get("products", {}).get("edges", [])

            if edges:
                return edges[0].get("node")
            return None

        except Exception:
            return None


# =============================================================================
# Register Adapter
# =============================================================================

register_adapter("shopify", ShopifyAdapter)
