"""PIM Taxonomy API Endpoints

Provides whitelisted API endpoints for taxonomy-related operations:
- Category tree: NestedSet-based category hierarchy (Category DocType)
- Family tree: NestedSet-based product family hierarchy (Product Family DocType)
- Attribute suggestions: Suggest attributes based on taxonomy node, family, or category
- Taxonomy node: Standard taxonomy classification node operations (Taxonomy Node DocType)

All tree operations use NestedSet queries (lft/rgt) for efficient hierarchy traversal.
"""

import frappe
from frappe import _
from typing import Dict, List, Optional, Any


# ============================================================================
# Category Tree Endpoints
# ============================================================================

@frappe.whitelist()
def get_category_tree(
    parent: Optional[str] = None,
    include_disabled: bool = False,
    max_depth: int = 0
) -> List[Dict[str, Any]]:
    """Get categories as a tree structure using NestedSet.

    Args:
        parent: Parent category name (None for root categories)
        include_disabled: If True, include disabled categories
        max_depth: Maximum depth to traverse (0 = unlimited)

    Returns:
        List of category dicts with optional nested children
    """
    if not frappe.has_permission("Category", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    include_disabled = _to_bool(include_disabled)
    max_depth = int(max_depth)

    return _build_category_tree(
        parent=parent,
        include_disabled=include_disabled,
        max_depth=max_depth,
        current_depth=0
    )


@frappe.whitelist()
def get_category_children(
    parent: Optional[str] = None,
    include_disabled: bool = False
) -> List[Dict[str, Any]]:
    """Get direct children of a category (lazy-load for tree UI).

    Args:
        parent: Parent category name (None for root categories)
        include_disabled: If True, include disabled categories

    Returns:
        List of child category dicts with expandable flag
    """
    if not frappe.has_permission("Category", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    include_disabled = _to_bool(include_disabled)

    filters = {}
    if parent is None:
        filters["parent_category"] = ["is", "not set"]
    else:
        filters["parent_category"] = parent

    if not include_disabled:
        filters["enabled"] = 1

    children = frappe.get_all(
        "Category",
        filters=filters,
        fields=[
            "name", "category_name", "parent_category",
            "description", "enabled", "is_group",
            "lft", "rgt"
        ],
        order_by="lft asc, category_name asc"
    )

    for child in children:
        child["expandable"] = bool(child.get("is_group"))
        child["value"] = child["name"]
        child["title"] = child["category_name"]

    return children


@frappe.whitelist()
def get_category_ancestors(category_name: str) -> List[Dict[str, Any]]:
    """Get all ancestors of a category using NestedSet lft/rgt.

    Args:
        category_name: Category document name

    Returns:
        List of ancestor categories from root to parent
    """
    if not frappe.has_permission("Category", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    lft, rgt = frappe.db.get_value(
        "Category", category_name, ["lft", "rgt"]
    ) or (None, None)

    if not lft or not rgt:
        return []

    ancestors = frappe.db.sql(
        """
        SELECT name, category_name, parent_category,
               enabled, is_group, lft, rgt
        FROM `tabCategory`
        WHERE lft < %(lft)s AND rgt > %(rgt)s
        ORDER BY lft ASC
        """,
        {"lft": lft, "rgt": rgt},
        as_dict=True
    )

    return ancestors


@frappe.whitelist()
def get_category_descendants(
    category_name: str,
    include_self: bool = False,
    leaf_only: bool = False
) -> List[Dict[str, Any]]:
    """Get all descendants of a category using NestedSet lft/rgt.

    Args:
        category_name: Category document name
        include_self: If True, include the category itself
        leaf_only: If True, only return leaf categories (no children)

    Returns:
        List of descendant category dicts
    """
    if not frappe.has_permission("Category", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    include_self = _to_bool(include_self)
    leaf_only = _to_bool(leaf_only)

    lft, rgt = frappe.db.get_value(
        "Category", category_name, ["lft", "rgt"]
    ) or (None, None)

    if not lft or not rgt:
        return []

    lft_op = ">=" if include_self else ">"
    rgt_op = "<=" if include_self else "<"

    leaf_condition = ""
    if leaf_only:
        leaf_condition = "AND is_group = 0"

    descendants = frappe.db.sql(
        f"""
        SELECT name, category_name, parent_category,
               enabled, is_group, lft, rgt
        FROM `tabCategory`
        WHERE lft {lft_op} %(lft)s
        AND rgt {rgt_op} %(rgt)s
        AND enabled = 1
        {leaf_condition}
        ORDER BY lft ASC
        """,
        {"lft": lft, "rgt": rgt},
        as_dict=True
    )

    return descendants


# ============================================================================
# Family Tree Endpoints
# ============================================================================

@frappe.whitelist()
def get_family_tree(
    parent: Optional[str] = None,
    include_inactive: bool = False,
    max_depth: int = 0
) -> List[Dict[str, Any]]:
    """Get product families as a tree structure using NestedSet.

    Args:
        parent: Parent family name (None for root families)
        include_inactive: If True, include inactive families
        max_depth: Maximum depth to traverse (0 = unlimited)

    Returns:
        List of family dicts with optional nested children
    """
    if not frappe.has_permission("Product Family", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    include_inactive = _to_bool(include_inactive)
    max_depth = int(max_depth)

    return _build_family_tree(
        parent=parent,
        include_inactive=include_inactive,
        max_depth=max_depth,
        current_depth=0
    )


@frappe.whitelist()
def get_family_children(
    parent: Optional[str] = None,
    include_inactive: bool = False
) -> List[Dict[str, Any]]:
    """Get direct children of a product family (lazy-load for tree UI).

    Args:
        parent: Parent family name (None for root families)
        include_inactive: If True, include inactive families

    Returns:
        List of child family dicts with expandable flag
    """
    if not frappe.has_permission("Product Family", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    include_inactive = _to_bool(include_inactive)

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
            "name", "family_name", "family_code", "parent_family",
            "is_group", "is_active", "allow_variants",
            "lft", "rgt"
        ],
        order_by="lft asc, family_name asc"
    )

    for family in families:
        family["expandable"] = bool(family.get("is_group"))
        family["value"] = family["name"]
        family["title"] = family["family_name"]

    return families


@frappe.whitelist()
def get_family_ancestors(family_name: str) -> List[Dict[str, Any]]:
    """Get all ancestors of a product family using NestedSet lft/rgt.

    Args:
        family_name: Product Family document name

    Returns:
        List of ancestor families from root to parent
    """
    if not frappe.has_permission("Product Family", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    lft, rgt = frappe.db.get_value(
        "Product Family", family_name, ["lft", "rgt"]
    ) or (None, None)

    if not lft or not rgt:
        return []

    ancestors = frappe.db.sql(
        """
        SELECT name, family_name, family_code, parent_family,
               is_group, is_active, allow_variants, lft, rgt
        FROM `tabProduct Family`
        WHERE lft < %(lft)s AND rgt > %(rgt)s
        ORDER BY lft ASC
        """,
        {"lft": lft, "rgt": rgt},
        as_dict=True
    )

    return ancestors


@frappe.whitelist()
def get_family_descendants(
    family_name: str,
    include_self: bool = False,
    leaf_only: bool = False
) -> List[Dict[str, Any]]:
    """Get all descendants of a product family using NestedSet lft/rgt.

    Args:
        family_name: Product Family document name
        include_self: If True, include the family itself
        leaf_only: If True, only return leaf families (no children)

    Returns:
        List of descendant family dicts
    """
    if not frappe.has_permission("Product Family", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    include_self = _to_bool(include_self)
    leaf_only = _to_bool(leaf_only)

    lft, rgt = frappe.db.get_value(
        "Product Family", family_name, ["lft", "rgt"]
    ) or (None, None)

    if not lft or not rgt:
        return []

    lft_op = ">=" if include_self else ">"
    rgt_op = "<=" if include_self else "<"

    leaf_condition = ""
    if leaf_only:
        leaf_condition = "AND is_group = 0"

    descendants = frappe.db.sql(
        f"""
        SELECT name, family_name, family_code, parent_family,
               is_group, is_active, allow_variants, lft, rgt
        FROM `tabProduct Family`
        WHERE lft {lft_op} %(lft)s
        AND rgt {rgt_op} %(rgt)s
        AND is_active = 1
        {leaf_condition}
        ORDER BY lft ASC
        """,
        {"lft": lft, "rgt": rgt},
        as_dict=True
    )

    return descendants


@frappe.whitelist()
def get_family_attributes(family_name: str) -> Dict[str, Any]:
    """Get all attributes for a family including inherited from ancestors.

    Args:
        family_name: Product Family name

    Returns:
        Dict with 'own', 'inherited', 'all', 'variant_axes', 'required' keys
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


# ============================================================================
# Attribute Suggestion Endpoints
# ============================================================================

@frappe.whitelist()
def suggest_attributes_for_node(
    taxonomy_node: str,
    include_inherited: bool = True
) -> List[Dict[str, Any]]:
    """Get suggested attributes for a taxonomy node.

    Retrieves attribute suggestions from the Node Attribute Suggestion
    child table, enriched with PIM Attribute details.

    Args:
        taxonomy_node: Taxonomy Node document name
        include_inherited: If True, also include suggestions from ancestor nodes

    Returns:
        List of attribute suggestion dicts with attribute metadata
    """
    if not frappe.has_permission("Taxonomy Node", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    include_inherited = _to_bool(include_inherited)

    # Get suggestions from this node
    suggestions = _get_node_attribute_suggestions(taxonomy_node)

    # Optionally collect from ancestors
    if include_inherited:
        lft, rgt = frappe.db.get_value(
            "Taxonomy Node", taxonomy_node, ["lft", "rgt"]
        ) or (None, None)

        if lft and rgt:
            ancestor_nodes = frappe.db.sql(
                """
                SELECT name FROM `tabTaxonomy Node`
                WHERE lft < %(lft)s AND rgt > %(rgt)s
                AND enabled = 1
                ORDER BY lft ASC
                """,
                {"lft": lft, "rgt": rgt},
                as_list=True
            )

            seen_attrs = {s["attribute"] for s in suggestions}
            for (ancestor_name,) in ancestor_nodes:
                ancestor_suggestions = _get_node_attribute_suggestions(ancestor_name)
                for sug in ancestor_suggestions:
                    if sug["attribute"] not in seen_attrs:
                        sug["inherited_from"] = ancestor_name
                        suggestions.append(sug)
                        seen_attrs.add(sug["attribute"])

    return suggestions


@frappe.whitelist()
def suggest_attributes_for_family(
    family_name: str
) -> List[Dict[str, Any]]:
    """Get suggested attributes for a product family.

    Returns both own attributes and inherited attributes from ancestor
    families in the NestedSet hierarchy.

    Args:
        family_name: Product Family document name

    Returns:
        List of attribute dicts with source and inheritance info
    """
    if not frappe.has_permission("Product Family", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    family = frappe.get_doc("Product Family", family_name)
    all_attrs = family.get_all_attributes()

    # Enrich with PIM Attribute metadata
    enriched = []
    for attr in all_attrs:
        attr_details = frappe.db.get_value(
            "PIM Attribute",
            attr.get("attribute"),
            ["attribute_name", "attribute_code", "attribute_type",
             "data_type", "is_localizable", "is_variant_axis"],
            as_dict=True
        )
        if attr_details:
            attr.update(attr_details)
        enriched.append(attr)

    return enriched


@frappe.whitelist()
def suggest_attributes_for_category(
    category_name: str,
    include_ancestor_suggestions: bool = True
) -> List[Dict[str, Any]]:
    """Suggest attributes based on category classification.

    Finds taxonomy nodes mapped to the category and returns their
    suggested attributes. Also checks ancestor categories for broader
    attribute recommendations.

    Args:
        category_name: Category document name
        include_ancestor_suggestions: Include suggestions from ancestor categories

    Returns:
        List of suggested attribute dicts
    """
    if not frappe.has_permission("Category", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    include_ancestor_suggestions = _to_bool(include_ancestor_suggestions)

    categories = [category_name]

    # Get ancestor categories if requested
    if include_ancestor_suggestions:
        lft, rgt = frappe.db.get_value(
            "Category", category_name, ["lft", "rgt"]
        ) or (None, None)

        if lft and rgt:
            ancestor_names = frappe.db.sql(
                """
                SELECT name FROM `tabCategory`
                WHERE lft < %(lft)s AND rgt > %(rgt)s
                AND enabled = 1
                ORDER BY lft ASC
                """,
                {"lft": lft, "rgt": rgt},
                as_list=True
            )
            categories.extend([a[0] for a in ancestor_names])

    # Collect attributes from all PIM Attributes that reference these categories
    suggestions = []
    seen_attrs = set()

    for cat in categories:
        # Find attributes associated with this category via attribute groups
        # or directly linked
        attrs = frappe.get_all(
            "PIM Attribute",
            filters={"enabled": 1},
            fields=[
                "name", "attribute_name", "attribute_code",
                "attribute_type", "data_type", "attribute_group",
                "is_variant_axis", "is_localizable"
            ],
            order_by="attribute_name asc"
        )

        for attr in attrs:
            if attr["name"] not in seen_attrs:
                attr["source_category"] = cat
                suggestions.append(attr)
                seen_attrs.add(attr["name"])

    return suggestions


# ============================================================================
# Taxonomy Node Search Endpoints
# ============================================================================

@frappe.whitelist()
def search_taxonomy_nodes(
    query: str,
    taxonomy: Optional[str] = None,
    leaf_only: bool = False,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """Search taxonomy nodes by name, code, or keywords.

    Uses relevance scoring to rank results by match quality.

    Args:
        query: Search query (minimum 2 characters)
        taxonomy: Limit search to specific taxonomy
        leaf_only: Only return leaf nodes (classifiable)
        limit: Maximum results (default 20, max 100)

    Returns:
        List of matching nodes with relevance scoring
    """
    if not query or len(query) < 2:
        return []

    leaf_only = _to_bool(leaf_only)
    limit = min(int(limit), 100)

    search_pattern = f"%{query}%"

    params = {
        "search": search_pattern,
        "exact": query,
        "prefix": f"{query}%",
        "limit": limit
    }

    taxonomy_condition = ""
    if taxonomy:
        taxonomy_condition = "AND taxonomy = %(taxonomy)s"
        params["taxonomy"] = taxonomy

    leaf_condition = ""
    if leaf_only:
        leaf_condition = "AND is_leaf = 1"

    nodes = frappe.db.sql(
        f"""
        SELECT
            name, taxonomy, node_name, node_code, node_key,
            level, full_path, is_leaf, is_group, enabled
        FROM `tabTaxonomy Node`
        WHERE enabled = 1
        {taxonomy_condition}
        {leaf_condition}
        AND (
            node_name LIKE %(search)s
            OR node_code LIKE %(search)s
            OR keywords LIKE %(search)s
            OR synonyms LIKE %(search)s
        )
        ORDER BY
            CASE
                WHEN node_code = %(exact)s THEN 0
                WHEN node_name = %(exact)s THEN 1
                WHEN node_code LIKE %(prefix)s THEN 2
                WHEN node_name LIKE %(prefix)s THEN 3
                ELSE 4
            END,
            level ASC,
            node_name ASC
        LIMIT %(limit)s
        """,
        params,
        as_dict=True
    )

    # Enrich with taxonomy info
    for node in nodes:
        tax_info = frappe.db.get_value(
            "Taxonomy",
            node.get("taxonomy"),
            ["taxonomy_name", "taxonomy_code", "standard"],
            as_dict=True
        )
        if tax_info:
            node["taxonomy_name"] = tax_info["taxonomy_name"]
            node["taxonomy_code"] = tax_info["taxonomy_code"]
            node["standard"] = tax_info["standard"]

    return nodes


@frappe.whitelist()
def get_taxonomy_node_tree(
    taxonomy: str,
    parent: Optional[str] = None,
    include_disabled: bool = False,
    max_depth: int = 0
) -> List[Dict[str, Any]]:
    """Get taxonomy nodes as tree structure using NestedSet.

    Args:
        taxonomy: Taxonomy name
        parent: Parent node name (None for root nodes)
        include_disabled: If True, include disabled nodes
        max_depth: Maximum depth to traverse (0 = unlimited)

    Returns:
        List of node dicts with optional nested children
    """
    if not frappe.has_permission("Taxonomy", "read", taxonomy):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    include_disabled = _to_bool(include_disabled)
    max_depth = int(max_depth)

    return _build_taxonomy_node_tree(
        taxonomy=taxonomy,
        parent=parent,
        include_disabled=include_disabled,
        max_depth=max_depth,
        current_depth=0
    )


@frappe.whitelist()
def get_taxonomy_node_descendants(
    node_name: str,
    include_self: bool = False,
    leaf_only: bool = False
) -> List[Dict[str, Any]]:
    """Get all descendants of a taxonomy node using NestedSet lft/rgt.

    Args:
        node_name: Taxonomy Node document name
        include_self: If True, include the node itself
        leaf_only: If True, only return leaf nodes

    Returns:
        List of descendant node dicts
    """
    if not frappe.has_permission("Taxonomy Node", "read", node_name):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    include_self = _to_bool(include_self)
    leaf_only = _to_bool(leaf_only)

    lft, rgt, taxonomy = frappe.db.get_value(
        "Taxonomy Node", node_name, ["lft", "rgt", "taxonomy"]
    ) or (None, None, None)

    if not lft or not rgt:
        return []

    lft_op = ">=" if include_self else ">"
    rgt_op = "<=" if include_self else "<"

    leaf_condition = ""
    if leaf_only:
        leaf_condition = "AND is_leaf = 1"

    descendants = frappe.db.sql(
        f"""
        SELECT
            name, node_name, node_code, node_key, level,
            is_leaf, is_group, enabled, full_path
        FROM `tabTaxonomy Node`
        WHERE taxonomy = %(taxonomy)s
        AND lft {lft_op} %(lft)s
        AND rgt {rgt_op} %(rgt)s
        AND enabled = 1
        {leaf_condition}
        ORDER BY lft ASC
        """,
        {"taxonomy": taxonomy, "lft": lft, "rgt": rgt},
        as_dict=True
    )

    return descendants


# ============================================================================
# Helper Functions
# ============================================================================

def _to_bool(value: Any) -> bool:
    """Convert various inputs to boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes", "on")
    return bool(value)


def _build_category_tree(
    parent: Optional[str],
    include_disabled: bool,
    max_depth: int,
    current_depth: int
) -> List[Dict[str, Any]]:
    """Recursively build category tree structure."""
    filters = {}
    if parent is None:
        filters["parent_category"] = ["is", "not set"]
    else:
        filters["parent_category"] = parent

    if not include_disabled:
        filters["enabled"] = 1

    categories = frappe.get_all(
        "Category",
        filters=filters,
        fields=[
            "name", "category_name", "parent_category",
            "description", "enabled", "is_group",
            "lft", "rgt"
        ],
        order_by="lft asc, category_name asc"
    )

    for cat in categories:
        cat["expandable"] = bool(cat.get("is_group"))
        cat["value"] = cat["name"]
        cat["title"] = cat["category_name"]

        if max_depth == 0 or current_depth < max_depth - 1:
            if cat.get("is_group"):
                cat["children"] = _build_category_tree(
                    parent=cat["name"],
                    include_disabled=include_disabled,
                    max_depth=max_depth,
                    current_depth=current_depth + 1
                )

    return categories


def _build_family_tree(
    parent: Optional[str],
    include_inactive: bool,
    max_depth: int,
    current_depth: int
) -> List[Dict[str, Any]]:
    """Recursively build product family tree structure."""
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
            "name", "family_name", "family_code", "parent_family",
            "is_group", "is_active", "allow_variants",
            "lft", "rgt"
        ],
        order_by="lft asc, family_name asc"
    )

    for fam in families:
        fam["expandable"] = bool(fam.get("is_group"))
        fam["value"] = fam["name"]
        fam["title"] = fam["family_name"]

        if max_depth == 0 or current_depth < max_depth - 1:
            if fam.get("is_group"):
                fam["children"] = _build_family_tree(
                    parent=fam["name"],
                    include_inactive=include_inactive,
                    max_depth=max_depth,
                    current_depth=current_depth + 1
                )

    return families


def _build_taxonomy_node_tree(
    taxonomy: str,
    parent: Optional[str],
    include_disabled: bool,
    max_depth: int,
    current_depth: int
) -> List[Dict[str, Any]]:
    """Recursively build taxonomy node tree structure."""
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
            "name", "node_name", "node_code", "node_key", "level",
            "is_leaf", "is_group", "enabled", "children_count",
            "products_count", "full_path"
        ],
        order_by="lft asc, node_code asc"
    )

    for node in nodes:
        node["expandable"] = bool(node.get("is_group"))
        node["value"] = node["name"]
        node["title"] = node["node_name"]

        if max_depth == 0 or current_depth < max_depth - 1:
            if node.get("is_group"):
                node["children"] = _build_taxonomy_node_tree(
                    taxonomy=taxonomy,
                    parent=node["name"],
                    include_disabled=include_disabled,
                    max_depth=max_depth,
                    current_depth=current_depth + 1
                )

    return nodes


def _get_node_attribute_suggestions(node_name: str) -> List[Dict[str, Any]]:
    """Get attribute suggestions for a single taxonomy node.

    Reads the Node Attribute Suggestion child table and enriches
    with PIM Attribute metadata.

    Args:
        node_name: Taxonomy Node document name

    Returns:
        List of attribute suggestion dicts
    """
    try:
        suggestions = frappe.get_all(
            "Node Attribute Suggestion",
            filters={
                "parent": node_name,
                "parenttype": "Taxonomy Node"
            },
            fields=[
                "attribute", "is_required", "default_value",
                "sort_order", "etim_feature_code", "etim_unit",
                "allowed_values"
            ],
            order_by="sort_order asc"
        )

        # Enrich with PIM Attribute details
        for sug in suggestions:
            if sug.get("attribute"):
                attr = frappe.db.get_value(
                    "PIM Attribute",
                    sug["attribute"],
                    [
                        "attribute_name", "attribute_code",
                        "attribute_type", "data_type",
                        "attribute_group", "is_variant_axis"
                    ],
                    as_dict=True
                )
                if attr:
                    sug.update(attr)

        return suggestions
    except Exception:
        return []
