"""
PIM Attribute Group Controller
Manages attribute groups for organizing PIM attributes into logical categories.

Supports hierarchical grouping via parent_group, sort ordering, and
standard group protection. Groups define the visual layout sections
on product forms (e.g., General, Dimensions, SEO).
"""

import frappe
from frappe import _
from frappe.model.document import Document
from typing import Dict, List, Optional
import re
import json


# Maximum nesting depth for group hierarchy
MAX_HIERARCHY_DEPTH = 5


class PIMAttributeGroup(Document):

    def validate(self):
        self.validate_group_code()
        self.validate_group_name()
        self.validate_parent_group()
        self.validate_display_settings()

    def validate_group_code(self):
        """Ensure group_code is a URL-safe slug"""
        if not self.group_code:
            self.group_code = frappe.scrub(self.group_name)

        if not re.match(r'^[a-z][a-z0-9_]*$', self.group_code):
            frappe.throw(
                _("Group Code must start with a letter and contain only lowercase letters, numbers, and underscores"),
                title=_("Invalid Group Code")
            )

    def validate_group_name(self):
        """Ensure group_name is not empty and is reasonably formatted"""
        if not self.group_name or not self.group_name.strip():
            frappe.throw(
                _("Group Name is required"),
                title=_("Missing Group Name")
            )

        self.group_name = self.group_name.strip()

        # Check for duplicate group names (case-insensitive)
        existing = frappe.db.get_value(
            "PIM Attribute Group",
            {
                "group_name": self.group_name,
                "name": ["!=", self.name or ""]
            },
            "name"
        )
        if existing:
            frappe.throw(
                _("An attribute group with the name '{0}' already exists").format(self.group_name),
                title=_("Duplicate Group Name")
            )

    def validate_parent_group(self):
        """Validate parent_group to prevent circular references and excessive nesting"""
        if not self.parent_group:
            return

        # Cannot be own parent
        if self.parent_group == self.name:
            frappe.throw(
                _("A group cannot be its own parent"),
                title=_("Invalid Parent Group")
            )

        # Verify parent exists
        if not frappe.db.exists("PIM Attribute Group", self.parent_group):
            frappe.throw(
                _("Parent group '{0}' does not exist").format(self.parent_group),
                title=_("Invalid Parent Group")
            )

        # Check for circular references
        if self._creates_circular_reference():
            frappe.throw(
                _("Setting '{0}' as parent would create a circular reference").format(
                    self.parent_group
                ),
                title=_("Circular Reference")
            )

        # Check hierarchy depth
        depth = self._get_hierarchy_depth()
        if depth > MAX_HIERARCHY_DEPTH:
            frappe.throw(
                _("Maximum hierarchy depth of {0} levels exceeded").format(MAX_HIERARCHY_DEPTH),
                title=_("Maximum Depth Exceeded")
            )

    def validate_display_settings(self):
        """Ensure display settings are consistent"""
        # is_collapsed_default only makes sense if is_collapsible
        if getattr(self, 'is_collapsed_default', 0) and not getattr(self, 'is_collapsible', 0):
            self.is_collapsed_default = 0

    def before_save(self):
        """Prepare data before saving"""
        # Ensure sort_order is set
        if self.sort_order is None or self.sort_order == 0:
            self.sort_order = self._get_next_sort_order()

    def on_update(self):
        """Handle post-update actions"""
        self._invalidate_cache()

    def on_trash(self):
        """Prevent deletion if group is in use or is standard"""
        if self.is_standard:
            frappe.throw(
                _("Standard attribute groups cannot be deleted"),
                title=_("Cannot Delete")
            )

        # Check if any attributes are using this group
        usage_count = frappe.db.count("PIM Attribute", {"attribute_group": self.name})
        if usage_count > 0:
            frappe.throw(
                _("Cannot delete attribute group '{0}' as it is used by {1} attribute(s). "
                  "Please reassign these attributes to another group first.").format(
                    self.group_name, usage_count
                ),
                title=_("Attribute Group In Use")
            )

        # Check if any child groups reference this as parent
        child_count = frappe.db.count("PIM Attribute Group", {"parent_group": self.name})
        if child_count > 0:
            frappe.throw(
                _("Cannot delete attribute group '{0}' as it has {1} child group(s). "
                  "Please reassign or delete child groups first.").format(
                    self.group_name, child_count
                ),
                title=_("Has Child Groups")
            )

    def _creates_circular_reference(self) -> bool:
        """Check if setting parent_group would create a circular reference.

        Walks up the ancestor chain from parent_group to see if it leads
        back to this document.

        Returns:
            True if circular reference would be created
        """
        visited = set()
        current = self.parent_group

        while current:
            if current == self.name:
                return True
            if current in visited:
                # Already a broken circular ref in the chain
                return True
            visited.add(current)
            current = frappe.db.get_value("PIM Attribute Group", current, "parent_group")

        return False

    def _get_hierarchy_depth(self) -> int:
        """Calculate the depth of this group in the hierarchy.

        Returns:
            Integer depth (1 = root level, 2 = one parent, etc.)
        """
        depth = 1
        current = self.parent_group

        while current:
            depth += 1
            if depth > MAX_HIERARCHY_DEPTH + 1:
                break
            current = frappe.db.get_value("PIM Attribute Group", current, "parent_group")

        return depth

    def _get_next_sort_order(self) -> int:
        """Get next available sort order value.

        Uses increments of 10 to allow easy reordering between existing groups.
        Scoped to the same parent_group for hierarchical ordering.

        Returns:
            Next sort order integer
        """
        filters = {}
        if self.parent_group:
            filters["parent_group"] = self.parent_group
        else:
            filters["parent_group"] = ["is", "not set"]

        max_order = frappe.db.sql("""
            SELECT MAX(sort_order) FROM `tabPIM Attribute Group`
            WHERE {condition}
        """.format(
            condition="parent_group = %(parent_group)s" if self.parent_group
            else "(parent_group IS NULL OR parent_group = '')"
        ), {"parent_group": self.parent_group} if self.parent_group else {})

        if max_order and max_order[0][0] is not None:
            return max_order[0][0] + 10
        return 10

    def _invalidate_cache(self):
        """Clear relevant caches"""
        try:
            from frappe_pim.pim.utils.cache import invalidate_cache
            invalidate_cache("attribute_group", self.name)
        except (ImportError, AttributeError):
            pass

    def get_child_groups(self) -> List[Dict]:
        """Get direct child groups of this group.

        Returns:
            List of child group dicts
        """
        return frappe.get_all(
            "PIM Attribute Group",
            filters={"parent_group": self.name},
            fields=["name", "group_name", "group_code", "sort_order",
                    "icon", "color", "parent_group"],
            order_by="sort_order asc"
        )

    def get_all_descendant_groups(self) -> List[str]:
        """Get all descendant group names recursively.

        Returns:
            List of group names (not including self)
        """
        descendants = []
        self._collect_descendants(self.name, descendants)
        return descendants

    def _collect_descendants(self, group_name: str, result: List[str]):
        """Recursively collect descendant group names.

        Args:
            group_name: The group to find children of
            result: Accumulator list for descendant names
        """
        children = frappe.db.get_all(
            "PIM Attribute Group",
            filters={"parent_group": group_name},
            pluck="name"
        )
        for child in children:
            if child not in result:
                result.append(child)
                self._collect_descendants(child, result)

    def get_group_attributes(self) -> List[Dict]:
        """Get all attributes assigned to this group.

        Returns:
            List of attribute dicts with core fields
        """
        return frappe.get_all(
            "PIM Attribute",
            filters={"attribute_group": self.name},
            fields=[
                "name", "attribute_name", "attribute_code",
                "data_type", "is_required", "sort_order"
            ],
            order_by="sort_order asc"
        )


