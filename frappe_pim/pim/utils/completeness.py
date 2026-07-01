"""Product Data Completeness Scoring

This module provides functions for calculating product data quality scores
based on the percentage of required fields and attributes that are filled.

The completeness score is calculated as:
    Score = (filled_required / total_required) * 100

Required fields come from:
    1. Core product fields (product_name, product_code, short_description)
    2. Family Attribute Templates marked as required
    3. Channel-specific requirements for syndication readiness

Additional features:
    - Channel-specific scoring rules per marketplace (Amazon, Shopify, etc.)
    - Gap analysis to identify missing fields for each channel
    - Weighted scoring based on field importance
    - Remediation recommendations for quality improvement

These functions are called as doc_events hooks when Product Master
or Product Variant documents are saved.

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum


# =============================================================================
# Channel Requirement Definitions
# =============================================================================

class FieldImportance(str, Enum):
    """Importance level for fields affecting score weights"""
    CRITICAL = "critical"     # Score drops to 0 if missing
    REQUIRED = "required"     # Standard required field
    RECOMMENDED = "recommended"  # Impacts score but not blocking
    OPTIONAL = "optional"     # Nice to have


@dataclass
class FieldRequirement:
    """Defines a field requirement for channel compliance"""
    field_name: str
    importance: FieldImportance = FieldImportance.REQUIRED
    min_length: int = None
    max_length: int = None
    pattern: str = None  # Regex pattern
    allowed_values: List[str] = None
    description: str = ""
    remediation: str = ""  # How to fix if missing

    def to_dict(self) -> Dict:
        return {
            "field_name": self.field_name,
            "importance": self.importance.value,
            "min_length": self.min_length,
            "max_length": self.max_length,
            "pattern": self.pattern,
            "allowed_values": self.allowed_values,
            "description": self.description,
            "remediation": self.remediation,
        }


@dataclass
class ChannelRequirements:
    """Complete requirements for a channel"""
    channel_code: str
    channel_name: str
    core_fields: List[FieldRequirement] = field(default_factory=list)
    attribute_fields: List[FieldRequirement] = field(default_factory=list)
    media_requirements: Dict = field(default_factory=dict)
    category_required: bool = False
    gtin_required: bool = False
    description: str = ""

    def get_all_required_fields(self) -> List[str]:
        """Get all required and critical field names"""
        fields = []
        for req in self.core_fields + self.attribute_fields:
            if req.importance in (FieldImportance.CRITICAL, FieldImportance.REQUIRED):
                fields.append(req.field_name)
        return fields

    def get_critical_fields(self) -> List[str]:
        """Get only critical field names"""
        return [
            req.field_name for req in self.core_fields + self.attribute_fields
            if req.importance == FieldImportance.CRITICAL
        ]

    def to_dict(self) -> Dict:
        return {
            "channel_code": self.channel_code,
            "channel_name": self.channel_name,
            "core_fields": [f.to_dict() for f in self.core_fields],
            "attribute_fields": [f.to_dict() for f in self.attribute_fields],
            "media_requirements": self.media_requirements,
            "category_required": self.category_required,
            "gtin_required": self.gtin_required,
            "description": self.description,
        }


# Channel-specific requirement definitions
CHANNEL_REQUIREMENTS: Dict[str, ChannelRequirements] = {
    "amazon": ChannelRequirements(
        channel_code="amazon",
        channel_name="Amazon",
        description="Amazon Marketplace listing requirements",
        gtin_required=True,
        category_required=True,
        core_fields=[
            FieldRequirement(
                field_name="product_name",
                importance=FieldImportance.CRITICAL,
                min_length=1,
                max_length=200,
                description="Product title shown in search results",
                remediation="Add a descriptive product title between 1-200 characters"
            ),
            FieldRequirement(
                field_name="short_description",
                importance=FieldImportance.REQUIRED,
                min_length=50,
                max_length=2000,
                description="Product bullet points/features",
                remediation="Add product bullet points (minimum 50 characters)"
            ),
            FieldRequirement(
                field_name="long_description",
                importance=FieldImportance.RECOMMENDED,
                min_length=100,
                description="Full product description",
                remediation="Add detailed product description for better conversion"
            ),
            FieldRequirement(
                field_name="gtin",
                importance=FieldImportance.CRITICAL,
                pattern=r"^\d{8,14}$",
                description="UPC/EAN/GTIN barcode",
                remediation="Add valid GTIN (8-14 digit barcode)"
            ),
            FieldRequirement(
                field_name="brand",
                importance=FieldImportance.REQUIRED,
                description="Product brand name",
                remediation="Add brand name for this product"
            ),
            FieldRequirement(
                field_name="manufacturer",
                importance=FieldImportance.RECOMMENDED,
                description="Manufacturer name",
                remediation="Add manufacturer information"
            ),
        ],
        attribute_fields=[
            FieldRequirement(
                field_name="weight",
                importance=FieldImportance.REQUIRED,
                description="Product weight for shipping",
                remediation="Add product weight for shipping calculation"
            ),
            FieldRequirement(
                field_name="dimensions",
                importance=FieldImportance.REQUIRED,
                description="Product dimensions (L x W x H)",
                remediation="Add product dimensions for shipping"
            ),
        ],
        media_requirements={
            "min_images": 1,
            "recommended_images": 7,
            "main_image_required": True,
            "min_resolution": 1000,  # pixels
            "max_resolution": 10000,
            "allowed_formats": ["jpg", "jpeg", "png", "gif", "tiff"],
            "white_background_required": True,
        }
    ),

    "shopify": ChannelRequirements(
        channel_code="shopify",
        channel_name="Shopify",
        description="Shopify store product requirements",
        gtin_required=False,
        category_required=False,
        core_fields=[
            FieldRequirement(
                field_name="product_name",
                importance=FieldImportance.CRITICAL,
                min_length=1,
                max_length=255,
                description="Product title",
                remediation="Add a product title"
            ),
            FieldRequirement(
                field_name="short_description",
                importance=FieldImportance.RECOMMENDED,
                description="Product description (HTML allowed)",
                remediation="Add product description for better SEO"
            ),
            FieldRequirement(
                field_name="sku",
                importance=FieldImportance.REQUIRED,
                description="Stock Keeping Unit",
                remediation="Add SKU for inventory tracking"
            ),
            FieldRequirement(
                field_name="price",
                importance=FieldImportance.CRITICAL,
                description="Product price",
                remediation="Set product price"
            ),
        ],
        attribute_fields=[
            FieldRequirement(
                field_name="vendor",
                importance=FieldImportance.RECOMMENDED,
                description="Product vendor/brand",
                remediation="Add vendor/brand name"
            ),
            FieldRequirement(
                field_name="product_type",
                importance=FieldImportance.RECOMMENDED,
                description="Product type for categorization",
                remediation="Add product type for organization"
            ),
        ],
        media_requirements={
            "min_images": 1,
            "recommended_images": 4,
            "main_image_required": True,
            "max_file_size": 20 * 1024 * 1024,  # 20MB
            "allowed_formats": ["jpg", "jpeg", "png", "gif", "webp"],
        }
    ),

    "woocommerce": ChannelRequirements(
        channel_code="woocommerce",
        channel_name="WooCommerce",
        description="WooCommerce store product requirements",
        gtin_required=False,
        category_required=True,
        core_fields=[
            FieldRequirement(
                field_name="product_name",
                importance=FieldImportance.CRITICAL,
                description="Product title",
                remediation="Add a product title"
            ),
            FieldRequirement(
                field_name="short_description",
                importance=FieldImportance.REQUIRED,
                max_length=400,
                description="Short product description",
                remediation="Add a brief product description"
            ),
            FieldRequirement(
                field_name="long_description",
                importance=FieldImportance.RECOMMENDED,
                description="Full product description",
                remediation="Add detailed product description"
            ),
            FieldRequirement(
                field_name="sku",
                importance=FieldImportance.REQUIRED,
                description="Stock Keeping Unit",
                remediation="Add SKU for inventory management"
            ),
            FieldRequirement(
                field_name="price",
                importance=FieldImportance.CRITICAL,
                description="Regular price",
                remediation="Set product regular price"
            ),
        ],
        attribute_fields=[
            FieldRequirement(
                field_name="weight",
                importance=FieldImportance.RECOMMENDED,
                description="Product weight",
                remediation="Add weight for shipping"
            ),
            FieldRequirement(
                field_name="stock_quantity",
                importance=FieldImportance.RECOMMENDED,
                description="Stock quantity",
                remediation="Set inventory stock level"
            ),
        ],
        media_requirements={
            "min_images": 1,
            "main_image_required": True,
            "allowed_formats": ["jpg", "jpeg", "png", "gif"],
        }
    ),

    "google_merchant": ChannelRequirements(
        channel_code="google_merchant",
        channel_name="Google Merchant Center",
        description="Google Shopping feed requirements",
        gtin_required=True,
        category_required=True,
        core_fields=[
            FieldRequirement(
                field_name="product_name",
                importance=FieldImportance.CRITICAL,
                min_length=1,
                max_length=150,
                description="Product title (max 150 chars for display)",
                remediation="Add product title under 150 characters"
            ),
            FieldRequirement(
                field_name="short_description",
                importance=FieldImportance.CRITICAL,
                min_length=1,
                max_length=5000,
                description="Product description",
                remediation="Add product description"
            ),
            FieldRequirement(
                field_name="gtin",
                importance=FieldImportance.CRITICAL,
                pattern=r"^\d{8,14}$",
                description="Global Trade Item Number",
                remediation="Add valid GTIN (UPC, EAN, ISBN)"
            ),
            FieldRequirement(
                field_name="brand",
                importance=FieldImportance.CRITICAL,
                description="Product brand",
                remediation="Add brand name (required for most categories)"
            ),
            FieldRequirement(
                field_name="mpn",
                importance=FieldImportance.REQUIRED,
                description="Manufacturer Part Number",
                remediation="Add MPN if no GTIN available"
            ),
            FieldRequirement(
                field_name="price",
                importance=FieldImportance.CRITICAL,
                description="Product price",
                remediation="Set product price"
            ),
            FieldRequirement(
                field_name="availability",
                importance=FieldImportance.CRITICAL,
                allowed_values=["in_stock", "out_of_stock", "preorder", "backorder"],
                description="Stock availability status",
                remediation="Set product availability status"
            ),
            FieldRequirement(
                field_name="condition",
                importance=FieldImportance.REQUIRED,
                allowed_values=["new", "refurbished", "used"],
                description="Product condition",
                remediation="Specify product condition"
            ),
        ],
        attribute_fields=[
            FieldRequirement(
                field_name="google_product_category",
                importance=FieldImportance.REQUIRED,
                description="Google product taxonomy category ID",
                remediation="Map to Google product category"
            ),
            FieldRequirement(
                field_name="age_group",
                importance=FieldImportance.RECOMMENDED,
                allowed_values=["newborn", "infant", "toddler", "kids", "adult"],
                description="Target age group (required for apparel)",
                remediation="Set target age group"
            ),
            FieldRequirement(
                field_name="gender",
                importance=FieldImportance.RECOMMENDED,
                allowed_values=["male", "female", "unisex"],
                description="Target gender (required for apparel)",
                remediation="Set target gender"
            ),
        ],
        media_requirements={
            "min_images": 1,
            "main_image_required": True,
            "min_resolution": 100,
            "recommended_resolution": 800,
            "allowed_formats": ["jpg", "jpeg", "png", "gif", "bmp", "tiff"],
            "no_promotional_text": True,
        }
    ),

    "trendyol": ChannelRequirements(
        channel_code="trendyol",
        channel_name="Trendyol",
        description="Trendyol marketplace requirements (Turkey)",
        gtin_required=True,
        category_required=True,
        core_fields=[
            FieldRequirement(
                field_name="product_name",
                importance=FieldImportance.CRITICAL,
                min_length=3,
                max_length=100,
                description="Product title in Turkish",
                remediation="Add Turkish product title (3-100 characters)"
            ),
            FieldRequirement(
                field_name="short_description",
                importance=FieldImportance.REQUIRED,
                description="Product description",
                remediation="Add product description"
            ),
            FieldRequirement(
                field_name="barcode",
                importance=FieldImportance.CRITICAL,
                pattern=r"^\d{8,14}$",
                description="Product barcode (GTIN)",
                remediation="Add valid barcode/GTIN"
            ),
            FieldRequirement(
                field_name="brand_id",
                importance=FieldImportance.CRITICAL,
                description="Trendyol brand ID",
                remediation="Map product to Trendyol brand"
            ),
            FieldRequirement(
                field_name="category_id",
                importance=FieldImportance.CRITICAL,
                description="Trendyol category ID",
                remediation="Map product to Trendyol category"
            ),
            FieldRequirement(
                field_name="price",
                importance=FieldImportance.CRITICAL,
                description="Sale price in TRY",
                remediation="Set product price"
            ),
            FieldRequirement(
                field_name="stock_quantity",
                importance=FieldImportance.CRITICAL,
                description="Available stock quantity",
                remediation="Set stock quantity"
            ),
        ],
        attribute_fields=[
            FieldRequirement(
                field_name="desi",
                importance=FieldImportance.REQUIRED,
                description="Volumetric weight (desi) for shipping",
                remediation="Calculate and add desi value"
            ),
            FieldRequirement(
                field_name="vat_rate",
                importance=FieldImportance.REQUIRED,
                allowed_values=["0", "1", "8", "18", "20"],
                description="VAT rate percentage",
                remediation="Set applicable VAT rate"
            ),
        ],
        media_requirements={
            "min_images": 2,
            "max_images": 8,
            "main_image_required": True,
            "min_resolution": 800,
            "allowed_formats": ["jpg", "jpeg", "png"],
            "white_background_required": True,
        }
    ),

    "hepsiburada": ChannelRequirements(
        channel_code="hepsiburada",
        channel_name="Hepsiburada",
        description="Hepsiburada marketplace requirements (Turkey)",
        gtin_required=True,
        category_required=True,
        core_fields=[
            FieldRequirement(
                field_name="product_name",
                importance=FieldImportance.CRITICAL,
                description="Product title",
                remediation="Add product title"
            ),
            FieldRequirement(
                field_name="barcode",
                importance=FieldImportance.CRITICAL,
                pattern=r"^\d{8,14}$",
                description="Product barcode",
                remediation="Add valid barcode"
            ),
            FieldRequirement(
                field_name="price",
                importance=FieldImportance.CRITICAL,
                description="Product price in TRY",
                remediation="Set product price"
            ),
            FieldRequirement(
                field_name="stock_quantity",
                importance=FieldImportance.CRITICAL,
                description="Stock quantity",
                remediation="Set stock level"
            ),
            FieldRequirement(
                field_name="category_id",
                importance=FieldImportance.CRITICAL,
                description="Hepsiburada category ID",
                remediation="Map to Hepsiburada category"
            ),
        ],
        attribute_fields=[
            FieldRequirement(
                field_name="shipping_profile",
                importance=FieldImportance.REQUIRED,
                description="Shipping/cargo profile",
                remediation="Select shipping profile"
            ),
        ],
        media_requirements={
            "min_images": 1,
            "main_image_required": True,
            "min_resolution": 500,
            "allowed_formats": ["jpg", "jpeg", "png"],
        }
    ),

    "n11": ChannelRequirements(
        channel_code="n11",
        channel_name="N11",
        description="N11 marketplace requirements (Turkey)",
        gtin_required=False,
        category_required=True,
        core_fields=[
            FieldRequirement(
                field_name="product_name",
                importance=FieldImportance.CRITICAL,
                max_length=100,
                description="Product title",
                remediation="Add product title (max 100 chars)"
            ),
            FieldRequirement(
                field_name="short_description",
                importance=FieldImportance.REQUIRED,
                description="Product description",
                remediation="Add product description"
            ),
            FieldRequirement(
                field_name="sku",
                importance=FieldImportance.CRITICAL,
                description="Product seller code",
                remediation="Add unique product code"
            ),
            FieldRequirement(
                field_name="price",
                importance=FieldImportance.CRITICAL,
                description="Display price in TRY",
                remediation="Set product price"
            ),
            FieldRequirement(
                field_name="stock_quantity",
                importance=FieldImportance.CRITICAL,
                description="Stock quantity",
                remediation="Set stock quantity"
            ),
            FieldRequirement(
                field_name="category_id",
                importance=FieldImportance.CRITICAL,
                description="N11 category ID",
                remediation="Map to N11 category"
            ),
        ],
        attribute_fields=[
            FieldRequirement(
                field_name="shipping_template",
                importance=FieldImportance.REQUIRED,
                description="Cargo/shipping template",
                remediation="Select shipping template"
            ),
        ],
        media_requirements={
            "min_images": 1,
            "max_images": 6,
            "main_image_required": True,
            "allowed_formats": ["jpg", "jpeg", "png"],
        }
    ),

    "ebay": ChannelRequirements(
        channel_code="ebay",
        channel_name="eBay",
        description="eBay marketplace requirements",
        gtin_required=True,
        category_required=True,
        core_fields=[
            FieldRequirement(
                field_name="product_name",
                importance=FieldImportance.CRITICAL,
                min_length=1,
                max_length=80,
                description="Item title (80 char limit)",
                remediation="Add title under 80 characters"
            ),
            FieldRequirement(
                field_name="short_description",
                importance=FieldImportance.REQUIRED,
                description="Item description (HTML allowed)",
                remediation="Add item description"
            ),
            FieldRequirement(
                field_name="sku",
                importance=FieldImportance.REQUIRED,
                description="Seller SKU",
                remediation="Add seller SKU"
            ),
            FieldRequirement(
                field_name="price",
                importance=FieldImportance.CRITICAL,
                description="Start price or Buy It Now price",
                remediation="Set item price"
            ),
            FieldRequirement(
                field_name="condition",
                importance=FieldImportance.CRITICAL,
                description="Item condition ID",
                remediation="Set item condition"
            ),
            FieldRequirement(
                field_name="gtin",
                importance=FieldImportance.REQUIRED,
                description="UPC, EAN, or ISBN",
                remediation="Add product identifier"
            ),
        ],
        attribute_fields=[
            FieldRequirement(
                field_name="brand",
                importance=FieldImportance.REQUIRED,
                description="Brand name",
                remediation="Add brand name"
            ),
            FieldRequirement(
                field_name="mpn",
                importance=FieldImportance.RECOMMENDED,
                description="Manufacturer Part Number",
                remediation="Add MPN if available"
            ),
        ],
        media_requirements={
            "min_images": 1,
            "max_images": 24,
            "main_image_required": True,
            "min_resolution": 500,
            "max_file_size": 12 * 1024 * 1024,  # 12MB
            "allowed_formats": ["jpg", "jpeg", "png", "gif"],
        }
    ),

    "etsy": ChannelRequirements(
        channel_code="etsy",
        channel_name="Etsy",
        description="Etsy marketplace requirements",
        gtin_required=False,
        category_required=True,
        core_fields=[
            FieldRequirement(
                field_name="product_name",
                importance=FieldImportance.CRITICAL,
                min_length=1,
                max_length=140,
                description="Listing title",
                remediation="Add title (max 140 characters)"
            ),
            FieldRequirement(
                field_name="long_description",
                importance=FieldImportance.REQUIRED,
                description="Listing description",
                remediation="Add detailed description"
            ),
            FieldRequirement(
                field_name="price",
                importance=FieldImportance.CRITICAL,
                description="Listing price",
                remediation="Set listing price"
            ),
            FieldRequirement(
                field_name="who_made",
                importance=FieldImportance.CRITICAL,
                allowed_values=["i_did", "someone_else", "collective"],
                description="Who made this item",
                remediation="Specify who made the item"
            ),
            FieldRequirement(
                field_name="when_made",
                importance=FieldImportance.CRITICAL,
                description="When the item was made",
                remediation="Specify when item was made"
            ),
            FieldRequirement(
                field_name="is_supply",
                importance=FieldImportance.CRITICAL,
                description="Is this a supply or finished product",
                remediation="Specify if supply or finished product"
            ),
        ],
        attribute_fields=[
            FieldRequirement(
                field_name="tags",
                importance=FieldImportance.REQUIRED,
                description="Search tags (up to 13)",
                remediation="Add search tags for discoverability"
            ),
            FieldRequirement(
                field_name="materials",
                importance=FieldImportance.RECOMMENDED,
                description="Materials used",
                remediation="List materials used"
            ),
        ],
        media_requirements={
            "min_images": 1,
            "max_images": 10,
            "main_image_required": True,
            "min_resolution": 2000,  # For zoom functionality
            "allowed_formats": ["jpg", "jpeg", "png", "gif"],
        }
    ),

    "walmart": ChannelRequirements(
        channel_code="walmart",
        channel_name="Walmart Marketplace",
        description="Walmart Marketplace listing requirements",
        gtin_required=True,
        category_required=True,
        core_fields=[
            FieldRequirement(
                field_name="product_name",
                importance=FieldImportance.CRITICAL,
                min_length=1,
                max_length=200,
                description="Product name",
                remediation="Add product name (max 200 chars)"
            ),
            FieldRequirement(
                field_name="short_description",
                importance=FieldImportance.REQUIRED,
                max_length=4000,
                description="Short description",
                remediation="Add short description"
            ),
            FieldRequirement(
                field_name="long_description",
                importance=FieldImportance.RECOMMENDED,
                description="Full description",
                remediation="Add detailed description"
            ),
            FieldRequirement(
                field_name="sku",
                importance=FieldImportance.CRITICAL,
                description="Seller SKU",
                remediation="Add unique SKU"
            ),
            FieldRequirement(
                field_name="gtin",
                importance=FieldImportance.CRITICAL,
                pattern=r"^\d{8,14}$",
                description="UPC or GTIN",
                remediation="Add valid UPC/GTIN"
            ),
            FieldRequirement(
                field_name="brand",
                importance=FieldImportance.CRITICAL,
                description="Brand name",
                remediation="Add brand name"
            ),
            FieldRequirement(
                field_name="price",
                importance=FieldImportance.CRITICAL,
                description="Price",
                remediation="Set product price"
            ),
        ],
        attribute_fields=[
            FieldRequirement(
                field_name="product_type",
                importance=FieldImportance.REQUIRED,
                description="Walmart product type",
                remediation="Select Walmart product type"
            ),
            FieldRequirement(
                field_name="shipping_weight",
                importance=FieldImportance.REQUIRED,
                description="Shipping weight",
                remediation="Add shipping weight"
            ),
        ],
        media_requirements={
            "min_images": 2,
            "recommended_images": 4,
            "main_image_required": True,
            "min_resolution": 1000,
            "allowed_formats": ["jpg", "jpeg", "png"],
            "white_background_required": True,
        }
    ),

    "meta_commerce": ChannelRequirements(
        channel_code="meta_commerce",
        channel_name="Meta Commerce (Facebook/Instagram)",
        description="Meta Commerce catalog requirements",
        gtin_required=False,
        category_required=True,
        core_fields=[
            FieldRequirement(
                field_name="product_name",
                importance=FieldImportance.CRITICAL,
                max_length=150,
                description="Product title",
                remediation="Add product title (max 150 chars)"
            ),
            FieldRequirement(
                field_name="short_description",
                importance=FieldImportance.REQUIRED,
                max_length=5000,
                description="Product description",
                remediation="Add product description"
            ),
            FieldRequirement(
                field_name="price",
                importance=FieldImportance.CRITICAL,
                description="Product price",
                remediation="Set product price"
            ),
            FieldRequirement(
                field_name="availability",
                importance=FieldImportance.CRITICAL,
                allowed_values=["in stock", "out of stock", "preorder", "available for order", "discontinued"],
                description="Availability status",
                remediation="Set availability status"
            ),
            FieldRequirement(
                field_name="condition",
                importance=FieldImportance.REQUIRED,
                allowed_values=["new", "refurbished", "used"],
                description="Product condition",
                remediation="Set product condition"
            ),
            FieldRequirement(
                field_name="url",
                importance=FieldImportance.CRITICAL,
                description="Product page URL",
                remediation="Add product page link"
            ),
        ],
        attribute_fields=[
            FieldRequirement(
                field_name="brand",
                importance=FieldImportance.RECOMMENDED,
                description="Brand name",
                remediation="Add brand name"
            ),
            FieldRequirement(
                field_name="google_product_category",
                importance=FieldImportance.RECOMMENDED,
                description="Google product category ID",
                remediation="Map to Google product category"
            ),
        ],
        media_requirements={
            "min_images": 1,
            "main_image_required": True,
            "min_resolution": 500,
            "allowed_formats": ["jpg", "jpeg", "png", "gif"],
            "max_file_size": 8 * 1024 * 1024,  # 8MB
        }
    ),

    "tiktok_shop": ChannelRequirements(
        channel_code="tiktok_shop",
        channel_name="TikTok Shop",
        description="TikTok Shop listing requirements",
        gtin_required=False,
        category_required=True,
        core_fields=[
            FieldRequirement(
                field_name="product_name",
                importance=FieldImportance.CRITICAL,
                min_length=1,
                max_length=255,
                description="Product name",
                remediation="Add product name"
            ),
            FieldRequirement(
                field_name="short_description",
                importance=FieldImportance.REQUIRED,
                description="Product description",
                remediation="Add product description"
            ),
            FieldRequirement(
                field_name="price",
                importance=FieldImportance.CRITICAL,
                description="Sale price",
                remediation="Set product price"
            ),
            FieldRequirement(
                field_name="stock_quantity",
                importance=FieldImportance.CRITICAL,
                description="Available quantity",
                remediation="Set stock quantity"
            ),
            FieldRequirement(
                field_name="category_id",
                importance=FieldImportance.CRITICAL,
                description="TikTok Shop category",
                remediation="Select product category"
            ),
        ],
        attribute_fields=[
            FieldRequirement(
                field_name="brand",
                importance=FieldImportance.RECOMMENDED,
                description="Brand name",
                remediation="Add brand name"
            ),
            FieldRequirement(
                field_name="package_weight",
                importance=FieldImportance.REQUIRED,
                description="Package weight for shipping",
                remediation="Add package weight"
            ),
        ],
        media_requirements={
            "min_images": 1,
            "max_images": 9,
            "main_image_required": True,
            "min_resolution": 600,
            "allowed_formats": ["jpg", "jpeg", "png"],
            "video_allowed": True,
        }
    ),

    # Default/generic channel for custom channels
    "default": ChannelRequirements(
        channel_code="default",
        channel_name="Default",
        description="Generic channel requirements",
        gtin_required=False,
        category_required=False,
        core_fields=[
            FieldRequirement(
                field_name="product_name",
                importance=FieldImportance.CRITICAL,
                description="Product name/title",
                remediation="Add product name"
            ),
            FieldRequirement(
                field_name="short_description",
                importance=FieldImportance.RECOMMENDED,
                description="Product description",
                remediation="Add product description"
            ),
            FieldRequirement(
                field_name="price",
                importance=FieldImportance.REQUIRED,
                description="Product price",
                remediation="Set product price"
            ),
        ],
        attribute_fields=[],
        media_requirements={
            "min_images": 1,
            "main_image_required": True,
        }
    ),
}


@dataclass
class GapItem:
    """Represents a single gap/missing item in product data"""
    field_name: str
    importance: FieldImportance
    current_value: Any = None
    requirement: str = ""
    remediation: str = ""
    score_impact: float = 0.0  # How much this gap affects the score

    def to_dict(self) -> Dict:
        return {
            "field_name": self.field_name,
            "importance": self.importance.value,
            "current_value": str(self.current_value) if self.current_value else None,
            "requirement": self.requirement,
            "remediation": self.remediation,
            "score_impact": self.score_impact,
        }


@dataclass
class GapAnalysisResult:
    """Complete gap analysis result for a product-channel pair"""
    product_name: str
    channel_code: str
    channel_name: str
    score: float
    is_channel_ready: bool
    critical_gaps: List[GapItem] = field(default_factory=list)
    required_gaps: List[GapItem] = field(default_factory=list)
    recommended_gaps: List[GapItem] = field(default_factory=list)
    media_gaps: List[Dict] = field(default_factory=list)
    total_gaps: int = 0
    analyzed_at: str = ""

    def to_dict(self) -> Dict:
        return {
            "product_name": self.product_name,
            "channel_code": self.channel_code,
            "channel_name": self.channel_name,
            "score": self.score,
            "is_channel_ready": self.is_channel_ready,
            "critical_gaps": [g.to_dict() for g in self.critical_gaps],
            "required_gaps": [g.to_dict() for g in self.required_gaps],
            "recommended_gaps": [g.to_dict() for g in self.recommended_gaps],
            "media_gaps": self.media_gaps,
            "total_gaps": self.total_gaps,
            "analyzed_at": self.analyzed_at,
        }


# =============================================================================
# Channel Requirements Registry Functions
# =============================================================================

def get_channel_requirements(channel_code: str) -> ChannelRequirements:
    """Get requirements for a specific channel.

    Args:
        channel_code: The channel code (e.g., 'amazon', 'shopify')

    Returns:
        ChannelRequirements object for the channel
    """
    code = channel_code.lower() if channel_code else "default"
    return CHANNEL_REQUIREMENTS.get(code, CHANNEL_REQUIREMENTS["default"])


def list_supported_channels() -> List[str]:
    """Get list of channels with defined requirements.

    Returns:
        List of channel codes
    """
    return [code for code in CHANNEL_REQUIREMENTS.keys() if code != "default"]


def register_channel_requirements(channel_code: str, requirements: ChannelRequirements) -> None:
    """Register custom channel requirements.

    Args:
        channel_code: Unique channel identifier
        requirements: ChannelRequirements object
    """
    CHANNEL_REQUIREMENTS[channel_code.lower()] = requirements


def calculate_score(doc, method=None):
    """Calculate completeness score for a Product Master.

    Computes the data quality score as a percentage of filled required
    fields. The score considers both core product fields and dynamic
    attributes from the product's family template.

    Args:
        doc: The Product Master document being saved
        method: The hook method name (unused, for Frappe hook signature)

    Returns:
        float: Completeness score from 0.0 to 100.0

    Example:
        A product with 3/5 required fields filled would score 60.0
    """
    import frappe

    try:
        # Core required fields for all products
        core_required_fields = ["product_name", "product_code", "short_description"]

        # Count filled core fields
        core_filled = sum(1 for field in core_required_fields if _has_field_value(doc, field))
        total_required = len(core_required_fields)
        total_filled = core_filled

        # Get required attributes from family template if product has a family
        if doc.get("product_family"):
            required_attrs = _get_required_attributes(doc.product_family)

            if required_attrs:
                total_required += len(required_attrs)

                # Count filled attribute values
                attribute_values = doc.get("attribute_values") or []
                for attr_code in required_attrs:
                    if _is_attribute_filled(attribute_values, attr_code):
                        total_filled += 1

        # Calculate score
        if total_required == 0:
            score = 100.0
        else:
            score = round((total_filled / total_required) * 100, 2)

        # Update the document's completeness_score field if it exists
        if hasattr(doc, "completeness_score"):
            doc.completeness_score = score

        return score

    except Exception as e:
        frappe.log_error(
            message=f"Error calculating completeness for {doc.name}: {str(e)}",
            title="PIM Completeness Score Error"
        )
        return 0.0


def calculate_variant_score(doc, method=None):
    """Calculate completeness score for a Product Variant.

    Computes the data quality score for product variants. Variants have
    their own set of required fields and may inherit requirements from
    their parent product's family.

    Args:
        doc: The Product Variant document being saved
        method: The hook method name (unused, for Frappe hook signature)

    Returns:
        float: Completeness score from 0.0 to 100.0
    """
    import frappe

    try:
        # Core required fields for variants
        core_required_fields = ["sku", "variant_name"]

        # Count filled core fields
        core_filled = sum(1 for field in core_required_fields if _has_field_value(doc, field))
        total_required = len(core_required_fields)
        total_filled = core_filled

        # Get parent product's family for attribute requirements
        family = None
        if doc.get("parent_product"):
            family = frappe.db.get_value(
                "Product Master",
                doc.parent_product,
                "product_family"
            )
        elif doc.get("product_family"):
            family = doc.product_family

        # Get required variant-level attributes from family
        if family:
            required_attrs = _get_required_variant_attributes(family)

            if required_attrs:
                total_required += len(required_attrs)

                # Count filled attribute values
                attribute_values = doc.get("attribute_values") or []
                for attr_code in required_attrs:
                    if _is_attribute_filled(attribute_values, attr_code):
                        total_filled += 1

        # Calculate score
        if total_required == 0:
            score = 100.0
        else:
            score = round((total_filled / total_required) * 100, 2)

        # Update the document's completeness_score field if it exists
        if hasattr(doc, "completeness_score"):
            doc.completeness_score = score

        return score

    except Exception as e:
        frappe.log_error(
            message=f"Error calculating variant completeness for {doc.name}: {str(e)}",
            title="PIM Completeness Score Error"
        )
        return 0.0


def _has_field_value(doc, field_name):
    """Check if a document field has a non-empty value.

    Args:
        doc: Document to check
        field_name: Name of the field to check

    Returns:
        bool: True if field has a value, False otherwise
    """
    value = doc.get(field_name)
    if value is None:
        return False
    if isinstance(value, str):
        return len(value.strip()) > 0
    return True


def _get_required_attributes(family):
    """Get list of required attribute codes for a product family.

    Queries the Family Attribute Template child table to find all
    attributes marked as required for the given family.

    Args:
        family: Name of the Product Family

    Returns:
        list: List of attribute codes that are required
    """
    import frappe

    try:
        required = frappe.get_all(
            "Family Attribute Template",
            filters={
                "parent": family,
                "is_required_in_family": 1
            },
            pluck="attribute"
        )
        return required or []
    except Exception:
        # Family Attribute Template may not exist yet
        return []


def _get_required_variant_attributes(family):
    """Get list of required variant-level attributes for a family.

    Some attributes are specifically required at the variant level
    (e.g., size, color) rather than the master product level.

    Args:
        family: Name of the Product Family

    Returns:
        list: List of attribute codes required for variants
    """
    import frappe

    try:
        # Get attributes that are required and variant-level
        required = frappe.get_all(
            "Family Attribute Template",
            filters={
                "parent": family,
                "is_required": 1,
                "is_variant_attribute": 1
            },
            pluck="attribute"
        )
        return required or []
    except Exception:
        # Fall back to regular required attributes if variant flag doesn't exist
        return _get_required_attributes(family)


def _is_attribute_filled(attribute_values, attr_code):
    """Check if an attribute has a value in the EAV table.

    Searches through the Product Attribute Value child table rows
    to find if the specified attribute has any value set.

    Args:
        attribute_values: List of Product Attribute Value rows
        attr_code: Attribute code to check

    Returns:
        bool: True if attribute has a value, False otherwise
    """
    for row in attribute_values:
        if row.get("attribute") == attr_code:
            return _has_eav_value(row)
    return False


def _has_eav_value(row):
    """Check if an EAV row has any value set.

    Checks all value columns in the Product Attribute Value row
    to determine if any value is present.

    Args:
        row: Product Attribute Value row (dict-like)

    Returns:
        bool: True if any value column has a value, False otherwise
    """
    # Check all possible value columns in EAV structure
    value_fields = [
        "value_text",
        "value_int",
        "value_float",
        "value_boolean",
        "value_date",
        "value_datetime",
        "value_link",
        "value_data",
    ]

    for field in value_fields:
        value = row.get(field)
        if value is not None:
            # Handle different value types
            if isinstance(value, str):
                if len(value.strip()) > 0:
                    return True
            elif isinstance(value, bool):
                # Boolean fields are always considered "filled" if present
                return True
            elif isinstance(value, (int, float)):
                return True
            else:
                return True

    return False


def get_completeness_summary(product_name):
    """Get detailed completeness breakdown for a product.

    Returns a detailed report of which required fields are filled
    and which are missing.

    Args:
        product_name: Name of the Product Master

    Returns:
        dict: Summary with filled, missing, and score information
    """
    import frappe

    try:
        doc = frappe.get_doc("Product Master", product_name)

        # Core fields analysis
        core_fields = ["product_name", "product_code", "short_description"]
        core_analysis = {
            field: _has_field_value(doc, field) for field in core_fields
        }

        # Attribute analysis
        attribute_analysis = {}
        if doc.get("product_family"):
            required_attrs = _get_required_attributes(doc.product_family)
            attribute_values = doc.get("attribute_values") or []

            for attr_code in required_attrs:
                attribute_analysis[attr_code] = _is_attribute_filled(
                    attribute_values, attr_code
                )

        # Calculate totals
        core_filled = sum(1 for v in core_analysis.values() if v)
        attr_filled = sum(1 for v in attribute_analysis.values() if v)
        total_filled = core_filled + attr_filled
        total_required = len(core_analysis) + len(attribute_analysis)

        score = round((total_filled / total_required) * 100, 2) if total_required > 0 else 100.0

        return {
            "product_name": product_name,
            "score": score,
            "total_required": total_required,
            "total_filled": total_filled,
            "core_fields": core_analysis,
            "attributes": attribute_analysis,
            "missing_core": [k for k, v in core_analysis.items() if not v],
            "missing_attributes": [k for k, v in attribute_analysis.items() if not v],
        }

    except Exception as e:
        frappe.log_error(
            message=f"Error getting completeness summary for {product_name}: {str(e)}",
            title="PIM Completeness Error"
        )
        return {
            "product_name": product_name,
            "score": 0.0,
            "error": str(e)
        }


# =============================================================================
# Channel-Specific Scoring Functions
# =============================================================================

def calculate_channel_specific_score(product_name: str, channel_code: str) -> Dict:
    """Calculate channel-specific completeness score for a product.

    Evaluates a product against a specific channel's requirements and calculates
    a weighted score based on field importance levels.

    Scoring weights:
        - Critical fields: 40% of total (must all be filled for channel readiness)
        - Required fields: 40% of total
        - Recommended fields: 20% of total

    Args:
        product_name: Name of the Product Master
        channel_code: Channel code (e.g., 'amazon', 'shopify')

    Returns:
        dict: Score details including:
            - score: Overall channel completeness (0-100)
            - is_channel_ready: True if all critical fields are filled
            - critical_score: Score for critical fields only
            - required_score: Score for required fields
            - recommended_score: Score for recommended fields
            - filled_fields: List of filled field names
            - missing_fields: List of missing field names
            - channel: Channel information
    """
    import frappe
    from datetime import datetime

    try:
        doc = frappe.get_doc("Product Master", product_name)
        requirements = get_channel_requirements(channel_code)

        # Initialize counters
        critical_total = 0
        critical_filled = 0
        required_total = 0
        required_filled = 0
        recommended_total = 0
        recommended_filled = 0

        filled_fields = []
        missing_fields = []

        # Check all requirements
        all_requirements = requirements.core_fields + requirements.attribute_fields

        for req in all_requirements:
            value = _get_product_field_value(doc, req.field_name)
            is_filled = _check_field_value(value, req)

            if req.importance == FieldImportance.CRITICAL:
                critical_total += 1
                if is_filled:
                    critical_filled += 1
                    filled_fields.append(req.field_name)
                else:
                    missing_fields.append(req.field_name)

            elif req.importance == FieldImportance.REQUIRED:
                required_total += 1
                if is_filled:
                    required_filled += 1
                    filled_fields.append(req.field_name)
                else:
                    missing_fields.append(req.field_name)

            elif req.importance == FieldImportance.RECOMMENDED:
                recommended_total += 1
                if is_filled:
                    recommended_filled += 1
                    filled_fields.append(req.field_name)
                else:
                    missing_fields.append(req.field_name)

        # Calculate sub-scores
        critical_score = (critical_filled / critical_total * 100) if critical_total > 0 else 100.0
        required_score = (required_filled / required_total * 100) if required_total > 0 else 100.0
        recommended_score = (recommended_filled / recommended_total * 100) if recommended_total > 0 else 100.0

        # Determine channel readiness (all critical fields must be filled)
        is_channel_ready = critical_filled == critical_total

        # Calculate weighted overall score
        # Critical: 40%, Required: 40%, Recommended: 20%
        weighted_score = (
            (critical_score * 0.4) +
            (required_score * 0.4) +
            (recommended_score * 0.2)
        )

        # If not channel ready, cap the score at 60
        if not is_channel_ready:
            weighted_score = min(weighted_score, 60.0)

        return {
            "product_name": product_name,
            "channel_code": requirements.channel_code,
            "channel_name": requirements.channel_name,
            "score": round(weighted_score, 2),
            "is_channel_ready": is_channel_ready,
            "critical_score": round(critical_score, 2),
            "required_score": round(required_score, 2),
            "recommended_score": round(recommended_score, 2),
            "critical_count": f"{critical_filled}/{critical_total}",
            "required_count": f"{required_filled}/{required_total}",
            "recommended_count": f"{recommended_filled}/{recommended_total}",
            "filled_fields": filled_fields,
            "missing_fields": missing_fields,
            "calculated_at": datetime.now().isoformat(),
        }

    except Exception as e:
        frappe.log_error(
            message=f"Error calculating channel score for {product_name} ({channel_code}): {str(e)}",
            title="PIM Channel Score Error"
        )
        return {
            "product_name": product_name,
            "channel_code": channel_code,
            "score": 0.0,
            "is_channel_ready": False,
            "error": str(e)
        }


def calculate_multi_channel_scores(product_name: str, channel_codes: List[str] = None) -> Dict:
    """Calculate completeness scores for a product across multiple channels.

    Args:
        product_name: Name of the Product Master
        channel_codes: List of channel codes to evaluate. If None, evaluates all supported channels.

    Returns:
        dict: Channel readiness summary with scores per channel
    """
    import frappe
    from datetime import datetime

    if channel_codes is None:
        channel_codes = list_supported_channels()

    results = {
        "product_name": product_name,
        "channels": {},
        "ready_channels": [],
        "not_ready_channels": [],
        "calculated_at": datetime.now().isoformat(),
    }

    for channel_code in channel_codes:
        try:
            score_result = calculate_channel_specific_score(product_name, channel_code)
            results["channels"][channel_code] = score_result

            if score_result.get("is_channel_ready"):
                results["ready_channels"].append(channel_code)
            else:
                results["not_ready_channels"].append(channel_code)

        except Exception as e:
            results["channels"][channel_code] = {
                "error": str(e),
                "is_channel_ready": False
            }
            results["not_ready_channels"].append(channel_code)

    # Calculate overall readiness percentage
    total = len(channel_codes)
    ready = len(results["ready_channels"])
    results["readiness_percentage"] = round((ready / total * 100) if total > 0 else 0, 2)
    results["total_channels"] = total
    results["ready_count"] = ready

    return results


# =============================================================================
# Gap Analysis Functions
# =============================================================================

def gap_analysis(product_name: str, channel_code: str) -> GapAnalysisResult:
    """Perform detailed gap analysis for a product against channel requirements.

    Identifies all missing or incomplete fields with remediation recommendations.

    Args:
        product_name: Name of the Product Master
        channel_code: Channel code (e.g., 'amazon', 'shopify')

    Returns:
        GapAnalysisResult: Detailed gap analysis including:
            - Critical gaps (must fix before publishing)
            - Required gaps (should fix before publishing)
            - Recommended gaps (nice to have)
            - Media gaps (missing images, wrong format, etc.)
            - Score and readiness status
    """
    import frappe
    from datetime import datetime
    import re

    try:
        doc = frappe.get_doc("Product Master", product_name)
        requirements = get_channel_requirements(channel_code)

        critical_gaps = []
        required_gaps = []
        recommended_gaps = []
        media_gaps = []

        total_fields = 0
        filled_fields = 0

        # Analyze all field requirements
        all_requirements = requirements.core_fields + requirements.attribute_fields

        for req in all_requirements:
            total_fields += 1
            value = _get_product_field_value(doc, req.field_name)
            validation_result = _validate_field_against_requirement(value, req)

            if validation_result["is_valid"]:
                filled_fields += 1
                continue

            # Create gap item
            gap = GapItem(
                field_name=req.field_name,
                importance=req.importance,
                current_value=value,
                requirement=validation_result.get("requirement", req.description),
                remediation=req.remediation or validation_result.get("remediation", ""),
                score_impact=_calculate_field_score_impact(req.importance, total_fields)
            )

            # Categorize by importance
            if req.importance == FieldImportance.CRITICAL:
                critical_gaps.append(gap)
            elif req.importance == FieldImportance.REQUIRED:
                required_gaps.append(gap)
            else:
                recommended_gaps.append(gap)

        # Analyze media requirements
        media_gaps = _analyze_media_gaps(doc, requirements.media_requirements)

        # Calculate score
        score = (filled_fields / total_fields * 100) if total_fields > 0 else 100.0

        # Product is channel ready only if no critical gaps
        is_channel_ready = len(critical_gaps) == 0

        return GapAnalysisResult(
            product_name=product_name,
            channel_code=requirements.channel_code,
            channel_name=requirements.channel_name,
            score=round(score, 2),
            is_channel_ready=is_channel_ready,
            critical_gaps=critical_gaps,
            required_gaps=required_gaps,
            recommended_gaps=recommended_gaps,
            media_gaps=media_gaps,
            total_gaps=len(critical_gaps) + len(required_gaps) + len(recommended_gaps),
            analyzed_at=datetime.now().isoformat()
        )

    except Exception as e:
        import frappe
        frappe.log_error(
            message=f"Error in gap analysis for {product_name} ({channel_code}): {str(e)}",
            title="PIM Gap Analysis Error"
        )
        return GapAnalysisResult(
            product_name=product_name,
            channel_code=channel_code,
            channel_name="Unknown",
            score=0.0,
            is_channel_ready=False,
            analyzed_at=datetime.now().isoformat()
        )


def gap_analysis_multi_channel(product_name: str, channel_codes: List[str] = None) -> Dict:
    """Perform gap analysis across multiple channels.

    Args:
        product_name: Name of the Product Master
        channel_codes: List of channels to analyze. If None, analyzes all supported channels.

    Returns:
        dict: Gap analysis results for each channel with summary
    """
    from datetime import datetime

    if channel_codes is None:
        channel_codes = list_supported_channels()

    results = {
        "product_name": product_name,
        "channels": {},
        "summary": {
            "total_channels": len(channel_codes),
            "ready_channels": 0,
            "not_ready_channels": 0,
            "common_gaps": [],
        },
        "analyzed_at": datetime.now().isoformat(),
    }

    # Track gaps across all channels to find common ones
    gap_frequency = {}

    for channel_code in channel_codes:
        analysis = gap_analysis(product_name, channel_code)
        results["channels"][channel_code] = analysis.to_dict()

        if analysis.is_channel_ready:
            results["summary"]["ready_channels"] += 1
        else:
            results["summary"]["not_ready_channels"] += 1

        # Track gap frequency
        all_gaps = analysis.critical_gaps + analysis.required_gaps + analysis.recommended_gaps
        for gap in all_gaps:
            if gap.field_name not in gap_frequency:
                gap_frequency[gap.field_name] = {
                    "count": 0,
                    "channels": [],
                    "importance": gap.importance.value,
                    "remediation": gap.remediation
                }
            gap_frequency[gap.field_name]["count"] += 1
            gap_frequency[gap.field_name]["channels"].append(channel_code)

    # Find common gaps (appearing in more than half the channels)
    threshold = len(channel_codes) / 2
    results["summary"]["common_gaps"] = [
        {
            "field_name": field,
            "channel_count": info["count"],
            "channels": info["channels"],
            "importance": info["importance"],
            "remediation": info["remediation"]
        }
        for field, info in gap_frequency.items()
        if info["count"] >= threshold
    ]

    # Sort by frequency
    results["summary"]["common_gaps"].sort(key=lambda x: x["channel_count"], reverse=True)

    return results


def get_remediation_plan(product_name: str, channel_code: str = None) -> Dict:
    """Generate a prioritized remediation plan for product gaps.

    Creates an actionable list of steps to make a product channel-ready,
    ordered by impact and importance.

    Args:
        product_name: Name of the Product Master
        channel_code: Specific channel to analyze. If None, analyzes for best overall coverage.

    Returns:
        dict: Prioritized remediation steps with estimated impact
    """
    from datetime import datetime

    if channel_code:
        analysis = gap_analysis(product_name, channel_code)
        channels_analyzed = [channel_code]
    else:
        # Analyze across all channels and find highest-impact gaps
        multi_analysis = gap_analysis_multi_channel(product_name)
        channels_analyzed = list(multi_analysis["channels"].keys())

    remediation_steps = []

    # Process critical gaps first
    if channel_code:
        all_gaps = analysis.critical_gaps + analysis.required_gaps + analysis.recommended_gaps
    else:
        # Aggregate gaps from all channels
        all_gaps = []
        seen_fields = set()
        for ch_code, ch_data in multi_analysis["channels"].items():
            for gap_list in ["critical_gaps", "required_gaps", "recommended_gaps"]:
                for gap in ch_data.get(gap_list, []):
                    field = gap["field_name"]
                    if field not in seen_fields:
                        seen_fields.add(field)
                        # Convert dict back to GapItem for processing
                        all_gaps.append(GapItem(
                            field_name=gap["field_name"],
                            importance=FieldImportance(gap["importance"]),
                            current_value=gap.get("current_value"),
                            requirement=gap.get("requirement", ""),
                            remediation=gap.get("remediation", ""),
                            score_impact=gap.get("score_impact", 0)
                        ))

    # Sort by importance and then by score impact
    priority_order = {
        FieldImportance.CRITICAL: 0,
        FieldImportance.REQUIRED: 1,
        FieldImportance.RECOMMENDED: 2,
        FieldImportance.OPTIONAL: 3,
    }
    all_gaps.sort(key=lambda x: (priority_order.get(x.importance, 99), -x.score_impact))

    for idx, gap in enumerate(all_gaps, 1):
        step = {
            "priority": idx,
            "field_name": gap.field_name,
            "importance": gap.importance.value,
            "current_value": gap.current_value,
            "action": gap.remediation or f"Fill in the {gap.field_name} field",
            "estimated_impact": f"+{gap.score_impact:.1f}% score improvement",
            "blocking": gap.importance == FieldImportance.CRITICAL,
        }
        remediation_steps.append(step)

    return {
        "product_name": product_name,
        "channels_analyzed": channels_analyzed,
        "total_steps": len(remediation_steps),
        "blocking_steps": sum(1 for s in remediation_steps if s["blocking"]),
        "steps": remediation_steps,
        "generated_at": datetime.now().isoformat(),
    }


# =============================================================================
# Helper Functions for Channel-Specific Scoring
# =============================================================================

def _get_product_field_value(doc, field_name: str) -> Any:
    """Get field value from product document, checking multiple sources.

    Checks direct fields, attribute values, and custom fields.

    Args:
        doc: Product Master document
        field_name: Field name to retrieve

    Returns:
        The field value or None if not found
    """
    # Direct field on document
    if hasattr(doc, field_name):
        return doc.get(field_name)

    # Check common field mappings
    field_mappings = {
        "gtin": ["barcode", "ean", "upc", "gtin13", "gtin14"],
        "sku": ["product_code", "item_code"],
        "price": ["standard_rate", "base_price", "selling_price"],
        "stock_quantity": ["stock_qty", "qty", "quantity", "available_qty"],
        "brand": ["brand_name"],
        "weight": ["net_weight", "gross_weight"],
        "dimensions": ["item_dimensions"],
        "long_description": ["description", "web_long_description"],
        "short_description": ["description", "web_short_description"],
    }

    if field_name in field_mappings:
        for alt_field in field_mappings[field_name]:
            if hasattr(doc, alt_field):
                value = doc.get(alt_field)
                if value:
                    return value

    # Check attribute values (EAV)
    attribute_values = doc.get("attribute_values") or []
    for attr in attribute_values:
        if attr.get("attribute") == field_name:
            return _get_eav_value(attr)

    return None


def _get_eav_value(row: Dict) -> Any:
    """Extract value from EAV row checking all value columns.

    Args:
        row: Product Attribute Value row

    Returns:
        The value from whichever column has it
    """
    value_fields = [
        "value_text", "value_int", "value_float", "value_boolean",
        "value_date", "value_datetime", "value_link", "value_data",
    ]

    for field in value_fields:
        value = row.get(field)
        if value is not None and value != "":
            return value

    return None


def _check_field_value(value: Any, requirement: FieldRequirement) -> bool:
    """Check if a field value satisfies basic requirements.

    Args:
        value: The field value
        requirement: FieldRequirement to check against

    Returns:
        bool: True if value is acceptable
    """
    # None or empty is not acceptable for required/critical
    if value is None:
        return False

    if isinstance(value, str):
        value = value.strip()
        if not value:
            return False

        # Check min/max length
        if requirement.min_length and len(value) < requirement.min_length:
            return False
        if requirement.max_length and len(value) > requirement.max_length:
            return False

    # Value exists and passes basic checks
    return True


def _validate_field_against_requirement(value: Any, requirement: FieldRequirement) -> Dict:
    """Validate a field value against full requirement specification.

    Args:
        value: The field value
        requirement: FieldRequirement to validate against

    Returns:
        dict: Validation result with is_valid, requirement description, and remediation
    """
    import re

    result = {
        "is_valid": True,
        "requirement": requirement.description,
        "remediation": requirement.remediation,
        "issues": []
    }

    # Check if value exists
    if value is None:
        result["is_valid"] = False
        result["issues"].append("Field is empty")
        result["requirement"] = f"Required: {requirement.description}"
        return result

    # String validation
    if isinstance(value, str):
        value = value.strip()

        if not value:
            result["is_valid"] = False
            result["issues"].append("Field is empty")
            return result

        # Check min length
        if requirement.min_length and len(value) < requirement.min_length:
            result["is_valid"] = False
            result["issues"].append(f"Too short (min {requirement.min_length} characters)")
            result["requirement"] = f"Minimum {requirement.min_length} characters required"

        # Check max length
        if requirement.max_length and len(value) > requirement.max_length:
            result["is_valid"] = False
            result["issues"].append(f"Too long (max {requirement.max_length} characters)")
            result["requirement"] = f"Maximum {requirement.max_length} characters allowed"

        # Check pattern
        if requirement.pattern:
            if not re.match(requirement.pattern, value):
                result["is_valid"] = False
                result["issues"].append("Invalid format")
                result["requirement"] = f"Must match pattern: {requirement.pattern}"

        # Check allowed values
        if requirement.allowed_values:
            if value.lower() not in [v.lower() for v in requirement.allowed_values]:
                result["is_valid"] = False
                result["issues"].append(f"Invalid value (allowed: {', '.join(requirement.allowed_values)})")
                result["requirement"] = f"Must be one of: {', '.join(requirement.allowed_values)}"

    return result


def _calculate_field_score_impact(importance: FieldImportance, total_fields: int) -> float:
    """Calculate the score impact of filling a specific field.

    Args:
        importance: Field importance level
        total_fields: Total number of fields being evaluated

    Returns:
        float: Percentage impact on score
    """
    if total_fields == 0:
        return 0.0

    base_impact = 100.0 / total_fields

    # Weight by importance
    weights = {
        FieldImportance.CRITICAL: 1.5,
        FieldImportance.REQUIRED: 1.0,
        FieldImportance.RECOMMENDED: 0.5,
        FieldImportance.OPTIONAL: 0.25,
    }

    return base_impact * weights.get(importance, 1.0)


def _analyze_media_gaps(doc, media_requirements: Dict) -> List[Dict]:
    """Analyze media/image gaps against channel requirements.

    Args:
        doc: Product Master document
        media_requirements: Channel media requirement specification

    Returns:
        list: List of media gap dictionaries
    """
    gaps = []

    if not media_requirements:
        return gaps

    # Get product media
    media_items = doc.get("media") or doc.get("images") or []
    image_count = len(media_items)

    # Check minimum images
    min_images = media_requirements.get("min_images", 0)
    if image_count < min_images:
        gaps.append({
            "type": "missing_images",
            "requirement": f"Minimum {min_images} images required",
            "current": image_count,
            "needed": min_images - image_count,
            "remediation": f"Add {min_images - image_count} more product images"
        })

    # Check main image
    if media_requirements.get("main_image_required") and image_count == 0:
        gaps.append({
            "type": "no_main_image",
            "requirement": "Main product image required",
            "current": None,
            "remediation": "Add a main product image"
        })

    # Check recommended image count
    recommended = media_requirements.get("recommended_images")
    if recommended and image_count < recommended:
        gaps.append({
            "type": "below_recommended_images",
            "requirement": f"Recommended {recommended} images",
            "current": image_count,
            "needed": recommended - image_count,
            "remediation": f"Consider adding {recommended - image_count} more images for better conversion"
        })

    return gaps


# =============================================================================
# API Functions for Frappe
# =============================================================================

def api_calculate_channel_score(product_name: str, channel_code: str) -> Dict:
    """API wrapper for calculate_channel_specific_score.

    Args:
        product_name: Name of the Product Master
        channel_code: Channel code

    Returns:
        dict: Channel-specific score result
    """
    return calculate_channel_specific_score(product_name, channel_code)


def api_gap_analysis(product_name: str, channel_code: str) -> Dict:
    """API wrapper for gap_analysis.

    Args:
        product_name: Name of the Product Master
        channel_code: Channel code

    Returns:
        dict: Gap analysis result
    """
    result = gap_analysis(product_name, channel_code)
    return result.to_dict()


def api_multi_channel_scores(product_name: str, channels: str = None) -> Dict:
    """API wrapper for calculate_multi_channel_scores.

    Args:
        product_name: Name of the Product Master
        channels: Comma-separated channel codes (optional)

    Returns:
        dict: Multi-channel score results
    """
    channel_list = None
    if channels:
        channel_list = [c.strip() for c in channels.split(",")]
    return calculate_multi_channel_scores(product_name, channel_list)


def api_get_remediation_plan(product_name: str, channel_code: str = None) -> Dict:
    """API wrapper for get_remediation_plan.

    Args:
        product_name: Name of the Product Master
        channel_code: Optional specific channel

    Returns:
        dict: Prioritized remediation plan
    """
    return get_remediation_plan(product_name, channel_code)


def api_list_channel_requirements() -> Dict:
    """List all available channel requirements.

    Returns:
        dict: Channel codes and their requirement summaries
    """
    return {
        "channels": [
            {
                "code": code,
                "name": req.channel_name,
                "description": req.description,
                "gtin_required": req.gtin_required,
                "category_required": req.category_required,
                "critical_fields": req.get_critical_fields(),
                "required_fields": req.get_all_required_fields(),
            }
            for code, req in CHANNEL_REQUIREMENTS.items()
            if code != "default"
        ]
    }


def api_get_channel_requirements(channel_code: str) -> Dict:
    """Get detailed requirements for a specific channel.

    Args:
        channel_code: Channel code

    Returns:
        dict: Full channel requirements
    """
    req = get_channel_requirements(channel_code)
    return req.to_dict()


# Wrapper for Frappe whitelist - applied at runtime
def _wrap_for_whitelist():
    """Apply frappe.whitelist decorator to API functions at runtime."""
    import frappe

    global api_calculate_channel_score, api_gap_analysis, api_multi_channel_scores
    global api_get_remediation_plan, api_list_channel_requirements, api_get_channel_requirements

    api_calculate_channel_score = frappe.whitelist()(api_calculate_channel_score)
    api_gap_analysis = frappe.whitelist()(api_gap_analysis)
    api_multi_channel_scores = frappe.whitelist()(api_multi_channel_scores)
    api_get_remediation_plan = frappe.whitelist()(api_get_remediation_plan)
    api_list_channel_requirements = frappe.whitelist()(api_list_channel_requirements)
    api_get_channel_requirements = frappe.whitelist()(api_get_channel_requirements)


# Apply whitelist decorators when module is loaded in Frappe context
try:
    import frappe
    _wrap_for_whitelist()
except ImportError:
    pass  # Frappe not available, skip whitelist decoration