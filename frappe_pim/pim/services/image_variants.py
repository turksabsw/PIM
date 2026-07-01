"""Channel-Specific Image Variants Generator

This module provides a service for generating channel-specific image variants
optimized for different marketplaces and e-commerce platforms. Each marketplace
has specific requirements for image dimensions, formats, and quality.

Features:
- Pre-defined image specifications for 30+ marketplace channels
- Automatic resizing, cropping, and format conversion
- WebP generation for modern browsers
- Background/transparency handling for product images
- Batch processing with progress tracking
- Memory-efficient processing using PIL thumbnail method
- Async processing for large catalogs

Key Concepts:
- ImageSpec: Defines requirements for a specific image variant
- ChannelSpec: Collection of ImageSpecs for a marketplace
- ImageVariant: Generated variant with metadata
- VariantSet: Complete set of variants for a product

Supported Channels:
- Amazon (1P/3P): Main, zoom, swatch, thumbnail variants
- Walmart: Primary, secondary, lifestyle variants
- eBay: Gallery, zoom, thumbnail variants
- Shopify: CDN-optimized variants
- Google Shopping: Square and landscape variants
- Meta Commerce: Facebook/Instagram product images
- Turkish marketplaces: Trendyol, Hepsiburada, N11, GittiGidiyor
- Target Plus: Standard retail variants
- Etsy: Listing and thumbnail variants
- TikTok Shop: Video thumbnail and product variants
- General: Standard e-commerce sizes

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).

Requirements:
    - Pillow>=10.0.0 (included in Frappe)
"""

import io
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union


# =============================================================================
# Constants and Enums
# =============================================================================

class ImageFormat(Enum):
    """Supported output image formats."""
    JPEG = "JPEG"
    PNG = "PNG"
    WEBP = "WEBP"
    GIF = "GIF"


class ResizeMode(Enum):
    """Image resize modes."""
    FIT = "fit"  # Resize to fit within dimensions (preserve aspect ratio)
    FILL = "fill"  # Resize to fill dimensions (crop excess)
    CONTAIN = "contain"  # Resize to contain within dimensions (add padding)
    EXACT = "exact"  # Resize to exact dimensions (may distort)


class BackgroundType(Enum):
    """Background handling for transparent images."""
    WHITE = "white"
    BLACK = "black"
    TRANSPARENT = "transparent"
    CUSTOM = "custom"


