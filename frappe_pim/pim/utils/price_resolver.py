"""
PIM Price Resolver Utility
Multi-layer price calculation with priority-based resolution

Price Resolution Priority (highest to lowest):
1. Contract Price - customer-specific contract pricing
2. Channel Listing Price - marketplace-specific listing price
3. Channel Price List - channel's default price list in ERPNext
4. Fallback Price List - system default price list
5. Currency Conversion - convert to requested currency if different
6. Pricing Rules - apply discounts, promotions (ERPNext Pricing Rules)
7. Guardrails - enforce min/max price constraints
"""

# Defer frappe import to function level for module import without Frappe context

# Price layer identifiers for tracing
PRICE_LAYER_CONTRACT = "contract_price"
PRICE_LAYER_LISTING = "channel_listing"
PRICE_LAYER_CHANNEL_PRICE_LIST = "channel_price_list"
PRICE_LAYER_FALLBACK_PRICE_LIST = "fallback_price_list"
PRICE_LAYER_CURRENCY_CONVERSION = "currency_conversion"
PRICE_LAYER_PRICING_RULES = "pricing_rules"
PRICE_LAYER_GUARDRAILS = "guardrails"


def resolve_price(
    sku=None,
    product_variant=None,
    product_master=None,
    channel_code=None,
    customer=None,
    qty=1,
    currency=None,
    date=None,
    include_pricing_rules=True,
    include_guardrails=True
):
    """Resolve the final price for a product using multi-layer price resolution

    This is the main price resolution function that evaluates prices in priority order:
    1. Contract Price (customer-specific)
    2. Channel Listing Price (marketplace-specific)
    3. Channel Price List (channel default)
    4. Fallback Price List (system default)
    5. Currency Conversion
    6. Pricing Rules (discounts)
    7. Guardrails (min/max limits)

    Args:
        sku: Product SKU (will look up product_variant if not provided)
        product_variant: Product Variant document name
        product_master: Product Master document name (for master-level pricing)
        channel_code: Sales channel code or name
        customer: Customer name/ID for customer-specific pricing
        qty: Order quantity for quantity-based pricing
        currency: Target currency for conversion (defaults to channel/system currency)
        date: Date for time-based pricing (defaults to today)
        include_pricing_rules: Whether to apply ERPNext pricing rules
        include_guardrails: Whether to enforce price guardrails

    Returns:
        dict with price resolution result:
        {
            "final_unit_price": float,      # Final price per unit
            "original_price": float,        # Price before any modifications
            "discount_amount": float,       # Total discount applied
            "discount_percent": float,      # Discount as percentage
            "currency": str,                # Price currency
            "price_layer": str,             # Which layer determined the base price
            "applied_rules": list,          # List of applied modifications
            "guardrail_applied": bool,      # Whether guardrail adjusted price
            "is_valid": bool,               # Whether price resolution was successful
            "messages": list,               # Warning/info messages
            "trace": list                   # Detailed trace of price resolution steps
        }
    """
    import frappe
    from frappe import _
    from frappe.utils import flt, getdate, today

    # Initialize result
    result = {
        "final_unit_price": 0,
        "original_price": 0,
        "discount_amount": 0,
        "discount_percent": 0,
        "currency": None,
        "price_layer": None,
        "applied_rules": [],
        "guardrail_applied": False,
        "is_valid": False,
        "messages": [],
        "trace": []
    }

    try:
        # Resolve date
        price_date = getdate(date) if date else getdate(today())

        # Resolve product variant from SKU if needed
        if not product_variant and sku:
            product_variant = _resolve_variant_from_sku(sku)
            if not product_variant:
                result["messages"].append(f"Product variant not found for SKU: {sku}")
                return result

        # Get product info
        product_info = _get_product_info(product_variant, product_master)
        if not product_info:
            result["messages"].append("Product information not available")
            return result

        # Resolve channel
        channel = _get_channel(channel_code)
        channel_currency = channel.get("currency") if channel else None

        # Determine target currency
        target_currency = currency or channel_currency or _get_default_currency()
        result["currency"] = target_currency

        # Step 1: Try Contract Price (highest priority)
        base_price, price_layer, trace_entry = _try_contract_price(
            customer=customer,
            product_variant=product_variant,
            product_master=product_info.get("product_master"),
            channel_code=channel_code,
            qty=qty,
            currency=target_currency
        )
        result["trace"].append(trace_entry)

        # Step 2: Try Channel Listing Price
        if base_price is None:
            base_price, price_layer, trace_entry = _try_channel_listing_price(
                product_variant=product_variant,
                channel_code=channel_code
            )
            result["trace"].append(trace_entry)

        # Step 3: Try Channel Price List
        if base_price is None and channel:
            base_price, price_layer, trace_entry = _try_channel_price_list(
                erp_item=product_info.get("erp_item"),
                price_list=channel.get("erp_price_list"),
                currency=target_currency
            )
            result["trace"].append(trace_entry)

        # Step 4: Try Fallback Price List
        if base_price is None:
            base_price, price_layer, trace_entry = _try_fallback_price_list(
                erp_item=product_info.get("erp_item"),
                currency=target_currency
            )
            result["trace"].append(trace_entry)

        # If no price found, return failure
        if base_price is None:
            result["messages"].append("No price found for this product")
            return result

        # Store original price and layer
        result["original_price"] = flt(base_price)
        result["price_layer"] = price_layer
        final_price = flt(base_price)

        # Step 5: Currency Conversion (if needed)
        source_currency = _get_price_currency(price_layer, channel, product_variant)
        if source_currency and source_currency != target_currency:
            converted_price, trace_entry = _apply_currency_conversion(
                base_price, source_currency, target_currency, price_date
            )
            result["trace"].append(trace_entry)
            if converted_price is not None:
                final_price = converted_price
                result["applied_rules"].append({
                    "type": "currency_conversion",
                    "from_currency": source_currency,
                    "to_currency": target_currency,
                    "original_amount": base_price,
                    "converted_amount": converted_price
                })

        # Step 6: Apply Pricing Rules (discounts, promotions)
        if include_pricing_rules:
            discounted_price, discount_details, trace_entry = _apply_pricing_rules(
                item_code=product_info.get("erp_item"),
                price=final_price,
                customer=customer,
                qty=qty,
                price_list=channel.get("erp_price_list") if channel else None,
                date=price_date
            )
            result["trace"].append(trace_entry)
            if discounted_price is not None and discounted_price != final_price:
                result["applied_rules"].extend(discount_details)
                final_price = discounted_price

        # Step 7: Apply Guardrails (min/max price limits)
        if include_guardrails and channel:
            guardrail_price, guardrail_applied, trace_entry = _apply_guardrails(
                price=final_price,
                channel=channel,
                product_info=product_info
            )
            result["trace"].append(trace_entry)
            if guardrail_applied:
                result["guardrail_applied"] = True
                result["applied_rules"].append({
                    "type": "guardrail",
                    "original_price": final_price,
                    "adjusted_price": guardrail_price,
                    "channel": channel_code
                })
                final_price = guardrail_price

        # Calculate discount amounts
        result["final_unit_price"] = flt(final_price)
        result["discount_amount"] = flt(result["original_price"] - final_price)
        if result["original_price"] > 0:
            result["discount_percent"] = flt(
                (result["discount_amount"] / result["original_price"]) * 100, 2
            )

        result["is_valid"] = True

    except Exception as e:
        import traceback
        result["messages"].append(f"Error resolving price: {str(e)}")
        result["trace"].append({
            "step": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
        })

    return result


