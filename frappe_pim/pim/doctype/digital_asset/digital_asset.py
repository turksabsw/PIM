"""
Digital Asset Controller
Digital Asset Management for PIM system with renditions support
"""

import frappe
from frappe import _
from frappe.model.document import Document
from typing import Optional, List, Dict, Any
import os
import hashlib
import json
from datetime import datetime


class DigitalAsset(Document):
    def validate(self):
        self.validate_dates()
        self.validate_renditions()
        self.set_asset_code()

    def before_save(self):
        self.extract_file_metadata()
        self.update_rendition_defaults()

    def after_insert(self):
        if self.auto_generate_renditions:
            self.queue_rendition_generation()
        self.create_pim_event("Created")

    def on_update(self):
        self.update_linked_products_count()
        self.create_pim_event("Updated")

    def on_trash(self):
        self.create_pim_event("Deleted")
        self.cleanup_renditions()

    def validate_dates(self):
        """Validate date ranges"""
        if self.valid_from and self.valid_to:
            if self.valid_from > self.valid_to:
                frappe.throw(
                    _("Valid From date cannot be after Valid To date"),
                    title=_("Invalid Date Range")
                )

        if self.license_expiry and self.valid_to:
            if self.license_expiry < self.valid_to:
                frappe.msgprint(
                    _("License expiry is before the asset validity end date"),
                    indicator="orange",
                    alert=True
                )

    def validate_renditions(self):
        """Validate rendition configurations"""
        if not self.renditions:
            return

        # Check for duplicate rendition types
        seen_types = {}
        for rendition in self.renditions:
            key = f"{rendition.rendition_type}_{rendition.width}x{rendition.height}"
            if key in seen_types and not rendition.rendition_name:
                frappe.throw(
                    _("Duplicate rendition configuration: {0}").format(key),
                    title=_("Duplicate Rendition")
                )
            seen_types[key] = True

    def set_asset_code(self):
        """Set asset code if not provided"""
        if not self.asset_code:
            # Generate asset code from name or file
            if self.name:
                self.asset_code = self.name.replace(" ", "-").upper()

    def extract_file_metadata(self):
        """Extract metadata from the uploaded file"""
        if not self.original_file:
            return

        try:
            file_path = self.get_file_path(self.original_file)
            if not file_path or not os.path.exists(file_path):
                return

            # Get basic file info
            file_stat = os.stat(file_path)
            self.file_size = file_stat.st_size

            # Get filename and format
            filename = os.path.basename(self.original_file)
            if not self.original_filename:
                self.original_filename = filename

            _, ext = os.path.splitext(filename)
            self.file_format = ext.lstrip('.').upper() if ext else None

            # Set MIME type based on extension
            self.mime_type = self.get_mime_type(ext.lstrip('.').lower() if ext else '')

            # Calculate content hash
            self.content_hash = self.calculate_file_hash(file_path)

            # Auto-detect asset type from extension
            if not self.asset_type:
                self.asset_type = self.detect_asset_type(ext.lstrip('.').lower() if ext else '')

            # Extract image-specific metadata
            if self.asset_type == "Image":
                self.extract_image_metadata(file_path)

        except Exception as e:
            frappe.log_error(f"Error extracting file metadata: {str(e)}")

    def get_file_path(self, file_url: str) -> Optional[str]:
        """Get the full file path from a file URL"""
        if not file_url:
            return None

        if file_url.startswith('/files/'):
            site_path = frappe.get_site_path()
            return os.path.join(site_path, 'public', file_url.lstrip('/'))
        elif file_url.startswith('/private/files/'):
            site_path = frappe.get_site_path()
            return os.path.join(site_path, file_url.lstrip('/'))

        return None

    def get_mime_type(self, extension: str) -> str:
        """Get MIME type from file extension"""
        mime_map = {
            # Images
            'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
            'gif': 'image/gif', 'webp': 'image/webp', 'svg': 'image/svg+xml',
            'tiff': 'image/tiff', 'tif': 'image/tiff', 'bmp': 'image/bmp',
            'ico': 'image/x-icon', 'heic': 'image/heic', 'heif': 'image/heif',
            # Videos
            'mp4': 'video/mp4', 'webm': 'video/webm', 'mov': 'video/quicktime',
            'avi': 'video/x-msvideo', 'mkv': 'video/x-matroska',
            'm4v': 'video/x-m4v', 'wmv': 'video/x-ms-wmv',
            # Audio
            'mp3': 'audio/mpeg', 'wav': 'audio/wav', 'ogg': 'audio/ogg',
            'flac': 'audio/flac', 'aac': 'audio/aac', 'm4a': 'audio/mp4',
            # Documents
            'pdf': 'application/pdf', 'doc': 'application/msword',
            'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'xls': 'application/vnd.ms-excel',
            'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'ppt': 'application/vnd.ms-powerpoint',
            'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            # Archives
            'zip': 'application/zip', 'rar': 'application/x-rar-compressed',
            '7z': 'application/x-7z-compressed', 'tar': 'application/x-tar',
            'gz': 'application/gzip',
            # 3D
            'obj': 'model/obj', 'fbx': 'model/fbx', 'gltf': 'model/gltf+json',
            'glb': 'model/gltf-binary', 'stl': 'model/stl', 'usdz': 'model/vnd.usdz+zip'
        }
        return mime_map.get(extension, 'application/octet-stream')

    def detect_asset_type(self, extension: str) -> str:
        """Detect asset type from file extension"""
        image_exts = {'jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'tiff', 'tif', 'bmp', 'ico', 'heic', 'heif'}
        video_exts = {'mp4', 'webm', 'mov', 'avi', 'mkv', 'm4v', 'wmv'}
        audio_exts = {'mp3', 'wav', 'ogg', 'flac', 'aac', 'm4a'}
        document_exts = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'rtf'}
        archive_exts = {'zip', 'rar', '7z', 'tar', 'gz'}
        model_3d_exts = {'obj', 'fbx', 'gltf', 'glb', 'stl', 'usdz', 'dae'}

        if extension in image_exts:
            return "Image"
        elif extension in video_exts:
            return "Video"
        elif extension in audio_exts:
            return "Audio"
        elif extension in document_exts:
            return "Document"
        elif extension in archive_exts:
            return "Archive"
        elif extension in model_3d_exts:
            return "3D Model"
        return "Other"

    def calculate_file_hash(self, file_path: str) -> str:
        """Calculate SHA256 hash of a file"""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def extract_image_metadata(self, file_path: str):
        """Extract metadata from image files"""
        try:
            # Try using PIL for image dimensions
            from PIL import Image
            with Image.open(file_path) as img:
                self.width = img.width
                self.height = img.height

                # Calculate aspect ratio
                from math import gcd
                divisor = gcd(img.width, img.height)
                self.aspect_ratio = f"{img.width // divisor}:{img.height // divisor}"

                # Get DPI if available
                if hasattr(img, 'info') and 'dpi' in img.info:
                    dpi = img.info['dpi']
                    self.dpi = int(dpi[0]) if isinstance(dpi, tuple) else int(dpi)

                # Get color mode
                if img.mode:
                    mode_map = {
                        '1': 'Bitmap', 'L': 'Grayscale', 'P': 'Palette',
                        'RGB': 'sRGB', 'RGBA': 'sRGB', 'CMYK': 'CMYK',
                        'LAB': 'LAB', 'HSV': 'HSV'
                    }
                    self.color_space = mode_map.get(img.mode, img.mode)

                # Get bit depth
                mode_bits = {'1': 1, 'L': 8, 'P': 8, 'RGB': 24, 'RGBA': 32, 'CMYK': 32}
                self.bit_depth = mode_bits.get(img.mode, 8)

                # Extract EXIF data
                if hasattr(img, '_getexif') and img._getexif():
                    exif = img._getexif()
                    if exif:
                        # Convert EXIF to serializable format
                        exif_data = {}
                        for tag_id, value in exif.items():
                            try:
                                from PIL.ExifTags import TAGS
                                tag = TAGS.get(tag_id, tag_id)
                                if isinstance(value, bytes):
                                    value = value.decode('utf-8', errors='ignore')
                                exif_data[str(tag)] = str(value)
                            except Exception:
                                pass
                        if exif_data:
                            self.exif_data = json.dumps(exif_data)

        except ImportError:
            # PIL not available, skip image metadata extraction
            pass
        except Exception as e:
            frappe.log_error(f"Error extracting image metadata: {str(e)}")

    def update_rendition_defaults(self):
        """Ensure only one default rendition per type"""
        if not self.renditions:
            return

        # Group renditions by type
        by_type = {}
        for rendition in self.renditions:
            rtype = rendition.rendition_type
            if rtype not in by_type:
                by_type[rtype] = []
            by_type[rtype].append(rendition)

        # Ensure only one default per type
        for rtype, renditions in by_type.items():
            defaults = [r for r in renditions if r.is_default]
            if len(defaults) > 1:
                # Keep only the first default
                for r in defaults[1:]:
                    r.is_default = 0

    def queue_rendition_generation(self):
        """Queue background job to generate renditions"""
        if self.asset_type != "Image":
            return

        frappe.enqueue(
            "frappe_pim.pim.doctype.digital_asset.digital_asset.generate_image_renditions",
            asset_name=self.name,
            queue="long"
        )

    def update_linked_products_count(self):
        """Update the count of linked products"""
        try:
            count = frappe.db.count(
                "Product Asset Link",
                filters={"digital_asset": self.name}
            )
            if count != self.linked_products_count:
                frappe.db.set_value(
                    "Digital Asset", self.name,
                    "linked_products_count", count,
                    update_modified=False
                )
        except Exception:
            # Table might not exist yet
            pass

    def cleanup_renditions(self):
        """Clean up rendition files when asset is deleted"""
        if not self.renditions:
            return

        for rendition in self.renditions:
            if rendition.file:
                try:
                    file_path = self.get_file_path(rendition.file)
                    if file_path and os.path.exists(file_path):
                        os.remove(file_path)
                except Exception as e:
                    frappe.log_error(f"Error cleaning up rendition: {str(e)}")

    def create_pim_event(self, event_type: str):
        """Create a PIM Event for this asset change"""
        try:
            from frappe_pim.pim.doctype.pim_event.pim_event import create_event_for_doc
            create_event_for_doc(self, event_type)
        except Exception:
            # PIM Event might not be available
            pass

    def get_rendition(self, rendition_type: str = "Web", width: int = None) -> Optional[Dict]:
        """Get a specific rendition

        Args:
            rendition_type: Type of rendition to get
            width: Specific width to match (optional)

        Returns:
            Rendition data or None
        """
        if not self.renditions:
            return None

        matching = []
        for r in self.renditions:
            if r.rendition_type == rendition_type:
                if width and r.width == width:
                    return r.as_dict()
                matching.append(r)

        if matching:
            # Return default or first match
            for r in matching:
                if r.is_default:
                    return r.as_dict()
            return matching[0].as_dict()

        return None

    def get_url(self, rendition_type: str = None) -> str:
        """Get the URL for this asset

        Args:
            rendition_type: Optional rendition type to get URL for

        Returns:
            URL string
        """
        if rendition_type and self.renditions:
            rendition = self.get_rendition(rendition_type)
            if rendition and rendition.get('file'):
                return rendition['file']

        if self.cdn_enabled and self.cdn_url:
            return self.cdn_url

        return self.original_file or ""

    def is_valid(self, as_of_date: str = None) -> bool:
        """Check if asset is valid for a given date

        Args:
            as_of_date: Date to check validity for (defaults to today)

        Returns:
            True if valid, False otherwise
        """
        if self.status != "Active":
            return False

        check_date = as_of_date or frappe.utils.today()

        if self.valid_from and str(self.valid_from) > check_date:
            return False

        if self.valid_to and str(self.valid_to) < check_date:
            return False

        if self.license_expiry and str(self.license_expiry) < check_date:
            return False

        return True

    def increment_view_count(self):
        """Increment the view counter"""
        frappe.db.set_value(
            "Digital Asset", self.name,
            {
                "view_count": (self.view_count or 0) + 1,
                "last_used_at": frappe.utils.now_datetime()
            },
            update_modified=False
        )

    def increment_download_count(self):
        """Increment the download counter"""
        frappe.db.set_value(
            "Digital Asset", self.name,
            {
                "download_count": (self.download_count or 0) + 1,
                "last_used_at": frappe.utils.now_datetime()
            },
            update_modified=False
        )


