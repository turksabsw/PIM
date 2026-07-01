"""
Taxonomy REST API
Provides REST API endpoints for taxonomy classification lookup operations
"""

import frappe
from frappe import _
from typing import Optional, List, Dict, Any
import json


# ============================================================================
# Taxonomy Retrieval APIs
# ============================================================================

@frappe.whitelist()
def get_taxonomy(
    name: Optional[str] = None,
    code: Optional[str] = None,
    include_nodes: bool = False,
    include_statistics: bool = False
) -> Dict[str, Any]:
    """Get a single taxonomy by name or code

    Args:
        name: Taxonomy document name
        code: Taxonomy code
        include_nodes: Include root-level nodes
        include_statistics: Include usage statistics

    Returns:
        Taxonomy data dictionary

    Raises:
        frappe.DoesNotExistError: If taxonomy not found
    """
    include_nodes = _to_bool(include_nodes)
    include_statistics = _to_bool(include_statistics)

    # Validate input
    if not name and not code:
        frappe.throw(
            _("Either 'name' or 'code' parameter is required"),
            title=_("Missing Parameter")
        )

    # Find taxonomy
    taxonomy_name = name
    if not taxonomy_name and code:
        taxonomy_name = frappe.db.get_value("Taxonomy", {"taxonomy_code": code}, "name")
        if not taxonomy_name:
            frappe.throw(
                _("Taxonomy with code '{0}' not found").format(code),
                exc=frappe.DoesNotExistError
            )

    # Check permissions
    if not frappe.has_permission("Taxonomy", "read", taxonomy_name):
        frappe.throw(
            _("You do not have permission to access this taxonomy"),
            exc=frappe.PermissionError
        )

    # Get taxonomy document
    try:
        taxonomy = frappe.get_doc("Taxonomy", taxonomy_name)
    except frappe.DoesNotExistError:
        frappe.throw(
            _("Taxonomy '{0}' not found").format(taxonomy_name),
            exc=frappe.DoesNotExistError
        )

    # Build response
    result = _serialize_taxonomy(taxonomy)

    # Add optional data
    if include_nodes:
        result["nodes"] = get_node_tree(taxonomy=taxonomy_name)

    if include_statistics:
        result["statistics"] = _get_taxonomy_statistics(taxonomy_name)

    return result


@frappe.whitelist()
def get_taxonomies(
    enabled_only: bool = True,
    standard: Optional[str] = None,
    include_statistics: bool = False,
    limit: int = 100,
    offset: int = 0
) -> Dict[str, Any]:
    """Get all taxonomies with optional filters

    Args:
        enabled_only: If True, return only enabled taxonomies
        standard: Filter by standard type (GS1, UNSPSC, ECLASS, ETIM, Custom)
        include_statistics: Include usage statistics for each taxonomy
        limit: Maximum results to return (default 100)
        offset: Skip first N results for pagination

    Returns:
        Dictionary with 'data' (list of taxonomies) and 'total' count
    """
    enabled_only = _to_bool(enabled_only)
    include_statistics = _to_bool(include_statistics)
    limit = min(int(limit), 500)
    offset = int(offset)

    # Build filters
    filters = {}
    if enabled_only:
        filters["enabled"] = 1
    if standard:
        filters["standard"] = standard

    # Get taxonomies
    taxonomies = frappe.get_all(
        "Taxonomy",
        filters=filters,
        fields=[
            "name", "taxonomy_name", "taxonomy_code", "standard",
            "version", "enabled", "max_levels", "total_nodes",
            "products_classified", "description", "creation", "modified"
        ],
        order_by="taxonomy_name asc",
        limit_start=offset,
        limit_page_length=limit
    )

    # Add statistics if requested
    if include_statistics:
        for tax in taxonomies:
            tax["statistics"] = _get_taxonomy_statistics(tax["name"])

    # Get total count
    total = frappe.db.count("Taxonomy", filters=filters)

    return {
        "data": taxonomies,
        "total": total,
        "limit": limit,
        "offset": offset
    }


