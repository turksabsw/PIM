"""
Product Family Controller
Implements NestedSet hierarchy for product attribute structure.
Defines which attributes are required/optional for products in this family,
with attribute inheritance from ancestor families.
"""

import frappe
from frappe import _
from frappe.utils.nestedset import NestedSet
from typing import Dict, List, Optional
import re


class ProductFamily(NestedSet):
    nsm_parent_field = "parent_family"

    def validate(self):
        self.validate_family_code()
        self.validate_parent()
        self.validate_variant_axes()
        self.validate_duplicate_attributes()
        self.calculate_level()
        self.update_full_path()

    def validate_family_code(self):
        """Ensure family_code is a valid URL-safe slug"""
        if not self.family_code:
            self.family_code = frappe.scrub(self.family_name)

        if not re.match(r'^[a-z][a-z0-9_]*$', self.family_code):
            frappe.throw(
                _("Family Code must start with a letter and contain only lowercase letters, numbers, and underscores"),
                title=_("Invalid Family Code")
            )

    def validate_parent(self):
        """Validate parent family constraints"""
        if self.parent_family:
            # Cannot be own parent
            if self.parent_family == self.name:
                frappe.throw(
                    _("A family cannot be its own parent"),
                    title=_("Invalid Parent")
                )

            # Parent must be active
            parent_active = frappe.db.get_value(
                "Product Family", self.parent_family, "is_active"
            )
            if parent_active is not None and not parent_active:
                frappe.throw(
                    _("Parent family '{0}' is inactive. Cannot add children to inactive families.").format(
                        self.parent_family
                    ),
                    title=_("Inactive Parent")
                )

    def validate_variant_axes(self):
        """Ensure variant axes are only set when variants are allowed"""
        if not self.allow_variants and self.variant_attributes:
            frappe.msgprint(
                _("Variant attributes are configured but variants are not allowed. "
                  "They will be ignored until 'Allow Variants' is checked."),
                indicator="orange"
            )

        # Validate variant axes are also listed in family attributes
        if self.variant_attributes and self.attributes:
            family_attr_names = {
                row.attribute for row in self.attributes
            }
            for row in self.variant_attributes:
                if row.attribute and row.attribute not in family_attr_names:
                    frappe.msgprint(
                        _("Variant axis attribute '{0}' is not in the family attributes list. "
                          "Consider adding it for completeness tracking.").format(
                            row.attribute
                        ),
                        indicator="orange"
                    )

    def validate_duplicate_attributes(self):
        """Ensure no duplicate attributes in the family attributes table"""
        if not self.attributes:
            return

        seen = set()
        for row in self.attributes:
            if row.attribute in seen:
                frappe.throw(
                    _("Duplicate attribute '{0}' in family attributes. "
                      "Each attribute can only appear once.").format(row.attribute),
                    title=_("Duplicate Attribute")
                )
            seen.add(row.attribute)

    def calculate_level(self):
        """Calculate hierarchy level based on parent"""
        if not self.parent_family:
            self.level = 1
        else:
            parent_level = frappe.db.get_value(
                "Product Family", self.parent_family, "level"
            ) or 0
            self.level = parent_level + 1

    def update_full_path(self):
        """Build full path string from root to this family"""
        ancestors = self.get_ancestors()
        path_parts = [a.family_name for a in ancestors]
        path_parts.append(self.family_name)
        self.full_path = " > ".join(path_parts)

    def on_update(self):
        """Handle post-update operations"""
        super().on_update()
        self._update_children_count()
        self._update_parent_is_group()
        self._update_products_count()
        self._invalidate_cache()

    def after_insert(self):
        """Handle post-insert operations"""
        self._update_parent_is_group()

    def on_trash(self):
        """Validate before deletion"""
        # Check if family has children
        children_count = frappe.db.count(
            "Product Family",
            {"parent_family": self.name}
        )
        if children_count > 0:
            frappe.throw(
                _("Cannot delete family '{0}' as it has {1} child family(ies). "
                  "Please delete child families first.").format(
                    self.family_name, children_count
                ),
                title=_("Family Has Children")
            )

        # Check if products are using this family
        products_count = frappe.db.sql(
            """SELECT COUNT(*) FROM `tabItem`
            WHERE custom_pim_product_family = %s""",
            (self.name,),
            as_list=True
        )
        if products_count and products_count[0][0] > 0:
            frappe.throw(
                _("Cannot delete family '{0}' as it is used by {1} product(s). "
                  "Please reassign the products first.").format(
                    self.family_name, products_count[0][0]
                ),
                title=_("Family In Use")
            )

    def after_delete(self):
        """Handle post-deletion cleanup"""
        if self.parent_family:
            self._update_node_is_group(self.parent_family)
        self._invalidate_cache()

    # ---------------------------------------------------------------
    # Business Logic Methods
    # ---------------------------------------------------------------

    def get_inherited_attributes(self) -> List[Dict]:
        """Get attributes inherited from ancestor families.

        Walks up the parent chain collecting attributes from each ancestor.
        Parent attributes are ordered by hierarchy level (root first).

        Returns:
            List of dicts with attribute info and source family
        """
        if not self.inherit_parent_attributes or not self.parent_family:
            return []

        inherited = []
        ancestors = self.get_ancestors()

        for ancestor in ancestors:
            ancestor_attrs = frappe.get_all(
                "Family Attribute Template",
                filters={"parent": ancestor.name, "parenttype": "Product Family"},
                fields=["attribute", "is_required_in_family", "default_value", "sort_order"],
                order_by="sort_order asc"
            )
            for attr in ancestor_attrs:
                attr["source_family"] = ancestor.name
                attr["source_family_name"] = ancestor.family_name
                attr["inherited"] = True
                inherited.append(attr)

        return inherited

    def get_all_attributes(self) -> List[Dict]:
        """Get combined list of own attributes + inherited attributes.

        Inherited attributes come first (root-to-parent order), then own attributes.
        If an attribute exists in both inherited and own, the own definition takes
        precedence (overrides inherited).

        Returns:
            List of dicts with attribute info, source, and override status
        """
        inherited = self.get_inherited_attributes()
        own_attributes = []

        for row in (self.attributes or []):
            own_attributes.append({
                "attribute": row.attribute,
                "is_required_in_family": row.is_required_in_family,
                "default_value": row.default_value,
                "sort_order": row.sort_order,
                "source_family": self.name,
                "source_family_name": self.family_name,
                "inherited": False
            })

        # Build combined list: inherited first, own overrides
        own_attr_names = {a["attribute"] for a in own_attributes}
        combined = []

        # Add inherited attributes that are NOT overridden by own
        for attr in inherited:
            if attr["attribute"] not in own_attr_names:
                combined.append(attr)
            else:
                # Mark the own attribute as an override
                for own in own_attributes:
                    if own["attribute"] == attr["attribute"]:
                        own["overrides_inherited"] = True
                        own["inherited_from"] = attr["source_family"]
                        break

        # Add own attributes
        combined.extend(own_attributes)

        return combined

    def get_variant_axes(self) -> List[Dict]:
        """Get the variant axis attributes for this family.

        Returns axes from variant_attributes table, enriched with
        attribute details.

        Returns:
            List of dicts with attribute details for variant axes
        """
        if not self.allow_variants:
            return []

        axes = []
        for row in (self.variant_attributes or []):
            attr_details = frappe.db.get_value(
                "PIM Attribute",
                row.attribute,
                ["attribute_name", "attribute_code", "attribute_type", "is_variant_axis"],
                as_dict=True
            )
            if attr_details:
                axes.append({
                    "attribute": row.attribute,
                    "attribute_name": attr_details.attribute_name,
                    "attribute_code": attr_details.attribute_code,
                    "attribute_type": attr_details.attribute_type,
                    "sort_order": row.sort_order
                })

        # Sort by sort_order
        axes.sort(key=lambda x: x.get("sort_order", 0))
        return axes

    def get_required_attributes(self) -> List[str]:
        """Get list of required attribute names from all attributes.

        Returns:
            List of attribute names that are required
        """
        all_attrs = self.get_all_attributes()
        return [
            a["attribute"] for a in all_attrs
            if a.get("is_required_in_family")
        ]

    def validate_product_attributes(self, attribute_values: List[Dict]) -> Dict:
        """Check if a set of attribute values satisfies this family's requirements.

        Args:
            attribute_values: List of dicts with 'attribute' and 'value' keys

        Returns:
            dict with 'valid' (bool), 'missing' (list), and 'errors' (list)
        """
        all_attrs = self.get_all_attributes()
        provided_attrs = {av.get("attribute") for av in attribute_values if av.get("value")}

        missing = []
        errors = []

        for attr in all_attrs:
            if attr.get("is_required_in_family") and attr["attribute"] not in provided_attrs:
                missing.append(attr["attribute"])
                errors.append(
                    _("Required attribute '{0}' is missing").format(attr["attribute"])
                )

        return {
            "valid": len(missing) == 0,
            "missing": missing,
            "errors": errors,
            "total_attributes": len(all_attrs),
            "provided_attributes": len(provided_attrs)
        }

    def get_ancestors(self) -> List["ProductFamily"]:
        """Get all ancestor families in order from root to parent.

        Returns:
            List of ProductFamily documents ordered root-first
        """
        ancestors = []
        parent = self.parent_family

        while parent:
            parent_doc = frappe.get_doc("Product Family", parent)
            ancestors.insert(0, parent_doc)
            parent = parent_doc.parent_family

        return ancestors

    def get_children(self, include_inactive: bool = False) -> List[Dict]:
        """Get direct child families.

        Args:
            include_inactive: If True, include inactive families

        Returns:
            List of child family dicts
        """
        filters = {"parent_family": self.name}
        if not include_inactive:
            filters["is_active"] = 1

        return frappe.get_all(
            "Product Family",
            filters=filters,
            fields=[
                "name", "family_name", "family_code", "level",
                "is_group", "is_active", "products_count", "children_count"
            ],
            order_by="family_name asc"
        )

    def get_descendants(self, include_self: bool = False) -> List[str]:
        """Get all descendant family names using Nested Set (lft/rgt).

        Args:
            include_self: If True, include this family in results

        Returns:
            List of family names
        """
        if not self.lft or not self.rgt:
            return [self.name] if include_self else []

        condition = ">=" if include_self else ">"
        end_condition = "<=" if include_self else "<"

        descendants = frappe.db.sql(
            """
            SELECT name FROM `tabProduct Family`
            WHERE lft {condition} %s
            AND rgt {end_condition} %s
            ORDER BY lft
            """.format(condition=condition, end_condition=end_condition),
            (self.lft, self.rgt),
            as_list=True
        )

        return [d[0] for d in descendants]

    # ---------------------------------------------------------------
    # Internal Helper Methods
    # ---------------------------------------------------------------

    def _update_children_count(self):
        """Update this family's children_count"""
        count = frappe.db.count(
            "Product Family",
            {"parent_family": self.name}
        )
        if self.children_count != count:
            frappe.db.set_value(
                "Product Family", self.name,
                "children_count", count,
                update_modified=False
            )

    def _update_parent_is_group(self):
        """Update parent family's is_group status when children change"""
        if self.parent_family:
            self._update_node_is_group(self.parent_family)

        # Also update old parent if parent changed
        if self.has_value_changed("parent_family") and self.get_doc_before_save():
            old_parent = self.get_doc_before_save().parent_family
            if old_parent:
                self._update_node_is_group(old_parent)

    def _update_node_is_group(self, family_name: str):
        """Update a specific family's is_group status"""
        children_count = frappe.db.count(
            "Product Family",
            {"parent_family": family_name}
        )
        frappe.db.set_value(
            "Product Family", family_name,
            {
                "is_group": 1 if children_count > 0 else 0,
                "children_count": children_count
            },
            update_modified=False
        )

    def _update_products_count(self):
        """Update the products_count field for this family"""
        try:
            count = frappe.db.sql(
                """SELECT COUNT(*) FROM `tabItem`
                WHERE custom_pim_product_family = %s""",
                (self.name,),
                as_list=True
            )
            new_count = count[0][0] if count else 0
            if self.products_count != new_count:
                frappe.db.set_value(
                    "Product Family", self.name,
                    "products_count", new_count,
                    update_modified=False
                )
        except Exception:
            pass

    def _invalidate_cache(self):
        """Invalidate family-related caches"""
        try:
            frappe.cache().delete_key(f"pim:product_family:{self.name}")
            frappe.cache().delete_key("pim:product_family_tree")
            from frappe_pim.pim.utils.cache import invalidate_cache
            invalidate_cache("product_family", self.name)
        except (ImportError, AttributeError):
            pass


