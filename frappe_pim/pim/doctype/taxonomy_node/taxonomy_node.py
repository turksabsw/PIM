"""
Taxonomy Node Controller
Implements Nested Set Model for 20-level deep hierarchies supporting
GS1, UNSPSC, eCl@ss, ETIM classification standards
"""

import frappe
from frappe import _
from frappe.utils.nestedset import NestedSet
from typing import Optional, List, Dict, Any


class TaxonomyNode(NestedSet):
    nsm_parent_field = "parent_node"

    def validate(self):
        self.validate_taxonomy()
        self.validate_parent_node()
        self.validate_node_code()
        self.validate_level()
        self.generate_node_key()
        self.calculate_level()
        self.validate_max_level()

    def validate_taxonomy(self):
        """Ensure taxonomy exists and is enabled"""
        if not self.taxonomy:
            frappe.throw(
                _("Taxonomy is required"),
                title=_("Missing Taxonomy")
            )

        taxonomy = frappe.get_doc("Taxonomy", self.taxonomy)
        if not taxonomy.enabled:
            frappe.throw(
                _("Cannot add nodes to disabled taxonomy '{0}'").format(
                    taxonomy.taxonomy_name
                ),
                title=_("Taxonomy Disabled")
            )

    def validate_parent_node(self):
        """Ensure parent node belongs to same taxonomy"""
        if self.parent_node:
            parent_taxonomy = frappe.db.get_value(
                "Taxonomy Node", self.parent_node, "taxonomy"
            )
            if parent_taxonomy != self.taxonomy:
                frappe.throw(
                    _("Parent node must belong to the same taxonomy"),
                    title=_("Invalid Parent Node")
                )

    def validate_node_code(self):
        """Validate node code against taxonomy pattern"""
        if not self.node_code:
            frappe.throw(
                _("Node Code is required"),
                title=_("Missing Node Code")
            )

        # Get taxonomy pattern
        taxonomy = frappe.get_doc("Taxonomy", self.taxonomy)
        if taxonomy.node_code_pattern:
            if not taxonomy.validate_node_code(self.node_code):
                frappe.throw(
                    _("Node Code '{0}' does not match taxonomy pattern '{1}'").format(
                        self.node_code, taxonomy.node_code_pattern
                    ),
                    title=_("Invalid Node Code Format")
                )

    def validate_level(self):
        """Ensure level is positive"""
        if self.level is not None and self.level < 1:
            self.level = 1

    def generate_node_key(self):
        """Generate unique node key: {taxonomy_code}-{node_code}"""
        if not self.node_key or self.has_value_changed("taxonomy") or self.has_value_changed("node_code"):
            taxonomy_code = frappe.db.get_value(
                "Taxonomy", self.taxonomy, "taxonomy_code"
            )
            self.node_key = f"{taxonomy_code}-{self.node_code}"

    def calculate_level(self):
        """Calculate hierarchy level based on parent"""
        if not self.parent_node:
            self.level = 1
        else:
            parent_level = frappe.db.get_value(
                "Taxonomy Node", self.parent_node, "level"
            ) or 0
            self.level = parent_level + 1

    def validate_max_level(self):
        """Ensure level doesn't exceed maximum (20 levels)"""
        max_allowed = 20

        # Also check taxonomy-specific max_levels
        taxonomy_max = frappe.db.get_value(
            "Taxonomy", self.taxonomy, "max_levels"
        )
        if taxonomy_max:
            max_allowed = min(max_allowed, taxonomy_max)

        if self.level > max_allowed:
            frappe.throw(
                _("Maximum hierarchy depth is {0} levels. Current level: {1}").format(
                    max_allowed, self.level
                ),
                title=_("Maximum Depth Exceeded")
            )

    def before_save(self):
        """Pre-save operations"""
        self.update_path_fields()

    def on_update(self):
        """Handle post-update operations"""
        super().on_update()
        self.update_parent_is_leaf()
        self.update_children_count()
        self.update_taxonomy_node_count()
        self.invalidate_cache()

    def after_insert(self):
        """Handle post-insert operations"""
        self.update_parent_is_leaf()
        self.update_taxonomy_node_count()

    def on_trash(self):
        """Handle pre-deletion validation and cleanup"""
        # Check if node has children
        children_count = frappe.db.count(
            "Taxonomy Node",
            {"parent_node": self.name}
        )
        if children_count > 0:
            frappe.throw(
                _("Cannot delete node '{0}' as it has {1} child node(s). "
                  "Please delete child nodes first.").format(
                    self.node_name, children_count
                ),
                title=_("Node Has Children")
            )

        # Check if products are classified to this node
        classification_count = frappe.db.count(
            "Product Classification",
            {"taxonomy_node": self.name}
        )
        if classification_count > 0:
            frappe.throw(
                _("Cannot delete node '{0}' as it has {1} product classification(s). "
                  "Please remove the classifications first.").format(
                    self.node_name, classification_count
                ),
                title=_("Node In Use")
            )

    def after_delete(self):
        """Handle post-deletion cleanup"""
        # Update old parent's is_leaf status
        if self.parent_node:
            self._update_node_is_leaf(self.parent_node)

        self.update_taxonomy_node_count()
        self.invalidate_cache()

    def update_path_fields(self):
        """Update full_path and full_code_path fields"""
        ancestors = self.get_ancestors()
        ancestors.append(self)

        # Build name path
        name_parts = [a.node_name for a in ancestors]
        self.full_path = " > ".join(name_parts)

        # Build code path
        code_parts = [a.node_code for a in ancestors]
        separator = frappe.db.get_value(
            "Taxonomy", self.taxonomy, "code_separator"
        ) or "."
        self.full_code_path = separator.join(code_parts)

    def get_ancestors(self) -> List["TaxonomyNode"]:
        """Get all ancestor nodes in order from root to parent"""
        ancestors = []
        parent = self.parent_node

        while parent:
            parent_doc = frappe.get_doc("Taxonomy Node", parent)
            ancestors.insert(0, parent_doc)
            parent = parent_doc.parent_node

        return ancestors

    def update_parent_is_leaf(self):
        """Update parent node's is_leaf status"""
        if self.parent_node:
            self._update_node_is_leaf(self.parent_node)

        # Also update old parent if parent changed
        if self.has_value_changed("parent_node") and self.get_doc_before_save():
            old_parent = self.get_doc_before_save().parent_node
            if old_parent:
                self._update_node_is_leaf(old_parent)

    def _update_node_is_leaf(self, node_name: str):
        """Update a specific node's is_leaf status"""
        children_count = frappe.db.count(
            "Taxonomy Node",
            {"parent_node": node_name}
        )
        is_leaf = 1 if children_count == 0 else 0
        is_group = 0 if children_count == 0 else 1

        frappe.db.set_value(
            "Taxonomy Node", node_name,
            {"is_leaf": is_leaf, "is_group": is_group, "children_count": children_count},
            update_modified=False
        )

    def update_children_count(self):
        """Update this node's children_count"""
        count = frappe.db.count(
            "Taxonomy Node",
            {"parent_node": self.name}
        )
        if self.children_count != count:
            frappe.db.set_value(
                "Taxonomy Node", self.name,
                {"children_count": count, "is_leaf": 1 if count == 0 else 0, "is_group": 0 if count == 0 else 1},
                update_modified=False
            )

    def update_taxonomy_node_count(self):
        """Update taxonomy's total_nodes count"""
        try:
            taxonomy_doc = frappe.get_doc("Taxonomy", self.taxonomy)
            taxonomy_doc.update_node_count()
        except Exception:
            pass

    def invalidate_cache(self):
        """Clear relevant caches"""
        try:
            frappe.cache().delete_key(f"pim:taxonomy_node:{self.name}")
            frappe.cache().delete_key(f"pim:taxonomy_nodes:{self.taxonomy}")
            frappe.cache().delete_key(f"pim:taxonomy_tree:{self.taxonomy}")
        except Exception:
            pass

    def update_products_count(self):
        """Update the products_count field"""
        try:
            count = frappe.db.count(
                "Product Classification",
                {"taxonomy_node": self.name}
            )
            if self.products_count != count:
                frappe.db.set_value(
                    "Taxonomy Node", self.name,
                    "products_count", count,
                    update_modified=False
                )
        except Exception:
            pass

    def get_children(self, include_disabled: bool = False) -> List[Dict]:
        """Get direct child nodes

        Args:
            include_disabled: If True, include disabled nodes
        """
        filters = {"parent_node": self.name}
        if not include_disabled:
            filters["enabled"] = 1

        return frappe.get_all(
            "Taxonomy Node",
            filters=filters,
            fields=[
                "name", "node_name", "node_code", "level",
                "is_leaf", "enabled", "children_count"
            ],
            order_by="node_code asc"
        )

    def get_descendants(self, include_self: bool = False) -> List[str]:
        """Get all descendant node names using Nested Set

        Args:
            include_self: If True, include this node in results
        """
        if not self.lft or not self.rgt:
            return [self.name] if include_self else []

        condition = ">=" if include_self else ">"
        end_condition = "<=" if include_self else "<"

        descendants = frappe.db.sql(
            """
            SELECT name FROM `tabTaxonomy Node`
            WHERE taxonomy = %s
            AND lft {condition} %s
            AND rgt {end_condition} %s
            ORDER BY lft
            """.format(condition=condition, end_condition=end_condition),
            (self.taxonomy, self.lft, self.rgt),
            as_list=True
        )

        return [d[0] for d in descendants]


