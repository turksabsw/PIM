# Copyright (c) 2024, Frappe PIM and contributors
# For license information, please see license.txt
"""BMEcat Export Unit Tests

This module contains unit tests for:
- BMEcat XML generation
- XML structure validation
- Article element generation
- Helper functions (HTML cleaning, MIME types, etc.)

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for linting/static analysis).
"""

import unittest


class TestBMEcatXMLGeneration(unittest.TestCase):
    """Test cases for BMEcat XML document generation."""

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

    def test_basic_catalog_generation(self):
        """Test basic BMEcat catalog XML generation."""
        from frappe_pim.pim.export.bmecat import export_catalog

        xml_content = export_catalog(
            products=[],
            supplier_id="TEST-SUPPLIER",
            supplier_name="Test Supplier Inc",
            catalog_id="TEST-CATALOG-001",
            catalog_version="1.0",
            language="eng",
            territory="US",
            currency="USD",
            save_file=False
        )

        # Verify XML was generated
        self.assertIsInstance(xml_content, str)
        self.assertIn('<?xml', xml_content)
        self.assertIn('BMECAT', xml_content)

    def test_catalog_has_header_section(self):
        """Test that generated XML has proper HEADER section."""
        from frappe_pim.pim.export.bmecat import export_catalog

        xml_content = export_catalog(
            products=[],
            supplier_id="SUPPLIER-123",
            supplier_name="My Supplier",
            catalog_id="CAT-001",
            catalog_version="2.0",
            save_file=False
        )

        self.assertIn('<HEADER>', xml_content)
        self.assertIn('<SUPPLIER_ID>SUPPLIER-123</SUPPLIER_ID>', xml_content)
        self.assertIn('<SUPPLIER_NAME>My Supplier</SUPPLIER_NAME>', xml_content)
        self.assertIn('<CATALOG_ID>CAT-001</CATALOG_ID>', xml_content)
        self.assertIn('<CATALOG_VERSION>2.0</CATALOG_VERSION>', xml_content)

    def test_catalog_has_generator_info(self):
        """Test that generated XML includes generator info."""
        from frappe_pim.pim.export.bmecat import export_catalog

        xml_content = export_catalog(
            products=[],
            supplier_id="TEST",
            supplier_name="Test",
            catalog_id="TEST",
            catalog_version="1.0",
            save_file=False
        )

        self.assertIn('<GENERATOR_INFO>Frappe PIM BMEcat Exporter</GENERATOR_INFO>', xml_content)

    def test_catalog_includes_language_and_currency(self):
        """Test that catalog includes language and currency settings."""
        from frappe_pim.pim.export.bmecat import export_catalog

        xml_content = export_catalog(
            products=[],
            supplier_id="TEST",
            supplier_name="Test",
            catalog_id="TEST",
            catalog_version="1.0",
            language="deu",
            currency="EUR",
            territory="DE",
            save_file=False
        )

        self.assertIn('<LANGUAGE>deu</LANGUAGE>', xml_content)
        self.assertIn('<CURRENCY>EUR</CURRENCY>', xml_content)
        self.assertIn('<TERRITORY>DE</TERRITORY>', xml_content)

    def test_catalog_has_t_new_catalog_element(self):
        """Test that generated XML has T_NEW_CATALOG element."""
        from frappe_pim.pim.export.bmecat import export_catalog

        xml_content = export_catalog(
            products=[],
            supplier_id="TEST",
            supplier_name="Test",
            catalog_id="TEST",
            catalog_version="1.0",
            save_file=False
        )

        self.assertIn('<T_NEW_CATALOG>', xml_content)
        self.assertIn('</T_NEW_CATALOG>', xml_content)

    def test_catalog_generation_date(self):
        """Test that catalog includes generation date."""
        from frappe_pim.pim.export.bmecat import export_catalog

        xml_content = export_catalog(
            products=[],
            supplier_id="TEST",
            supplier_name="Test",
            catalog_id="TEST",
            catalog_version="1.0",
            save_file=False
        )

        self.assertIn('<GENERATION_DATE>', xml_content)
        self.assertIn('</GENERATION_DATE>', xml_content)


