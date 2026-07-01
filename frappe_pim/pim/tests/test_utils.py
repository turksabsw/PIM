# Copyright (c) 2024, Frappe PIM and contributors
# For license information, please see license.txt
"""PIM Test Utilities

This module provides utility functions and fixtures for testing the PIM application.
It includes helpers for creating test documents, setting up fixtures,
and cleaning up after tests.

Usage:
    from frappe_pim.pim.tests.test_utils import (
        create_test_attribute,
        create_test_family,
        create_test_product,
        cleanup_test_documents,
        PIMTestCase
    )

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for linting/static analysis).
"""

import unittest
from contextlib import contextmanager


class PIMTestCase(unittest.TestCase):
    """Base test case class for PIM tests.

    Provides common setup and teardown functionality for PIM tests.
    Automatically tracks created documents for cleanup.

    Example:
        class TestProductMaster(PIMTestCase):
            def test_create_product(self):
                product = create_test_product(self, "Test Product")
                self.assertEqual(product.product_name, "Test Product")
    """

    @classmethod
    def setUpClass(cls):
        """Set up test class - called once before all tests in the class."""
        import frappe
        frappe.set_user("Administrator")

    def setUp(self):
        """Set up test - called before each test method."""
        self.created_documents = []

    def tearDown(self):
        """Tear down test - called after each test method."""
        cleanup_test_documents(self.created_documents)
        self.created_documents = []

    def track_document(self, doctype, name):
        """Track a document for cleanup after test.

        Args:
            doctype: The DocType of the document
            name: The name of the document
        """
        self.created_documents.append((doctype, name))


def create_test_attribute(test_case=None, code=None, name=None, data_type="Data",
                          attribute_group=None, is_required=False, **kwargs):
    """Create a test PIM Attribute document.

    Args:
        test_case: PIMTestCase instance for tracking (optional)
        code: Unique attribute code (auto-generated if not provided)
        name: Display name for the attribute
        data_type: Type of attribute (Data, Int, Float, Select, etc.)
        attribute_group: Link to PIM Attribute Group
        is_required: Whether attribute is required
        **kwargs: Additional fields to set on the document

    Returns:
        frappe.Document: The created PIM Attribute document
    """
    import frappe
    from frappe.utils import random_string

    code = code or f"test_attr_{random_string(6).lower()}"
    name = name or f"Test Attribute {random_string(4)}"

    doc_data = {
        "doctype": "PIM Attribute",
        "attribute_code": code,
        "attribute_name": name,
        "data_type": data_type,
        "is_required_in_family": is_required,
    }

    if attribute_group:
        doc_data["attribute_group"] = attribute_group

    doc_data.update(kwargs)

    doc = frappe.get_doc(doc_data)
    doc.insert(ignore_permissions=True)

    if test_case:
        test_case.track_document("PIM Attribute", doc.name)

    return doc


def create_test_attribute_group(test_case=None, name=None, **kwargs):
    """Create a test PIM Attribute Group document.

    Args:
        test_case: PIMTestCase instance for tracking (optional)
        name: Group name (auto-generated if not provided)
        **kwargs: Additional fields to set on the document

    Returns:
        frappe.Document: The created PIM Attribute Group document
    """
    import frappe
    from frappe.utils import random_string

    name = name or f"Test Group {random_string(4)}"

    doc_data = {
        "doctype": "PIM Attribute Group",
        "group_name": name,
        "is_standard": 0,
    }
    doc_data.update(kwargs)

    doc = frappe.get_doc(doc_data)
    doc.insert(ignore_permissions=True)

    if test_case:
        test_case.track_document("PIM Attribute Group", doc.name)

    return doc


def create_test_family(test_case=None, name=None, parent_family=None,
                       attributes=None, **kwargs):
    """Create a test Product Family document.

    Args:
        test_case: PIMTestCase instance for tracking (optional)
        name: Family name (auto-generated if not provided)
        parent_family: Parent family for tree structure
        attributes: List of attribute codes to add as templates
        **kwargs: Additional fields to set on the document

    Returns:
        frappe.Document: The created Product Family document
    """
    import frappe
    from frappe.utils import random_string

    name = name or f"Test Family {random_string(4)}"

    doc_data = {
        "doctype": "Product Family",
        "family_name": name,
    }

    if parent_family:
        doc_data["parent_product_family"] = parent_family
        doc_data["is_group"] = 0
    else:
        doc_data["is_group"] = 1

    doc_data.update(kwargs)

    doc = frappe.get_doc(doc_data)

    # Add attribute templates if provided
    if attributes:
        for attr in attributes:
            if isinstance(attr, str):
                doc.append("attributes", {
                    "attribute": attr,
                    "is_required_in_family": 0
                })
            elif isinstance(attr, dict):
                doc.append("attributes", attr)

    doc.insert(ignore_permissions=True)

    if test_case:
        test_case.track_document("Product Family", doc.name)

    return doc


