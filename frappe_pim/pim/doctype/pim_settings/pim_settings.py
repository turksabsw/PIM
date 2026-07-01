"""
PIM Settings Controller
Global configuration for Product Information Management
"""

import frappe
from frappe import _
from frappe.model.document import Document
import re


class PIMSettings(Document):
    def validate(self):
        self.validate_gln()
        self.validate_thumbnail_size()
        self.validate_quality_score()
        self.validate_allowed_formats()

    def validate_gln(self):
        """Validate GLN format if provided"""
        if self.gln:
            # GLN must be exactly 13 digits
            if not re.match(r'^\d{13}$', self.gln):
                frappe.throw(
                    _("GLN must be exactly 13 digits"),
                    title=_("Invalid GLN")
                )

            # Validate check digit
            if not self._validate_gln_check_digit(self.gln):
                frappe.throw(
                    _("Invalid GLN check digit"),
                    title=_("Invalid GLN")
                )

    def _validate_gln_check_digit(self, gln):
        """Validate GLN check digit using GS1 algorithm"""
        digits = [int(d) for d in gln]
        # Multiply digits by alternating 1 and 3, starting from right
        total = 0
        for i, digit in enumerate(digits[:-1]):
            multiplier = 3 if (12 - i) % 2 == 0 else 1
            total += digit * multiplier

        check_digit = (10 - (total % 10)) % 10
        return check_digit == digits[-1]

    def validate_thumbnail_size(self):
        """Ensure thumbnail size is within reasonable bounds"""
        if self.auto_generate_thumbnails and self.thumbnail_size:
            if self.thumbnail_size < 50:
                frappe.throw(
                    _("Thumbnail size must be at least 50 pixels"),
                    title=_("Invalid Thumbnail Size")
                )
            if self.thumbnail_size > 500:
                frappe.throw(
                    _("Thumbnail size cannot exceed 500 pixels"),
                    title=_("Invalid Thumbnail Size")
                )

    def validate_quality_score(self):
        """Validate quality score settings"""
        if self.enable_quality_scoring and self.minimum_quality_score:
            if self.minimum_quality_score < 0 or self.minimum_quality_score > 100:
                frappe.throw(
                    _("Minimum quality score must be between 0 and 100"),
                    title=_("Invalid Quality Score")
                )

    def validate_allowed_formats(self):
        """Validate allowed image formats"""
        if self.allowed_image_formats:
            formats = [f.strip().lower() for f in self.allowed_image_formats.split(',')]
            valid_formats = ['jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp', 'tiff', 'svg']

            for fmt in formats:
                if fmt and fmt not in valid_formats:
                    frappe.throw(
                        _("Invalid image format: {0}. Allowed: {1}").format(
                            fmt, ', '.join(valid_formats)
                        ),
                        title=_("Invalid Format")
                    )

            # Normalize the formats
            self.allowed_image_formats = ','.join(formats)


def get_pim_settings():
    """Get PIM Settings singleton

    Returns:
        Document: PIM Settings document
    """
    return frappe.get_single("PIM Settings")


def get_setting(field_name, default=None):
    """Get a specific PIM setting value

    Args:
        field_name: Name of the setting field
        default: Default value if setting is not found

    Returns:
        The setting value or default
    """
    try:
        settings = frappe.get_cached_doc("PIM Settings")
        return getattr(settings, field_name, default)
    except Exception:
        return default


@frappe.whitelist()
def is_erp_sync_enabled():
    """Check if ERP sync is enabled

    Returns:
        bool: True if ERP sync is enabled
    """
    return bool(get_setting("enable_erp_sync", True))


@frappe.whitelist()
def is_ai_enrichment_enabled():
    """Check if AI enrichment is enabled

    Returns:
        bool: True if AI enrichment is enabled and configured
    """
    settings = get_pim_settings()
    return bool(
        settings.enable_ai_enrichment and
        settings.ai_provider and
        settings.ai_api_key
    )


@frappe.whitelist()
def get_ai_config():
    """Get AI configuration for enrichment tasks

    Returns:
        dict: AI configuration or None if not enabled
    """
    settings = get_pim_settings()

    if not settings.enable_ai_enrichment:
        return None

    return {
        "provider": settings.ai_provider,
        "model": settings.ai_model,
        "require_approval": settings.ai_require_approval
    }


