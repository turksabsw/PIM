"""GDSN Data Pool Synchronization Service

This module provides services for synchronizing product data with the Global Data
Synchronization Network (GDSN) through certified data pools. GDSN is the worldwide
standard for product data exchange between trading partners.

The service supports:
- CIN (Catalogue Item Notification) - Publishing product data TO data pools
- CIP (Catalogue Item Publication) - Receiving subscribed product data FROM data pools
- RCI (Registry Catalogue Item) - Querying the GS1 Global Registry
- Subscription management - Subscribe to receive product data from trading partners
- Data pool connection management - Configure and test data pool connections

Key Concepts:
- Data Pool: A certified GDSN node that receives and distributes product data
- Information Provider (IP): The party that publishes product data (brand owner)
- Data Recipient (DR): The party that subscribes to receive product data (retailer)
- GLN: Global Location Number - identifies parties in GDSN
- GTIN: Global Trade Item Number - identifies products

Message Flow:
1. Information Provider publishes CIN to their source data pool
2. Data Recipient sends subscription request to their data pool
3. GS1 Global Registry matches subscriptions
4. Source data pool sends CIP to recipient's data pool
5. Recipient's data pool delivers product data

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


# =============================================================================
# Constants and Enums
# =============================================================================

class GDSNMessageType(Enum):
    """GDSN message types."""
    CIN = "CatalogueItemNotification"
    CIP = "CatalogueItemPublication"
    CIRR = "CatalogueItemRegistrationResponse"
    CIS = "CatalogueItemSubscription"
    CIHR = "CatalogueItemHierarchicalResponse"
    RCI = "RegistryCatalogueItem"


class GDSNDocumentCommand(Enum):
    """GDSN document command types."""
    ADD = "ADD"
    CHANGE_BY_REFRESH = "CHANGE_BY_REFRESH"
    DELETE = "DELETE"
    CORRECT = "CORRECT"


class GDSNSyncStatus(Enum):
    """Sync status states."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PUBLISHED = "published"
    SUBSCRIBED = "subscribed"
    RECEIVED = "received"
    FAILED = "failed"
    REJECTED = "rejected"


class GDSNCatalogueItemState(Enum):
    """Catalogue item state codes."""
    IN_PROGRESS = "IN_PROGRESS"
    FINAL = "FINAL"
    DISCONTINUED = "DISCONTINUED"
    WITHDRAWN = "WITHDRAWN"


