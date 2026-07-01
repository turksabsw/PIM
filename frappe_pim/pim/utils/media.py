"""Product Media Processing Utilities

This module provides image processing functions for the PIM application
using Pillow (PIL) for image manipulation. Features include:
- Image processing and optimization for product images
- Thumbnail generation with configurable sizes
- WebP format conversion for web optimization
- Large file handling via background jobs

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).

Requirements:
    - Pillow>=10.0.0
    - libwebp-dev (system package for WebP support)
"""

import io
import os
from typing import Optional, Tuple, Dict, Any, Union

# Default configuration
DEFAULT_THUMBNAIL_SIZES = {
    "small": (150, 150),
    "medium": (300, 300),
    "large": (600, 600),
}

DEFAULT_QUALITY = 85
DEFAULT_WEBP_QUALITY = 80
MAX_DIMENSION = 2048
LARGE_FILE_THRESHOLD = 10 * 1024 * 1024  # 10MB


def process_product_image(
    file_path: str,
    product_name: Optional[str] = None,
    max_dimension: int = MAX_DIMENSION,
    quality: int = DEFAULT_QUALITY,
    generate_thumbnails: bool = True,
    convert_webp: bool = True,
    async_processing: bool = False,
) -> Dict[str, Any]:
    """Process a product image with optimization and format conversion.

    This is the main entry point for processing product images. It handles:
    - Image resizing if dimensions exceed max_dimension
    - Automatic orientation correction (EXIF)
    - Optional thumbnail generation
    - Optional WebP conversion
    - Background processing for large files

    Args:
        file_path: Path to the image file (can be absolute or Frappe file URL)
        product_name: Name of the product (for logging and file naming)
        max_dimension: Maximum width/height for the processed image
        quality: JPEG/PNG quality (1-100)
        generate_thumbnails: Whether to generate thumbnail versions
        convert_webp: Whether to create WebP version
        async_processing: Force background job for processing

    Returns:
        dict: Processing result containing:
            - success: bool indicating if processing succeeded
            - original_path: Path to original file
            - processed_path: Path to processed file (if modified)
            - thumbnails: Dict of thumbnail paths by size name
            - webp_path: Path to WebP version (if created)
            - error: Error message (if failed)

    Example:
        >>> result = process_product_image('/path/to/image.jpg', 'PROD-001')
        >>> result['thumbnails']['medium']
        '/path/to/image_medium.jpg'
    """
    try:
        from PIL import Image
    except ImportError:
        return {
            "success": False,
            "error": "Pillow library not installed. Run: pip install Pillow",
            "original_path": file_path,
        }

    result = {
        "success": False,
        "original_path": file_path,
        "processed_path": None,
        "thumbnails": {},
        "webp_path": None,
        "error": None,
    }

    try:
        # Resolve Frappe file path if needed
        resolved_path = _resolve_file_path(file_path)

        if not os.path.exists(resolved_path):
            result["error"] = f"File not found: {resolved_path}"
            return result

        # Check file size for async processing decision
        file_size = os.path.getsize(resolved_path)
        if file_size > LARGE_FILE_THRESHOLD and not async_processing:
            # Enqueue for background processing
            return _enqueue_image_processing(
                file_path=file_path,
                product_name=product_name,
                max_dimension=max_dimension,
                quality=quality,
                generate_thumbnails=generate_thumbnails,
                convert_webp=convert_webp,
            )

        # Open and process image
        with Image.open(resolved_path) as img:
            # Correct orientation from EXIF
            img = _correct_orientation(img)

            # Get original format
            original_format = img.format or _get_format_from_extension(resolved_path)

            # Convert to RGB if necessary (for JPEG/WebP compatibility)
            if img.mode in ("RGBA", "P"):
                # Preserve alpha for PNG, convert to RGB for JPEG
                if original_format.upper() == "JPEG":
                    img = img.convert("RGB")
            elif img.mode != "RGB":
                img = img.convert("RGB")

            # Resize if larger than max_dimension
            processed_img = img
            if max(img.size) > max_dimension:
                processed_img = _resize_preserving_aspect(img, max_dimension)
                # Save processed image
                processed_path = _get_processed_path(resolved_path)
                _save_image(processed_img, processed_path, quality, original_format)
                result["processed_path"] = processed_path
            else:
                # No resize needed, use original
                result["processed_path"] = resolved_path
                processed_img = img.copy()

            # Generate thumbnails
            if generate_thumbnails:
                result["thumbnails"] = _generate_all_thumbnails(
                    processed_img, resolved_path, quality, original_format
                )

            # Convert to WebP
            if convert_webp:
                webp_path = convert_to_webp(
                    result["processed_path"] or resolved_path,
                    quality=DEFAULT_WEBP_QUALITY,
                )
                if webp_path:
                    result["webp_path"] = webp_path

            result["success"] = True

    except Exception as e:
        result["error"] = str(e)
        _log_error(f"Error processing image {file_path}: {e}", product_name)

    return result


