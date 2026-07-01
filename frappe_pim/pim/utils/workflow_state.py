"""
Workflow State Management Utility Module

This module provides functions for managing product lifecycle state transitions.
It defines valid state transitions, validates state changes, and tracks the
workflow history for products.

Key functionality:
- Define valid state transitions between lifecycle states
- Get valid next states for a product
- Validate state transition requests
- Apply state transitions with audit logging
- Get workflow statistics and reports
- Bulk state update operations

Product Lifecycle States:
1. In Preparation - Initial state for new products being created
2. In Production - Product is actively being worked on
3. Assigned - Product has been assigned to a responsible person
4. Awaiting Acceptance - Product is waiting for acceptance from assignee
5. Awaiting Approval - Product is waiting for management approval
6. Approved - Product has been approved and is ready for publication
7. Archived - Product has been archived/discontinued

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""


# Lifecycle states definition with display labels and descriptions
WORKFLOW_STATES = {
    "In Preparation": {
        "label": "In Preparation",
        "description": "Initial state for new products being created",
        "color": "blue",
        "is_initial": True,
        "is_terminal": False,
    },
    "In Production": {
        "label": "In Production",
        "description": "Product is actively being worked on",
        "color": "orange",
        "is_initial": False,
        "is_terminal": False,
    },
    "Assigned": {
        "label": "Assigned",
        "description": "Product has been assigned to a responsible person",
        "color": "purple",
        "is_initial": False,
        "is_terminal": False,
    },
    "Awaiting Acceptance": {
        "label": "Awaiting Acceptance",
        "description": "Product is waiting for acceptance from assignee",
        "color": "yellow",
        "is_initial": False,
        "is_terminal": False,
    },
    "Awaiting Approval": {
        "label": "Awaiting Approval",
        "description": "Product is waiting for management approval",
        "color": "yellow",
        "is_initial": False,
        "is_terminal": False,
    },
    "Approved": {
        "label": "Approved",
        "description": "Product has been approved and is ready for publication",
        "color": "green",
        "is_initial": False,
        "is_terminal": False,
    },
    "Archived": {
        "label": "Archived",
        "description": "Product has been archived/discontinued",
        "color": "gray",
        "is_initial": False,
        "is_terminal": True,
    },
}


# Valid state transitions (from_state -> list of allowed to_states)
# This defines the workflow rules for state changes
STATE_TRANSITIONS = {
    "In Preparation": ["In Production", "Assigned", "Archived"],
    "In Production": ["In Preparation", "Assigned", "Awaiting Acceptance", "Archived"],
    "Assigned": ["In Production", "Awaiting Acceptance", "Archived"],
    "Awaiting Acceptance": ["Assigned", "Awaiting Approval", "In Production", "Archived"],
    "Awaiting Approval": ["Awaiting Acceptance", "Approved", "In Production", "Archived"],
    "Approved": ["In Production", "Awaiting Approval", "Archived"],
    "Archived": ["In Preparation"],  # Can only reactivate to initial state
}


# Default initial state for new products
DEFAULT_STATE = "In Preparation"


def get_valid_transitions(current_state):
    """Get list of valid next states from the current state.

    Returns all states that the product can transition to from
    its current workflow state.

    Args:
        current_state: Current workflow state name (str)

    Returns:
        list: List of valid target state names. Returns empty list
              if current_state is invalid.

    Example:
        >>> valid = get_valid_transitions("In Production")
        >>> print(valid)
        ['In Preparation', 'Assigned', 'Awaiting Acceptance', 'Archived']
    """
    if not current_state:
        return []

    return STATE_TRANSITIONS.get(current_state, [])


def is_valid_transition(from_state, to_state):
    """Check if a state transition is valid.

    Validates whether transitioning from one state to another
    is allowed according to the workflow rules.

    Args:
        from_state: Current workflow state name (str)
        to_state: Target workflow state name (str)

    Returns:
        bool: True if transition is valid, False otherwise

    Example:
        >>> is_valid_transition("In Production", "Approved")
        False
        >>> is_valid_transition("In Production", "Assigned")
        True
    """
    if not from_state or not to_state:
        return False

    if from_state not in WORKFLOW_STATES:
        return False

    if to_state not in WORKFLOW_STATES:
        return False

    valid_targets = get_valid_transitions(from_state)
    return to_state in valid_targets


def get_state_info(state):
    """Get detailed information about a workflow state.

    Returns metadata about the specified workflow state including
    its label, description, color, and flags.

    Args:
        state: Workflow state name (str)

    Returns:
        dict: State information containing:
            - name: State name
            - label: Display label
            - description: State description
            - color: UI color indicator
            - is_initial: Whether this is the initial state
            - is_terminal: Whether this is a terminal state
            - valid_transitions: List of valid next states

        Returns None if state is not found.

    Example:
        >>> info = get_state_info("In Production")
        >>> print(info["description"])
        'Product is actively being worked on'
    """
    if state not in WORKFLOW_STATES:
        return None

    state_config = WORKFLOW_STATES[state].copy()
    state_config["name"] = state
    state_config["valid_transitions"] = get_valid_transitions(state)
    return state_config


def get_all_states():
    """Get information about all workflow states.

    Returns a list of all available workflow states with their
    metadata and valid transitions.

    Returns:
        list: List of state info dicts

    Example:
        >>> states = get_all_states()
        >>> for s in states:
        ...     print(f"{s['name']}: {s['description']}")
    """
    states = []
    for state_name in WORKFLOW_STATES.keys():
        states.append(get_state_info(state_name))
    return states


def validate_transition(doc, method=None):
    """Validate workflow state transition on product save.

    This function is designed to be used as a doc_event hook.
    It checks if the state transition from the old state to
    the new state is valid according to workflow rules.

    Args:
        doc: The Product Master document being saved
        method: The hook method name (unused, for Frappe hook signature)

    Returns:
        dict: Validation result with:
            - is_valid: Boolean indicating transition validity
            - from_state: Previous state
            - to_state: New state
            - message: Validation message

    Raises:
        frappe.ValidationError: If transition is invalid

    Example:
        # In hooks.py:
        # doc_events = {
        #     "Product Master": {
        #         "before_save": "frappe_pim.pim.utils.workflow_state.validate_transition"
        #     }
        # }
    """
    import frappe

    try:
        new_state = doc.get("workflow_state")
        if not new_state:
            return {"is_valid": True, "from_state": None, "to_state": None, "message": "No workflow state set"}

        # Get old state if document exists
        old_state = None
        if doc.name and not doc.is_new():
            old_doc = frappe.get_doc("Product Master", doc.name)
            old_state = old_doc.get("workflow_state")

        # If no old state, this is a new document - allow any initial state
        if not old_state:
            if new_state not in WORKFLOW_STATES:
                frappe.throw(
                    f"Invalid workflow state: {new_state}",
                    title="Invalid Workflow State"
                )
            return {"is_valid": True, "from_state": None, "to_state": new_state, "message": "Initial state set"}

        # If state hasn't changed, no validation needed
        if old_state == new_state:
            return {"is_valid": True, "from_state": old_state, "to_state": new_state, "message": "State unchanged"}

        # Validate the transition
        if not is_valid_transition(old_state, new_state):
            valid_states = get_valid_transitions(old_state)
            frappe.throw(
                f"Cannot transition from '{old_state}' to '{new_state}'. "
                f"Valid transitions: {', '.join(valid_states) if valid_states else 'None'}",
                title="Invalid State Transition"
            )

        return {
            "is_valid": True,
            "from_state": old_state,
            "to_state": new_state,
            "message": f"Valid transition from '{old_state}' to '{new_state}'"
        }

    except frappe.ValidationError:
        raise
    except Exception as e:
        import frappe
        frappe.log_error(
            message=f"Error validating workflow transition for {doc.name}: {str(e)}",
            title="PIM Workflow Validation Error"
        )
        return {"is_valid": False, "from_state": None, "to_state": None, "message": str(e)}


def apply_transition(product, new_state, user=None, comment=None):
    """Apply a workflow state transition to a product.

    Changes the product's workflow state and logs the transition.
    Validates the transition before applying.

    Args:
        product: Product Master name (str) or Product Master document
        new_state: Target workflow state name (str)
        user: User who is making the transition (optional, defaults to current user)
        comment: Optional comment for the transition

    Returns:
        dict: Result containing:
            - success: Boolean indicating if transition was applied
            - product: Product name
            - from_state: Previous state
            - to_state: New state
            - message: Result message
            - timestamp: When the transition was applied

    Example:
        >>> result = apply_transition("PROD-001", "Approved", comment="Ready for publishing")
        >>> print(result["success"])
        True
    """
    import frappe
    from frappe.utils import now_datetime

    try:
        # Get product document
        if isinstance(product, str):
            product_name = product
            # Product Master is a virtual DocType backed by Item
            if not frappe.db.exists("Item", product_name):
                return _error_result(product_name, "Product not found")
            product_doc = frappe.get_doc("Product Master", product_name)
        else:
            product_doc = product
            product_name = product_doc.name

        # Get current state
        current_state = product_doc.get("workflow_state") or DEFAULT_STATE

        # Validate transition
        if not is_valid_transition(current_state, new_state):
            valid_states = get_valid_transitions(current_state)
            return _error_result(
                product_name,
                f"Invalid transition from '{current_state}' to '{new_state}'. "
                f"Valid: {', '.join(valid_states) if valid_states else 'None'}",
                current_state,
                new_state
            )

        # Apply the transition
        # Use db_update instead of save to avoid global_search issues
        # with uninitialized child tables on the virtual Product Master
        product_doc.workflow_state = new_state
        product_doc.db_update()

        # Log the transition
        _log_transition(
            product_name,
            current_state,
            new_state,
            user or frappe.session.user,
            comment
        )

        return {
            "success": True,
            "product": product_name,
            "from_state": current_state,
            "to_state": new_state,
            "message": f"Successfully transitioned from '{current_state}' to '{new_state}'",
            "timestamp": str(now_datetime()),
        }

    except Exception as e:
        import frappe
        frappe.log_error(
            message=f"Error applying workflow transition: {str(e)}",
            title="PIM Workflow Transition Error"
        )
        return _error_result(str(product), str(e))


def get_product_workflow_status(product):
    """Get comprehensive workflow status for a product.

    Returns the current workflow state along with available
    transitions and additional metadata.

    Args:
        product: Product Master name (str) or Product Master document

    Returns:
        dict: Workflow status containing:
            - product: Product name
            - current_state: Current workflow state
            - state_info: Full state information
            - valid_transitions: List of valid next states
            - can_be_approved: Whether product can transition to Approved
            - can_be_archived: Whether product can be archived
            - is_archived: Whether product is currently archived

    Example:
        >>> status = get_product_workflow_status("PROD-001")
        >>> print(status["current_state"])
        'In Production'
        >>> print(status["can_be_approved"])
        False
    """
    import frappe

    try:
        # Get product document
        if isinstance(product, str):
            product_name = product
            if not frappe.db.exists("Item", product_name):
                return _empty_workflow_status(product_name)
            product_doc = frappe.get_doc("Product Master", product_name)
        else:
            product_doc = product
            product_name = product_doc.name

        # Get current state
        current_state = product_doc.get("workflow_state") or DEFAULT_STATE

        # Get state info and valid transitions
        state_info = get_state_info(current_state)
        valid_transitions = get_valid_transitions(current_state)

        return {
            "product": product_name,
            "current_state": current_state,
            "state_info": state_info,
            "valid_transitions": valid_transitions,
            "can_be_approved": "Approved" in valid_transitions,
            "can_be_archived": "Archived" in valid_transitions,
            "is_archived": current_state == "Archived",
            "is_initial_state": state_info.get("is_initial", False) if state_info else False,
        }

    except Exception as e:
        import frappe
        frappe.log_error(
            message=f"Error getting workflow status for {product}: {str(e)}",
            title="PIM Workflow Status Error"
        )
        return _empty_workflow_status(str(product))


def get_products_by_state(
    state,
    product_family=None,
    category=None,
    limit=100,
):
    """Get products in a specific workflow state.

    Retrieves all products that are currently in the specified
    workflow state.

    Args:
        state: Workflow state name to filter by
        product_family: Filter by product family (optional)
        category: Filter by category (optional)
        limit: Maximum number of products to return (default: 100)

    Returns:
        list: List of dicts containing:
            - name: Product Master name
            - product_name: Display name
            - product_family: Product family
            - category: Category
            - workflow_state: Workflow state
            - modified: Last modified date

    Example:
        >>> products = get_products_by_state("Awaiting Approval")
        >>> print(f"Found {len(products)} products awaiting approval")
    """
    import frappe

    try:
        if state not in WORKFLOW_STATES:
            return []

        # Build filters
        filters = {"workflow_state": state}
        if product_family:
            filters["product_family"] = product_family
        if category:
            filters["category"] = category

        # Get products
        products = frappe.get_all(
            "Product Master",
            filters=filters,
            fields=["name", "product_name", "product_family", "category", "workflow_state", "modified"],
            order_by="modified desc",
            limit=limit,
        )

        return products

    except Exception as e:
        import frappe
        frappe.log_error(
            message=f"Error getting products by state '{state}': {str(e)}",
            title="PIM Workflow Query Error"
        )
        return []


def get_workflow_statistics(product_family=None, category=None):
    """Get workflow state distribution statistics.

    Calculates the count and percentage of products in each
    workflow state.

    Args:
        product_family: Filter by product family (optional)
        category: Filter by category (optional)

    Returns:
        dict: Statistics containing:
            - total_products: Total number of products
            - by_state: Dict with counts and percentages per state
            - active_count: Products not in Archived state
            - archived_count: Products in Archived state
            - pending_approval: Products in approval-related states
            - in_progress: Products actively being worked on

    Example:
        >>> stats = get_workflow_statistics()
        >>> print(f"Total: {stats['total_products']}")
        >>> print(f"Archived: {stats['archived_count']}")
    """
    import frappe
    from frappe.utils import flt

    try:
        # Build filters
        filters = {}
        if product_family:
            filters["product_family"] = product_family
        if category:
            filters["category"] = category

        # Get all products with their states
        products = frappe.get_all(
            "Product Master",
            filters=filters,
            fields=["workflow_state"],
            limit=10000,
        )

        if not products:
            return _empty_statistics()

        total = len(products)

        # Count by state
        state_counts = {state: 0 for state in WORKFLOW_STATES.keys()}
        for p in products:
            state = p.get("workflow_state") or DEFAULT_STATE
            if state in state_counts:
                state_counts[state] += 1
            else:
                # Handle unknown states
                state_counts[state] = state_counts.get(state, 0) + 1

        # Calculate percentages and build result
        by_state = {}
        for state, count in state_counts.items():
            by_state[state] = {
                "count": count,
                "percentage": flt((count / total) * 100, 2) if total > 0 else 0,
                "label": WORKFLOW_STATES.get(state, {}).get("label", state),
                "color": WORKFLOW_STATES.get(state, {}).get("color", "gray"),
            }

        # Calculate aggregate counts
        archived_count = state_counts.get("Archived", 0)
        active_count = total - archived_count

        pending_approval_states = ["Awaiting Acceptance", "Awaiting Approval"]
        pending_approval = sum(state_counts.get(s, 0) for s in pending_approval_states)

        in_progress_states = ["In Preparation", "In Production", "Assigned"]
        in_progress = sum(state_counts.get(s, 0) for s in in_progress_states)

        return {
            "total_products": total,
            "by_state": by_state,
            "active_count": active_count,
            "archived_count": archived_count,
            "pending_approval": pending_approval,
            "in_progress": in_progress,
            "approved_count": state_counts.get("Approved", 0),
        }

    except Exception as e:
        import frappe
        frappe.log_error(
            message=f"Error calculating workflow statistics: {str(e)}",
            title="PIM Workflow Statistics Error"
        )
        return _empty_statistics()


def get_products_pending_action(user=None, action_type=None, limit=50):
    """Get products pending action from a specific user or action type.

    Retrieves products that require attention, such as those
    awaiting approval or acceptance.

    Args:
        user: Filter by assigned user (optional)
        action_type: Type of action needed - "approval", "acceptance", "all" (default: "all")
        limit: Maximum number of products to return (default: 50)

    Returns:
        list: List of product dicts with workflow status

    Example:
        >>> pending = get_products_pending_action(action_type="approval")
        >>> for p in pending:
        ...     print(f"{p['name']} needs approval")
    """
    import frappe

    try:
        # Determine states to filter
        if action_type == "approval":
            states = ["Awaiting Approval"]
        elif action_type == "acceptance":
            states = ["Awaiting Acceptance"]
        else:
            states = ["Awaiting Approval", "Awaiting Acceptance"]

        # Build filters
        filters = {"workflow_state": ["in", states]}

        # Get products
        products = frappe.get_all(
            "Product Master",
            filters=filters,
            fields=[
                "name",
                "product_name",
                "product_family",
                "category",
                "workflow_state",
                "modified",
                "modified_by",
            ],
            order_by="modified asc",  # Oldest first
            limit=limit,
        )

        # Add state info to each product
        for p in products:
            p["state_info"] = get_state_info(p.get("workflow_state"))
            p["valid_transitions"] = get_valid_transitions(p.get("workflow_state"))

        return products

    except Exception as e:
        import frappe
        frappe.log_error(
            message=f"Error getting products pending action: {str(e)}",
            title="PIM Workflow Pending Error"
        )
        return []


def bulk_transition(products, new_state, user=None, comment=None):
    """Apply workflow state transition to multiple products.

    Changes the workflow state for a list of products.
    Products with invalid transitions are skipped.

    Args:
        products: List of Product Master names
        new_state: Target workflow state name (str)
        user: User who is making the transition (optional)
        comment: Optional comment for all transitions

    Returns:
        dict: Results containing:
            - success_count: Number of successful transitions
            - failed_count: Number of failed transitions
            - results: List of individual results
            - errors: List of products with errors

    Example:
        >>> result = bulk_transition(["PROD-001", "PROD-002"], "Archived")
        >>> print(f"Archived {result['success_count']} products")
    """
    import frappe
    from frappe.utils import now_datetime

    try:
        results = []
        errors = []
        success_count = 0
        failed_count = 0

        for product_name in products:
            try:
                result = apply_transition(
                    product_name,
                    new_state,
                    user=user,
                    comment=comment
                )
                results.append(result)

                if result.get("success"):
                    success_count += 1
                else:
                    failed_count += 1
                    errors.append({
                        "product": product_name,
                        "error": result.get("message", "Unknown error"),
                    })

            except Exception as e:
                failed_count += 1
                errors.append({
                    "product": product_name,
                    "error": str(e),
                })

        return {
            "success_count": success_count,
            "failed_count": failed_count,
            "total_count": len(products),
            "results": results,
            "errors": errors,
            "timestamp": str(now_datetime()),
        }

    except Exception as e:
        import frappe
        frappe.log_error(
            message=f"Error in bulk workflow transition: {str(e)}",
            title="PIM Bulk Transition Error"
        )
        return {
            "success_count": 0,
            "failed_count": len(products),
            "total_count": len(products),
            "results": [],
            "errors": [{"product": "bulk", "error": str(e)}],
        }


def get_transition_path(from_state, to_state):
    """Find the shortest path between two workflow states.

    Calculates the sequence of state transitions needed to
    get from one state to another.

    Args:
        from_state: Starting workflow state
        to_state: Target workflow state

    Returns:
        list: List of states in the path, or empty list if no path exists

    Example:
        >>> path = get_transition_path("In Preparation", "Approved")
        >>> print(path)
        ['In Preparation', 'In Production', 'Assigned', 'Awaiting Acceptance', 'Awaiting Approval', 'Approved']
    """
    if from_state not in WORKFLOW_STATES or to_state not in WORKFLOW_STATES:
        return []

    if from_state == to_state:
        return [from_state]

    # BFS to find shortest path
    from collections import deque

    queue = deque([[from_state]])
    visited = {from_state}

    while queue:
        path = queue.popleft()
        current = path[-1]

        for next_state in get_valid_transitions(current):
            if next_state == to_state:
                return path + [next_state]

            if next_state not in visited:
                visited.add(next_state)
                queue.append(path + [next_state])

    return []  # No path found


def get_workflow_graph():
    """Get the full workflow graph for visualization.

    Returns the complete workflow structure that can be used
    for generating workflow diagrams.

    Returns:
        dict: Workflow graph containing:
            - states: List of state nodes with metadata
            - transitions: List of edges between states
            - initial_state: The default initial state
            - terminal_states: List of terminal states

    Example:
        >>> graph = get_workflow_graph()
        >>> for t in graph["transitions"]:
        ...     print(f"{t['from']} -> {t['to']}")
    """
    states = []
    transitions = []
    terminal_states = []

    for state_name, state_config in WORKFLOW_STATES.items():
        states.append({
            "name": state_name,
            "label": state_config["label"],
            "description": state_config["description"],
            "color": state_config["color"],
            "is_initial": state_config["is_initial"],
            "is_terminal": state_config["is_terminal"],
        })

        if state_config["is_terminal"]:
            terminal_states.append(state_name)

        # Add transitions
        for target in STATE_TRANSITIONS.get(state_name, []):
            transitions.append({
                "from": state_name,
                "to": target,
            })

    return {
        "states": states,
        "transitions": transitions,
        "initial_state": DEFAULT_STATE,
        "terminal_states": terminal_states,
    }


def can_user_transition(user, from_state, to_state):
    """Check if a user has permission to perform a state transition.

    Validates both the transition rules and user permissions.
    This can be extended to include role-based restrictions.

    Args:
        user: User name or email
        from_state: Current workflow state
        to_state: Target workflow state

    Returns:
        dict: Permission check result containing:
            - allowed: Boolean indicating if transition is allowed
            - reason: Reason for denial if not allowed
            - requires_approval: Whether the transition needs approval

    Example:
        >>> result = can_user_transition("user@example.com", "In Production", "Approved")
        >>> if not result["allowed"]:
        ...     print(result["reason"])
    """
    import frappe

    try:
        # First check if transition is valid
        if not is_valid_transition(from_state, to_state):
            return {
                "allowed": False,
                "reason": f"Invalid transition from '{from_state}' to '{to_state}'",
                "requires_approval": False,
            }

        # Check user permissions on Product Master
        if not frappe.has_permission("Product Master", "write", user=user):
            return {
                "allowed": False,
                "reason": "User does not have write permission on Product Master",
                "requires_approval": False,
            }

        # Check for special transitions that might require elevated permissions
        requires_approval = to_state in ["Approved"]

        # Approval transitions might require PIM Manager role
        if to_state == "Approved":
            user_roles = frappe.get_roles(user)
            if "PIM Manager" not in user_roles and "System Manager" not in user_roles:
                return {
                    "allowed": False,
                    "reason": "Only PIM Manager or System Manager can approve products",
                    "requires_approval": True,
                }

        return {
            "allowed": True,
            "reason": None,
            "requires_approval": requires_approval,
        }

    except Exception as e:
        import frappe
        frappe.log_error(
            message=f"Error checking transition permission: {str(e)}",
            title="PIM Workflow Permission Error"
        )
        return {
            "allowed": False,
            "reason": str(e),
            "requires_approval": False,
        }


# Private helper functions


def _log_transition(product, from_state, to_state, user, comment=None):
    """Log a workflow state transition.

    Creates a log entry for audit purposes.

    Args:
        product: Product Master name
        from_state: Previous state
        to_state: New state
        user: User who made the transition
        comment: Optional comment
    """
    import frappe
    from frappe.utils import now_datetime

    try:
        frappe.get_doc({
            "doctype": "Comment",
            "comment_type": "Info",
            "reference_doctype": "Product Master",
            "reference_name": product,
            "content": f"Workflow state changed from '{from_state}' to '{to_state}'" +
                       (f". Comment: {comment}" if comment else ""),
        }).insert(ignore_permissions=True)

    except Exception as e:
        frappe.log_error(
            message=f"Error logging transition for {product}: {str(e)}",
            title="PIM Workflow Log Error"
        )


def _error_result(product_name, message, from_state=None, to_state=None):
    """Return error result structure.

    Args:
        product_name: Product name
        message: Error message
        from_state: Current state (optional)
        to_state: Target state (optional)

    Returns:
        dict: Error result dictionary
    """
    from frappe.utils import now_datetime

    return {
        "success": False,
        "product": product_name,
        "from_state": from_state,
        "to_state": to_state,
        "message": message,
        "timestamp": str(now_datetime()) if 'now_datetime' in dir() else None,
    }


def _empty_workflow_status(product_name=None):
    """Return empty workflow status structure.

    Args:
        product_name: Product name for the result

    Returns:
        dict: Empty workflow status dictionary
    """
    return {
        "product": product_name,
        "current_state": None,
        "state_info": None,
        "valid_transitions": [],
        "can_be_approved": False,
        "can_be_archived": False,
        "is_archived": False,
        "is_initial_state": False,
    }


def _empty_statistics():
    """Return empty statistics result structure.

    Returns:
        dict: Empty statistics dictionary
    """
    return {
        "total_products": 0,
        "by_state": {},
        "active_count": 0,
        "archived_count": 0,
        "pending_approval": 0,
        "in_progress": 0,
        "approved_count": 0,
    }
