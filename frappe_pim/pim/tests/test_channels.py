# Copyright (c) 2024, Frappe PIM and contributors
# For license information, please see license.txt
"""Channel Adapter Unit Tests

This module contains unit tests for:
- Channel adapter base class functionality
- Adapter registry management
- Data classes (ValidationResult, MappingResult, PublishResult, etc.)
- Rate limiting logic
- Error handling

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for linting/static analysis).
"""

import unittest
from datetime import datetime, timedelta


class TestChannelAdapterBase(unittest.TestCase):
    """Test cases for ChannelAdapter base class."""

    def test_adapter_abstract_methods_exist(self):
        """Test that abstract methods are defined in base class."""
        from frappe_pim.pim.channels.base import ChannelAdapter
        import inspect

        # Check abstract methods exist
        abstract_methods = [
            "validate_product",
            "map_attributes",
            "generate_payload",
            "publish",
            "get_status",
            "handle_rate_limiting"
        ]

        for method_name in abstract_methods:
            self.assertTrue(hasattr(ChannelAdapter, method_name))
            method = getattr(ChannelAdapter, method_name)
            self.assertTrue(callable(method))

    def test_adapter_class_attributes(self):
        """Test that class attributes are defined."""
        from frappe_pim.pim.channels.base import ChannelAdapter

        # Check class attributes
        self.assertTrue(hasattr(ChannelAdapter, "channel_code"))
        self.assertTrue(hasattr(ChannelAdapter, "channel_name"))
        self.assertTrue(hasattr(ChannelAdapter, "default_requests_per_minute"))
        self.assertTrue(hasattr(ChannelAdapter, "max_retry_attempts"))

    def test_adapter_defaults(self):
        """Test default values for adapter settings."""
        from frappe_pim.pim.channels.base import ChannelAdapter

        self.assertEqual(ChannelAdapter.default_requests_per_minute, 60)
        self.assertEqual(ChannelAdapter.max_retry_attempts, 3)
        self.assertEqual(ChannelAdapter.base_backoff_seconds, 1.0)
        self.assertEqual(ChannelAdapter.max_backoff_seconds, 60.0)


class TestAdapterRegistry(unittest.TestCase):
    """Test cases for adapter registry management."""

    def test_register_adapter(self):
        """Test registering an adapter class."""
        from frappe_pim.pim.channels.base import (
            register_adapter,
            list_adapters,
            ChannelAdapter,
            ValidationResult,
            MappingResult,
            PublishResult,
            StatusResult,
            PublishStatus
        )

        # Create a mock adapter
        class MockTestAdapter(ChannelAdapter):
            channel_code = "mock_test"
            channel_name = "Mock Test"

            def validate_product(self, product):
                return ValidationResult(is_valid=True, product=product.get("name", ""))

            def map_attributes(self, product):
                return MappingResult(product=product.get("name", ""), mapped_data={})

            def generate_payload(self, products):
                return {"products": products}

            def publish(self, products):
                return PublishResult(success=True)

            def get_status(self, job_id):
                return StatusResult(job_id=job_id, status=PublishStatus.COMPLETED)

            def handle_rate_limiting(self, response=None):
                pass

        # Register adapter
        register_adapter("mock_test_channel", MockTestAdapter)

        # Verify registration
        adapters = list_adapters()
        self.assertIn("mock_test_channel", adapters)

    def test_list_adapters(self):
        """Test listing registered adapters."""
        from frappe_pim.pim.channels.base import list_adapters

        adapters = list_adapters()
        self.assertIsInstance(adapters, list)


