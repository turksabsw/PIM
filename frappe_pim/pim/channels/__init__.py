"""
Channel Adapters for PIM

This module provides marketplace channel adapters for publishing
product data to various e-commerce platforms.

Available Adapters:
- AmazonAdapter: Amazon SP-API integration (Seller/Vendor Central)
- WalmartAdapter: Walmart Marketplace integration
- EbayAdapter: eBay Sell API integration

Usage:
    from frappe_pim.pim.channels import get_adapter, list_adapters

    # Get adapter by channel code
    adapter = get_adapter("amazon", channel_doc)
    result = adapter.publish(products)

    # List available adapters
    available = list_adapters()
"""

from frappe_pim.pim.channels.base import (
    ChannelAdapter,
    ValidationResult,
    MappingResult,
    PublishResult,
    StatusResult,
    PublishStatus,
    RateLimitState,
    RateLimitError,
    AuthenticationError,
    PublishError,
    ValidationError,
    ChannelAdapterError,
    register_adapter,
    get_adapter,
    list_adapters,
)

# Import adapters to register them
from frappe_pim.pim.channels.amazon import AmazonAdapter
from frappe_pim.pim.channels.walmart import WalmartAdapter
from frappe_pim.pim.channels.ebay import EbayAdapter
from frappe_pim.pim.channels.trendyol import TrendyolAdapter
from frappe_pim.pim.channels.n11 import N11Adapter
from frappe_pim.pim.channels.hepsiburada import HepsiburadaAdapter


__all__ = [
    # Base classes and utilities
    "ChannelAdapter",
    "ValidationResult",
    "MappingResult",
    "PublishResult",
    "StatusResult",
    "PublishStatus",
    "RateLimitState",
    "RateLimitError",
    "AuthenticationError",
    "PublishError",
    "ValidationError",
    "ChannelAdapterError",
    "register_adapter",
    "get_adapter",
    "list_adapters",
    # Concrete adapters
    "AmazonAdapter",
    "WalmartAdapter",
    "EbayAdapter",
    "TrendyolAdapter",
    "N11Adapter",
    "HepsiburadaAdapter",
]
