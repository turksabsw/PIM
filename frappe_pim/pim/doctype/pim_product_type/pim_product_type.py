# Copyright (c) 2024, PIM and contributors
# For license information, please see license.txt

"""
PIM Product Type Controller
Defines product types (Drupal-style bundles) with custom fields and allowed families.
This is a FLAT DocType (NOT NestedSet).
"""

import frappe
from frappe import _
from frappe.model.document import Document
from typing import Dict, List, Optional
import re


class PIMProductType(Document):

    def validate(self):
        self.validate_type_code()
        self.validate_type_fields()
        self.validate_allowed_families()
        self.validate_variant_config()

    def validate_type_code(self):
        """Ensure type_code is URL-safe slug"""
        if not self.type_code:
            self.type_code = frappe.scrub(self.type_name)

        if not re.match(r'^[a-z][a-z0-9_]*$', self.type_code):
            frappe.throw(
                _("Type Code must start with a letter and contain only lowercase letters, numbers, and underscores"),
                title=_("Invalid Type Code")
            )

    def validate_type_fields(self):
        """Validate custom fields defined for this product type"""
        if not self.type_fields:
            return

        seen_fieldnames = set()
        for row in self.type_fields:
            # Ensure fieldname is provided
            if not row.fieldname:
                frappe.throw(
                    _("Row {0}: Fieldname is required for type fields").format(row.idx),
                    title=_("Missing Fieldname")
                )

            # Validate fieldname format
            if not re.match(r'^[a-z][a-z0-9_]*$', row.fieldname):
                frappe.throw(
                    _("Row {0}: Fieldname '{1}' must start with a letter and contain only "
                      "lowercase letters, numbers, and underscores").format(row.idx, row.fieldname),
                    title=_("Invalid Fieldname")
                )

            # Check for duplicate fieldnames
            if row.fieldname in seen_fieldnames:
                frappe.throw(
                    _("Row {0}: Duplicate fieldname '{1}'. Each field must have a unique name.").format(
                        row.idx, row.fieldname
                    ),
                    title=_("Duplicate Fieldname")
                )
            seen_fieldnames.add(row.fieldname)

            # Validate options for Select and Link fieldtypes
            if row.fieldtype == "Select" and not row.options:
                frappe.msgprint(
                    _("Row {0}: Select field '{1}' has no options defined.").format(
                        row.idx, row.label or row.fieldname
                    ),
                    indicator="orange"
                )

            if row.fieldtype == "Link" and not row.options:
                frappe.throw(
                    _("Row {0}: Link field '{1}' requires a DocType name in Options").format(
                        row.idx, row.label or row.fieldname
                    ),
                    title=_("Missing Options")
                )

    def validate_allowed_families(self):
        """Validate allowed families configuration"""
        families = self._parse_allowed_families()
        if not families:
            return

        # Validate that all referenced families exist and are active
        for family_name in families:
            family_name = family_name.strip()
            if not family_name:
                continue

            family_status = frappe.db.get_value(
                "Product Family", family_name, "enabled"
            )
            if family_status is not None and not family_status:
                frappe.msgprint(
                    _("Allowed family '{0}' is currently disabled.").format(family_name),
                    indicator="orange"
                )

    def validate_variant_config(self):
        """Validate variant configuration settings"""
        if not self.allow_variants:
            return

        max_levels = getattr(self, "max_variant_levels", None)
        if max_levels is not None and max_levels < 1:
            frappe.throw(
                _("Maximum variant levels must be at least 1"),
                title=_("Invalid Variant Config")
            )

    def before_save(self):
        """Auto-generate type_code if empty"""
        if not self.type_code:
            self.type_code = frappe.scrub(self.type_name)

    def on_update(self):
        """Invalidate cache on update"""
        self._invalidate_cache()

    def on_trash(self):
        """Prevent deletion of in-use product types"""
        # Check if product type is used by any products (via Item custom field)
        try:
            usage_count = frappe.db.sql(
                """SELECT COUNT(*) FROM `tabItem`
                WHERE custom_pim_product_type = %s""",
                (self.name,),
                as_list=True
            )
            if usage_count and usage_count[0][0] > 0:
                frappe.throw(
                    _("Cannot delete product type '{0}' as it is used by {1} product(s). "
                      "Please reassign the products first.").format(
                        self.type_name, usage_count[0][0]
                    ),
                    title=_("Product Type In Use")
                )
        except Exception:
            # If the custom field doesn't exist yet, skip the check
            pass

    # ---------------------------------------------------------------
    # Business Logic Methods
    # ---------------------------------------------------------------

    def get_type_fields(self) -> List[Dict]:
        """Get all custom fields defined for this product type.

        Returns fields from the type_fields child table, sorted by sort_order.

        Returns:
            List of dicts with field definitions (fieldname, label, fieldtype,
            options, reqd, default_value, sort_order)
        """
        if not self.type_fields:
            return []

        fields = []
        for row in self.type_fields:
            fields.append({
                "fieldname": row.fieldname,
                "label": row.label,
                "fieldtype": row.fieldtype,
                "options": row.options,
                "reqd": row.reqd,
                "default_value": row.default_value,
                "sort_order": row.sort_order or 0
            })

        # Sort by sort_order
        fields.sort(key=lambda x: x.get("sort_order", 0))
        return fields

    def _parse_allowed_families(self) -> List[str]:
        """Parse allowed_families_text into a list of family names."""
        text = getattr(self, "allowed_families_text", None) or ""
        return [f.strip() for f in text.split(",") if f.strip()]

    def get_allowed_families(self) -> List[Dict]:
        """Get product families that can use this product type.

        Reads from the allowed_families_text field (comma-separated names).
        If no families are configured, returns an empty list (meaning all
        families are allowed by convention).

        Returns:
            List of dicts with family name, family_name, and enabled status
        """
        family_names = self._parse_allowed_families()
        if not family_names:
            return []

        # Fetch family details
        families = frappe.get_all(
            "Product Family",
            filters={"name": ["in", family_names]},
            fields=["name", "family_name", "family_code", "enabled", "allow_variants"],
            order_by="family_name asc"
        )

        return families

    def get_allowed_family_names(self) -> List[str]:
        """Get just the names of allowed families.

        Convenience method that returns only family names as strings.

        Returns:
            List of Product Family names (strings)
        """
        return self._parse_allowed_families()

    def validate_product(self, product_doc) -> Dict:
        """Validate a product document against this type's requirements.

        Checks that:
        1. All required type-specific fields have values
        2. The product's family is in the allowed families (if any are configured)
        3. Variant configuration is consistent

        Args:
            product_doc: A Product Master or Item document to validate

        Returns:
            dict with 'valid' (bool), 'errors' (list of error messages),
            and 'warnings' (list of warning messages)
        """
        errors = []
        warnings = []

        # 1. Validate required type fields have values
        type_fields = self.get_type_fields()
        for field in type_fields:
            if field.get("reqd"):
                field_value = None
                # Check custom fields on the product doc
                custom_fieldname = f"custom_{field['fieldname']}"
                if hasattr(product_doc, custom_fieldname):
                    field_value = getattr(product_doc, custom_fieldname)
                elif hasattr(product_doc, field["fieldname"]):
                    field_value = getattr(product_doc, field["fieldname"])

                if not field_value:
                    errors.append(
                        _("Required field '{0}' ({1}) is missing or empty").format(
                            field.get("label", field["fieldname"]),
                            field["fieldname"]
                        )
                    )

        # 2. Validate product family is allowed
        allowed_families = self.get_allowed_family_names()
        if allowed_families:
            product_family = getattr(product_doc, "product_family", None) or \
                getattr(product_doc, "custom_pim_product_family", None)

            if product_family and product_family not in allowed_families:
                errors.append(
                    _("Product family '{0}' is not allowed for product type '{1}'. "
                      "Allowed families: {2}").format(
                        product_family,
                        self.type_name,
                        ", ".join(allowed_families)
                    )
                )
            elif not product_family:
                warnings.append(
                    _("No product family assigned. Consider assigning one of: {0}").format(
                        ", ".join(allowed_families)
                    )
                )

        # 3. Validate variant configuration consistency
        has_variants = getattr(product_doc, "has_variants", None) or \
            getattr(product_doc, "custom_pim_has_variants", None)

        if has_variants and not self.allow_variants:
            errors.append(
                _("Product type '{0}' does not allow variants, but this product has variants enabled").format(
                    self.type_name
                )
            )

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings
        }

    def is_family_allowed(self, family_name: str) -> bool:
        """Check if a specific family is allowed for this product type.

        If no allowed families are configured, all families are permitted.

        Args:
            family_name: Name of the Product Family to check

        Returns:
            True if the family is allowed or no restrictions are set
        """
        allowed = self.get_allowed_family_names()
        if not allowed:
            # No restrictions configured - all families allowed
            return True
        return family_name in allowed

    # ---------------------------------------------------------------
    # Internal Helper Methods
    # ---------------------------------------------------------------

    def _invalidate_cache(self):
        """Invalidate product type-related caches"""
        try:
            from frappe_pim.pim.utils.cache import invalidate_cache
            invalidate_cache("product_type", self.name)
        except (ImportError, AttributeError):
            pass


