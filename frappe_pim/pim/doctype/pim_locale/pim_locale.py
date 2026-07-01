"""
PIM Locale Controller
Manages localization support for PIM content (3D scoped attributes - locale dimension)
"""

import frappe
from frappe import _
from frappe.model.document import Document
from typing import Optional, List
import re


class PIMLocale(Document):
    def validate(self):
        self.validate_locale_code()
        self.validate_language_code()
        self.validate_country_code()
        self.validate_fallback_locale()
        self.validate_default_locale()

    def validate_locale_code(self):
        """Validate locale_code follows BCP 47 format (simplified)"""
        if not self.locale_code:
            # Auto-generate from language and country
            if self.language_code:
                self.locale_code = self.language_code.lower()
                if self.country_code:
                    self.locale_code += f"_{self.country_code.upper()}"

        # Validate format: language_COUNTRY or language (e.g., en_US, fr_FR, de)
        if not re.match(r'^[a-z]{2,3}(_[A-Z]{2})?$', self.locale_code):
            frappe.throw(
                _("Locale Code must be in format 'xx' or 'xx_XX' (e.g., en, en_US, fr_FR)"),
                title=_("Invalid Locale Code")
            )

    def validate_language_code(self):
        """Validate language_code is ISO 639-1 format"""
        if self.language_code:
            self.language_code = self.language_code.lower()
            if not re.match(r'^[a-z]{2,3}$', self.language_code):
                frappe.throw(
                    _("Language Code must be 2-3 lowercase letters (ISO 639-1 format)"),
                    title=_("Invalid Language Code")
                )

    def validate_country_code(self):
        """Validate country_code is ISO 3166-1 alpha-2 format"""
        if self.country_code:
            self.country_code = self.country_code.upper()
            if not re.match(r'^[A-Z]{2}$', self.country_code):
                frappe.throw(
                    _("Country Code must be 2 uppercase letters (ISO 3166-1 alpha-2 format)"),
                    title=_("Invalid Country Code")
                )

    def validate_fallback_locale(self):
        """Validate fallback locale is not circular"""
        if self.fallback_locale:
            if self.fallback_locale == self.name:
                frappe.throw(
                    _("Fallback Locale cannot be the same as this locale"),
                    title=_("Invalid Fallback Locale")
                )

            # Check for circular fallback chains
            visited = {self.name}
            current = self.fallback_locale
            while current:
                if current in visited:
                    frappe.throw(
                        _("Circular fallback chain detected. Locale '{0}' would create a loop.").format(current),
                        title=_("Circular Fallback")
                    )
                visited.add(current)
                current = frappe.db.get_value("PIM Locale", current, "fallback_locale")

    def validate_default_locale(self):
        """Ensure only one default locale exists"""
        if self.is_default:
            existing_default = frappe.db.get_value(
                "PIM Locale",
                {"is_default": 1, "name": ["!=", self.name]},
                "name"
            )
            if existing_default:
                # Automatically unset the previous default
                frappe.db.set_value("PIM Locale", existing_default, "is_default", 0)
                frappe.msgprint(
                    _("Locale '{0}' is no longer the default locale.").format(existing_default),
                    indicator="orange"
                )

    def on_update(self):
        """Handle post-update actions"""
        self.update_statistics()
        self.invalidate_cache()

    def on_trash(self):
        """Cleanup before deletion"""
        # Check if this locale is used by any product attribute values
        try:
            attr_count = frappe.db.count("Product Attribute Value", {"locale": self.name})
            if attr_count > 0:
                frappe.throw(
                    _("Cannot delete locale '{0}' as it is used by {1} product attribute value(s). "
                      "Please remove or reassign the localized content first.").format(
                        self.locale_name, attr_count
                    ),
                    title=_("Locale In Use")
                )
        except Exception:
            # Product Attribute Value DocType may not exist yet
            pass

        # Check if used as fallback by other locales
        fallback_count = frappe.db.count("PIM Locale", {"fallback_locale": self.name})
        if fallback_count > 0:
            frappe.throw(
                _("Cannot delete locale '{0}' as it is used as fallback by {1} other locale(s). "
                  "Please update those locales first.").format(
                    self.locale_name, fallback_count
                ),
                title=_("Locale In Use")
            )

        # Warn if this is the default locale
        if self.is_default:
            frappe.throw(
                _("Cannot delete the default locale '{0}'. "
                  "Please set another locale as default first.").format(self.locale_name),
                title=_("Cannot Delete Default Locale")
            )

    def update_statistics(self):
        """Update statistical fields"""
        try:
            # Count products with localized content
            count = frappe.db.sql("""
                SELECT COUNT(DISTINCT parent)
                FROM `tabProduct Attribute Value`
                WHERE locale = %s
            """, (self.name,))[0][0] or 0

            if self.products_with_content != count:
                frappe.db.set_value(
                    "PIM Locale", self.name,
                    "products_with_content", count,
                    update_modified=False
                )
        except Exception:
            # Product Attribute Value DocType may not exist yet
            pass

    def invalidate_cache(self):
        """Clear relevant caches"""
        try:
            frappe.cache().delete_key(f"pim:locale:{self.name}")
            frappe.cache().delete_key("pim:all_locales")
            frappe.cache().delete_key("pim:default_locale")
            frappe.cache().delete_key("pim:enabled_locales")
        except Exception:
            pass

    def get_fallback_chain(self) -> List[str]:
        """Get the complete fallback chain for this locale

        Returns:
            List of locale names in fallback order (excluding self)
        """
        chain = []
        visited = {self.name}
        current = self.fallback_locale

        while current and current not in visited:
            chain.append(current)
            visited.add(current)
            current = frappe.db.get_value("PIM Locale", current, "fallback_locale")

        return chain


