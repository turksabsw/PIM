# Copyright (c) 2024, Frappe PIM Team and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today, flt, cint


class PriceRule(Document):
    """Price Rule DocType for managing pricing rules and conditions.

    Supports various pricing strategies including:
    - Campaign/promotional pricing
    - Dealer/wholesale pricing
    - Volume discounts
    - Buy X Get Y offers
    - Time-based pricing
    - Customer-specific pricing
    """

    def validate(self):
        """Validate price rule data before saving."""
        self.validate_dates()
        self.validate_pricing_action()
        self.validate_conditions()
        self.validate_applicability()
        self.validate_limits()
        self.validate_coupon_code()
        self.update_status_based_on_dates()

    def validate_dates(self):
        """Validate date ranges."""
        if self.valid_from and self.valid_to:
            if getdate(self.valid_from) > getdate(self.valid_to):
                frappe.throw(
                    _("Valid From date cannot be after Valid To date"),
                    title=_("Invalid Date Range")
                )

        if self.has_time_condition:
            if self.valid_from_time and self.valid_to_time:
                # Note: This is a simple validation, doesn't handle overnight spans
                pass

    def validate_pricing_action(self):
        """Validate pricing action values."""
        if self.pricing_action == "Discount Percentage":
            if not self.discount_percentage:
                frappe.throw(_("Discount Percentage is required"))
            if self.discount_percentage < 0 or self.discount_percentage > 100:
                frappe.throw(_("Discount Percentage must be between 0 and 100"))

        elif self.pricing_action == "Fixed Discount":
            if not self.fixed_discount:
                frappe.throw(_("Fixed Discount Amount is required"))
            if self.fixed_discount < 0:
                frappe.throw(_("Fixed Discount Amount cannot be negative"))

        elif self.pricing_action == "Fixed Price":
            if not self.fixed_price:
                frappe.throw(_("Fixed Price is required"))
            if self.fixed_price < 0:
                frappe.throw(_("Fixed Price cannot be negative"))

        elif self.pricing_action == "Markup Percentage":
            if not self.markup_percentage:
                frappe.throw(_("Markup Percentage is required"))

        elif self.pricing_action == "Price Markup":
            if not self.price_markup:
                frappe.throw(_("Price Markup Amount is required"))

        elif self.pricing_action in ["Free Items", "Buy X Get Y"]:
            if not self.get_quantity or self.get_quantity < 1:
                frappe.throw(_("Get Quantity must be at least 1"))

            if self.pricing_action == "Buy X Get Y":
                if not self.buy_quantity or self.buy_quantity < 1:
                    frappe.throw(_("Buy Quantity must be at least 1"))

    def validate_conditions(self):
        """Validate condition values."""
        if self.has_quantity_condition:
            if self.min_quantity and self.min_quantity < 0:
                frappe.throw(_("Minimum Quantity cannot be negative"))
            if self.max_quantity and self.max_quantity < 0:
                frappe.throw(_("Maximum Quantity cannot be negative"))
            if self.min_quantity and self.max_quantity:
                if self.min_quantity > self.max_quantity:
                    frappe.throw(
                        _("Minimum Quantity cannot be greater than Maximum Quantity")
                    )

        if self.has_value_condition:
            if self.min_value and self.min_value < 0:
                frappe.throw(_("Minimum Value cannot be negative"))
            if self.max_value and self.max_value < 0:
                frappe.throw(_("Maximum Value cannot be negative"))
            if self.min_value and self.max_value:
                if self.min_value > self.max_value:
                    frappe.throw(
                        _("Minimum Value cannot be greater than Maximum Value")
                    )

    def validate_applicability(self):
        """Validate applicability settings."""
        # Ensure the appropriate link field is set based on apply_to
        apply_to_field_map = {
            "Specific Product": "product_master",
            "Product Family": "product_family",
            "Product Category": "product_category",
            "Brand": "brand",
            "Product Collection": "product_collection",
            "Product Series": "product_series",
            "Package Variant": "package_variant"
        }

        if self.apply_to in apply_to_field_map:
            field = apply_to_field_map[self.apply_to]
            if not getattr(self, field, None):
                frappe.throw(
                    _("{0} is required when Apply To is set to {1}").format(
                        frappe.unscrub(field), self.apply_to
                    )
                )

        # Validate customer applicability
        customer_field_map = {
            "Specific Customer": "customer",
            "Customer Group": "customer_group",
            "Territory": "territory",
            "Customer Type": "customer_type"
        }

        if self.customer_applicability in customer_field_map:
            field = customer_field_map[self.customer_applicability]
            if not getattr(self, field, None):
                frappe.throw(
                    _("{0} is required when Customer Applicability is set to {1}").format(
                        frappe.unscrub(field), self.customer_applicability
                    )
                )

    def validate_limits(self):
        """Validate discount limits."""
        if self.max_discount_percentage:
            if self.max_discount_percentage < 0 or self.max_discount_percentage > 100:
                frappe.throw(_("Maximum Discount % must be between 0 and 100"))

        if self.max_discount_amount and self.max_discount_amount < 0:
            frappe.throw(_("Maximum Discount Amount cannot be negative"))

        if self.min_margin_percentage:
            if self.min_margin_percentage < 0 or self.min_margin_percentage > 100:
                frappe.throw(_("Minimum Margin % must be between 0 and 100"))

    def validate_coupon_code(self):
        """Validate coupon code uniqueness if required."""
        if self.requires_coupon and self.coupon_code:
            existing = frappe.db.exists(
                "Price Rule",
                {
                    "coupon_code": self.coupon_code,
                    "name": ["!=", self.name or ""],
                    "enabled": 1
                }
            )
            if existing:
                frappe.throw(
                    _("Coupon code '{0}' is already in use by another active rule").format(
                        self.coupon_code
                    )
                )

    def update_status_based_on_dates(self):
        """Update status based on validity dates."""
        if not self.auto_expire:
            return

        current_date = getdate(today())

        # Check if rule has expired
        if self.valid_to and getdate(self.valid_to) < current_date:
            if self.status not in ["Expired", "Archived"]:
                self.status = "Expired"

        # Check if rule should become active
        if self.status == "Draft" and self.enabled:
            if self.valid_from:
                if getdate(self.valid_from) <= current_date:
                    if not self.valid_to or getdate(self.valid_to) >= current_date:
                        self.status = "Active"
            elif not self.valid_to or getdate(self.valid_to) >= current_date:
                self.status = "Active"

    def before_save(self):
        """Actions before saving the document."""
        # Ensure rule code is uppercase without spaces
        if self.rule_code:
            self.rule_code = self.rule_code.upper().replace(" ", "-")

    def on_update(self):
        """Actions after updating the document."""
        self.clear_pricing_cache()

    def on_trash(self):
        """Actions when deleting the document."""
        self.clear_pricing_cache()

    def clear_pricing_cache(self):
        """Clear any cached pricing data."""
        # Clear cache for affected products/categories
        frappe.cache().delete_key("price_rules")

    def increment_usage(self, customer=None, discount_amount=0):
        """Increment usage statistics.

        Args:
            customer: Customer who used the rule
            discount_amount: Amount of discount given
        """
        self.usage_count = cint(self.usage_count) + 1
        self.total_discount_given = flt(self.total_discount_given) + flt(discount_amount)
        self.last_used_date = today()

        # Track unique customers (simplified - would need proper tracking in production)
        if customer:
            self.unique_customers = cint(self.unique_customers) + 1

        self.db_update()

    def is_applicable(self, product=None, customer=None, quantity=0, value=0):
        """Check if this rule is applicable to the given context.

        Args:
            product: Product Master name
            customer: Customer name
            quantity: Quantity being purchased
            value: Value of the transaction

        Returns:
            Tuple of (is_applicable, reason)
        """
        # Check if enabled and active
        if not self.enabled:
            return False, _("Rule is disabled")

        if self.status != "Active":
            return False, _("Rule is not active")

        # Check date validity
        current_date = getdate(today())
        if self.valid_from and getdate(self.valid_from) > current_date:
            return False, _("Rule not yet valid")

        if self.valid_to and getdate(self.valid_to) < current_date:
            return False, _("Rule has expired")

        # Check usage limits
        if self.max_usage_count and self.usage_count >= self.max_usage_count:
            return False, _("Maximum usage limit reached")

        # Check quantity conditions
        if self.has_quantity_condition:
            if self.min_quantity and quantity < self.min_quantity:
                return False, _("Quantity below minimum")
            if self.max_quantity and quantity > self.max_quantity:
                return False, _("Quantity exceeds maximum")

        # Check value conditions
        if self.has_value_condition:
            if self.min_value and value < self.min_value:
                return False, _("Value below minimum")
            if self.max_value and value > self.max_value:
                return False, _("Value exceeds maximum")

        # Check product applicability
        if product and self.apply_to != "All Products":
            if not self._check_product_applicability(product):
                return False, _("Product not applicable")

        # Check customer applicability
        if customer and self.customer_applicability != "All Customers":
            if not self._check_customer_applicability(customer):
                return False, _("Customer not applicable")

        return True, _("Rule is applicable")

    def _check_product_applicability(self, product):
        """Check if product matches the rule's scope."""
        if self.apply_to == "Specific Product":
            return product == self.product_master

        product_doc = frappe.get_doc("Product Master", product)

        if self.apply_to == "Product Family":
            return product_doc.product_family == self.product_family

        if self.apply_to == "Product Category":
            return product_doc.category == self.product_category

        if self.apply_to == "Brand":
            return product_doc.brand == self.brand

        return True

    def _check_customer_applicability(self, customer):
        """Check if customer matches the rule's scope."""
        if self.customer_applicability == "Specific Customer":
            return customer == self.customer

        customer_doc = frappe.get_doc("Customer", customer)

        if self.customer_applicability == "Customer Group":
            return customer_doc.customer_group == self.customer_group

        if self.customer_applicability == "Territory":
            return customer_doc.territory == self.territory

        return True

    def calculate_discount(self, original_price, quantity=1):
        """Calculate the discounted price based on this rule.

        Args:
            original_price: Original item price
            quantity: Quantity being purchased

        Returns:
            Dictionary with discount details
        """
        discount_amount = 0
        final_price = original_price

        if self.pricing_action == "Discount Percentage":
            discount_amount = original_price * (self.discount_percentage / 100)

        elif self.pricing_action == "Fixed Discount":
            discount_amount = min(self.fixed_discount, original_price)

        elif self.pricing_action == "Fixed Price":
            discount_amount = max(0, original_price - self.fixed_price)
            final_price = self.fixed_price

        elif self.pricing_action == "Markup Percentage":
            markup = original_price * (self.markup_percentage / 100)
            final_price = original_price + markup
            discount_amount = -markup  # Negative discount = markup

        elif self.pricing_action == "Price Markup":
            final_price = original_price + self.price_markup
            discount_amount = -self.price_markup

        # Apply maximum discount limit
        if self.max_discount_amount and discount_amount > self.max_discount_amount:
            discount_amount = self.max_discount_amount

        if self.max_discount_percentage:
            max_discount = original_price * (self.max_discount_percentage / 100)
            if discount_amount > max_discount:
                discount_amount = max_discount

        # Calculate final price if not already set
        if self.pricing_action not in ["Fixed Price", "Markup Percentage", "Price Markup"]:
            final_price = original_price - discount_amount

        # Apply rounding
        if self.round_to and self.round_to > 0:
            final_price = round(final_price / self.round_to) * self.round_to

        return {
            "original_price": original_price,
            "discount_amount": discount_amount,
            "final_price": max(0, final_price),
            "discount_percentage": (discount_amount / original_price * 100) if original_price > 0 else 0,
            "rule_name": self.rule_name,
            "rule_code": self.rule_code
        }