def generate_thumbnail(
    source_path: str,
    size: Union[str, Tuple[int, int]] = "medium",
    quality: int = DEFAULT_QUALITY,
    output_path: Optional[str] = None,
) -> Optional[str]:
    """Generate a thumbnail from an image file.

    Creates a resized version of an image that fits within the specified
    dimensions while preserving aspect ratio. Uses PIL's thumbnail method
    for high-quality downscaling.

    Args:
        source_path: Path to the source image file
        size: Either a preset name ('small', 'medium', 'large') or
              a tuple of (width, height) dimensions
        quality: Output quality (1-100)
        output_path: Optional custom output path. If not provided,
                     a path is generated based on source and size.

    Returns:
        str: Path to the generated thumbnail, or None if failed

    Example:
        >>> generate_thumbnail('/path/to/image.jpg', 'small')
        '/path/to/image_small.jpg'
        >>> generate_thumbnail('/path/to/image.jpg', (200, 200))
        '/path/to/image_200x200.jpg'
    """
    try:
        from PIL import Image
    except ImportError:
        _log_error("Pillow library not installed", None)
        return None

    try:
        # Resolve size
        if isinstance(size, str):
            dimensions = DEFAULT_THUMBNAIL_SIZES.get(size)
            if not dimensions:
                _log_error(f"Unknown thumbnail size: {size}", None)
                return None
            size_name = size
        else:
            dimensions = size
            size_name = f"{dimensions[0]}x{dimensions[1]}"

        # Resolve source path
        resolved_path = _resolve_file_path(source_path)

        if not os.path.exists(resolved_path):
            _log_error(f"Source file not found: {resolved_path}", None)
            return None

        # Determine output path
        if output_path is None:
            output_path = _get_thumbnail_path(resolved_path, size_name)

        # Create thumbnail
        with Image.open(resolved_path) as img:
            # Correct orientation
            img = _correct_orientation(img)

            # Get format
            original_format = img.format or _get_format_from_extension(resolved_path)

            # Convert mode if necessary
            if img.mode in ("RGBA", "P") and original_format.upper() == "JPEG":
                img = img.convert("RGB")
            elif img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")

            # Create a copy for thumbnail (thumbnail modifies in place)
            thumb = img.copy()
            thumb.thumbnail(dimensions, Image.Resampling.LANCZOS)

            # Save thumbnail
            _save_image(thumb, output_path, quality, original_format)

        return output_path

    except Exception as e:
        _log_error(f"Error generating thumbnail for {source_path}: {e}", None)
        return None


def convert_to_webp(
    source_path: str,
    quality: int = DEFAULT_WEBP_QUALITY,
    output_path: Optional[str] = None,
    lossless: bool = False,
) -> Optional[str]:
    """Convert an image to WebP format.

    WebP typically provides 25-35% smaller file sizes compared to JPEG/PNG
    while maintaining similar visual quality. This function handles the
    conversion with options for quality and lossless compression.

    Args:
        source_path: Path to the source image file
        quality: WebP quality (1-100). Ignored if lossless=True.
        output_path: Optional custom output path. If not provided,
                     replaces extension with .webp
        lossless: If True, use lossless WebP compression

    Returns:
        str: Path to the generated WebP file, or None if failed

    Example:
        >>> convert_to_webp('/path/to/image.jpg')
        '/path/to/image.webp'
        >>> convert_to_webp('/path/to/image.png', lossless=True)
        '/path/to/image.webp'
    """
    try:
        from PIL import Image
    except ImportError:
        _log_error("Pillow library not installed", None)
        return None

    try:
        # Resolve source path
        resolved_path = _resolve_file_path(source_path)

        if not os.path.exists(resolved_path):
            _log_error(f"Source file not found: {resolved_path}", None)
            return None

        # Determine output path
        if output_path is None:
            base, _ = os.path.splitext(resolved_path)
            output_path = f"{base}.webp"

        # Convert to WebP
        with Image.open(resolved_path) as img:
            # Correct orientation
            img = _correct_orientation(img)

            # Handle transparency
            if img.mode == "RGBA":
                # WebP supports transparency
                pass
            elif img.mode == "P" and "transparency" in img.info:
                # Convert palette with transparency to RGBA
                img = img.convert("RGBA")
            elif img.mode != "RGB":
                img = img.convert("RGB")

            # Save as WebP
            save_kwargs = {
                "format": "WEBP",
                "quality": quality,
                "method": 6,  # Slowest but best compression
            }

            if lossless:
                save_kwargs["lossless"] = True
                del save_kwargs["quality"]

            img.save(output_path, **save_kwargs)

        return output_path

    except Exception as e:
        _log_error(f"Error converting to WebP {source_path}: {e}", None)
        return None