@frappe.whitelist()
def get_attribute_groups(include_children: int = 0) -> List[Dict]:
    """Get all attribute groups ordered by sort_order.

    Args:
        include_children: If 1, include child_count for each group

    Returns:
        List of attribute group dicts
    """
    groups = frappe.get_all(
        "PIM Attribute Group",
        fields=["name", "group_name", "group_code", "icon", "color",
                "sort_order", "parent_group", "is_collapsible",
                "is_collapsed_default", "description"],
        order_by="sort_order asc"
    )

    if int(include_children):
        for group in groups:
            group["child_count"] = frappe.db.count(
                "PIM Attribute Group",
                {"parent_group": group.name}
            )
            group["attribute_count"] = frappe.db.count(
                "PIM Attribute",
                {"attribute_group": group.name}
            )

    return groups


@frappe.whitelist()
def get_attributes_by_group(group: str) -> List[Dict]:
    """Get all attributes belonging to a specific group.

    Args:
        group: Name of the PIM Attribute Group

    Returns:
        List of attribute dicts
    """
    if not frappe.db.exists("PIM Attribute Group", group):
        frappe.throw(_("Attribute Group '{0}' not found").format(group))

    return frappe.get_all(
        "PIM Attribute",
        filters={"attribute_group": group},
        fields=[
            "name", "attribute_name", "attribute_code",
            "data_type", "is_required", "sort_order"
        ],
        order_by="sort_order asc"
    )