@frappe.whitelist()
def get_applicable_rules(product=None, customer=None, channel=None):
    """Get all applicable price rules for given context.

    Args:
        product: Product Master name
        customer: Customer name
        channel: Channel name

    Returns:
        List of applicable price rules sorted by priority
    """
    filters = {
        "enabled": 1,
        "status": "Active"
    }

    # Get all active rules
    rules = frappe.get_all(
        "Price Rule",
        filters=filters,
        fields=["name", "rule_name", "rule_code", "rule_type", "priority",
                "pricing_action", "discount_percentage", "fixed_discount",
                "fixed_price", "apply_to", "customer_applicability"],
        order_by="priority ASC"
    )

    applicable_rules = []

    for rule_data in rules:
        rule = frappe.get_doc("Price Rule", rule_data.name)
        is_applicable, reason = rule.is_applicable(
            product=product,
            customer=customer
        )

        if is_applicable:
            applicable_rules.append({
                "name": rule.name,
                "rule_name": rule.rule_name,
                "rule_code": rule.rule_code,
                "rule_type": rule.rule_type,
                "priority": rule.priority,
                "pricing_action": rule.pricing_action,
                "discount_percentage": rule.discount_percentage,
                "fixed_discount": rule.fixed_discount,
                "fixed_price": rule.fixed_price
            })

    return applicable_rules