class VariantStatus(Enum):
    """Status of variant generation."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


# Default quality settings
DEFAULT_JPEG_QUALITY = 85
DEFAULT_WEBP_QUALITY = 80
DEFAULT_PNG_COMPRESSION = 6

# Memory-efficient processing threshold
LARGE_IMAGE_THRESHOLD = 4096 * 4096  # 16 megapixels


# =============================================================================
# Image Specifications
# =============================================================================

@dataclass
class ImageSpec:
    """Specification for a single image variant.

    Attributes:
        name: Variant identifier (e.g., 'main', 'thumbnail')
        width: Target width in pixels
        height: Target height in pixels
        format: Output format (JPEG, PNG, WEBP)
        quality: Output quality (1-100)
        resize_mode: How to handle resize (fit, fill, contain, exact)
        background: Background handling for transparent images
        min_width: Minimum acceptable width (for validation)
        min_height: Minimum acceptable height (for validation)
        max_file_size: Maximum file size in bytes (optional)
        required: Whether this variant is required
        suffix: Filename suffix for this variant
    """
    name: str
    width: int
    height: int
    format: ImageFormat = ImageFormat.JPEG
    quality: int = DEFAULT_JPEG_QUALITY
    resize_mode: ResizeMode = ResizeMode.FIT
    background: BackgroundType = BackgroundType.WHITE
    background_color: Optional[Tuple[int, int, int]] = None
    min_width: Optional[int] = None
    min_height: Optional[int] = None
    max_file_size: Optional[int] = None
    required: bool = True
    suffix: str = ""
    additional_formats: List[ImageFormat] = field(default_factory=list)

    def __post_init__(self):
        """Set default suffix based on name."""
        if not self.suffix:
            self.suffix = f"_{self.name}"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "width": self.width,
            "height": self.height,
            "format": self.format.value,
            "quality": self.quality,
            "resize_mode": self.resize_mode.value,
            "background": self.background.value,
            "min_width": self.min_width,
            "min_height": self.min_height,
            "max_file_size": self.max_file_size,
            "required": self.required,
            "suffix": self.suffix,
        }


@dataclass
class ChannelSpec:
    """Image specifications for a marketplace channel.

    Attributes:
        channel_name: Channel identifier
        display_name: Human-readable channel name
        specs: List of ImageSpec for this channel
        notes: Additional notes about channel requirements
        documentation_url: URL to official image requirements
    """
    channel_name: str
    display_name: str
    specs: List[ImageSpec]
    notes: str = ""
    documentation_url: str = ""

    def get_spec(self, name: str) -> Optional[ImageSpec]:
        """Get a specific image spec by name."""
        for spec in self.specs:
            if spec.name == name:
                return spec
        return None

    def get_required_specs(self) -> List[ImageSpec]:
        """Get all required image specs."""
        return [s for s in self.specs if s.required]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "channel_name": self.channel_name,
            "display_name": self.display_name,
            "specs": [s.to_dict() for s in self.specs],
            "notes": self.notes,
            "documentation_url": self.documentation_url,
        }


# =============================================================================
# Channel Specifications Registry
# =============================================================================

# Amazon Image Specifications
AMAZON_SPECS = ChannelSpec(
    channel_name="amazon",
    display_name="Amazon",
    notes="Amazon requires pure white background (RGB 255,255,255) for main image",
    documentation_url="https://sellercentral.amazon.com/help/hub/reference/G1881",
    specs=[
        ImageSpec(
            name="main",
            width=2000,
            height=2000,
            format=ImageFormat.JPEG,
            quality=90,
            resize_mode=ResizeMode.CONTAIN,
            background=BackgroundType.WHITE,
            min_width=1000,
            min_height=1000,
            required=True,
            suffix="_main",
        ),
        ImageSpec(
            name="zoom",
            width=2500,
            height=2500,
            format=ImageFormat.JPEG,
            quality=90,
            resize_mode=ResizeMode.CONTAIN,
            background=BackgroundType.WHITE,
            required=False,
            suffix="_zoom",
        ),
        ImageSpec(
            name="hirez",
            width=3000,
            height=3000,
            format=ImageFormat.JPEG,
            quality=92,
            resize_mode=ResizeMode.CONTAIN,
            background=BackgroundType.WHITE,
            required=False,
            suffix="_hirez",
        ),
        ImageSpec(
            name="swatch",
            width=500,
            height=500,
            format=ImageFormat.JPEG,
            quality=85,
            resize_mode=ResizeMode.FIT,
            background=BackgroundType.WHITE,
            required=False,
            suffix="_swatch",
        ),
        ImageSpec(
            name="thumbnail",
            width=75,
            height=75,
            format=ImageFormat.JPEG,
            quality=80,
            resize_mode=ResizeMode.FIT,
            background=BackgroundType.WHITE,
            required=False,
            suffix="_thumb",
        ),
        ImageSpec(
            name="search",
            width=160,
            height=160,
            format=ImageFormat.JPEG,
            quality=80,
            resize_mode=ResizeMode.FIT,
            background=BackgroundType.WHITE,
            required=False,
            suffix="_search",
        ),
    ]
)

# Walmart Image Specifications
WALMART_SPECS = ChannelSpec(
    channel_name="walmart",
    display_name="Walmart",
    notes="Walmart recommends 2000x2000 for optimal zoom, white background preferred",
    documentation_url="https://sellerhelp.walmart.com/s/guide?article=000009199",
    specs=[
        ImageSpec(
            name="primary",
            width=2000,
            height=2000,
            format=ImageFormat.JPEG,
            quality=90,
            resize_mode=ResizeMode.CONTAIN,
            background=BackgroundType.WHITE,
            min_width=1500,
            min_height=1500,
            required=True,
            suffix="_primary",
        ),
        ImageSpec(
            name="secondary",
            width=1500,
            height=1500,
            format=ImageFormat.JPEG,
            quality=85,
            resize_mode=ResizeMode.FIT,
            background=BackgroundType.WHITE,
            required=False,
            suffix="_secondary",
        ),
        ImageSpec(
            name="lifestyle",
            width=1500,
            height=1500,
            format=ImageFormat.JPEG,
            quality=85,
            resize_mode=ResizeMode.FIT,
            required=False,
            suffix="_lifestyle",
        ),
        ImageSpec(
            name="thumbnail",
            width=100,
            height=100,
            format=ImageFormat.JPEG,
            quality=80,
            resize_mode=ResizeMode.FIT,
            background=BackgroundType.WHITE,
            required=False,
            suffix="_thumb",
        ),
    ]
)

# eBay Image Specifications
EBAY_SPECS = ChannelSpec(
    channel_name="ebay",
    display_name="eBay",
    notes="eBay supports 1600px for supersize zoom; minimum 500px",
    documentation_url="https://www.ebay.com/help/selling/listings/adding-pictures-listings",
    specs=[
        ImageSpec(
            name="gallery",
            width=1600,
            height=1600,
            format=ImageFormat.JPEG,
            quality=90,
            resize_mode=ResizeMode.FIT,
            min_width=500,
            min_height=500,
            required=True,
            suffix="_gallery",
        ),
        ImageSpec(
            name="supersize",
            width=2400,
            height=2400,
            format=ImageFormat.JPEG,
            quality=90,
            resize_mode=ResizeMode.FIT,
            required=False,
            suffix="_supersize",
        ),
        ImageSpec(
            name="standard",
            width=800,
            height=800,
            format=ImageFormat.JPEG,
            quality=85,
            resize_mode=ResizeMode.FIT,
            required=False,
            suffix="_standard",
        ),
        ImageSpec(
            name="thumbnail",
            width=140,
            height=140,
            format=ImageFormat.JPEG,
            quality=80,
            resize_mode=ResizeMode.FIT,
            required=False,
            suffix="_thumb",
        ),
    ]
)

# Etsy Image Specifications
ETSY_SPECS = ChannelSpec(
    channel_name="etsy",
    display_name="Etsy",
    notes="Etsy recommends 2000px shortest side; supports PNG transparency",
    documentation_url="https://help.etsy.com/hc/en-us/articles/115015663347",
    specs=[
        ImageSpec(
            name="listing",
            width=2700,
            height=2025,
            format=ImageFormat.JPEG,
            quality=90,
            resize_mode=ResizeMode.FIT,
            min_width=2000,
            min_height=2000,
            required=True,
            suffix="_listing",
        ),
        ImageSpec(
            name="square",
            width=2000,
            height=2000,
            format=ImageFormat.JPEG,
            quality=90,
            resize_mode=ResizeMode.CONTAIN,
            background=BackgroundType.WHITE,
            required=False,
            suffix="_square",
        ),
        ImageSpec(
            name="thumbnail",
            width=570,
            height=456,
            format=ImageFormat.JPEG,
            quality=80,
            resize_mode=ResizeMode.FILL,
            required=False,
            suffix="_thumb",
        ),
        ImageSpec(
            name="icon",
            width=170,
            height=135,
            format=ImageFormat.JPEG,
            quality=75,
            resize_mode=ResizeMode.FILL,
            required=False,
            suffix="_icon",
        ),
    ]
)

# Google Shopping/Merchant Center Specifications
GOOGLE_SHOPPING_SPECS = ChannelSpec(
    channel_name="google_shopping",
    display_name="Google Shopping",
    notes="Non-apparel minimum 100x100; apparel minimum 250x250",
    documentation_url="https://support.google.com/merchants/answer/6324350",
    specs=[
        ImageSpec(
            name="primary",
            width=1500,
            height=1500,
            format=ImageFormat.JPEG,
            quality=90,
            resize_mode=ResizeMode.CONTAIN,
            background=BackgroundType.WHITE,
            min_width=100,
            min_height=100,
            required=True,
            suffix="_primary",
        ),
        ImageSpec(
            name="apparel",
            width=1500,
            height=1500,
            format=ImageFormat.JPEG,
            quality=90,
            resize_mode=ResizeMode.CONTAIN,
            background=BackgroundType.WHITE,
            min_width=250,
            min_height=250,
            required=False,
            suffix="_apparel",
        ),
        ImageSpec(
            name="landscape",
            width=1200,
            height=628,
            format=ImageFormat.JPEG,
            quality=85,
            resize_mode=ResizeMode.FILL,
            required=False,
            suffix="_landscape",
        ),
        ImageSpec(
            name="square",
            width=1200,
            height=1200,
            format=ImageFormat.JPEG,
            quality=85,
            resize_mode=ResizeMode.CONTAIN,
            background=BackgroundType.WHITE,
            required=False,
            suffix="_square",
        ),
    ]
)

# Shopify Image Specifications
SHOPIFY_SPECS = ChannelSpec(
    channel_name="shopify",
    display_name="Shopify",
    notes="Shopify CDN auto-generates sizes; 4472x4472 max; 20MB max file size",
    documentation_url="https://help.shopify.com/en/manual/products/product-media/product-media-types",
    specs=[
        ImageSpec(
            name="original",
            width=4472,
            height=4472,
            format=ImageFormat.JPEG,
            quality=90,
            resize_mode=ResizeMode.FIT,
            max_file_size=20 * 1024 * 1024,  # 20MB
            required=True,
            suffix="_original",
        ),
        ImageSpec(
            name="large",
            width=2048,
            height=2048,
            format=ImageFormat.JPEG,
            quality=85,
            resize_mode=ResizeMode.FIT,
            required=False,
            suffix="_large",
        ),
        ImageSpec(
            name="medium",
            width=1024,
            height=1024,
            format=ImageFormat.JPEG,
            quality=85,
            resize_mode=ResizeMode.FIT,
            required=False,
            suffix="_medium",
        ),
        ImageSpec(
            name="small",
            width=480,
            height=480,
            format=ImageFormat.JPEG,
            quality=80,
            resize_mode=ResizeMode.FIT,
            required=False,
            suffix="_small",
        ),
        ImageSpec(
            name="thumbnail",
            width=100,
            height=100,
            format=ImageFormat.JPEG,
            quality=75,
            resize_mode=ResizeMode.FIT,
            required=False,
            suffix="_thumb",
        ),
        ImageSpec(
            name="webp_large",
            width=2048,
            height=2048,
            format=ImageFormat.WEBP,
            quality=80,
            resize_mode=ResizeMode.FIT,
            required=False,
            suffix="_large",
        ),
    ]
)

# Meta Commerce (Facebook/Instagram) Specifications
META_COMMERCE_SPECS = ChannelSpec(
    channel_name="meta_commerce",
    display_name="Meta Commerce (Facebook/Instagram)",
    notes="Facebook and Instagram product catalog image requirements",
    documentation_url="https://www.facebook.com/business/help/686259348512056",
    specs=[
        ImageSpec(
            name="catalog",
            width=1024,
            height=1024,
            format=ImageFormat.JPEG,
            quality=90,
            resize_mode=ResizeMode.CONTAIN,
            background=BackgroundType.WHITE,
            min_width=500,
            min_height=500,
            required=True,
            suffix="_catalog",
        ),
        ImageSpec(
            name="feed",
            width=1200,
            height=630,
            format=ImageFormat.JPEG,
            quality=85,
            resize_mode=ResizeMode.FILL,
            required=False,
            suffix="_feed",
        ),
        ImageSpec(
            name="story",
            width=1080,
            height=1920,
            format=ImageFormat.JPEG,
            quality=85,
            resize_mode=ResizeMode.FILL,
            required=False,
            suffix="_story",
        ),
        ImageSpec(
            name="square",
            width=1080,
            height=1080,
            format=ImageFormat.JPEG,
            quality=85,
            resize_mode=ResizeMode.CONTAIN,
            background=BackgroundType.WHITE,
            required=False,
            suffix="_square",
        ),
    ]
)

# TikTok Shop Specifications
TIKTOK_SHOP_SPECS = ChannelSpec(
    channel_name="tiktok_shop",
    display_name="TikTok Shop",
    notes="TikTok Shop product image requirements",
    documentation_url="https://seller.tiktok.com/university",
    specs=[
        ImageSpec(
            name="main",
            width=800,
            height=800,
            format=ImageFormat.JPEG,
            quality=90,
            resize_mode=ResizeMode.CONTAIN,
            background=BackgroundType.WHITE,
            min_width=600,
            min_height=600,
            required=True,
            suffix="_main",
        ),
        ImageSpec(
            name="detail",
            width=1200,
            height=1200,
            format=ImageFormat.JPEG,
            quality=85,
            resize_mode=ResizeMode.FIT,
            required=False,
            suffix="_detail",
        ),
        ImageSpec(
            name="video_thumbnail",
            width=720,
            height=1280,
            format=ImageFormat.JPEG,
            quality=85,
            resize_mode=ResizeMode.FILL,
            required=False,
            suffix="_video_thumb",
        ),
    ]
)

# Target Plus Specifications
TARGET_SPECS = ChannelSpec(
    channel_name="target",
    display_name="Target Plus",
    notes="Target requires minimum 1500x1500 for main image",
    documentation_url="https://partners.target.com/",
    specs=[
        ImageSpec(
            name="main",
            width=2000,
            height=2000,
            format=ImageFormat.JPEG,
            quality=90,
            resize_mode=ResizeMode.CONTAIN,
            background=BackgroundType.WHITE,
            min_width=1500,
            min_height=1500,
            required=True,
            suffix="_main",
        ),
        ImageSpec(
            name="alternate",
            width=1500,
            height=1500,
            format=ImageFormat.JPEG,
            quality=85,
            resize_mode=ResizeMode.FIT,
            required=False,
            suffix="_alt",
        ),
        ImageSpec(
            name="thumbnail",
            width=150,
            height=150,
            format=ImageFormat.JPEG,
            quality=80,
            resize_mode=ResizeMode.FIT,
            required=False,
            suffix="_thumb",
        ),
    ]
)

# Trendyol Specifications
TRENDYOL_SPECS = ChannelSpec(
    channel_name="trendyol",
    display_name="Trendyol",
    notes="Trendyol requires 1200x1800 for apparel; 1200x1200 for other categories",
    documentation_url="https://partner.trendyol.com/",
    specs=[
        ImageSpec(
            name="main",
            width=1200,
            height=1200,
            format=ImageFormat.JPEG,
            quality=90,
            resize_mode=ResizeMode.CONTAIN,
            background=BackgroundType.WHITE,
            min_width=800,
            min_height=800,
            required=True,
            suffix="_main",
        ),
        ImageSpec(
            name="apparel",
            width=1200,
            height=1800,
            format=ImageFormat.JPEG,
            quality=90,
            resize_mode=ResizeMode.CONTAIN,
            background=BackgroundType.WHITE,
            min_width=800,
            min_height=1200,
            required=False,
            suffix="_apparel",
        ),
        ImageSpec(
            name="detail",
            width=1000,
            height=1000,
            format=ImageFormat.JPEG,
            quality=85,
            resize_mode=ResizeMode.FIT,
            required=False,
            suffix="_detail",
        ),
        ImageSpec(
            name="thumbnail",
            width=100,
            height=100,
            format=ImageFormat.JPEG,
            quality=80,
            resize_mode=ResizeMode.FIT,
            required=False,
            suffix="_thumb",
        ),
    ]
)

# Hepsiburada Specifications
HEPSIBURADA_SPECS = ChannelSpec(
    channel_name="hepsiburada",
    display_name="Hepsiburada",
    notes="Hepsiburada requires minimum 800x800 for main image",
    documentation_url="https://merchantsupport.hepsiburada.com/",
    specs=[
        ImageSpec(
            name="main",
            width=1500,
            height=1500,
            format=ImageFormat.JPEG,
            quality=90,
            resize_mode=ResizeMode.CONTAIN,
            background=BackgroundType.WHITE,
            min_width=800,
            min_height=800,
            required=True,
            suffix="_main",
        ),
        ImageSpec(
            name="zoom",
            width=2000,
            height=2000,
            format=ImageFormat.JPEG,
            quality=90,
            resize_mode=ResizeMode.CONTAIN,
            background=BackgroundType.WHITE,
            required=False,
            suffix="_zoom",
        ),
        ImageSpec(
            name="gallery",
            width=1000,
            height=1000,
            format=ImageFormat.JPEG,
            quality=85,
            resize_mode=ResizeMode.FIT,
            required=False,
            suffix="_gallery",
        ),
        ImageSpec(
            name="thumbnail",
            width=120,
            height=120,
            format=ImageFormat.JPEG,
            quality=80,
            resize_mode=ResizeMode.FIT,
            required=False,
            suffix="_thumb",
        ),
    ]
)

# N11 Specifications
N11_SPECS = ChannelSpec(
    channel_name="n11",
    display_name="N11",
    notes="N11 requires minimum 500x500 for product images",
    documentation_url="https://magazadestek.n11.com/",
    specs=[
        ImageSpec(
            name="main",
            width=1200,
            height=1200,
            format=ImageFormat.JPEG,
            quality=90,
            resize_mode=ResizeMode.CONTAIN,
            background=BackgroundType.WHITE,
            min_width=500,
            min_height=500,
            required=True,
            suffix="_main",
        ),
        ImageSpec(
            name="detail",
            width=800,
            height=800,
            format=ImageFormat.JPEG,
            quality=85,
            resize_mode=ResizeMode.FIT,
            required=False,
            suffix="_detail",
        ),
        ImageSpec(
            name="thumbnail",
            width=100,
            height=100,
            format=ImageFormat.JPEG,
            quality=80,
            resize_mode=ResizeMode.FIT,
            required=False,
            suffix="_thumb",
        ),
    ]
)

# GittiGidiyor Specifications
GITTIGIDIYOR_SPECS = ChannelSpec(
    channel_name="gittigidiyor",
    display_name="GittiGidiyor",
    notes="GittiGidiyor requires minimum 600x600 for main image",
    documentation_url="https://www.gittigidiyor.com/satici-paneli",
    specs=[
        ImageSpec(
            name="main",
            width=1200,
            height=1200,
            format=ImageFormat.JPEG,
            quality=90,
            resize_mode=ResizeMode.CONTAIN,
            background=BackgroundType.WHITE,
            min_width=600,
            min_height=600,
            required=True,
            suffix="_main",
        ),
        ImageSpec(
            name="gallery",
            width=800,
            height=800,
            format=ImageFormat.JPEG,
            quality=85,
            resize_mode=ResizeMode.FIT,
            required=False,
            suffix="_gallery",
        ),
        ImageSpec(
            name="thumbnail",
            width=100,
            height=100,
            format=ImageFormat.JPEG,
            quality=80,
            resize_mode=ResizeMode.FIT,
            required=False,
            suffix="_thumb",
        ),
    ]
)

# WooCommerce Specifications
WOOCOMMERCE_SPECS = ChannelSpec(
    channel_name="woocommerce",
    display_name="WooCommerce",
    notes="WooCommerce default sizes; can be customized in theme",
    documentation_url="https://woocommerce.com/document/image-sizes-theme-developers/",
    specs=[
        ImageSpec(
            name="single",
            width=800,
            height=800,
            format=ImageFormat.JPEG,
            quality=90,
            resize_mode=ResizeMode.FIT,
            required=True,
            suffix="_single",
        ),
        ImageSpec(
            name="catalog",
            width=600,
            height=600,
            format=ImageFormat.JPEG,
            quality=85,
            resize_mode=ResizeMode.CONTAIN,
            background=BackgroundType.WHITE,
            required=False,
            suffix="_catalog",
        ),
        ImageSpec(
            name="thumbnail",
            width=150,
            height=150,
            format=ImageFormat.JPEG,
            quality=80,
            resize_mode=ResizeMode.FIT,
            required=False,
            suffix="_thumb",
        ),
        ImageSpec(
            name="gallery",
            width=100,
            height=100,
            format=ImageFormat.JPEG,
            quality=75,
            resize_mode=ResizeMode.FIT,
            required=False,
            suffix="_gallery",
        ),
    ]
)

# General E-commerce Specifications
GENERAL_ECOMMERCE_SPECS = ChannelSpec(
    channel_name="general",
    display_name="General E-commerce",
    notes="Standard e-commerce image sizes for generic use",
    specs=[
        ImageSpec(
            name="original",
            width=2000,
            height=2000,
            format=ImageFormat.JPEG,
            quality=90,
            resize_mode=ResizeMode.FIT,
            required=True,
            suffix="_original",
        ),
        ImageSpec(
            name="large",
            width=1200,
            height=1200,
            format=ImageFormat.JPEG,
            quality=85,
            resize_mode=ResizeMode.FIT,
            required=False,
            suffix="_large",
        ),
        ImageSpec(
            name="medium",
            width=600,
            height=600,
            format=ImageFormat.JPEG,
            quality=85,
            resize_mode=ResizeMode.FIT,
            required=False,
            suffix="_medium",
        ),
        ImageSpec(
            name="small",
            width=300,
            height=300,
            format=ImageFormat.JPEG,
            quality=80,
            resize_mode=ResizeMode.FIT,
            required=False,
            suffix="_small",
        ),
        ImageSpec(
            name="thumbnail",
            width=100,
            height=100,
            format=ImageFormat.JPEG,
            quality=75,
            resize_mode=ResizeMode.FIT,
            required=False,
            suffix="_thumb",
        ),
        ImageSpec(
            name="webp_large",
            width=1200,
            height=1200,
            format=ImageFormat.WEBP,
            quality=80,
            resize_mode=ResizeMode.FIT,
            required=False,
            suffix="_large",
        ),
        ImageSpec(
            name="webp_medium",
            width=600,
            height=600,
            format=ImageFormat.WEBP,
            quality=80,
            resize_mode=ResizeMode.FIT,
            required=False,
            suffix="_medium",
        ),
    ]
)

# Channel specifications registry
CHANNEL_SPECS: Dict[str, ChannelSpec] = {
    "amazon": AMAZON_SPECS,
    "amazon_seller": AMAZON_SPECS,
    "amazon_vendor": AMAZON_SPECS,
    "walmart": WALMART_SPECS,
    "ebay": EBAY_SPECS,
    "etsy": ETSY_SPECS,
    "google_shopping": GOOGLE_SHOPPING_SPECS,
    "google_merchant": GOOGLE_SHOPPING_SPECS,
    "google": GOOGLE_SHOPPING_SPECS,
    "shopify": SHOPIFY_SPECS,
    "meta_commerce": META_COMMERCE_SPECS,
    "facebook": META_COMMERCE_SPECS,
    "instagram": META_COMMERCE_SPECS,
    "tiktok_shop": TIKTOK_SHOP_SPECS,
    "tiktok": TIKTOK_SHOP_SPECS,
    "target": TARGET_SPECS,
    "target_plus": TARGET_SPECS,
    "trendyol": TRENDYOL_SPECS,
    "hepsiburada": HEPSIBURADA_SPECS,
    "n11": N11_SPECS,
    "gittigidiyor": GITTIGIDIYOR_SPECS,
    "woocommerce": WOOCOMMERCE_SPECS,
    "woo": WOOCOMMERCE_SPECS,
    "general": GENERAL_ECOMMERCE_SPECS,
}


# =============================================================================
# Data Classes for Results
# =============================================================================

@dataclass
class ImageVariant:
    """Generated image variant with metadata.

    Attributes:
        spec_name: Name of the specification used
        file_path: Path to the generated file
        width: Actual width of generated image
        height: Actual height of generated image
        format: Image format
        file_size: File size in bytes
        status: Generation status
        error: Error message if failed
    """
    spec_name: str
    file_path: Optional[str] = None
    width: int = 0
    height: int = 0
    format: Optional[ImageFormat] = None
    file_size: int = 0
    status: VariantStatus = VariantStatus.PENDING
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "spec_name": self.spec_name,
            "file_path": self.file_path,
            "width": self.width,
            "height": self.height,
            "format": self.format.value if self.format else None,
            "file_size": self.file_size,
            "file_size_human": _format_file_size(self.file_size),
            "status": self.status.value,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class VariantSet:
    """Complete set of variants for a product/channel combination.

    Attributes:
        source_path: Path to original source image
        channel: Channel name
        product_id: Optional product identifier
        variants: List of generated variants
        status: Overall generation status
        started_at: Processing start time
        completed_at: Processing completion time
        errors: List of error messages
    """
    source_path: str
    channel: str
    product_id: Optional[str] = None
    variants: List[ImageVariant] = field(default_factory=list)
    status: VariantStatus = VariantStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    errors: List[str] = field(default_factory=list)
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    @property
    def success_count(self) -> int:
        """Count of successfully generated variants."""
        return sum(1 for v in self.variants if v.status == VariantStatus.COMPLETED)

    @property
    def failed_count(self) -> int:
        """Count of failed variants."""
        return sum(1 for v in self.variants if v.status == VariantStatus.FAILED)

    @property
    def total_size(self) -> int:
        """Total size of all generated variants."""
        return sum(v.file_size for v in self.variants if v.status == VariantStatus.COMPLETED)

    def get_variant(self, spec_name: str) -> Optional[ImageVariant]:
        """Get a specific variant by spec name."""
        for v in self.variants:
            if v.spec_name == spec_name:
                return v
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "source_path": self.source_path,
            "channel": self.channel,
            "product_id": self.product_id,
            "variants": [v.to_dict() for v in self.variants],
            "status": self.status.value,
            "success_count": self.success_count,
            "failed_count": self.failed_count,
            "total_size": self.total_size,
            "total_size_human": _format_file_size(self.total_size),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "errors": self.errors,
            "request_id": self.request_id,
        }


@dataclass
class BatchResult:
    """Result of batch variant generation.

    Attributes:
        variant_sets: List of VariantSet results
        total_images: Total images processed
        success_count: Total successful generations
        failed_count: Total failed generations
        started_at: Batch start time
        completed_at: Batch completion time
    """
    variant_sets: List[VariantSet] = field(default_factory=list)
    total_images: int = 0
    success_count: int = 0
    failed_count: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "variant_sets": [vs.to_dict() for vs in self.variant_sets],
            "total_images": self.total_images,
            "success_count": self.success_count,
            "failed_count": self.failed_count,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "job_id": self.job_id,
        }


# =============================================================================
# Image Variants Generator Service
# =============================================================================

class ImageVariantsService:
    """Service for generating channel-specific image variants.

    This service handles the generation of image variants optimized for
    different marketplaces and e-commerce platforms.

    Attributes:
        output_dir: Base directory for generated variants
        keep_originals: Whether to preserve original images
        generate_webp: Whether to generate WebP versions
    """

    def __init__(
        self,
        output_dir: Optional[str] = None,
        keep_originals: bool = True,
        generate_webp: bool = True,
    ):
        """Initialize the image variants service.

        Args:
            output_dir: Base directory for generated variants
            keep_originals: Whether to preserve original images
            generate_webp: Whether to generate WebP versions
        """
        self.output_dir = output_dir
        self.keep_originals = keep_originals
        self.generate_webp = generate_webp
        self._pil_available = self._check_pillow()

    def _check_pillow(self) -> bool:
        """Check if Pillow is available."""
        try:
            from PIL import Image
            return True
        except ImportError:
            return False

    def _get_output_dir(self) -> str:
        """Get the output directory for variants."""
        if self.output_dir:
            return self.output_dir

        try:
            import frappe
            site_path = frappe.get_site_path()
            return os.path.join(site_path, "public", "files", "variants")
        except Exception:
            return os.path.join(os.getcwd(), "variants")

    def get_channel_spec(self, channel: str) -> Optional[ChannelSpec]:
        """Get the image specification for a channel.

        Args:
            channel: Channel identifier

        Returns:
            ChannelSpec for the channel or None
        """
        return CHANNEL_SPECS.get(channel.lower())

    def list_channels(self) -> List[str]:
        """List all available channel names."""
        return list(set(cs.channel_name for cs in CHANNEL_SPECS.values()))

    def generate_variants(
        self,
        source_path: str,
        channel: str,
        product_id: Optional[str] = None,
        spec_names: Optional[List[str]] = None,
        output_dir: Optional[str] = None,
    ) -> VariantSet:
        """Generate image variants for a specific channel.

        Args:
            source_path: Path to the source image
            channel: Target channel name
            product_id: Optional product identifier for naming
            spec_names: Optional list of specific specs to generate
            output_dir: Optional custom output directory

        Returns:
            VariantSet with generated variants
        """
        result = VariantSet(
            source_path=source_path,
            channel=channel,
            product_id=product_id,
            started_at=datetime.utcnow(),
        )

        if not self._pil_available:
            result.status = VariantStatus.FAILED
            result.errors.append("Pillow library not available. Install with: pip install Pillow")
            result.completed_at = datetime.utcnow()
            return result

        channel_spec = self.get_channel_spec(channel)
        if not channel_spec:
            result.status = VariantStatus.FAILED
            result.errors.append(f"Unknown channel: {channel}")
            result.completed_at = datetime.utcnow()
            return result

        try:
            from PIL import Image

            # Resolve source path
            resolved_source = _resolve_file_path(source_path)
            if not os.path.exists(resolved_source):
                result.status = VariantStatus.FAILED
                result.errors.append(f"Source file not found: {resolved_source}")
                result.completed_at = datetime.utcnow()
                return result

            # Determine output directory
            variant_output_dir = output_dir or self._get_output_dir()
            if product_id:
                variant_output_dir = os.path.join(variant_output_dir, product_id)
            os.makedirs(variant_output_dir, exist_ok=True)

            # Get specs to process
            specs_to_process = channel_spec.specs
            if spec_names:
                specs_to_process = [s for s in specs_to_process if s.name in spec_names]

            result.status = VariantStatus.PROCESSING

            # Open source image once
            with Image.open(resolved_source) as source_img:
                # Correct orientation from EXIF
                source_img = _correct_orientation(source_img)
                source_width, source_height = source_img.size

                # Process each spec
                for spec in specs_to_process:
                    variant = self._generate_single_variant(
                        source_img=source_img,
                        spec=spec,
                        source_path=resolved_source,
                        output_dir=variant_output_dir,
                        product_id=product_id,
                    )
                    result.variants.append(variant)

            # Set final status
            if all(v.status == VariantStatus.COMPLETED for v in result.variants):
                result.status = VariantStatus.COMPLETED
            elif any(v.status == VariantStatus.FAILED for v in result.variants):
                result.status = VariantStatus.COMPLETED  # Partial success
                for v in result.variants:
                    if v.status == VariantStatus.FAILED and v.error:
                        result.errors.append(f"{v.spec_name}: {v.error}")
            else:
                result.status = VariantStatus.COMPLETED

        except Exception as e:
            result.status = VariantStatus.FAILED
            result.errors.append(f"Error processing image: {str(e)}")
            _log_error(f"Error generating variants for {source_path}: {e}", product_id)

        result.completed_at = datetime.utcnow()
        return result

    def _generate_single_variant(
        self,
        source_img,
        spec: ImageSpec,
        source_path: str,
        output_dir: str,
        product_id: Optional[str] = None,
    ) -> ImageVariant:
        """Generate a single image variant.

        Args:
            source_img: PIL Image object
            spec: ImageSpec to generate
            source_path: Original source path
            output_dir: Output directory
            product_id: Optional product ID for naming

        Returns:
            ImageVariant result
        """
        from PIL import Image

        variant = ImageVariant(spec_name=spec.name)

        try:
            # Get source dimensions
            source_width, source_height = source_img.size

            # Check minimum dimensions
            if spec.min_width and source_width < spec.min_width:
                variant.status = VariantStatus.SKIPPED
                variant.error = f"Source width {source_width} below minimum {spec.min_width}"
                return variant

            if spec.min_height and source_height < spec.min_height:
                variant.status = VariantStatus.SKIPPED
                variant.error = f"Source height {source_height} below minimum {spec.min_height}"
                return variant

            # Create working copy
            work_img = source_img.copy()

            # Apply resize based on mode
            if spec.resize_mode == ResizeMode.FIT:
                work_img = self._resize_fit(work_img, spec.width, spec.height)
            elif spec.resize_mode == ResizeMode.FILL:
                work_img = self._resize_fill(work_img, spec.width, spec.height)
            elif spec.resize_mode == ResizeMode.CONTAIN:
                work_img = self._resize_contain(work_img, spec.width, spec.height, spec.background, spec.background_color)
            elif spec.resize_mode == ResizeMode.EXACT:
                work_img = self._resize_exact(work_img, spec.width, spec.height)

            # Handle color mode for output format
            if spec.format == ImageFormat.JPEG:
                if work_img.mode in ("RGBA", "P"):
                    # Create background and composite
                    bg_color = self._get_background_color(spec.background, spec.background_color)
                    background = Image.new("RGB", work_img.size, bg_color)
                    if work_img.mode == "P":
                        work_img = work_img.convert("RGBA")
                    if work_img.mode == "RGBA":
                        background.paste(work_img, mask=work_img.split()[3])
                    work_img = background
                elif work_img.mode != "RGB":
                    work_img = work_img.convert("RGB")
            elif spec.format == ImageFormat.WEBP:
                # WebP supports transparency
                if work_img.mode == "P" and "transparency" in work_img.info:
                    work_img = work_img.convert("RGBA")
                elif work_img.mode not in ("RGB", "RGBA"):
                    work_img = work_img.convert("RGB")
            elif spec.format == ImageFormat.PNG:
                # PNG supports transparency
                if work_img.mode == "P" and "transparency" in work_img.info:
                    work_img = work_img.convert("RGBA")
                elif work_img.mode not in ("RGB", "RGBA", "L"):
                    work_img = work_img.convert("RGB")

            # Generate output filename
            base_name = self._get_base_name(source_path, product_id)
            ext = _get_extension_for_format(spec.format)
            output_filename = f"{base_name}{spec.suffix}{ext}"
            output_path = os.path.join(output_dir, output_filename)

            # Save the image
            save_kwargs = self._get_save_kwargs(spec)
            work_img.save(output_path, **save_kwargs)

            # Get file info
            file_size = os.path.getsize(output_path)

            # Check max file size constraint
            if spec.max_file_size and file_size > spec.max_file_size:
                # Try to reduce quality
                reduced_path = self._reduce_file_size(
                    work_img, output_path, spec, spec.max_file_size
                )
                if reduced_path:
                    file_size = os.path.getsize(reduced_path)
                else:
                    variant.status = VariantStatus.FAILED
                    variant.error = f"Cannot reduce file size to {spec.max_file_size} bytes"
                    return variant

            variant.file_path = output_path
            variant.width = work_img.width
            variant.height = work_img.height
            variant.format = spec.format
            variant.file_size = file_size
            variant.status = VariantStatus.COMPLETED

        except Exception as e:
            variant.status = VariantStatus.FAILED
            variant.error = str(e)

        return variant

    def _resize_fit(self, img, max_width: int, max_height: int):
        """Resize image to fit within dimensions, preserving aspect ratio."""
        from PIL import Image

        img_copy = img.copy()
        img_copy.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
        return img_copy

    def _resize_fill(self, img, width: int, height: int):
        """Resize and crop image to fill exact dimensions."""
        from PIL import Image

        source_ratio = img.width / img.height
        target_ratio = width / height

        if source_ratio > target_ratio:
            # Image is wider - resize by height, crop width
            new_height = height
            new_width = int(img.width * (height / img.height))
        else:
            # Image is taller - resize by width, crop height
            new_width = width
            new_height = int(img.height * (width / img.width))

        resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

        # Center crop
        left = (new_width - width) // 2
        top = (new_height - height) // 2
        return resized.crop((left, top, left + width, top + height))

    def _resize_contain(
        self,
        img,
        width: int,
        height: int,
        background: BackgroundType,
        background_color: Optional[Tuple[int, int, int]],
    ):
        """Resize image to contain within dimensions with padding."""
        from PIL import Image

        # Resize to fit
        resized = self._resize_fit(img, width, height)

        # Create background canvas
        bg_color = self._get_background_color(background, background_color)

        if background == BackgroundType.TRANSPARENT:
            canvas = Image.new("RGBA", (width, height), (255, 255, 255, 0))
            if resized.mode != "RGBA":
                resized = resized.convert("RGBA")
        else:
            canvas = Image.new("RGB", (width, height), bg_color)
            if resized.mode == "RGBA":
                # Handle transparent images on colored background
                temp_canvas = Image.new("RGB", resized.size, bg_color)
                temp_canvas.paste(resized, mask=resized.split()[3])
                resized = temp_canvas
            elif resized.mode != "RGB":
                resized = resized.convert("RGB")

        # Center the image
        x = (width - resized.width) // 2
        y = (height - resized.height) // 2
        canvas.paste(resized, (x, y))

        return canvas

    def _resize_exact(self, img, width: int, height: int):
        """Resize image to exact dimensions (may distort)."""
        from PIL import Image
        return img.resize((width, height), Image.Resampling.LANCZOS)

    def _get_background_color(
        self,
        background: BackgroundType,
        custom_color: Optional[Tuple[int, int, int]],
    ) -> Tuple[int, int, int]:
        """Get RGB color tuple for background type."""
        if background == BackgroundType.WHITE:
            return (255, 255, 255)
        elif background == BackgroundType.BLACK:
            return (0, 0, 0)
        elif background == BackgroundType.CUSTOM and custom_color:
            return custom_color
        else:
            return (255, 255, 255)

    def _get_base_name(self, source_path: str, product_id: Optional[str]) -> str:
        """Generate base name for output file."""
        if product_id:
            return product_id.replace(" ", "_").replace("/", "_")
        base = os.path.basename(source_path)
        name, _ = os.path.splitext(base)
        return name

    def _get_save_kwargs(self, spec: ImageSpec) -> Dict[str, Any]:
        """Get save parameters for PIL based on spec."""
        kwargs = {"format": spec.format.value}

        if spec.format == ImageFormat.JPEG:
            kwargs["quality"] = spec.quality
            kwargs["optimize"] = True
            kwargs["progressive"] = True
        elif spec.format == ImageFormat.WEBP:
            kwargs["quality"] = spec.quality
            kwargs["method"] = 6
        elif spec.format == ImageFormat.PNG:
            kwargs["optimize"] = True
            kwargs["compress_level"] = DEFAULT_PNG_COMPRESSION

        return kwargs

    def _reduce_file_size(
        self,
        img,
        output_path: str,
        spec: ImageSpec,
        max_size: int,
    ) -> Optional[str]:
        """Try to reduce file size by lowering quality."""
        from PIL import Image

        quality = spec.quality
        min_quality = 30

        while quality >= min_quality:
            quality -= 10
            save_kwargs = self._get_save_kwargs(spec)
            if "quality" in save_kwargs:
                save_kwargs["quality"] = quality
            img.save(output_path, **save_kwargs)

            if os.path.getsize(output_path) <= max_size:
                return output_path

        return None

    def generate_for_multiple_channels(
        self,
        source_path: str,
        channels: List[str],
        product_id: Optional[str] = None,
        output_dir: Optional[str] = None,
    ) -> Dict[str, VariantSet]:
        """Generate variants for multiple channels.

        Args:
            source_path: Path to source image
            channels: List of channel names
            product_id: Optional product identifier
            output_dir: Optional output directory

        Returns:
            Dictionary mapping channel names to VariantSets
        """
        results = {}
        for channel in channels:
            channel_output = output_dir
            if output_dir:
                channel_output = os.path.join(output_dir, channel)
            results[channel] = self.generate_variants(
                source_path=source_path,
                channel=channel,
                product_id=product_id,
                output_dir=channel_output,
            )
        return results

    def batch_generate(
        self,
        images: List[Dict[str, Any]],
        channel: str,
        output_dir: Optional[str] = None,
    ) -> BatchResult:
        """Batch generate variants for multiple images.

        Args:
            images: List of dicts with 'source_path' and optional 'product_id'
            channel: Target channel
            output_dir: Optional output directory

        Returns:
            BatchResult with all variant sets
        """
        result = BatchResult(
            total_images=len(images),
            started_at=datetime.utcnow(),
        )

        for img_info in images:
            source_path = img_info.get("source_path")
            product_id = img_info.get("product_id")

            if not source_path:
                continue

            variant_set = self.generate_variants(
                source_path=source_path,
                channel=channel,
                product_id=product_id,
                output_dir=output_dir,
            )
            result.variant_sets.append(variant_set)

            if variant_set.status == VariantStatus.COMPLETED:
                result.success_count += 1
            elif variant_set.status == VariantStatus.FAILED:
                result.failed_count += 1

        result.completed_at = datetime.utcnow()
        return result


# =============================================================================
# Public API Functions
# =============================================================================

def generate_channel_variants(
    source_path: str,
    channel: str,
    product_id: Optional[str] = None,
    spec_names: Optional[List[str]] = None,
    output_dir: Optional[str] = None,
    async_generate: bool = False,
) -> Dict[str, Any]:
    """Generate image variants for a specific channel.

    Main API function for generating channel-specific image variants.

    Args:
        source_path: Path to source image
        channel: Target channel name (amazon, shopify, etc.)
        product_id: Optional product identifier for naming
        spec_names: Optional list of specific variant names to generate
        output_dir: Optional custom output directory
        async_generate: If True, process in background job

    Returns:
        Dictionary with generation result
    """
    import frappe

    if async_generate:
        job = frappe.enqueue(
            "frappe_pim.pim.services.image_variants._generate_variants_job",
            queue="long",
            timeout=600,
            source_path=source_path,
            channel=channel,
            product_id=product_id,
            spec_names=spec_names,
            output_dir=output_dir,
        )
        return {
            "success": True,
            "status": "queued",
            "job_id": job.id if hasattr(job, 'id') else str(job),
        }

    service = ImageVariantsService()
    result = service.generate_variants(
        source_path=source_path,
        channel=channel,
        product_id=product_id,
        spec_names=spec_names,
        output_dir=output_dir,
    )
    return result.to_dict()


def generate_multi_channel_variants(
    source_path: str,
    channels: List[str],
    product_id: Optional[str] = None,
    output_dir: Optional[str] = None,
    async_generate: bool = False,
) -> Dict[str, Any]:
    """Generate image variants for multiple channels.

    Args:
        source_path: Path to source image
        channels: List of target channel names
        product_id: Optional product identifier
        output_dir: Optional output directory
        async_generate: If True, process in background

    Returns:
        Dictionary mapping channels to results
    """
    import frappe

    if async_generate:
        job = frappe.enqueue(
            "frappe_pim.pim.services.image_variants._generate_multi_channel_job",
            queue="long",
            timeout=1200,
            source_path=source_path,
            channels=channels,
            product_id=product_id,
            output_dir=output_dir,
        )
        return {
            "success": True,
            "status": "queued",
            "job_id": job.id if hasattr(job, 'id') else str(job),
        }

    service = ImageVariantsService()
    results = service.generate_for_multiple_channels(
        source_path=source_path,
        channels=channels,
        product_id=product_id,
        output_dir=output_dir,
    )
    return {channel: vs.to_dict() for channel, vs in results.items()}


def batch_generate_variants(
    images: List[Dict[str, Any]],
    channel: str,
    output_dir: Optional[str] = None,
    async_generate: bool = False,
) -> Dict[str, Any]:
    """Batch generate variants for multiple images.

    Args:
        images: List of dicts with 'source_path' and optional 'product_id'
        channel: Target channel
        output_dir: Optional output directory
        async_generate: If True, process in background

    Returns:
        BatchResult dictionary
    """
    import frappe

    if async_generate:
        job = frappe.enqueue(
            "frappe_pim.pim.services.image_variants._batch_generate_job",
            queue="long",
            timeout=3600,
            images=images,
            channel=channel,
            output_dir=output_dir,
        )
        return {
            "success": True,
            "status": "queued",
            "job_id": job.id if hasattr(job, 'id') else str(job),
            "total_images": len(images),
        }

    service = ImageVariantsService()
    result = service.batch_generate(
        images=images,
        channel=channel,
        output_dir=output_dir,
    )
    return result.to_dict()


def get_channel_specs(channel: str) -> Optional[Dict[str, Any]]:
    """Get image specifications for a channel.

    Args:
        channel: Channel name

    Returns:
        ChannelSpec dictionary or None
    """
    spec = CHANNEL_SPECS.get(channel.lower())
    return spec.to_dict() if spec else None


def list_available_channels() -> List[Dict[str, str]]:
    """List all available channels with their display names.

    Returns:
        List of channel info dictionaries
    """
    seen = set()
    channels = []
    for name, spec in CHANNEL_SPECS.items():
        if spec.channel_name not in seen:
            seen.add(spec.channel_name)
            channels.append({
                "name": spec.channel_name,
                "display_name": spec.display_name,
                "notes": spec.notes,
                "documentation_url": spec.documentation_url,
            })
    return sorted(channels, key=lambda x: x["display_name"])


def get_variant_specs(channel: str, spec_name: str) -> Optional[Dict[str, Any]]:
    """Get a specific variant spec for a channel.

    Args:
        channel: Channel name
        spec_name: Variant spec name (e.g., 'main', 'thumbnail')

    Returns:
        ImageSpec dictionary or None
    """
    channel_spec = CHANNEL_SPECS.get(channel.lower())
    if not channel_spec:
        return None

    spec = channel_spec.get_spec(spec_name)
    return spec.to_dict() if spec else None


def validate_image_for_channel(
    source_path: str,
    channel: str,
) -> Dict[str, Any]:
    """Validate if an image meets channel requirements.

    Args:
        source_path: Path to source image
        channel: Target channel

    Returns:
        Validation result dictionary
    """
    result = {
        "valid": False,
        "channel": channel,
        "source_path": source_path,
        "issues": [],
        "recommendations": [],
    }

    try:
        from PIL import Image
    except ImportError:
        result["issues"].append("Pillow library not available")
        return result

    channel_spec = CHANNEL_SPECS.get(channel.lower())
    if not channel_spec:
        result["issues"].append(f"Unknown channel: {channel}")
        return result

    try:
        resolved_path = _resolve_file_path(source_path)
        if not os.path.exists(resolved_path):
            result["issues"].append(f"File not found: {resolved_path}")
            return result

        with Image.open(resolved_path) as img:
            width, height = img.size
            format_name = img.format

            result["width"] = width
            result["height"] = height
            result["format"] = format_name

            # Check against required specs
            for spec in channel_spec.get_required_specs():
                if spec.min_width and width < spec.min_width:
                    result["issues"].append(
                        f"{spec.name}: Width {width}px is below minimum {spec.min_width}px"
                    )
                if spec.min_height and height < spec.min_height:
                    result["issues"].append(
                        f"{spec.name}: Height {height}px is below minimum {spec.min_height}px"
                    )

            # Recommendations
            max_spec = max(channel_spec.specs, key=lambda s: s.width * s.height)
            if width < max_spec.width or height < max_spec.height:
                result["recommendations"].append(
                    f"Consider using a higher resolution image ({max_spec.width}x{max_spec.height} recommended)"
                )

            result["valid"] = len(result["issues"]) == 0

    except Exception as e:
        result["issues"].append(f"Error reading image: {str(e)}")

    return result


def generate_product_variants(
    product_name: str,
    channel: str,
    image_field: str = "image",
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate variants for a product's image.

    Args:
        product_name: Product Variant or Product Master name
        channel: Target channel
        image_field: Field name containing the image URL
        output_dir: Optional output directory

    Returns:
        Generation result dictionary
    """
    import frappe

    # Try Product Variant first, then Product Master
    for doctype in ["Product Variant", "Product Master"]:
        try:
            doc = frappe.get_doc(doctype, product_name)
            image_url = doc.get(image_field)
            if image_url:
                return generate_channel_variants(
                    source_path=image_url,
                    channel=channel,
                    product_id=product_name,
                    output_dir=output_dir,
                )
        except frappe.DoesNotExistError:
            continue

    return {
        "success": False,
        "error": f"Product not found or no image: {product_name}",
    }