# ============================================================================
# Taxonomy Node APIs
# ============================================================================

@frappe.whitelist()
def get_node(
    name: Optional[str] = None,
    node_key: Optional[str] = None,
    include_ancestors: bool = False,
    include_children: bool = False,
    include_suggested_attributes: bool = False
) -> Dict[str, Any]:
    """Get a single taxonomy node by name or node_key

    Args:
        name: Taxonomy Node document name
        node_key: Unique node key (taxonomy_code-node_code)
        include_ancestors: Include ancestor path
        include_children: Include direct children
        include_suggested_attributes: Include suggested attributes

    Returns:
        Node data dictionary
    """
    include_ancestors = _to_bool(include_ancestors)
    include_children = _to_bool(include_children)
    include_suggested_attributes = _to_bool(include_suggested_attributes)

    # Validate input
    if not name and not node_key:
        frappe.throw(
            _("Either 'name' or 'node_key' parameter is required"),
            title=_("Missing Parameter")
        )

    # Find node
    node_name = name
    if not node_name and node_key:
        node_name = frappe.db.get_value("Taxonomy Node", {"node_key": node_key}, "name")
        if not node_name:
            frappe.throw(
                _("Taxonomy Node with key '{0}' not found").format(node_key),
                exc=frappe.DoesNotExistError
            )

    # Check permissions
    if not frappe.has_permission("Taxonomy Node", "read", node_name):
        frappe.throw(
            _("You do not have permission to access this node"),
            exc=frappe.PermissionError
        )

    # Get node
    try:
        node = frappe.get_doc("Taxonomy Node", node_name)
    except frappe.DoesNotExistError:
        frappe.throw(
            _("Taxonomy Node '{0}' not found").format(node_name),
            exc=frappe.DoesNotExistError
        )

    # Build response
    result = _serialize_node(node)

    # Add ancestors
    if include_ancestors:
        result["ancestors"] = _get_node_ancestors(node)

    # Add children
    if include_children:
        result["children"] = get_node_children(node_name=node_name)

    # Add suggested attributes
    if include_suggested_attributes:
        result["suggested_attributes"] = _get_node_suggested_attributes(node)

    return result


@frappe.whitelist()
def get_node_tree(
    taxonomy: str,
    parent: Optional[str] = None,
    include_disabled: bool = False,
    max_depth: int = 0
) -> List[Dict[str, Any]]:
    """Get taxonomy nodes as tree structure

    Args:
        taxonomy: Taxonomy name
        parent: Parent node name (None for root nodes)
        include_disabled: If True, include disabled nodes
        max_depth: Maximum depth to traverse (0 = unlimited)

    Returns:
        List of node dictionaries with optional children
    """
    include_disabled = _to_bool(include_disabled)
    max_depth = int(max_depth)

    # Check taxonomy permissions
    if not frappe.has_permission("Taxonomy", "read", taxonomy):
        frappe.throw(_("Permission denied"), exc=frappe.PermissionError)

    return _get_tree_recursive(
        taxonomy=taxonomy,
        parent=parent,
        include_disabled=include_disabled,
        max_depth=max_depth,
        current_depth=0
    )


@frappe.whitelist()
def get_node_children(
    node_name: Optional[str] = None,
    taxonomy: Optional[str] = None,
    include_disabled: bool = False
) -> List[Dict[str, Any]]:
    """Get direct children of a taxonomy node

    Args:
        node_name: Parent node name (if None, returns root nodes for taxonomy)
        taxonomy: Taxonomy name (required if node_name is None)
        include_disabled: If True, include disabled nodes

    Returns:
        List of child node dictionaries
    """
    include_disabled = _to_bool(include_disabled)

    # Determine taxonomy
    if node_name:
        taxonomy = frappe.db.get_value("Taxonomy Node", node_name, "taxonomy")
        if not taxonomy:
            frappe.throw(
                _("Node '{0}' not found").format(node_name),
                exc=frappe.DoesNotExistError
            )

    if not taxonomy:
        frappe.throw(
            _("Either 'node_name' or 'taxonomy' parameter is required"),
            title=_("Missing Parameter")
        )

    # Build filters
    filters = {"taxonomy": taxonomy}

    if node_name:
        filters["parent_node"] = node_name
    else:
        filters["parent_node"] = ["is", "not set"]

    if not include_disabled:
        filters["enabled"] = 1

    # Get children
    children = frappe.get_all(
        "Taxonomy Node",
        filters=filters,
        fields=[
            "name", "node_name", "node_code", "node_key", "level",
            "is_leaf", "is_group", "enabled", "children_count",
            "products_count", "full_path"
        ],
        order_by="lft asc, node_code asc"
    )

    # Add UI helper fields
    for child in children:
        child["expandable"] = child.get("is_group", False)
        child["value"] = child["name"]
        child["title"] = child["node_name"]

    return children


