"""
Taxonomy Controller
Manages classification systems (GS1, UNSPSC, ECLASS, ETIM) for PIM
"""

import frappe
from frappe import _
from frappe.model.document import Document
from typing import Optional, List
import re


class Taxonomy(Document):
    def validate(self):
        self.validate_taxonomy_code()
        self.validate_max_levels()
        self.validate_node_code_pattern()
        self.validate_standard_config()

    def validate_taxonomy_code(self):
        """Ensure taxonomy_code is URL-safe slug"""
        if not self.taxonomy_code:
            # Auto-generate from taxonomy_name
            self.taxonomy_code = frappe.scrub(self.taxonomy_name)

        # Must be lowercase, no spaces, alphanumeric with underscores/hyphens
        if not re.match(r'^[a-z][a-z0-9_-]*$', self.taxonomy_code):
            frappe.throw(
                _("Taxonomy Code must start with a letter and contain only lowercase letters, numbers, underscores, and hyphens"),
                title=_("Invalid Taxonomy Code")
            )

    def validate_max_levels(self):
        """Ensure max_levels is within valid range (1-20)"""
        if self.max_levels is not None:
            if self.max_levels < 1:
                frappe.throw(
                    _("Maximum Levels must be at least 1"),
                    title=_("Invalid Maximum Levels")
                )
            if self.max_levels > 20:
                frappe.throw(
                    _("Maximum Levels cannot exceed 20"),
                    title=_("Invalid Maximum Levels")
                )

    def validate_node_code_pattern(self):
        """Validate regex pattern if provided"""
        if self.node_code_pattern:
            try:
                re.compile(self.node_code_pattern)
            except re.error as e:
                frappe.throw(
                    _("Invalid Node Code Pattern: {0}").format(str(e)),
                    title=_("Invalid Regex Pattern")
                )

    def validate_standard_config(self):
        """Validate standard-specific configuration"""
        if self.standard == "UNSPSC":
            self._set_unspsc_defaults()
        elif self.standard == "GS1":
            self._set_gs1_defaults()
        elif self.standard == "ECLASS":
            self._set_eclass_defaults()
        elif self.standard == "ETIM":
            self._set_etim_defaults()

    def _set_unspsc_defaults(self):
        """Set defaults for UNSPSC taxonomy"""
        if not self.level_names:
            self.level_names = "Segment,Family,Class,Commodity"
        if not self.max_levels:
            self.max_levels = 4
        if not self.node_code_pattern:
            self.node_code_pattern = r"^[0-9]{8}$"

    def _set_gs1_defaults(self):
        """Set defaults for GS1 GPC taxonomy"""
        if not self.level_names:
            self.level_names = "Segment,Family,Class,Brick"
        if not self.max_levels:
            self.max_levels = 4

    def _set_eclass_defaults(self):
        """Set defaults for eCl@ss taxonomy"""
        if not self.level_names:
            self.level_names = "Segment,Main Group,Group,Sub-Group"
        if not self.max_levels:
            self.max_levels = 4
        if not self.node_code_pattern:
            self.node_code_pattern = r"^[0-9]{2}-[0-9]{2}-[0-9]{2}-[0-9]{2}$"

    def _set_etim_defaults(self):
        """Set defaults for ETIM taxonomy"""
        if not self.level_names:
            self.level_names = "Group,Class"
        if not self.max_levels:
            self.max_levels = 2

    def on_update(self):
        """Handle post-update actions"""
        self.update_node_count()
        self.invalidate_cache()

    def on_trash(self):
        """Cleanup before deletion"""
        # Check if any taxonomy nodes exist
        node_count = frappe.db.count("Taxonomy Node", {"taxonomy": self.name})
        if node_count > 0:
            frappe.throw(
                _("Cannot delete taxonomy '{0}' as it has {1} taxonomy node(s). "
                  "Please delete the nodes first.").format(
                    self.taxonomy_name, node_count
                ),
                title=_("Taxonomy In Use")
            )

        # Check if any products are classified with this taxonomy
        classification_count = frappe.db.count("Product Classification", {"taxonomy": self.name})
        if classification_count > 0:
            frappe.throw(
                _("Cannot delete taxonomy '{0}' as it is used by {1} product classification(s). "
                  "Please remove the classifications first.").format(
                    self.taxonomy_name, classification_count
                ),
                title=_("Taxonomy In Use")
            )

    def update_node_count(self):
        """Update the total_nodes count"""
        try:
            count = frappe.db.count("Taxonomy Node", {"taxonomy": self.name})
            if self.total_nodes != count:
                frappe.db.set_value("Taxonomy", self.name, "total_nodes", count, update_modified=False)
        except Exception:
            # Taxonomy Node DocType may not exist yet
            pass

    def update_products_count(self):
        """Update the products_classified count"""
        try:
            count = frappe.db.count("Product Classification", {"taxonomy": self.name})
            if self.products_classified != count:
                frappe.db.set_value("Taxonomy", self.name, "products_classified", count, update_modified=False)
        except Exception:
            # Product Classification DocType may not exist yet
            pass

    def invalidate_cache(self):
        """Clear relevant caches"""
        try:
            frappe.cache().delete_key(f"pim:taxonomy:{self.name}")
            frappe.cache().delete_key("pim:all_taxonomies")
            frappe.cache().delete_key(f"pim:taxonomy_nodes:{self.name}")
        except Exception:
            pass

    def get_level_names(self) -> List[str]:
        """Get list of level names"""
        if self.level_names:
            return [name.strip() for name in self.level_names.split(",")]
        return []

    def validate_node_code(self, code: str) -> bool:
        """Validate a node code against the pattern"""
        if not self.node_code_pattern:
            return True
        return bool(re.match(self.node_code_pattern, code))