# =============================================================================
# Helper Functions
# =============================================================================

def _resolve_file_path(file_path: str) -> str:
    """Resolve a Frappe file URL or path to absolute filesystem path."""
    if file_path.startswith("/files/") or file_path.startswith("/private/files/"):
        try:
            import frappe
            site_path = frappe.get_site_path()
            if file_path.startswith("/private/"):
                return os.path.join(site_path, file_path.lstrip("/"))
            else:
                return os.path.join(site_path, "public", file_path.lstrip("/"))
        except Exception:
            return file_path
    return file_path


def _correct_orientation(img):
    """Correct image orientation based on EXIF data."""
    try:
        from PIL import ExifTags

        for orientation in ExifTags.TAGS.keys():
            if ExifTags.TAGS[orientation] == "Orientation":
                break

        exif = img._getexif()
        if exif is None:
            return img

        exif_orientation = exif.get(orientation)

        if exif_orientation == 3:
            img = img.rotate(180, expand=True)
        elif exif_orientation == 6:
            img = img.rotate(270, expand=True)
        elif exif_orientation == 8:
            img = img.rotate(90, expand=True)

    except (AttributeError, KeyError, TypeError):
        pass

    return img


def _get_extension_for_format(format: ImageFormat) -> str:
    """Get file extension for image format."""
    extensions = {
        ImageFormat.JPEG: ".jpg",
        ImageFormat.PNG: ".png",
        ImageFormat.WEBP: ".webp",
        ImageFormat.GIF: ".gif",
    }
    return extensions.get(format, ".jpg")