class TestBMEcatXMLValidation(unittest.TestCase):
    """Test cases for BMEcat XML validation."""

    def test_validate_valid_bmecat_xml(self):
        """Test validation of valid BMEcat XML."""
        from frappe_pim.pim.export.bmecat import export_catalog, validate_bmecat_xml

        xml_content = export_catalog(
            products=[],
            supplier_id="TEST",
            supplier_name="Test",
            catalog_id="TEST",
            catalog_version="1.0",
            save_file=False
        )

        is_valid, errors = validate_bmecat_xml(xml_content)

        self.assertTrue(is_valid)
        self.assertEqual(len(errors), 0)

    def test_validate_missing_header(self):
        """Test validation fails when HEADER is missing."""
        from frappe_pim.pim.export.bmecat import validate_bmecat_xml

        # Malformed XML without HEADER
        invalid_xml = '<?xml version="1.0"?><BMECAT><T_NEW_CATALOG></T_NEW_CATALOG></BMECAT>'

        is_valid, errors = validate_bmecat_xml(invalid_xml)

        self.assertFalse(is_valid)
        self.assertIn("Missing required HEADER element", errors)

    def test_validate_missing_t_new_catalog(self):
        """Test validation fails when T_NEW_CATALOG is missing."""
        from frappe_pim.pim.export.bmecat import validate_bmecat_xml

        # Malformed XML without T_NEW_CATALOG
        invalid_xml = '<?xml version="1.0"?><BMECAT><HEADER><CATALOG><CATALOG_ID>1</CATALOG_ID></CATALOG></HEADER></BMECAT>'

        is_valid, errors = validate_bmecat_xml(invalid_xml)

        self.assertFalse(is_valid)
        self.assertIn("Missing T_NEW_CATALOG transaction element", errors)

    def test_validate_invalid_xml_syntax(self):
        """Test validation catches XML syntax errors."""
        from frappe_pim.pim.export.bmecat import validate_bmecat_xml

        # Malformed XML with syntax error
        invalid_xml = '<?xml version="1.0"?><BMECAT><HEADER>'  # Missing closing tags

        is_valid, errors = validate_bmecat_xml(invalid_xml)

        self.assertFalse(is_valid)
        self.assertTrue(any("XML Syntax Error" in e for e in errors))

    def test_validate_wrong_root_element(self):
        """Test validation fails with wrong root element."""
        from frappe_pim.pim.export.bmecat import validate_bmecat_xml

        invalid_xml = '<?xml version="1.0"?><CATALOG><HEADER></HEADER></CATALOG>'

        is_valid, errors = validate_bmecat_xml(invalid_xml)

        self.assertFalse(is_valid)
        self.assertIn("Root element must be BMECAT", errors)