# ---------------------------------------------------------------
# API Functions
# ---------------------------------------------------------------

@frappe.whitelist()
def get_product_types():
    """Get all active product types"""
    if not frappe.has_permission("PIM Product Type", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    return frappe.get_all(
        "PIM Product Type",
        filters={"is_active": 1},
        fields=["name", "type_name", "type_code", "allow_variants", "is_active"],
        order_by="type_name"
    )


@frappe.whitelist()
def get_type_fields_for_product(product_type: str) -> List[Dict]:
    """Get custom fields defined for a product type.

    Args:
        product_type: Name of the PIM Product Type

    Returns:
        List of field definitions
    """
    if not frappe.has_permission("PIM Product Type", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    doc = frappe.get_doc("PIM Product Type", product_type)
    return doc.get_type_fields()


@frappe.whitelist()
def get_allowed_families_for_type(product_type: str) -> List[Dict]:
    """Get allowed families for a product type.

    Args:
        product_type: Name of the PIM Product Type

    Returns:
        List of allowed Product Family dicts
    """
    if not frappe.has_permission("PIM Product Type", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    doc = frappe.get_doc("PIM Product Type", product_type)
    return doc.get_allowed_families()


@frappe.whitelist()
def validate_product_for_type(product_type: str, product_name: str) -> Dict:
    """Validate a product against its product type's requirements.

    Args:
        product_type: Name of the PIM Product Type
        product_name: Name of the Item/Product to validate

    Returns:
        dict with 'valid', 'errors', and 'warnings'
    """
    if not frappe.has_permission("PIM Product Type", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    type_doc = frappe.get_doc("PIM Product Type", product_type)
    product_doc = frappe.get_doc("Item", product_name)
    return type_doc.validate_product(product_doc)