@frappe.whitelist()
def get_taxonomies(enabled_only: bool = True, standard: Optional[str] = None) -> List[dict]:
    """Get all taxonomies with optional filters

    Args:
        enabled_only: If True, return only enabled taxonomies
        standard: Filter by standard type (GS1, UNSPSC, ECLASS, ETIM, Custom)
    """
    filters = {}
    if enabled_only:
        filters["enabled"] = 1
    if standard:
        filters["standard"] = standard

    return frappe.get_all(
        "Taxonomy",
        filters=filters,
        fields=[
            "name", "taxonomy_name", "taxonomy_code", "standard",
            "version", "enabled", "max_levels", "total_nodes"
        ],
        order_by="taxonomy_name asc"
    )


@frappe.whitelist()
def get_taxonomy_hierarchy(taxonomy: str) -> dict:
    """Get taxonomy with its hierarchy structure

    Args:
        taxonomy: Taxonomy name (document name)

    Returns:
        Taxonomy details with nested nodes
    """
    doc = frappe.get_doc("Taxonomy", taxonomy)

    # Get root nodes (no parent)
    nodes = get_taxonomy_nodes(taxonomy, parent=None)

    return {
        "name": doc.name,
        "taxonomy_name": doc.taxonomy_name,
        "standard": doc.standard,
        "version": doc.version,
        "max_levels": doc.max_levels,
        "level_names": doc.get_level_names(),
        "nodes": nodes
    }


def get_taxonomy_nodes(taxonomy: str, parent: Optional[str] = None) -> List[dict]:
    """Get taxonomy nodes for a given parent

    Args:
        taxonomy: Taxonomy name
        parent: Parent node name (None for root nodes)
    """
    filters = {"taxonomy": taxonomy}
    if parent is None:
        filters["parent_node"] = ["is", "not set"]
    else:
        filters["parent_node"] = parent

    nodes = frappe.get_all(
        "Taxonomy Node",
        filters=filters,
        fields=["name", "node_name", "node_code", "level", "is_leaf"],
        order_by="node_code asc"
    )

    # Recursively get children
    for node in nodes:
        if not node.get("is_leaf"):
            node["children"] = get_taxonomy_nodes(taxonomy, parent=node["name"])

    return nodes