def get_image_info(file_path: str) -> Optional[Dict[str, Any]]:
    """Get metadata information about an image file.

    Extracts image dimensions, format, color mode, and file size
    without loading the full image into memory.

    Args:
        file_path: Path to the image file

    Returns:
        dict: Image information including width, height, format, mode, size
              Returns None if file cannot be read.
    """
    try:
        from PIL import Image
    except ImportError:
        return None

    try:
        resolved_path = _resolve_file_path(file_path)

        if not os.path.exists(resolved_path):
            return None

        file_size = os.path.getsize(resolved_path)

        with Image.open(resolved_path) as img:
            return {
                "width": img.width,
                "height": img.height,
                "format": img.format,
                "mode": img.mode,
                "file_size": file_size,
                "file_size_human": _format_file_size(file_size),
            }

    except Exception:
        return None


def optimize_image(
    source_path: str,
    output_path: Optional[str] = None,
    max_dimension: int = MAX_DIMENSION,
    quality: int = DEFAULT_QUALITY,
) -> Optional[str]:
    """Optimize an image for web delivery.

    Resizes large images, optimizes compression, and strips unnecessary
    metadata for smaller file sizes.

    Args:
        source_path: Path to the source image
        output_path: Optional custom output path
        max_dimension: Maximum width or height
        quality: Output quality (1-100)

    Returns:
        str: Path to optimized image, or None if failed
    """
    try:
        from PIL import Image
    except ImportError:
        return None

    try:
        resolved_path = _resolve_file_path(source_path)

        if not os.path.exists(resolved_path):
            return None

        if output_path is None:
            output_path = _get_processed_path(resolved_path)

        with Image.open(resolved_path) as img:
            # Correct orientation
            img = _correct_orientation(img)

            original_format = img.format or _get_format_from_extension(resolved_path)

            # Convert mode if needed
            if img.mode in ("RGBA", "P") and original_format.upper() == "JPEG":
                img = img.convert("RGB")
            elif img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")

            # Resize if needed
            if max(img.size) > max_dimension:
                img = _resize_preserving_aspect(img, max_dimension)

            # Save with optimization
            _save_image(img, output_path, quality, original_format, optimize=True)

        return output_path

    except Exception as e:
        _log_error(f"Error optimizing image {source_path}: {e}", None)
        return None


def process_image(
    source_path: str,
    operations: Optional[Dict[str, Any]] = None,
    output_path: Optional[str] = None,
    quality: int = DEFAULT_QUALITY,
) -> Dict[str, Any]:
    """Process an image with a sequence of operations.

    This is a flexible image processing function that can apply multiple
    operations in sequence. Supported operations include resize, crop,
    rotate, format conversion, and optimization.

    Args:
        source_path: Path to the source image file
        operations: Dictionary of operations to apply. Supported keys:
            - resize: Dict with 'width' and/or 'height', or 'max_dimension'
            - crop: Dict with 'left', 'top', 'right', 'bottom' or 'box' tuple
            - rotate: Degrees to rotate (90, 180, 270)
            - format: Target format ('JPEG', 'PNG', 'WEBP', 'GIF')
            - flip: 'horizontal' or 'vertical'
            - optimize: Boolean to apply optimization
        output_path: Optional custom output path
        quality: Output quality (1-100)

    Returns:
        dict: Processing result containing:
            - success: bool indicating if processing succeeded
            - original_path: Path to original file
            - output_path: Path to processed file
            - original_size: Tuple of (width, height)
            - output_size: Tuple of (width, height)
            - operations_applied: List of operations that were applied
            - error: Error message (if failed)

    Example:
        >>> result = process_image('/path/to/image.jpg', {
        ...     'resize': {'max_dimension': 800},
        ...     'crop': {'left': 10, 'top': 10, 'right': 790, 'bottom': 590},
        ...     'format': 'WEBP'
        ... })
        >>> result['output_path']
        '/path/to/image_processed.webp'
    """
    try:
        from PIL import Image
    except ImportError:
        return {
            "success": False,
            "error": "Pillow library not installed. Run: pip install Pillow",
            "original_path": source_path,
        }

    if operations is None:
        operations = {}

    result = {
        "success": False,
        "original_path": source_path,
        "output_path": None,
        "original_size": None,
        "output_size": None,
        "operations_applied": [],
        "error": None,
    }

    try:
        resolved_path = _resolve_file_path(source_path)

        if not os.path.exists(resolved_path):
            result["error"] = f"File not found: {resolved_path}"
            return result

        with Image.open(resolved_path) as img:
            # Correct orientation
            img = _correct_orientation(img)
            result["original_size"] = img.size

            # Get original format
            original_format = img.format or _get_format_from_extension(resolved_path)
            target_format = operations.get("format", original_format)

            # Apply operations in order
            processed_img = img.copy()

            # Resize operation
            if "resize" in operations:
                resize_opts = operations["resize"]
                if "max_dimension" in resize_opts:
                    max_dim = resize_opts["max_dimension"]
                    if max(processed_img.size) > max_dim:
                        processed_img = _resize_preserving_aspect(processed_img, max_dim)
                        result["operations_applied"].append("resize")
                elif "width" in resize_opts or "height" in resize_opts:
                    processed_img = _resize_to_dimensions(
                        processed_img,
                        resize_opts.get("width"),
                        resize_opts.get("height"),
                        resize_opts.get("preserve_aspect", True),
                    )
                    result["operations_applied"].append("resize")

            # Crop operation
            if "crop" in operations:
                crop_opts = operations["crop"]
                if "box" in crop_opts:
                    box = crop_opts["box"]
                else:
                    box = (
                        crop_opts.get("left", 0),
                        crop_opts.get("top", 0),
                        crop_opts.get("right", processed_img.width),
                        crop_opts.get("bottom", processed_img.height),
                    )
                processed_img = processed_img.crop(box)
                result["operations_applied"].append("crop")

            # Rotate operation
            if "rotate" in operations:
                degrees = operations["rotate"]
                if degrees in (90, 180, 270):
                    processed_img = processed_img.rotate(degrees, expand=True)
                    result["operations_applied"].append("rotate")

            # Flip operation
            if "flip" in operations:
                flip_dir = operations["flip"]
                if flip_dir == "horizontal":
                    processed_img = processed_img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                    result["operations_applied"].append("flip_horizontal")
                elif flip_dir == "vertical":
                    processed_img = processed_img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
                    result["operations_applied"].append("flip_vertical")

            # Handle color mode conversion for format compatibility
            if target_format.upper() == "JPEG" and processed_img.mode in ("RGBA", "P"):
                processed_img = processed_img.convert("RGB")
            elif processed_img.mode not in ("RGB", "RGBA", "L"):
                processed_img = processed_img.convert("RGB")

            # Determine output path
            if output_path is None:
                base, _ = os.path.splitext(resolved_path)
                ext = _get_extension_from_format(target_format)
                output_path = f"{base}_processed{ext}"

            # Save processed image
            result["output_size"] = processed_img.size
            optimize = operations.get("optimize", True)
            _save_image(processed_img, output_path, quality, target_format, optimize)
            result["output_path"] = output_path

            # Format conversion counts as an operation if different
            if target_format.upper() != original_format.upper():
                result["operations_applied"].append(f"convert_to_{target_format.lower()}")

            result["success"] = True

    except Exception as e:
        result["error"] = str(e)
        _log_error(f"Error processing image {source_path}: {e}", None)

    return result