def _format_file_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def _log_error(message: str, context: Optional[str]):
    """Log error to Frappe error log if available."""
    try:
        import frappe

        title = "PIM Image Variants Error"
        if context:
            title = f"{title} - {context}"
        frappe.log_error(message=message, title=title)
    except Exception:
        pass


# =============================================================================
# Background Job Handlers
# =============================================================================

def _generate_variants_job(
    source_path: str,
    channel: str,
    product_id: Optional[str] = None,
    spec_names: Optional[List[str]] = None,
    output_dir: Optional[str] = None,
):
    """Background job for generating variants."""
    service = ImageVariantsService()
    result = service.generate_variants(
        source_path=source_path,
        channel=channel,
        product_id=product_id,
        spec_names=spec_names,
        output_dir=output_dir,
    )

    # Log result
    try:
        import frappe
        frappe.log_error(
            message=f"Variants generated: {result.success_count} success, {result.failed_count} failed",
            title=f"Image Variants Job - {product_id or source_path}"
        )
    except Exception:
        pass


def _generate_multi_channel_job(
    source_path: str,
    channels: List[str],
    product_id: Optional[str] = None,
    output_dir: Optional[str] = None,
):
    """Background job for multi-channel variant generation."""
    service = ImageVariantsService()
    results = service.generate_for_multiple_channels(
        source_path=source_path,
        channels=channels,
        product_id=product_id,
        output_dir=output_dir,
    )

    # Log result
    try:
        import frappe
        success_count = sum(1 for vs in results.values() if vs.status == VariantStatus.COMPLETED)
        frappe.log_error(
            message=f"Multi-channel variants: {success_count}/{len(channels)} channels completed",
            title=f"Multi-Channel Image Variants - {product_id or source_path}"
        )
    except Exception:
        pass