def _resolve_variant_from_sku(sku):
    """Look up product variant by SKU

    Args:
        sku: Product SKU

    Returns:
        Product Variant name or None
    """
    import frappe

    return frappe.db.get_value("Product Variant", {"sku": sku}, "name")


def _get_product_info(product_variant, product_master):
    """Get product information needed for price resolution

    Args:
        product_variant: Product Variant name
        product_master: Product Master name

    Returns:
        dict with product info or None
    """
    import frappe

    if product_variant:
        variant = frappe.db.get_value(
            "Product Variant",
            product_variant,
            ["name", "sku", "product_master", "erp_item"],
            as_dict=True
        )
        if variant:
            return {
                "product_variant": variant.name,
                "sku": variant.sku,
                "product_master": variant.product_master,
                "erp_item": variant.erp_item
            }

    if product_master:
        master = frappe.db.get_value(
            "Product Master",
            product_master,
            ["name", "sku", "erp_item"],
            as_dict=True
        )
        if master:
            return {
                "product_variant": None,
                "sku": master.sku,
                "product_master": master.name,
                "erp_item": master.erp_item
            }

    return None


def _get_channel(channel_code):
    """Get sales channel information

    Args:
        channel_code: Channel code or name

    Returns:
        dict with channel info or None
    """
    import frappe

    if not channel_code:
        return None

    if not frappe.db.exists("PIM Sales Channel", channel_code):
        return None

    return frappe.db.get_value(
        "PIM Sales Channel",
        channel_code,
        [
            "name", "channel_code", "channel_name", "currency",
            "erp_price_list", "min_price", "max_price",
            "enforce_map", "allow_below_cost", "min_price_margin",
            "price_markup_percent", "price_rounding"
        ],
        as_dict=True
    )