class TestValidationResult(unittest.TestCase):
    """Test cases for ValidationResult data class."""

    def test_validation_result_creation(self):
        """Test creating a ValidationResult."""
        from frappe_pim.pim.channels.base import ValidationResult

        result = ValidationResult(
            is_valid=True,
            product="TEST-001",
            errors=[],
            warnings=[]
        )

        self.assertTrue(result.is_valid)
        self.assertEqual(result.product, "TEST-001")
        self.assertEqual(len(result.errors), 0)

    def test_validation_result_with_errors(self):
        """Test ValidationResult with errors."""
        from frappe_pim.pim.channels.base import ValidationResult

        result = ValidationResult(
            is_valid=False,
            product="TEST-002",
            errors=[{"field": "title", "message": "Title is required"}],
            warnings=[{"field": "description", "message": "Description too short"}]
        )

        self.assertFalse(result.is_valid)
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.errors[0]["field"], "title")
        self.assertEqual(len(result.warnings), 1)

    def test_validation_result_to_dict(self):
        """Test ValidationResult.to_dict method."""
        from frappe_pim.pim.channels.base import ValidationResult

        result = ValidationResult(
            is_valid=True,
            product="TEST-003",
            channel="amazon"
        )

        result_dict = result.to_dict()

        self.assertIsInstance(result_dict, dict)
        self.assertIn("is_valid", result_dict)
        self.assertIn("product", result_dict)
        self.assertIn("channel", result_dict)
        self.assertIn("validated_at", result_dict)


class TestMappingResult(unittest.TestCase):
    """Test cases for MappingResult data class."""

    def test_mapping_result_creation(self):
        """Test creating a MappingResult."""
        from frappe_pim.pim.channels.base import MappingResult

        result = MappingResult(
            product="TEST-001",
            mapped_data={"title": "Test Product", "price": 29.99},
            unmapped_fields=["custom_field_1"]
        )

        self.assertEqual(result.product, "TEST-001")
        self.assertEqual(result.mapped_data["title"], "Test Product")
        self.assertEqual(len(result.unmapped_fields), 1)

    def test_mapping_result_to_dict(self):
        """Test MappingResult.to_dict method."""
        from frappe_pim.pim.channels.base import MappingResult

        result = MappingResult(
            product="TEST-002",
            mapped_data={"sku": "SKU-123"},
            channel="shopify"
        )

        result_dict = result.to_dict()

        self.assertIsInstance(result_dict, dict)
        self.assertIn("product", result_dict)
        self.assertIn("mapped_data", result_dict)
        self.assertIn("unmapped_fields", result_dict)


class TestPublishResult(unittest.TestCase):
    """Test cases for PublishResult data class."""

    def test_publish_result_creation(self):
        """Test creating a PublishResult."""
        from frappe_pim.pim.channels.base import PublishResult, PublishStatus

        result = PublishResult(
            success=True,
            job_id="JOB-001",
            status=PublishStatus.COMPLETED,
            products_submitted=10,
            products_succeeded=10,
            products_failed=0
        )

        self.assertTrue(result.success)
        self.assertEqual(result.job_id, "JOB-001")
        self.assertEqual(result.status, PublishStatus.COMPLETED)
        self.assertEqual(result.products_submitted, 10)

    def test_publish_result_partial_success(self):
        """Test PublishResult with partial success."""
        from frappe_pim.pim.channels.base import PublishResult, PublishStatus

        result = PublishResult(
            success=True,
            status=PublishStatus.PARTIAL,
            products_submitted=10,
            products_succeeded=7,
            products_failed=3,
            errors=[
                {"product": "PROD-001", "error": "Invalid GTIN"},
                {"product": "PROD-002", "error": "Missing title"},
                {"product": "PROD-003", "error": "Price out of range"}
            ]
        )

        self.assertEqual(result.status, PublishStatus.PARTIAL)
        self.assertEqual(result.products_failed, 3)
        self.assertEqual(len(result.errors), 3)

    def test_publish_result_to_dict(self):
        """Test PublishResult.to_dict method."""
        from frappe_pim.pim.channels.base import PublishResult, PublishStatus

        result = PublishResult(
            success=True,
            job_id="JOB-002",
            status=PublishStatus.PENDING
        )

        result_dict = result.to_dict()

        self.assertIsInstance(result_dict, dict)
        self.assertIn("success", result_dict)
        self.assertIn("job_id", result_dict)
        self.assertIn("status", result_dict)
        self.assertEqual(result_dict["status"], "pending")


