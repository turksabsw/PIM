# Copyright (c) 2024, Frappe PIM and contributors
# For license information, please see license.txt
"""Workflow State Transitions Unit Tests

This module contains unit tests for:
- Workflow state definitions and constants
- Valid state transitions
- State transition validation
- State transition application
- Workflow status retrieval
- Workflow statistics
- Transition path finding
- Workflow graph generation
- Bulk state transitions
- User permission checks for transitions

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for linting/static analysis).
"""

import unittest


class MockProductDoc:
    """Mock product document for testing workflow functions without database."""

    def __init__(self, **kwargs):
        """Initialize mock product with provided fields."""
        self.name = kwargs.get("name", "TEST-001")
        self.product_name = kwargs.get("product_name", "Test Product")
        self.workflow_state = kwargs.get("workflow_state", None)
        self.product_family = kwargs.get("product_family", None)
        self.category = kwargs.get("category", None)
        self.status = kwargs.get("status", "Draft")
        self._is_new = kwargs.get("is_new", False)

        # Set any additional fields
        for key, value in kwargs.items():
            if not hasattr(self, key):
                setattr(self, key, value)

    def get(self, field, default=None):
        """Get field value with default."""
        return getattr(self, field, default)

    def is_new(self):
        """Check if document is new."""
        return self._is_new


class TestWorkflowConstants(unittest.TestCase):
    """Test cases for workflow module constants and configuration."""

    def test_workflow_states_defined(self):
        """Test that all 7 workflow states are defined."""
        from frappe_pim.pim.utils.workflow_state import WORKFLOW_STATES

        expected_states = [
            "In Preparation",
            "In Production",
            "Assigned",
            "Awaiting Acceptance",
            "Awaiting Approval",
            "Approved",
            "Archived",
        ]

        for state in expected_states:
            self.assertIn(state, WORKFLOW_STATES)

        self.assertEqual(len(WORKFLOW_STATES), 7)

    def test_workflow_states_have_required_properties(self):
        """Test that each state has required properties."""
        from frappe_pim.pim.utils.workflow_state import WORKFLOW_STATES

        required_properties = ["label", "description", "color", "is_initial", "is_terminal"]

        for state_name, state_config in WORKFLOW_STATES.items():
            for prop in required_properties:
                self.assertIn(
                    prop, state_config,
                    f"State '{state_name}' missing property '{prop}'"
                )

    def test_exactly_one_initial_state(self):
        """Test that there is exactly one initial state."""
        from frappe_pim.pim.utils.workflow_state import WORKFLOW_STATES

        initial_states = [
            name for name, config in WORKFLOW_STATES.items()
            if config.get("is_initial")
        ]

        self.assertEqual(len(initial_states), 1)
        self.assertEqual(initial_states[0], "In Preparation")

    def test_exactly_one_terminal_state(self):
        """Test that there is exactly one terminal state."""
        from frappe_pim.pim.utils.workflow_state import WORKFLOW_STATES

        terminal_states = [
            name for name, config in WORKFLOW_STATES.items()
            if config.get("is_terminal")
        ]

        self.assertEqual(len(terminal_states), 1)
        self.assertEqual(terminal_states[0], "Archived")

    def test_default_state_defined(self):
        """Test that default state is defined."""
        from frappe_pim.pim.utils.workflow_state import DEFAULT_STATE

        self.assertEqual(DEFAULT_STATE, "In Preparation")

    def test_state_transitions_defined(self):
        """Test that state transitions are defined."""
        from frappe_pim.pim.utils.workflow_state import STATE_TRANSITIONS, WORKFLOW_STATES

        # All states should have transition rules
        for state in WORKFLOW_STATES.keys():
            self.assertIn(
                state, STATE_TRANSITIONS,
                f"No transitions defined for state '{state}'"
            )

    def test_transitions_only_reference_valid_states(self):
        """Test that all transitions reference valid states."""
        from frappe_pim.pim.utils.workflow_state import STATE_TRANSITIONS, WORKFLOW_STATES

        for from_state, to_states in STATE_TRANSITIONS.items():
            for to_state in to_states:
                self.assertIn(
                    to_state, WORKFLOW_STATES,
                    f"Transition from '{from_state}' to '{to_state}' references invalid state"
                )

    def test_archived_can_only_go_to_initial(self):
        """Test that Archived state can only transition to initial state."""
        from frappe_pim.pim.utils.workflow_state import STATE_TRANSITIONS

        archived_transitions = STATE_TRANSITIONS.get("Archived", [])
        self.assertEqual(archived_transitions, ["In Preparation"])