@frappe.whitelist()
def get_node_ancestors(node_name: str) -> List[Dict[str, Any]]:
    """Get all ancestors of a taxonomy node

    Args:
        node_name: Taxonomy Node name

    Returns:
        List of ancestor nodes from root to parent
    """
    if not frappe.has_permission("Taxonomy Node", "read", node_name):
        frappe.throw(_("Permission denied"), exc=frappe.PermissionError)

    try:
        node = frappe.get_doc("Taxonomy Node", node_name)
    except frappe.DoesNotExistError:
        frappe.throw(
            _("Taxonomy Node '{0}' not found").format(node_name),
            exc=frappe.DoesNotExistError
        )

    return _get_node_ancestors(node)


@frappe.whitelist()
def get_node_descendants(
    node_name: str,
    include_self: bool = False,
    leaf_only: bool = False
) -> List[Dict[str, Any]]:
    """Get all descendants of a taxonomy node

    Args:
        node_name: Taxonomy Node name
        include_self: If True, include the node itself
        leaf_only: If True, only return leaf nodes

    Returns:
        List of descendant node dictionaries
    """
    include_self = _to_bool(include_self)
    leaf_only = _to_bool(leaf_only)

    if not frappe.has_permission("Taxonomy Node", "read", node_name):
        frappe.throw(_("Permission denied"), exc=frappe.PermissionError)

    # Get node for lft/rgt
    lft, rgt, taxonomy = frappe.db.get_value(
        "Taxonomy Node", node_name, ["lft", "rgt", "taxonomy"]
    )

    if not lft or not rgt:
        frappe.throw(_("Node tree not built"), title=_("Tree Error"))

    # Build query conditions
    condition = ">=" if include_self else ">"
    end_condition = "<=" if include_self else "<"

    filters_sql = f"""
        taxonomy = %(taxonomy)s
        AND lft {condition} %(lft)s
        AND rgt {end_condition} %(rgt)s
    """

    if leaf_only:
        filters_sql += " AND is_leaf = 1"

    descendants = frappe.db.sql(
        f"""
        SELECT
            name, node_name, node_code, node_key, level,
            is_leaf, enabled, full_path
        FROM `tabTaxonomy Node`
        WHERE {filters_sql}
        AND enabled = 1
        ORDER BY lft
        """,
        {"taxonomy": taxonomy, "lft": lft, "rgt": rgt},
        as_dict=True
    )

    return descendants


# ============================================================================
# Search & Autocomplete APIs
# ============================================================================

@frappe.whitelist()
def search_nodes(
    query: str,
    taxonomy: Optional[str] = None,
    leaf_only: bool = False,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """Search taxonomy nodes by name, code, or keywords

    Args:
        query: Search query (minimum 2 characters)
        taxonomy: Limit search to specific taxonomy
        leaf_only: Only return classifiable (leaf) nodes
        limit: Maximum results (default 20, max 100)

    Returns:
        List of matching nodes with relevance scoring
    """
    if not query or len(query) < 2:
        return []

    leaf_only = _to_bool(leaf_only)
    limit = min(int(limit), 100)

    search_pattern = f"%{query}%"

    # Build taxonomy filter
    taxonomy_condition = ""
    params = {
        "search": search_pattern,
        "exact": query,
        "prefix": f"{query}%",
        "limit": limit
    }

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
            level, full_path, is_leaf, enabled
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
            node["taxonomy"],
            ["taxonomy_name", "taxonomy_code", "standard"],
            as_dict=True
        )
        if tax_info:
            node["taxonomy_name"] = tax_info["taxonomy_name"]
            node["taxonomy_code"] = tax_info["taxonomy_code"]
            node["standard"] = tax_info["standard"]

    return nodes