class TestBMEcatArticleGeneration(unittest.TestCase):
    """Test cases for article element generation in BMEcat XML."""

    @classmethod
    def setUpClass(cls):
        """Set up test class."""
        import frappe
        frappe.set_user("Administrator")

    def setUp(self):
        """Set up test."""
        self.created_documents = []

    def tearDown(self):
        """Tear down test."""
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
        """Track a document for cleanup."""
        self.created_documents.append((doctype, name))

    def test_article_generation_with_product(self):
        """Test article generation with a real product."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.export.bmecat import export_catalog

        # Create a test product
        product_code = f"EXP-{random_string(6).upper()}"
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Export Test Product {random_string(4)}",
            "product_code": product_code,
            "short_description": "A test product for export",
            "status": "Active"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Generate catalog with this product
        xml_content = export_catalog(
            products=[product.name],
            supplier_id="TEST",
            supplier_name="Test",
            catalog_id="TEST",
            catalog_version="1.0",
            save_file=False
        )

        # Verify article was included
        self.assertIn('<ARTICLE', xml_content)
        self.assertIn(f'<SUPPLIER_AID>{product_code}</SUPPLIER_AID>', xml_content)
        self.assertIn('<DESCRIPTION_SHORT>', xml_content)

    def test_article_includes_description(self):
        """Test article includes description elements."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.export.bmecat import export_catalog

        product_code = f"DESC-{random_string(6).upper()}"
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Product with Description {random_string(4)}",
            "product_code": product_code,
            "short_description": "This is a short description for export",
            "status": "Draft"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        xml_content = export_catalog(
            products=[product.name],
            supplier_id="TEST",
            supplier_name="Test",
            catalog_id="TEST",
            catalog_version="1.0",
            save_file=False
        )

        self.assertIn('<ARTICLE_DETAILS>', xml_content)
        self.assertIn('<DESCRIPTION_SHORT>', xml_content)

    def test_article_with_variant(self):
        """Test article generation from product variant."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.export.bmecat import export_catalog

        # Create master product
        master_code = f"MASTER-{random_string(6).upper()}"
        master = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Master Product {random_string(4)}",
            "product_code": master_code,
            "status": "Active"
        })
        master.insert(ignore_permissions=True)
        self.track_document("Product Master", master.name)

        # Create variant
        variant_code = f"VAR-{random_string(6).upper()}"
        variant = frappe.get_doc({
            "doctype": "Product Variant",
            "variant_name": f"Variant {random_string(4)}",
            "variant_code": variant_code,
            "product_master": master.name,
            "status": "Active"
        })
        variant.insert(ignore_permissions=True)
        self.track_document("Product Variant", variant.name)

        xml_content = export_catalog(
            products=[variant.name],
            supplier_id="TEST",
            supplier_name="Test",
            catalog_id="TEST",
            catalog_version="1.0",
            save_file=False
        )

        self.assertIn(f'<SUPPLIER_AID>{variant_code}</SUPPLIER_AID>', xml_content)


class TestBMEcatArticleCount(unittest.TestCase):
    """Test cases for article count utility function."""

    def test_get_article_count_empty_catalog(self):
        """Test article count in empty catalog."""
        from frappe_pim.pim.export.bmecat import export_catalog, get_article_count

        xml_content = export_catalog(
            products=[],
            supplier_id="TEST",
            supplier_name="Test",
            catalog_id="TEST",
            catalog_version="1.0",
            save_file=False
        )

        count = get_article_count(xml_content)
        self.assertEqual(count, 0)

    def test_get_article_count_with_products(self):
        """Test article count with products."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.export.bmecat import export_catalog, get_article_count

        # Create products
        products = []
        for i in range(3):
            product = frappe.get_doc({
                "doctype": "Product Master",
                "product_name": f"Count Test {i} {random_string(4)}",
                "product_code": f"CNT{i}-{random_string(6).upper()}",
                "status": "Active"
            })
            product.insert(ignore_permissions=True)
            products.append(product)

        xml_content = export_catalog(
            products=[p.name for p in products],
            supplier_id="TEST",
            supplier_name="Test",
            catalog_id="TEST",
            catalog_version="1.0",
            save_file=False
        )

        # Cleanup
        for p in products:
            frappe.delete_doc("Product Master", p.name, force=True, ignore_permissions=True)
        frappe.db.commit()

        count = get_article_count(xml_content)
        self.assertEqual(count, 3)

    def test_get_article_count_invalid_xml(self):
        """Test article count with invalid XML returns 0."""
        from frappe_pim.pim.export.bmecat import get_article_count

        count = get_article_count("not valid xml")
        self.assertEqual(count, 0)