# Common GDSN Data Pools (for reference)
GDSN_DATA_POOLS = {
    "1SYNC": {
        "name": "1SYNC",
        "gln": "0614141000005",
        "endpoint": "https://api.1sync.org/gdsn",
        "regions": ["US", "CA"]
    },
    "SINFOS": {
        "name": "SA2 Worldsync (SINFOS)",
        "gln": "4000001000004",
        "endpoint": "https://sinfos.gs1.de/ws",
        "regions": ["DE", "AT", "CH"]
    },
    "TIKS": {
        "name": "Tiks (Turkey)",
        "gln": "8699999999990",
        "endpoint": "https://tiks.gs1tr.org/ws",
        "regions": ["TR"]
    },
    "GS1NET": {
        "name": "GS1net",
        "gln": "5060000000003",
        "endpoint": "https://gs1net.org/api/gdsn",
        "regions": ["GB", "IE"]
    },
    "AGILOG": {
        "name": "Agilog",
        "gln": "5400000000009",
        "endpoint": "https://agilog.com/gdsn/ws",
        "regions": ["BE", "NL", "LU"]
    }
}


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class DataPoolConfig:
    """Configuration for a GDSN data pool connection."""
    name: str
    gln: str
    endpoint_url: str
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    certificate_path: Optional[str] = None
    private_key_path: Optional[str] = None
    timeout: int = 60
    max_retries: int = 3
    is_test_environment: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (excluding secrets)."""
        return {
            "name": self.name,
            "gln": self.gln,
            "endpoint_url": self.endpoint_url,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "is_test_environment": self.is_test_environment,
        }


@dataclass
class GDSNSubscription:
    """Represents a GDSN subscription."""
    subscriber_gln: str
    publisher_gln: str
    gtin: Optional[str] = None
    gpc_category: Optional[str] = None
    target_market: str = "001"  # Global
    subscription_id: Optional[str] = None
    status: GDSNSyncStatus = GDSNSyncStatus.PENDING
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class SyncResult:
    """Result of a GDSN sync operation."""
    success: bool
    message_type: GDSNMessageType
    message_id: str
    status: GDSNSyncStatus
    products_count: int = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    response_data: Optional[Dict[str, Any]] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "message_type": self.message_type.value,
            "message_id": self.message_id,
            "status": self.status.value,
            "products_count": self.products_count,
            "errors": self.errors,
            "warnings": self.warnings,
            "response_data": self.response_data,
            "timestamp": self.timestamp.isoformat(),
        }


# =============================================================================
# GDSN Data Pool Client
# =============================================================================

class GDSNDataPoolClient:
    """Client for communicating with a GDSN data pool.

    This client handles the low-level communication with GDSN data pools,
    including authentication, message formatting, and error handling.

    Attributes:
        config: Data pool configuration
        session: HTTP session for connection reuse
    """

    def __init__(self, config: DataPoolConfig):
        """Initialize the data pool client.

        Args:
            config: Data pool configuration
        """
        self.config = config
        self._session = None

    def _get_session(self):
        """Get or create HTTP session."""
        import requests

        if self._session is None:
            self._session = requests.Session()

            # Configure authentication
            if self.config.certificate_path and self.config.private_key_path:
                self._session.cert = (
                    self.config.certificate_path,
                    self.config.private_key_path
                )

            # Set default headers
            self._session.headers.update({
                "Content-Type": "application/xml",
                "Accept": "application/xml",
                "User-Agent": "Frappe-PIM-GDSN/1.0"
            })

            # API key authentication if available
            if self.config.api_key:
                self._session.headers["X-API-Key"] = self.config.api_key

        return self._session

    def close(self):
        """Close the HTTP session."""
        if self._session:
            self._session.close()
            self._session = None

    def test_connection(self) -> Tuple[bool, str]:
        """Test the connection to the data pool.

        Returns:
            Tuple of (success, message)
        """
        import requests

        try:
            session = self._get_session()
            response = session.get(
                f"{self.config.endpoint_url}/health",
                timeout=self.config.timeout
            )

            if response.status_code == 200:
                return True, "Connection successful"
            else:
                return False, f"Unexpected status code: {response.status_code}"

        except requests.exceptions.ConnectionError as e:
            return False, f"Connection failed: {str(e)}"
        except requests.exceptions.Timeout:
            return False, "Connection timed out"
        except Exception as e:
            return False, f"Connection error: {str(e)}"

    def send_cin(
        self,
        xml_content: str,
        message_id: Optional[str] = None
    ) -> SyncResult:
        """Send a Catalogue Item Notification (CIN) to the data pool.

        Args:
            xml_content: The CIN XML document
            message_id: Optional message ID (generated if not provided)

        Returns:
            SyncResult with the operation outcome
        """
        import requests

        message_id = message_id or str(uuid.uuid4())

        try:
            session = self._get_session()

            # Add message ID to headers
            headers = {"X-Message-ID": message_id}

            response = session.post(
                f"{self.config.endpoint_url}/cin",
                data=xml_content.encode("utf-8"),
                headers=headers,
                timeout=self.config.timeout
            )

            if response.status_code in (200, 201, 202):
                return SyncResult(
                    success=True,
                    message_type=GDSNMessageType.CIN,
                    message_id=message_id,
                    status=GDSNSyncStatus.PUBLISHED,
                    response_data=self._parse_response(response),
                )
            else:
                error_msg = self._extract_error(response)
                return SyncResult(
                    success=False,
                    message_type=GDSNMessageType.CIN,
                    message_id=message_id,
                    status=GDSNSyncStatus.FAILED,
                    errors=[error_msg],
                    response_data={"status_code": response.status_code},
                )

        except requests.exceptions.Timeout:
            return SyncResult(
                success=False,
                message_type=GDSNMessageType.CIN,
                message_id=message_id,
                status=GDSNSyncStatus.FAILED,
                errors=["Request timed out"],
            )
        except Exception as e:
            return SyncResult(
                success=False,
                message_type=GDSNMessageType.CIN,
                message_id=message_id,
                status=GDSNSyncStatus.FAILED,
                errors=[f"Request failed: {str(e)}"],
            )

    def send_subscription(
        self,
        subscription: GDSNSubscription,
        message_id: Optional[str] = None
    ) -> SyncResult:
        """Send a subscription request to the data pool.

        Args:
            subscription: The subscription details
            message_id: Optional message ID

        Returns:
            SyncResult with the operation outcome
        """
        import requests

        message_id = message_id or str(uuid.uuid4())

        try:
            # Build subscription XML
            xml_content = self._build_subscription_xml(subscription)

            session = self._get_session()
            headers = {"X-Message-ID": message_id}

            response = session.post(
                f"{self.config.endpoint_url}/subscription",
                data=xml_content.encode("utf-8"),
                headers=headers,
                timeout=self.config.timeout
            )

            if response.status_code in (200, 201, 202):
                return SyncResult(
                    success=True,
                    message_type=GDSNMessageType.CIS,
                    message_id=message_id,
                    status=GDSNSyncStatus.SUBSCRIBED,
                    response_data=self._parse_response(response),
                )
            else:
                error_msg = self._extract_error(response)
                return SyncResult(
                    success=False,
                    message_type=GDSNMessageType.CIS,
                    message_id=message_id,
                    status=GDSNSyncStatus.FAILED,
                    errors=[error_msg],
                )

        except Exception as e:
            return SyncResult(
                success=False,
                message_type=GDSNMessageType.CIS,
                message_id=message_id,
                status=GDSNSyncStatus.FAILED,
                errors=[f"Subscription request failed: {str(e)}"],
            )

    def poll_messages(self) -> List[Dict[str, Any]]:
        """Poll for incoming messages from the data pool.

        Returns:
            List of received messages
        """
        import requests

        try:
            session = self._get_session()
            response = session.get(
                f"{self.config.endpoint_url}/messages",
                timeout=self.config.timeout
            )

            if response.status_code == 200:
                return self._parse_messages(response)
            else:
                return []

        except Exception:
            return []

    def acknowledge_message(self, message_id: str) -> bool:
        """Acknowledge receipt of a message.

        Args:
            message_id: The message ID to acknowledge

        Returns:
            True if acknowledged successfully
        """
        import requests

        try:
            session = self._get_session()
            response = session.post(
                f"{self.config.endpoint_url}/messages/{message_id}/ack",
                timeout=self.config.timeout
            )
            return response.status_code in (200, 204)

        except Exception:
            return False

    def _build_subscription_xml(self, subscription: GDSNSubscription) -> str:
        """Build subscription XML message.

        Args:
            subscription: Subscription details

        Returns:
            XML string
        """
        try:
            from lxml import etree
        except ImportError:
            raise ImportError(
                "lxml is required for GDSN sync. Install with: pip install lxml"
            )

        # CIS namespace
        cis_ns = "urn:gs1:gdsn:catalogue_item_subscription:xsd:3"
        gdsn_ns = "urn:gs1:gdsn:gdsn_common:xsd:3"
        sh_ns = "urn:gs1:shared:shared_common:xsd:3"

        nsmap = {
            None: cis_ns,
            "gdsn": gdsn_ns,
            "sh": sh_ns
        }

        root = etree.Element("catalogueItemSubscription", nsmap=nsmap)

        # Subscriber GLN
        subscriber = etree.SubElement(root, "subscriber")
        gln = etree.SubElement(subscriber, f"{{{sh_ns}}}gln")
        gln.text = subscription.subscriber_gln

        # Publisher GLN (data source)
        publisher = etree.SubElement(root, "dataSource")
        gln = etree.SubElement(publisher, f"{{{sh_ns}}}gln")
        gln.text = subscription.publisher_gln

        # GTIN filter (if specified)
        if subscription.gtin:
            gtin_filter = etree.SubElement(root, "gtin")
            gtin_filter.text = subscription.gtin

        # GPC category filter (if specified)
        if subscription.gpc_category:
            gpc = etree.SubElement(root, "gpcCategoryCode")
            gpc.text = subscription.gpc_category

        # Target market
        target = etree.SubElement(root, f"{{{gdsn_ns}}}targetMarket")
        target_code = etree.SubElement(target, f"{{{gdsn_ns}}}targetMarketCountryCode")
        target_code.text = subscription.target_market

        return etree.tostring(root, encoding="unicode", pretty_print=True)

    def _parse_response(self, response) -> Dict[str, Any]:
        """Parse response from data pool.

        Args:
            response: HTTP response object

        Returns:
            Parsed response data
        """
        try:
            from lxml import etree

            doc = etree.fromstring(response.content)

            # Extract key response elements
            result = {
                "status_code": response.status_code,
                "content_type": response.headers.get("Content-Type"),
            }

            # Try to extract message ID from response
            msg_id = doc.find(".//{*}messageId")
            if msg_id is not None and msg_id.text:
                result["message_id"] = msg_id.text

            # Try to extract status
            status = doc.find(".//{*}status")
            if status is not None and status.text:
                result["status"] = status.text

            return result

        except Exception:
            return {
                "status_code": response.status_code,
                "raw_content": response.text[:500] if response.text else None
            }

    def _parse_messages(self, response) -> List[Dict[str, Any]]:
        """Parse incoming messages from data pool.

        Args:
            response: HTTP response object

        Returns:
            List of message dictionaries
        """
        try:
            from lxml import etree

            messages = []
            doc = etree.fromstring(response.content)

            for msg in doc.findall(".//{*}message"):
                msg_data = {
                    "message_id": msg.get("id"),
                    "message_type": msg.get("type"),
                    "received_at": datetime.utcnow().isoformat(),
                }

                # Extract XML content
                content = msg.find("{*}content")
                if content is not None:
                    msg_data["content"] = etree.tostring(
                        content,
                        encoding="unicode"
                    )

                messages.append(msg_data)

            return messages

        except Exception:
            return []

    def _extract_error(self, response) -> str:
        """Extract error message from response.

        Args:
            response: HTTP response object

        Returns:
            Error message string
        """
        try:
            from lxml import etree

            doc = etree.fromstring(response.content)
            error = doc.find(".//{*}error")
            if error is not None and error.text:
                return error.text

            # Try to find fault message
            fault = doc.find(".//{*}faultstring")
            if fault is not None and fault.text:
                return fault.text

        except Exception:
            pass

        return f"HTTP {response.status_code}: {response.text[:200] if response.text else 'Unknown error'}"


# =============================================================================
# GDSN Sync Service
# =============================================================================

class GDSNSyncService:
    """High-level service for GDSN synchronization operations.

    This service provides business-level operations for GDSN sync,
    including product publication, subscription management, and
    incoming message processing.

    Attributes:
        client: Data pool client instance
        gln_information_provider: GLN of the information provider
        gln_brand_owner: GLN of the brand owner
    """

    def __init__(
        self,
        data_pool_config: Optional[DataPoolConfig] = None,
        gln_information_provider: Optional[str] = None,
        gln_brand_owner: Optional[str] = None
    ):
        """Initialize the GDSN sync service.

        Args:
            data_pool_config: Data pool configuration (loaded from settings if not provided)
            gln_information_provider: Information provider GLN
            gln_brand_owner: Brand owner GLN
        """
        self._config = data_pool_config
        self._client = None
        self.gln_information_provider = gln_information_provider
        self.gln_brand_owner = gln_brand_owner

    @property
    def client(self) -> GDSNDataPoolClient:
        """Get the data pool client (lazy initialization)."""
        if self._client is None:
            config = self._config or self._load_data_pool_config()
            self._client = GDSNDataPoolClient(config)
        return self._client

    def _load_data_pool_config(self) -> DataPoolConfig:
        """Load data pool configuration from PIM Settings.

        Returns:
            DataPoolConfig instance

        Raises:
            ValueError: If GDSN is not configured
        """
        import frappe

        settings = _get_pim_settings()

        if not settings.get("gdsn_data_pool_gln"):
            raise ValueError(
                "GDSN data pool not configured. Please configure in PIM Settings."
            )

        return DataPoolConfig(
            name=settings.get("gdsn_data_pool_name", "GDSN Data Pool"),
            gln=settings.get("gdsn_data_pool_gln"),
            endpoint_url=settings.get("gdsn_endpoint_url", ""),
            api_key=settings.get("gdsn_api_key"),
            timeout=settings.get("gdsn_timeout", 60),
            max_retries=settings.get("gdsn_max_retries", 3),
            is_test_environment=settings.get("gdsn_test_mode", False),
        )

    def _load_gln_settings(self):
        """Load GLN settings if not already set."""
        if not self.gln_information_provider or not self.gln_brand_owner:
            settings = _get_pim_settings()
            self.gln_information_provider = (
                self.gln_information_provider or
                settings.get("gln_information_provider") or
                settings.get("company_gln")
            )
            self.gln_brand_owner = (
                self.gln_brand_owner or
                settings.get("gln_brand_owner") or
                self.gln_information_provider
            )

    def publish_products(
        self,
        product_names: List[str],
        target_market: str = "001",
        document_command: GDSNDocumentCommand = GDSNDocumentCommand.ADD,
        data_recipient_gln: Optional[str] = None
    ) -> SyncResult:
        """Publish products to the GDSN data pool.

        Generates a CIN message and sends it to the configured data pool.

        Args:
            product_names: List of Product Variant/Master names to publish
            target_market: ISO 3166-1 numeric country code
            document_command: Document command type
            data_recipient_gln: Specific recipient GLN (optional)

        Returns:
            SyncResult with operation outcome
        """
        import frappe

        self._load_gln_settings()

        if not product_names:
            return SyncResult(
                success=False,
                message_type=GDSNMessageType.CIN,
                message_id=str(uuid.uuid4()),
                status=GDSNSyncStatus.FAILED,
                errors=["No products specified for publication"]
            )

        try:
            # Generate CIN XML
            from frappe_pim.pim.export.gs1_xml import export_catalogue_item_notification

            xml_content = export_catalogue_item_notification(
                products=product_names,
                gln_brand_owner=self.gln_brand_owner,
                gln_information_provider=self.gln_information_provider,
                gln_data_recipient=data_recipient_gln,
                target_market=target_market,
                document_command=document_command.value,
                save_file=False
            )

            # Send to data pool
            result = self.client.send_cin(xml_content)
            result.products_count = len(product_names)

            # Log the sync operation
            if result.success:
                _log_sync_operation(
                    operation_type="publish",
                    message_type=GDSNMessageType.CIN.value,
                    message_id=result.message_id,
                    products=product_names,
                    status="success",
                    target_market=target_market
                )

                # Update product sync status
                for product_name in product_names:
                    _update_product_gdsn_status(
                        product_name,
                        GDSNSyncStatus.PUBLISHED,
                        result.message_id
                    )
            else:
                _log_sync_operation(
                    operation_type="publish",
                    message_type=GDSNMessageType.CIN.value,
                    message_id=result.message_id,
                    products=product_names,
                    status="failed",
                    errors=result.errors
                )

            return result

        except Exception as e:
            error_msg = f"Failed to publish products: {str(e)}"
            frappe.log_error(
                message=error_msg,
                title="GDSN Sync Error"
            )
            return SyncResult(
                success=False,
                message_type=GDSNMessageType.CIN,
                message_id=str(uuid.uuid4()),
                status=GDSNSyncStatus.FAILED,
                errors=[error_msg]
            )

    def subscribe_to_publisher(
        self,
        publisher_gln: str,
        gtin: Optional[str] = None,
        gpc_category: Optional[str] = None,
        target_market: str = "001"
    ) -> SyncResult:
        """Subscribe to receive product data from a publisher.

        Args:
            publisher_gln: GLN of the data publisher
            gtin: Specific GTIN to subscribe to (optional)
            gpc_category: GPC category to subscribe to (optional)
            target_market: Target market code

        Returns:
            SyncResult with operation outcome
        """
        import frappe

        self._load_gln_settings()

        if not publisher_gln:
            return SyncResult(
                success=False,
                message_type=GDSNMessageType.CIS,
                message_id=str(uuid.uuid4()),
                status=GDSNSyncStatus.FAILED,
                errors=["Publisher GLN is required"]
            )

        try:
            subscription = GDSNSubscription(
                subscriber_gln=self.gln_information_provider,
                publisher_gln=publisher_gln,
                gtin=gtin,
                gpc_category=gpc_category,
                target_market=target_market,
            )

            result = self.client.send_subscription(subscription)

            if result.success:
                _log_sync_operation(
                    operation_type="subscribe",
                    message_type=GDSNMessageType.CIS.value,
                    message_id=result.message_id,
                    status="success",
                    publisher_gln=publisher_gln,
                    gtin=gtin,
                    gpc_category=gpc_category
                )

                # Store subscription record
                _create_subscription_record(subscription, result.message_id)
            else:
                _log_sync_operation(
                    operation_type="subscribe",
                    message_type=GDSNMessageType.CIS.value,
                    message_id=result.message_id,
                    status="failed",
                    errors=result.errors
                )

            return result

        except Exception as e:
            error_msg = f"Failed to create subscription: {str(e)}"
            frappe.log_error(
                message=error_msg,
                title="GDSN Sync Error"
            )
            return SyncResult(
                success=False,
                message_type=GDSNMessageType.CIS,
                message_id=str(uuid.uuid4()),
                status=GDSNSyncStatus.FAILED,
                errors=[error_msg]
            )

    def process_incoming_messages(self) -> List[SyncResult]:
        """Poll and process incoming messages from the data pool.

        Returns:
            List of SyncResult for each processed message
        """
        import frappe

        results = []

        try:
            messages = self.client.poll_messages()

            for msg in messages:
                result = self._process_message(msg)
                results.append(result)

                # Acknowledge successful processing
                if result.success and msg.get("message_id"):
                    self.client.acknowledge_message(msg["message_id"])

        except Exception as e:
            frappe.log_error(
                message=f"Error processing incoming GDSN messages: {str(e)}",
                title="GDSN Sync Error"
            )

        return results

    def _process_message(self, message: Dict[str, Any]) -> SyncResult:
        """Process a single incoming message.

        Args:
            message: Message dictionary from data pool

        Returns:
            SyncResult for the processing operation
        """
        import frappe

        message_type = message.get("message_type", "")
        message_id = message.get("message_id", str(uuid.uuid4()))
        content = message.get("content", "")

        try:
            if message_type == "CIP" or "CatalogueItemPublication" in message_type:
                return self._process_cip(content, message_id)
            elif message_type == "CIRR" or "RegistrationResponse" in message_type:
                return self._process_cirr(content, message_id)
            else:
                return SyncResult(
                    success=False,
                    message_type=GDSNMessageType.CIP,
                    message_id=message_id,
                    status=GDSNSyncStatus.FAILED,
                    warnings=[f"Unknown message type: {message_type}"]
                )

        except Exception as e:
            frappe.log_error(
                message=f"Error processing message {message_id}: {str(e)}",
                title="GDSN Message Processing Error"
            )
            return SyncResult(
                success=False,
                message_type=GDSNMessageType.CIP,
                message_id=message_id,
                status=GDSNSyncStatus.FAILED,
                errors=[f"Processing error: {str(e)}"]
            )

    def _process_cip(self, xml_content: str, message_id: str) -> SyncResult:
        """Process a Catalogue Item Publication (CIP) message.

        Extracts product data from the CIP and creates/updates local products.

        Args:
            xml_content: CIP XML content
            message_id: Message identifier

        Returns:
            SyncResult for the processing operation
        """
        try:
            from lxml import etree
        except ImportError:
            return SyncResult(
                success=False,
                message_type=GDSNMessageType.CIP,
                message_id=message_id,
                status=GDSNSyncStatus.FAILED,
                errors=["lxml is required for processing CIP messages"]
            )

        products_created = 0
        products_updated = 0
        errors = []
        warnings = []

        try:
            doc = etree.fromstring(
                xml_content.encode() if isinstance(xml_content, str) else xml_content
            )

            # Find all trade items in the CIP
            trade_items = doc.findall(".//{*}tradeItem")

            for item in trade_items:
                try:
                    result = _import_trade_item(item)
                    if result.get("created"):
                        products_created += 1
                    elif result.get("updated"):
                        products_updated += 1
                    if result.get("warnings"):
                        warnings.extend(result["warnings"])
                except Exception as e:
                    gtin = _extract_gtin(item)
                    errors.append(f"Failed to import {gtin}: {str(e)}")

            _log_sync_operation(
                operation_type="receive_cip",
                message_type=GDSNMessageType.CIP.value,
                message_id=message_id,
                status="success" if not errors else "partial",
                products_created=products_created,
                products_updated=products_updated,
                errors=errors
            )

            return SyncResult(
                success=len(errors) == 0,
                message_type=GDSNMessageType.CIP,
                message_id=message_id,
                status=GDSNSyncStatus.RECEIVED,
                products_count=products_created + products_updated,
                errors=errors,
                warnings=warnings,
            )

        except etree.XMLSyntaxError as e:
            return SyncResult(
                success=False,
                message_type=GDSNMessageType.CIP,
                message_id=message_id,
                status=GDSNSyncStatus.FAILED,
                errors=[f"Invalid XML: {str(e)}"]
            )

    def _process_cirr(self, xml_content: str, message_id: str) -> SyncResult:
        """Process a Catalogue Item Registration Response (CIRR).

        Updates local status based on registration response from data pool.

        Args:
            xml_content: CIRR XML content
            message_id: Message identifier

        Returns:
            SyncResult for the processing operation
        """
        try:
            from lxml import etree

            doc = etree.fromstring(
                xml_content.encode() if isinstance(xml_content, str) else xml_content
            )

            # Extract response status
            status = doc.find(".//{*}responseStatusCode")
            status_text = status.text if status is not None else "UNKNOWN"

            # Extract GTIN if present
            gtin = doc.find(".//{*}gtin")
            gtin_text = gtin.text if gtin is not None else None

            # Map response to sync status
            if status_text == "ACCEPTED":
                sync_status = GDSNSyncStatus.PUBLISHED
            elif status_text == "REJECTED":
                sync_status = GDSNSyncStatus.REJECTED
            else:
                sync_status = GDSNSyncStatus.PENDING

            # Update product status if GTIN is known
            if gtin_text:
                _update_product_gdsn_status_by_gtin(gtin_text, sync_status, message_id)

            _log_sync_operation(
                operation_type="receive_cirr",
                message_type=GDSNMessageType.CIRR.value,
                message_id=message_id,
                status=status_text,
                gtin=gtin_text
            )

            return SyncResult(
                success=status_text == "ACCEPTED",
                message_type=GDSNMessageType.CIRR,
                message_id=message_id,
                status=sync_status,
                response_data={"gtin": gtin_text, "response_status": status_text}
            )

        except Exception as e:
            return SyncResult(
                success=False,
                message_type=GDSNMessageType.CIRR,
                message_id=message_id,
                status=GDSNSyncStatus.FAILED,
                errors=[f"Failed to process CIRR: {str(e)}"]
            )

    def withdraw_product(self, product_name: str, target_market: str = "001") -> SyncResult:
        """Withdraw a product from GDSN.

        Sends a DELETE command for the product.

        Args:
            product_name: Product Variant/Master name
            target_market: Target market code

        Returns:
            SyncResult with operation outcome
        """
        return self.publish_products(
            product_names=[product_name],
            target_market=target_market,
            document_command=GDSNDocumentCommand.DELETE
        )

    def get_sync_status(self, product_name: str) -> Optional[Dict[str, Any]]:
        """Get the GDSN sync status for a product.

        Args:
            product_name: Product Variant/Master name

        Returns:
            Dictionary with sync status details or None
        """
        return _get_product_sync_status(product_name)

    def close(self):
        """Close the service and release resources."""
        if self._client:
            self._client.close()
            self._client = None


# =============================================================================
# Public API Functions
# =============================================================================

def publish_to_data_pool(
    product_names: List[str],
    target_market: str = "001",
    document_command: str = "ADD",
    async_publish: bool = False
) -> Dict[str, Any]:
    """Publish products to the GDSN data pool.

    This is the main API function for publishing products to GDSN.

    Args:
        product_names: List of product names to publish
        target_market: ISO 3166-1 numeric country code
        document_command: ADD, CHANGE_BY_REFRESH, DELETE, or CORRECT
        async_publish: If True, enqueue as background job

    Returns:
        Dictionary with result or job ID
    """
    import frappe

    if async_publish:
        job = frappe.enqueue(
            "frappe_pim.pim.services.gdsn_sync._publish_products_job",
            queue="long",
            timeout=3600,
            product_names=product_names,
            target_market=target_market,
            document_command=document_command
        )
        return {
            "success": True,
            "job_id": job.id if hasattr(job, 'id') else str(job),
            "status": "queued"
        }

    service = GDSNSyncService()
    try:
        cmd = GDSNDocumentCommand[document_command]
        result = service.publish_products(
            product_names=product_names,
            target_market=target_market,
            document_command=cmd
        )
        return result.to_dict()
    finally:
        service.close()


def subscribe_to_product(
    publisher_gln: str,
    gtin: Optional[str] = None,
    gpc_category: Optional[str] = None,
    target_market: str = "001"
) -> Dict[str, Any]:
    """Subscribe to receive product data from a publisher.

    Args:
        publisher_gln: GLN of the data publisher
        gtin: Specific GTIN to subscribe to
        gpc_category: GPC category to subscribe to
        target_market: Target market code

    Returns:
        Dictionary with subscription result
    """
    service = GDSNSyncService()
    try:
        result = service.subscribe_to_publisher(
            publisher_gln=publisher_gln,
            gtin=gtin,
            gpc_category=gpc_category,
            target_market=target_market
        )
        return result.to_dict()
    finally:
        service.close()


def get_sync_status(product_name: str) -> Optional[Dict[str, Any]]:
    """Get GDSN sync status for a product.

    Args:
        product_name: Product Variant/Master name

    Returns:
        Sync status dictionary or None
    """
    return _get_product_sync_status(product_name)


def process_incoming_cin(xml_content: str) -> Dict[str, Any]:
    """Process an incoming CIN message.

    This function is typically called when receiving a CIN webhook
    or processing downloaded messages.

    Args:
        xml_content: CIN XML content

    Returns:
        Dictionary with processing result
    """
    service = GDSNSyncService()
    try:
        result = service._process_cip(xml_content, str(uuid.uuid4()))
        return result.to_dict()
    finally:
        service.close()


def process_incoming_cip(xml_content: str) -> Dict[str, Any]:
    """Process an incoming CIP message.

    This function is typically called when receiving a CIP webhook
    or processing downloaded messages.

    Args:
        xml_content: CIP XML content

    Returns:
        Dictionary with processing result
    """
    service = GDSNSyncService()
    try:
        result = service._process_cip(xml_content, str(uuid.uuid4()))
        return result.to_dict()
    finally:
        service.close()


def sync_product_to_gdsn(product_name: str, target_market: str = "001") -> Dict[str, Any]:
    """Synchronize a single product to GDSN.

    Determines if the product should be added or updated based on
    its current sync status.

    Args:
        product_name: Product Variant/Master name
        target_market: Target market code

    Returns:
        Dictionary with sync result
    """
    # Check current status
    current_status = _get_product_sync_status(product_name)

    if current_status and current_status.get("status") == GDSNSyncStatus.PUBLISHED.value:
        # Already published, send update
        command = "CHANGE_BY_REFRESH"
    else:
        # New publication
        command = "ADD"

    return publish_to_data_pool(
        product_names=[product_name],
        target_market=target_market,
        document_command=command
    )


def sync_all_products_to_gdsn(
    target_market: str = "001",
    status_filter: Optional[str] = None,
    completeness_threshold: int = 80,
    async_sync: bool = True
) -> Dict[str, Any]:
    """Synchronize all eligible products to GDSN.

    Finds products meeting criteria and publishes them.

    Args:
        target_market: Target market code
        status_filter: Filter by product status (e.g., "Active")
        completeness_threshold: Minimum completeness score
        async_sync: If True, process in background

    Returns:
        Dictionary with sync result or job ID
    """
    import frappe

    # Get eligible products
    filters = {}
    if status_filter:
        filters["status"] = status_filter

    products = frappe.get_all(
        "Product Variant",
        filters=filters,
        fields=["name", "completeness_score", "gtin"],
        order_by="modified desc"
    )

    # Filter by completeness and GTIN presence
    eligible = [
        p["name"] for p in products
        if (p.get("completeness_score") or 0) >= completeness_threshold
        and p.get("gtin")
    ]

    if not eligible:
        return {
            "success": False,
            "message": "No eligible products found for GDSN sync",
            "criteria": {
                "completeness_threshold": completeness_threshold,
                "status_filter": status_filter,
                "requires_gtin": True
            }
        }

    return publish_to_data_pool(
        product_names=eligible,
        target_market=target_market,
        document_command="CHANGE_BY_REFRESH",
        async_publish=async_sync
    )


# =============================================================================
# Helper Functions (Private)
# =============================================================================

def _get_pim_settings() -> Dict[str, Any]:
    """Get PIM Settings values.

    Returns:
        Dictionary with PIM settings
    """
    import frappe

    try:
        if not frappe.db.exists("DocType", "PIM Settings"):
            return {}

        settings = frappe.get_single("PIM Settings")
        return {field.fieldname: settings.get(field.fieldname) for field in settings.meta.fields}
    except Exception:
        return {}


def _is_gdsn_enabled() -> bool:
    """Check if GDSN sync is enabled in settings.

    Returns:
        True if GDSN sync is enabled
    """
    settings = _get_pim_settings()
    return settings.get("enable_gdsn_sync", False)


def _log_sync_operation(**kwargs):
    """Log a GDSN sync operation.

    Creates a log entry for the sync operation.
    """
    import frappe

    try:
        # Check if GDSN Sync Log DocType exists
        if not frappe.db.exists("DocType", "GDSN Sync Log"):
            # Fall back to Error Log
            frappe.log_error(
                message=str(kwargs),
                title="GDSN Sync Operation"
            )
            return

        log = frappe.get_doc({
            "doctype": "GDSN Sync Log",
            "operation_type": kwargs.get("operation_type"),
            "message_type": kwargs.get("message_type"),
            "message_id": kwargs.get("message_id"),
            "status": kwargs.get("status"),
            "products": kwargs.get("products"),
            "products_created": kwargs.get("products_created", 0),
            "products_updated": kwargs.get("products_updated", 0),
            "errors": str(kwargs.get("errors", [])),
            "timestamp": datetime.utcnow()
        })
        log.insert(ignore_permissions=True)
        frappe.db.commit()

    except Exception:
        # Fallback to error log
        frappe.log_error(
            message=str(kwargs),
            title="GDSN Sync Operation"
        )


def _update_product_gdsn_status(
    product_name: str,
    status: GDSNSyncStatus,
    message_id: Optional[str] = None
):
    """Update the GDSN sync status of a product.

    Args:
        product_name: Product Variant/Master name
        status: New sync status
        message_id: Associated message ID
    """
    import frappe

    try:
        frappe.db.set_value(
            "Product Variant",
            product_name,
            {
                "gdsn_sync_status": status.value,
                "gdsn_last_sync": datetime.utcnow(),
                "gdsn_message_id": message_id
            },
            update_modified=True
        )
        frappe.db.commit()
    except Exception:
        pass  # Field might not exist


def _update_product_gdsn_status_by_gtin(
    gtin: str,
    status: GDSNSyncStatus,
    message_id: Optional[str] = None
):
    """Update GDSN sync status for product by GTIN.

    Args:
        gtin: Product GTIN
        status: New sync status
        message_id: Associated message ID
    """
    import frappe

    try:
        product_name = frappe.db.get_value(
            "Product Variant",
            {"gtin": gtin},
            "name"
        )
        if product_name:
            _update_product_gdsn_status(product_name, status, message_id)
    except Exception:
        pass


def _get_product_sync_status(product_name: str) -> Optional[Dict[str, Any]]:
    """Get the GDSN sync status for a product.

    Args:
        product_name: Product Variant/Master name

    Returns:
        Dictionary with sync status or None
    """
    import frappe

    try:
        data = frappe.db.get_value(
            "Product Variant",
            product_name,
            ["gdsn_sync_status", "gdsn_last_sync", "gdsn_message_id"],
            as_dict=True
        )
        return data if data else None
    except Exception:
        return None


def _create_subscription_record(subscription: GDSNSubscription, message_id: str):
    """Create a subscription record in the database.

    Args:
        subscription: Subscription details
        message_id: Message ID from data pool
    """
    import frappe

    try:
        # Check if GDSN Subscription DocType exists
        if not frappe.db.exists("DocType", "GDSN Subscription"):
            return

        sub = frappe.get_doc({
            "doctype": "GDSN Subscription",
            "subscriber_gln": subscription.subscriber_gln,
            "publisher_gln": subscription.publisher_gln,
            "gtin": subscription.gtin,
            "gpc_category": subscription.gpc_category,
            "target_market": subscription.target_market,
            "subscription_id": message_id,
            "status": GDSNSyncStatus.SUBSCRIBED.value,
            "created_at": datetime.utcnow()
        })
        sub.insert(ignore_permissions=True)
        frappe.db.commit()

    except Exception:
        pass


def _import_trade_item(item_element) -> Dict[str, Any]:
    """Import a trade item from CIP XML into PIM.

    Args:
        item_element: lxml element for tradeItem

    Returns:
        Dictionary with import result
    """
    import frappe

    result = {"created": False, "updated": False, "warnings": []}

    # Extract GTIN
    gtin = _extract_gtin(item_element)
    if not gtin:
        raise ValueError("Trade item has no GTIN")

    # Check if product exists
    existing = frappe.db.get_value(
        "Product Variant",
        {"gtin": gtin},
        "name"
    )

    # Extract product data
    product_data = _extract_product_data(item_element)
    product_data["gtin"] = gtin
    product_data["gdsn_sync_status"] = GDSNSyncStatus.RECEIVED.value
    product_data["gdsn_last_sync"] = datetime.utcnow()

    if existing:
        # Update existing product
        try:
            doc = frappe.get_doc("Product Variant", existing)
            doc.flags.from_gdsn = True
            for field, value in product_data.items():
                if value is not None:
                    doc.set(field, value)
            doc.save(ignore_permissions=True)
            frappe.db.commit()
            result["updated"] = True
        except Exception as e:
            result["warnings"].append(f"Update warning: {str(e)}")
    else:
        # Create new product
        try:
            doc = frappe.get_doc({
                "doctype": "Product Variant",
                **product_data
            })
            doc.flags.from_gdsn = True
            doc.insert(ignore_permissions=True)
            frappe.db.commit()
            result["created"] = True
        except Exception as e:
            raise ValueError(f"Failed to create product: {str(e)}")

    return result


def _extract_gtin(item_element) -> Optional[str]:
    """Extract GTIN from trade item element.

    Args:
        item_element: lxml element for tradeItem

    Returns:
        GTIN string or None
    """
    gtin = item_element.find(".//{*}gtin")
    if gtin is not None and gtin.text:
        return gtin.text.strip()
    return None


def _extract_product_data(item_element) -> Dict[str, Any]:
    """Extract product data from trade item element.

    Args:
        item_element: lxml element for tradeItem

    Returns:
        Dictionary with extracted product data
    """
    data = {}

    # Brand name
    brand = item_element.find(".//{*}brandName")
    if brand is not None and brand.text:
        data["brand"] = brand.text.strip()

    # Short description
    desc_short = item_element.find(".//{*}descriptionShort")
    if desc_short is not None and desc_short.text:
        data["variant_name"] = desc_short.text.strip()

    # Long description
    desc_long = item_element.find(".//{*}tradeItemDescription")
    if desc_long is not None and desc_long.text:
        data["description"] = desc_long.text.strip()

    # Net weight
    net_weight = item_element.find(".//{*}netWeight")
    if net_weight is not None and net_weight.text:
        try:
            data["net_weight"] = float(net_weight.text)
        except ValueError:
            pass

    # Gross weight
    gross_weight = item_element.find(".//{*}grossWeight")
    if gross_weight is not None and gross_weight.text:
        try:
            data["gross_weight"] = float(gross_weight.text)
        except ValueError:
            pass

    # Dimensions
    height = item_element.find(".//{*}height")
    if height is not None and height.text:
        try:
            data["height"] = float(height.text)
        except ValueError:
            pass

    width = item_element.find(".//{*}width")
    if width is not None and width.text:
        try:
            data["width"] = float(width.text)
        except ValueError:
            pass

    depth = item_element.find(".//{*}depth")
    if depth is not None and depth.text:
        try:
            data["depth"] = float(depth.text)
        except ValueError:
            pass

    # GPC category code
    gpc = item_element.find(".//{*}gpcCategoryCode")
    if gpc is not None and gpc.text:
        data["gpc_code"] = gpc.text.strip()

    # Trade item unit descriptor
    unit_desc = item_element.find(".//{*}tradeItemUnitDescriptor")
    if unit_desc is not None and unit_desc.text:
        data["trade_item_unit_descriptor"] = unit_desc.text.strip()

    # Country of origin
    country = item_element.find(".//{*}countryOfOrigin")
    if country is not None:
        country_code = country.find("{*}countryCode")
        if country_code is not None and country_code.text:
            data["country_of_origin"] = country_code.text.strip()

    return data


def _publish_products_job(
    product_names: List[str],
    target_market: str,
    document_command: str
):
    """Background job for publishing products.

    Args:
        product_names: List of product names
        target_market: Target market code
        document_command: Document command type
    """
    service = GDSNSyncService()
    try:
        cmd = GDSNDocumentCommand[document_command]
        service.publish_products(
            product_names=product_names,
            target_market=target_market,
            document_command=cmd
        )
    finally:
        service.close()


# =============================================================================
# Frappe API Wrappers
# =============================================================================

def _wrap_for_whitelist():
    """Wrap functions for Frappe whitelist at runtime."""
    import frappe

    functions = [
        "publish_to_data_pool",
        "subscribe_to_product",
        "get_sync_status",
        "process_incoming_cin",
        "process_incoming_cip",
        "sync_product_to_gdsn",
        "sync_all_products_to_gdsn",
    ]

    module = __import__(__name__)
    for name in __name__.split('.')[1:]:
        module = getattr(module, name)

    for func_name in functions:
        func = getattr(module, func_name)
        if not getattr(func, "_whitelisted", False):
            whitelisted = frappe.whitelist()(func)
            setattr(module, func_name, whitelisted)


# Apply whitelist decorators when module is loaded in Frappe context
try:
    _wrap_for_whitelist()
except Exception:
    pass  # Not in Frappe context
