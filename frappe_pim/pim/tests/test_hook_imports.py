"""Hook Import Verification Tests

This module verifies that all module paths referenced in hooks.py
can be imported successfully without requiring the Frappe framework.

All utility modules use deferred frappe imports at function level,
allowing the modules themselves to be imported standalone.

Run via: python -m pytest frappe_pim/pim/tests/test_hook_imports.py -v
Or in bench: bench --site [site] run-tests --module frappe_pim.pim.tests.test_hook_imports
"""

import unittest


class TestHookImports(unittest.TestCase):
    """Test that all hook paths resolve to importable modules and functions."""

    # =========================================================================
    # Installation Hooks
    # =========================================================================

    def test_install_after_install(self):
        """Verify after_install hook can be imported."""
        from frappe_pim.pim.setup.install import after_install
        self.assertTrue(callable(after_install))

    def test_install_after_migrate(self):
        """Verify after_migrate hook can be imported."""
        from frappe_pim.pim.setup.install import after_migrate
        self.assertTrue(callable(after_migrate))

    def test_install_before_uninstall(self):
        """Verify before_uninstall hook can be imported."""
        from frappe_pim.pim.setup.install import before_uninstall
        self.assertTrue(callable(before_uninstall))

    # =========================================================================
    # Completeness Hooks
    # =========================================================================

    def test_completeness_calculate_score(self):
        """Verify calculate_score hook can be imported."""
        from frappe_pim.pim.utils.completeness import calculate_score
        self.assertTrue(callable(calculate_score))

    def test_completeness_calculate_variant_score(self):
        """Verify calculate_variant_score hook can be imported."""
        from frappe_pim.pim.utils.completeness import calculate_variant_score
        self.assertTrue(callable(calculate_variant_score))

    # =========================================================================
    # Inheritance Hooks
    # =========================================================================

    def test_inheritance_copy_family_attributes(self):
        """Verify copy_family_attributes hook can be imported."""
        from frappe_pim.pim.utils.inheritance import copy_family_attributes
        self.assertTrue(callable(copy_family_attributes))

    def test_inheritance_inherit_from_master(self):
        """Verify inherit_from_master hook can be imported."""
        from frappe_pim.pim.utils.inheritance import inherit_from_master
        self.assertTrue(callable(inherit_from_master))

    # =========================================================================
    # Cache Hooks
    # =========================================================================

    def test_cache_invalidate_product_cache(self):
        """Verify invalidate_product_cache hook can be imported."""
        from frappe_pim.pim.utils.cache import invalidate_product_cache
        self.assertTrue(callable(invalidate_product_cache))

    def test_cache_invalidate_variant_cache(self):
        """Verify invalidate_variant_cache hook can be imported."""
        from frappe_pim.pim.utils.cache import invalidate_variant_cache
        self.assertTrue(callable(invalidate_variant_cache))

    def test_cache_invalidate_attribute_cache(self):
        """Verify invalidate_attribute_cache hook can be imported."""
        from frappe_pim.pim.utils.cache import invalidate_attribute_cache
        self.assertTrue(callable(invalidate_attribute_cache))

    def test_cache_invalidate_family_cache(self):
        """Verify invalidate_family_cache hook can be imported."""
        from frappe_pim.pim.utils.cache import invalidate_family_cache
        self.assertTrue(callable(invalidate_family_cache))

    # =========================================================================
    # ERP Sync Hooks
    # =========================================================================

    def test_erp_sync_on_item_insert(self):
        """Verify on_item_insert hook can be imported."""
        from frappe_pim.pim.utils.erp_sync import on_item_insert
        self.assertTrue(callable(on_item_insert))

    def test_erp_sync_on_item_update(self):
        """Verify on_item_update hook can be imported."""
        from frappe_pim.pim.utils.erp_sync import on_item_update
        self.assertTrue(callable(on_item_update))

    def test_erp_sync_on_item_delete(self):
        """Verify on_item_delete hook can be imported."""
        from frappe_pim.pim.utils.erp_sync import on_item_delete
        self.assertTrue(callable(on_item_delete))

    # =========================================================================
    # Scheduled Task Hooks
    # =========================================================================

    def test_scheduled_recalculate_stale_scores(self):
        """Verify recalculate_stale_scores hook can be imported."""
        from frappe_pim.pim.tasks.scheduled import recalculate_stale_scores
        self.assertTrue(callable(recalculate_stale_scores))

    def test_scheduled_generate_scheduled_feeds(self):
        """Verify generate_scheduled_feeds hook can be imported."""
        from frappe_pim.pim.tasks.scheduled import generate_scheduled_feeds
        self.assertTrue(callable(generate_scheduled_feeds))

    def test_scheduled_cleanup_orphan_media(self):
        """Verify cleanup_orphan_media hook can be imported."""
        from frappe_pim.pim.tasks.scheduled import cleanup_orphan_media
        self.assertTrue(callable(cleanup_orphan_media))

    def test_scheduled_optimize_eav_indexes(self):
        """Verify optimize_eav_indexes hook can be imported."""
        from frappe_pim.pim.tasks.scheduled import optimize_eav_indexes
        self.assertTrue(callable(optimize_eav_indexes))

    # =========================================================================
    # Jinja Helper Hooks
    # =========================================================================

    def test_jinja_get_product_attributes(self):
        """Verify get_product_attributes jinja helper can be imported."""
        from frappe_pim.pim.utils.jinja_helpers import get_product_attributes
        self.assertTrue(callable(get_product_attributes))

    def test_jinja_get_completeness_badge(self):
        """Verify get_completeness_badge jinja helper can be imported."""
        from frappe_pim.pim.utils.jinja_helpers import get_completeness_badge
        self.assertTrue(callable(get_completeness_badge))

    def test_jinja_get_completeness_progress_bar(self):
        """Verify get_completeness_progress_bar jinja helper can be imported."""
        from frappe_pim.pim.utils.jinja_helpers import get_completeness_progress_bar
        self.assertTrue(callable(get_completeness_progress_bar))

    def test_jinja_get_product_status_badge(self):
        """Verify get_product_status_badge jinja helper can be imported."""
        from frappe_pim.pim.utils.jinja_helpers import get_product_status_badge
        self.assertTrue(callable(get_product_status_badge))

    def test_jinja_format_attribute_value(self):
        """Verify format_attribute_value jinja helper can be imported."""
        from frappe_pim.pim.utils.jinja_helpers import format_attribute_value
        self.assertTrue(callable(format_attribute_value))