# API Functions

@frappe.whitelist()
def get_node_tree(
    taxonomy: str,
    parent: Optional[str] = None,
    include_disabled: bool = False
) -> List[Dict]:
    """Get taxonomy nodes as tree structure

    Args:
        taxonomy: Taxonomy name
        parent: Parent node name (None for root nodes)
        include_disabled: If True, include disabled nodes
    """
    filters = {"taxonomy": taxonomy}

    if parent is None:
        filters["parent_node"] = ["is", "not set"]
    else:
        filters["parent_node"] = parent

    if not include_disabled:
        filters["enabled"] = 1

    nodes = frappe.get_all(
        "Taxonomy Node",
        filters=filters,
        fields=[
            "name", "node_name", "node_code", "level",
            "is_leaf", "is_group", "enabled", "children_count",
            "full_path", "products_count"
        ],
        order_by="lft asc, node_code asc"
    )

    # Add expandable flag for tree view
    for node in nodes:
        node["expandable"] = node.get("is_group", False)
        node["value"] = node["name"]
        node["title"] = node["node_name"]

    return nodes


@frappe.whitelist()
def get_node_path(node_name: str) -> Dict:
    """Get full path information for a node

    Args:
        node_name: Taxonomy Node name
    """
    node = frappe.get_doc("Taxonomy Node", node_name)

    ancestors = node.get_ancestors()
    path_nodes = []

    for ancestor in ancestors:
        path_nodes.append({
            "name": ancestor.name,
            "node_name": ancestor.node_name,
            "node_code": ancestor.node_code,
            "level": ancestor.level
        })

    # Add current node
    path_nodes.append({
        "name": node.name,
        "node_name": node.node_name,
        "node_code": node.node_code,
        "level": node.level
    })

    return {
        "node": node_name,
        "taxonomy": node.taxonomy,
        "full_path": node.full_path,
        "full_code_path": node.full_code_path,
        "path_nodes": path_nodes,
        "level": node.level
    }