def _get_default_currency():
    """Get system default currency

    Returns:
        Currency code string
    """
    import frappe

    return frappe.db.get_single_value("Global Defaults", "default_currency") or "USD"


def _try_contract_price(customer, product_variant, product_master, channel_code, qty, currency):
    """Try to get contract price for customer

    Args:
        customer: Customer name
        product_variant: Product Variant name
        product_master: Product Master name
        channel_code: Sales channel code
        qty: Order quantity
        currency: Target currency

    Returns:
        tuple: (price, price_layer, trace_entry)
    """
    import frappe
    from frappe.utils import flt

    trace = {
        "step": PRICE_LAYER_CONTRACT,
        "checked": False,
        "found": False,
        "price": None
    }

    if not customer:
        trace["message"] = "No customer specified"
        return None, None, trace

    trace["checked"] = True

    try:
        # Import helper from contract price module
        from frappe_pim.pim.doctype.pim_contract_price.pim_contract_price import (
            get_best_contract_price
        )

        # Get a base price to apply contract pricing to
        # First try to get from price list
        base_price = _get_base_price_for_contract(product_variant, product_master)

        if base_price is None:
            trace["message"] = "No base price available for contract calculation"
            return None, None, trace

        result = get_best_contract_price(
            customer=customer,
            base_price=base_price,
            product_variant=product_variant,
            product_master=product_master,
            channel_code=channel_code,
            qty=qty
        )

        if result and result.get("is_applicable"):
            price = flt(result.get("final_price"))
            trace["found"] = True
            trace["price"] = price
            trace["contract_name"] = result.get("contract_name")
            trace["pricing_type"] = result.get("pricing_type")
            return price, PRICE_LAYER_CONTRACT, trace

        trace["message"] = "No applicable contract price found"

    except (ImportError, AttributeError) as e:
        trace["message"] = f"Contract price module not available: {str(e)}"
    except Exception as e:
        trace["message"] = f"Error getting contract price: {str(e)}"

    return None, None, trace


def _get_base_price_for_contract(product_variant, product_master):
    """Get base price for contract price calculation

    Args:
        product_variant: Product Variant name
        product_master: Product Master name

    Returns:
        Base price or None
    """
    import frappe

    # Try to get ERPNext item
    erp_item = None
    if product_variant:
        erp_item = frappe.db.get_value("Product Variant", product_variant, "erp_item")
    elif product_master:
        erp_item = frappe.db.get_value("Product Master", product_master, "erp_item")

    if not erp_item:
        return None

    # Get default price list
    default_price_list = frappe.db.get_single_value("Selling Settings", "selling_price_list")
    if not default_price_list:
        return None

    # Get price from default price list
    price = frappe.db.get_value(
        "Item Price",
        {
            "item_code": erp_item,
            "price_list": default_price_list,
            "selling": 1
        },
        "price_list_rate"
    )

    return price


