"""
PIM Attribute Template Controller
Reusable attribute set templates for consistent product attribute definition.

Templates define a pre-configured collection of attributes (with defaults,
required flags, variant axis flags, and grouping) that can be applied to
Product Families or Product Masters for rapid, consistent setup.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from typing import Any, Dict, List, Optional
import re


class PIMAttributeTemplate(Document):

    def validate(self):
        self.validate_template_code()
        self.validate_attributes()
        self.validate_no_duplicate_attributes()
        self.validate_variant_axes()

    def validate_template_code(self):
        """Ensure template_code is URL-safe slug"""
        if not self.template_code:
            self.template_code = frappe.scrub(self.template_name)

        if not re.match(r'^[a-z][a-z0-9_]*$', self.template_code):
            frappe.throw(
                _("Template Code must start with a letter and contain only lowercase letters, numbers, and underscores"),
                title=_("Invalid Template Code")
            )

    def validate_attributes(self):
        """Ensure at least one attribute is defined and all exist"""
        if not self.attributes or len(self.attributes) == 0:
            frappe.throw(
                _("At least one attribute must be defined in the template"),
                title=_("No Attributes")
            )

        # Validate each attribute exists
        for row in self.attributes:
            if row.attribute and not frappe.db.exists("PIM Attribute", row.attribute):
                frappe.throw(
                    _("Attribute '{0}' does not exist").format(row.attribute),
                    title=_("Invalid Attribute")
                )

    def validate_no_duplicate_attributes(self):
        """Ensure no duplicate attributes in the template"""
        seen = set()
        for row in self.attributes:
            if row.attribute in seen:
                frappe.throw(
                    _("Attribute '{0}' is duplicated in the template").format(row.attribute),
                    title=_("Duplicate Attribute")
                )
            seen.add(row.attribute)

    def validate_variant_axes(self):
        """Validate variant axis configuration"""
        variant_axes = [row for row in self.attributes if row.is_variant_axis]

        # Variant axes should not have default values (they are per-variant)
        for row in variant_axes:
            if row.default_value:
                frappe.msgprint(
                    _("Variant axis attribute '{0}' has a default value. "
                      "Default values are ignored for variant axes.").format(row.attribute),
                    indicator="orange"
                )

        # Variant axes should not be inherited (they define the variant)
        for row in variant_axes:
            if row.is_inherited:
                frappe.msgprint(
                    _("Variant axis attribute '{0}' is marked as inherited. "
                      "Variant axes typically should not be inherited.").format(row.attribute),
                    indicator="orange"
                )

    def before_save(self):
        """Set sort order for attributes without one"""
        for idx, row in enumerate(self.attributes):
            if not row.sort_order:
                row.sort_order = (idx + 1) * 10

    def on_update(self):
        """Invalidate cache on update"""
        self._invalidate_cache()

    def on_trash(self):
        """Prevent deletion if template is in use"""
        self._check_usage_before_delete()

    def _check_usage_before_delete(self):
        """Check all references before allowing deletion"""
        # Check if used by Product Master (attribute_template Link field)
        try:
            master_count = frappe.db.count("Product Master", {"attribute_template": self.name})
            if master_count > 0:
                frappe.throw(
                    _("Cannot delete template '{0}' as it is used by {1} product master(s)").format(
                        self.template_name, master_count
                    ),
                    title=_("Template In Use")
                )
        except Exception:
            # Product Master may be a Virtual DocType; skip if query fails
            pass

        # Check if referenced by PIM Product Type (default_attribute_template)
        try:
            type_count = frappe.db.count("PIM Product Type", {"default_attribute_template": self.name})
            if type_count > 0:
                frappe.throw(
                    _("Cannot delete template '{0}' as it is the default template for {1} product type(s)").format(
                        self.template_name, type_count
                    ),
                    title=_("Template In Use")
                )
        except Exception:
            pass

    def _invalidate_cache(self):
        """Invalidate attribute template-related caches"""
        try:
            from frappe_pim.pim.utils.cache import invalidate_cache
            invalidate_cache("attribute_template", self.name)
        except (ImportError, AttributeError):
            pass

    def get_attributes_list(self) -> List[Dict]:
        """Get a list of attribute details for this template.

        Returns:
            List of dicts with attribute info including type, required flag, etc.
            Sorted by sort_order.
        """
        attributes = []
        for row in self.attributes:
            try:
                attr_doc = frappe.get_cached_doc("PIM Attribute", row.attribute)
                attributes.append({
                    "attribute": row.attribute,
                    "attribute_name": getattr(attr_doc, 'attribute_name', row.attribute),
                    "attribute_type": getattr(attr_doc, 'attribute_type', None),
                    "is_required": row.is_required,
                    "is_variant_axis": row.is_variant_axis,
                    "is_inherited": row.is_inherited,
                    "default_value": row.default_value,
                    "sort_order": row.sort_order,
                    "group": row.group
                })
            except frappe.DoesNotExistError:
                frappe.log_error(
                    message=_("Attribute '{0}' referenced in template '{1}' does not exist").format(
                        row.attribute, self.name
                    ),
                    title=_("Missing Template Attribute")
                )
        return sorted(attributes, key=lambda x: x.get('sort_order', 0))

    def get_variant_axes(self) -> List[str]:
        """Get attributes marked as variant axes.

        Returns:
            List of attribute names that are variant axes
        """
        return [
            row.attribute for row in self.attributes
            if row.is_variant_axis
        ]

    def get_required_attributes(self) -> List[str]:
        """Get attributes marked as required.

        Returns:
            List of attribute names that are required
        """
        return [
            row.attribute for row in self.attributes
            if row.is_required
        ]

    def get_grouped_attributes(self) -> Dict[str, List[Dict]]:
        """Get template attributes grouped by their attribute group.

        Returns:
            Dict mapping group name to list of attribute dicts.
            Ungrouped attributes appear under the key "Ungrouped".
        """
        grouped = {}
        for attr in self.get_attributes_list():
            group_key = attr.get("group") or "Ungrouped"
            grouped.setdefault(group_key, []).append(attr)
        return grouped

    def apply_to_family(self, family_name: str, overwrite: bool = False) -> int:
        """Apply this template's attributes to a Product Family.

        Copies template attribute rows into the family's `attributes`
        child table (Family Attribute Template).

        Args:
            family_name: Name of the Product Family document
            overwrite: If True, replace existing attributes; if False, only add new ones

        Returns:
            Number of attributes applied
        """
        family = frappe.get_doc("Product Family", family_name)

        existing_attrs = {row.attribute for row in family.get("attributes", [])}

        if overwrite:
            family.set("attributes", [])
            existing_attrs = set()

        applied_count = 0
        for row in self.attributes:
            if row.attribute not in existing_attrs:
                family.append("attributes", {
                    "attribute": row.attribute,
                    "is_required_in_family": row.is_required,
                    "default_value": row.default_value or "",
                    "sort_order": row.sort_order
                })
                applied_count += 1

        if applied_count > 0:
            family.save(ignore_permissions=True)
            self._update_usage_stats()

        return applied_count

    def clone_template(self, new_name: str, new_code: Optional[str] = None) -> "PIMAttributeTemplate":
        """Create a copy of this template with a new name.

        Args:
            new_name: Display name for the cloned template
            new_code: Optional code for the clone. Auto-generated from name if not provided.

        Returns:
            The newly created PIM Attribute Template document
        """
        new_doc = frappe.copy_doc(self)
        new_doc.template_name = new_name
        new_doc.template_code = new_code or frappe.scrub(new_name)
        new_doc.usage_count = 0
        new_doc.last_applied = None
        new_doc.insert(ignore_permissions=True)
        return new_doc

    def _update_usage_stats(self):
        """Update usage count and last applied timestamp"""
        frappe.db.set_value(
            "PIM Attribute Template",
            self.name,
            {
                "usage_count": (self.usage_count or 0) + 1,
                "last_applied": frappe.utils.now()
            },
            update_modified=False
        )


@frappe.whitelist()
def get_template_attributes(template_name: str) -> List[Dict]:
    """Get all attributes for a specific template.

    Args:
        template_name: Name of the PIM Attribute Template

    Returns:
        List of attribute dicts with configuration
    """
    if not frappe.has_permission("PIM Attribute Template", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    template = frappe.get_doc("PIM Attribute Template", template_name)
    return template.get_attributes_list()


@frappe.whitelist()
def get_active_templates(product_type: Optional[str] = None) -> List[Dict]:
    """Get all active attribute templates.

    Args:
        product_type: Optional filter by product type

    Returns:
        List of template dicts
    """
    if not frappe.has_permission("PIM Attribute Template", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    filters = {"is_active": 1}
    if product_type:
        filters["product_type"] = product_type

    return frappe.get_all(
        "PIM Attribute Template",
        filters=filters,
        fields=["name", "template_name", "template_code", "product_type",
                "description", "usage_count"],
        order_by="template_name"
    )


@frappe.whitelist()
def apply_template_to_product(template_name: str, product_doctype: str, product_name: str) -> int:
    """Apply an attribute template to a product.

    Copies the template's attributes to the product's attribute values table.

    Args:
        template_name: Name of the PIM Attribute Template
        product_doctype: Either 'Product Master' or 'Product Variant'
        product_name: Name of the product document

    Returns:
        Number of attributes applied
    """
    if not frappe.has_permission("PIM Attribute Template", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    if product_doctype not in ("Product Master", "Product Variant"):
        frappe.throw(
            _("Invalid product doctype: {0}").format(product_doctype),
            title=_("Invalid DocType")
        )

    if not frappe.has_permission(product_doctype, "write"):
        frappe.throw(_("Not permitted to modify product"), frappe.PermissionError)

    template = frappe.get_doc("PIM Attribute Template", template_name)
    product = frappe.get_doc(product_doctype, product_name)

    applied_count = 0
    existing_attrs = {a.attribute for a in product.get("attributes", [])}

    for attr in template.attributes:
        if attr.attribute not in existing_attrs:
            product.append("attributes", {
                "attribute": attr.attribute,
                "value": attr.default_value or "",
                "is_inherited": attr.is_inherited
            })
            applied_count += 1

    if applied_count > 0:
        product.save()
        template._update_usage_stats()

    return applied_count


@frappe.whitelist()
def apply_template_to_family(template_name: str, family_name: str, overwrite: int = 0) -> int:
    """Apply an attribute template to a Product Family.

    Args:
        template_name: Name of the PIM Attribute Template
        family_name: Name of the Product Family
        overwrite: If 1, replace existing attributes; if 0, only add new ones

    Returns:
        Number of attributes applied
    """
    if not frappe.has_permission("PIM Attribute Template", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    if not frappe.has_permission("Product Family", "write"):
        frappe.throw(_("Not permitted to modify product family"), frappe.PermissionError)

    template = frappe.get_doc("PIM Attribute Template", template_name)
    return template.apply_to_family(family_name, overwrite=bool(overwrite))


@frappe.whitelist()
def get_templates_for_product_type(product_type: str) -> List[Dict]:
    """Get attribute templates suitable for a product type.

    Returns templates specifically assigned to this product type,
    plus generic templates (no product type restriction).

    Args:
        product_type: Name of the PIM Product Type

    Returns:
        List of matching templates
    """
    if not frappe.has_permission("PIM Attribute Template", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    return frappe.get_all(
        "PIM Attribute Template",
        filters={
            "is_active": 1,
            "product_type": ["in", [product_type, None, ""]]
        },
        fields=["name", "template_name", "template_code", "product_type", "description"],
        order_by="product_type desc, template_name"
    )


@frappe.whitelist()
def clone_template(template_name: str, new_name: str, new_code: Optional[str] = None) -> str:
    """Clone an existing template with a new name.

    Args:
        template_name: Name of the source template
        new_name: Display name for the cloned template
        new_code: Optional code for the clone

    Returns:
        Name of the newly created template
    """
    if not frappe.has_permission("PIM Attribute Template", "create"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    template = frappe.get_doc("PIM Attribute Template", template_name)
    new_doc = template.clone_template(new_name, new_code)
    return new_doc.name


@frappe.whitelist()
def merge_templates(template_names: str, merged_name: str, merged_code: Optional[str] = None) -> str:
    """Merge multiple templates into a new one.

    Combines attributes from all specified templates. If the same attribute
    appears in multiple templates, the first occurrence wins.

    Args:
        template_names: JSON list of template names to merge
        merged_name: Display name for the merged template
        merged_code: Optional code for the merged template

    Returns:
        Name of the newly created merged template
    """
    import json as _json

    if not frappe.has_permission("PIM Attribute Template", "create"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    if isinstance(template_names, str):
        template_names = _json.loads(template_names)

    if len(template_names) < 2:
        frappe.throw(
            _("At least two templates are required for merging"),
            title=_("Insufficient Templates")
        )

    # Collect unique attributes from all templates
    seen_attrs = set()
    merged_attributes = []

    for tpl_name in template_names:
        tpl = frappe.get_doc("PIM Attribute Template", tpl_name)
        for row in tpl.attributes:
            if row.attribute not in seen_attrs:
                merged_attributes.append({
                    "attribute": row.attribute,
                    "is_required": row.is_required,
                    "is_variant_axis": row.is_variant_axis,
                    "is_inherited": row.is_inherited,
                    "default_value": row.default_value,
                    "sort_order": row.sort_order,
                    "group": row.group
                })
                seen_attrs.add(row.attribute)

    # Create the merged template
    new_doc = frappe.new_doc("PIM Attribute Template")
    new_doc.template_name = merged_name
    new_doc.template_code = merged_code or frappe.scrub(merged_name)
    new_doc.description = _("Merged from: {0}").format(", ".join(template_names))
    new_doc.is_active = 1

    for attr_data in merged_attributes:
        new_doc.append("attributes", attr_data)

    new_doc.insert(ignore_permissions=True)
    return new_doc.name
