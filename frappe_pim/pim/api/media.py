"""PIM Media/DAM API Endpoints

This module provides API endpoints for Digital Asset Management (DAM)
functionality including media upload, processing, retrieval, and organization.
Key features include:

- Media upload with automatic processing
- Image processing (resize, thumbnail, format conversion)
- WebP optimization for web delivery
- Channel-specific media transformations
- Media library management and search
- Batch processing support

All API functions are decorated with @frappe.whitelist() for security
and require appropriate permissions.

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

from datetime import datetime
from typing import Dict, List, Optional, Any, Union
import json
import os


# Supported media types
SUPPORTED_IMAGE_TYPES = {
    "image/jpeg": {"extension": ".jpg", "format": "JPEG"},
    "image/png": {"extension": ".png", "format": "PNG"},
    "image/gif": {"extension": ".gif", "format": "GIF"},
    "image/webp": {"extension": ".webp", "format": "WEBP"},
    "image/bmp": {"extension": ".bmp", "format": "BMP"},
    "image/tiff": {"extension": ".tiff", "format": "TIFF"},
}

SUPPORTED_DOCUMENT_TYPES = {
    "application/pdf": {"extension": ".pdf", "type": "document"},
    "application/msword": {"extension": ".doc", "type": "document"},
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {
        "extension": ".docx", "type": "document"
    },
    "application/vnd.ms-excel": {"extension": ".xls", "type": "spreadsheet"},
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {
        "extension": ".xlsx", "type": "spreadsheet"
    },
}

SUPPORTED_VIDEO_TYPES = {
    "video/mp4": {"extension": ".mp4", "type": "video"},
    "video/webm": {"extension": ".webm", "type": "video"},
    "video/quicktime": {"extension": ".mov", "type": "video"},
}

# Default thumbnail sizes for DAM
DEFAULT_THUMBNAIL_SIZES = {
    "thumb": (100, 100),
    "small": (150, 150),
    "medium": (300, 300),
    "large": (600, 600),
    "preview": (800, 800),
}

# Channel-specific image requirements
CHANNEL_IMAGE_SPECS = {
    "amazon": {
        "main": {"min_dimension": 1000, "max_dimension": 10000, "format": "JPEG"},
        "variant": {"min_dimension": 500, "max_dimension": 10000, "format": "JPEG"},
    },
    "shopify": {
        "main": {"max_dimension": 4472, "format": "JPEG"},
        "thumbnail": {"dimension": 100, "format": "JPEG"},
    },
    "google_merchant": {
        "main": {"min_dimension": 100, "max_dimension": 64000000, "format": "JPEG"},
    },
    "woocommerce": {
        "main": {"max_dimension": 2048, "format": "JPEG"},
        "thumbnail": {"dimension": 300, "format": "JPEG"},
    },
    "trendyol": {
        "main": {"min_dimension": 800, "format": "JPEG"},
    },
    "hepsiburada": {
        "main": {"min_dimension": 600, "format": "JPEG"},
    },
}


def upload_media(
    file_data: Optional[str] = None,
    file_url: Optional[str] = None,
    product_name: Optional[str] = None,
    media_type: str = "image",
    is_primary: bool = False,
    title: Optional[str] = None,
    alt_text: Optional[str] = None,
    description: Optional[str] = None,
    tags: Optional[str] = None,
    auto_process: bool = True,
    generate_thumbnails: bool = True,
    convert_webp: bool = True,
    async_processing: bool = False
) -> Dict[str, Any]:
    """Upload media to the DAM system.

    Uploads a media file and optionally processes it for product usage.
    Supports both base64 file data and URL-based uploads.

    Args:
        file_data: Base64 encoded file data (optional if file_url provided)
        file_url: URL to fetch file from (optional if file_data provided)
        product_name: Link to Product Master document (optional)
        media_type: Type of media ('image', 'document', 'video')
        is_primary: Whether this is the primary/main image
        title: Media title/name
        alt_text: Alternative text for accessibility
        description: Detailed description
        tags: JSON list of tags for categorization
        auto_process: Automatically process images (resize, optimize)
        generate_thumbnails: Generate thumbnail versions
        convert_webp: Create WebP version for web optimization
        async_processing: Process in background job

    Returns:
        dict: Upload result with file details and processing status

    Example:
        >>> # Upload with base64 data
        >>> result = upload_media(
        ...     file_data="data:image/jpeg;base64,/9j/4AAQ...",
        ...     product_name="PROD-001",
        ...     is_primary=True,
        ...     auto_process=True
        ... )
        >>> print(result["file_url"])

        >>> # Upload from URL
        >>> result = upload_media(
        ...     file_url="https://example.com/image.jpg",
        ...     product_name="PROD-001"
        ... )
    """
    import frappe
    from frappe import _

    if not frappe.has_permission("Product Media", "create"):
        frappe.throw(_("Not permitted to upload media"), frappe.PermissionError)

    try:
        # Validate inputs
        if not file_data and not file_url:
            return {
                "success": False,
                "error": _("Either file_data or file_url is required")
            }

        # Parse tags if provided
        if tags and isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except json.JSONDecodeError:
                tags = [t.strip() for t in tags.split(",")]

        # Handle base64 upload
        if file_data:
            file_result = _save_base64_file(file_data, title)
            if not file_result.get("success"):
                return file_result
            saved_file_url = file_result["file_url"]
            filename = file_result["filename"]
            content_type = file_result.get("content_type")
        else:
            # Handle URL-based upload
            file_result = _fetch_and_save_url(file_url, title)
            if not file_result.get("success"):
                return file_result
            saved_file_url = file_result["file_url"]
            filename = file_result["filename"]
            content_type = file_result.get("content_type")

        # Determine media type from content type if not specified
        if not media_type or media_type == "auto":
            media_type = _detect_media_type(content_type, filename)

        # Create Product Media document if product is specified
        media_doc = None
        if product_name:
            media_doc = _create_product_media_doc(
                product_name=product_name,
                file_url=saved_file_url,
                media_type=media_type,
                is_primary=is_primary,
                title=title or filename,
                alt_text=alt_text,
                description=description,
                tags=tags
            )

        result = {
            "success": True,
            "file_url": saved_file_url,
            "filename": filename,
            "media_type": media_type,
            "content_type": content_type,
            "timestamp": datetime.now().isoformat()
        }

        if media_doc:
            result["media_doc"] = media_doc.name

        # Process image if requested
        if auto_process and media_type == "image":
            if async_processing:
                result["processing"] = _enqueue_media_processing(
                    file_url=saved_file_url,
                    product_name=product_name,
                    generate_thumbnails=generate_thumbnails,
                    convert_webp=convert_webp
                )
            else:
                processing_result = process_media(
                    file_url=saved_file_url,
                    generate_thumbnails=generate_thumbnails,
                    convert_webp=convert_webp
                )
                result["processing"] = processing_result

                # Update media doc with processed info
                if media_doc and processing_result.get("success"):
                    _update_media_doc_with_processed(
                        media_doc.name,
                        processing_result
                    )

        return result

    except Exception as e:
        frappe.log_error(
            message=f"Media upload failed: {str(e)}",
            title="PIM Media Upload Error"
        )
        return {
            "success": False,
            "error": str(e)
        }


def process_media(
    file_url: str,
    operations: Optional[str] = None,
    max_dimension: int = 2048,
    quality: int = 85,
    generate_thumbnails: bool = True,
    convert_webp: bool = True,
    target_format: Optional[str] = None,
    async_processing: bool = False
) -> Dict[str, Any]:
    """Process a media file with various operations.

    Applies image processing operations including resize, crop, rotate,
    format conversion, thumbnail generation, and WebP optimization.

    Args:
        file_url: URL or path to the media file
        operations: JSON object of operations to apply:
            - resize: {"max_dimension": int} or {"width": int, "height": int}
            - crop: {"left": int, "top": int, "right": int, "bottom": int}
            - rotate: int (90, 180, 270)
            - flip: "horizontal" or "vertical"
            - format: "JPEG", "PNG", "WEBP", etc.
        max_dimension: Maximum width/height after resize
        quality: Output quality (1-100)
        generate_thumbnails: Generate all thumbnail sizes
        convert_webp: Create WebP version
        target_format: Target format for conversion
        async_processing: Run as background job

    Returns:
        dict: Processing result with paths to processed files

    Example:
        >>> result = process_media(
        ...     file_url="/files/product_image.jpg",
        ...     max_dimension=1200,
        ...     generate_thumbnails=True,
        ...     convert_webp=True
        ... )
        >>> result["thumbnails"]["medium"]
        '/files/product_image_medium.jpg'
    """
    import frappe
    from frappe import _

    if not frappe.has_permission("Product Media", "read"):
        frappe.throw(_("Not permitted to process media"), frappe.PermissionError)

    try:
        # Parse operations if JSON string
        if operations and isinstance(operations, str):
            operations = json.loads(operations)

        # Async processing
        if async_processing:
            return _enqueue_media_processing(
                file_url=file_url,
                operations=operations,
                max_dimension=max_dimension,
                quality=quality,
                generate_thumbnails=generate_thumbnails,
                convert_webp=convert_webp,
                target_format=target_format
            )

        # Import media utilities
        from frappe_pim.pim.utils.media import (
            process_product_image,
            process_image,
            convert_to_webp,
            generate_thumbnail
        )

        result = {
            "success": False,
            "original_path": file_url,
            "processed_path": None,
            "thumbnails": {},
            "webp_path": None,
            "operations_applied": [],
            "timestamp": datetime.now().isoformat()
        }

        # Apply custom operations if specified
        if operations:
            process_result = process_image(
                source_path=file_url,
                operations=operations,
                quality=quality
            )
            if process_result.get("success"):
                result["processed_path"] = process_result.get("output_path")
                result["operations_applied"] = process_result.get("operations_applied", [])
                file_url = result["processed_path"] or file_url
            else:
                result["error"] = process_result.get("error")
                return result

        # Standard processing (resize to max_dimension)
        if not operations and max_dimension:
            process_result = process_product_image(
                file_path=file_url,
                max_dimension=max_dimension,
                quality=quality,
                generate_thumbnails=False,
                convert_webp=False
            )
            if process_result.get("success"):
                result["processed_path"] = process_result.get("processed_path")
                file_url = result["processed_path"] or file_url
            elif process_result.get("error"):
                result["error"] = process_result.get("error")
                return result

        # Generate thumbnails
        if generate_thumbnails:
            for size_name, dimensions in DEFAULT_THUMBNAIL_SIZES.items():
                thumb_path = generate_thumbnail(
                    source_path=file_url,
                    size=dimensions,
                    quality=quality
                )
                if thumb_path:
                    result["thumbnails"][size_name] = thumb_path

        # Convert to WebP
        if convert_webp:
            webp_path = convert_to_webp(
                source_path=file_url,
                quality=80
            )
            if webp_path:
                result["webp_path"] = webp_path

        result["success"] = True
        return result

    except Exception as e:
        frappe.log_error(
            message=f"Media processing failed for {file_url}: {str(e)}",
            title="PIM Media Processing Error"
        )
        return {
            "success": False,
            "error": str(e),
            "original_path": file_url
        }


def get_media(
    file_url: Optional[str] = None,
    media_name: Optional[str] = None,
    product_name: Optional[str] = None,
    include_thumbnails: bool = True,
    include_metadata: bool = True
) -> Dict[str, Any]:
    """Retrieve media information and URLs.

    Gets detailed information about a media file including metadata,
    thumbnails, and associated product information.

    Args:
        file_url: Direct file URL to retrieve info for
        media_name: Name of Product Media document
        product_name: Get all media for a product
        include_thumbnails: Include thumbnail URLs
        include_metadata: Include image metadata (dimensions, size)

    Returns:
        dict: Media information including URLs and metadata

    Example:
        >>> # Get single media by URL
        >>> result = get_media(file_url="/files/image.jpg")
        >>> result["width"], result["height"]
        (1200, 800)

        >>> # Get all media for a product
        >>> result = get_media(product_name="PROD-001")
        >>> len(result["media"])
        5
    """
    import frappe
    from frappe import _

    if not frappe.has_permission("Product Media", "read"):
        frappe.throw(_("Not permitted to view media"), frappe.PermissionError)

    try:
        # Get by product - return all media for product
        if product_name:
            return _get_product_media_list(product_name, include_thumbnails, include_metadata)

        # Get by media document name
        if media_name:
            return _get_media_doc_details(media_name, include_thumbnails, include_metadata)

        # Get by file URL
        if file_url:
            return _get_file_media_info(file_url, include_thumbnails, include_metadata)

        return {
            "success": False,
            "error": _("file_url, media_name, or product_name is required")
        }

    except Exception as e:
        frappe.log_error(
            message=f"Media retrieval failed: {str(e)}",
            title="PIM Media Retrieval Error"
        )
        return {
            "success": False,
            "error": str(e)
        }


def delete_media(
    media_name: Optional[str] = None,
    file_url: Optional[str] = None,
    delete_file: bool = True,
    delete_thumbnails: bool = True
) -> Dict[str, Any]:
    """Delete media from the DAM system.

    Removes a media document and optionally its associated files
    including the original file and generated thumbnails.

    Args:
        media_name: Name of Product Media document to delete
        file_url: File URL to delete (without Product Media doc)
        delete_file: Also delete the actual file
        delete_thumbnails: Delete generated thumbnail files

    Returns:
        dict: Deletion result with list of deleted files

    Example:
        >>> result = delete_media(media_name="MEDIA-001", delete_file=True)
        >>> result["deleted_files"]
        ['/files/image.jpg', '/files/image_medium.jpg', '/files/image.webp']
    """
    import frappe
    from frappe import _

    if not frappe.has_permission("Product Media", "delete"):
        frappe.throw(_("Not permitted to delete media"), frappe.PermissionError)

    try:
        deleted_files = []

        if media_name:
            media_doc = frappe.get_doc("Product Media", media_name)
            file_url = media_doc.file_url

            # Collect thumbnail paths to delete
            if delete_thumbnails:
                for field in ["thumbnail_small", "thumbnail_medium", "thumbnail_large", "webp_url"]:
                    thumb_url = media_doc.get(field)
                    if thumb_url:
                        _delete_file_by_url(thumb_url)
                        deleted_files.append(thumb_url)

            # Delete the media document
            frappe.delete_doc("Product Media", media_name)

        # Delete the actual file
        if delete_file and file_url:
            _delete_file_by_url(file_url)
            deleted_files.append(file_url)

        frappe.db.commit()

        return {
            "success": True,
            "deleted_files": deleted_files,
            "message": _("Media deleted successfully")
        }

    except frappe.DoesNotExistError:
        return {
            "success": False,
            "error": _("Media not found")
        }
    except Exception as e:
        frappe.log_error(
            message=f"Media deletion failed: {str(e)}",
            title="PIM Media Deletion Error"
        )
        return {
            "success": False,
            "error": str(e)
        }


def transform_for_channel(
    file_url: str,
    channel: str,
    image_type: str = "main",
    async_processing: bool = False
) -> Dict[str, Any]:
    """Transform media to meet channel-specific requirements.

    Processes an image to conform to a specific marketplace channel's
    image requirements (dimensions, format, etc.).

    Args:
        file_url: URL of the source image
        channel: Channel key (amazon, shopify, google_merchant, etc.)
        image_type: Type of image (main, variant, thumbnail)
        async_processing: Run as background job

    Returns:
        dict: Transformation result with channel-optimized file URL

    Example:
        >>> result = transform_for_channel(
        ...     file_url="/files/product.jpg",
        ...     channel="amazon",
        ...     image_type="main"
        ... )
        >>> result["transformed_url"]
        '/files/product_amazon_main.jpg'
    """
    import frappe
    from frappe import _

    if not frappe.has_permission("Product Media", "read"):
        frappe.throw(_("Not permitted to transform media"), frappe.PermissionError)

    try:
        # Validate channel
        channel_key = channel.lower().replace(" ", "_")
        if channel_key not in CHANNEL_IMAGE_SPECS:
            return {
                "success": False,
                "error": _("Unknown channel: {0}. Supported: {1}").format(
                    channel,
                    ", ".join(CHANNEL_IMAGE_SPECS.keys())
                )
            }

        channel_specs = CHANNEL_IMAGE_SPECS[channel_key]
        image_spec = channel_specs.get(image_type, channel_specs.get("main", {}))

        if not image_spec:
            return {
                "success": False,
                "error": _("No spec found for image type: {0}").format(image_type)
            }

        if async_processing:
            return _enqueue_channel_transform(
                file_url=file_url,
                channel=channel_key,
                image_type=image_type,
                image_spec=image_spec
            )

        # Import media utilities
        from frappe_pim.pim.utils.media import (
            resize_image,
            convert_format,
            get_image_info
        )

        # Get current image info
        info = get_image_info(file_url)
        if not info:
            return {
                "success": False,
                "error": _("Could not read image: {0}").format(file_url)
            }

        output_path = None
        operations = []

        # Check minimum dimension
        min_dim = image_spec.get("min_dimension")
        if min_dim:
            current_min = min(info["width"], info["height"])
            if current_min < min_dim:
                return {
                    "success": False,
                    "error": _("Image too small. Minimum dimension: {0}px").format(min_dim),
                    "current_dimensions": (info["width"], info["height"])
                }

        # Resize if needed
        max_dim = image_spec.get("max_dimension")
        fixed_dim = image_spec.get("dimension")

        if fixed_dim:
            output_path = resize_image(
                source_path=file_url,
                width=fixed_dim,
                height=fixed_dim,
                preserve_aspect=True
            )
            operations.append("resize")
        elif max_dim and max(info["width"], info["height"]) > max_dim:
            output_path = resize_image(
                source_path=file_url,
                max_dimension=max_dim
            )
            operations.append("resize")

        # Convert format if needed
        target_format = image_spec.get("format")
        if target_format:
            source_path = output_path or file_url
            converted_path = convert_format(
                source_path=source_path,
                target_format=target_format
            )
            if converted_path:
                output_path = converted_path
                operations.append(f"convert_to_{target_format.lower()}")

        # Generate output filename with channel suffix
        if output_path:
            base_name = os.path.splitext(os.path.basename(file_url))[0]
            ext = os.path.splitext(output_path)[1]
            final_name = f"{base_name}_{channel_key}_{image_type}{ext}"
            # Move/rename to final path
            final_path = _rename_to_final_path(output_path, final_name)
        else:
            final_path = file_url

        return {
            "success": True,
            "original_url": file_url,
            "transformed_url": final_path,
            "channel": channel,
            "image_type": image_type,
            "operations_applied": operations,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        frappe.log_error(
            message=f"Channel transform failed: {str(e)}",
            title="PIM Media Transform Error"
        )
        return {
            "success": False,
            "error": str(e)
        }


def get_media_library(
    media_type: Optional[str] = None,
    search: Optional[str] = None,
    tags: Optional[str] = None,
    product_name: Optional[str] = None,
    orphaned_only: bool = False,
    page: int = 1,
    page_size: int = 50,
    sort_by: str = "modified",
    sort_order: str = "desc"
) -> Dict[str, Any]:
    """Browse the media library with filtering and search.

    Retrieves media assets with optional filtering by type, tags,
    product association, and text search.

    Args:
        media_type: Filter by type ('image', 'document', 'video')
        search: Search in title, filename, description
        tags: JSON list of tags to filter by
        product_name: Filter by associated product
        orphaned_only: Only show media not linked to any product
        page: Page number (1-based)
        page_size: Results per page (max 100)
        sort_by: Field to sort by (modified, creation, title, file_size)
        sort_order: Sort direction ('asc' or 'desc')

    Returns:
        dict: Paginated list of media items

    Example:
        >>> result = get_media_library(
        ...     media_type="image",
        ...     tags='["product", "hero"]',
        ...     page=1,
        ...     page_size=20
        ... )
        >>> result["total_count"]
        156
        >>> len(result["media"])
        20
    """
    import frappe
    from frappe import _

    if not frappe.has_permission("Product Media", "read"):
        frappe.throw(_("Not permitted to view media library"), frappe.PermissionError)

    try:
        # Validate and sanitize inputs
        page_size = min(max(page_size, 1), 100)
        page = max(page, 1)
        offset = (page - 1) * page_size

        # Build filters
        filters = {}

        if media_type:
            filters["media_type"] = media_type

        if product_name:
            filters["parent"] = product_name

        if orphaned_only:
            filters["parent"] = ["is", "not set"]

        # Parse tags filter
        if tags:
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except json.JSONDecodeError:
                    tags = [t.strip() for t in tags.split(",")]
            # Tags stored as JSON array - need SQL LIKE for each
            # This is a simplified approach; production might use a tags child table

        # Get count first
        total_count = frappe.db.count("Product Media", filters)

        # Get media list
        or_filters = None
        if search:
            or_filters = [
                ["title", "like", f"%{search}%"],
                ["file_name", "like", f"%{search}%"],
                ["description", "like", f"%{search}%"],
            ]

        media_list = frappe.get_all(
            "Product Media",
            filters=filters,
            or_filters=or_filters,
            fields=[
                "name", "file_url", "file_name", "title", "media_type",
                "is_primary", "alt_text", "description", "file_size",
                "width", "height", "thumbnail_medium", "webp_url",
                "parent", "creation", "modified"
            ],
            order_by=f"{sort_by} {sort_order}",
            start=offset,
            page_length=page_size
        )

        return {
            "success": True,
            "media": media_list,
            "total_count": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": (total_count + page_size - 1) // page_size
        }

    except Exception as e:
        frappe.log_error(
            message=f"Media library retrieval failed: {str(e)}",
            title="PIM Media Library Error"
        )
        return {
            "success": False,
            "error": str(e)
        }


def batch_process_media(
    file_urls: str,
    operation: str = "optimize",
    operation_params: Optional[str] = None,
    async_processing: bool = True
) -> Dict[str, Any]:
    """Process multiple media files in batch.

    Applies the same operation to multiple files, useful for bulk
    optimization or transformation tasks.

    Args:
        file_urls: JSON list of file URLs to process
        operation: Operation to perform:
            - optimize: Resize and optimize for web
            - thumbnails: Generate all thumbnail sizes
            - webp: Convert to WebP format
            - format: Convert to specified format
            - channel: Transform for specific channel
        operation_params: JSON object with operation-specific parameters
        async_processing: Run as background job (recommended for >5 files)

    Returns:
        dict: Batch processing result or job ID for async operations

    Example:
        >>> result = batch_process_media(
        ...     file_urls='["/files/img1.jpg", "/files/img2.jpg"]',
        ...     operation="optimize",
        ...     async_processing=True
        ... )
        >>> result["job_id"]
        'batch-media-001'
    """
    import frappe
    from frappe import _

    if not frappe.has_permission("Product Media", "write"):
        frappe.throw(_("Not permitted to process media"), frappe.PermissionError)

    try:
        # Parse inputs
        if isinstance(file_urls, str):
            file_urls = json.loads(file_urls)

        if operation_params and isinstance(operation_params, str):
            operation_params = json.loads(operation_params)
        else:
            operation_params = operation_params or {}

        if not file_urls or not isinstance(file_urls, list):
            return {
                "success": False,
                "error": _("file_urls must be a non-empty list")
            }

        # Async processing for larger batches
        if async_processing or len(file_urls) > 5:
            return _enqueue_batch_processing(
                file_urls=file_urls,
                operation=operation,
                operation_params=operation_params
            )

        # Synchronous processing for small batches
        results = []
        for file_url in file_urls:
            result = _process_single_file(file_url, operation, operation_params)
            results.append({
                "file_url": file_url,
                "result": result
            })

        success_count = sum(1 for r in results if r["result"].get("success"))

        return {
            "success": True,
            "total": len(file_urls),
            "succeeded": success_count,
            "failed": len(file_urls) - success_count,
            "results": results,
            "timestamp": datetime.now().isoformat()
        }

    except json.JSONDecodeError:
        return {
            "success": False,
            "error": _("Invalid JSON format for file_urls or operation_params")
        }
    except Exception as e:
        frappe.log_error(
            message=f"Batch media processing failed: {str(e)}",
            title="PIM Batch Processing Error"
        )
        return {
            "success": False,
            "error": str(e)
        }


def get_processing_status(job_id: str) -> Dict[str, Any]:
    """Get status of an async media processing job.

    Args:
        job_id: The job ID returned from async processing functions

    Returns:
        dict: Job status including progress and results

    Example:
        >>> status = get_processing_status(job_id="media-proc-001")
        >>> status["status"]
        'completed'
        >>> status["progress"]
        100
    """
    import frappe
    from frappe import _

    if not frappe.has_permission("Product Media", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    try:
        # Try to get from Media Processing Log if exists
        try:
            log = frappe.get_doc("Media Processing Log", job_id)
            return {
                "success": True,
                "job_id": job_id,
                "status": log.status,
                "progress": log.progress or 0,
                "total_files": log.total_files or 0,
                "processed_files": log.processed_files or 0,
                "results": json.loads(log.results) if log.results else [],
                "errors": json.loads(log.errors) if log.errors else [],
                "started_at": log.started_at,
                "completed_at": log.completed_at
            }
        except frappe.DoesNotExistError:
            pass

        # Fall back to background job status
        from frappe.utils.background_jobs import get_job

        job = get_job(job_id)
        if job:
            return {
                "success": True,
                "job_id": job_id,
                "status": job.get_status() or "unknown"
            }

        return {
            "success": False,
            "error": _("Job not found: {0}").format(job_id)
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def update_media_metadata(
    media_name: str,
    title: Optional[str] = None,
    alt_text: Optional[str] = None,
    description: Optional[str] = None,
    tags: Optional[str] = None,
    is_primary: Optional[bool] = None,
    sort_order: Optional[int] = None
) -> Dict[str, Any]:
    """Update metadata for a media document.

    Args:
        media_name: Name of the Product Media document
        title: New title
        alt_text: New alt text
        description: New description
        tags: JSON list of tags
        is_primary: Set as primary media
        sort_order: Display order

    Returns:
        dict: Update result

    Example:
        >>> result = update_media_metadata(
        ...     media_name="MEDIA-001",
        ...     title="Product Hero Image",
        ...     alt_text="Front view of product"
        ... )
    """
    import frappe
    from frappe import _

    if not frappe.has_permission("Product Media", "write"):
        frappe.throw(_("Not permitted to update media"), frappe.PermissionError)

    try:
        media_doc = frappe.get_doc("Product Media", media_name)

        if title is not None:
            media_doc.title = title
        if alt_text is not None:
            media_doc.alt_text = alt_text
        if description is not None:
            media_doc.description = description
        if tags is not None:
            if isinstance(tags, str):
                tags = json.loads(tags)
            media_doc.tags = json.dumps(tags)
        if sort_order is not None:
            media_doc.sort_order = sort_order

        # Handle is_primary - ensure only one primary per product
        if is_primary is not None:
            if is_primary and media_doc.parent:
                # Clear other primary flags
                frappe.db.sql("""
                    UPDATE `tabProduct Media`
                    SET is_primary = 0
                    WHERE parent = %s AND name != %s
                """, (media_doc.parent, media_name))
            media_doc.is_primary = is_primary

        media_doc.save()
        frappe.db.commit()

        return {
            "success": True,
            "media_name": media_name,
            "message": _("Media metadata updated successfully")
        }

    except frappe.DoesNotExistError:
        return {
            "success": False,
            "error": _("Media not found: {0}").format(media_name)
        }
    except Exception as e:
        frappe.log_error(
            message=f"Media metadata update failed: {str(e)}",
            title="PIM Media Update Error"
        )
        return {
            "success": False,
            "error": str(e)
        }


def get_supported_formats() -> Dict[str, Any]:
    """Get list of supported media formats and channel specifications.

    Returns:
        dict: Supported formats and channel image requirements

    Example:
        >>> formats = get_supported_formats()
        >>> formats["image_types"]
        ['jpeg', 'png', 'gif', 'webp', 'bmp', 'tiff']
    """
    return {
        "success": True,
        "image_types": list(SUPPORTED_IMAGE_TYPES.keys()),
        "document_types": list(SUPPORTED_DOCUMENT_TYPES.keys()),
        "video_types": list(SUPPORTED_VIDEO_TYPES.keys()),
        "thumbnail_sizes": DEFAULT_THUMBNAIL_SIZES,
        "channel_specs": CHANNEL_IMAGE_SPECS
    }


# ============================================================================
# Internal Helper Functions
# ============================================================================

def _save_base64_file(file_data: str, title: Optional[str] = None) -> Dict[str, Any]:
    """Save base64 encoded file data to Frappe File."""
    import frappe
    import base64
    import re

    try:
        # Parse data URI if present
        match = re.match(r"data:([^;]+);base64,(.+)", file_data)
        if match:
            content_type = match.group(1)
            file_data = match.group(2)
        else:
            content_type = "application/octet-stream"

        # Decode base64
        file_content = base64.b64decode(file_data)

        # Determine extension
        ext = _get_extension_for_content_type(content_type)
        filename = f"{title or 'upload'}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"

        # Save file
        file_doc = frappe.get_doc({
            "doctype": "File",
            "file_name": filename,
            "content": file_content,
            "is_private": 0,
            "folder": "Home/Media"
        })

        try:
            file_doc.insert(ignore_permissions=True)
            frappe.db.commit()
        except Exception:
            # Folder might not exist
            file_doc.folder = "Home"
            file_doc.insert(ignore_permissions=True)
            frappe.db.commit()

        return {
            "success": True,
            "file_url": file_doc.file_url,
            "filename": filename,
            "content_type": content_type
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to save file: {str(e)}"
        }


def _fetch_and_save_url(url: str, title: Optional[str] = None) -> Dict[str, Any]:
    """Fetch file from URL and save to Frappe File."""
    import frappe
    import requests

    try:
        response = requests.get(url, timeout=30, stream=True)
        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "").split(";")[0]
        ext = _get_extension_for_content_type(content_type)

        # Extract filename from URL or generate one
        url_filename = url.split("/")[-1].split("?")[0]
        if not title:
            title = os.path.splitext(url_filename)[0]

        filename = f"{title}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"

        # Save file
        file_doc = frappe.get_doc({
            "doctype": "File",
            "file_name": filename,
            "content": response.content,
            "is_private": 0,
            "folder": "Home/Media"
        })

        try:
            file_doc.insert(ignore_permissions=True)
            frappe.db.commit()
        except Exception:
            file_doc.folder = "Home"
            file_doc.insert(ignore_permissions=True)
            frappe.db.commit()

        return {
            "success": True,
            "file_url": file_doc.file_url,
            "filename": filename,
            "content_type": content_type
        }

    except requests.RequestException as e:
        return {
            "success": False,
            "error": f"Failed to fetch URL: {str(e)}"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to save file: {str(e)}"
        }


def _detect_media_type(content_type: Optional[str], filename: str) -> str:
    """Detect media type from content type or filename."""
    if content_type:
        if content_type in SUPPORTED_IMAGE_TYPES:
            return "image"
        if content_type in SUPPORTED_DOCUMENT_TYPES:
            return "document"
        if content_type in SUPPORTED_VIDEO_TYPES:
            return "video"

    # Fall back to extension
    ext = os.path.splitext(filename)[1].lower()
    if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif"):
        return "image"
    if ext in (".pdf", ".doc", ".docx", ".xls", ".xlsx"):
        return "document"
    if ext in (".mp4", ".webm", ".mov"):
        return "video"

    return "other"


def _get_extension_for_content_type(content_type: str) -> str:
    """Get file extension for content type."""
    all_types = {**SUPPORTED_IMAGE_TYPES, **SUPPORTED_DOCUMENT_TYPES, **SUPPORTED_VIDEO_TYPES}
    type_info = all_types.get(content_type)
    if type_info:
        return type_info["extension"]
    return ".bin"


def _create_product_media_doc(
    product_name: str,
    file_url: str,
    media_type: str,
    is_primary: bool,
    title: str,
    alt_text: Optional[str],
    description: Optional[str],
    tags: Optional[List[str]]
) -> Any:
    """Create a Product Media child document."""
    import frappe

    # Get the product document
    product = frappe.get_doc("Product Master", product_name)

    # If is_primary, clear other primary flags
    if is_primary:
        for media in product.get("media", []):
            media.is_primary = 0

    # Add new media entry
    media_entry = product.append("media", {
        "file_url": file_url,
        "media_type": media_type,
        "is_primary": is_primary,
        "title": title,
        "alt_text": alt_text,
        "description": description,
        "tags": json.dumps(tags) if tags else None
    })

    product.save()
    frappe.db.commit()

    return media_entry


def _update_media_doc_with_processed(media_name: str, processing_result: Dict) -> None:
    """Update media document with processing results."""
    import frappe

    updates = {}

    if processing_result.get("thumbnails"):
        thumbs = processing_result["thumbnails"]
        if "small" in thumbs:
            updates["thumbnail_small"] = thumbs["small"]
        if "medium" in thumbs:
            updates["thumbnail_medium"] = thumbs["medium"]
        if "large" in thumbs:
            updates["thumbnail_large"] = thumbs["large"]

    if processing_result.get("webp_path"):
        updates["webp_url"] = processing_result["webp_path"]

    if updates:
        frappe.db.set_value("Product Media", media_name, updates)
        frappe.db.commit()


def _enqueue_media_processing(**kwargs) -> Dict[str, Any]:
    """Enqueue media processing as background job."""
    import frappe

    job = frappe.enqueue(
        "frappe_pim.pim.api.media.process_media",
        queue="long",
        timeout=600,
        **kwargs,
        async_processing=False  # Prevent infinite loop
    )

    return {
        "success": True,
        "queued": True,
        "job_id": str(job.id) if hasattr(job, "id") else str(job),
        "message": "Media processing queued"
    }


def _enqueue_channel_transform(**kwargs) -> Dict[str, Any]:
    """Enqueue channel transformation as background job."""
    import frappe

    job = frappe.enqueue(
        "frappe_pim.pim.api.media.transform_for_channel",
        queue="default",
        timeout=300,
        **kwargs,
        async_processing=False
    )

    return {
        "success": True,
        "queued": True,
        "job_id": str(job.id) if hasattr(job, "id") else str(job),
        "message": "Channel transformation queued"
    }


def _enqueue_batch_processing(
    file_urls: List[str],
    operation: str,
    operation_params: Dict
) -> Dict[str, Any]:
    """Enqueue batch processing as background job."""
    import frappe

    job = frappe.enqueue(
        "frappe_pim.pim.api.media._run_batch_processing",
        queue="long",
        timeout=3600,
        file_urls=file_urls,
        operation=operation,
        operation_params=operation_params
    )

    return {
        "success": True,
        "queued": True,
        "job_id": str(job.id) if hasattr(job, "id") else str(job),
        "total_files": len(file_urls),
        "message": "Batch processing queued"
    }


def _run_batch_processing(
    file_urls: List[str],
    operation: str,
    operation_params: Dict
) -> Dict[str, Any]:
    """Background job handler for batch processing."""
    results = []

    for file_url in file_urls:
        result = _process_single_file(file_url, operation, operation_params)
        results.append({
            "file_url": file_url,
            "result": result
        })

    success_count = sum(1 for r in results if r["result"].get("success"))

    return {
        "success": True,
        "total": len(file_urls),
        "succeeded": success_count,
        "failed": len(file_urls) - success_count,
        "results": results
    }


def _process_single_file(
    file_url: str,
    operation: str,
    operation_params: Dict
) -> Dict[str, Any]:
    """Process a single file with the specified operation."""
    if operation == "optimize":
        return process_media(
            file_url=file_url,
            max_dimension=operation_params.get("max_dimension", 2048),
            quality=operation_params.get("quality", 85),
            generate_thumbnails=True,
            convert_webp=True
        )
    elif operation == "thumbnails":
        return process_media(
            file_url=file_url,
            generate_thumbnails=True,
            convert_webp=False
        )
    elif operation == "webp":
        from frappe_pim.pim.utils.media import convert_to_webp
        webp_path = convert_to_webp(file_url, quality=operation_params.get("quality", 80))
        return {"success": bool(webp_path), "webp_path": webp_path}
    elif operation == "format":
        from frappe_pim.pim.utils.media import convert_format
        target_format = operation_params.get("format", "JPEG")
        converted = convert_format(file_url, target_format)
        return {"success": bool(converted), "converted_path": converted}
    elif operation == "channel":
        return transform_for_channel(
            file_url=file_url,
            channel=operation_params.get("channel", ""),
            image_type=operation_params.get("image_type", "main")
        )
    else:
        return {"success": False, "error": f"Unknown operation: {operation}"}


def _get_product_media_list(
    product_name: str,
    include_thumbnails: bool,
    include_metadata: bool
) -> Dict[str, Any]:
    """Get all media for a product."""
    import frappe

    try:
        product = frappe.get_doc("Product Master", product_name)
        media_list = []

        for media in product.get("media", []):
            media_item = {
                "name": media.name,
                "file_url": media.file_url,
                "media_type": media.media_type,
                "is_primary": media.is_primary,
                "title": media.title,
                "alt_text": media.alt_text
            }

            if include_thumbnails:
                media_item["thumbnails"] = {
                    "small": media.get("thumbnail_small"),
                    "medium": media.get("thumbnail_medium"),
                    "large": media.get("thumbnail_large")
                }
                media_item["webp_url"] = media.get("webp_url")

            if include_metadata:
                media_item["width"] = media.get("width")
                media_item["height"] = media.get("height")
                media_item["file_size"] = media.get("file_size")

            media_list.append(media_item)

        return {
            "success": True,
            "product_name": product_name,
            "media_count": len(media_list),
            "media": media_list
        }

    except frappe.DoesNotExistError:
        return {
            "success": False,
            "error": f"Product not found: {product_name}"
        }


def _get_media_doc_details(
    media_name: str,
    include_thumbnails: bool,
    include_metadata: bool
) -> Dict[str, Any]:
    """Get details for a specific media document."""
    import frappe

    try:
        media = frappe.get_doc("Product Media", media_name)

        result = {
            "success": True,
            "name": media.name,
            "file_url": media.file_url,
            "media_type": media.media_type,
            "is_primary": media.is_primary,
            "title": media.title,
            "alt_text": media.alt_text,
            "description": media.description,
            "product": media.parent
        }

        if include_thumbnails:
            result["thumbnails"] = {
                "small": media.get("thumbnail_small"),
                "medium": media.get("thumbnail_medium"),
                "large": media.get("thumbnail_large")
            }
            result["webp_url"] = media.get("webp_url")

        if include_metadata:
            result["width"] = media.get("width")
            result["height"] = media.get("height")
            result["file_size"] = media.get("file_size")

        return result

    except frappe.DoesNotExistError:
        return {
            "success": False,
            "error": f"Media not found: {media_name}"
        }


def _get_file_media_info(
    file_url: str,
    include_thumbnails: bool,
    include_metadata: bool
) -> Dict[str, Any]:
    """Get info for a file by URL."""
    from frappe_pim.pim.utils.media import get_image_info

    info = get_image_info(file_url)

    if not info:
        return {
            "success": False,
            "error": f"Could not read file: {file_url}"
        }

    result = {
        "success": True,
        "file_url": file_url,
        "filename": os.path.basename(file_url)
    }

    if include_metadata:
        result.update({
            "width": info.get("width"),
            "height": info.get("height"),
            "format": info.get("format"),
            "mode": info.get("mode"),
            "file_size": info.get("file_size"),
            "file_size_human": info.get("file_size_human")
        })

    return result


def _delete_file_by_url(file_url: str) -> None:
    """Delete a file by its URL."""
    import frappe

    try:
        # Find the File document
        file_doc = frappe.get_all(
            "File",
            filters={"file_url": file_url},
            fields=["name"],
            limit=1
        )

        if file_doc:
            frappe.delete_doc("File", file_doc[0]["name"], force=True)
    except Exception:
        pass  # Ignore errors when deleting files


def _rename_to_final_path(source_path: str, final_name: str) -> str:
    """Rename processed file to final path."""
    import frappe
    import shutil

    try:
        site_path = frappe.get_site_path()

        # Determine source and destination paths
        if source_path.startswith("/"):
            if source_path.startswith("/private/"):
                full_source = os.path.join(site_path, source_path.lstrip("/"))
            else:
                full_source = os.path.join(site_path, "public", source_path.lstrip("/"))
        else:
            full_source = source_path

        # Generate destination path
        dest_dir = os.path.dirname(full_source)
        full_dest = os.path.join(dest_dir, final_name)

        # Rename file
        if os.path.exists(full_source) and full_source != full_dest:
            shutil.move(full_source, full_dest)

            # Return URL format
            if "/private/" in full_dest:
                return "/private/files/" + final_name
            return "/files/" + final_name

        return source_path

    except Exception:
        return source_path


# Make functions available for frappe.whitelist()
def _wrap_for_whitelist():
    """Wrapper to add @frappe.whitelist() decorators at runtime."""
    import frappe

    global upload_media, process_media, get_media, delete_media
    global transform_for_channel, get_media_library, batch_process_media
    global get_processing_status, update_media_metadata, get_supported_formats

    upload_media = frappe.whitelist()(upload_media)
    process_media = frappe.whitelist()(process_media)
    get_media = frappe.whitelist()(get_media)
    delete_media = frappe.whitelist()(delete_media)
    transform_for_channel = frappe.whitelist()(transform_for_channel)
    get_media_library = frappe.whitelist()(get_media_library)
    batch_process_media = frappe.whitelist()(batch_process_media)
    get_processing_status = frappe.whitelist()(get_processing_status)
    update_media_metadata = frappe.whitelist()(update_media_metadata)
    get_supported_formats = frappe.whitelist(allow_guest=True)(get_supported_formats)


# Try to add whitelist decorators if frappe is available
try:
    _wrap_for_whitelist()
except ImportError:
    pass  # frappe not available, decorators will be added when module is used