@frappe.whitelist()
def search_nodes(
    taxonomy: str,
    search_term: str,
    limit: int = 20
) -> List[Dict]:
    """Search taxonomy nodes by name or code

    Args:
        taxonomy: Taxonomy name
        search_term: Search term
        limit: Maximum results to return
    """
    if not search_term or len(search_term) < 2:
        return []

    nodes = frappe.db.sql(
        """
        SELECT
            name, node_name, node_code, level,
            full_path, is_leaf, enabled
        FROM `tabTaxonomy Node`
        WHERE taxonomy = %s
        AND enabled = 1
        AND (
            node_name LIKE %s
            OR node_code LIKE %s
            OR keywords LIKE %s
            OR synonyms LIKE %s
        )
        ORDER BY
            CASE
                WHEN node_code = %s THEN 0
                WHEN node_name = %s THEN 1
                WHEN node_code LIKE %s THEN 2
                ELSE 3
            END,
            level ASC,
            node_name ASC
        LIMIT %s
        """,
        (
            taxonomy,
            f"%{search_term}%",
            f"%{search_term}%",
            f"%{search_term}%",
            f"%{search_term}%",
            search_term,
            search_term,
            f"{search_term}%",
            limit
        ),
        as_dict=True
    )

    return nodes


@frappe.whitelist()
def get_leaf_nodes(taxonomy: str, parent: Optional[str] = None) -> List[Dict]:
    """Get all leaf nodes (classifiable nodes) for a taxonomy

    Args:
        taxonomy: Taxonomy name
        parent: Optional parent node to filter descendants
    """
    filters = {
        "taxonomy": taxonomy,
        "is_leaf": 1,
        "enabled": 1
    }

    if parent:
        # Get parent's lft/rgt for descendant filtering
        parent_lft, parent_rgt = frappe.db.get_value(
            "Taxonomy Node", parent, ["lft", "rgt"]
        )
        if parent_lft and parent_rgt:
            return frappe.db.sql(
                """
                SELECT name, node_name, node_code, level, full_path
                FROM `tabTaxonomy Node`
                WHERE taxonomy = %s
                AND is_leaf = 1
                AND enabled = 1
                AND lft > %s
                AND rgt < %s
                ORDER BY lft
                """,
                (taxonomy, parent_lft, parent_rgt),
                as_dict=True
            )

    return frappe.get_all(
        "Taxonomy Node",
        filters=filters,
        fields=["name", "node_name", "node_code", "level", "full_path"],
        order_by="lft asc"
    )


@frappe.whitelist()
def move_node(node_name: str, new_parent: Optional[str] = None) -> Dict:
    """Move a node to a new parent

    Args:
        node_name: Node to move
        new_parent: New parent node (None for root level)
    """
    node = frappe.get_doc("Taxonomy Node", node_name)

    # Validate new parent is in same taxonomy
    if new_parent:
        new_parent_taxonomy = frappe.db.get_value(
            "Taxonomy Node", new_parent, "taxonomy"
        )
        if new_parent_taxonomy != node.taxonomy:
            frappe.throw(
                _("Cannot move node to a different taxonomy"),
                title=_("Invalid Move")
            )

        # Check for circular reference
        if new_parent == node_name:
            frappe.throw(
                _("Cannot move node to itself"),
                title=_("Invalid Move")
            )

        # Check if new_parent is a descendant
        descendants = node.get_descendants()
        if new_parent in descendants:
            frappe.throw(
                _("Cannot move node to its own descendant"),
                title=_("Invalid Move")
            )

    # Store old parent for is_leaf update
    old_parent = node.parent_node

    # Update parent
    node.parent_node = new_parent
    node.save()

    return {
        "success": True,
        "node": node_name,
        "old_parent": old_parent,
        "new_parent": new_parent,
        "new_level": node.level
    }