class TestBMEcatHelperFunctions(unittest.TestCase):
    """Test cases for BMEcat helper functions."""

    def test_clean_html_removes_tags(self):
        """Test HTML tag removal."""
        from frappe_pim.pim.export.bmecat import _clean_html

        html = "<p>Hello <strong>world</strong></p>"
        clean = _clean_html(html)

        self.assertEqual(clean, "Hello world")

    def test_clean_html_handles_empty(self):
        """Test HTML cleaning handles empty string."""
        from frappe_pim.pim.export.bmecat import _clean_html

        self.assertEqual(_clean_html(""), "")
        self.assertEqual(_clean_html(None), "")

    def test_clean_html_normalizes_whitespace(self):
        """Test HTML cleaning normalizes whitespace."""
        from frappe_pim.pim.export.bmecat import _clean_html

        html = "<p>Hello</p>   <p>World</p>"
        clean = _clean_html(html)

        self.assertEqual(clean, "Hello World")

    def test_get_mime_type_jpeg(self):
        """Test MIME type detection for JPEG."""
        from frappe_pim.pim.export.bmecat import _get_mime_type

        self.assertEqual(_get_mime_type("image.jpg"), "image/jpeg")
        self.assertEqual(_get_mime_type("image.jpeg"), "image/jpeg")

    def test_get_mime_type_png(self):
        """Test MIME type detection for PNG."""
        from frappe_pim.pim.export.bmecat import _get_mime_type

        self.assertEqual(_get_mime_type("image.png"), "image/png")

    def test_get_mime_type_webp(self):
        """Test MIME type detection for WebP."""
        from frappe_pim.pim.export.bmecat import _get_mime_type

        self.assertEqual(_get_mime_type("image.webp"), "image/webp")

    def test_get_mime_type_pdf(self):
        """Test MIME type detection for PDF."""
        from frappe_pim.pim.export.bmecat import _get_mime_type

        self.assertEqual(_get_mime_type("document.pdf"), "application/pdf")

    def test_get_mime_type_unknown(self):
        """Test MIME type detection for unknown extension."""
        from frappe_pim.pim.export.bmecat import _get_mime_type

        self.assertEqual(_get_mime_type("file.xyz"), "application/octet-stream")

    def test_get_mime_type_no_extension(self):
        """Test MIME type detection for file without extension."""
        from frappe_pim.pim.export.bmecat import _get_mime_type

        self.assertEqual(_get_mime_type("file"), "application/octet-stream")

    def test_get_mime_type_empty(self):
        """Test MIME type detection for empty path."""
        from frappe_pim.pim.export.bmecat import _get_mime_type

        self.assertEqual(_get_mime_type(""), "application/octet-stream")
        self.assertEqual(_get_mime_type(None), "application/octet-stream")


class TestBMEcatAttributeValue(unittest.TestCase):
    """Test cases for attribute value extraction."""

    def test_get_attribute_value_text(self):
        """Test extracting text value from attribute."""
        from frappe_pim.pim.export.bmecat import _get_attribute_value

        attr_value = {"attribute": "color", "value_text": "Red"}
        value = _get_attribute_value(attr_value)

        self.assertEqual(value, "Red")

    def test_get_attribute_value_int(self):
        """Test extracting integer value from attribute."""
        from frappe_pim.pim.export.bmecat import _get_attribute_value

        attr_value = {"attribute": "quantity", "value_int": 42}
        value = _get_attribute_value(attr_value)

        self.assertEqual(value, 42)

    def test_get_attribute_value_float(self):
        """Test extracting float value from attribute."""
        from frappe_pim.pim.export.bmecat import _get_attribute_value

        attr_value = {"attribute": "weight", "value_float": 3.14}
        value = _get_attribute_value(attr_value)

        self.assertEqual(value, 3.14)

    def test_get_attribute_value_boolean_true(self):
        """Test extracting boolean True value from attribute."""
        from frappe_pim.pim.export.bmecat import _get_attribute_value

        attr_value = {"attribute": "active", "value_boolean": True}
        value = _get_attribute_value(attr_value)

        self.assertEqual(value, "yes")

    def test_get_attribute_value_boolean_false(self):
        """Test extracting boolean False value from attribute."""
        from frappe_pim.pim.export.bmecat import _get_attribute_value

        attr_value = {"attribute": "discontinued", "value_boolean": False}
        value = _get_attribute_value(attr_value)

        self.assertEqual(value, "no")

    def test_get_attribute_value_date(self):
        """Test extracting date value from attribute."""
        from frappe_pim.pim.export.bmecat import _get_attribute_value

        attr_value = {"attribute": "release_date", "value_date": "2024-01-15"}
        value = _get_attribute_value(attr_value)

        self.assertEqual(value, "2024-01-15")

    def test_get_attribute_value_none(self):
        """Test extracting value when no value is set."""
        from frappe_pim.pim.export.bmecat import _get_attribute_value

        attr_value = {"attribute": "empty_attr"}
        value = _get_attribute_value(attr_value)

        self.assertIsNone(value)

    def test_get_attribute_value_empty_string(self):
        """Test that empty string is treated as no value."""
        from frappe_pim.pim.export.bmecat import _get_attribute_value

        attr_value = {"attribute": "empty_text", "value_text": "   "}
        value = _get_attribute_value(attr_value)

        self.assertIsNone(value)