@frappe.whitelist()
def get_grouped_attributes() -> List[Dict]:
    """Get all attributes organized by their groups.

    Returns:
        List of dicts, each with 'group' and 'attributes' keys.
        Includes an 'Ungrouped' entry for attributes without a group.
    """
    groups = get_attribute_groups()
    result = []

    for group in groups:
        attributes = frappe.get_all(
            "PIM Attribute",
            filters={"attribute_group": group.name},
            fields=[
                "name", "attribute_name", "attribute_code",
                "data_type", "is_required", "sort_order"
            ],
            order_by="sort_order asc"
        )
        result.append({
            "group": group,
            "attributes": attributes
        })

    # Also include ungrouped attributes
    ungrouped = frappe.get_all(
        "PIM Attribute",
        filters={"attribute_group": ["is", "not set"]},
        fields=[
            "name", "attribute_name", "attribute_code",
            "data_type", "is_required", "sort_order"
        ],
        order_by="sort_order asc"
    )

    if ungrouped:
        result.append({
            "group": {
                "name": None,
                "group_name": _("Ungrouped"),
                "group_code": "ungrouped",
                "icon": None,
                "color": None,
                "sort_order": 9999,
                "parent_group": None
            },
            "attributes": ungrouped
        })

    return result


@frappe.whitelist()
def get_group_hierarchy() -> List[Dict]:
    """Get attribute groups organized as a tree hierarchy.

    Returns:
        List of root-level group dicts, each with a 'children' key
        containing nested child groups.
    """
    all_groups = frappe.get_all(
        "PIM Attribute Group",
        fields=["name", "group_name", "group_code", "icon", "color",
                "sort_order", "parent_group", "description"],
        order_by="sort_order asc"
    )

    # Build lookup by name
    groups_by_name = {g.name: dict(g, children=[]) for g in all_groups}

    # Build tree
    roots = []
    for g in all_groups:
        node = groups_by_name[g.name]
        if g.parent_group and g.parent_group in groups_by_name:
            groups_by_name[g.parent_group]["children"].append(node)
        else:
            roots.append(node)

    return roots


@frappe.whitelist()
def reorder_groups(order: str) -> Dict:
    """Reorder attribute groups based on provided order list.

    Args:
        order: JSON string of list of group names in desired order

    Returns:
        dict with 'success' key
    """
    if isinstance(order, str):
        order = json.loads(order)

    if not isinstance(order, list):
        frappe.throw(_("Order must be a list of group names"))

    for idx, group_name in enumerate(order):
        if not frappe.db.exists("PIM Attribute Group", group_name):
            frappe.throw(_("Attribute Group '{0}' not found").format(group_name))

        frappe.db.set_value(
            "PIM Attribute Group",
            group_name,
            "sort_order",
            (idx + 1) * 10,
            update_modified=False
        )

    frappe.db.commit()
    return {"success": True}


@frappe.whitelist()
def move_group(group: str, new_parent: Optional[str] = None) -> Dict:
    """Move a group to a new parent in the hierarchy.

    Args:
        group: Name of the group to move
        new_parent: Name of the new parent group, or None/empty for root level

    Returns:
        dict with 'success' key
    """
    if not frappe.db.exists("PIM Attribute Group", group):
        frappe.throw(_("Attribute Group '{0}' not found").format(group))

    doc = frappe.get_doc("PIM Attribute Group", group)
    doc.parent_group = new_parent if new_parent else None
    doc.save()

    return {"success": True, "name": doc.name}


def get_standard_attribute_groups() -> List[Dict]:
    """Get the standard attribute groups that should be installed by default.

    Returns:
        List of dicts with standard attribute group definitions
    """
    return [
        {
            "group_name": "General",
            "group_code": "general",
            "sort_order": 10,
            "is_standard": 1,
            "icon": "fa fa-info-circle",
            "description": "General product attributes like name, description, and basic properties"
        },
        {
            "group_name": "Dimensions",
            "group_code": "dimensions",
            "sort_order": 20,
            "is_standard": 1,
            "icon": "fa fa-ruler-combined",
            "description": "Physical dimensions and measurements (weight, height, width, etc.)"
        },
        {
            "group_name": "Media",
            "group_code": "media",
            "sort_order": 30,
            "is_standard": 1,
            "icon": "fa fa-image",
            "description": "Images, videos, and other media attributes"
        },
        {
            "group_name": "SEO",
            "group_code": "seo",
            "sort_order": 40,
            "is_standard": 1,
            "icon": "fa fa-search",
            "description": "Search engine optimization attributes (meta title, description, keywords)"
        },
        {
            "group_name": "Technical",
            "group_code": "technical",
            "sort_order": 50,
            "is_standard": 1,
            "icon": "fa fa-cogs",
            "description": "Technical specifications and engineering attributes"
        }
    ]


def install_standard_groups():
    """Install standard attribute groups if they don't exist.

    Called during app setup / after_migrate hook.
    """
    for group_def in get_standard_attribute_groups():
        if not frappe.db.exists("PIM Attribute Group", group_def["group_code"]):
            doc = frappe.new_doc("PIM Attribute Group")
            doc.update(group_def)
            doc.insert(ignore_permissions=True)
            frappe.db.commit()