def _try_channel_listing_price(product_variant, channel_code):
    """Try to get marketplace listing price for channel

    Args:
        product_variant: Product Variant name
        channel_code: Sales channel code

    Returns:
        tuple: (price, price_layer, trace_entry)
    """
    import frappe
    from frappe.utils import flt

    trace = {
        "step": PRICE_LAYER_LISTING,
        "checked": False,
        "found": False,
        "price": None
    }

    if not product_variant or not channel_code:
        trace["message"] = "Product variant or channel not specified"
        return None, None, trace

    trace["checked"] = True

    try:
        # Check if PIM Marketplace Listing DocType exists
        if not frappe.db.exists("DocType", "PIM Marketplace Listing"):
            trace["message"] = "PIM Marketplace Listing DocType not available"
            return None, None, trace

        listing = frappe.db.get_value(
            "PIM Marketplace Listing",
            {
                "product_variant": product_variant,
                "sales_channel": channel_code,
                "is_active": 1
            },
            ["listing_price", "sale_price", "sale_start_date", "sale_end_date", "listing_currency"],
            as_dict=True
        )

        if listing and listing.listing_price:
            # Check if sale is active
            from frappe.utils import now_datetime, get_datetime
            now = now_datetime()

            price = flt(listing.listing_price)

            if listing.sale_price:
                sale_active = True
                if listing.sale_start_date and get_datetime(listing.sale_start_date) > now:
                    sale_active = False
                if listing.sale_end_date and get_datetime(listing.sale_end_date) < now:
                    sale_active = False

                if sale_active:
                    price = flt(listing.sale_price)
                    trace["is_sale_price"] = True

            trace["found"] = True
            trace["price"] = price
            trace["currency"] = listing.listing_currency
            return price, PRICE_LAYER_LISTING, trace

        trace["message"] = "No active listing found for this product/channel"

    except Exception as e:
        trace["message"] = f"Error getting listing price: {str(e)}"

    return None, None, trace


def _try_channel_price_list(erp_item, price_list, currency):
    """Try to get price from channel's ERPNext price list

    Args:
        erp_item: ERPNext Item code
        price_list: Price List name
        currency: Target currency

    Returns:
        tuple: (price, price_layer, trace_entry)
    """
    import frappe
    from frappe.utils import flt

    trace = {
        "step": PRICE_LAYER_CHANNEL_PRICE_LIST,
        "checked": False,
        "found": False,
        "price": None
    }

    if not erp_item or not price_list:
        trace["message"] = "ERPNext item or price list not specified"
        return None, None, trace

    trace["checked"] = True
    trace["price_list"] = price_list

    try:
        price = frappe.db.get_value(
            "Item Price",
            {
                "item_code": erp_item,
                "price_list": price_list,
                "selling": 1
            },
            "price_list_rate"
        )

        if price:
            trace["found"] = True
            trace["price"] = flt(price)
            return flt(price), PRICE_LAYER_CHANNEL_PRICE_LIST, trace

        trace["message"] = f"No price found in price list: {price_list}"

    except Exception as e:
        trace["message"] = f"Error getting channel price list price: {str(e)}"

    return None, None, trace


def _try_fallback_price_list(erp_item, currency):
    """Try to get price from system default price list

    Args:
        erp_item: ERPNext Item code
        currency: Target currency

    Returns:
        tuple: (price, price_layer, trace_entry)
    """
    import frappe
    from frappe.utils import flt

    trace = {
        "step": PRICE_LAYER_FALLBACK_PRICE_LIST,
        "checked": False,
        "found": False,
        "price": None
    }

    if not erp_item:
        trace["message"] = "ERPNext item not specified"
        return None, None, trace

    trace["checked"] = True

    try:
        # Get default selling price list
        default_price_list = frappe.db.get_single_value("Selling Settings", "selling_price_list")

        if not default_price_list:
            trace["message"] = "No default selling price list configured"
            return None, None, trace

        trace["price_list"] = default_price_list

        price = frappe.db.get_value(
            "Item Price",
            {
                "item_code": erp_item,
                "price_list": default_price_list,
                "selling": 1
            },
            "price_list_rate"
        )

        if price:
            trace["found"] = True
            trace["price"] = flt(price)
            return flt(price), PRICE_LAYER_FALLBACK_PRICE_LIST, trace

        # Try standard rate from Item master as last resort
        standard_rate = frappe.db.get_value("Item", erp_item, "standard_rate")
        if standard_rate:
            trace["found"] = True
            trace["price"] = flt(standard_rate)
            trace["source"] = "item_standard_rate"
            return flt(standard_rate), PRICE_LAYER_FALLBACK_PRICE_LIST, trace

        trace["message"] = "No price found in default price list or item master"

    except Exception as e:
        trace["message"] = f"Error getting fallback price: {str(e)}"

    return None, None, trace