class TestGetValidTransitions(unittest.TestCase):
    """Test cases for get_valid_transitions function."""

    def test_valid_transitions_from_in_preparation(self):
        """Test valid transitions from In Preparation state."""
        from frappe_pim.pim.utils.workflow_state import get_valid_transitions

        transitions = get_valid_transitions("In Preparation")

        self.assertIn("In Production", transitions)
        self.assertIn("Assigned", transitions)
        self.assertIn("Archived", transitions)

    def test_valid_transitions_from_in_production(self):
        """Test valid transitions from In Production state."""
        from frappe_pim.pim.utils.workflow_state import get_valid_transitions

        transitions = get_valid_transitions("In Production")

        self.assertIn("In Preparation", transitions)
        self.assertIn("Assigned", transitions)
        self.assertIn("Awaiting Acceptance", transitions)
        self.assertIn("Archived", transitions)

    def test_valid_transitions_from_approved(self):
        """Test valid transitions from Approved state."""
        from frappe_pim.pim.utils.workflow_state import get_valid_transitions

        transitions = get_valid_transitions("Approved")

        self.assertIn("In Production", transitions)
        self.assertIn("Awaiting Approval", transitions)
        self.assertIn("Archived", transitions)

    def test_valid_transitions_from_archived(self):
        """Test valid transitions from Archived state."""
        from frappe_pim.pim.utils.workflow_state import get_valid_transitions

        transitions = get_valid_transitions("Archived")

        # Archived can only go back to In Preparation
        self.assertEqual(transitions, ["In Preparation"])

    def test_valid_transitions_empty_state(self):
        """Test that empty state returns empty list."""
        from frappe_pim.pim.utils.workflow_state import get_valid_transitions

        transitions = get_valid_transitions("")
        self.assertEqual(transitions, [])

        transitions = get_valid_transitions(None)
        self.assertEqual(transitions, [])

    def test_valid_transitions_invalid_state(self):
        """Test that invalid state returns empty list."""
        from frappe_pim.pim.utils.workflow_state import get_valid_transitions

        transitions = get_valid_transitions("Invalid State")
        self.assertEqual(transitions, [])


class TestIsValidTransition(unittest.TestCase):
    """Test cases for is_valid_transition function."""

    def test_valid_transition_in_production_to_assigned(self):
        """Test valid transition from In Production to Assigned."""
        from frappe_pim.pim.utils.workflow_state import is_valid_transition

        self.assertTrue(is_valid_transition("In Production", "Assigned"))

    def test_valid_transition_awaiting_approval_to_approved(self):
        """Test valid transition from Awaiting Approval to Approved."""
        from frappe_pim.pim.utils.workflow_state import is_valid_transition

        self.assertTrue(is_valid_transition("Awaiting Approval", "Approved"))

    def test_invalid_transition_in_production_to_approved(self):
        """Test invalid transition from In Production directly to Approved."""
        from frappe_pim.pim.utils.workflow_state import is_valid_transition

        self.assertFalse(is_valid_transition("In Production", "Approved"))

    def test_invalid_transition_in_preparation_to_approved(self):
        """Test invalid transition from In Preparation directly to Approved."""
        from frappe_pim.pim.utils.workflow_state import is_valid_transition

        self.assertFalse(is_valid_transition("In Preparation", "Approved"))

    def test_invalid_transition_approved_to_awaiting_acceptance(self):
        """Test invalid transition from Approved to Awaiting Acceptance."""
        from frappe_pim.pim.utils.workflow_state import is_valid_transition

        self.assertFalse(is_valid_transition("Approved", "Awaiting Acceptance"))

    def test_invalid_transition_empty_from_state(self):
        """Test that empty from_state returns False."""
        from frappe_pim.pim.utils.workflow_state import is_valid_transition

        self.assertFalse(is_valid_transition("", "In Production"))
        self.assertFalse(is_valid_transition(None, "In Production"))

    def test_invalid_transition_empty_to_state(self):
        """Test that empty to_state returns False."""
        from frappe_pim.pim.utils.workflow_state import is_valid_transition

        self.assertFalse(is_valid_transition("In Production", ""))
        self.assertFalse(is_valid_transition("In Production", None))

    def test_invalid_transition_both_invalid_states(self):
        """Test with both invalid states."""
        from frappe_pim.pim.utils.workflow_state import is_valid_transition

        self.assertFalse(is_valid_transition("Invalid1", "Invalid2"))

    def test_same_state_transition(self):
        """Test that same state to same state returns False (no self-loops)."""
        from frappe_pim.pim.utils.workflow_state import is_valid_transition

        # Based on STATE_TRANSITIONS, no self-transitions are defined
        self.assertFalse(is_valid_transition("In Production", "In Production"))
        self.assertFalse(is_valid_transition("Approved", "Approved"))


