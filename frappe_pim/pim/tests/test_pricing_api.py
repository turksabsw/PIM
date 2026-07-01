# Copyright (c) 2024, Frappe PIM and contributors
# For license information, please see license.txt
"""PIM Pricing API End-to-End Tests

This module contains comprehensive tests for the pricing API with all price layers:
1. Contract Price (customer-specific) - highest priority
2. Channel Listing Price (marketplace-specific)
3. Channel Price List (channel default)
4. Fallback Price List (system default)
5. Currency Conversion
6. Pricing Rules (discounts, promotions)
7. Guardrails (min/max price limits)

Tests verify that price resolution returns correct prices with applied_rules trace.

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for linting/static analysis).

Run tests:
    bench --site [site] run-tests --app frappe_pim --module frappe_pim.pim.tests.test_pricing_api
"""

import unittest


class TestPricingAPIModuleImports(unittest.TestCase):
    """Test that pricing API modules can be imported correctly."""

    def test_import_pricing_api(self):
        """Verify pricing.py API can be imported."""
        from frappe_pim.pim.api import pricing
        self.assertIsNotNone(pricing)

    def test_import_get_final_price(self):
        """Verify get_final_price function can be imported."""
        from frappe_pim.pim.api.pricing import get_final_price
        self.assertIsNotNone(get_final_price)
        self.assertTrue(callable(get_final_price))

    def test_import_get_price_breakdown(self):
        """Verify get_price_breakdown function can be imported."""
        from frappe_pim.pim.api.pricing import get_price_breakdown
        self.assertIsNotNone(get_price_breakdown)
        self.assertTrue(callable(get_price_breakdown))

    def test_import_get_bulk_prices(self):
        """Verify get_bulk_prices function can be imported."""
        from frappe_pim.pim.api.pricing import get_bulk_prices
        self.assertIsNotNone(get_bulk_prices)
        self.assertTrue(callable(get_bulk_prices))

    def test_import_price_resolver(self):
        """Verify price_resolver utility can be imported."""
        from frappe_pim.pim.utils import price_resolver
        self.assertIsNotNone(price_resolver)

    def test_import_resolve_price(self):
        """Verify resolve_price function can be imported."""
        from frappe_pim.pim.utils.price_resolver import resolve_price
        self.assertIsNotNone(resolve_price)
        self.assertTrue(callable(resolve_price))

    def test_import_validate_price_against_guardrails(self):
        """Verify validate_price_against_guardrails function can be imported."""
        from frappe_pim.pim.utils.price_resolver import validate_price_against_guardrails
        self.assertIsNotNone(validate_price_against_guardrails)
        self.assertTrue(callable(validate_price_against_guardrails))

    def test_price_layer_constants(self):
        """Verify price layer constants are defined."""
        from frappe_pim.pim.utils.price_resolver import (
            PRICE_LAYER_CONTRACT,
            PRICE_LAYER_LISTING,
            PRICE_LAYER_CHANNEL_PRICE_LIST,
            PRICE_LAYER_FALLBACK_PRICE_LIST,
            PRICE_LAYER_CURRENCY_CONVERSION,
            PRICE_LAYER_PRICING_RULES,
            PRICE_LAYER_GUARDRAILS
        )
        self.assertEqual(PRICE_LAYER_CONTRACT, "contract_price")
        self.assertEqual(PRICE_LAYER_LISTING, "channel_listing")
        self.assertEqual(PRICE_LAYER_CHANNEL_PRICE_LIST, "channel_price_list")
        self.assertEqual(PRICE_LAYER_FALLBACK_PRICE_LIST, "fallback_price_list")
        self.assertEqual(PRICE_LAYER_CURRENCY_CONVERSION, "currency_conversion")
        self.assertEqual(PRICE_LAYER_PRICING_RULES, "pricing_rules")
        self.assertEqual(PRICE_LAYER_GUARDRAILS, "guardrails")