def convert_format(
    source_path: str,
    target_format: str,
    output_path: Optional[str] = None,
    quality: int = DEFAULT_QUALITY,
    preserve_transparency: bool = True,
) -> Optional[str]:
    """Convert an image to a different format.

    Converts images between supported formats (JPEG, PNG, WEBP, GIF, BMP, TIFF).
    Handles color mode conversion automatically for format compatibility.

    Args:
        source_path: Path to the source image file
        target_format: Target format ('JPEG', 'PNG', 'WEBP', 'GIF', 'BMP', 'TIFF')
        output_path: Optional custom output path. If not provided,
                     the source extension is replaced with target format extension.
        quality: Output quality (1-100). Applies to JPEG and WEBP.
        preserve_transparency: If True, converts to RGBA for formats that support
                               transparency. If False, converts to RGB.

    Returns:
        str: Path to the converted image file, or None if failed

    Example:
        >>> convert_format('/path/to/image.png', 'JPEG')
        '/path/to/image.jpg'
        >>> convert_format('/path/to/image.jpg', 'WEBP', quality=90)
        '/path/to/image.webp'
    """
    try:
        from PIL import Image
    except ImportError:
        _log_error("Pillow library not installed", None)
        return None

    # Normalize format name
    target_format = target_format.upper()
    supported_formats = {"JPEG", "JPG", "PNG", "WEBP", "GIF", "BMP", "TIFF", "TIF"}

    if target_format not in supported_formats:
        _log_error(f"Unsupported target format: {target_format}", None)
        return None

    # Normalize JPG to JPEG
    if target_format == "JPG":
        target_format = "JPEG"
    elif target_format == "TIF":
        target_format = "TIFF"

    try:
        resolved_path = _resolve_file_path(source_path)

        if not os.path.exists(resolved_path):
            _log_error(f"Source file not found: {resolved_path}", None)
            return None

        # Determine output path
        if output_path is None:
            base, _ = os.path.splitext(resolved_path)
            ext = _get_extension_from_format(target_format)
            output_path = f"{base}{ext}"

        with Image.open(resolved_path) as img:
            # Correct orientation
            img = _correct_orientation(img)

            # Handle color mode for format compatibility
            if target_format == "JPEG":
                # JPEG doesn't support transparency
                if img.mode in ("RGBA", "P"):
                    # Create white background for transparency
                    if img.mode == "P":
                        img = img.convert("RGBA")
                    background = Image.new("RGB", img.size, (255, 255, 255))
                    background.paste(img, mask=img.split()[3])  # Use alpha channel as mask
                    img = background
                elif img.mode != "RGB":
                    img = img.convert("RGB")
            elif target_format in ("PNG", "WEBP", "GIF"):
                # These formats support transparency
                if preserve_transparency and img.mode == "P" and "transparency" in img.info:
                    img = img.convert("RGBA")
                elif img.mode not in ("RGB", "RGBA", "P", "L"):
                    img = img.convert("RGB")
            else:
                # BMP, TIFF - convert to RGB if necessary
                if img.mode not in ("RGB", "RGBA", "L"):
                    img = img.convert("RGB")

            # Prepare save options
            save_kwargs = {"format": target_format}

            if target_format == "JPEG":
                save_kwargs["quality"] = quality
                save_kwargs["optimize"] = True
                save_kwargs["progressive"] = True
            elif target_format == "WEBP":
                save_kwargs["quality"] = quality
                save_kwargs["method"] = 6
            elif target_format == "PNG":
                save_kwargs["optimize"] = True

            # Ensure directory exists
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

            img.save(output_path, **save_kwargs)

        return output_path

    except Exception as e:
        _log_error(f"Error converting format {source_path} to {target_format}: {e}", None)
        return None