class TestModuleImports(unittest.TestCase):
    """Test that all hook modules can be imported as a whole."""

    def test_import_install_module(self):
        """Verify install module can be imported."""
        from frappe_pim.pim.setup import install
        self.assertIsNotNone(install)

    def test_import_completeness_module(self):
        """Verify completeness module can be imported."""
        from frappe_pim.pim.utils import completeness
        self.assertIsNotNone(completeness)

    def test_import_inheritance_module(self):
        """Verify inheritance module can be imported."""
        from frappe_pim.pim.utils import inheritance
        self.assertIsNotNone(inheritance)

    def test_import_cache_module(self):
        """Verify cache module can be imported."""
        from frappe_pim.pim.utils import cache
        self.assertIsNotNone(cache)

    def test_import_erp_sync_module(self):
        """Verify erp_sync module can be imported."""
        from frappe_pim.pim.utils import erp_sync
        self.assertIsNotNone(erp_sync)

    def test_import_scheduled_module(self):
        """Verify scheduled tasks module can be imported."""
        from frappe_pim.pim.tasks import scheduled
        self.assertIsNotNone(scheduled)

    def test_import_jinja_helpers_module(self):
        """Verify jinja_helpers module can be imported."""
        from frappe_pim.pim.utils import jinja_helpers
        self.assertIsNotNone(jinja_helpers)


if __name__ == "__main__":
    unittest.main()