# ============================================
# Background Jobs
# ============================================

def generate_image_renditions(asset_name: str):
    """Generate standard image renditions

    Args:
        asset_name: Name of the Digital Asset
    """
    try:
        from PIL import Image

        asset = frappe.get_doc("Digital Asset", asset_name)
        if asset.asset_type != "Image" or not asset.original_file:
            return

        file_path = asset.get_file_path(asset.original_file)
        if not file_path or not os.path.exists(file_path):
            return

        # Standard rendition sizes
        rendition_configs = [
            {"name": "Thumbnail", "type": "Thumbnail", "width": 150, "height": 150},
            {"name": "Small", "type": "Small", "width": 320, "height": None},
            {"name": "Medium", "type": "Medium", "width": 640, "height": None},
            {"name": "Large", "type": "Large", "width": 1280, "height": None},
            {"name": "Web", "type": "Web", "width": 1920, "height": None}
        ]

        with Image.open(file_path) as img:
            original_width, original_height = img.size

            for config in rendition_configs:
                # Skip if original is smaller than target
                if config["width"] and original_width <= config["width"]:
                    continue

                # Generate rendition
                if config["width"] and config["height"]:
                    # Thumbnail - crop to square
                    size = min(original_width, original_height, config["width"])
                    rendition_img = img.copy()
                    rendition_img.thumbnail((size, size), Image.Resampling.LANCZOS)
                else:
                    # Maintain aspect ratio
                    ratio = config["width"] / original_width
                    new_height = int(original_height * ratio)
                    rendition_img = img.resize(
                        (config["width"], new_height),
                        Image.Resampling.LANCZOS
                    )

                # Save rendition
                rendition_filename = f"{asset_name}_{config['type'].lower()}.{asset.file_format.lower()}"
                rendition_path = os.path.join(
                    frappe.get_site_path(), 'public', 'files', rendition_filename
                )

                save_kwargs = {}
                if asset.file_format.lower() in ['jpg', 'jpeg']:
                    save_kwargs['quality'] = 85
                    save_kwargs['optimize'] = True

                rendition_img.save(rendition_path, **save_kwargs)

                # Get file size
                rendition_size = os.stat(rendition_path).st_size

                # Add to renditions table
                asset.append("renditions", {
                    "rendition_name": config["name"],
                    "rendition_type": config["type"],
                    "file": f"/files/{rendition_filename}",
                    "width": rendition_img.width,
                    "height": rendition_img.height,
                    "file_size": rendition_size,
                    "file_format": asset.file_format,
                    "is_auto_generated": 1,
                    "is_default": config["type"] == "Web",
                    "quality": save_kwargs.get('quality', 100),
                    "generated_at": frappe.utils.now_datetime()
                })

        asset.save(ignore_permissions=True)
        frappe.db.commit()

    except ImportError:
        frappe.log_error("PIL not installed - cannot generate renditions")
    except Exception as e:
        frappe.log_error(f"Error generating renditions for {asset_name}: {str(e)}")