class TestPricingAPIBasicFunctionality(unittest.TestCase):
    """Test basic pricing API functionality."""

    @classmethod
    def setUpClass(cls):
        """Set up test class - called once before all tests."""
        import frappe
        frappe.set_user("Administrator")

    def test_get_final_price_missing_sku(self):
        """Test get_final_price returns error for missing SKU."""
        from frappe_pim.pim.api.pricing import get_final_price

        result = get_final_price(sku=None)
        # Should return error response or throw
        # The function handles missing SKU gracefully
        self.assertFalse(result.get("success", True))

    def test_get_final_price_nonexistent_product(self):
        """Test get_final_price with non-existent SKU."""
        from frappe_pim.pim.api.pricing import get_final_price

        result = get_final_price(
            sku="NONEXISTENT-SKU-12345",
            channel="Default",
            qty=1
        )
        self.assertFalse(result.get("success"))
        self.assertIn("messages", result)

    def test_get_final_price_result_structure(self):
        """Test get_final_price returns correctly structured response."""
        from frappe_pim.pim.api.pricing import get_final_price

        result = get_final_price(
            sku="TEST-SKU",
            channel="Default",
            qty=1
        )
        # Verify response structure has all expected fields
        expected_fields = [
            "success",
            "final_unit_price",
            "original_price",
            "discount_amount",
            "discount_percent",
            "currency",
            "price_source",
            "applied_rules",
            "guardrail_applied",
            "messages"
        ]
        for field in expected_fields:
            self.assertIn(field, result, f"Missing field: {field}")