@frappe.whitelist()
def autocomplete_nodes(
    query: str,
    taxonomy: Optional[str] = None,
    limit: int = 10
) -> List[Dict[str, str]]:
    """Autocomplete node search for UI dropdowns

    Args:
        query: Search query (minimum 2 characters)
        taxonomy: Limit to specific taxonomy
        limit: Maximum results (default 10, max 50)

    Returns:
        List of nodes with name, code, and display label
    """
    if not query or len(query) < 2:
        return []

    limit = min(int(limit), 50)

    # Build taxonomy filter
    taxonomy_condition = ""
    params = {
        "search": f"%{query}%",
        "exact": query,
        "prefix": f"{query}%",
        "limit": limit
    }

    if taxonomy:
        taxonomy_condition = "AND taxonomy = %(taxonomy)s"
        params["taxonomy"] = taxonomy

    nodes = frappe.db.sql(
        f"""
        SELECT name, taxonomy, node_name, node_code, full_path, is_leaf
        FROM `tabTaxonomy Node`
        WHERE enabled = 1
        AND is_leaf = 1
        {taxonomy_condition}
        AND (
            node_name LIKE %(search)s
            OR node_code LIKE %(search)s
        )
        ORDER BY
            CASE
                WHEN node_code = %(exact)s THEN 0
                WHEN node_name = %(exact)s THEN 1
                WHEN node_code LIKE %(prefix)s THEN 2
                ELSE 3
            END,
            node_name ASC
        LIMIT %(limit)s
        """,
        params,
        as_dict=True
    )

    return [
        {
            "name": n["name"],
            "taxonomy": n["taxonomy"],
            "node_code": n["node_code"],
            "node_name": n["node_name"],
            "label": f"[{n['node_code']}] {n['node_name']}",
            "description": n["full_path"],
            "is_leaf": n["is_leaf"]
        }
        for n in nodes
    ]


# ============================================================================
# Classification APIs
# ============================================================================