def create_test_product(test_case=None, name=None, product_code=None,
                        family=None, status="Draft", attributes=None, **kwargs):
    """Create a test Product Master document.

    Args:
        test_case: PIMTestCase instance for tracking (optional)
        name: Product name (auto-generated if not provided)
        product_code: Unique product code (auto-generated if not provided)
        family: Link to Product Family
        status: Product status (Draft, Active, Inactive)
        attributes: List of attribute values to set
        **kwargs: Additional fields to set on the document

    Returns:
        frappe.Document: The created Product Master document
    """
    import frappe
    from frappe.utils import random_string

    name = name or f"Test Product {random_string(4)}"
    product_code = product_code or f"TEST-{random_string(6).upper()}"

    doc_data = {
        "doctype": "Product Master",
        "product_name": name,
        "product_code": product_code,
        "status": status,
    }

    if family:
        doc_data["product_family"] = family

    doc_data.update(kwargs)

    doc = frappe.get_doc(doc_data)

    # Add attribute values if provided
    if attributes:
        for attr_value in attributes:
            if isinstance(attr_value, dict):
                doc.append("attribute_values", attr_value)

    doc.insert(ignore_permissions=True)

    if test_case:
        test_case.track_document("Product Master", doc.name)

    return doc


def create_test_variant(test_case=None, name=None, variant_code=None,
                        product_master=None, status="Draft", **kwargs):
    """Create a test Product Variant document.

    Args:
        test_case: PIMTestCase instance for tracking (optional)
        name: Variant name (auto-generated if not provided)
        variant_code: Unique variant/SKU code (auto-generated if not provided)
        product_master: Link to parent Product Master
        status: Variant status (Draft, Active, Inactive)
        **kwargs: Additional fields to set on the document

    Returns:
        frappe.Document: The created Product Variant document
    """
    import frappe
    from frappe.utils import random_string

    name = name or f"Test Variant {random_string(4)}"
    variant_code = variant_code or f"SKU-{random_string(6).upper()}"

    doc_data = {
        "doctype": "Product Variant",
        "variant_name": name,
        "variant_code": variant_code,
        "status": status,
    }

    if product_master:
        doc_data["product_master"] = product_master

    doc_data.update(kwargs)

    doc = frappe.get_doc(doc_data)
    doc.insert(ignore_permissions=True)

    if test_case:
        test_case.track_document("Product Variant", doc.name)

    return doc


def create_test_channel(test_case=None, name=None, **kwargs):
    """Create a test Channel document.

    Args:
        test_case: PIMTestCase instance for tracking (optional)
        name: Channel name (auto-generated if not provided)
        **kwargs: Additional fields to set on the document

    Returns:
        frappe.Document: The created Channel document
    """
    import frappe
    from frappe.utils import random_string

    name = name or f"Test Channel {random_string(4)}"

    doc_data = {
        "doctype": "Channel",
        "channel_name": name,
        "channel_code": f"test-channel-{random_string(6).lower()}",
        "enabled": 1,
    }
    doc_data.update(kwargs)

    doc = frappe.get_doc(doc_data)
    doc.insert(ignore_permissions=True)

    if test_case:
        test_case.track_document("Channel", doc.name)

    return doc


def create_test_export_profile(test_case=None, name=None, channel=None,
                               export_format="JSON", **kwargs):
    """Create a test Export Profile document.

    Args:
        test_case: PIMTestCase instance for tracking (optional)
        name: Profile name (auto-generated if not provided)
        channel: Link to Channel
        export_format: Export format (CSV, JSON, XML, BMEcat)
        **kwargs: Additional fields to set on the document

    Returns:
        frappe.Document: The created Export Profile document
    """
    import frappe
    from frappe.utils import random_string

    name = name or f"Test Export {random_string(4)}"

    doc_data = {
        "doctype": "Export Profile",
        "profile_name": name,
        "export_format": export_format,
        "enabled": 1,
    }

    if channel:
        doc_data["channel"] = channel

    doc_data.update(kwargs)

    doc = frappe.get_doc(doc_data)
    doc.insert(ignore_permissions=True)

    if test_case:
        test_case.track_document("Export Profile", doc.name)

    return doc


def cleanup_test_documents(documents):
    """Clean up test documents after tests.

    Args:
        documents: List of (doctype, name) tuples to delete
    """
    import frappe

    # Delete in reverse order to handle dependencies
    for doctype, name in reversed(documents):
        try:
            if frappe.db.exists(doctype, name):
                frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
        except Exception:
            # Log but don't fail test cleanup
            pass

    # Commit cleanup
    frappe.db.commit()