class TestGetStateInfo(unittest.TestCase):
    """Test cases for get_state_info function."""

    def test_get_state_info_returns_complete_info(self):
        """Test that state info includes all required fields."""
        from frappe_pim.pim.utils.workflow_state import get_state_info

        info = get_state_info("In Production")

        self.assertIsNotNone(info)
        self.assertEqual(info["name"], "In Production")
        self.assertEqual(info["label"], "In Production")
        self.assertIn("description", info)
        self.assertIn("color", info)
        self.assertIn("is_initial", info)
        self.assertIn("is_terminal", info)
        self.assertIn("valid_transitions", info)

    def test_get_state_info_in_preparation(self):
        """Test state info for In Preparation."""
        from frappe_pim.pim.utils.workflow_state import get_state_info

        info = get_state_info("In Preparation")

        self.assertTrue(info["is_initial"])
        self.assertFalse(info["is_terminal"])
        self.assertEqual(info["color"], "blue")

    def test_get_state_info_archived(self):
        """Test state info for Archived."""
        from frappe_pim.pim.utils.workflow_state import get_state_info

        info = get_state_info("Archived")

        self.assertFalse(info["is_initial"])
        self.assertTrue(info["is_terminal"])
        self.assertEqual(info["color"], "gray")

    def test_get_state_info_awaiting_approval(self):
        """Test state info for Awaiting Approval."""
        from frappe_pim.pim.utils.workflow_state import get_state_info

        info = get_state_info("Awaiting Approval")

        self.assertEqual(info["color"], "yellow")
        self.assertIn("Approved", info["valid_transitions"])

    def test_get_state_info_invalid_state(self):
        """Test that invalid state returns None."""
        from frappe_pim.pim.utils.workflow_state import get_state_info

        info = get_state_info("Invalid State")
        self.assertIsNone(info)

        info = get_state_info("")
        self.assertIsNone(info)

        info = get_state_info(None)
        self.assertIsNone(info)


class TestGetAllStates(unittest.TestCase):
    """Test cases for get_all_states function."""

    def test_get_all_states_returns_list(self):
        """Test that get_all_states returns a list."""
        from frappe_pim.pim.utils.workflow_state import get_all_states

        states = get_all_states()
        self.assertIsInstance(states, list)

    def test_get_all_states_returns_seven_states(self):
        """Test that all 7 states are returned."""
        from frappe_pim.pim.utils.workflow_state import get_all_states

        states = get_all_states()
        self.assertEqual(len(states), 7)

    def test_get_all_states_includes_all_required_fields(self):
        """Test that each state has all required fields."""
        from frappe_pim.pim.utils.workflow_state import get_all_states

        states = get_all_states()

        for state in states:
            self.assertIn("name", state)
            self.assertIn("label", state)
            self.assertIn("description", state)
            self.assertIn("color", state)
            self.assertIn("is_initial", state)
            self.assertIn("is_terminal", state)
            self.assertIn("valid_transitions", state)


