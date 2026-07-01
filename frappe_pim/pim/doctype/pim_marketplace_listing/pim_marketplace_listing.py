"""
PIM Marketplace Listing Controller
Marketplace-specific product listing data with pricing and sync status
"""

import frappe
from frappe import _
from frappe.model.document import Document

# Defer frappe import to function level for module import without Frappe context

class PIMMarketplaceListing(Document):

        def validate(self):
            self.validate_listing_sku()
            self.validate_pricing()
            self.validate_sale_dates()
            self.validate_quantity()
            self.validate_unique_listing()

        def validate_listing_sku(self):
            """Set listing SKU from product variant if not provided"""
            if not self.listing_sku and self.product_variant:
                # Use variant SKU as default listing SKU
                variant_sku = frappe.db.get_value(
                    "Product Variant", self.product_variant, "sku"
                )
                if variant_sku:
                    self.listing_sku = variant_sku

        def validate_pricing(self):
            """Validate pricing configuration"""
            if self.listing_price and self.listing_price < 0:
                frappe.throw(
                    _("Listing Price cannot be negative"),
                    title=_("Invalid Price")
                )

            if self.sale_price and self.sale_price < 0:
                frappe.throw(
                    _("Sale Price cannot be negative"),
                    title=_("Invalid Sale Price")
                )

            if self.sale_price and self.listing_price:
                if self.sale_price >= self.listing_price:
                    frappe.msgprint(
                        _("Sale Price should typically be less than Listing Price"),
                        indicator="orange"
                    )

            if self.min_advertised_price and self.listing_price:
                if self.listing_price < self.min_advertised_price:
                    frappe.msgprint(
                        _("Listing Price is below Minimum Advertised Price (MAP)"),
                        indicator="red"
                    )

            if self.max_price and self.listing_price:
                if self.listing_price > self.max_price:
                    frappe.msgprint(
                        _("Listing Price exceeds Maximum Price limit"),
                        indicator="red"
                    )

            # Set currency from channel if not specified
            if not self.listing_currency and self.sales_channel:
                channel_currency = frappe.db.get_value(
                    "PIM Sales Channel", self.sales_channel, "currency"
                )
                if channel_currency:
                    self.listing_currency = channel_currency

        def validate_sale_dates(self):
            """Validate sale date range"""
            if self.sale_start_date and self.sale_end_date:
                if get_datetime(self.sale_start_date) > get_datetime(self.sale_end_date):
                    frappe.throw(
                        _("Sale Start Date cannot be after Sale End Date"),
                        title=_("Invalid Sale Period")
                    )

            if self.sale_price and not (self.sale_start_date or self.sale_end_date):
                frappe.msgprint(
                    _("Consider setting sale dates when a sale price is defined"),
                    indicator="blue"
                )

        def validate_quantity(self):
            """Validate quantity constraints"""
            if self.min_order_qty and self.min_order_qty < 1:
                frappe.throw(
                    _("Minimum Order Quantity must be at least 1"),
                    title=_("Invalid Quantity")
                )

            if self.max_order_qty and self.min_order_qty:
                if self.max_order_qty < self.min_order_qty:
                    frappe.throw(
                        _("Maximum Order Quantity cannot be less than Minimum Order Quantity"),
                        title=_("Invalid Quantity Range")
                    )

            if self.listing_quantity and self.listing_quantity < 0:
                frappe.throw(
                    _("Listing Quantity cannot be negative"),
                    title=_("Invalid Quantity")
                )

        def validate_unique_listing(self):
            """Ensure unique product-channel combination"""
            if not self.is_new():
                return

            existing = frappe.db.exists(
                "PIM Marketplace Listing",
                {
                    "product_variant": self.product_variant,
                    "sales_channel": self.sales_channel,
                    "name": ["!=", self.name or ""]
                }
            )

            if existing:
                frappe.throw(
                    _("A listing already exists for this product on this channel: {0}").format(existing),
                    title=_("Duplicate Listing")
                )

        def before_save(self):
            """Update calculated fields before save"""
            self.set_listing_title()
            self.calculate_price_if_needed()

        def set_listing_title(self):
            """Set listing title from product if not provided"""
            if not self.listing_title and self.product_variant:
                variant_name = frappe.db.get_value(
                    "Product Variant", self.product_variant, "variant_name"
                )
                if variant_name:
                    self.listing_title = variant_name

        def calculate_price_if_needed(self):
            """Calculate listing price from channel pricing if enabled"""
            if not self.use_channel_pricing or self.price_override:
                return

            if not self.sales_channel or not self.product_variant:
                return

            try:
                # Get base price from product variant or ERPNext
                base_price = self._get_base_price()
                if not base_price:
                    return

                # Apply channel pricing rules
                channel = frappe.get_doc("PIM Sales Channel", self.sales_channel)
                price_result = channel.get_effective_price(base_price)

                if price_result.get("adjusted_price"):
                    self.listing_price = price_result["adjusted_price"]

                if price_result.get("currency") and not self.listing_currency:
                    self.listing_currency = price_result["currency"]

            except Exception as e:
                frappe.log_error(
                    f"Error calculating listing price: {str(e)}",
                    "PIM Marketplace Listing Price Calculation"
                )

        def _get_base_price(self):
            """Get base price for the product variant"""
            # First try to get from ERPNext Item Price
            channel_price_list = frappe.db.get_value(
                "PIM Sales Channel", self.sales_channel, "erp_price_list"
            )

            variant_item = frappe.db.get_value(
                "Product Variant", self.product_variant, "erp_item"
            )

            if variant_item and channel_price_list:
                price = frappe.db.get_value(
                    "Item Price",
                    {
                        "item_code": variant_item,
                        "price_list": channel_price_list,
                        "selling": 1
                    },
                    "price_list_rate"
                )
                if price:
                    return price

            # Fallback to default price list
            if variant_item:
                default_price_list = frappe.db.get_single_value(
                    "Selling Settings", "selling_price_list"
                )
                if default_price_list:
                    price = frappe.db.get_value(
                        "Item Price",
                        {
                            "item_code": variant_item,
                            "price_list": default_price_list,
                            "selling": 1
                        },
                        "price_list_rate"
                    )
                    if price:
                        return price

            return None

        def on_update(self):
            """Actions after save"""
            self._invalidate_cache()
            self._queue_sync_if_needed()

        def _invalidate_cache(self):
            """Invalidate listing-related caches"""
            try:
                from frappe_pim.pim.utils.cache import invalidate_cache
                invalidate_cache("pim_marketplace_listing", self.name)
                invalidate_cache("product_variant_listings", self.product_variant)
            except (ImportError, AttributeError):
                pass

        def _queue_sync_if_needed(self):
            """Queue sync to marketplace if active and changed"""
            if not self.is_active or self.listing_status == "Draft":
                return

            if self.sync_status == "Syncing":
                return

            # Check if sync queue doctype exists
            if not frappe.db.exists("DocType", "PIM Sync Queue"):
                return

            try:
                # Queue for sync
                queue_entry = frappe.get_doc({
                    "doctype": "PIM Sync Queue",
                    "doctype_name": "PIM Marketplace Listing",
                    "document_name": self.name,
                    "sync_direction": "PIM to Marketplace",
                    "status": "Pending",
                    "priority": 2
                })
                queue_entry.insert(ignore_permissions=True)

                self.db_set("sync_status", "Queued", update_modified=False)

            except Exception as e:
                frappe.log_error(
                    f"Error queueing marketplace sync: {str(e)}",
                    "PIM Marketplace Listing Sync Queue"
                )

        def on_trash(self):
            """Cleanup before deletion"""
            # Remove from sync queue
            frappe.db.delete(
                "PIM Sync Queue",
                {
                    "doctype_name": "PIM Marketplace Listing",
                    "document_name": self.name,
                    "status": ["in", ["Pending", "Queued"]]
                }
            )

        def mark_synced(self, external_id=None):
            """Mark listing as successfully synced

            Args:
                external_id: External marketplace ID if provided
            """
            update_fields = {
                "sync_status": "Synced",
                "last_synced": now_datetime(),
                "sync_error": None,
                "sync_retries": 0
            }

            if external_id:
                update_fields["external_id"] = external_id

            for field, value in update_fields.items():
                self.db_set(field, value, update_modified=False)

        def mark_sync_failed(self, error_message):
            """Mark listing as sync failed

            Args:
                error_message: Error message from sync attempt
            """
            self.db_set("sync_status", "Failed", update_modified=False)
            self.db_set("sync_error", error_message[:500], update_modified=False)
            self.db_set("sync_retries", (self.sync_retries or 0) + 1, update_modified=False)

        def get_effective_price(self):
            """Get the effective selling price for this listing

            Returns:
                dict with price details
            """
            now = now_datetime()

            # Check if sale is active
            if self.sale_price:
                sale_active = True

                if self.sale_start_date and get_datetime(self.sale_start_date) > now:
                    sale_active = False

                if self.sale_end_date and get_datetime(self.sale_end_date) < now:
                    sale_active = False

                if sale_active:
                    return {
                        "price": self.sale_price,
                        "original_price": self.listing_price,
                        "is_sale": True,
                        "sale_end_date": self.sale_end_date,
                        "currency": self.listing_currency
                    }

            return {
                "price": self.listing_price,
                "original_price": self.listing_price,
                "is_sale": False,
                "currency": self.listing_currency
            }

        def is_available(self):
            """Check if listing is available for purchase

            Returns:
                bool indicating availability
            """
            if not self.is_active:
                return False

            if self.listing_status not in ["Active", "Pending"]:
                return False

            if self.listing_quantity is not None and self.listing_quantity <= 0:
                return False

            return True