def crop_image(
    source_path: str,
    box: Optional[Tuple[int, int, int, int]] = None,
    left: int = 0,
    top: int = 0,
    right: Optional[int] = None,
    bottom: Optional[int] = None,
    output_path: Optional[str] = None,
    quality: int = DEFAULT_QUALITY,
) -> Optional[str]:
    """Crop an image to specified dimensions.

    Extracts a rectangular region from an image. Can specify the crop
    region either as a box tuple or individual coordinates.

    Args:
        source_path: Path to the source image file
        box: Optional tuple of (left, top, right, bottom) coordinates.
             If provided, overrides individual coordinate arguments.
        left: Left edge x-coordinate (default: 0)
        top: Top edge y-coordinate (default: 0)
        right: Right edge x-coordinate (default: image width)
        bottom: Bottom edge y-coordinate (default: image height)
        output_path: Optional custom output path
        quality: Output quality (1-100)

    Returns:
        str: Path to the cropped image, or None if failed

    Example:
        >>> crop_image('/path/to/image.jpg', left=100, top=100, right=500, bottom=400)
        '/path/to/image_cropped.jpg'
        >>> crop_image('/path/to/image.jpg', box=(100, 100, 500, 400))
        '/path/to/image_cropped.jpg'
    """
    try:
        from PIL import Image
    except ImportError:
        _log_error("Pillow library not installed", None)
        return None

    try:
        resolved_path = _resolve_file_path(source_path)

        if not os.path.exists(resolved_path):
            _log_error(f"Source file not found: {resolved_path}", None)
            return None

        with Image.open(resolved_path) as img:
            # Correct orientation
            img = _correct_orientation(img)

            # Get format
            original_format = img.format or _get_format_from_extension(resolved_path)

            # Determine crop box
            if box is None:
                # Use individual coordinates
                crop_right = right if right is not None else img.width
                crop_bottom = bottom if bottom is not None else img.height
                box = (left, top, crop_right, crop_bottom)

            # Validate box coordinates
            if box[0] < 0 or box[1] < 0:
                _log_error("Crop coordinates cannot be negative", None)
                return None
            if box[2] > img.width or box[3] > img.height:
                _log_error("Crop coordinates exceed image dimensions", None)
                return None
            if box[0] >= box[2] or box[1] >= box[3]:
                _log_error("Invalid crop box: left >= right or top >= bottom", None)
                return None

            # Perform crop
            cropped = img.crop(box)

            # Handle color mode for format
            if original_format.upper() == "JPEG" and cropped.mode in ("RGBA", "P"):
                cropped = cropped.convert("RGB")
            elif cropped.mode not in ("RGB", "RGBA", "L"):
                cropped = cropped.convert("RGB")

            # Determine output path
            if output_path is None:
                base, ext = os.path.splitext(resolved_path)
                output_path = f"{base}_cropped{ext}"

            # Save cropped image
            _save_image(cropped, output_path, quality, original_format)

        return output_path

    except Exception as e:
        _log_error(f"Error cropping image {source_path}: {e}", None)
        return None