class TestBMEcatLanguageCode(unittest.TestCase):
    """Test cases for language code conversion."""

    def test_get_language_code_english(self):
        """Test language code for English."""
        from frappe_pim.pim.export.bmecat import _get_language_code

        self.assertEqual(_get_language_code("en"), "eng")

    def test_get_language_code_german(self):
        """Test language code for German."""
        from frappe_pim.pim.export.bmecat import _get_language_code

        self.assertEqual(_get_language_code("de"), "deu")

    def test_get_language_code_french(self):
        """Test language code for French."""
        from frappe_pim.pim.export.bmecat import _get_language_code

        self.assertEqual(_get_language_code("fr"), "fra")

    def test_get_language_code_unknown(self):
        """Test language code for unknown language defaults to English."""
        from frappe_pim.pim.export.bmecat import _get_language_code

        self.assertEqual(_get_language_code("unknown"), "eng")

    def test_get_language_code_empty(self):
        """Test language code for empty string defaults to English."""
        from frappe_pim.pim.export.bmecat import _get_language_code

        self.assertEqual(_get_language_code(""), "eng")

    def test_get_language_code_none(self):
        """Test language code for None defaults to English."""
        from frappe_pim.pim.export.bmecat import _get_language_code

        self.assertEqual(_get_language_code(None), "eng")


class TestBMEcatWithExportProfile(unittest.TestCase):
    """Test cases for export with Export Profile configuration."""

    @classmethod
    def setUpClass(cls):
        """Set up test class."""
        import frappe
        frappe.set_user("Administrator")

    def setUp(self):
        """Set up test."""
        self.created_documents = []

    def tearDown(self):
        """Tear down test."""
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
        """Track a document for cleanup."""
        self.created_documents.append((doctype, name))

    def test_export_with_nonexistent_profile(self):
        """Test export with non-existent profile uses defaults."""
        from frappe_pim.pim.export.bmecat import export_catalog

        # Non-existent profile should not raise, just use defaults
        xml_content = export_catalog(
            profile_name="NonExistentProfile123456",
            products=[],
            save_file=False
        )

        self.assertIsInstance(xml_content, str)
        self.assertIn('BMECAT', xml_content)