@frappe.whitelist()
def get_best_price(product, original_price, customer=None, quantity=1):
    """Get the best price after applying applicable rules.

    Args:
        product: Product Master name
        original_price: Original item price
        customer: Customer name (optional)
        quantity: Quantity being purchased

    Returns:
        Dictionary with best price details
    """
    original_price = flt(original_price)
    quantity = flt(quantity) or 1

    applicable_rules = get_applicable_rules(product=product, customer=customer)

    if not applicable_rules:
        return {
            "original_price": original_price,
            "final_price": original_price,
            "discount_amount": 0,
            "applied_rules": []
        }

    best_price = original_price
    best_discount = 0
    applied_rules = []

    for rule_data in applicable_rules:
        rule = frappe.get_doc("Price Rule", rule_data["name"])

        # Check if rule is applicable based on quantity and value
        is_applicable, _ = rule.is_applicable(
            product=product,
            customer=customer,
            quantity=quantity,
            value=original_price * quantity
        )

        if not is_applicable:
            continue

        result = rule.calculate_discount(original_price, quantity)

        # Check if this gives a better price
        if result["final_price"] < best_price:
            best_price = result["final_price"]
            best_discount = result["discount_amount"]
            applied_rules = [result]

            # If exclusive rule, stop looking
            if rule.exclusive_rule:
                break

        # If can combine and not exclusive
        elif rule.can_combine and not rule.exclusive_rule:
            # For simplicity, just track additional applicable rules
            applied_rules.append(result)

    return {
        "original_price": original_price,
        "final_price": best_price,
        "discount_amount": best_discount,
        "discount_percentage": (best_discount / original_price * 100) if original_price > 0 else 0,
        "applied_rules": applied_rules
    }


