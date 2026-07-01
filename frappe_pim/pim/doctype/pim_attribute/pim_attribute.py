"""
PIM Attribute Controller (Content Entity)

Manages attribute definitions for the PIM system with validation based on
attribute_type, locale support, and value type enforcement using the EAV pattern.

Configuration entity: PIM Attribute Type (defines validation rules and base types)
Content entity: PIM Attribute (this - defines product attribute structure)

Each PIM Attribute can reference a PIM Attribute Type for inherited validation
rules, or use its own data_type and constraints directly.

Standard data types (12): Text, Long Text, Integer, Float, Select,
Multi Select, Boolean, Date, Datetime, Link, Image, File
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, get_datetime
from typing import Any, Dict, List, Optional
import re
import json


# Mapping from data_type to EAV storage column in Product Attribute Value
DATA_TYPE_TO_VALUE_COLUMN = {
    "Text": "value_text",
    "Long Text": "value_long_text",
    "Integer": "value_int",
    "Float": "value_float",
    "Select": "value_text",
    "Multi Select": "value_json",
    "Boolean": "value_boolean",
    "Date": "value_date",
    "Datetime": "value_datetime",
    "Link": "value_link",
    "Image": "value_text",
    "File": "value_text",
}

# Mapping from data_type to base_type for validation
DATA_TYPE_TO_BASE_TYPE = {
    "Text": "String",
    "Long Text": "String",
    "Integer": "Integer",
    "Float": "Float",
    "Select": "String",
    "Multi Select": "JSON",
    "Boolean": "Boolean",
    "Date": "Date",
    "Datetime": "Datetime",
    "Link": "String",
    "Image": "String",
    "File": "String",
}

# Data types that typically support localization
LOCALIZABLE_DATA_TYPES = ("Text", "Long Text", "Select", "Multi Select")


class PIMAttribute(Document):

    def validate(self):
        self.validate_attribute_code()
        self.validate_attribute_type()
        self.validate_options()
        self.validate_linked_doctype()
        self.validate_value_constraints()
        self.validate_locale_settings()

    def validate_attribute_code(self):
        """Ensure attribute_code is URL-safe slug"""
        if not self.attribute_code:
            self.attribute_code = frappe.scrub(self.attribute_name)

        if not re.match(r'^[a-z][a-z0-9_]*$', self.attribute_code):
            frappe.throw(
                _("Attribute Code must start with a letter and contain only "
                  "lowercase letters, numbers, and underscores"),
                title=_("Invalid Attribute Code")
            )

    def validate_attribute_type(self):
        """Validate and check compatibility with PIM Attribute Type if linked.

        When an attribute_type (Link to PIM Attribute Type) is set,
        ensures the type exists and checks base_type compatibility with
        the attribute's data_type.
        """
        attribute_type = getattr(self, 'attribute_type', None)
        if not attribute_type:
            return

        if not frappe.db.exists("PIM Attribute Type", attribute_type):
            frappe.throw(
                _("Attribute Type '{0}' does not exist").format(attribute_type),
                title=_("Invalid Attribute Type")
            )

        # Check base_type compatibility
        type_doc = frappe.get_cached_doc("PIM Attribute Type", attribute_type)
        expected_base = DATA_TYPE_TO_BASE_TYPE.get(self.data_type)

        if expected_base and type_doc.base_type and expected_base != type_doc.base_type:
            frappe.msgprint(
                _("Data type '{0}' (base: {1}) may not be fully compatible with "
                  "attribute type '{2}' (base: {3}). Validation will use "
                  "attribute type rules.").format(
                    self.data_type, expected_base,
                    type_doc.type_name, type_doc.base_type
                ),
                indicator="orange"
            )

    def validate_options(self):
        """Validate options for Select/Multi Select types"""
        if self.data_type in ['Select', 'Multi Select']:
            # Options can be defined here OR via PIM Attribute Option DocType
            # So we don't require options to be set here
            if self.options:
                # Clean and deduplicate options if provided
                options_list = [opt.strip() for opt in self.options.split(',') if opt.strip()]
                if len(options_list) != len(set(options_list)):
                    frappe.throw(
                        _("Duplicate options found. Each option must be unique."),
                        title=_("Duplicate Options")
                    )
                self.options = ', '.join(options_list)

    def validate_linked_doctype(self):
        """Ensure linked_doctype is set for Link type"""
        if self.data_type == 'Link' and not self.linked_doctype:
            frappe.throw(
                _("Linked DocType is required for Link data type"),
                title=_("Missing Linked DocType")
            )

    def validate_value_constraints(self):
        """Validate min/max value constraints"""
        if self.data_type in ['Integer', 'Float']:
            if self.min_value is not None and self.max_value is not None:
                if self.min_value > self.max_value:
                    frappe.throw(
                        _("Minimum value cannot be greater than maximum value"),
                        title=_("Invalid Constraints")
                    )

    def validate_locale_settings(self):
        """Validate locale-related configuration.

        When is_localizable is enabled, informs the user if the data type
        is not typically localizable (non-text types).
        """
        is_localizable = getattr(self, 'is_localizable', False)
        if not is_localizable:
            return

        if self.data_type not in LOCALIZABLE_DATA_TYPES:
            frappe.msgprint(
                _("Attribute '{0}' with data type '{1}' is marked as localizable. "
                  "Non-text types typically don't need localization.").format(
                    self.attribute_name, self.data_type
                ),
                indicator="blue"
            )

    def before_save(self):
        """Clean up fields based on data type"""
        # Clear irrelevant fields based on data type
        if self.data_type not in ['Select', 'Multi Select']:
            self.options = None

        if self.data_type != 'Link':
            self.linked_doctype = None

        if self.data_type not in ['Integer', 'Float']:
            self.min_value = None
            self.max_value = None
            self.value_prefix = None
            self.value_suffix = None

        if self.data_type not in ['Text', 'Long Text']:
            self.max_length = None

    def on_update(self):
        """Invalidate caches on update"""
        self._invalidate_cache()

    def on_trash(self):
        """Prevent deletion if attribute is in use"""
        if self.is_standard:
            frappe.throw(
                _("Standard attributes cannot be deleted"),
                title=_("Cannot Delete")
            )

        # Check if attribute is used in any product attribute value
        usage_count = frappe.db.count("Product Attribute Value", {"attribute": self.name})
        if usage_count > 0:
            frappe.throw(
                _("Cannot delete attribute '{0}' as it is used in {1} product(s)").format(
                    self.attribute_name, usage_count
                ),
                title=_("Attribute In Use")
            )

        # Check if attribute is used in any attribute template
        try:
            template_count = frappe.db.count(
                "PIM Template Attribute", {"attribute": self.name}
            )
            if template_count > 0:
                frappe.throw(
                    _("Cannot delete attribute '{0}' as it is used in "
                      "{1} template(s)").format(
                        self.attribute_name, template_count
                    ),
                    title=_("Attribute In Use")
                )
        except Exception:
            pass  # Table may not exist yet

    def _invalidate_cache(self):
        """Invalidate attribute-related caches"""
        try:
            from frappe_pim.pim.utils.cache import invalidate_cache
            invalidate_cache("attribute", self.name)
        except (ImportError, AttributeError):
            pass

    # =========================================================================
    # EAV Pattern Support
    # =========================================================================

    def get_value_column(self) -> str:
        """Get the EAV storage column name for this attribute's data type.

        Maps the attribute's data_type to the corresponding value_* column
        in the Product Attribute Value child table.

        Returns:
            str: Column name (e.g., 'value_text', 'value_int')
        """
        return DATA_TYPE_TO_VALUE_COLUMN.get(self.data_type, "value_text")

    def get_base_type(self) -> str:
        """Get the base type for this attribute.

        If an attribute_type (PIM Attribute Type) is linked, uses its base_type.
        Otherwise, derives from the data_type mapping.

        Returns:
            str: Base type (e.g., 'String', 'Integer', 'Float')
        """
        attribute_type = getattr(self, 'attribute_type', None)
        if attribute_type:
            try:
                type_doc = frappe.get_cached_doc("PIM Attribute Type", attribute_type)
                return type_doc.base_type
            except Exception:
                pass

        return DATA_TYPE_TO_BASE_TYPE.get(self.data_type, "String")

    def get_eav_mapping(self) -> Dict[str, Any]:
        """Get complete EAV mapping configuration for this attribute.

        Returns a dict with all information needed to store and retrieve
        values in the EAV system (Product Attribute Value child table).

        Returns:
            dict with keys: value_column, base_type, data_type, is_localizable,
                is_required, has_options, min_value, max_value, max_length
        """
        return {
            "attribute": self.name,
            "attribute_name": self.attribute_name,
            "data_type": self.data_type,
            "base_type": self.get_base_type(),
            "value_column": self.get_value_column(),
            "is_localizable": bool(getattr(self, 'is_localizable', False)),
            "is_required": bool(getattr(self, 'is_required', False)),
            "has_options": self.data_type in ['Select', 'Multi Select'],
            "min_value": self.min_value if self.data_type in ['Integer', 'Float'] else None,
            "max_value": self.max_value if self.data_type in ['Integer', 'Float'] else None,
            "max_length": self.max_length if self.data_type in ['Text', 'Long Text'] else None,
            "value_prefix": getattr(self, 'value_prefix', None),
            "value_suffix": getattr(self, 'value_suffix', None),
        }

    # =========================================================================
    # Value Validation (EAV + Attribute Type delegation)
    # =========================================================================

    def validate_value(self, value: Any, locale: Optional[str] = None) -> Dict:
        """Validate a value against this attribute's constraints.

        Delegates to PIM Attribute Type's validate_value() if an attribute_type
        is linked. Otherwise, uses local data_type based validation.

        Supports locale-aware validation for localizable attributes.

        Args:
            value: The value to validate
            locale: Optional locale code for locale-scoped validation

        Returns:
            dict with 'valid' (bool), 'errors' (list of str), and
            'value_column' (str) for EAV storage
        """
        errors = []
        value_column = self.get_value_column()

        # Required check
        is_required = getattr(self, 'is_required', False)
        if is_required and (value is None or value == ''):
            errors.append(
                _("Value is required for attribute '{0}'").format(self.attribute_name)
            )
            return {"valid": False, "errors": errors, "value_column": value_column}

        if value is None or value == '':
            return {"valid": True, "errors": [], "value_column": value_column}

        # Locale validation
        is_localizable = getattr(self, 'is_localizable', False)
        if locale and not is_localizable:
            errors.append(
                _("Attribute '{0}' does not support localization").format(
                    self.attribute_name
                )
            )

        # Try to delegate to PIM Attribute Type if linked
        attribute_type = getattr(self, 'attribute_type', None)
        if attribute_type:
            type_result = self._validate_via_attribute_type(attribute_type, value)
            if type_result:
                errors.extend(type_result.get("errors", []))
                return {
                    "valid": len(errors) == 0,
                    "errors": errors,
                    "value_column": value_column
                }

        # Local validation based on data_type
        type_errors = self._validate_by_data_type(value)
        errors.extend(type_errors)

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "value_column": value_column
        }

    def _validate_via_attribute_type(
        self, attribute_type: str, value: Any
    ) -> Optional[Dict]:
        """Delegate validation to PIM Attribute Type.

        Args:
            attribute_type: Name of the PIM Attribute Type
            value: Value to validate

        Returns:
            Validation result dict, or None if delegation fails
        """
        try:
            type_doc = frappe.get_cached_doc("PIM Attribute Type", attribute_type)
            return type_doc.validate_value(value)
        except Exception:
            return None

    def _validate_by_data_type(self, value: Any) -> List[str]:
        """Validate value based on the attribute's data_type.

        Covers all 12 data types: Text, Long Text, Integer, Float, Select,
        Multi Select, Boolean, Date, Datetime, Link, Image, File.

        Args:
            value: The value to validate

        Returns:
            List of error messages (empty if valid)
        """
        errors = []

        if self.data_type in ['Select', 'Multi Select']:
            valid_options = self.get_parsed_options()
            if self.data_type == 'Select':
                if value not in valid_options:
                    errors.append(_("Invalid option: {0}").format(value))
            else:
                # Multi Select: value can be comma-separated or JSON array
                values = self._parse_multi_value(value)
                invalid = [v for v in values if v not in valid_options]
                if invalid:
                    errors.append(
                        _("Invalid options: {0}").format(', '.join(invalid))
                    )

        elif self.data_type == 'Integer':
            try:
                int_val = int(value)
                if self.min_value is not None and int_val < self.min_value:
                    errors.append(
                        _("Value must be at least {0}").format(int(self.min_value))
                    )
                if self.max_value is not None and int_val > self.max_value:
                    errors.append(
                        _("Value must be at most {0}").format(int(self.max_value))
                    )
            except (ValueError, TypeError):
                errors.append(_("Value must be an integer"))

        elif self.data_type == 'Float':
            try:
                float_val = float(value)
                if self.min_value is not None and float_val < self.min_value:
                    errors.append(
                        _("Value must be at least {0}").format(self.min_value)
                    )
                if self.max_value is not None and float_val > self.max_value:
                    errors.append(
                        _("Value must be at most {0}").format(self.max_value)
                    )
            except (ValueError, TypeError):
                errors.append(_("Value must be a number"))

        elif self.data_type in ['Text', 'Long Text']:
            str_val = str(value)
            if self.max_length and len(str_val) > self.max_length:
                errors.append(
                    _("Value exceeds maximum length of {0}").format(self.max_length)
                )

        elif self.data_type == 'Boolean':
            if str(value).lower() not in ('true', 'false', '1', '0', 'yes', 'no'):
                errors.append(_("Value must be a boolean (true/false)"))

        elif self.data_type == 'Date':
            try:
                if isinstance(value, str):
                    getdate(value)
            except Exception:
                errors.append(_("Value must be a valid date (YYYY-MM-DD)"))

        elif self.data_type == 'Datetime':
            try:
                if isinstance(value, str):
                    get_datetime(value)
            except Exception:
                errors.append(
                    _("Value must be a valid datetime (YYYY-MM-DD HH:MM:SS)")
                )

        elif self.data_type == 'Link':
            if self.linked_doctype:
                if not frappe.db.exists(self.linked_doctype, value):
                    errors.append(
                        _("'{0}' is not a valid {1}").format(value, self.linked_doctype)
                    )

        # Image and File types accept any string (URL/path)
        # No additional validation needed

        return errors

    # =========================================================================
    # Value Coercion
    # =========================================================================

    def coerce_value(self, value: Any) -> Any:
        """Coerce a value to the correct Python type for this attribute.

        If an attribute_type is linked, delegates to its get_coerced_value().
        Otherwise, coerces based on data_type.

        Args:
            value: The raw value to coerce

        Returns:
            The coerced value, or the original if coercion fails
        """
        if value is None or value == '':
            return value

        # Try attribute_type delegation first
        attribute_type = getattr(self, 'attribute_type', None)
        if attribute_type:
            try:
                type_doc = frappe.get_cached_doc("PIM Attribute Type", attribute_type)
                return type_doc.get_coerced_value(value)
            except Exception:
                pass

        # Local coercion based on data_type
        try:
            if self.data_type == 'Integer':
                return int(value)
            elif self.data_type == 'Float':
                return float(value)
            elif self.data_type == 'Boolean':
                return str(value).lower() in ('true', '1', 'yes')
            elif self.data_type == 'Date':
                return str(getdate(value)) if isinstance(value, str) else value
            elif self.data_type == 'Datetime':
                return str(get_datetime(value)) if isinstance(value, str) else value
            elif self.data_type == 'Multi Select':
                return self._parse_multi_value(value)
            else:
                return str(value)
        except (ValueError, TypeError):
            return value

    # =========================================================================
    # Options Support
    # =========================================================================

    def get_parsed_options(self) -> List[str]:
        """Return options as a list - combines inline options and
        PIM Attribute Option records.

        Returns:
            List of option values, deduplicated and ordered
        """
        options = []

        # Get inline options (comma-separated in options field)
        if self.options:
            options.extend(
                [opt.strip() for opt in self.options.split(',') if opt.strip()]
            )

        # Get options from PIM Attribute Option DocType
        try:
            attribute_options = frappe.get_all(
                "PIM Attribute Option",
                filters={"attribute": self.name, "is_active": 1},
                fields=["option_value"],
                order_by="sort_order"
            )
            for opt in attribute_options:
                if opt.option_value and opt.option_value not in options:
                    options.append(opt.option_value)
        except Exception:
            pass  # Table may not exist yet

        return options

    # =========================================================================
    # Locale Support
    # =========================================================================

    def get_locale_config(self) -> Dict[str, Any]:
        """Get locale configuration for this attribute.

        Returns configuration relevant to multi-locale value storage
        in the EAV system.

        Returns:
            dict with is_localizable, supported_locales, and default_locale info
        """
        is_localizable = bool(getattr(self, 'is_localizable', False))

        config = {
            "is_localizable": is_localizable,
            "attribute": self.name,
            "attribute_name": self.attribute_name,
        }

        if is_localizable:
            try:
                locales = frappe.get_all(
                    "PIM Locale",
                    filters={"enabled": 1},
                    fields=["name", "locale_name", "language_code", "is_default"],
                    order_by="is_default desc, locale_name"
                )
                config["supported_locales"] = [loc.name for loc in locales]
                config["default_locale"] = next(
                    (loc.name for loc in locales if loc.is_default), None
                )
            except Exception:
                config["supported_locales"] = []
                config["default_locale"] = None

        return config

    def is_value_localizable(self) -> bool:
        """Check if this attribute supports locale-scoped values.

        Returns:
            True if the attribute is localizable
        """
        return bool(getattr(self, 'is_localizable', False))

    # =========================================================================
    # Helpers
    # =========================================================================

    def _parse_multi_value(self, value: Any) -> List[str]:
        """Parse a multi-select value to a list of strings.

        Handles both comma-separated strings and JSON arrays.

        Args:
            value: The value to parse

        Returns:
            List of individual option values
        """
        if isinstance(value, list):
            return [str(v).strip() for v in value if v]

        if isinstance(value, str):
            # Try JSON array first
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return [str(v).strip() for v in parsed if v]
            except (json.JSONDecodeError, TypeError):
                pass
            # Fall back to comma-separated
            return [v.strip() for v in value.split(',') if v.strip()]

        return [str(value)]

    def get_display_config(self) -> Dict[str, Any]:
        """Get display configuration for this attribute.

        Returns settings used by UI components for rendering.

        Returns:
            dict with display-related configuration
        """
        return {
            "attribute": self.name,
            "attribute_name": self.attribute_name,
            "data_type": self.data_type,
            "is_filterable": bool(getattr(self, 'is_filterable', False)),
            "is_searchable": bool(getattr(self, 'is_searchable', False)),
            "show_in_grid": bool(getattr(self, 'show_in_grid', True)),
            "sort_order": getattr(self, 'sort_order', 0),
            "weight_in_completeness": getattr(self, 'weight_in_completeness', 1),
            "value_prefix": getattr(self, 'value_prefix', None),
            "value_suffix": getattr(self, 'value_suffix', None),
        }


# =============================================================================
# Whitelisted API Functions
# =============================================================================

@frappe.whitelist()
def get_attribute_options(attribute: str) -> Dict:
    """Get options for a Select/Multi Select attribute.

    Args:
        attribute: PIM Attribute name

    Returns:
        dict with data_type, options, linked_doctype, is_required,
        value_column, and is_localizable
    """
    doc = frappe.get_doc("PIM Attribute", attribute)
    return {
        "data_type": doc.data_type,
        "options": doc.get_parsed_options(),
        "linked_doctype": doc.linked_doctype,
        "is_required": doc.is_required,
        "value_column": doc.get_value_column(),
        "is_localizable": doc.is_value_localizable(),
    }


@frappe.whitelist()
def validate_attribute_value(
    attribute: str,
    value: Any,
    locale: Optional[str] = None
) -> Dict:
    """Validate a value against attribute constraints.

    Delegates to PIM Attribute Type validation when available,
    with fallback to local data_type validation.

    Args:
        attribute: PIM Attribute name
        value: The value to validate
        locale: Optional locale code for locale-scoped validation

    Returns:
        dict with 'valid' (bool), 'errors' (list), and 'value_column' (str)
    """
    doc = frappe.get_doc("PIM Attribute", attribute)
    return doc.validate_value(value, locale=locale)


@frappe.whitelist()
def get_attribute_eav_mapping(attribute: str) -> Dict:
    """Get the EAV mapping configuration for an attribute.

    Returns information about how values for this attribute should be
    stored in the Product Attribute Value child table.

    Args:
        attribute: PIM Attribute name

    Returns:
        dict with value_column, base_type, data_type, and constraint info
    """
    doc = frappe.get_doc("PIM Attribute", attribute)
    return doc.get_eav_mapping()


@frappe.whitelist()
def get_attributes_by_group(group: Optional[str] = None) -> List[Dict]:
    """Get attributes filtered by group with EAV mapping info.

    Args:
        group: PIM Attribute Group name (optional, returns all if not specified)

    Returns:
        List of attribute dicts with core fields and EAV mapping
    """
    if not frappe.has_permission("PIM Attribute", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    filters = {}
    if group:
        filters["attribute_group"] = group

    attributes = frappe.get_all(
        "PIM Attribute",
        filters=filters,
        fields=[
            "name", "attribute_name", "attribute_code", "data_type",
            "attribute_group", "is_required", "is_localizable",
            "is_filterable", "is_searchable", "sort_order",
            "weight_in_completeness"
        ],
        order_by="sort_order, attribute_name"
    )

    # Enrich with EAV column mapping
    for attr in attributes:
        attr["value_column"] = DATA_TYPE_TO_VALUE_COLUMN.get(
            attr["data_type"], "value_text"
        )
        attr["base_type"] = DATA_TYPE_TO_BASE_TYPE.get(
            attr["data_type"], "String"
        )

    return attributes


@frappe.whitelist()
def get_attribute_metadata(attribute: str) -> Dict:
    """Get comprehensive metadata for an attribute.

    Returns all configuration needed for UI rendering and EAV storage.

    Args:
        attribute: PIM Attribute name

    Returns:
        dict with attribute metadata, EAV mapping, locale config,
        display config, and options
    """
    doc = frappe.get_doc("PIM Attribute", attribute)

    result = {
        "eav_mapping": doc.get_eav_mapping(),
        "locale_config": doc.get_locale_config(),
        "display_config": doc.get_display_config(),
    }

    if doc.data_type in ['Select', 'Multi Select']:
        result["options"] = doc.get_parsed_options()
    else:
        result["options"] = []

    return result


@frappe.whitelist()
def coerce_attribute_value(attribute: str, value: Any) -> Any:
    """Coerce a value to the correct type for an attribute.

    Args:
        attribute: PIM Attribute name
        value: The raw value to coerce

    Returns:
        The coerced value
    """
    doc = frappe.get_doc("PIM Attribute", attribute)
    return doc.coerce_value(value)