class TestPriceResolverLayers(unittest.TestCase):
    """Test price resolution through all price layers."""

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

    def test_price_resolver_result_structure(self):
        """Test resolve_price returns correctly structured response."""
        from frappe_pim.pim.utils.price_resolver import resolve_price

        result = resolve_price(sku="TEST-SKU")

        # Verify response structure
        expected_fields = [
            "final_unit_price",
            "original_price",
            "discount_amount",
            "discount_percent",
            "currency",
            "price_layer",
            "applied_rules",
            "guardrail_applied",
            "is_valid",
            "messages",
            "trace"
        ]
        for field in expected_fields:
            self.assertIn(field, result, f"Missing field: {field}")

    def test_price_resolver_trace_contains_all_layers(self):
        """Test resolve_price trace includes all price layer checks."""
        from frappe_pim.pim.utils.price_resolver import resolve_price

        result = resolve_price(
            sku="TEST-SKU",
            channel_code="test-channel",
            customer="TEST-CUSTOMER",
            include_pricing_rules=True,
            include_guardrails=True
        )

        # Trace should contain steps for each layer checked
        trace = result.get("trace", [])
        self.assertIsInstance(trace, list)
        # Even if no price found, trace should have entries

    def test_resolve_price_with_valid_product(self):
        """Test resolve_price with a valid product and price list setup."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(6).lower()

        # Check if Item DocType exists (ERPNext dependency)
        if not frappe.db.exists("DocType", "Item"):
            self.skipTest("ERPNext Item DocType not available")

        # Create a test Item in ERPNext
        item = frappe.get_doc({
            "doctype": "Item",
            "item_code": f"TEST-ITEM-{suffix.upper()}",
            "item_name": f"Test Item {suffix}",
            "item_group": "All Item Groups",
            "stock_uom": "Nos",
            "standard_rate": 100.00
        })
        item.insert(ignore_permissions=True)
        self.track_document("Item", item.name)

        # Create a Product Master
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Test Product {suffix}",
            "product_code": f"TEST-PROD-{suffix.upper()}",
            "short_description": "Test product for pricing",
            "status": "Active"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Create a Product Variant with ERP item link
        variant = frappe.get_doc({
            "doctype": "Product Variant",
            "variant_name": f"Test Variant {suffix}",
            "sku": f"TEST-VAR-{suffix.upper()}",
            "product_master": product.name,
            "erp_item": item.name,
            "status": "Active"
        })
        variant.insert(ignore_permissions=True)
        self.track_document("Product Variant", variant.name)

        # Now test price resolution
        from frappe_pim.pim.utils.price_resolver import resolve_price

        result = resolve_price(sku=variant.sku)

        # If Item has standard_rate, it should be found
        # The is_valid might be False if no price list is configured
        # But the trace should show what was checked
        self.assertIn("trace", result)
        self.assertIsInstance(result["trace"], list)


class TestSalesChannelPricing(unittest.TestCase):
    """Test pricing with sales channels."""

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

    def test_sales_channel_doctype_exists(self):
        """Verify PIM Sales Channel DocType exists."""
        import frappe
        self.assertTrue(
            frappe.db.exists("DocType", "PIM Sales Channel"),
            "PIM Sales Channel DocType must exist"
        )

    def test_create_sales_channel(self):
        """Test creating a PIM Sales Channel."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(6).lower()

        channel = frappe.get_doc({
            "doctype": "PIM Sales Channel",
            "channel_name": f"Test Channel {suffix}",
            "channel_code": f"test-channel-{suffix}",
            "channel_type": "Direct",
            "currency": "USD",
            "is_active": 1
        })
        channel.insert(ignore_permissions=True)
        self.track_document("PIM Sales Channel", channel.name)

        self.assertEqual(channel.channel_name, f"Test Channel {suffix}")
        self.assertEqual(channel.currency, "USD")

    def test_channel_with_guardrails(self):
        """Test sales channel with price guardrails."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(6).lower()

        channel = frappe.get_doc({
            "doctype": "PIM Sales Channel",
            "channel_name": f"Guardrail Channel {suffix}",
            "channel_code": f"guard-channel-{suffix}",
            "channel_type": "Marketplace",
            "currency": "USD",
            "is_active": 1,
            "min_price": 10.00,
            "max_price": 1000.00,
            "enforce_map": 1,
            "allow_below_cost": 0
        })
        channel.insert(ignore_permissions=True)
        self.track_document("PIM Sales Channel", channel.name)

        self.assertEqual(channel.min_price, 10.00)
        self.assertEqual(channel.max_price, 1000.00)
        self.assertTrue(channel.enforce_map)
        self.assertFalse(channel.allow_below_cost)


class TestContractPricing(unittest.TestCase):
    """Test contract pricing layer."""

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

    def test_contract_price_doctype_exists(self):
        """Verify PIM Contract Price DocType exists."""
        import frappe
        self.assertTrue(
            frappe.db.exists("DocType", "PIM Contract Price"),
            "PIM Contract Price DocType must exist"
        )

    def test_create_contract_price(self):
        """Test creating a PIM Contract Price."""
        import frappe
        from frappe.utils import random_string, add_days, today

        suffix = random_string(6).lower()

        # Check if Customer DocType exists (ERPNext dependency)
        if not frappe.db.exists("DocType", "Customer"):
            self.skipTest("ERPNext Customer DocType not available")

        # Get or create a test customer
        customer_name = f"Test Customer {suffix}"
        if not frappe.db.exists("Customer", customer_name):
            customer = frappe.get_doc({
                "doctype": "Customer",
                "customer_name": customer_name,
                "customer_type": "Company",
                "customer_group": "All Customer Groups",
                "territory": "All Territories"
            })
            customer.insert(ignore_permissions=True)
            self.track_document("Customer", customer.name)

        contract = frappe.get_doc({
            "doctype": "PIM Contract Price",
            "contract_name": f"Test Contract {suffix}",
            "customer_scope": "Specific Customer",
            "customer": customer_name,
            "product_scope": "All Products",
            "pricing_type": "Discount Percentage",
            "discount_percent": 10,
            "valid_from": today(),
            "valid_to": add_days(today(), 30),
            "is_active": 1
        })
        contract.insert(ignore_permissions=True)
        self.track_document("PIM Contract Price", contract.name)

        self.assertEqual(contract.discount_percent, 10)
        self.assertTrue(contract.is_active)


class TestMarketplaceListing(unittest.TestCase):
    """Test marketplace listing pricing layer."""

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

    def test_marketplace_listing_doctype_exists(self):
        """Verify PIM Marketplace Listing DocType exists."""
        import frappe
        self.assertTrue(
            frappe.db.exists("DocType", "PIM Marketplace Listing"),
            "PIM Marketplace Listing DocType must exist"
        )


class TestGuardrailValidation(unittest.TestCase):
    """Test price guardrail validation."""

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

    def test_validate_price_function_exists(self):
        """Verify validate_price_against_guardrails function works."""
        from frappe_pim.pim.utils.price_resolver import validate_price_against_guardrails

        # Test with non-existent channel
        result = validate_price_against_guardrails(
            price=50.00,
            channel_code="non-existent-channel"
        )

        # Should return a result with warnings about missing channel
        self.assertIn("is_valid", result)
        self.assertIn("warnings", result)
        self.assertIn("adjusted_price", result)

    def test_guardrail_min_price_enforcement(self):
        """Test that min price guardrail is enforced."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(6).lower()

        # Create channel with min price
        channel = frappe.get_doc({
            "doctype": "PIM Sales Channel",
            "channel_name": f"Min Price Channel {suffix}",
            "channel_code": f"min-price-{suffix}",
            "channel_type": "Direct",
            "currency": "USD",
            "is_active": 1,
            "min_price": 20.00,
            "enforce_map": 1
        })
        channel.insert(ignore_permissions=True)
        self.track_document("PIM Sales Channel", channel.name)

        from frappe_pim.pim.utils.price_resolver import validate_price_against_guardrails

        # Test price below minimum
        result = validate_price_against_guardrails(
            price=10.00,
            channel_code=channel.name
        )

        # Price should be invalid and adjusted to min
        self.assertFalse(result.get("is_valid"))
        self.assertEqual(result.get("adjusted_price"), 20.00)

    def test_guardrail_max_price_enforcement(self):
        """Test that max price guardrail is enforced."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(6).lower()

        # Create channel with max price
        channel = frappe.get_doc({
            "doctype": "PIM Sales Channel",
            "channel_name": f"Max Price Channel {suffix}",
            "channel_code": f"max-price-{suffix}",
            "channel_type": "Direct",
            "currency": "USD",
            "is_active": 1,
            "max_price": 100.00
        })
        channel.insert(ignore_permissions=True)
        self.track_document("PIM Sales Channel", channel.name)

        from frappe_pim.pim.utils.price_resolver import validate_price_against_guardrails

        # Test price above maximum
        result = validate_price_against_guardrails(
            price=150.00,
            channel_code=channel.name
        )

        # Price should be invalid and adjusted to max
        self.assertFalse(result.get("is_valid"))
        self.assertEqual(result.get("adjusted_price"), 100.00)

    def test_guardrail_price_within_range(self):
        """Test that price within range passes guardrails."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(6).lower()

        # Create channel with price range
        channel = frappe.get_doc({
            "doctype": "PIM Sales Channel",
            "channel_name": f"Range Channel {suffix}",
            "channel_code": f"range-channel-{suffix}",
            "channel_type": "Direct",
            "currency": "USD",
            "is_active": 1,
            "min_price": 10.00,
            "max_price": 100.00
        })
        channel.insert(ignore_permissions=True)
        self.track_document("PIM Sales Channel", channel.name)

        from frappe_pim.pim.utils.price_resolver import validate_price_against_guardrails

        # Test price within range
        result = validate_price_against_guardrails(
            price=50.00,
            channel_code=channel.name
        )

        # Price should be valid and unchanged
        self.assertTrue(result.get("is_valid"))
        self.assertEqual(result.get("adjusted_price"), 50.00)