def resize_image(
    source_path: str,
    width: Optional[int] = None,
    height: Optional[int] = None,
    max_dimension: Optional[int] = None,
    preserve_aspect: bool = True,
    output_path: Optional[str] = None,
    quality: int = DEFAULT_QUALITY,
) -> Optional[str]:
    """Resize an image to specified dimensions.

    Provides flexible resizing options including fixed dimensions,
    maximum dimension constraints, and aspect ratio preservation.

    Args:
        source_path: Path to the source image file
        width: Target width in pixels. If None and height is set,
               width is calculated to preserve aspect ratio.
        height: Target height in pixels. If None and width is set,
                height is calculated to preserve aspect ratio.
        max_dimension: Maximum width or height. If set, image is scaled
                       to fit within this constraint.
        preserve_aspect: If True, maintains original aspect ratio.
                         If False, image is stretched to exact dimensions.
        output_path: Optional custom output path
        quality: Output quality (1-100)

    Returns:
        str: Path to the resized image, or None if failed

    Example:
        >>> resize_image('/path/to/image.jpg', width=800)
        '/path/to/image_resized.jpg'
        >>> resize_image('/path/to/image.jpg', max_dimension=1024)
        '/path/to/image_resized.jpg'
        >>> resize_image('/path/to/image.jpg', width=400, height=300, preserve_aspect=False)
        '/path/to/image_resized.jpg'
    """
    try:
        from PIL import Image
    except ImportError:
        _log_error("Pillow library not installed", None)
        return None

    try:
        resolved_path = _resolve_file_path(source_path)

        if not os.path.exists(resolved_path):
            _log_error(f"Source file not found: {resolved_path}", None)
            return None

        with Image.open(resolved_path) as img:
            # Correct orientation
            img = _correct_orientation(img)

            # Get format
            original_format = img.format or _get_format_from_extension(resolved_path)
            original_width, original_height = img.size

            # Determine target dimensions
            if max_dimension is not None:
                # Use max_dimension constraint
                if max(img.size) <= max_dimension:
                    # Image already within constraints
                    if output_path is None:
                        return resolved_path
                resized = _resize_preserving_aspect(img, max_dimension)
            elif width is not None or height is not None:
                # Use explicit width/height
                resized = _resize_to_dimensions(img, width, height, preserve_aspect)
            else:
                _log_error("No resize dimensions specified", None)
                return None

            # Handle color mode for format
            if original_format.upper() == "JPEG" and resized.mode in ("RGBA", "P"):
                resized = resized.convert("RGB")
            elif resized.mode not in ("RGB", "RGBA", "L"):
                resized = resized.convert("RGB")

            # Determine output path
            if output_path is None:
                base, ext = os.path.splitext(resolved_path)
                output_path = f"{base}_resized{ext}"

            # Save resized image
            _save_image(resized, output_path, quality, original_format)

        return output_path

    except Exception as e:
        _log_error(f"Error resizing image {source_path}: {e}", None)
        return None


def smart_crop(
    source_path: str,
    target_width: int,
    target_height: int,
    gravity: str = "center",
    output_path: Optional[str] = None,
    quality: int = DEFAULT_QUALITY,
) -> Optional[str]:
    """Smart crop an image to fit exact dimensions.

    Crops an image to fit the target dimensions while maintaining the
    most important content based on the gravity setting.

    Args:
        source_path: Path to the source image file
        target_width: Desired width in pixels
        target_height: Desired height in pixels
        gravity: Crop anchor point. Options:
                 'center' - Crop from center (default)
                 'north' - Crop from top center
                 'south' - Crop from bottom center
                 'east' - Crop from right center
                 'west' - Crop from left center
                 'northeast' - Crop from top-right
                 'northwest' - Crop from top-left
                 'southeast' - Crop from bottom-right
                 'southwest' - Crop from bottom-left
        output_path: Optional custom output path
        quality: Output quality (1-100)

    Returns:
        str: Path to the cropped image, or None if failed

    Example:
        >>> smart_crop('/path/to/image.jpg', 400, 300, gravity='center')
        '/path/to/image_smart_cropped.jpg'
    """
    try:
        from PIL import Image
    except ImportError:
        _log_error("Pillow library not installed", None)
        return None

    try:
        resolved_path = _resolve_file_path(source_path)

        if not os.path.exists(resolved_path):
            _log_error(f"Source file not found: {resolved_path}", None)
            return None

        with Image.open(resolved_path) as img:
            # Correct orientation
            img = _correct_orientation(img)

            # Get format
            original_format = img.format or _get_format_from_extension(resolved_path)

            # First, resize to cover the target dimensions
            source_ratio = img.width / img.height
            target_ratio = target_width / target_height

            if source_ratio > target_ratio:
                # Image is wider than target - resize by height, crop width
                new_height = target_height
                new_width = int(img.width * (target_height / img.height))
            else:
                # Image is taller than target - resize by width, crop height
                new_width = target_width
                new_height = int(img.height * (target_width / img.width))

            # Use thumbnail for memory-efficient resize
            resized = img.copy()
            resized.thumbnail((new_width, new_height), Image.Resampling.LANCZOS)

            # Recalculate after thumbnail (thumbnail may not achieve exact size)
            actual_width, actual_height = resized.size

            # Calculate crop box based on gravity
            crop_box = _calculate_gravity_crop(
                actual_width, actual_height, target_width, target_height, gravity
            )

            # Perform crop
            cropped = resized.crop(crop_box)

            # Handle color mode for format
            if original_format.upper() == "JPEG" and cropped.mode in ("RGBA", "P"):
                cropped = cropped.convert("RGB")
            elif cropped.mode not in ("RGB", "RGBA", "L"):
                cropped = cropped.convert("RGB")

            # Determine output path
            if output_path is None:
                base, ext = os.path.splitext(resolved_path)
                output_path = f"{base}_smart_cropped{ext}"

            # Save cropped image
            _save_image(cropped, output_path, quality, original_format)

        return output_path

    except Exception as e:
        _log_error(f"Error smart cropping image {source_path}: {e}", None)
        return None


