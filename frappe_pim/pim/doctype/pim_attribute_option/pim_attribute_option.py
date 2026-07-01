"""
PIM Attribute Option Controller
Defines option values for select/multiselect type attributes
"""

import re
import frappe
from frappe import _
from frappe.model.document import Document


class PIMAttributeOption(Document):

    def validate(self):
        self.validate_option_value()
        self.validate_attribute_supports_options()
        self.validate_unique_combination()
        self.validate_single_default()

    def validate_option_value(self):
        """Ensure option_value is a valid identifier"""
        if not self.option_value:
            # Auto-generate from label if not provided
            self.option_value = frappe.scrub(self.option_label)

        # Clean up the option value to be URL-safe
        if not re.match(r'^[a-z0-9][a-z0-9_-]*$', self.option_value, re.IGNORECASE):
            frappe.throw(
                _("Option Value must start with a letter or number and contain only letters, numbers, underscores, and hyphens"),
                title=_("Invalid Option Value")
            )

    def validate_attribute_supports_options(self):
        """Ensure the linked attribute type supports options"""
        if not self.attribute:
            return

        try:
                attribute_doc = frappe.get_cached_doc("PIM Attribute", self.attribute)
                # data_type is a Select field with values like 'Text', 'Number', 'Select', 'Multi Select', etc.
                data_type = attribute_doc.get("data_type") or ""
                
                # Only Select and Multi Select types support options
                option_types = ["Select", "Multi Select", "Multiselect"]
                if data_type and data_type not in option_types:
                    frappe.throw(
                        _("Attribute '{0}' has data type '{1}' which does not support options. Only Select/Multi Select types can have options.").format(
                            self.attribute, data_type
                        ),
                        title=_("Invalid Attribute Type")
                    )
        except frappe.DoesNotExistError:
                # Attribute may not exist yet during creation flow
                pass

    def validate_unique_combination(self):
        """Ensure option_value is unique within the same attribute"""
        if not self.attribute or not self.option_value:
            return

        filters = {
        "attribute": self.attribute,
        "option_value": self.option_value,
        "name": ["!=", self.name or ""]
        }

        duplicate = frappe.db.exists("PIM Attribute Option", filters)
        if duplicate:
            frappe.throw(
                _("Option value '{0}' already exists for attribute '{1}'").format(
                    self.option_value, self.attribute
                ),
                title=_("Duplicate Option Value")
        )

    def validate_single_default(self):
        """Ensure only one default option per attribute"""
        if not self.is_default or not self.attribute:
            return

        filters = {
        "attribute": self.attribute,
        "is_default": 1,
        "name": ["!=", self.name or ""]
        }

        existing_default = frappe.db.get_value("PIM Attribute Option", filters, "name")
        if existing_default:
            # Unset the previous default
            frappe.db.set_value("PIM Attribute Option", existing_default, "is_default", 0)
        frappe.msgprint(
                _("Previous default option '{0}' has been unset").format(existing_default),
                indicator="orange"
        )

    def before_save(self):
        """Set defaults and clean up data"""
        # Auto-set label from value if not provided
        if not self.option_label and self.option_value:
            self.option_label = self.option_value.replace("_", " ").replace("-", " ").title()

        # Clean color code format
        if self.color_code:
            self.color_code = self.color_code.upper()
        if not self.color_code.startswith("#"):
                self.color_code = "#" + self.color_code

    def on_update(self):
        """Invalidate cache on update"""
        self._invalidate_cache()

    def on_trash(self):
        """Prevent deletion of in-use options"""
        # Check if option is used in product attribute values
        try:
            usage_count = frappe.db.count(
                "Product Attribute Value",
                {"attribute_value": self.option_value, "attribute": self.attribute}
            )
            if usage_count > 0:
                frappe.throw(
                    _("Cannot delete option '{0}' as it is used by {1} product(s)").format(
                        self.option_label, usage_count
                    ),
                    title=_("Option In Use")
                )
        except Exception:
            pass  # Table may not exist

    def _invalidate_cache(self):
        """Invalidate attribute option-related caches"""
        try:
            from frappe_pim.pim.utils.cache import invalidate_cache
            invalidate_cache("attribute_option", self.name)
            if self.attribute:
                invalidate_cache("attribute", self.attribute)
        except (ImportError, AttributeError):
            pass
    def get_attribute_options(attribute, include_inactive=False):
        """Get all options for a specific attribute

        Args:
            attribute: Name of the PIM Attribute
        include_inactive: If True, include inactive options

        Returns:
            List of option dicts with value, label, and display properties
        """
        import frappe

        if not frappe.has_permission("PIM Attribute Option", "read"):
            frappe.throw("Not permitted", frappe.PermissionError)

        filters = {"attribute": attribute}
        if not include_inactive:
            filters["is_active"] = 1

        return frappe.get_all(
        "PIM Attribute Option",
        filters=filters,
        fields=[
        "name", "option_value", "option_label", "sort_order",
        "color_code", "icon", "image", "is_default", "is_active",
        "description", "external_code"
        ],
        order_by="sort_order, option_label"
        )

    def get_default_option(attribute):
        """Get the default option for an attribute

        Args:
            attribute: Name of the PIM Attribute

        Returns:
            Option dict or None if no default
        """
        import frappe

        return frappe.db.get_value(
        "PIM Attribute Option",
        {"attribute": attribute, "is_default": 1, "is_active": 1},
        ["name", "option_value", "option_label", "color_code"],
        as_dict=True
        )

    def validate_option_value(attribute, value):
        """Validate that a value is a valid option for an attribute

        Args:
            attribute: Name of the PIM Attribute
        value: The option value to validate

        Returns:
            dict with 'valid' (bool) and 'option' (option details if valid)
        """
        import frappe

        option = frappe.db.get_value(
        "PIM Attribute Option",
        {"attribute": attribute, "option_value": value, "is_active": 1},
        ["name", "option_value", "option_label", "color_code"],
        as_dict=True
        )

        if option:
            return {"valid": True, "option": option}
        else:
            return {"valid": False, "option": None}

    def bulk_create_options(attribute, options):
        """Bulk create options for an attribute

        Args:
            attribute: Name of the PIM Attribute
        options: List of dicts with option_value, option_label, and optional fields

        Returns:
            List of created option names
        """
        import frappe

        if not frappe.has_permission("PIM Attribute Option", "create"):
            frappe.throw("Not permitted", frappe.PermissionError)

        created = []
        for idx, opt in enumerate(options):
            doc = frappe.new_doc("PIM Attribute Option")
        doc.attribute = attribute
        doc.option_value = opt.get("option_value")
        doc.option_label = opt.get("option_label", opt.get("option_value"))
        doc.sort_order = opt.get("sort_order", idx * 10)
        doc.color_code = opt.get("color_code")
        doc.icon = opt.get("icon")
        doc.is_default = opt.get("is_default", 0)
        doc.is_active = opt.get("is_active", 1)
        doc.insert()
        created.append(doc.name)

        return created