class TestBMEcatXMLStructure(unittest.TestCase):
    """Test cases for BMEcat XML structure and namespaces."""

    def test_xml_has_proper_namespace(self):
        """Test that generated XML has BMEcat namespace."""
        from frappe_pim.pim.export.bmecat import export_catalog, BMECAT_NS

        xml_content = export_catalog(
            products=[],
            supplier_id="TEST",
            supplier_name="Test",
            catalog_id="TEST",
            catalog_version="1.0",
            save_file=False
        )

        self.assertIn(BMECAT_NS, xml_content)

    def test_xml_has_schema_location(self):
        """Test that generated XML has schema location attribute."""
        from frappe_pim.pim.export.bmecat import export_catalog

        xml_content = export_catalog(
            products=[],
            supplier_id="TEST",
            supplier_name="Test",
            catalog_id="TEST",
            catalog_version="1.0",
            save_file=False
        )

        self.assertIn('schemaLocation', xml_content)
        self.assertIn('bmecat_2005.xsd', xml_content)

    def test_xml_has_version_attribute(self):
        """Test that BMECAT element has version attribute."""
        from frappe_pim.pim.export.bmecat import export_catalog

        xml_content = export_catalog(
            products=[],
            supplier_id="TEST",
            supplier_name="Test",
            catalog_id="TEST",
            catalog_version="1.0",
            save_file=False
        )

        self.assertIn('version="2005"', xml_content)

    def test_pretty_print_option(self):
        """Test pretty print option formats XML with indentation."""
        from frappe_pim.pim.export.bmecat import export_catalog

        # With pretty print (default)
        pretty_xml = export_catalog(
            products=[],
            supplier_id="TEST",
            supplier_name="Test",
            catalog_id="TEST",
            catalog_version="1.0",
            pretty_print=True,
            save_file=False
        )

        # Should contain newlines for pretty printing
        self.assertIn('\n', pretty_xml)


class TestBMEcatOrderDetails(unittest.TestCase):
    """Test cases for ARTICLE_ORDER_DETAILS element generation."""

    @classmethod
    def setUpClass(cls):
        """Set up test class."""
        import frappe
        frappe.set_user("Administrator")

    def setUp(self):
        """Set up test."""
        self.created_documents = []

    def tearDown(self):
        """Tear down test."""
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
        """Track a document for cleanup."""
        self.created_documents.append((doctype, name))

    def test_article_has_order_details(self):
        """Test that articles include order details section."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.export.bmecat import export_catalog

        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Order Detail Test {random_string(4)}",
            "product_code": f"ORD-{random_string(6).upper()}",
            "status": "Active"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        xml_content = export_catalog(
            products=[product.name],
            supplier_id="TEST",
            supplier_name="Test",
            catalog_id="TEST",
            catalog_version="1.0",
            save_file=False
        )

        self.assertIn('<ARTICLE_ORDER_DETAILS>', xml_content)
        self.assertIn('<ORDER_UNIT>', xml_content)
        self.assertIn('<QUANTITY_MIN>', xml_content)


class TestBMEcatPriceDetails(unittest.TestCase):
    """Test cases for ARTICLE_PRICE_DETAILS element generation."""

    @classmethod
    def setUpClass(cls):
        """Set up test class."""
        import frappe
        frappe.set_user("Administrator")

    def setUp(self):
        """Set up test."""
        self.created_documents = []

    def tearDown(self):
        """Tear down test."""
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
        """Track a document for cleanup."""
        self.created_documents.append((doctype, name))

    def test_price_excluded_when_no_price(self):
        """Test that price details are excluded when product has no price."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.export.bmecat import export_catalog

        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"No Price Test {random_string(4)}",
            "product_code": f"NOP-{random_string(6).upper()}",
            "status": "Active"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        xml_content = export_catalog(
            products=[product.name],
            supplier_id="TEST",
            supplier_name="Test",
            catalog_id="TEST",
            catalog_version="1.0",
            include_prices=True,
            save_file=False
        )

        # Should not have price details since product has no price
        self.assertNotIn('<ARTICLE_PRICE_DETAILS>', xml_content)


class TestBMEcatLxmlImport(unittest.TestCase):
    """Test cases for lxml dependency handling."""

    def test_export_requires_lxml(self):
        """Test that export function handles lxml import."""
        from frappe_pim.pim.export.bmecat import export_catalog

        # This should work if lxml is available
        try:
            xml_content = export_catalog(
                products=[],
                supplier_id="TEST",
                supplier_name="Test",
                catalog_id="TEST",
                catalog_version="1.0",
                save_file=False
            )
            self.assertIsInstance(xml_content, str)
        except ImportError as e:
            # If lxml is not installed, should raise ImportError with helpful message
            self.assertIn("lxml", str(e))


# Allow module import without running tests
if __name__ == "__main__":
    unittest.main()
