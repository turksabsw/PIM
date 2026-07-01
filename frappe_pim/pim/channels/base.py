"""
ChannelAdapter Base Class

Provides the abstract base class for all marketplace channel adapters.
Each marketplace implementation (Amazon, Shopify, WooCommerce, etc.) must
extend this class and implement all abstract methods.

Key Features:
- Abstract methods for validate, map, publish, and status workflows
- Built-in rate limiting with exponential backoff
- Credential encryption and secure storage
- Comprehensive error handling and logging
- Retry logic with configurable policies

Note: frappe imports are deferred to function/method level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Union
import time
import json


# =============================================================================
# Custom Exceptions
# =============================================================================

class ChannelAdapterError(Exception):
    """Base exception for all channel adapter errors"""

    def __init__(self, message: str, channel: str = None, details: Dict = None):
        self.message = message
        self.channel = channel
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> Dict:
        """Convert exception to dictionary for logging/API responses"""
        return {
            "error": self.__class__.__name__,
            "message": self.message,
            "channel": self.channel,
            "details": self.details,
        }


class ValidationError(ChannelAdapterError):
    """Raised when product validation fails against channel schema"""

    def __init__(self, message: str, channel: str = None,
                 field: str = None, value: Any = None,
                 rule: str = None, details: Dict = None):
        self.field = field
        self.value = value
        self.rule = rule
        details = details or {}
        details.update({
            "field": field,
            "value": str(value) if value is not None else None,
            "rule": rule,
        })
        super().__init__(message, channel, details)


class RateLimitError(ChannelAdapterError):
    """Raised when API rate limit is exceeded"""

    def __init__(self, message: str, channel: str = None,
                 retry_after: int = None, quota_remaining: int = None,
                 details: Dict = None):
        self.retry_after = retry_after  # Seconds to wait
        self.quota_remaining = quota_remaining
        details = details or {}
        details.update({
            "retry_after": retry_after,
            "quota_remaining": quota_remaining,
        })
        super().__init__(message, channel, details)


class AuthenticationError(ChannelAdapterError):
    """Raised when authentication fails"""
    pass


class PublishError(ChannelAdapterError):
    """Raised when product publishing fails"""

    def __init__(self, message: str, channel: str = None,
                 products: List[str] = None, partial_success: bool = False,
                 details: Dict = None):
        self.products = products or []
        self.partial_success = partial_success
        details = details or {}
        details.update({
            "products": products,
            "partial_success": partial_success,
        })
        super().__init__(message, channel, details)


# =============================================================================
# Data Classes
# =============================================================================

class PublishStatus(str, Enum):
    """Status values for publish jobs"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"
    RATE_LIMITED = "rate_limited"
    CANCELLED = "cancelled"


@dataclass
class ValidationResult:
    """Result of product validation against channel schema"""
    is_valid: bool
    product: str
    errors: List[Dict] = field(default_factory=list)
    warnings: List[Dict] = field(default_factory=list)
    channel: str = None
    validated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict:
        return {
            "is_valid": self.is_valid,
            "product": self.product,
            "errors": self.errors,
            "warnings": self.warnings,
            "channel": self.channel,
            "validated_at": self.validated_at.isoformat(),
        }


@dataclass
class MappingResult:
    """Result of attribute mapping to channel format"""
    product: str
    mapped_data: Dict
    unmapped_fields: List[str] = field(default_factory=list)
    channel: str = None

    def to_dict(self) -> Dict:
        return {
            "product": self.product,
            "mapped_data": self.mapped_data,
            "unmapped_fields": self.unmapped_fields,
            "channel": self.channel,
        }


@dataclass
class PublishResult:
    """Result of product publishing operation"""
    success: bool
    job_id: str = None
    status: PublishStatus = PublishStatus.PENDING
    products_submitted: int = 0
    products_succeeded: int = 0
    products_failed: int = 0
    errors: List[Dict] = field(default_factory=list)
    channel: str = None
    submitted_at: datetime = field(default_factory=datetime.now)
    external_id: str = None  # ID in the external system

    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "job_id": self.job_id,
            "status": self.status.value if isinstance(self.status, PublishStatus) else self.status,
            "products_submitted": self.products_submitted,
            "products_succeeded": self.products_succeeded,
            "products_failed": self.products_failed,
            "errors": self.errors,
            "channel": self.channel,
            "submitted_at": self.submitted_at.isoformat(),
            "external_id": self.external_id,
        }