def get_test_fixtures():
    """Get a complete set of test fixtures for integration tests.

    Creates a full hierarchy of test documents:
    - Attribute Group
    - Attributes
    - Product Family with templates
    - Product Master with attribute values
    - Product Variants

    Returns:
        dict: Dictionary containing all created fixtures
    """
    import frappe
    from frappe.utils import random_string

    fixtures = {}
    suffix = random_string(4)

    # Create attribute group
    fixtures["attribute_group"] = frappe.get_doc({
        "doctype": "PIM Attribute Group",
        "group_name": f"Test Group {suffix}",
        "is_standard": 0
    }).insert(ignore_permissions=True)

    # Create attributes
    fixtures["attributes"] = []
    attr_configs = [
        ("text_attr", "Text Attribute", "Data"),
        ("int_attr", "Integer Attribute", "Int"),
        ("float_attr", "Float Attribute", "Float"),
        ("select_attr", "Select Attribute", "Select"),
    ]
    for code, name, dtype in attr_configs:
        attr = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_code": f"{code}_{suffix}",
            "attribute_name": f"{name} {suffix}",
            "data_type": dtype,
            "attribute_group": fixtures["attribute_group"].name
        }).insert(ignore_permissions=True)
        fixtures["attributes"].append(attr)

    # Create family with templates
    fixtures["family"] = frappe.get_doc({
        "doctype": "Product Family",
        "family_name": f"Test Family {suffix}",
        "is_group": 0,
        "attributes": [
            {
                "attribute": fixtures["attributes"][0].name,
                "is_required_in_family": 1
            },
            {
                "attribute": fixtures["attributes"][1].name,
                "is_required_in_family": 0
            }
        ]
    }).insert(ignore_permissions=True)

    # Create product with attribute values
    fixtures["product"] = frappe.get_doc({
        "doctype": "Product Master",
        "product_name": f"Test Product {suffix}",
        "product_code": f"TEST-{suffix.upper()}",
        "product_family": fixtures["family"].name,
        "status": "Draft",
        "attribute_values": [
            {
                "attribute": fixtures["attributes"][0].name,
                "value_text": "Sample text value"
            }
        ]
    }).insert(ignore_permissions=True)

    # Create variant
    fixtures["variant"] = frappe.get_doc({
        "doctype": "Product Variant",
        "variant_name": f"Test Variant {suffix}",
        "variant_code": f"SKU-{suffix.upper()}",
        "product_master": fixtures["product"].name,
        "status": "Draft"
    }).insert(ignore_permissions=True)

    return fixtures


def cleanup_fixtures(fixtures):
    """Clean up fixtures created by get_test_fixtures.

    Args:
        fixtures: Dictionary returned by get_test_fixtures
    """
    import frappe

    # Delete in dependency order
    deletion_order = ["variant", "product", "family", "attributes", "attribute_group"]

    for key in deletion_order:
        if key not in fixtures:
            continue

        docs = fixtures[key]
        if not isinstance(docs, list):
            docs = [docs]

        for doc in docs:
            try:
                if frappe.db.exists(doc.doctype, doc.name):
                    frappe.delete_doc(doc.doctype, doc.name, force=True, ignore_permissions=True)
            except Exception:
                pass

    frappe.db.commit()


@contextmanager
def test_fixtures_context():
    """Context manager for test fixtures.

    Automatically creates fixtures on entry and cleans up on exit.

    Usage:
        with test_fixtures_context() as fixtures:
            product = fixtures["product"]
            # Run tests with product
        # Fixtures automatically cleaned up
    """
    fixtures = get_test_fixtures()
    try:
        yield fixtures
    finally:
        cleanup_fixtures(fixtures)


def mock_frappe_cache():
    """Create a mock cache for testing cache-related functions.

    Returns:
        dict: A dictionary-based mock cache object
    """
    class MockCache:
        def __init__(self):
            self._store = {}

        def get(self, key):
            return self._store.get(key)

        def set(self, key, value, expires_in_sec=None):
            self._store[key] = value

        def delete(self, key):
            self._store.pop(key, None)

        def delete_key(self, key):
            self._store.pop(key, None)

        def clear(self):
            self._store.clear()

    return MockCache()


def assert_completeness_score(test_case, product_name, expected_score, tolerance=0.01):
    """Assert that a product's completeness score matches expected value.

    Args:
        test_case: Test case instance for assertion
        product_name: Name of the product to check
        expected_score: Expected completeness score (0-100)
        tolerance: Acceptable difference from expected (default 0.01)
    """
    import frappe

    doc = frappe.get_doc("Product Master", product_name)
    actual_score = doc.completeness_score or 0

    test_case.assertAlmostEqual(
        actual_score,
        expected_score,
        delta=tolerance,
        msg=f"Completeness score {actual_score} does not match expected {expected_score}"
    )


def set_pim_settings(**settings):
    """Set PIM configuration settings for testing.

    Args:
        **settings: Key-value pairs of settings to configure

    Returns:
        dict: Original settings (for restoration in teardown)
    """
    import frappe

    original = {}

    # Get or create PIM Settings singleton if it exists
    try:
        if frappe.db.exists("DocType", "PIM Settings"):
            doc = frappe.get_single("PIM Settings")
            for key, value in settings.items():
                if hasattr(doc, key):
                    original[key] = getattr(doc, key)
                    setattr(doc, key, value)
            doc.save(ignore_permissions=True)
    except Exception:
        pass

    return original


def restore_pim_settings(original_settings):
    """Restore PIM settings to original values.

    Args:
        original_settings: Dictionary of settings to restore
    """
    set_pim_settings(**original_settings)