@frappe.whitelist()
def get_locales(enabled_only: bool = True) -> List[dict]:
    """Get all PIM locales with optional filters

    Args:
        enabled_only: If True, return only enabled locales

    Returns:
        List of locale dictionaries
    """
    filters = {}
    if enabled_only:
        filters["enabled"] = 1

    return frappe.get_all(
        "PIM Locale",
        filters=filters,
        fields=[
            "name", "locale_name", "locale_code", "language_code",
            "country_code", "enabled", "is_default", "text_direction",
            "fallback_locale", "content_priority"
        ],
        order_by="content_priority desc, locale_name asc"
    )


@frappe.whitelist()
def get_default_locale() -> Optional[str]:
    """Get the default locale name

    Returns:
        Default locale name or None if not set
    """
    # Try to get from cache first
    cached = frappe.cache().get_value("pim:default_locale")
    if cached:
        return cached

    default = frappe.db.get_value(
        "PIM Locale",
        {"is_default": 1, "enabled": 1},
        "name"
    )

    if default:
        frappe.cache().set_value("pim:default_locale", default, expires_in_sec=3600)

    return default


@frappe.whitelist()
def get_locale_fallback_chain(locale: str) -> List[str]:
    """Get the fallback chain for a locale

    Args:
        locale: Locale name

    Returns:
        List of locale names in fallback order
    """
    doc = frappe.get_doc("PIM Locale", locale)
    return doc.get_fallback_chain()


@frappe.whitelist()
def resolve_locale(preferred_locale: Optional[str] = None, channel: Optional[str] = None) -> str:
    """Resolve the best locale to use based on preferences and availability

    Args:
        preferred_locale: User's preferred locale
        channel: Sales channel that may have locale restrictions

    Returns:
        Resolved locale name
    """
    # If preferred locale is specified and enabled, use it
    if preferred_locale:
        is_enabled = frappe.db.get_value("PIM Locale", preferred_locale, "enabled")
        if is_enabled:
            # If channel is specified, check if locale is supported
            if channel:
                channel_locales = get_channel_locales(channel)
                if preferred_locale in channel_locales:
                    return preferred_locale
            else:
                return preferred_locale

    # Try channel's default locale if specified
    if channel:
        channel_default = frappe.db.get_value("Channel", channel, "default_locale")
        if channel_default:
            return channel_default

    # Fall back to system default locale
    default = get_default_locale()
    if default:
        return default

    # Last resort: return first enabled locale
    first_locale = frappe.db.get_value(
        "PIM Locale",
        {"enabled": 1},
        "name",
        order_by="content_priority desc"
    )

    if first_locale:
        return first_locale

    frappe.throw(
        _("No enabled locales found. Please configure at least one locale in PIM Locale."),
        title=_("No Locales Available")
    )


def get_channel_locales(channel: str) -> List[str]:
    """Get list of locales supported by a channel

    Args:
        channel: Channel name

    Returns:
        List of locale names supported by the channel
    """
    try:
        # Get channel's supported locales from child table
        locales = frappe.get_all(
            "Channel Locale",
            filters={"parent": channel},
            pluck="locale"
        )
        return locales if locales else []
    except Exception:
        # Channel Locale child table may not exist yet
        return []


@frappe.whitelist()
def set_default_locale(locale: str) -> None:
    """Set a locale as the default

    Args:
        locale: Locale name to set as default
    """
    frappe.only_for(["System Manager", "PIM Manager"])

    # Validate locale exists and is enabled
    doc = frappe.get_doc("PIM Locale", locale)
    if not doc.enabled:
        frappe.throw(
            _("Cannot set disabled locale '{0}' as default").format(locale),
            title=_("Invalid Locale")
        )

    # Unset current default
    current_default = get_default_locale()
    if current_default and current_default != locale:
        frappe.db.set_value("PIM Locale", current_default, "is_default", 0)

    # Set new default
    frappe.db.set_value("PIM Locale", locale, "is_default", 1)

    # Clear cache
    frappe.cache().delete_key("pim:default_locale")

    frappe.msgprint(
        _("Locale '{0}' is now the default locale.").format(doc.locale_name),
        indicator="green"
    )