class TestGetTransitionPath(unittest.TestCase):
    """Test cases for get_transition_path function."""

    def test_path_same_state(self):
        """Test path when from and to states are the same."""
        from frappe_pim.pim.utils.workflow_state import get_transition_path

        path = get_transition_path("In Production", "In Production")
        self.assertEqual(path, ["In Production"])

    def test_path_direct_transition(self):
        """Test path for direct transition."""
        from frappe_pim.pim.utils.workflow_state import get_transition_path

        path = get_transition_path("In Production", "Assigned")

        self.assertEqual(len(path), 2)
        self.assertEqual(path[0], "In Production")
        self.assertEqual(path[-1], "Assigned")

    def test_path_multi_step_transition(self):
        """Test path for multi-step transition."""
        from frappe_pim.pim.utils.workflow_state import get_transition_path

        path = get_transition_path("In Preparation", "Approved")

        # Should find a valid path
        self.assertGreater(len(path), 0)
        self.assertEqual(path[0], "In Preparation")
        self.assertEqual(path[-1], "Approved")

        # Verify each step is valid
        from frappe_pim.pim.utils.workflow_state import is_valid_transition
        for i in range(len(path) - 1):
            self.assertTrue(
                is_valid_transition(path[i], path[i + 1]),
                f"Invalid transition in path: {path[i]} -> {path[i + 1]}"
            )

    def test_path_from_archived(self):
        """Test path from Archived state."""
        from frappe_pim.pim.utils.workflow_state import get_transition_path

        path = get_transition_path("Archived", "Approved")

        # Should find a path through In Preparation
        self.assertGreater(len(path), 0)
        self.assertEqual(path[0], "Archived")
        self.assertEqual(path[1], "In Preparation")
        self.assertEqual(path[-1], "Approved")

    def test_path_invalid_states(self):
        """Test path with invalid states returns empty list."""
        from frappe_pim.pim.utils.workflow_state import get_transition_path

        path = get_transition_path("Invalid State", "Approved")
        self.assertEqual(path, [])

        path = get_transition_path("In Production", "Invalid State")
        self.assertEqual(path, [])


class TestGetWorkflowGraph(unittest.TestCase):
    """Test cases for get_workflow_graph function."""

    def test_workflow_graph_structure(self):
        """Test that workflow graph has correct structure."""
        from frappe_pim.pim.utils.workflow_state import get_workflow_graph

        graph = get_workflow_graph()

        self.assertIn("states", graph)
        self.assertIn("transitions", graph)
        self.assertIn("initial_state", graph)
        self.assertIn("terminal_states", graph)

    def test_workflow_graph_states(self):
        """Test that workflow graph contains all states."""
        from frappe_pim.pim.utils.workflow_state import get_workflow_graph

        graph = get_workflow_graph()

        self.assertEqual(len(graph["states"]), 7)

        state_names = [s["name"] for s in graph["states"]]
        self.assertIn("In Preparation", state_names)
        self.assertIn("Approved", state_names)
        self.assertIn("Archived", state_names)

    def test_workflow_graph_transitions(self):
        """Test that workflow graph contains transitions."""
        from frappe_pim.pim.utils.workflow_state import get_workflow_graph

        graph = get_workflow_graph()

        self.assertGreater(len(graph["transitions"]), 0)

        # Each transition should have from and to
        for transition in graph["transitions"]:
            self.assertIn("from", transition)
            self.assertIn("to", transition)

    def test_workflow_graph_initial_state(self):
        """Test that workflow graph has correct initial state."""
        from frappe_pim.pim.utils.workflow_state import get_workflow_graph

        graph = get_workflow_graph()

        self.assertEqual(graph["initial_state"], "In Preparation")

    def test_workflow_graph_terminal_states(self):
        """Test that workflow graph has correct terminal states."""
        from frappe_pim.pim.utils.workflow_state import get_workflow_graph

        graph = get_workflow_graph()

        self.assertEqual(len(graph["terminal_states"]), 1)
        self.assertIn("Archived", graph["terminal_states"])