@frappe.whitelist()
def get_product_classifications(
    sku: Optional[str] = None,
    product_name: Optional[str] = None,
    taxonomy: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Get classifications for a product

    Args:
        sku: Product SKU
        product_name: Product Master document name
        taxonomy: Filter by specific taxonomy

    Returns:
        List of classification dictionaries
    """
    # Find product
    if not product_name and sku:
        product_name = frappe.db.get_value("Product Master", {"sku": sku}, "name")

    if not product_name:
        frappe.throw(
            _("Product not found"),
            exc=frappe.DoesNotExistError
        )

    # Check permissions
    if not frappe.has_permission("Product Master", "read", product_name):
        frappe.throw(_("Permission denied"), exc=frappe.PermissionError)

    # Build filters
    filters = {"parent": product_name, "parenttype": "Product Master"}
    if taxonomy:
        filters["taxonomy"] = taxonomy

    # Get classifications
    try:
        classifications = frappe.get_all(
            "Product Classification",
            filters=filters,
            fields=[
                "name", "taxonomy", "taxonomy_node", "is_primary",
                "classification_date", "confidence_score", "source_system"
            ],
            order_by="is_primary desc, classification_date desc"
        )

        # Enrich with node details
        for cls in classifications:
            if cls.get("taxonomy_node"):
                node = frappe.db.get_value(
                    "Taxonomy Node",
                    cls["taxonomy_node"],
                    ["node_name", "node_code", "full_path", "level"],
                    as_dict=True
                )
                if node:
                    cls.update(node)

            if cls.get("taxonomy"):
                tax = frappe.db.get_value(
                    "Taxonomy",
                    cls["taxonomy"],
                    ["taxonomy_name", "taxonomy_code", "standard"],
                    as_dict=True
                )
                if tax:
                    cls["taxonomy_name"] = tax["taxonomy_name"]
                    cls["taxonomy_code"] = tax["taxonomy_code"]
                    cls["standard"] = tax["standard"]

        return classifications
    except Exception:
        return []


@frappe.whitelist()
def get_products_by_node(
    node_name: str,
    include_descendants: bool = False,
    limit: int = 20,
    offset: int = 0
) -> Dict[str, Any]:
    """Get products classified to a taxonomy node

    Args:
        node_name: Taxonomy Node name
        include_descendants: Include products from descendant nodes
        limit: Maximum results to return
        offset: Skip first N results for pagination

    Returns:
        Dictionary with 'data' (list of products) and 'total' count
    """
    include_descendants = _to_bool(include_descendants)
    limit = min(int(limit), 100)
    offset = int(offset)

    # Check permissions
    if not frappe.has_permission("Taxonomy Node", "read", node_name):
        frappe.throw(_("Permission denied"), exc=frappe.PermissionError)

    # Get node names to filter
    node_names = [node_name]

    if include_descendants:
        # Get all descendant nodes
        lft, rgt, taxonomy = frappe.db.get_value(
            "Taxonomy Node", node_name, ["lft", "rgt", "taxonomy"]
        )
        if lft and rgt:
            descendants = frappe.db.sql(
                """
                SELECT name FROM `tabTaxonomy Node`
                WHERE taxonomy = %s AND lft > %s AND rgt < %s
                """,
                (taxonomy, lft, rgt),
                as_list=True
            )
            node_names.extend([d[0] for d in descendants])

    # Get product names from classifications
    try:
        product_names = frappe.db.sql(
            """
            SELECT DISTINCT parent
            FROM `tabProduct Classification`
            WHERE taxonomy_node IN %(nodes)s
            AND parenttype = 'Product Master'
            LIMIT %(limit)s OFFSET %(offset)s
            """,
            {"nodes": node_names, "limit": limit, "offset": offset},
            as_list=True
        )

        total = frappe.db.sql(
            """
            SELECT COUNT(DISTINCT parent)
            FROM `tabProduct Classification`
            WHERE taxonomy_node IN %(nodes)s
            AND parenttype = 'Product Master'
            """,
            {"nodes": node_names},
            as_list=True
        )[0][0]

        # Get product details
        products = []
        for (pname,) in product_names:
            if frappe.has_permission("Product Master", "read", pname):
                product = frappe.db.get_value(
                    "Product Master",
                    pname,
                    ["name", "sku", "product_name", "status", "completeness_score"],
                    as_dict=True
                )
                if product:
                    products.append(product)

        return {
            "data": products,
            "total": total,
            "limit": limit,
            "offset": offset,
            "node": node_name,
            "include_descendants": include_descendants
        }
    except Exception:
        return {
            "data": [],
            "total": 0,
            "limit": limit,
            "offset": offset
        }


@frappe.whitelist()
def suggest_classification(
    sku: Optional[str] = None,
    product_name: Optional[str] = None,
    taxonomy: Optional[str] = None,
    text: Optional[str] = None,
    limit: int = 5
) -> List[Dict[str, Any]]:
    """Suggest taxonomy classifications for a product

    Uses product name/description or provided text to suggest matching nodes.

    Args:
        sku: Product SKU
        product_name: Product Master document name
        taxonomy: Limit suggestions to specific taxonomy
        text: Custom text to match (overrides product text)
        limit: Maximum suggestions to return

    Returns:
        List of suggested nodes with match scores
    """
    limit = min(int(limit), 20)

    # Get text for matching
    search_text = text
    if not search_text:
        # Find product
        pname = product_name
        if not pname and sku:
            pname = frappe.db.get_value("Product Master", {"sku": sku}, "name")

        if pname:
            product = frappe.db.get_value(
                "Product Master",
                pname,
                ["product_name", "short_description"],
                as_dict=True
            )
            if product:
                search_text = f"{product.get('product_name', '')} {product.get('short_description', '')}"

    if not search_text or len(search_text) < 3:
        return []

    # Extract keywords from search text
    keywords = _extract_keywords(search_text)

    if not keywords:
        return []

    # Build search pattern
    search_conditions = []
    params = {"limit": limit}

    for i, keyword in enumerate(keywords[:5]):  # Max 5 keywords
        param_name = f"kw{i}"
        params[param_name] = f"%{keyword}%"
        search_conditions.append(f"""(
            node_name LIKE %({param_name})s
            OR keywords LIKE %({param_name})s
            OR synonyms LIKE %({param_name})s
            OR description LIKE %({param_name})s
        )""")

    taxonomy_condition = ""
    if taxonomy:
        taxonomy_condition = "AND taxonomy = %(taxonomy)s"
        params["taxonomy"] = taxonomy

    # Search for matching nodes
    suggestions = frappe.db.sql(
        f"""
        SELECT
            name, taxonomy, node_name, node_code, node_key,
            full_path, level, is_leaf,
            ({" + ".join([f"({cond})" for cond in search_conditions])}) as match_score
        FROM `tabTaxonomy Node`
        WHERE enabled = 1
        AND is_leaf = 1
        {taxonomy_condition}
        AND ({" OR ".join(search_conditions)})
        ORDER BY match_score DESC, level ASC, node_name ASC
        LIMIT %(limit)s
        """,
        params,
        as_dict=True
    )

    # Enrich with taxonomy info
    for node in suggestions:
        tax_info = frappe.db.get_value(
            "Taxonomy",
            node["taxonomy"],
            ["taxonomy_name", "standard"],
            as_dict=True
        )
        if tax_info:
            node["taxonomy_name"] = tax_info["taxonomy_name"]
            node["standard"] = tax_info["standard"]

    return suggestions


# ============================================================================
# Validation APIs
# ============================================================================

@frappe.whitelist()
def validate_node_code(
    taxonomy: str,
    node_code: str
) -> Dict[str, Any]:
    """Validate a node code against taxonomy pattern

    Args:
        taxonomy: Taxonomy name
        node_code: Node code to validate

    Returns:
        Validation result with is_valid and message
    """
    try:
        tax_doc = frappe.get_doc("Taxonomy", taxonomy)
        is_valid = tax_doc.validate_node_code(node_code)

        return {
            "is_valid": is_valid,
            "node_code": node_code,
            "taxonomy": taxonomy,
            "pattern": tax_doc.node_code_pattern,
            "message": _("Valid node code") if is_valid else _("Node code does not match expected pattern")
        }
    except frappe.DoesNotExistError:
        return {
            "is_valid": False,
            "node_code": node_code,
            "taxonomy": taxonomy,
            "message": _("Taxonomy not found")
        }


@frappe.whitelist()
def get_level_info(
    taxonomy: str,
    level: int
) -> Dict[str, Any]:
    """Get information about a specific hierarchy level

    Args:
        taxonomy: Taxonomy name
        level: Level number (1-based)

    Returns:
        Level information including name and statistics
    """
    level = int(level)

    tax_doc = frappe.get_doc("Taxonomy", taxonomy)
    level_names = tax_doc.get_level_names()

    # Validate level
    if level < 1 or level > tax_doc.max_levels:
        frappe.throw(
            _("Invalid level. Must be between 1 and {0}").format(tax_doc.max_levels),
            title=_("Invalid Level")
        )

    # Get level name
    level_name = level_names[level - 1] if len(level_names) >= level else f"Level {level}"

    # Get statistics for this level
    node_count = frappe.db.count(
        "Taxonomy Node",
        {"taxonomy": taxonomy, "level": level, "enabled": 1}
    )

    return {
        "taxonomy": taxonomy,
        "level": level,
        "level_name": level_name,
        "max_levels": tax_doc.max_levels,
        "node_count": node_count
    }


# ============================================================================
# Crosswalk APIs
# ============================================================================

@frappe.whitelist()
def get_crosswalk_mappings(
    source_taxonomy: str,
    target_taxonomy: str,
    source_node: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Get crosswalk mappings between taxonomies

    Args:
        source_taxonomy: Source taxonomy name
        target_taxonomy: Target taxonomy name
        source_node: Optional specific source node to look up

    Returns:
        List of crosswalk mappings
    """
    filters = {
        "source_taxonomy": source_taxonomy,
        "target_taxonomy": target_taxonomy,
        "enabled": 1
    }

    if source_node:
        filters["source_node"] = source_node

    try:
        mappings = frappe.get_all(
            "Taxonomy Crosswalk",
            filters=filters,
            fields=[
                "name", "source_node", "target_node",
                "mapping_type", "confidence_score", "notes"
            ],
            order_by="confidence_score desc"
        )

        # Enrich with node details
        for mapping in mappings:
            if mapping.get("source_node"):
                source = frappe.db.get_value(
                    "Taxonomy Node",
                    mapping["source_node"],
                    ["node_name", "node_code", "full_path"],
                    as_dict=True
                )
                if source:
                    mapping["source_node_name"] = source["node_name"]
                    mapping["source_node_code"] = source["node_code"]
                    mapping["source_full_path"] = source["full_path"]

            if mapping.get("target_node"):
                target = frappe.db.get_value(
                    "Taxonomy Node",
                    mapping["target_node"],
                    ["node_name", "node_code", "full_path"],
                    as_dict=True
                )
                if target:
                    mapping["target_node_name"] = target["node_name"]
                    mapping["target_node_code"] = target["node_code"]
                    mapping["target_full_path"] = target["full_path"]

        return mappings
    except Exception:
        # Taxonomy Crosswalk may not exist yet
        return []


# ============================================================================
# Helper Functions
# ============================================================================

def _to_bool(value: Any) -> bool:
    """Convert various inputs to boolean"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes", "on")
    return bool(value)


def _serialize_taxonomy(taxonomy) -> Dict[str, Any]:
    """Serialize taxonomy document to dictionary"""
    return {
        "name": taxonomy.name,
        "taxonomy_name": taxonomy.taxonomy_name,
        "taxonomy_code": taxonomy.taxonomy_code,
        "standard": taxonomy.standard,
        "version": taxonomy.version,
        "description": taxonomy.description,
        "enabled": taxonomy.enabled,
        "max_levels": taxonomy.max_levels,
        "level_names": taxonomy.get_level_names(),
        "node_code_pattern": taxonomy.node_code_pattern,
        "total_nodes": taxonomy.total_nodes,
        "products_classified": taxonomy.products_classified,
        "creation": str(taxonomy.creation),
        "modified": str(taxonomy.modified)
    }


def _serialize_node(node) -> Dict[str, Any]:
    """Serialize taxonomy node to dictionary"""
    return {
        "name": node.name,
        "taxonomy": node.taxonomy,
        "node_name": node.node_name,
        "node_code": node.node_code,
        "node_key": node.node_key,
        "level": node.level,
        "parent_node": node.parent_node,
        "is_leaf": node.is_leaf,
        "is_group": node.is_group,
        "enabled": node.enabled,
        "description": node.description,
        "external_id": node.external_id,
        "synonyms": node.synonyms,
        "keywords": node.keywords,
        "full_path": node.full_path,
        "full_code_path": node.full_code_path,
        "children_count": node.children_count,
        "products_count": node.products_count
    }


def _get_taxonomy_statistics(taxonomy_name: str) -> Dict[str, Any]:
    """Get statistics for a taxonomy"""
    try:
        # Node counts by level
        level_stats = frappe.db.sql(
            """
            SELECT level, COUNT(*) as count
            FROM `tabTaxonomy Node`
            WHERE taxonomy = %s AND enabled = 1
            GROUP BY level
            ORDER BY level
            """,
            taxonomy_name,
            as_dict=True
        )

        # Total nodes
        total_nodes = frappe.db.count(
            "Taxonomy Node",
            {"taxonomy": taxonomy_name, "enabled": 1}
        )

        # Leaf nodes
        leaf_nodes = frappe.db.count(
            "Taxonomy Node",
            {"taxonomy": taxonomy_name, "enabled": 1, "is_leaf": 1}
        )

        # Products classified
        products_classified = frappe.db.count(
            "Product Classification",
            {"taxonomy": taxonomy_name}
        )

        return {
            "total_nodes": total_nodes,
            "leaf_nodes": leaf_nodes,
            "group_nodes": total_nodes - leaf_nodes,
            "products_classified": products_classified,
            "level_distribution": {str(s["level"]): s["count"] for s in level_stats}
        }
    except Exception:
        return {}


def _get_tree_recursive(
    taxonomy: str,
    parent: Optional[str],
    include_disabled: bool,
    max_depth: int,
    current_depth: int
) -> List[Dict[str, Any]]:
    """Recursively build tree structure"""
    # Build filters
    filters = {"taxonomy": taxonomy}

    if parent is None:
        filters["parent_node"] = ["is", "not set"]
    else:
        filters["parent_node"] = parent

    if not include_disabled:
        filters["enabled"] = 1

    # Get nodes
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

    # Add UI helper fields and recurse for children
    for node in nodes:
        node["expandable"] = node.get("is_group", False)
        node["value"] = node["name"]
        node["title"] = node["node_name"]

        # Check depth limit
        if max_depth == 0 or current_depth < max_depth - 1:
            if node.get("is_group"):
                node["children"] = _get_tree_recursive(
                    taxonomy=taxonomy,
                    parent=node["name"],
                    include_disabled=include_disabled,
                    max_depth=max_depth,
                    current_depth=current_depth + 1
                )

    return nodes


def _get_node_ancestors(node) -> List[Dict[str, Any]]:
    """Get ancestors of a node"""
    ancestors = []
    parent = node.parent_node

    while parent:
        parent_data = frappe.db.get_value(
            "Taxonomy Node",
            parent,
            ["name", "node_name", "node_code", "level", "parent_node"],
            as_dict=True
        )
        if parent_data:
            ancestors.insert(0, {
                "name": parent_data["name"],
                "node_name": parent_data["node_name"],
                "node_code": parent_data["node_code"],
                "level": parent_data["level"]
            })
            parent = parent_data["parent_node"]
        else:
            break

    return ancestors


def _get_node_suggested_attributes(node) -> List[Dict[str, Any]]:
    """Get suggested attributes for a taxonomy node"""
    try:
        suggestions = frappe.get_all(
            "Node Attribute Suggestion",
            filters={
                "parent": node.name,
                "parenttype": "Taxonomy Node"
            },
            fields=["attribute", "is_required", "sort_order"],
            order_by="sort_order asc"
        )

        # Enrich with attribute details
        for sug in suggestions:
            if sug.get("attribute"):
                attr = frappe.db.get_value(
                    "PIM Attribute",
                    sug["attribute"],
                    ["attribute_name", "attribute_type", "attribute_group"],
                    as_dict=True
                )
                if attr:
                    sug.update(attr)

        return suggestions
    except Exception:
        return []


def _extract_keywords(text: str) -> List[str]:
    """Extract keywords from text for matching"""
    import re

    # Remove special characters and convert to lowercase
    text = re.sub(r'[^\w\s]', ' ', text.lower())

    # Split into words
    words = text.split()

    # Filter stopwords and short words
    stopwords = {
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
        'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been',
        'be', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
        'could', 'should', 'may', 'might', 'must', 'shall', 'can', 'this',
        'that', 'these', 'those', 'it', 'its'
    }

    keywords = [w for w in words if len(w) >= 3 and w not in stopwords]

    # Remove duplicates while preserving order
    seen = set()
    unique = []
    for kw in keywords:
        if kw not in seen:
            seen.add(kw)
            unique.append(kw)

    return unique