# Private helper functions

def _resize_to_dimensions(
    img,
    width: Optional[int] = None,
    height: Optional[int] = None,
    preserve_aspect: bool = True,
):
    """Resize image to specified width and/or height.

    Args:
        img: PIL Image object
        width: Target width (None to calculate from height)
        height: Target height (None to calculate from width)
        preserve_aspect: Whether to preserve aspect ratio

    Returns:
        Resized PIL Image object
    """
    from PIL import Image

    original_width, original_height = img.size

    if preserve_aspect:
        if width and height:
            # Fit within both constraints
            width_ratio = width / original_width
            height_ratio = height / original_height
            ratio = min(width_ratio, height_ratio)
            new_width = int(original_width * ratio)
            new_height = int(original_height * ratio)
        elif width:
            ratio = width / original_width
            new_width = width
            new_height = int(original_height * ratio)
        elif height:
            ratio = height / original_height
            new_width = int(original_width * ratio)
            new_height = height
        else:
            return img
    else:
        # Stretch to exact dimensions
        new_width = width if width else original_width
        new_height = height if height else original_height

    return img.resize((new_width, new_height), Image.Resampling.LANCZOS)


def _get_extension_from_format(format_name: str) -> str:
    """Get file extension from PIL format name."""
    extension_map = {
        "JPEG": ".jpg",
        "PNG": ".png",
        "WEBP": ".webp",
        "GIF": ".gif",
        "BMP": ".bmp",
        "TIFF": ".tiff",
    }
    return extension_map.get(format_name.upper(), ".jpg")


def _calculate_gravity_crop(
    image_width: int,
    image_height: int,
    target_width: int,
    target_height: int,
    gravity: str,
) -> Tuple[int, int, int, int]:
    """Calculate crop box coordinates based on gravity setting.

    Args:
        image_width: Current image width
        image_height: Current image height
        target_width: Desired crop width
        target_height: Desired crop height
        gravity: Anchor point for crop

    Returns:
        Tuple of (left, top, right, bottom) coordinates
    """
    # Calculate available space for cropping
    x_extra = max(0, image_width - target_width)
    y_extra = max(0, image_height - target_height)

    # Calculate offsets based on gravity
    gravity = gravity.lower()

    if gravity in ("center", "centre"):
        x_offset = x_extra // 2
        y_offset = y_extra // 2
    elif gravity == "north":
        x_offset = x_extra // 2
        y_offset = 0
    elif gravity == "south":
        x_offset = x_extra // 2
        y_offset = y_extra
    elif gravity == "east":
        x_offset = x_extra
        y_offset = y_extra // 2
    elif gravity == "west":
        x_offset = 0
        y_offset = y_extra // 2
    elif gravity == "northeast":
        x_offset = x_extra
        y_offset = 0
    elif gravity == "northwest":
        x_offset = 0
        y_offset = 0
    elif gravity == "southeast":
        x_offset = x_extra
        y_offset = y_extra
    elif gravity == "southwest":
        x_offset = 0
        y_offset = y_extra
    else:
        # Default to center
        x_offset = x_extra // 2
        y_offset = y_extra // 2

    # Ensure we don't exceed image boundaries
    crop_width = min(target_width, image_width)
    crop_height = min(target_height, image_height)

    return (x_offset, y_offset, x_offset + crop_width, y_offset + crop_height)


def _resolve_file_path(file_path: str) -> str:
    """Resolve a Frappe file URL or path to an absolute filesystem path."""
    if file_path.startswith("/files/") or file_path.startswith("/private/files/"):
        # Frappe file URL - resolve to actual path
        try:
            import frappe
            site_path = frappe.get_site_path()
            if file_path.startswith("/private/"):
                return os.path.join(site_path, file_path.lstrip("/"))
            else:
                return os.path.join(site_path, "public", file_path.lstrip("/"))
        except Exception:
            # Return as-is if Frappe not available
            return file_path
    return file_path


def _correct_orientation(img):
    """Correct image orientation based on EXIF data."""
    try:
        from PIL import ExifTags

        # Get EXIF orientation tag
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
        # No EXIF data or orientation not found
        pass

    return img