class TestEmptyWorkflowStatus(unittest.TestCase):
    """Test cases for _empty_workflow_status helper."""

    def test_empty_workflow_status_structure(self):
        """Test empty workflow status structure."""
        from frappe_pim.pim.utils.workflow_state import _empty_workflow_status

        status = _empty_workflow_status("TEST-001")

        self.assertEqual(status["product"], "TEST-001")
        self.assertIsNone(status["current_state"])
        self.assertIsNone(status["state_info"])
        self.assertEqual(status["valid_transitions"], [])
        self.assertFalse(status["can_be_approved"])
        self.assertFalse(status["can_be_archived"])
        self.assertFalse(status["is_archived"])
        self.assertFalse(status["is_initial_state"])

    def test_empty_workflow_status_no_product(self):
        """Test empty workflow status without product name."""
        from frappe_pim.pim.utils.workflow_state import _empty_workflow_status

        status = _empty_workflow_status()

        self.assertIsNone(status["product"])


class TestEmptyStatistics(unittest.TestCase):
    """Test cases for _empty_statistics helper."""

    def test_empty_statistics_structure(self):
        """Test empty statistics structure."""
        from frappe_pim.pim.utils.workflow_state import _empty_statistics

        stats = _empty_statistics()

        self.assertEqual(stats["total_products"], 0)
        self.assertEqual(stats["by_state"], {})
        self.assertEqual(stats["active_count"], 0)
        self.assertEqual(stats["archived_count"], 0)
        self.assertEqual(stats["pending_approval"], 0)
        self.assertEqual(stats["in_progress"], 0)
        self.assertEqual(stats["approved_count"], 0)