@frappe.whitelist()
def get_quality_config():
    """Get data quality configuration

    Returns:
        dict: Quality configuration
    """
    settings = get_pim_settings()

    return {
        "enabled": settings.enable_quality_scoring,
        "minimum_score": settings.minimum_quality_score or 60,
        "block_publish": settings.block_publish_below_minimum,
        "auto_scan": settings.auto_scan_on_save
    }


@frappe.whitelist()
def get_media_config():
    """Get media settings configuration

    Returns:
        dict: Media configuration
    """
    settings = get_pim_settings()

    allowed_formats = []
    if settings.allowed_image_formats:
        allowed_formats = [f.strip() for f in settings.allowed_image_formats.split(',')]

    return {
        "auto_thumbnails": settings.auto_generate_thumbnails,
        "thumbnail_size": settings.thumbnail_size or 150,
        "max_size_mb": settings.max_image_size_mb or 10,
        "allowed_formats": allowed_formats
    }


@frappe.whitelist()
def test_ai_connection():
    """Test the AI provider connection

    Returns:
        dict: Connection test result
    """
    settings = get_pim_settings()

    if not settings.enable_ai_enrichment:
        return {"status": "error", "message": _("AI enrichment is not enabled")}

    if not settings.ai_provider:
        return {"status": "error", "message": _("AI provider is not configured")}

    if not settings.ai_api_key:
        return {"status": "error", "message": _("AI API key is not configured")}

    # Get the actual API key (decrypted)
    api_key = settings.get_password("ai_api_key")

    try:
        # Test connection based on provider
        if settings.ai_provider == "OpenAI":
            return _test_openai_connection(api_key, settings.ai_model)
        elif settings.ai_provider == "Anthropic":
            return _test_anthropic_connection(api_key, settings.ai_model)
        elif settings.ai_provider == "Google Gemini":
            return _test_gemini_connection(api_key, settings.ai_model)
        elif settings.ai_provider == "Azure OpenAI":
            return _test_azure_connection(api_key, settings.ai_model)
        else:
            return {"status": "error", "message": _("Unknown AI provider")}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _test_openai_connection(api_key, model):
    """Test OpenAI API connection"""
    import requests

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.get(
            "https://api.openai.com/v1/models",
            headers=headers,
            timeout=10
        )

        if response.status_code == 200:
            return {"status": "success", "message": _("OpenAI connection successful")}
        elif response.status_code == 401:
            return {"status": "error", "message": _("Invalid API key")}
        else:
            return {"status": "error", "message": f"HTTP {response.status_code}"}
    except requests.exceptions.Timeout:
        return {"status": "error", "message": _("Connection timed out")}
    except requests.exceptions.RequestException as e:
        return {"status": "error", "message": str(e)}


def _test_anthropic_connection(api_key, model):
    """Test Anthropic API connection"""
    import requests

    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01"
    }

    try:
        # Simple test - create a minimal message request
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json={
                "model": model or "claude-3-haiku-20240307",
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "test"}]
            },
            timeout=10
        )

        if response.status_code == 200:
            return {"status": "success", "message": _("Anthropic connection successful")}
        elif response.status_code == 401:
            return {"status": "error", "message": _("Invalid API key")}
        else:
            return {"status": "error", "message": f"HTTP {response.status_code}"}
    except requests.exceptions.Timeout:
        return {"status": "error", "message": _("Connection timed out")}
    except requests.exceptions.RequestException as e:
        return {"status": "error", "message": str(e)}


def _test_gemini_connection(api_key, model):
    """Test Google Gemini API connection"""
    import requests

    try:
        response = requests.get(
            f"https://generativelanguage.googleapis.com/v1/models?key={api_key}",
            timeout=10
        )

        if response.status_code == 200:
            return {"status": "success", "message": _("Google Gemini connection successful")}
        elif response.status_code == 400 or response.status_code == 403:
            return {"status": "error", "message": _("Invalid API key")}
        else:
            return {"status": "error", "message": f"HTTP {response.status_code}"}
    except requests.exceptions.Timeout:
        return {"status": "error", "message": _("Connection timed out")}
    except requests.exceptions.RequestException as e:
        return {"status": "error", "message": str(e)}


def _test_azure_connection(api_key, model):
    """Test Azure OpenAI connection - requires additional configuration"""
    return {
        "status": "info",
        "message": _("Azure OpenAI requires endpoint configuration. Please verify settings manually.")
    }