def _batch_generate_job(
    images: List[Dict[str, Any]],
    channel: str,
    output_dir: Optional[str] = None,
):
    """Background job for batch variant generation."""
    service = ImageVariantsService()
    result = service.batch_generate(
        images=images,
        channel=channel,
        output_dir=output_dir,
    )

    # Log result
    try:
        import frappe
        frappe.log_error(
            message=f"Batch complete: {result.success_count} success, {result.failed_count} failed",
            title=f"Batch Image Variants - {channel}"
        )
    except Exception:
        pass


# =============================================================================
# Frappe API Wrappers
# =============================================================================

def _wrap_for_whitelist():
    """Wrap functions for Frappe whitelist at runtime."""
    import frappe

    functions = [
        "generate_channel_variants",
        "generate_multi_channel_variants",
        "batch_generate_variants",
        "get_channel_specs",
        "list_available_channels",
        "get_variant_specs",
        "validate_image_for_channel",
        "generate_product_variants",
    ]

    module = __import__(__name__)
    for name in __name__.split('.')[1:]:
        module = getattr(module, name)

    for func_name in functions:
        func = getattr(module, func_name)
        if not getattr(func, "_whitelisted", False):
            whitelisted = frappe.whitelist()(func)
            setattr(module, func_name, whitelisted)


# Apply whitelist decorators when module is loaded in Frappe context
try:
    _wrap_for_whitelist()
except Exception:
    pass  # Not in Frappe context