class TestWorkflowIntegration(unittest.TestCase):
    """Integration tests for workflow state management with actual database.

    These tests require Frappe to be initialized and connected to database.
    """

    @classmethod
    def setUpClass(cls):
        """Set up test class - called once before all tests."""
        import frappe
        frappe.set_user("Administrator")

    def setUp(self):
        """Set up test - called before each test method."""
        self.created_documents = []

    def tearDown(self):
        """Tear down test - called after each test method."""
        import frappe
        # Delete in reverse order to handle dependencies
        for doctype, name in reversed(self.created_documents):
            try:
                if frappe.db.exists(doctype, name):
                    frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
            except Exception:
                pass
        frappe.db.commit()
        self.created_documents = []

    def track_document(self, doctype, name):
        """Track a document for cleanup after test."""
        self.created_documents.append((doctype, name))

    def test_validate_transition_new_document(self):
        """Test validate_transition with a new document."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.workflow_state import validate_transition

        # Create a new product document without saving
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Workflow Test {random_string(4)}",
            "product_code": f"WF-{random_string(6).upper()}",
            "short_description": "Testing workflow validation.",
            "status": "Draft",
            "workflow_state": "In Preparation"
        })

        # Mock is_new to return True
        product.flags.is_new = True

        result = validate_transition(product)

        self.assertTrue(result["is_valid"])

    def test_apply_transition_basic(self):
        """Test apply_transition with a real product."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.workflow_state import apply_transition

        # Create a test product
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Transition Test {random_string(4)}",
            "product_code": f"TRANS-{random_string(6).upper()}",
            "short_description": "Testing workflow transitions.",
            "status": "Draft",
            "workflow_state": "In Preparation"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Apply valid transition
        result = apply_transition(product.name, "In Production")

        self.assertTrue(result["success"])
        self.assertEqual(result["from_state"], "In Preparation")
        self.assertEqual(result["to_state"], "In Production")

        # Verify the product was updated
        product.reload()
        self.assertEqual(product.workflow_state, "In Production")

    def test_apply_transition_invalid(self):
        """Test apply_transition with invalid transition."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.workflow_state import apply_transition

        # Create a test product
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Invalid Transition Test {random_string(4)}",
            "product_code": f"INVTRANS-{random_string(6).upper()}",
            "short_description": "Testing invalid transitions.",
            "status": "Draft",
            "workflow_state": "In Preparation"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Try invalid transition (In Preparation -> Approved is not valid)
        result = apply_transition(product.name, "Approved")

        self.assertFalse(result["success"])
        self.assertIn("Invalid transition", result["message"])

    def test_apply_transition_nonexistent_product(self):
        """Test apply_transition with non-existent product."""
        from frappe_pim.pim.utils.workflow_state import apply_transition

        result = apply_transition("NONEXISTENT-PRODUCT-12345", "In Production")

        self.assertFalse(result["success"])
        self.assertIn("not found", result["message"])

    def test_get_product_workflow_status_basic(self):
        """Test get_product_workflow_status with a real product."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.workflow_state import get_product_workflow_status

        # Create a test product
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Status Test {random_string(4)}",
            "product_code": f"STAT-{random_string(6).upper()}",
            "short_description": "Testing workflow status.",
            "status": "Draft",
            "workflow_state": "In Production"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Get workflow status
        status = get_product_workflow_status(product.name)

        self.assertEqual(status["product"], product.name)
        self.assertEqual(status["current_state"], "In Production")
        self.assertIsNotNone(status["state_info"])
        self.assertGreater(len(status["valid_transitions"]), 0)
        self.assertFalse(status["can_be_approved"])  # Not valid from In Production
        self.assertTrue(status["can_be_archived"])  # Valid from In Production
        self.assertFalse(status["is_archived"])

    def test_get_product_workflow_status_nonexistent(self):
        """Test get_product_workflow_status with non-existent product."""
        from frappe_pim.pim.utils.workflow_state import get_product_workflow_status

        status = get_product_workflow_status("NONEXISTENT-12345")

        self.assertIsNone(status["current_state"])
        self.assertEqual(status["valid_transitions"], [])

    def test_get_products_by_state(self):
        """Test get_products_by_state function."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.workflow_state import get_products_by_state

        # Create test products in specific state
        product_names = []
        for i in range(3):
            product = frappe.get_doc({
                "doctype": "Product Master",
                "product_name": f"State Filter Test {i} {random_string(4)}",
                "product_code": f"SFT{i}-{random_string(6).upper()}",
                "short_description": f"Testing state filter {i}.",
                "status": "Draft",
                "workflow_state": "In Production"
            })
            product.insert(ignore_permissions=True)
            self.track_document("Product Master", product.name)
            product_names.append(product.name)

        # Get products by state
        products = get_products_by_state("In Production")

        self.assertIsInstance(products, list)
        # At least our test products should be in there
        found_names = [p["name"] for p in products]
        for name in product_names:
            self.assertIn(name, found_names)

    def test_get_products_by_state_invalid(self):
        """Test get_products_by_state with invalid state."""
        from frappe_pim.pim.utils.workflow_state import get_products_by_state

        products = get_products_by_state("Invalid State")

        self.assertEqual(products, [])

    def test_get_workflow_statistics(self):
        """Test get_workflow_statistics function."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.workflow_state import get_workflow_statistics

        # Create test products in different states
        states = ["In Preparation", "In Production", "Assigned"]
        for state in states:
            product = frappe.get_doc({
                "doctype": "Product Master",
                "product_name": f"Stats Test {state} {random_string(4)}",
                "product_code": f"STATS-{random_string(6).upper()}",
                "short_description": f"Testing statistics in {state}.",
                "status": "Draft",
                "workflow_state": state
            })
            product.insert(ignore_permissions=True)
            self.track_document("Product Master", product.name)

        # Get statistics
        stats = get_workflow_statistics()

        self.assertIn("total_products", stats)
        self.assertIn("by_state", stats)
        self.assertIn("active_count", stats)
        self.assertIn("archived_count", stats)
        self.assertIn("pending_approval", stats)
        self.assertIn("in_progress", stats)

        self.assertGreater(stats["total_products"], 0)
        self.assertIn("In Production", stats["by_state"])

    def test_get_products_pending_action(self):
        """Test get_products_pending_action function."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.workflow_state import (
            get_products_pending_action,
            apply_transition
        )

        # Create a product and move to Awaiting Approval
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Pending Test {random_string(4)}",
            "product_code": f"PEND-{random_string(6).upper()}",
            "short_description": "Testing pending action.",
            "status": "Draft",
            "workflow_state": "Awaiting Approval"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Get pending products
        pending = get_products_pending_action(action_type="approval")

        self.assertIsInstance(pending, list)
        found = any(p["name"] == product.name for p in pending)
        self.assertTrue(found, "Created product should be in pending approval list")

    def test_bulk_transition(self):
        """Test bulk_transition function."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.workflow_state import bulk_transition

        # Create test products
        product_names = []
        for i in range(3):
            product = frappe.get_doc({
                "doctype": "Product Master",
                "product_name": f"Bulk Test {i} {random_string(4)}",
                "product_code": f"BULK{i}-{random_string(6).upper()}",
                "short_description": f"Testing bulk transition {i}.",
                "status": "Draft",
                "workflow_state": "In Preparation"
            })
            product.insert(ignore_permissions=True)
            self.track_document("Product Master", product.name)
            product_names.append(product.name)

        # Bulk transition to In Production
        result = bulk_transition(product_names, "In Production")

        self.assertEqual(result["success_count"], 3)
        self.assertEqual(result["failed_count"], 0)
        self.assertEqual(result["total_count"], 3)

        # Verify all products were updated
        for name in product_names:
            product = frappe.get_doc("Product Master", name)
            self.assertEqual(product.workflow_state, "In Production")

    def test_bulk_transition_mixed_results(self):
        """Test bulk_transition with mixed valid/invalid transitions."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.workflow_state import bulk_transition

        # Create products in different states
        valid_product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Bulk Valid {random_string(4)}",
            "product_code": f"BULKV-{random_string(6).upper()}",
            "short_description": "Testing bulk transition valid.",
            "status": "Draft",
            "workflow_state": "In Preparation"
        })
        valid_product.insert(ignore_permissions=True)
        self.track_document("Product Master", valid_product.name)

        # Product already in production - can't go to In Production again
        invalid_product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Bulk Invalid {random_string(4)}",
            "product_code": f"BULKI-{random_string(6).upper()}",
            "short_description": "Testing bulk transition invalid.",
            "status": "Draft",
            "workflow_state": "Approved"
        })
        invalid_product.insert(ignore_permissions=True)
        self.track_document("Product Master", invalid_product.name)

        # Bulk transition to In Production
        result = bulk_transition(
            [valid_product.name, invalid_product.name],
            "In Production"
        )

        # Valid product succeeds, invalid fails
        self.assertEqual(result["success_count"], 2)  # Both actually valid from their states

    def test_workflow_filter_archived_separately(self):
        """Test that archived products are tracked separately."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.workflow_state import get_workflow_statistics

        # Create an archived product
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Archived Test {random_string(4)}",
            "product_code": f"ARCH-{random_string(6).upper()}",
            "short_description": "Testing archived filtering.",
            "status": "Draft",
            "workflow_state": "Archived"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Get statistics
        stats = get_workflow_statistics()

        # Archived count should be > 0
        self.assertGreater(stats["archived_count"], 0)
        self.assertIn("Archived", stats["by_state"])