# ---------------------------------------------------------------
# API Functions
# ---------------------------------------------------------------

@frappe.whitelist()
def get_family_tree(parent: Optional[str] = None, include_inactive: bool = False) -> List[Dict]:
    """Get product families as tree structure.

    Args:
        parent: Parent family name (None for root families)
        include_inactive: If True, include inactive families
    """
    filters = {}

    if parent is None:
        filters["parent_family"] = ["is", "not set"]
    else:
        filters["parent_family"] = parent

    if not include_inactive:
        filters["is_active"] = 1

    families = frappe.get_all(
        "Product Family",
        filters=filters,
        fields=[
            "name", "family_name", "family_code", "level",
            "is_group", "is_active", "products_count", "children_count",
            "allow_variants", "full_path"
        ],
        order_by="lft asc, family_name asc"
    )

    for family in families:
        family["expandable"] = bool(family.get("is_group"))
        family["value"] = family["name"]
        family["title"] = family["family_name"]

    return families


@frappe.whitelist()
def get_family_attributes(family_name: str) -> Dict:
    """Get all attributes for a family including inherited.

    Args:
        family_name: Product Family name

    Returns:
        dict with 'own', 'inherited', 'all', and 'variant_axes' keys
    """
    if not frappe.has_permission("Product Family", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    family = frappe.get_doc("Product Family", family_name)

    return {
        "own": [{
            "attribute": row.attribute,
            "is_required_in_family": row.is_required_in_family,
            "default_value": row.default_value,
            "sort_order": row.sort_order
        } for row in (family.attributes or [])],
        "inherited": family.get_inherited_attributes(),
        "all": family.get_all_attributes(),
        "variant_axes": family.get_variant_axes(),
        "required": family.get_required_attributes()
    }