@dataclass
class StatusResult:
    """Result of checking publish job status"""
    job_id: str
    status: PublishStatus
    progress: float = 0.0  # 0.0 to 1.0
    products_processed: int = 0
    products_total: int = 0
    errors: List[Dict] = field(default_factory=list)
    channel: str = None
    last_checked: datetime = field(default_factory=datetime.now)
    completed_at: datetime = None

    def to_dict(self) -> Dict:
        return {
            "job_id": self.job_id,
            "status": self.status.value if isinstance(self.status, PublishStatus) else self.status,
            "progress": self.progress,
            "products_processed": self.products_processed,
            "products_total": self.products_total,
            "errors": self.errors,
            "channel": self.channel,
            "last_checked": self.last_checked.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


@dataclass
class RateLimitState:
    """Tracks rate limit state for a channel"""
    requests_made: int = 0
    requests_limit: int = 100
    window_start: datetime = field(default_factory=datetime.now)
    window_duration: int = 60  # seconds
    retry_after: datetime = None
    last_request: datetime = None
    consecutive_failures: int = 0

    def is_limited(self) -> bool:
        """Check if currently rate limited"""
        if self.retry_after and datetime.now() < self.retry_after:
            return True

        # Reset window if expired
        if datetime.now() > self.window_start + timedelta(seconds=self.window_duration):
            self.requests_made = 0
            self.window_start = datetime.now()
            return False

        return self.requests_made >= self.requests_limit

    def wait_time(self) -> float:
        """Get seconds to wait before next request"""
        if self.retry_after:
            delta = self.retry_after - datetime.now()
            if delta.total_seconds() > 0:
                return delta.total_seconds()

        if self.is_limited():
            window_end = self.window_start + timedelta(seconds=self.window_duration)
            delta = window_end - datetime.now()
            return max(0, delta.total_seconds())

        return 0


# =============================================================================
# Adapter Registry
# =============================================================================

_adapter_registry: Dict[str, type] = {}


def register_adapter(channel_code: str, adapter_class: type) -> None:
    """Register a channel adapter class.

    Args:
        channel_code: Unique identifier for the channel (e.g., 'amazon', 'shopify')
        adapter_class: The adapter class that extends ChannelAdapter
    """
    if not issubclass(adapter_class, ChannelAdapter):
        raise TypeError(f"Adapter class must extend ChannelAdapter: {adapter_class}")
    _adapter_registry[channel_code.lower()] = adapter_class


def get_adapter(channel_code: str, channel_doc: Any = None) -> "ChannelAdapter":
    """Get an adapter instance for a channel.

    Args:
        channel_code: The channel code to get adapter for
        channel_doc: Optional Channel document to initialize adapter with

    Returns:
        ChannelAdapter instance

    Raises:
        ValueError: If no adapter is registered for the channel code
    """
    import frappe

    code = channel_code.lower()

    if code not in _adapter_registry:
        frappe.throw(
            frappe._("No adapter registered for channel: {0}").format(channel_code),
            title=frappe._("Adapter Not Found")
        )

    adapter_class = _adapter_registry[code]
    return adapter_class(channel_doc)


def list_adapters() -> List[str]:
    """Get list of all registered adapter codes.

    Returns:
        List of channel codes with registered adapters
    """
    return list(_adapter_registry.keys())


# =============================================================================
# Channel Adapter Base Class
# =============================================================================

class ChannelAdapter(ABC):
    """Abstract base class for marketplace channel adapters.

    All marketplace adapters must extend this class and implement
    the abstract methods: validate_product, map_attributes,
    generate_payload, publish, get_status, handle_rate_limiting.

    Attributes:
        channel: The Channel document this adapter is for
        channel_code: Unique identifier for this channel type
        rate_limit_state: Current rate limiting state
        credentials: Decrypted API credentials
        config: Channel-specific configuration
    """

    # Class-level attributes to be overridden by subclasses
    channel_code: str = None  # e.g., 'amazon', 'shopify'
    channel_name: str = None  # e.g., 'Amazon', 'Shopify'

    # Default rate limit settings (can be overridden)
    default_requests_per_minute: int = 60
    default_requests_per_second: float = 2.0
    max_retry_attempts: int = 3
    base_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 60.0

    def __init__(self, channel_doc: Any = None):
        """Initialize the adapter.

        Args:
            channel_doc: The Channel Frappe document, or None to use defaults
        """
        self.channel = channel_doc
        self._credentials = None
        self._config = None
        self._rate_limit_state = None
        self._session = None

    @property
    def credentials(self) -> Dict:
        """Get decrypted API credentials.

        Returns:
            Dictionary of API credentials
        """
        if self._credentials is None:
            self._credentials = self._get_credentials()
        return self._credentials

    @property
    def config(self) -> Dict:
        """Get channel-specific configuration.

        Returns:
            Dictionary of configuration settings
        """
        if self._config is None:
            self._config = self._get_config()
        return self._config

    @property
    def rate_limit_state(self) -> RateLimitState:
        """Get current rate limit state.

        Returns:
            RateLimitState instance
        """
        if self._rate_limit_state is None:
            self._rate_limit_state = self._init_rate_limit_state()
        return self._rate_limit_state

    # =========================================================================
    # Abstract Methods - Must be implemented by subclasses
    # =========================================================================

    @abstractmethod
    def validate_product(self, product: Dict) -> ValidationResult:
        """Validate a product against the channel's schema and requirements.

        Checks that all required fields are present, values are within
        allowed ranges, and product data conforms to channel rules.

        Args:
            product: Product data dictionary

        Returns:
            ValidationResult with validation status and any errors/warnings

        Example:
            result = adapter.validate_product({
                "sku": "ABC123",
                "title": "Sample Product",
                "price": 29.99
            })
            if not result.is_valid:
                for error in result.errors:
                    print(f"Field {error['field']}: {error['message']}")
        """
        pass

    @abstractmethod
    def map_attributes(self, product: Dict) -> MappingResult:
        """Map internal product attributes to channel-specific format.

        Converts PIM product fields to the format expected by the channel's
        API. Handles attribute name mapping, value transformations, and
        format conversions.

        Args:
            product: Product data dictionary in PIM format

        Returns:
            MappingResult with mapped data and any unmapped fields

        Example:
            result = adapter.map_attributes(pim_product)
            channel_data = result.mapped_data
        """
        pass

    @abstractmethod
    def generate_payload(self, products: List[Dict]) -> Dict:
        """Generate the complete payload for publishing products.

        Takes validated and mapped product data and generates the final
        payload format required by the channel's API (JSON, XML, etc.).

        Args:
            products: List of mapped product data dictionaries

        Returns:
            Dictionary with the complete payload ready for publishing

        Example:
            payload = adapter.generate_payload(mapped_products)
            # payload might include envelope, headers, batch info, etc.
        """
        pass

    @abstractmethod
    def publish(self, products: List[Dict]) -> PublishResult:
        """Publish products to the channel.

        Handles the complete publishing workflow including validation,
        mapping, payload generation, and API submission. Implements
        retry logic and rate limiting.

        Args:
            products: List of product data dictionaries in PIM format

        Returns:
            PublishResult with job status and any errors

        Raises:
            RateLimitError: If rate limit is exceeded and cannot retry
            AuthenticationError: If authentication fails
            PublishError: If publishing fails

        Example:
            result = adapter.publish(products)
            if result.success:
                print(f"Published {result.products_succeeded} products")
            else:
                for error in result.errors:
                    print(f"Error: {error['message']}")
        """
        pass

    @abstractmethod
    def get_status(self, job_id: str) -> StatusResult:
        """Check the status of a publish job.

        Many channel APIs process submissions asynchronously. This method
        retrieves the current status of a previously submitted job.

        Args:
            job_id: The job ID returned from publish()

        Returns:
            StatusResult with current job status and progress

        Example:
            status = adapter.get_status(publish_result.job_id)
            if status.status == PublishStatus.COMPLETED:
                print(f"All {status.products_total} products processed")
        """
        pass

    @abstractmethod
    def handle_rate_limiting(self, response: Any = None) -> None:
        """Handle rate limiting for the channel API.

        Parses rate limit headers/responses and updates internal state.
        Implements waiting/backoff when limits are reached.

        Args:
            response: Optional API response to parse for rate limit info

        Raises:
            RateLimitError: If rate limit is exceeded and max retries reached

        Example:
            try:
                response = self._make_api_call()
                self.handle_rate_limiting(response)
            except RateLimitError as e:
                frappe.log_error(f"Rate limited, retry after {e.retry_after}s")
        """
        pass

    # =========================================================================
    # Protected Helper Methods
    # =========================================================================

    def _get_credentials(self) -> Dict:
        """Get decrypted API credentials from channel document.

        Returns:
            Dictionary of credentials (api_key, api_secret, etc.)
        """
        import frappe

        credentials = {}

        if not self.channel:
            return credentials

        # Get api_key using Frappe's password field decryption
        if hasattr(self.channel, 'api_key') and self.channel.api_key:
            try:
                credentials['api_key'] = self.channel.get_password('api_key')
            except Exception:
                credentials['api_key'] = self.channel.api_key

        # Get api_secret if it exists
        if hasattr(self.channel, 'api_secret') and self.channel.api_secret:
            try:
                credentials['api_secret'] = self.channel.get_password('api_secret')
            except Exception:
                credentials['api_secret'] = self.channel.api_secret

        # Get access_token if it exists
        if hasattr(self.channel, 'access_token') and self.channel.access_token:
            try:
                credentials['access_token'] = self.channel.get_password('access_token')
            except Exception:
                credentials['access_token'] = self.channel.access_token

        # Get refresh_token if it exists
        if hasattr(self.channel, 'refresh_token') and self.channel.refresh_token:
            try:
                credentials['refresh_token'] = self.channel.get_password('refresh_token')
            except Exception:
                credentials['refresh_token'] = self.channel.refresh_token

        return credentials

    def _get_config(self) -> Dict:
        """Get channel-specific configuration.

        Returns:
            Dictionary of configuration settings
        """
        config = {
            'base_url': getattr(self.channel, 'base_url', None) if self.channel else None,
            'timeout': getattr(self.channel, 'timeout', 30) if self.channel else 30,
            'batch_size': getattr(self.channel, 'batch_size', 100) if self.channel else 100,
        }

        # Parse custom_settings JSON if present
        if self.channel and hasattr(self.channel, 'custom_settings'):
            try:
                custom = self.channel.custom_settings
                if custom:
                    if isinstance(custom, str):
                        custom = json.loads(custom)
                    config.update(custom)
            except (json.JSONDecodeError, TypeError):
                pass

        return config

    def _init_rate_limit_state(self) -> RateLimitState:
        """Initialize rate limit state from channel settings.

        Returns:
            RateLimitState instance
        """
        return RateLimitState(
            requests_limit=int(self.default_requests_per_minute),
            window_duration=60,
        )

    def _wait_for_rate_limit(self) -> None:
        """Wait if rate limited, with exponential backoff.

        Raises:
            RateLimitError: If max wait time exceeded
        """
        wait_time = self.rate_limit_state.wait_time()

        if wait_time > 0:
            if wait_time > self.max_backoff_seconds:
                raise RateLimitError(
                    f"Rate limit wait time ({wait_time}s) exceeds maximum ({self.max_backoff_seconds}s)",
                    channel=self.channel_code,
                    retry_after=int(wait_time),
                )
            time.sleep(wait_time)

    def _record_request(self) -> None:
        """Record that a request was made for rate limiting."""
        self.rate_limit_state.requests_made += 1
        self.rate_limit_state.last_request = datetime.now()

    def _calculate_backoff(self, attempt: int) -> float:
        """Calculate exponential backoff time.

        Args:
            attempt: Current attempt number (0-indexed)

        Returns:
            Seconds to wait before retry
        """
        backoff = self.base_backoff_seconds * (2 ** attempt)
        return min(backoff, self.max_backoff_seconds)

    def _log_publish_event(self, event_type: str, data: Dict) -> None:
        """Log a publish event for auditing.

        Args:
            event_type: Type of event (submit, success, error, etc.)
            data: Event data to log
        """
        import frappe

        try:
            log_data = {
                "channel": self.channel.name if self.channel else self.channel_code,
                "channel_code": self.channel_code,
                "event_type": event_type,
                "data": json.dumps(data, default=str),
                "timestamp": datetime.now().isoformat(),
            }

            frappe.log_error(
                message=json.dumps(log_data, indent=2),
                title=f"PIM Channel Publish - {event_type}"
            )
        except Exception:
            pass  # Don't fail on logging errors

    def _get_auth_headers(self) -> Dict:
        """Build authentication headers for API requests.

        Returns:
            Dictionary of HTTP headers
        """
        headers = {}

        if self.credentials.get('api_key'):
            headers['Authorization'] = f"Bearer {self.credentials['api_key']}"

        return headers

    def _make_request(self, method: str, url: str, **kwargs) -> Any:
        """Make an HTTP request with rate limiting and retry logic.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Request URL
            **kwargs: Additional arguments passed to requests

        Returns:
            Response object

        Raises:
            RateLimitError: If rate limit exceeded after retries
            AuthenticationError: If authentication fails
        """
        import requests

        # Wait if rate limited
        self._wait_for_rate_limit()

        # Set defaults
        if 'timeout' not in kwargs:
            kwargs['timeout'] = self.config.get('timeout', 30)

        if 'headers' not in kwargs:
            kwargs['headers'] = {}
        kwargs['headers'].update(self._get_auth_headers())

        last_error = None

        for attempt in range(self.max_retry_attempts):
            try:
                self._record_request()
                response = requests.request(method, url, **kwargs)

                # Handle rate limiting from response
                self.handle_rate_limiting(response)

                # Check for auth errors
                if response.status_code in (401, 403):
                    raise AuthenticationError(
                        f"Authentication failed: HTTP {response.status_code}",
                        channel=self.channel_code,
                    )

                return response

            except RateLimitError:
                # Wait and retry for rate limits
                backoff = self._calculate_backoff(attempt)
                time.sleep(backoff)
                self.rate_limit_state.consecutive_failures += 1
                last_error = RateLimitError(
                    "Rate limit exceeded after retries",
                    channel=self.channel_code,
                )

            except requests.exceptions.RequestException as e:
                last_error = e
                if attempt < self.max_retry_attempts - 1:
                    backoff = self._calculate_backoff(attempt)
                    time.sleep(backoff)

        # All retries exhausted
        if isinstance(last_error, RateLimitError):
            raise last_error
        raise PublishError(
            f"Request failed after {self.max_retry_attempts} attempts: {last_error}",
            channel=self.channel_code,
        )

    # =========================================================================
    # Convenience Methods
    # =========================================================================

    def validate_products(self, products: List[Dict]) -> List[ValidationResult]:
        """Validate multiple products.

        Args:
            products: List of product data dictionaries

        Returns:
            List of ValidationResult objects
        """
        return [self.validate_product(p) for p in products]

    def map_products(self, products: List[Dict]) -> List[MappingResult]:
        """Map multiple products to channel format.

        Args:
            products: List of product data dictionaries

        Returns:
            List of MappingResult objects
        """
        return [self.map_attributes(p) for p in products]

    def is_connected(self) -> bool:
        """Check if channel is connected and authenticated.

        Returns:
            True if connected, False otherwise
        """
        if not self.channel:
            return False

        return getattr(self.channel, 'connection_status', None) == 'Connected'

    def test_connection(self) -> Dict:
        """Test the connection to this channel.

        Returns:
            Dictionary with connection status and any errors
        """
        import frappe

        try:
            if not self.config.get('base_url'):
                return {
                    "success": False,
                    "message": frappe._("Base URL is not configured"),
                }

            response = self._make_request('GET', self.config['base_url'])

            if response.status_code == 200:
                return {
                    "success": True,
                    "message": frappe._("Connection successful"),
                }
            else:
                return {
                    "success": False,
                    "message": f"HTTP {response.status_code}: {response.reason}",
                }

        except AuthenticationError as e:
            return {
                "success": False,
                "message": str(e.message),
            }
        except Exception as e:
            return {
                "success": False,
                "message": str(e),
            }

    def __repr__(self) -> str:
        channel_name = self.channel.name if self.channel else 'No Channel'
        return f"<{self.__class__.__name__}({channel_name})>"