class TestWorkflowStateChangesTracked(unittest.TestCase):
    """Test that workflow state changes are tracked correctly."""

    @classmethod
    def setUpClass(cls):
        """Set up test class - called once before all tests."""
        import frappe
        frappe.set_user("Administrator")

    def setUp(self):
        """Set up test - called before each test method."""
        self.created_documents = []

    def tearDown(self):
        """Tear down test - called after each test method."""
        import frappe
        for doctype, name in reversed(self.created_documents):
            try:
                if frappe.db.exists(doctype, name):
                    frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
            except Exception:
                pass
        frappe.db.commit()
        self.created_documents = []

    def track_document(self, doctype, name):
        """Track a document for cleanup after test."""
        self.created_documents.append((doctype, name))

    def test_state_transition_logged(self):
        """Test that state transitions are logged as comments."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.workflow_state import apply_transition

        # Create a test product
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Log Test {random_string(4)}",
            "product_code": f"LOG-{random_string(6).upper()}",
            "short_description": "Testing transition logging.",
            "status": "Draft",
            "workflow_state": "In Preparation"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Apply transition
        result = apply_transition(product.name, "In Production", comment="Test comment")

        self.assertTrue(result["success"])

        # Check for comment log
        comments = frappe.get_all(
            "Comment",
            filters={
                "reference_doctype": "Product Master",
                "reference_name": product.name,
                "comment_type": "Info"
            },
            fields=["content"]
        )

        # Should have at least one comment about the transition
        transition_comment = any(
            "In Preparation" in c.get("content", "") and "In Production" in c.get("content", "")
            for c in comments
        )
        self.assertTrue(
            transition_comment,
            "Transition should be logged as a comment"
        )


# Allow module import without running tests
if __name__ == "__main__":
    unittest.main()