class TestStatusResult(unittest.TestCase):
    """Test cases for StatusResult data class."""

    def test_status_result_creation(self):
        """Test creating a StatusResult."""
        from frappe_pim.pim.channels.base import StatusResult, PublishStatus

        result = StatusResult(
            job_id="JOB-001",
            status=PublishStatus.IN_PROGRESS,
            progress=0.5,
            products_processed=50,
            products_total=100
        )

        self.assertEqual(result.job_id, "JOB-001")
        self.assertEqual(result.status, PublishStatus.IN_PROGRESS)
        self.assertEqual(result.progress, 0.5)

    def test_status_result_completed(self):
        """Test StatusResult for completed job."""
        from frappe_pim.pim.channels.base import StatusResult, PublishStatus

        result = StatusResult(
            job_id="JOB-002",
            status=PublishStatus.COMPLETED,
            progress=1.0,
            products_processed=100,
            products_total=100,
            completed_at=datetime.now()
        )

        self.assertEqual(result.status, PublishStatus.COMPLETED)
        self.assertEqual(result.progress, 1.0)
        self.assertIsNotNone(result.completed_at)

    def test_status_result_to_dict(self):
        """Test StatusResult.to_dict method."""
        from frappe_pim.pim.channels.base import StatusResult, PublishStatus

        result = StatusResult(
            job_id="JOB-003",
            status=PublishStatus.FAILED,
            errors=[{"message": "Connection timeout"}]
        )

        result_dict = result.to_dict()

        self.assertIsInstance(result_dict, dict)
        self.assertIn("job_id", result_dict)
        self.assertIn("status", result_dict)
        self.assertIn("errors", result_dict)


class TestRateLimitState(unittest.TestCase):
    """Test cases for RateLimitState data class."""

    def test_rate_limit_state_creation(self):
        """Test creating a RateLimitState."""
        from frappe_pim.pim.channels.base import RateLimitState

        state = RateLimitState(
            requests_limit=100,
            window_duration=60
        )

        self.assertEqual(state.requests_limit, 100)
        self.assertEqual(state.window_duration, 60)
        self.assertEqual(state.requests_made, 0)

    def test_rate_limit_is_limited_false(self):
        """Test is_limited returns False when under limit."""
        from frappe_pim.pim.channels.base import RateLimitState

        state = RateLimitState(
            requests_limit=100,
            window_duration=60
        )
        state.requests_made = 50

        self.assertFalse(state.is_limited())

    def test_rate_limit_is_limited_true(self):
        """Test is_limited returns True when at limit."""
        from frappe_pim.pim.channels.base import RateLimitState

        state = RateLimitState(
            requests_limit=100,
            window_duration=60
        )
        state.requests_made = 100

        self.assertTrue(state.is_limited())

    def test_rate_limit_is_limited_with_retry_after(self):
        """Test is_limited returns True when retry_after is set."""
        from frappe_pim.pim.channels.base import RateLimitState

        state = RateLimitState(
            requests_limit=100,
            window_duration=60
        )
        state.retry_after = datetime.now() + timedelta(seconds=30)

        self.assertTrue(state.is_limited())

    def test_rate_limit_wait_time(self):
        """Test wait_time calculation."""
        from frappe_pim.pim.channels.base import RateLimitState

        state = RateLimitState(
            requests_limit=100,
            window_duration=60
        )
        state.requests_made = 50

        wait_time = state.wait_time()
        self.assertEqual(wait_time, 0)

    def test_rate_limit_wait_time_with_retry_after(self):
        """Test wait_time when retry_after is set."""
        from frappe_pim.pim.channels.base import RateLimitState

        state = RateLimitState(
            requests_limit=100,
            window_duration=60
        )
        state.retry_after = datetime.now() + timedelta(seconds=10)

        wait_time = state.wait_time()
        self.assertGreater(wait_time, 0)
        self.assertLessEqual(wait_time, 10)


class TestPublishStatus(unittest.TestCase):
    """Test cases for PublishStatus enum."""

    def test_publish_status_values(self):
        """Test PublishStatus enum values."""
        from frappe_pim.pim.channels.base import PublishStatus

        self.assertEqual(PublishStatus.PENDING.value, "pending")
        self.assertEqual(PublishStatus.IN_PROGRESS.value, "in_progress")
        self.assertEqual(PublishStatus.COMPLETED.value, "completed")
        self.assertEqual(PublishStatus.FAILED.value, "failed")
        self.assertEqual(PublishStatus.PARTIAL.value, "partial")
        self.assertEqual(PublishStatus.RATE_LIMITED.value, "rate_limited")
        self.assertEqual(PublishStatus.CANCELLED.value, "cancelled")