def _resize_preserving_aspect(img, max_dimension: int):
    """Resize image to fit within max_dimension while preserving aspect ratio."""
    from PIL import Image

    width, height = img.size

    if width > height:
        new_width = max_dimension
        new_height = int((height / width) * max_dimension)
    else:
        new_height = max_dimension
        new_width = int((width / height) * max_dimension)

    return img.resize((new_width, new_height), Image.Resampling.LANCZOS)


def _get_format_from_extension(file_path: str) -> str:
    """Get PIL format name from file extension."""
    ext = os.path.splitext(file_path)[1].lower()
    format_map = {
        ".jpg": "JPEG",
        ".jpeg": "JPEG",
        ".png": "PNG",
        ".gif": "GIF",
        ".webp": "WEBP",
        ".bmp": "BMP",
        ".tiff": "TIFF",
        ".tif": "TIFF",
    }
    return format_map.get(ext, "JPEG")


def _save_image(
    img,
    output_path: str,
    quality: int,
    format_name: str,
    optimize: bool = True,
):
    """Save image with appropriate settings for format."""
    # Ensure directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    save_kwargs = {
        "format": format_name,
        "quality": quality,
    }

    if format_name.upper() == "JPEG":
        save_kwargs["optimize"] = optimize
        save_kwargs["progressive"] = True
    elif format_name.upper() == "PNG":
        save_kwargs["optimize"] = optimize
        # Remove quality for PNG as it doesn't use it
        del save_kwargs["quality"]

    img.save(output_path, **save_kwargs)


def _get_processed_path(original_path: str) -> str:
    """Generate path for processed image."""
    base, ext = os.path.splitext(original_path)
    return f"{base}_processed{ext}"


def _get_thumbnail_path(original_path: str, size_name: str) -> str:
    """Generate path for thumbnail image."""
    base, ext = os.path.splitext(original_path)
    return f"{base}_{size_name}{ext}"


def _generate_all_thumbnails(
    img,
    original_path: str,
    quality: int,
    format_name: str,
) -> Dict[str, str]:
    """Generate all default thumbnail sizes."""
    from PIL import Image

    thumbnails = {}

    for size_name, dimensions in DEFAULT_THUMBNAIL_SIZES.items():
        try:
            thumb_path = _get_thumbnail_path(original_path, size_name)

            # Create copy and resize
            thumb = img.copy()
            thumb.thumbnail(dimensions, Image.Resampling.LANCZOS)

            # Save
            _save_image(thumb, thumb_path, quality, format_name)
            thumbnails[size_name] = thumb_path

        except Exception as e:
            _log_error(f"Error generating {size_name} thumbnail: {e}", None)

    return thumbnails


def _enqueue_image_processing(**kwargs) -> Dict[str, Any]:
    """Enqueue image processing as a background job."""
    try:
        import frappe

        frappe.enqueue(
            "frappe_pim.pim.utils.media.process_product_image",
            queue="long",
            timeout=600,
            async_processing=True,  # Prevent recursive enqueue
            **kwargs,
        )

        return {
            "success": True,
            "queued": True,
            "message": "Image processing queued for background execution",
            "original_path": kwargs.get("file_path"),
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to queue image processing: {e}",
            "original_path": kwargs.get("file_path"),
        }


def _log_error(message: str, product_name: Optional[str]):
    """Log error to Frappe error log if available."""
    try:
        import frappe

        title = "PIM Media Processing Error"
        if product_name:
            title = f"{title} - {product_name}"

        frappe.log_error(message=message, title=title)
    except Exception:
        # Frappe not available, silently ignore
        pass


def _format_file_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


# Frappe-specific functions for Product Media integration

def process_product_media_on_upload(doc, method=None):
    """Hook function for Product Media document upload.

    This function can be called from doc_events to automatically
    process images when they are attached to products.

    Args:
        doc: The Product Media document
        method: Hook method name (unused)
    """
    try:
        import frappe

        file_url = doc.get("file_url") or doc.get("image")
        if not file_url:
            return

        # Only process image types
        if not _is_image_file(file_url):
            return

        # Process the image
        result = process_product_image(
            file_path=file_url,
            product_name=doc.get("parent"),
            generate_thumbnails=True,
            convert_webp=True,
        )

        if result.get("success"):
            # Store thumbnail paths if the doctype supports it
            if result.get("thumbnails"):
                doc.thumbnail_small = result["thumbnails"].get("small")
                doc.thumbnail_medium = result["thumbnails"].get("medium")
                doc.thumbnail_large = result["thumbnails"].get("large")

            if result.get("webp_path"):
                doc.webp_url = result["webp_path"]

    except Exception as e:
        frappe.log_error(
            message=f"Error processing product media {doc.name}: {e}",
            title="PIM Media Processing Error"
        )


def _is_image_file(file_path: str) -> bool:
    """Check if file is an image based on extension."""
    image_extensions = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif"}
    ext = os.path.splitext(file_path)[1].lower()
    return ext in image_extensions