def _get_price_currency(price_layer, channel, product_variant):
    """Determine the currency of the resolved price

    Args:
        price_layer: Which price layer was used
        channel: Channel dict
        product_variant: Product Variant name

    Returns:
        Currency code or None
    """
    import frappe

    if price_layer == PRICE_LAYER_LISTING:
        # Get listing currency
        if product_variant and channel:
            listing_currency = frappe.db.get_value(
                "PIM Marketplace Listing",
                {
                    "product_variant": product_variant,
                    "sales_channel": channel.get("name")
                },
                "listing_currency"
            )
            if listing_currency:
                return listing_currency

    if price_layer in (PRICE_LAYER_CHANNEL_PRICE_LIST, PRICE_LAYER_FALLBACK_PRICE_LIST):
        # Price list currency
        price_list = None
        if price_layer == PRICE_LAYER_CHANNEL_PRICE_LIST and channel:
            price_list = channel.get("erp_price_list")
        else:
            price_list = frappe.db.get_single_value("Selling Settings", "selling_price_list")

        if price_list:
            pl_currency = frappe.db.get_value("Price List", price_list, "currency")
            if pl_currency:
                return pl_currency

    # Default to channel currency or system default
    if channel:
        return channel.get("currency")

    return _get_default_currency()


def _apply_currency_conversion(price, from_currency, to_currency, date):
    """Apply currency conversion if needed

    Args:
        price: Price to convert
        from_currency: Source currency
        to_currency: Target currency
        date: Conversion date

    Returns:
        tuple: (converted_price, trace_entry)
    """
    import frappe
    from frappe.utils import flt

    trace = {
        "step": PRICE_LAYER_CURRENCY_CONVERSION,
        "from_currency": from_currency,
        "to_currency": to_currency,
        "original_price": price,
        "converted": False
    }

    if from_currency == to_currency:
        trace["message"] = "Same currency, no conversion needed"
        return price, trace

    try:
        # Get exchange rate using ERPNext's currency exchange
        exchange_rate = get_exchange_rate(from_currency, to_currency, date)

        if exchange_rate and exchange_rate != 1:
            converted_price = flt(price * exchange_rate, 2)
            trace["converted"] = True
            trace["exchange_rate"] = exchange_rate
            trace["converted_price"] = converted_price
            return converted_price, trace

        trace["message"] = "No exchange rate found or rate is 1"

    except Exception as e:
        trace["message"] = f"Error converting currency: {str(e)}"

    return price, trace


def get_exchange_rate(from_currency, to_currency, date=None):
    """Get exchange rate between two currencies

    Args:
        from_currency: Source currency code
        to_currency: Target currency code
        date: Exchange rate date (optional)

    Returns:
        Exchange rate or 1 if not found
    """
    import frappe
    from frappe.utils import getdate, today

    if from_currency == to_currency:
        return 1

    exchange_date = getdate(date) if date else getdate(today())

    try:
        # Try to get from Currency Exchange
        rate = frappe.db.get_value(
            "Currency Exchange",
            {
                "from_currency": from_currency,
                "to_currency": to_currency,
                "date": ["<=", exchange_date]
            },
            "exchange_rate",
            order_by="date desc"
        )

        if rate:
            return rate

        # Try reverse exchange rate
        reverse_rate = frappe.db.get_value(
            "Currency Exchange",
            {
                "from_currency": to_currency,
                "to_currency": from_currency,
                "date": ["<=", exchange_date]
            },
            "exchange_rate",
            order_by="date desc"
        )

        if reverse_rate:
            return 1 / reverse_rate

    except Exception:
        pass

    return 1