@frappe.whitelist()
def get_price_rule_statistics():
    """Get statistics about price rules.

    Returns:
        Dictionary with rule statistics
    """
    total = frappe.db.count("Price Rule")
    active = frappe.db.count("Price Rule", {"status": "Active", "enabled": 1})
    expired = frappe.db.count("Price Rule", {"status": "Expired"})
    draft = frappe.db.count("Price Rule", {"status": "Draft"})

    # Get rule type distribution
    type_distribution = frappe.db.sql("""
        SELECT rule_type, COUNT(*) as count
        FROM `tabPrice Rule`
        WHERE enabled = 1 AND status = 'Active'
        GROUP BY rule_type
        ORDER BY count DESC
    """, as_dict=True)

    # Get most used rules
    most_used = frappe.get_all(
        "Price Rule",
        filters={"usage_count": [">", 0]},
        fields=["name", "rule_name", "rule_code", "usage_count", "total_discount_given"],
        order_by="usage_count DESC",
        limit=10
    )

    # Get total discount given
    total_discount = frappe.db.sql("""
        SELECT SUM(total_discount_given) as total
        FROM `tabPrice Rule`
    """)[0][0] or 0

    return {
        "total": total,
        "active": active,
        "expired": expired,
        "draft": draft,
        "type_distribution": type_distribution,
        "most_used": most_used,
        "total_discount_given": total_discount
    }


@frappe.whitelist()
def validate_coupon_code(coupon_code, product=None, customer=None):
    """Validate a coupon code and return the associated rule.

    Args:
        coupon_code: Coupon code to validate
        product: Product Master name (optional)
        customer: Customer name (optional)

    Returns:
        Dictionary with validation result
    """
    rule = frappe.db.get_value(
        "Price Rule",
        {
            "coupon_code": coupon_code,
            "requires_coupon": 1,
            "enabled": 1,
            "status": "Active"
        },
        ["name", "rule_name", "discount_percentage", "fixed_discount", "pricing_action"],
        as_dict=True
    )

    if not rule:
        return {
            "valid": False,
            "message": _("Invalid or expired coupon code")
        }

    rule_doc = frappe.get_doc("Price Rule", rule.name)
    is_applicable, reason = rule_doc.is_applicable(
        product=product,
        customer=customer
    )

    if not is_applicable:
        return {
            "valid": False,
            "message": reason
        }

    return {
        "valid": True,
        "rule_name": rule.rule_name,
        "pricing_action": rule.pricing_action,
        "discount_percentage": rule.discount_percentage,
        "fixed_discount": rule.fixed_discount,
        "message": _("Coupon code applied successfully")
    }


@frappe.whitelist()
def bulk_update_status(rule_names, new_status):
    """Bulk update status for multiple price rules.

    Args:
        rule_names: List of rule names or JSON string
        new_status: New status to set

    Returns:
        Number of rules updated
    """
    if isinstance(rule_names, str):
        import json
        rule_names = json.loads(rule_names)

    valid_statuses = ["Draft", "Active", "Paused", "Expired", "Archived"]
    if new_status not in valid_statuses:
        frappe.throw(_("Invalid status: {0}").format(new_status))

    count = 0
    for rule_name in rule_names:
        frappe.db.set_value("Price Rule", rule_name, "status", new_status)
        count += 1

    frappe.db.commit()

    # Clear cache
    frappe.cache().delete_key("price_rules")

    return count


@frappe.whitelist()
def duplicate_rule(rule_name, new_rule_code, new_rule_name=None):
    """Create a copy of an existing price rule.

    Args:
        rule_name: Source rule name
        new_rule_code: Code for the new rule
        new_rule_name: Optional name for the new rule

    Returns:
        Name of the newly created rule
    """
    source = frappe.get_doc("Price Rule", rule_name)

    new_rule = frappe.copy_doc(source)
    new_rule.rule_code = new_rule_code.upper().replace(" ", "-")
    new_rule.rule_name = new_rule_name or f"Copy of {source.rule_name}"
    new_rule.status = "Draft"
    new_rule.usage_count = 0
    new_rule.total_discount_given = 0
    new_rule.last_used_date = None
    new_rule.unique_customers = 0

    # Clear coupon code to avoid duplicates
    new_rule.coupon_code = None

    new_rule.insert()

    return new_rule.name