def get_listing_for_product(product_variant, sales_channel=None):
    """Get marketplace listing for a product variant

    Args:
        product_variant: Product Variant name
        sales_channel: Optional specific channel

    Returns:
        Listing document or None
    """
    import frappe

    if not frappe.has_permission("PIM Marketplace Listing", "read"):
        frappe.throw("Not permitted", frappe.PermissionError)

    filters = {"product_variant": product_variant}

    if sales_channel:
        filters["sales_channel"] = sales_channel

    listing_name = frappe.db.get_value(
        "PIM Marketplace Listing",
        filters,
        "name"
    )

    if listing_name:
        return frappe.get_doc("PIM Marketplace Listing", listing_name)

    return None

def get_listings_for_channel(sales_channel, status=None, limit=100):
    """Get all listings for a sales channel

    Args:
        sales_channel: Sales channel name
        status: Optional filter by listing status
        limit: Maximum number of results

    Returns:
        List of listing dicts
    """
    import frappe

    if not frappe.has_permission("PIM Marketplace Listing", "read"):
        frappe.throw("Not permitted", frappe.PermissionError)

    filters = {
        "sales_channel": sales_channel,
        "is_active": 1
    }

    if status:
        filters["listing_status"] = status

    return frappe.get_all(
        "PIM Marketplace Listing",
        filters=filters,
        fields=[
            "name", "product_variant", "listing_sku", "listing_title",
            "listing_price", "listing_currency", "listing_status",
            "external_id", "last_synced", "sync_status"
        ],
        order_by="modified desc",
        limit=limit
    )