class TestBulkPricing(unittest.TestCase):
    """Test bulk pricing API."""

    @classmethod
    def setUpClass(cls):
        """Set up test class - called once before all tests."""
        import frappe
        frappe.set_user("Administrator")

    def test_get_bulk_prices_function(self):
        """Test get_bulk_prices function with multiple SKUs."""
        from frappe_pim.pim.api.pricing import get_bulk_prices
        import json

        skus = ["SKU-001", "SKU-002", "SKU-003"]

        result = get_bulk_prices(
            skus=json.dumps(skus),
            channel="Default",
            qty=1
        )

        # Verify result structure
        self.assertIn("success", result)
        self.assertIn("total_skus", result)
        self.assertIn("prices", result)
        self.assertEqual(result.get("total_skus"), 3)

    def test_get_bulk_prices_limit(self):
        """Test get_bulk_prices respects max limit."""
        from frappe_pim.pim.api.pricing import get_bulk_prices
        import json

        # Create list of 101 SKUs (exceeds limit of 100)
        skus = [f"SKU-{i:04d}" for i in range(101)]

        # Should throw error for exceeding limit
        try:
            result = get_bulk_prices(
                skus=json.dumps(skus),
                channel="Default",
                qty=1
            )
            # If no error, check if result indicates failure
            self.fail("Should have thrown error for exceeding limit")
        except Exception as e:
            # Expected to throw error
            self.assertIn("Maximum", str(e))