def _apply_pricing_rules(item_code, price, customer, qty, price_list, date):
    """Apply ERPNext pricing rules (discounts, promotions)

    Args:
        item_code: ERPNext Item code
        price: Current price
        customer: Customer name
        qty: Order quantity
        price_list: Price list name
        date: Pricing date

    Returns:
        tuple: (discounted_price, discount_details, trace_entry)
    """
    import frappe
    from frappe.utils import flt

    trace = {
        "step": PRICE_LAYER_PRICING_RULES,
        "checked": False,
        "applied": False,
        "rules": []
    }

    if not item_code:
        trace["message"] = "No item code for pricing rules"
        return price, [], trace

    trace["checked"] = True
    discount_details = []

    try:
        # Get applicable pricing rules
        # This uses ERPNext's pricing rule logic
        args = frappe._dict({
            "item_code": item_code,
            "qty": flt(qty),
            "price": flt(price),
            "price_list": price_list,
            "customer": customer,
            "transaction_date": date,
            "company": frappe.defaults.get_defaults().get("company"),
            "doctype": "Sales Order",  # Context for pricing rules
            "name": None,
            "is_return": 0
        })

        # Try to get pricing rule discount
        try:
            from erpnext.accounts.doctype.pricing_rule.pricing_rule import get_pricing_rule_for_item
            pricing_rules = get_pricing_rule_for_item(args)

            if pricing_rules and isinstance(pricing_rules, dict):
                if pricing_rules.get("discount_percentage"):
                    discount_pct = flt(pricing_rules.get("discount_percentage"))
                    discount_amount = price * (discount_pct / 100)
                    discounted_price = price - discount_amount

                    rule_detail = {
                        "type": "pricing_rule_discount_percentage",
                        "rule_name": pricing_rules.get("pricing_rule"),
                        "discount_percentage": discount_pct,
                        "discount_amount": discount_amount
                    }
                    discount_details.append(rule_detail)
                    trace["rules"].append(rule_detail)
                    trace["applied"] = True

                    return discounted_price, discount_details, trace

                if pricing_rules.get("discount_amount"):
                    discount_amount = flt(pricing_rules.get("discount_amount"))
                    discounted_price = price - discount_amount

                    rule_detail = {
                        "type": "pricing_rule_discount_amount",
                        "rule_name": pricing_rules.get("pricing_rule"),
                        "discount_amount": discount_amount
                    }
                    discount_details.append(rule_detail)
                    trace["rules"].append(rule_detail)
                    trace["applied"] = True

                    return discounted_price, discount_details, trace

                if pricing_rules.get("price_list_rate"):
                    # Direct price override from pricing rule
                    discounted_price = flt(pricing_rules.get("price_list_rate"))

                    rule_detail = {
                        "type": "pricing_rule_price_override",
                        "rule_name": pricing_rules.get("pricing_rule"),
                        "price_list_rate": discounted_price
                    }
                    discount_details.append(rule_detail)
                    trace["rules"].append(rule_detail)
                    trace["applied"] = True

                    return discounted_price, discount_details, trace

        except (ImportError, AttributeError):
            trace["message"] = "ERPNext pricing rule module not available"

        trace["message"] = "No applicable pricing rules found"

    except Exception as e:
        trace["message"] = f"Error applying pricing rules: {str(e)}"

    return price, discount_details, trace


def _apply_guardrails(price, channel, product_info):
    """Apply price guardrails (min/max limits)

    Args:
        price: Current price
        channel: Channel dict with guardrail settings
        product_info: Product info dict

    Returns:
        tuple: (adjusted_price, guardrail_applied, trace_entry)
    """
    from frappe.utils import flt

    trace = {
        "step": PRICE_LAYER_GUARDRAILS,
        "checked": True,
        "applied": False,
        "original_price": price,
        "adjustments": []
    }

    adjusted_price = flt(price)
    guardrail_applied = False

    # Check channel min price (MAP - Minimum Advertised Price)
    if channel.get("min_price") and adjusted_price < flt(channel.get("min_price")):
        if channel.get("enforce_map"):
            trace["adjustments"].append({
                "type": "min_price_enforced",
                "min_price": channel.get("min_price"),
                "original_price": adjusted_price
            })
            adjusted_price = flt(channel.get("min_price"))
            guardrail_applied = True
        else:
            trace["adjustments"].append({
                "type": "min_price_warning",
                "min_price": channel.get("min_price"),
                "current_price": adjusted_price
            })

    # Check channel max price
    if channel.get("max_price") and adjusted_price > flt(channel.get("max_price")):
        trace["adjustments"].append({
            "type": "max_price_enforced",
            "max_price": channel.get("max_price"),
            "original_price": adjusted_price
        })
        adjusted_price = flt(channel.get("max_price"))
        guardrail_applied = True

    # Check below cost if applicable
    if not channel.get("allow_below_cost") and product_info:
        cost = _get_product_cost(product_info)
        if cost and adjusted_price < flt(cost):
            trace["adjustments"].append({
                "type": "below_cost_prevented",
                "cost": cost,
                "attempted_price": adjusted_price
            })
            adjusted_price = flt(cost)
            guardrail_applied = True

    trace["applied"] = guardrail_applied
    trace["final_price"] = adjusted_price

    return adjusted_price, guardrail_applied, trace


