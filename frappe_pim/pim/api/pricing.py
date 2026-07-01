"""PIM Pricing API Endpoints

This module provides API endpoints for price resolution and pricing operations.
All functions support both synchronous use and whitelisted API access.

Endpoints:
- get_final_price: Get the final resolved price for a product
- get_price_breakdown: Get detailed price breakdown with all layers
- get_bulk_prices: Get prices for multiple products at once
- get_applicable_discounts: Get list of applicable discounts/promotions
- validate_price: Validate a price against channel guardrails

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""


def get_final_price(
    sku,
    channel=None,
    customer=None,
    qty=1,
    currency=None,
    date=None
):
    """Get the final resolved price for a product.

    This is the main pricing API that uses multi-layer price resolution:
    1. Contract Price (customer-specific) - highest priority
    2. Channel Listing Price (marketplace-specific)
    3. Channel Price List (channel default)
    4. Fallback Price List (system default)
    5. Currency Conversion (if needed)
    6. Pricing Rules (discounts, promotions)
    7. Guardrails (min/max price limits)

    Args:
        sku: Product SKU (required) - used to look up the product variant
        channel: Sales channel code (optional) - for channel-specific pricing
        customer: Customer name/ID (optional) - for customer-specific contract pricing
        qty: Order quantity (default: 1) - for quantity-based pricing tiers
        currency: Target currency (optional) - defaults to channel/system currency
        date: Pricing date (optional) - defaults to today, format: YYYY-MM-DD

    Returns:
        dict: Price resolution result with:
            - success: bool - Whether price resolution was successful
            - final_unit_price: float - Final price per unit after all adjustments
            - original_price: float - Base price before any modifications
            - discount_amount: float - Total discount applied
            - discount_percent: float - Discount as percentage
            - currency: str - Price currency code
            - price_source: str - Which layer determined the base price
            - applied_rules: list - List of applied pricing modifications
            - guardrail_applied: bool - Whether guardrail adjusted the price
            - messages: list - Warning/info messages

    Example:
        >>> result = get_final_price(sku="PROD-001-RED-L", channel="amazon-us")
        >>> print(f"Final price: {result['currency']} {result['final_unit_price']}")

    API Usage:
        POST /api/method/frappe_pim.pim.api.pricing.get_final_price
        {
            "sku": "PROD-001",
            "channel": "amazon-us",
            "customer": "CUST-001",
            "qty": 10,
            "currency": "USD",
            "date": "2024-01-15"
        }
    """
    import frappe
    from frappe import _
    from frappe.utils import flt

    # Validate required parameters
    if not sku:
        frappe.throw(_("SKU is required"), title=_("Missing Parameter"))

    # Convert qty to number
    try:
        qty = flt(qty) if qty else 1
        qty = max(1, qty)  # Ensure at least 1
    except (ValueError, TypeError):
        qty = 1

    try:
        # Import price resolver
        from frappe_pim.pim.utils.price_resolver import resolve_price

        # Resolve price using the multi-layer resolution
        result = resolve_price(
            sku=sku,
            channel_code=channel,
            customer=customer,
            qty=qty,
            currency=currency,
            date=date,
            include_pricing_rules=True,
            include_guardrails=True
        )

        # Format response for API
        return {
            "success": result.get("is_valid", False),
            "final_unit_price": result.get("final_unit_price", 0),
            "original_price": result.get("original_price", 0),
            "discount_amount": result.get("discount_amount", 0),
            "discount_percent": result.get("discount_percent", 0),
            "currency": result.get("currency"),
            "price_source": result.get("price_layer"),
            "applied_rules": result.get("applied_rules", []),
            "guardrail_applied": result.get("guardrail_applied", False),
            "messages": result.get("messages", [])
        }

    except ImportError as e:
        frappe.log_error(
            message=f"Price resolver import failed: {str(e)}",
            title="PIM Pricing API Error"
        )
        return {
            "success": False,
            "final_unit_price": 0,
            "original_price": 0,
            "discount_amount": 0,
            "discount_percent": 0,
            "currency": None,
            "price_source": None,
            "applied_rules": [],
            "guardrail_applied": False,
            "messages": [f"Price resolution not available: {str(e)}"]
        }
    except Exception as e:
        frappe.log_error(
            message=f"Price resolution failed for SKU {sku}: {str(e)}",
            title="PIM Pricing API Error"
        )
        return {
            "success": False,
            "final_unit_price": 0,
            "original_price": 0,
            "discount_amount": 0,
            "discount_percent": 0,
            "currency": None,
            "price_source": None,
            "applied_rules": [],
            "guardrail_applied": False,
            "messages": [f"Error resolving price: {str(e)}"]
        }


def get_price_breakdown(
    sku,
    channel=None,
    customer=None,
    qty=1,
    currency=None,
    date=None,
    include_trace=True
):
    """Get detailed price breakdown showing all resolution layers.

    This endpoint provides comprehensive pricing information including
    the complete trace of how the price was resolved through each layer.

    Args:
        sku: Product SKU (required)
        channel: Sales channel code (optional)
        customer: Customer name/ID (optional)
        qty: Order quantity (default: 1)
        currency: Target currency (optional)
        date: Pricing date (optional)
        include_trace: Include detailed resolution trace (default: True)

    Returns:
        dict: Detailed price breakdown with:
            - sku: Product SKU
            - channel: Channel code used
            - customer: Customer ID used
            - quantity: Quantity used for calculation
            - currency: Price currency
            - base_price: Original base price
            - final_price: Final calculated price
            - discount_amount: Total discount
            - discount_percent: Discount percentage
            - price_source: Which layer provided base price
            - layers: dict - Each pricing layer and its contribution
            - applied_rules: list - Applied pricing modifications
            - resolution_trace: list - Step-by-step resolution (if include_trace)
            - is_valid: bool - Whether resolution succeeded
            - messages: list - Any warnings or info

    Example:
        >>> breakdown = get_price_breakdown(sku="PROD-001", include_trace=True)
        >>> for layer in breakdown['layers']:
        ...     print(f"{layer['name']}: {layer['price']}")
    """
    import frappe
    from frappe import _
    from frappe.utils import flt

    if not sku:
        frappe.throw(_("SKU is required"), title=_("Missing Parameter"))

    try:
        qty = flt(qty) if qty else 1
        qty = max(1, qty)
    except (ValueError, TypeError):
        qty = 1

    try:
        from frappe_pim.pim.utils.price_resolver import resolve_price

        result = resolve_price(
            sku=sku,
            channel_code=channel,
            customer=customer,
            qty=qty,
            currency=currency,
            date=date,
            include_pricing_rules=True,
            include_guardrails=True
        )

        # Build layers summary from trace
        layers = []
        trace = result.get("trace", [])

        for step in trace:
            layer_info = {
                "name": step.get("step", "unknown"),
                "checked": step.get("checked", False),
                "found": step.get("found", False),
                "price": step.get("price"),
                "message": step.get("message")
            }

            # Add extra info based on layer type
            if step.get("price_list"):
                layer_info["price_list"] = step.get("price_list")
            if step.get("contract_name"):
                layer_info["contract_name"] = step.get("contract_name")
            if step.get("is_sale_price"):
                layer_info["is_sale_price"] = True
            if step.get("exchange_rate"):
                layer_info["exchange_rate"] = step.get("exchange_rate")
            if step.get("rules"):
                layer_info["rules_applied"] = step.get("rules")
            if step.get("adjustments"):
                layer_info["adjustments"] = step.get("adjustments")

            layers.append(layer_info)

        response = {
            "sku": sku,
            "channel": channel,
            "customer": customer,
            "quantity": qty,
            "currency": result.get("currency"),
            "base_price": result.get("original_price"),
            "final_price": result.get("final_unit_price"),
            "discount_amount": result.get("discount_amount"),
            "discount_percent": result.get("discount_percent"),
            "price_source": result.get("price_layer"),
            "layers": layers,
            "applied_rules": result.get("applied_rules", []),
            "guardrail_applied": result.get("guardrail_applied", False),
            "is_valid": result.get("is_valid", False),
            "messages": result.get("messages", [])
        }

        if include_trace:
            response["resolution_trace"] = trace

        return response

    except ImportError as e:
        frappe.log_error(
            message=f"Price resolver import failed: {str(e)}",
            title="PIM Pricing API Error"
        )
        frappe.throw(
            _("Price resolution not available"),
            title=_("Service Unavailable")
        )
    except Exception as e:
        frappe.log_error(
            message=f"Price breakdown failed for SKU {sku}: {str(e)}",
            title="PIM Pricing API Error"
        )
        frappe.throw(
            _("Failed to get price breakdown: {0}").format(str(e)),
            title=_("Price Breakdown Failed")
        )


def get_bulk_prices(
    skus,
    channel=None,
    customer=None,
    qty=1,
    currency=None,
    date=None
):
    """Get prices for multiple products in a single request.

    Efficiently retrieves prices for multiple SKUs. Useful for
    cart calculations, catalog displays, and bulk operations.

    Args:
        skus: JSON list of product SKUs (required)
        channel: Sales channel code (optional) - applies to all SKUs
        customer: Customer name/ID (optional) - for contract pricing
        qty: Order quantity per item (default: 1)
        currency: Target currency (optional)
        date: Pricing date (optional)

    Returns:
        dict: Bulk pricing results with:
            - success: bool - Overall success status
            - total_skus: int - Number of SKUs requested
            - successful: int - Number successfully priced
            - failed: int - Number that failed
            - prices: dict - SKU -> price result mapping
            - errors: list - Any errors encountered

    Example:
        >>> result = get_bulk_prices(
        ...     skus=["PROD-001", "PROD-002", "PROD-003"],
        ...     channel="amazon-us"
        ... )
        >>> for sku, price_info in result['prices'].items():
        ...     print(f"{sku}: {price_info['final_unit_price']}")
    """
    import frappe
    from frappe import _
    from frappe.utils import flt
    import json

    # Parse SKUs if JSON string
    if isinstance(skus, str):
        try:
            skus = json.loads(skus)
        except json.JSONDecodeError:
            frappe.throw(_("Invalid SKUs format - expected JSON list"))

    if not skus or not isinstance(skus, list):
        frappe.throw(_("SKUs list is required"), title=_("Missing Parameter"))

    # Limit bulk requests to prevent abuse
    max_skus = 100
    if len(skus) > max_skus:
        frappe.throw(
            _("Maximum {0} SKUs allowed per request").format(max_skus),
            title=_("Limit Exceeded")
        )

    try:
        qty = flt(qty) if qty else 1
        qty = max(1, qty)
    except (ValueError, TypeError):
        qty = 1

    try:
        from frappe_pim.pim.utils.price_resolver import resolve_price

        prices = {}
        errors = []
        successful = 0
        failed = 0

        for sku in skus:
            try:
                result = resolve_price(
                    sku=sku,
                    channel_code=channel,
                    customer=customer,
                    qty=qty,
                    currency=currency,
                    date=date,
                    include_pricing_rules=True,
                    include_guardrails=True
                )

                prices[sku] = {
                    "success": result.get("is_valid", False),
                    "final_unit_price": result.get("final_unit_price", 0),
                    "original_price": result.get("original_price", 0),
                    "discount_amount": result.get("discount_amount", 0),
                    "discount_percent": result.get("discount_percent", 0),
                    "currency": result.get("currency"),
                    "price_source": result.get("price_layer"),
                    "messages": result.get("messages", [])
                }

                if result.get("is_valid"):
                    successful += 1
                else:
                    failed += 1

            except Exception as e:
                prices[sku] = {
                    "success": False,
                    "final_unit_price": 0,
                    "error": str(e)
                }
                errors.append({"sku": sku, "error": str(e)})
                failed += 1

        return {
            "success": failed == 0,
            "total_skus": len(skus),
            "successful": successful,
            "failed": failed,
            "prices": prices,
            "errors": errors if errors else None
        }

    except ImportError as e:
        frappe.log_error(
            message=f"Price resolver import failed: {str(e)}",
            title="PIM Pricing API Error"
        )
        frappe.throw(
            _("Price resolution not available"),
            title=_("Service Unavailable")
        )


def get_applicable_discounts(
    sku,
    channel=None,
    customer=None,
    qty=1,
    date=None
):
    """Get list of applicable discounts and promotions for a product.

    Returns all potential discounts that could apply to this product
    based on the given context (channel, customer, quantity, date).

    Args:
        sku: Product SKU (required)
        channel: Sales channel code (optional)
        customer: Customer name/ID (optional)
        qty: Order quantity (default: 1)
        date: Date to check discounts for (optional)

    Returns:
        dict: Applicable discounts with:
            - sku: Product SKU
            - base_price: Price before discounts
            - discounts: list - Available discount details
            - best_discount: dict - The best/most beneficial discount
            - total_potential_savings: float - Maximum possible savings
            - messages: list - Any info messages

    Example:
        >>> discounts = get_applicable_discounts(
        ...     sku="PROD-001",
        ...     customer="CUST-001",
        ...     qty=10
        ... )
        >>> print(f"Best discount: {discounts['best_discount']['name']}")
    """
    import frappe
    from frappe import _
    from frappe.utils import flt, getdate, today

    if not sku:
        frappe.throw(_("SKU is required"), title=_("Missing Parameter"))

    try:
        qty = flt(qty) if qty else 1
        qty = max(1, qty)
    except (ValueError, TypeError):
        qty = 1

    price_date = getdate(date) if date else getdate(today())

    discounts = []
    best_discount = None
    total_potential_savings = 0
    messages = []

    try:
        # Get product variant info
        variant = frappe.db.get_value(
            "Product Variant",
            {"sku": sku},
            ["name", "product_master", "erp_item"],
            as_dict=True
        )

        if not variant:
            return {
                "sku": sku,
                "base_price": 0,
                "discounts": [],
                "best_discount": None,
                "total_potential_savings": 0,
                "messages": [f"Product not found for SKU: {sku}"]
            }

        # Get base price for calculations
        from frappe_pim.pim.utils.price_resolver import resolve_price, _get_channel

        base_result = resolve_price(
            sku=sku,
            channel_code=channel,
            customer=customer,
            qty=qty,
            date=date,
            include_pricing_rules=False,  # Get base price without discounts
            include_guardrails=False
        )

        base_price = base_result.get("original_price", 0)

        if base_price <= 0:
            return {
                "sku": sku,
                "base_price": 0,
                "discounts": [],
                "best_discount": None,
                "total_potential_savings": 0,
                "messages": base_result.get("messages", ["No base price found"])
            }

        # 1. Check contract prices
        if customer:
            try:
                from frappe_pim.pim.doctype.pim_contract_price.pim_contract_price import (
                    get_applicable_contracts
                )

                contracts = get_applicable_contracts(
                    customer=customer,
                    product_variant=variant.name,
                    product_master=variant.product_master,
                    channel_code=channel,
                    qty=qty
                )

                for contract in contracts:
                    discount_info = {
                        "type": "contract_price",
                        "name": contract.get("name"),
                        "description": f"Contract: {contract.get('name')}",
                        "pricing_type": contract.get("pricing_type"),
                        "discount_amount": 0,
                        "discount_percent": 0,
                        "final_price": 0,
                        "priority": 1  # Highest priority
                    }

                    # Calculate discount based on contract type
                    pricing_type = contract.get("pricing_type")
                    if pricing_type == "Fixed Price":
                        final_price = flt(contract.get("fixed_price", 0))
                        discount_info["final_price"] = final_price
                        discount_info["discount_amount"] = base_price - final_price
                        if base_price > 0:
                            discount_info["discount_percent"] = flt(
                                ((base_price - final_price) / base_price) * 100, 2
                            )
                    elif pricing_type == "Discount Percentage":
                        discount_pct = flt(contract.get("discount_percent", 0))
                        discount_amt = base_price * (discount_pct / 100)
                        discount_info["discount_percent"] = discount_pct
                        discount_info["discount_amount"] = discount_amt
                        discount_info["final_price"] = base_price - discount_amt
                    elif pricing_type == "Discount Amount":
                        discount_amt = flt(contract.get("discount_amount", 0))
                        discount_info["discount_amount"] = discount_amt
                        discount_info["final_price"] = base_price - discount_amt
                        if base_price > 0:
                            discount_info["discount_percent"] = flt(
                                (discount_amt / base_price) * 100, 2
                            )

                    discounts.append(discount_info)

            except (ImportError, AttributeError):
                messages.append("Contract pricing module not available")

        # 2. Check customer segment discounts
        if customer:
            try:
                from frappe_pim.pim.doctype.pim_customer_segment.pim_customer_segment import (
                    get_customer_segments
                )

                segments = get_customer_segments(customer)

                for segment in segments:
                    if not segment.get("is_valid_now"):
                        continue

                    discount_type = segment.get("discount_type")
                    discount_info = {
                        "type": "customer_segment",
                        "name": segment.get("name"),
                        "description": f"Segment: {segment.get('segment_name')}",
                        "discount_amount": 0,
                        "discount_percent": 0,
                        "final_price": 0,
                        "priority": 2
                    }

                    if discount_type == "Percentage":
                        discount_pct = flt(segment.get("discount_percent", 0))
                        discount_amt = base_price * (discount_pct / 100)
                        discount_info["discount_percent"] = discount_pct
                        discount_info["discount_amount"] = discount_amt
                        discount_info["final_price"] = base_price - discount_amt
                    elif discount_type == "Fixed Amount":
                        discount_amt = flt(segment.get("discount_amount", 0))
                        discount_info["discount_amount"] = discount_amt
                        discount_info["final_price"] = base_price - discount_amt
                        if base_price > 0:
                            discount_info["discount_percent"] = flt(
                                (discount_amt / base_price) * 100, 2
                            )

                    if discount_info["discount_amount"] > 0:
                        discounts.append(discount_info)

            except (ImportError, AttributeError):
                messages.append("Customer segment module not available")

        # 3. Check ERPNext pricing rules
        if variant.erp_item:
            try:
                from erpnext.accounts.doctype.pricing_rule.pricing_rule import (
                    get_pricing_rules
                )

                args = frappe._dict({
                    "item_code": variant.erp_item,
                    "qty": qty,
                    "customer": customer,
                    "transaction_date": price_date,
                    "company": frappe.defaults.get_defaults().get("company")
                })

                # Get channel price list if available
                if channel:
                    channel_info = _get_channel(channel)
                    if channel_info and channel_info.get("erp_price_list"):
                        args["price_list"] = channel_info.get("erp_price_list")

                pricing_rules = get_pricing_rules(args)

                for rule in (pricing_rules or []):
                    discount_info = {
                        "type": "pricing_rule",
                        "name": rule.get("name"),
                        "description": rule.get("title") or f"Pricing Rule: {rule.get('name')}",
                        "discount_amount": 0,
                        "discount_percent": 0,
                        "final_price": 0,
                        "priority": 3,
                        "valid_from": str(rule.get("valid_from")) if rule.get("valid_from") else None,
                        "valid_upto": str(rule.get("valid_upto")) if rule.get("valid_upto") else None
                    }

                    if rule.get("discount_percentage"):
                        discount_pct = flt(rule.get("discount_percentage"))
                        discount_amt = base_price * (discount_pct / 100)
                        discount_info["discount_percent"] = discount_pct
                        discount_info["discount_amount"] = discount_amt
                        discount_info["final_price"] = base_price - discount_amt
                    elif rule.get("discount_amount"):
                        discount_amt = flt(rule.get("discount_amount"))
                        discount_info["discount_amount"] = discount_amt
                        discount_info["final_price"] = base_price - discount_amt
                        if base_price > 0:
                            discount_info["discount_percent"] = flt(
                                (discount_amt / base_price) * 100, 2
                            )

                    if discount_info["discount_amount"] > 0:
                        discounts.append(discount_info)

            except (ImportError, AttributeError):
                messages.append("ERPNext pricing rules not available")

        # 4. Check sale prices in marketplace listing
        if channel:
            try:
                listing = frappe.db.get_value(
                    "PIM Marketplace Listing",
                    {
                        "product_variant": variant.name,
                        "sales_channel": channel,
                        "is_active": 1
                    },
                    ["listing_price", "sale_price", "sale_start_date", "sale_end_date"],
                    as_dict=True
                )

                if listing and listing.sale_price and listing.listing_price:
                    from frappe.utils import now_datetime, get_datetime

                    now = now_datetime()
                    sale_active = True

                    if listing.sale_start_date and get_datetime(listing.sale_start_date) > now:
                        sale_active = False
                    if listing.sale_end_date and get_datetime(listing.sale_end_date) < now:
                        sale_active = False

                    discount_amt = flt(listing.listing_price) - flt(listing.sale_price)

                    if discount_amt > 0:
                        discount_info = {
                            "type": "sale_price",
                            "name": "Channel Sale",
                            "description": f"Sale price on {channel}",
                            "discount_amount": discount_amt,
                            "discount_percent": flt(
                                (discount_amt / listing.listing_price) * 100, 2
                            ) if listing.listing_price else 0,
                            "final_price": flt(listing.sale_price),
                            "priority": 2,
                            "is_active": sale_active,
                            "valid_from": str(listing.sale_start_date) if listing.sale_start_date else None,
                            "valid_upto": str(listing.sale_end_date) if listing.sale_end_date else None
                        }
                        discounts.append(discount_info)

            except Exception:
                pass  # Listing check is optional

        # Sort discounts by savings (highest first)
        discounts.sort(key=lambda x: x.get("discount_amount", 0), reverse=True)

        # Find best discount
        if discounts:
            best_discount = discounts[0]
            total_potential_savings = best_discount.get("discount_amount", 0)

        return {
            "sku": sku,
            "base_price": base_price,
            "discounts": discounts,
            "best_discount": best_discount,
            "total_potential_savings": total_potential_savings,
            "messages": messages
        }

    except ImportError as e:
        frappe.log_error(
            message=f"Module import failed: {str(e)}",
            title="PIM Pricing API Error"
        )
        return {
            "sku": sku,
            "base_price": 0,
            "discounts": [],
            "best_discount": None,
            "total_potential_savings": 0,
            "messages": [f"Discount lookup not available: {str(e)}"]
        }
    except Exception as e:
        frappe.log_error(
            message=f"Discount lookup failed for SKU {sku}: {str(e)}",
            title="PIM Pricing API Error"
        )
        return {
            "sku": sku,
            "base_price": 0,
            "discounts": [],
            "best_discount": None,
            "total_potential_savings": 0,
            "messages": [f"Error getting discounts: {str(e)}"]
        }


def validate_price(
    price,
    channel,
    sku=None,
    product_variant=None
):
    """Validate a price against channel guardrails.

    Checks if a proposed price meets the channel's pricing rules
    including min/max limits and cost constraints.

    Args:
        price: Price to validate (required)
        channel: Sales channel code (required)
        sku: Product SKU (optional) - for cost validation
        product_variant: Product Variant name (optional) - alternative to SKU

    Returns:
        dict: Validation result with:
            - is_valid: bool - Whether price passes all guardrails
            - price: float - Original price
            - adjusted_price: float - Price adjusted to meet guardrails
            - warnings: list - Guardrail violations or warnings
            - guardrails: dict - Channel guardrail settings

    Example:
        >>> result = validate_price(price=9.99, channel="amazon-us", sku="PROD-001")
        >>> if not result['is_valid']:
        ...     print(f"Warning: {result['warnings']}")
    """
    import frappe
    from frappe import _
    from frappe.utils import flt

    if price is None:
        frappe.throw(_("Price is required"), title=_("Missing Parameter"))

    if not channel:
        frappe.throw(_("Channel is required"), title=_("Missing Parameter"))

    try:
        price = flt(price)
    except (ValueError, TypeError):
        frappe.throw(_("Invalid price format"), title=_("Invalid Parameter"))

    # Resolve product variant from SKU if needed
    variant_name = product_variant
    if not variant_name and sku:
        variant_name = frappe.db.get_value("Product Variant", {"sku": sku}, "name")

    try:
        from frappe_pim.pim.utils.price_resolver import validate_price_against_guardrails

        result = validate_price_against_guardrails(
            price=price,
            channel_code=channel,
            product_variant=variant_name
        )

        # Get channel guardrails for response
        channel_info = frappe.db.get_value(
            "PIM Sales Channel",
            channel,
            ["min_price", "max_price", "enforce_map", "allow_below_cost", "min_price_margin"],
            as_dict=True
        )

        return {
            "is_valid": result.get("is_valid", True),
            "price": price,
            "adjusted_price": result.get("adjusted_price", price),
            "warnings": result.get("warnings", []),
            "guardrails": {
                "min_price": channel_info.get("min_price") if channel_info else None,
                "max_price": channel_info.get("max_price") if channel_info else None,
                "enforce_map": channel_info.get("enforce_map") if channel_info else False,
                "allow_below_cost": channel_info.get("allow_below_cost") if channel_info else True,
                "min_price_margin": channel_info.get("min_price_margin") if channel_info else None
            }
        }

    except ImportError as e:
        frappe.log_error(
            message=f"Price validator import failed: {str(e)}",
            title="PIM Pricing API Error"
        )
        return {
            "is_valid": True,  # Default to valid if can't validate
            "price": price,
            "adjusted_price": price,
            "warnings": ["Price validation not available"],
            "guardrails": {}
        }
    except Exception as e:
        frappe.log_error(
            message=f"Price validation failed: {str(e)}",
            title="PIM Pricing API Error"
        )
        return {
            "is_valid": True,
            "price": price,
            "adjusted_price": price,
            "warnings": [f"Validation error: {str(e)}"],
            "guardrails": {}
        }


def get_price_history(
    sku,
    channel=None,
    days=30,
    limit=100
):
    """Get historical prices for a product.

    Returns price changes over time for analysis and tracking.

    Args:
        sku: Product SKU (required)
        channel: Sales channel code (optional) - filter by channel
        days: Number of days of history (default: 30)
        limit: Maximum records to return (default: 100)

    Returns:
        dict: Price history with:
            - sku: Product SKU
            - channel: Channel filter used
            - history: list - Price records with dates
            - current_price: float - Current price
            - min_price: float - Lowest price in period
            - max_price: float - Highest price in period
            - avg_price: float - Average price

    Example:
        >>> history = get_price_history(sku="PROD-001", days=90)
        >>> print(f"Price range: {history['min_price']} - {history['max_price']}")
    """
    import frappe
    from frappe import _
    from frappe.utils import flt, add_days, today

    if not sku:
        frappe.throw(_("SKU is required"), title=_("Missing Parameter"))

    try:
        days = int(days)
        days = min(365, max(1, days))  # Limit to 1-365 days
    except (ValueError, TypeError):
        days = 30

    try:
        limit = int(limit)
        limit = min(1000, max(1, limit))  # Limit to 1-1000 records
    except (ValueError, TypeError):
        limit = 100

    # Get product variant
    variant = frappe.db.get_value(
        "Product Variant",
        {"sku": sku},
        ["name", "erp_item"],
        as_dict=True
    )

    if not variant:
        return {
            "sku": sku,
            "channel": channel,
            "history": [],
            "current_price": 0,
            "min_price": 0,
            "max_price": 0,
            "avg_price": 0,
            "messages": [f"Product not found for SKU: {sku}"]
        }

    history = []
    from_date = add_days(today(), -days)

    # Get price history from Item Price changes if available
    if variant.erp_item:
        try:
            # Get price versions from Item Price
            # Note: This requires ERPNext to track price history
            # For now, we'll get the current price and any version data

            filters = {
                "item_code": variant.erp_item,
                "selling": 1
            }

            if channel:
                channel_info = frappe.db.get_value(
                    "PIM Sales Channel",
                    channel,
                    "erp_price_list"
                )
                if channel_info:
                    filters["price_list"] = channel_info

            prices = frappe.get_all(
                "Item Price",
                filters=filters,
                fields=["price_list_rate", "valid_from", "valid_upto", "price_list", "creation"],
                order_by="creation desc",
                limit=limit
            )

            for price_record in prices:
                history.append({
                    "date": str(price_record.get("valid_from") or price_record.get("creation")),
                    "price": flt(price_record.price_list_rate),
                    "price_list": price_record.price_list,
                    "source": "item_price"
                })

        except Exception as e:
            frappe.log_error(
                message=f"Error getting price history: {str(e)}",
                title="PIM Pricing API"
            )

    # Get current price
    current_price = 0
    try:
        from frappe_pim.pim.utils.price_resolver import resolve_price

        result = resolve_price(
            sku=sku,
            channel_code=channel,
            include_pricing_rules=False,
            include_guardrails=False
        )
        current_price = result.get("original_price", 0)
    except Exception:
        pass

    # Calculate statistics
    prices = [h.get("price", 0) for h in history if h.get("price")]
    min_price = min(prices) if prices else 0
    max_price = max(prices) if prices else 0
    avg_price = flt(sum(prices) / len(prices), 2) if prices else 0

    return {
        "sku": sku,
        "channel": channel,
        "days": days,
        "history": history,
        "current_price": current_price,
        "min_price": min_price,
        "max_price": max_price,
        "avg_price": avg_price
    }


# ============================================================================
# Whitelist Wrapper
# ============================================================================

def _wrap_for_whitelist():
    """Add @frappe.whitelist() decorators at runtime."""
    import frappe

    global get_final_price, get_price_breakdown, get_bulk_prices
    global get_applicable_discounts, validate_price, get_price_history

    get_final_price = frappe.whitelist()(get_final_price)
    get_price_breakdown = frappe.whitelist()(get_price_breakdown)
    get_bulk_prices = frappe.whitelist()(get_bulk_prices)
    get_applicable_discounts = frappe.whitelist()(get_applicable_discounts)
    validate_price = frappe.whitelist()(validate_price)
    get_price_history = frappe.whitelist()(get_price_history)


# Apply whitelist decorators if frappe is available
try:
    _wrap_for_whitelist()
except ImportError:
    pass  # Decorators will be added when module is used in Frappe context
