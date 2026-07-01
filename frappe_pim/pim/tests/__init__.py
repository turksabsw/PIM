# Copyright (c) 2024, Frappe PIM and contributors
# For license information, please see license.txt
"""PIM Test Suite

This package contains test modules for the Frappe PIM application:
- test_utils: Test utilities and fixtures for Frappe test setup
- test_product_master: Product Master CRUD and validation tests
- test_pim_attribute: Attribute types and options tests
- test_completeness: Completeness score algorithm tests
- test_inheritance: Family attribute inheritance tests
- test_grid_api: Grid API format and pagination tests
- test_e2e: Full workflow integration tests

Running Tests:
    # Run all PIM tests
    bench --site [site-name] run-tests --app frappe_pim

    # Run specific module tests
    bench --site [site-name] run-tests --module frappe_pim.pim.tests.test_product_master

    # Run with verbose output
    bench --site [site-name] run-tests --app frappe_pim --verbose

Note: Tests require a Frappe site to be running with the PIM app installed.
"""