# ============================================
# API Methods
# ============================================

@frappe.whitelist()
def get_asset(
    asset_name: str = None,
    asset_code: str = None,
    include_renditions: bool = True
) -> Dict[str, Any]:
    """Get a digital asset by name or code

    Args:
        asset_name: Asset document name
        asset_code: Asset code
        include_renditions: Include rendition details

    Returns:
        Asset data dictionary
    """
    if not frappe.has_permission("Digital Asset", "read"):
        frappe.throw(_("You do not have permission to view assets"))

    filters = {}
    if asset_name:
        filters["name"] = asset_name
    elif asset_code:
        filters["asset_code"] = asset_code
    else:
        frappe.throw(_("Either asset_name or asset_code is required"))

    asset = frappe.get_doc("Digital Asset", filters)

    data = asset.as_dict()

    if not include_renditions:
        data.pop("renditions", None)

    return data


@frappe.whitelist()
def search_assets(
    query: str = None,
    asset_type: str = None,
    status: str = None,
    brand: str = None,
    category: str = None,
    channel: str = None,
    locale: str = None,
    tags: str = None,
    valid_only: bool = False,
    limit: int = 20,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """Search for digital assets

    Args:
        query: Text search query
        asset_type: Filter by asset type
        status: Filter by status
        brand: Filter by brand
        category: Filter by category
        channel: Filter by channel
        locale: Filter by locale
        tags: Filter by tags (comma-separated)
        valid_only: Only return currently valid assets
        limit: Maximum results
        offset: Results offset

    Returns:
        List of matching assets
    """
    if not frappe.has_permission("Digital Asset", "read"):
        frappe.throw(_("You do not have permission to view assets"))

    filters = {}

    if asset_type:
        filters["asset_type"] = asset_type
    if status:
        filters["status"] = status
    if brand:
        filters["brand"] = brand
    if category:
        filters["asset_category"] = category
    if channel:
        filters["channel"] = channel
    if locale:
        filters["locale"] = locale

    if valid_only:
        today = frappe.utils.today()
        filters["status"] = "Active"
        # Note: Date filters handled in query

    # Build query for text search and tags
    conditions = []
    values = {}

    if query:
        conditions.append("""
            (asset_title LIKE %(query)s
             OR asset_code LIKE %(query)s
             OR original_filename LIKE %(query)s
             OR description LIKE %(query)s)
        """)
        values["query"] = f"%{query}%"

    if tags:
        tag_list = [t.strip() for t in tags.split(",")]
        tag_conditions = []
        for i, tag in enumerate(tag_list):
            tag_conditions.append(f"tags LIKE %(tag_{i})s")
            values[f"tag_{i}"] = f"%{tag}%"
        conditions.append(f"({' OR '.join(tag_conditions)})")

    if valid_only:
        today = frappe.utils.today()
        conditions.append("""
            (valid_from IS NULL OR valid_from <= %(today)s)
            AND (valid_to IS NULL OR valid_to >= %(today)s)
        """)
        values["today"] = today

    where_clause = ""
    if conditions:
        where_clause = "AND " + " AND ".join(conditions)

    # Build filter clause
    filter_clause = ""
    for key, value in filters.items():
        filter_clause += f" AND `{key}` = %({key})s"
        values[key] = value

    assets = frappe.db.sql(f"""
        SELECT
            name, asset_code, asset_title, asset_type, status,
            thumbnail, original_file, file_format, file_size,
            width, height, brand, asset_category as category,
            channel, locale, valid_from, valid_to,
            view_count, download_count, linked_products_count
        FROM `tabDigital Asset`
        WHERE 1=1 {filter_clause} {where_clause}
        ORDER BY modified DESC
        LIMIT %(limit)s OFFSET %(offset)s
    """, {**values, "limit": min(limit, 100), "offset": offset}, as_dict=True)

    return assets


@frappe.whitelist()
def get_product_assets(
    product: str,
    asset_type: str = None,
    role: str = None
) -> List[Dict[str, Any]]:
    """Get all assets linked to a product

    Args:
        product: Product Master name or SKU
        asset_type: Filter by asset type
        role: Filter by asset role (e.g., Main Image, Gallery, Document)

    Returns:
        List of linked assets
    """
    if not frappe.has_permission("Digital Asset", "read"):
        frappe.throw(_("You do not have permission to view assets"))

    filters = {"product": product}
    if asset_type:
        filters["asset_type"] = asset_type
    if role:
        filters["role"] = role

    try:
        links = frappe.get_all(
            "Product Asset Link",
            filters=filters,
            fields=["digital_asset", "role", "sort_order", "is_primary"],
            order_by="sort_order asc"
        )

        assets = []
        for link in links:
            asset = frappe.get_doc("Digital Asset", link.digital_asset)
            asset_data = {
                "name": asset.name,
                "asset_code": asset.asset_code,
                "asset_title": asset.asset_title,
                "asset_type": asset.asset_type,
                "thumbnail": asset.thumbnail,
                "url": asset.get_url(),
                "role": link.role,
                "is_primary": link.is_primary,
                "sort_order": link.sort_order
            }
            assets.append(asset_data)

        return assets

    except Exception:
        # Product Asset Link might not exist
        return []


@frappe.whitelist()
def upload_asset(
    file: str,
    asset_title: str,
    asset_type: str = None,
    description: str = None,
    brand: str = None,
    category: str = None,
    tags: str = None,
    auto_generate_renditions: bool = True
) -> Dict[str, Any]:
    """Upload a new digital asset

    Args:
        file: File URL (from Frappe file upload)
        asset_title: Title for the asset
        asset_type: Type of asset (auto-detected if not provided)
        description: Asset description
        brand: Associated brand
        category: Asset category
        tags: Comma-separated tags
        auto_generate_renditions: Generate renditions automatically

    Returns:
        Created asset data
    """
    if not frappe.has_permission("Digital Asset", "create"):
        frappe.throw(_("You do not have permission to create assets"))

    asset = frappe.get_doc({
        "doctype": "Digital Asset",
        "original_file": file,
        "asset_title": asset_title,
        "asset_type": asset_type,
        "description": description,
        "brand": brand,
        "asset_category": category,
        "tags": tags,
        "auto_generate_renditions": 1 if auto_generate_renditions else 0,
        "status": "Draft"
    })
    asset.insert()

    return {
        "success": True,
        "asset_name": asset.name,
        "asset_code": asset.asset_code
    }


@frappe.whitelist()
def get_asset_url(
    asset_name: str,
    rendition_type: str = None
) -> str:
    """Get the URL for an asset

    Args:
        asset_name: Asset name
        rendition_type: Optional specific rendition type

    Returns:
        URL string
    """
    if not frappe.has_permission("Digital Asset", "read"):
        frappe.throw(_("You do not have permission to view assets"))

    asset = frappe.get_doc("Digital Asset", asset_name)

    # Increment view count
    asset.increment_view_count()

    return asset.get_url(rendition_type)


@frappe.whitelist()
def regenerate_renditions(asset_name: str) -> Dict[str, Any]:
    """Regenerate renditions for an asset

    Args:
        asset_name: Asset name

    Returns:
        Status dict
    """
    if not frappe.has_permission("Digital Asset", "write"):
        frappe.throw(_("You do not have permission to modify assets"))

    asset = frappe.get_doc("Digital Asset", asset_name)

    if asset.asset_type != "Image":
        frappe.throw(_("Renditions can only be generated for images"))

    # Clear existing auto-generated renditions
    asset.renditions = [r for r in (asset.renditions or []) if not r.is_auto_generated]
    asset.save()

    # Queue regeneration
    frappe.enqueue(
        "frappe_pim.pim.doctype.digital_asset.digital_asset.generate_image_renditions",
        asset_name=asset_name,
        queue="long"
    )

    return {
        "success": True,
        "message": _("Rendition generation queued")
    }


@frappe.whitelist()
def get_asset_statistics() -> Dict[str, Any]:
    """Get statistics about digital assets

    Returns:
        Statistics dictionary
    """
    if not frappe.has_permission("Digital Asset", "read"):
        frappe.throw(_("You do not have permission to view assets"))

    stats = {}

    # Total count
    stats["total_assets"] = frappe.db.count("Digital Asset")

    # By type
    type_counts = frappe.db.sql("""
        SELECT asset_type, COUNT(*) as count
        FROM `tabDigital Asset`
        GROUP BY asset_type
    """, as_dict=True)
    stats["by_type"] = {r.asset_type: r.count for r in type_counts}

    # By status
    status_counts = frappe.db.sql("""
        SELECT status, COUNT(*) as count
        FROM `tabDigital Asset`
        GROUP BY status
    """, as_dict=True)
    stats["by_status"] = {r.status: r.count for r in status_counts}

    # Total file size
    total_size = frappe.db.sql("""
        SELECT SUM(file_size) as total
        FROM `tabDigital Asset`
    """)[0][0] or 0
    stats["total_file_size"] = total_size
    stats["total_file_size_formatted"] = frappe.utils.formatters.filesize(total_size)

    # Most used assets
    stats["most_viewed"] = frappe.get_all(
        "Digital Asset",
        filters={"status": "Active"},
        fields=["name", "asset_title", "view_count"],
        order_by="view_count desc",
        limit=5
    )

    return stats