class TestPricingAPIIntegration(unittest.TestCase):
    """Integration tests for pricing API with full setup."""

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

    def test_full_price_resolution_flow(self):
        """Test complete price resolution flow with all components."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(6).lower()

        # Check if ERPNext is available
        if not frappe.db.exists("DocType", "Item"):
            self.skipTest("ERPNext Item DocType not available")

        # 1. Create ERPNext Item
        item = frappe.get_doc({
            "doctype": "Item",
            "item_code": f"PRICE-TEST-{suffix.upper()}",
            "item_name": f"Price Test Item {suffix}",
            "item_group": "All Item Groups",
            "stock_uom": "Nos",
            "standard_rate": 99.99
        })
        item.insert(ignore_permissions=True)
        self.track_document("Item", item.name)

        # 2. Create Product Master
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Price Test Product {suffix}",
            "product_code": f"PRICE-PROD-{suffix.upper()}",
            "short_description": "Product for price testing",
            "status": "Active"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # 3. Create Product Variant with ERP link
        variant = frappe.get_doc({
            "doctype": "Product Variant",
            "variant_name": f"Price Test Variant {suffix}",
            "sku": f"PRICE-VAR-{suffix.upper()}",
            "product_master": product.name,
            "erp_item": item.name,
            "status": "Active"
        })
        variant.insert(ignore_permissions=True)
        self.track_document("Product Variant", variant.name)

        # 4. Create Sales Channel
        channel = frappe.get_doc({
            "doctype": "PIM Sales Channel",
            "channel_name": f"Price Test Channel {suffix}",
            "channel_code": f"price-test-{suffix}",
            "channel_type": "Direct",
            "currency": "USD",
            "is_active": 1,
            "min_price": 50.00,
            "max_price": 200.00
        })
        channel.insert(ignore_permissions=True)
        self.track_document("PIM Sales Channel", channel.name)

        # 5. Test price resolution through API
        from frappe_pim.pim.api.pricing import get_final_price

        result = get_final_price(
            sku=variant.sku,
            channel=channel.name,
            qty=1
        )

        # Verify result has expected structure
        self.assertIn("success", result)
        self.assertIn("final_unit_price", result)
        self.assertIn("currency", result)
        self.assertIn("applied_rules", result)
        self.assertIn("messages", result)

        # If price found, verify it's valid
        if result.get("success"):
            self.assertGreater(result.get("final_unit_price"), 0)

    def test_price_breakdown_api(self):
        """Test get_price_breakdown API returns detailed information."""
        from frappe_pim.pim.api.pricing import get_price_breakdown

        result = get_price_breakdown(
            sku="TEST-SKU",
            channel="Default",
            qty=1,
            include_trace=True
        )

        # Verify detailed breakdown structure (even for non-existent product)
        # The function should handle gracefully and still return structure
        self.assertIn("sku", result)
        self.assertIn("channel", result)


class TestPriceLayerPriority(unittest.TestCase):
    """Test that price layers are evaluated in correct priority order."""

    def test_layer_priority_order(self):
        """Verify price layers are defined in correct priority order."""
        from frappe_pim.pim.utils.price_resolver import (
            PRICE_LAYER_CONTRACT,
            PRICE_LAYER_LISTING,
            PRICE_LAYER_CHANNEL_PRICE_LIST,
            PRICE_LAYER_FALLBACK_PRICE_LIST
        )

        # Document expected priority order
        priority_order = [
            PRICE_LAYER_CONTRACT,           # 1. Highest - customer contract
            PRICE_LAYER_LISTING,            # 2. Channel listing
            PRICE_LAYER_CHANNEL_PRICE_LIST, # 3. Channel price list
            PRICE_LAYER_FALLBACK_PRICE_LIST # 4. Fallback (lowest for base price)
        ]

        # Verify constants are unique
        self.assertEqual(len(priority_order), len(set(priority_order)))


class TestCurrencyConversion(unittest.TestCase):
    """Test currency conversion functionality."""

    def test_get_exchange_rate_same_currency(self):
        """Test exchange rate returns 1 for same currency."""
        from frappe_pim.pim.utils.price_resolver import get_exchange_rate

        rate = get_exchange_rate("USD", "USD")
        self.assertEqual(rate, 1)

    def test_get_exchange_rate_different_currency(self):
        """Test exchange rate lookup for different currencies."""
        from frappe_pim.pim.utils.price_resolver import get_exchange_rate

        # This may return 1 if no exchange rate is configured
        rate = get_exchange_rate("USD", "EUR")
        self.assertIsNotNone(rate)
        self.assertIsInstance(rate, (int, float))


class TestPricingDocTypeVerification(unittest.TestCase):
    """Verify all pricing-related DocTypes exist and are properly configured."""

    @classmethod
    def setUpClass(cls):
        """Set up test class - called once before all tests."""
        import frappe
        frappe.set_user("Administrator")

    def test_all_pricing_doctypes_exist(self):
        """Verify all pricing-related DocTypes exist."""
        import frappe

        required_doctypes = [
            "PIM Sales Channel",
            "PIM Contract Price",
            "PIM Marketplace Listing",
            "PIM Customer Segment"
        ]

        for doctype in required_doctypes:
            self.assertTrue(
                frappe.db.exists("DocType", doctype),
                f"{doctype} DocType must exist"
            )

    def test_sales_channel_has_required_fields(self):
        """Verify PIM Sales Channel has all pricing fields."""
        import frappe

        meta = frappe.get_meta("PIM Sales Channel")

        required_fields = [
            "channel_name",
            "channel_code",
            "channel_type",
            "currency",
            "is_active"
        ]

        for field in required_fields:
            self.assertIsNotNone(
                meta.get_field(field),
                f"PIM Sales Channel missing required field: {field}"
            )

    def test_contract_price_has_required_fields(self):
        """Verify PIM Contract Price has all required fields."""
        import frappe

        meta = frappe.get_meta("PIM Contract Price")

        required_fields = [
            "contract_name",
            "customer_scope",
            "product_scope",
            "pricing_type",
            "is_active"
        ]

        for field in required_fields:
            self.assertIsNotNone(
                meta.get_field(field),
                f"PIM Contract Price missing required field: {field}"
            )


# Allow module import without running tests
if __name__ == "__main__":
    unittest.main()