def get_product_listings(product_variant):
    """Get all marketplace listings for a product variant

    Args:
        product_variant: Product Variant name

    Returns:
        List of listing dicts with channel info
    """
    import frappe

    if not frappe.has_permission("PIM Marketplace Listing", "read"):
        frappe.throw("Not permitted", frappe.PermissionError)

    return frappe.db.sql("""
        SELECT
            ml.name,
            ml.sales_channel,
            sc.channel_name,
            sc.channel_type,
            ml.listing_sku,
            ml.listing_title,
            ml.listing_price,
            ml.listing_currency,
            ml.listing_status,
            ml.external_id,
            ml.external_url,
            ml.last_synced,
            ml.sync_status
        FROM `tabPIM Marketplace Listing` ml
        JOIN `tabPIM Sales Channel` sc ON ml.sales_channel = sc.name
        WHERE ml.product_variant = %(product_variant)s
        ORDER BY sc.channel_name
    """, {"product_variant": product_variant}, as_dict=True)

def create_listing(product_variant, sales_channel, **kwargs):
    """Create a new marketplace listing

    Args:
        product_variant: Product Variant name
        sales_channel: Sales channel name
        **kwargs: Additional listing fields

    Returns:
        Created listing document
    """
    import frappe
    from frappe import _

    if not frappe.has_permission("PIM Marketplace Listing", "create"):
        frappe.throw("Not permitted", frappe.PermissionError)

    # Check if listing already exists
    existing = frappe.db.exists(
        "PIM Marketplace Listing",
        {
            "product_variant": product_variant,
            "sales_channel": sales_channel
        }
    )

    if existing:
        frappe.throw(
            _("Listing already exists for this product on this channel"),
            title=_("Duplicate Listing")
        )

    listing = frappe.get_doc({
        "doctype": "PIM Marketplace Listing",
        "product_variant": product_variant,
        "sales_channel": sales_channel,
        **kwargs
    })

    listing.insert()
    return listing

def bulk_update_prices(sales_channel, price_updates):
    """Bulk update listing prices for a channel

    Args:
        sales_channel: Sales channel name
        price_updates: List of dicts with product_variant and new_price

    Returns:
        dict with success count and errors
    """
    import frappe

    if not frappe.has_permission("PIM Marketplace Listing", "write"):
        frappe.throw("Not permitted", frappe.PermissionError)

    success_count = 0
    errors = []

    for update in price_updates:
        try:
            listing_name = frappe.db.get_value(
                "PIM Marketplace Listing",
                {
                    "product_variant": update.get("product_variant"),
                    "sales_channel": sales_channel
                },
                "name"
            )

            if listing_name:
                frappe.db.set_value(
                    "PIM Marketplace Listing",
                    listing_name,
                    "listing_price",
                    update.get("new_price")
                )
                success_count += 1
            else:
                errors.append({
                    "product_variant": update.get("product_variant"),
                    "error": "Listing not found"
                })

        except Exception as e:
            errors.append({
                "product_variant": update.get("product_variant"),
                "error": str(e)
            })

    frappe.db.commit()

    return {
        "success_count": success_count,
        "error_count": len(errors),
        "errors": errors
    }

def get_listings_pending_sync(sales_channel=None, limit=50):
    """Get listings that need to be synced to marketplace

    Args:
        sales_channel: Optional filter by channel
        limit: Maximum number of results

    Returns:
        List of listing names
    """
    import frappe

    filters = {
        "is_active": 1,
        "listing_status": ["!=", "Draft"],
        "sync_status": ["in", ["Pending", "Queued", "Failed"]]
    }

    if sales_channel:
        filters["sales_channel"] = sales_channel

    return frappe.get_all(
        "PIM Marketplace Listing",
        filters=filters,
        fields=["name", "product_variant", "sales_channel", "sync_status", "sync_retries"],
        order_by="sync_retries asc, modified asc",
        limit=limit
    )