def _get_product_cost(product_info):
    """Get product cost for margin validation

    Args:
        product_info: Product info dict

    Returns:
        Cost or None
    """
    import frappe

    erp_item = product_info.get("erp_item")
    if not erp_item:
        return None

    # Get valuation rate or last purchase rate
    item_data = frappe.db.get_value(
        "Item",
        erp_item,
        ["valuation_rate", "last_purchase_rate"],
        as_dict=True
    )

    if item_data:
        return item_data.get("valuation_rate") or item_data.get("last_purchase_rate")

    return None


# Convenience functions for common use cases

def get_price_for_sku(sku, channel_code=None, customer=None, qty=1, currency=None):
    """Quick price lookup by SKU

    Args:
        sku: Product SKU
        channel_code: Optional sales channel
        customer: Optional customer for contract pricing
        qty: Order quantity
        currency: Target currency

    Returns:
        dict with price result
    """
    return resolve_price(
        sku=sku,
        channel_code=channel_code,
        customer=customer,
        qty=qty,
        currency=currency
    )


def get_bulk_prices(skus, channel_code=None, customer=None, qty=1, currency=None):
    """Get prices for multiple SKUs

    Args:
        skus: List of product SKUs
        channel_code: Optional sales channel
        customer: Optional customer for contract pricing
        qty: Order quantity per item
        currency: Target currency

    Returns:
        dict mapping SKU to price result
    """
    results = {}
    for sku in skus:
        results[sku] = resolve_price(
            sku=sku,
            channel_code=channel_code,
            customer=customer,
            qty=qty,
            currency=currency
        )
    return results


def get_price_breakdown(sku, channel_code=None, customer=None, qty=1, currency=None):
    """Get detailed price breakdown with all layers

    Args:
        sku: Product SKU
        channel_code: Optional sales channel
        customer: Optional customer
        qty: Order quantity
        currency: Target currency

    Returns:
        dict with detailed breakdown
    """
    result = resolve_price(
        sku=sku,
        channel_code=channel_code,
        customer=customer,
        qty=qty,
        currency=currency,
        include_pricing_rules=True,
        include_guardrails=True
    )

    return {
        "sku": sku,
        "channel": channel_code,
        "customer": customer,
        "quantity": qty,
        "currency": result.get("currency"),
        "base_price": result.get("original_price"),
        "final_price": result.get("final_unit_price"),
        "discount_amount": result.get("discount_amount"),
        "discount_percent": result.get("discount_percent"),
        "price_source": result.get("price_layer"),
        "applied_rules": result.get("applied_rules"),
        "guardrail_applied": result.get("guardrail_applied"),
        "resolution_trace": result.get("trace"),
        "is_valid": result.get("is_valid"),
        "messages": result.get("messages")
    }


def validate_price_against_guardrails(price, channel_code, product_variant=None):
    """Validate a price against channel guardrails without full resolution

    Args:
        price: Price to validate
        channel_code: Sales channel code
        product_variant: Optional product variant for cost validation

    Returns:
        dict with validation result
    """
    import frappe
    from frappe.utils import flt

    result = {
        "is_valid": True,
        "warnings": [],
        "adjusted_price": flt(price)
    }

    channel = _get_channel(channel_code)
    if not channel:
        result["warnings"].append("Channel not found")
        return result

    # Check min price
    if channel.get("min_price") and flt(price) < flt(channel.get("min_price")):
        if channel.get("enforce_map"):
            result["is_valid"] = False
            result["adjusted_price"] = flt(channel.get("min_price"))
        result["warnings"].append(
            f"Price {price} is below minimum {channel.get('min_price')}"
        )

    # Check max price
    if channel.get("max_price") and flt(price) > flt(channel.get("max_price")):
        result["is_valid"] = False
        result["adjusted_price"] = flt(channel.get("max_price"))
        result["warnings"].append(
            f"Price {price} exceeds maximum {channel.get('max_price')}"
        )

    # Check cost if product specified
    if product_variant and not channel.get("allow_below_cost"):
        product_info = _get_product_info(product_variant, None)
        if product_info:
            cost = _get_product_cost(product_info)
            if cost and flt(price) < flt(cost):
                result["is_valid"] = False
                result["adjusted_price"] = flt(cost)
                result["warnings"].append(
                    f"Price {price} is below cost {cost}"
                )

    return result