class TestChannelAdapterExceptions(unittest.TestCase):
    """Test cases for channel adapter exception classes."""

    def test_channel_adapter_error(self):
        """Test ChannelAdapterError exception."""
        from frappe_pim.pim.channels.base import ChannelAdapterError

        error = ChannelAdapterError(
            message="Test error",
            channel="amazon",
            details={"code": "TEST_ERROR"}
        )

        self.assertEqual(error.message, "Test error")
        self.assertEqual(error.channel, "amazon")
        self.assertEqual(error.details["code"], "TEST_ERROR")

    def test_channel_adapter_error_to_dict(self):
        """Test ChannelAdapterError.to_dict method."""
        from frappe_pim.pim.channels.base import ChannelAdapterError

        error = ChannelAdapterError(
            message="Test error",
            channel="shopify"
        )

        error_dict = error.to_dict()

        self.assertIn("error", error_dict)
        self.assertIn("message", error_dict)
        self.assertIn("channel", error_dict)

    def test_validation_error(self):
        """Test ValidationError exception."""
        from frappe_pim.pim.channels.base import ValidationError

        error = ValidationError(
            message="Invalid field value",
            channel="amazon",
            field="price",
            value=-10.00,
            rule="price_must_be_positive"
        )

        self.assertEqual(error.field, "price")
        self.assertEqual(error.value, -10.00)
        self.assertEqual(error.rule, "price_must_be_positive")

    def test_rate_limit_error(self):
        """Test RateLimitError exception."""
        from frappe_pim.pim.channels.base import RateLimitError

        error = RateLimitError(
            message="Rate limit exceeded",
            channel="amazon",
            retry_after=60,
            quota_remaining=0
        )

        self.assertEqual(error.retry_after, 60)
        self.assertEqual(error.quota_remaining, 0)

    def test_authentication_error(self):
        """Test AuthenticationError exception."""
        from frappe_pim.pim.channels.base import AuthenticationError

        error = AuthenticationError(
            message="Invalid API key",
            channel="shopify"
        )

        self.assertEqual(error.message, "Invalid API key")
        self.assertEqual(error.channel, "shopify")

    def test_publish_error(self):
        """Test PublishError exception."""
        from frappe_pim.pim.channels.base import PublishError

        error = PublishError(
            message="Publish failed",
            channel="amazon",
            products=["PROD-001", "PROD-002"],
            partial_success=True
        )

        self.assertEqual(len(error.products), 2)
        self.assertTrue(error.partial_success)


class TestChannelAdapterHelpers(unittest.TestCase):
    """Test cases for channel adapter helper methods."""

    def test_calculate_backoff(self):
        """Test exponential backoff calculation."""
        from frappe_pim.pim.channels.base import (
            ChannelAdapter,
            ValidationResult,
            MappingResult,
            PublishResult,
            StatusResult,
            PublishStatus
        )

        # Create concrete adapter for testing
        class TestAdapter(ChannelAdapter):
            channel_code = "test"
            channel_name = "Test"
            base_backoff_seconds = 1.0
            max_backoff_seconds = 60.0

            def validate_product(self, product):
                return ValidationResult(is_valid=True, product="")

            def map_attributes(self, product):
                return MappingResult(product="", mapped_data={})

            def generate_payload(self, products):
                return {}

            def publish(self, products):
                return PublishResult(success=True)

            def get_status(self, job_id):
                return StatusResult(job_id=job_id, status=PublishStatus.COMPLETED)

            def handle_rate_limiting(self, response=None):
                pass

        adapter = TestAdapter()

        # Test backoff calculation
        backoff_0 = adapter._calculate_backoff(0)
        backoff_1 = adapter._calculate_backoff(1)
        backoff_2 = adapter._calculate_backoff(2)

        self.assertEqual(backoff_0, 1.0)  # 1 * 2^0 = 1
        self.assertEqual(backoff_1, 2.0)  # 1 * 2^1 = 2
        self.assertEqual(backoff_2, 4.0)  # 1 * 2^2 = 4

        # Test max backoff
        backoff_large = adapter._calculate_backoff(10)
        self.assertEqual(backoff_large, 60.0)  # Capped at max_backoff_seconds

    def test_validate_products_batch(self):
        """Test batch validation method."""
        from frappe_pim.pim.channels.base import (
            ChannelAdapter,
            ValidationResult,
            MappingResult,
            PublishResult,
            StatusResult,
            PublishStatus
        )

        class TestAdapter(ChannelAdapter):
            channel_code = "test"
            channel_name = "Test"

            def validate_product(self, product):
                is_valid = "title" in product
                return ValidationResult(
                    is_valid=is_valid,
                    product=product.get("sku", ""),
                    errors=[] if is_valid else [{"field": "title", "message": "Required"}]
                )

            def map_attributes(self, product):
                return MappingResult(product="", mapped_data={})

            def generate_payload(self, products):
                return {}

            def publish(self, products):
                return PublishResult(success=True)

            def get_status(self, job_id):
                return StatusResult(job_id=job_id, status=PublishStatus.COMPLETED)

            def handle_rate_limiting(self, response=None):
                pass

        adapter = TestAdapter()

        products = [
            {"sku": "SKU-001", "title": "Product 1"},
            {"sku": "SKU-002"},  # Missing title
            {"sku": "SKU-003", "title": "Product 3"}
        ]

        results = adapter.validate_products(products)

        self.assertEqual(len(results), 3)
        self.assertTrue(results[0].is_valid)
        self.assertFalse(results[1].is_valid)
        self.assertTrue(results[2].is_valid)

    def test_map_products_batch(self):
        """Test batch mapping method."""
        from frappe_pim.pim.channels.base import (
            ChannelAdapter,
            ValidationResult,
            MappingResult,
            PublishResult,
            StatusResult,
            PublishStatus
        )

        class TestAdapter(ChannelAdapter):
            channel_code = "test"
            channel_name = "Test"

            def validate_product(self, product):
                return ValidationResult(is_valid=True, product="")

            def map_attributes(self, product):
                return MappingResult(
                    product=product.get("sku", ""),
                    mapped_data={
                        "sku": product.get("sku"),
                        "name": product.get("title")
                    }
                )

            def generate_payload(self, products):
                return {}

            def publish(self, products):
                return PublishResult(success=True)

            def get_status(self, job_id):
                return StatusResult(job_id=job_id, status=PublishStatus.COMPLETED)

            def handle_rate_limiting(self, response=None):
                pass

        adapter = TestAdapter()

        products = [
            {"sku": "SKU-001", "title": "Product 1"},
            {"sku": "SKU-002", "title": "Product 2"}
        ]

        results = adapter.map_products(products)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].mapped_data["sku"], "SKU-001")
        self.assertEqual(results[1].mapped_data["sku"], "SKU-002")


class TestChannelAdapterConfig(unittest.TestCase):
    """Test cases for channel adapter configuration."""

    def test_get_config_with_no_channel(self):
        """Test config retrieval when no channel document."""
        from frappe_pim.pim.channels.base import (
            ChannelAdapter,
            ValidationResult,
            MappingResult,
            PublishResult,
            StatusResult,
            PublishStatus
        )

        class TestAdapter(ChannelAdapter):
            channel_code = "test"
            channel_name = "Test"

            def validate_product(self, product):
                return ValidationResult(is_valid=True, product="")

            def map_attributes(self, product):
                return MappingResult(product="", mapped_data={})

            def generate_payload(self, products):
                return {}

            def publish(self, products):
                return PublishResult(success=True)

            def get_status(self, job_id):
                return StatusResult(job_id=job_id, status=PublishStatus.COMPLETED)

            def handle_rate_limiting(self, response=None):
                pass

        adapter = TestAdapter(channel_doc=None)
        config = adapter.config

        self.assertIsInstance(config, dict)
        self.assertIsNone(config.get("base_url"))
        self.assertEqual(config.get("timeout"), 30)
        self.assertEqual(config.get("batch_size"), 100)


# Allow module import without running tests
if __name__ == "__main__":
    unittest.main()
