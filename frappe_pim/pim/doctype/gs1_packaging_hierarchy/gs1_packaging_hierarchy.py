"""
GS1 Packaging Hierarchy Controller

Manages multi-level packaging hierarchy for products following GS1/GDSN standards.
Supports packaging levels: Base Unit (Each), Inner Pack, Case, and Pallet.

Each level can have its own GTIN, dimensions, weight, and quantity relationships.
The hierarchy follows GS1 Global Trade Item Number (GTIN) standards:
- Base unit: GTIN-13 or GTIN-14 with indicator digit 0
- Higher levels: GTIN-14 with indicator digits 1-9
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt


class GS1PackagingHierarchy(Document):
    """GS1 Packaging Hierarchy DocType controller.

    Manages packaging levels (each, inner, case, pallet) with GTIN validation
    and automatic quantity calculations per GS1/GDSN standards.
    """

    def validate(self):
        """Validate the packaging hierarchy before save."""
        self.validate_gtins()
        self.validate_quantities()
        self.validate_packaging_levels()
        self.calculate_totals()
        self.set_hierarchy_levels()
        self.run_gs1_validation()

    def validate_gtins(self):
        """Validate all GTINs in the hierarchy using GS1 standards."""
        from frappe_pim.pim.utils.gs1_validation import validate_gtin, validate_gtin14

        errors = []

        # Validate base unit GTIN (required)
        if self.base_unit_gtin:
            result = validate_gtin(self.base_unit_gtin)
            if not result.is_valid:
                errors.append(_("Base Unit GTIN: {0}").format(
                    ", ".join(result.errors)
                ))

        # Validate inner pack GTIN if enabled
        if self.has_inner_pack and self.inner_pack_gtin:
            result = validate_gtin14(self.inner_pack_gtin)
            if not result.is_valid:
                errors.append(_("Inner Pack GTIN: {0}").format(
                    ", ".join(result.errors)
                ))
            # Check indicator digit
            self._validate_gtin14_indicator(
                self.inner_pack_gtin,
                "Inner Pack",
                errors
            )

        # Validate case GTIN if enabled
        if self.has_case and self.case_gtin:
            result = validate_gtin14(self.case_gtin)
            if not result.is_valid:
                errors.append(_("Case GTIN: {0}").format(
                    ", ".join(result.errors)
                ))
            # Check indicator digit
            self._validate_gtin14_indicator(
                self.case_gtin,
                "Case",
                errors,
                expected_indicator=self.case_indicator_digit
            )

        # Validate pallet GTIN if enabled (optional for pallet level)
        if self.has_pallet and self.pallet_gtin:
            result = validate_gtin14(self.pallet_gtin)
            if not result.is_valid:
                errors.append(_("Pallet GTIN: {0}").format(
                    ", ".join(result.errors)
                ))
            # Check indicator digit
            self._validate_gtin14_indicator(
                self.pallet_gtin,
                "Pallet",
                errors,
                expected_indicator=self.pallet_indicator_digit
            )

        # Check for duplicate GTINs
        gtins = [
            self.base_unit_gtin,
            self.inner_pack_gtin if self.has_inner_pack else None,
            self.case_gtin if self.has_case else None,
            self.pallet_gtin if self.has_pallet else None,
        ]
        gtins = [g for g in gtins if g]
        if len(gtins) != len(set(gtins)):
            errors.append(_("Duplicate GTINs detected in packaging hierarchy"))

        if errors:
            frappe.throw(
                _("GTIN Validation Errors:<br>") + "<br>".join(errors),
                title=_("GS1 Validation Error")
            )

    def _validate_gtin14_indicator(
        self,
        gtin: str,
        level_name: str,
        errors: list,
        expected_indicator: str = None
    ):
        """Validate GTIN-14 indicator digit.

        GTIN-14 first digit (indicator) meanings:
        - 0: Standard GTIN expressed in 14-digit format
        - 1-8: Different packaging levels
        - 9: Variable measure trade items

        Args:
            gtin: The GTIN-14 to validate
            level_name: Name of the packaging level for error messages
            errors: List to append errors to
            expected_indicator: Expected indicator digit if specified
        """
        if not gtin or len(gtin) != 14:
            return

        indicator = gtin[0]

        if indicator == "0":
            errors.append(
                _("{0} GTIN should have indicator digit 1-9 for packaging levels, "
                  "not 0 (which represents base trade item)").format(level_name)
            )

        if expected_indicator and indicator != expected_indicator:
            errors.append(
                _("{0} GTIN indicator digit ({1}) does not match "
                  "selected indicator ({2})").format(
                    level_name, indicator, expected_indicator
                )
            )

    def validate_quantities(self):
        """Validate packaging quantities are positive integers."""
        if self.has_inner_pack:
            if not self.inner_pack_quantity or cint(self.inner_pack_quantity) <= 0:
                frappe.throw(
                    _("Inner Pack quantity must be a positive integer"),
                    title=_("Invalid Quantity")
                )

        if self.has_case:
            if not self.case_quantity or cint(self.case_quantity) <= 0:
                frappe.throw(
                    _("Case quantity must be a positive integer"),
                    title=_("Invalid Quantity")
                )

        if self.has_pallet:
            if not self.pallet_quantity or cint(self.pallet_quantity) <= 0:
                frappe.throw(
                    _("Pallet quantity (cases per pallet) must be a positive integer"),
                    title=_("Invalid Quantity")
                )

    def validate_packaging_levels(self):
        """Validate that packaging levels follow logical hierarchy.

        - Cannot have pallet without case
        - Indicator digits should increase with packaging level
        """
        # Pallet requires case
        if self.has_pallet and not self.has_case:
            frappe.throw(
                _("Pallet level requires Case level to be enabled"),
                title=_("Invalid Hierarchy")
            )

        # Validate indicator digit sequence
        indicators = []
        if self.has_inner_pack and self.inner_pack_gtin:
            indicators.append(("Inner Pack", cint(self.inner_pack_gtin[0]) if self.inner_pack_gtin else 0))
        if self.has_case and self.case_gtin:
            indicators.append(("Case", cint(self.case_gtin[0]) if self.case_gtin else 0))
        if self.has_pallet and self.pallet_gtin:
            indicators.append(("Pallet", cint(self.pallet_gtin[0]) if self.pallet_gtin else 0))

        # Check that indicator digits increase (or allow same if not specified)
        for i in range(1, len(indicators)):
            if indicators[i][1] > 0 and indicators[i-1][1] > 0:
                if indicators[i][1] <= indicators[i-1][1]:
                    frappe.msgprint(
                        _("Warning: {0} indicator digit ({1}) should be greater than "
                          "{2} indicator digit ({3}) for proper hierarchy").format(
                            indicators[i][0], indicators[i][1],
                            indicators[i-1][0], indicators[i-1][1]
                        ),
                        title=_("Indicator Digit Warning"),
                        indicator="orange"
                    )

    def calculate_totals(self):
        """Calculate total base units per case and per pallet."""
        # Base units per inner pack
        inner_qty = cint(self.inner_pack_quantity) if self.has_inner_pack else 1

        # Calculate base units per case
        if self.has_case:
            case_qty = cint(self.case_quantity)
            if self.has_inner_pack:
                # Case contains inner packs
                self.total_base_units_per_case = inner_qty * case_qty
            else:
                # Case contains base units directly
                self.total_base_units_per_case = case_qty
        else:
            self.total_base_units_per_case = 0

        # Calculate base units per pallet
        if self.has_pallet and self.has_case:
            pallet_qty = cint(self.pallet_quantity)
            self.total_base_units_per_pallet = (
                self.total_base_units_per_case * pallet_qty
            )
        else:
            self.total_base_units_per_pallet = 0

    def set_hierarchy_levels(self):
        """Count and set the number of packaging levels."""
        levels = 1  # Base unit is always level 1

        if self.has_inner_pack:
            levels += 1
        if self.has_case:
            levels += 1
        if self.has_pallet:
            levels += 1

        self.hierarchy_levels = levels

    def run_gs1_validation(self):
        """Run comprehensive GS1 validation and set status."""
        errors = []

        # Check required fields based on enabled levels
        if self.has_inner_pack:
            if not self.inner_pack_gtin:
                errors.append(_("Inner Pack GTIN is required when Inner Pack is enabled"))
            if not self.inner_pack_quantity:
                errors.append(_("Inner Pack quantity is required"))

        if self.has_case:
            if not self.case_gtin:
                errors.append(_("Case GTIN is required when Case is enabled"))
            if not self.case_quantity:
                errors.append(_("Case quantity is required"))

        if self.has_pallet:
            if not self.pallet_quantity:
                errors.append(_("Pallet quantity (cases per pallet) is required"))

        # Validate dimensions are positive
        dimension_fields = [
            ("base_unit", ["length", "width", "height", "gross_weight", "net_weight"]),
        ]
        if self.has_inner_pack:
            dimension_fields.append(
                ("inner_pack", ["length", "width", "height", "gross_weight", "net_weight"])
            )
        if self.has_case:
            dimension_fields.append(
                ("case", ["length", "width", "height", "gross_weight", "net_weight"])
            )
        if self.has_pallet:
            dimension_fields.append(
                ("pallet", ["length", "width", "height", "gross_weight", "net_weight"])
            )

        for prefix, fields in dimension_fields:
            for field in fields:
                field_name = f"{prefix}_{field}"
                value = self.get(field_name)
                if value and flt(value) < 0:
                    errors.append(
                        _("{0} {1} cannot be negative").format(
                            prefix.replace("_", " ").title(),
                            field.replace("_", " ")
                        )
                    )

        # Validate weight consistency
        # Net weight should not exceed gross weight
        for prefix in ["base_unit", "inner_pack", "case", "pallet"]:
            if prefix != "base_unit":
                check_field = f"has_{prefix.replace('_pack', '')}"
                if prefix == "inner_pack":
                    check_field = "has_inner_pack"
                if not self.get(check_field):
                    continue

            gross = flt(self.get(f"{prefix}_gross_weight"))
            net = flt(self.get(f"{prefix}_net_weight"))

            if gross > 0 and net > 0 and net > gross:
                errors.append(
                    _("{0}: Net weight ({1} kg) exceeds gross weight ({2} kg)").format(
                        prefix.replace("_", " ").title(), net, gross
                    )
                )

        # Set validation status
        if errors:
            self.validation_status = "Invalid"
            self.validation_errors = "\n".join(errors)
        else:
            self.validation_status = "Valid"
            self.validation_errors = None

    def on_update(self):
        """Actions after saving the hierarchy."""
        # Update product's packaging info if needed
        if self.product and self.status == "Active":
            self.set_as_default_hierarchy()

    def set_as_default_hierarchy(self):
        """Set this as the default packaging hierarchy for the product.

        Deactivates other hierarchies for the same product/market combination.
        """
        if not self.product or self.status != "Active":
            return

        # Find other active hierarchies for same product and market
        filters = {
            "product": self.product,
            "status": "Active",
            "name": ["!=", self.name]
        }
        if self.target_market:
            filters["target_market"] = self.target_market

        other_hierarchies = frappe.get_all(
            "GS1 Packaging Hierarchy",
            filters=filters,
            pluck="name"
        )

        # Deprecate others
        for hierarchy_name in other_hierarchies:
            frappe.db.set_value(
                "GS1 Packaging Hierarchy",
                hierarchy_name,
                "status",
                "Deprecated",
                update_modified=False
            )

        if other_hierarchies:
            frappe.msgprint(
                _("Deprecated {0} other packaging hierarchies for this product").format(
                    len(other_hierarchies)
                ),
                indicator="blue"
            )

    def before_submit(self):
        """Validate before submission."""
        if self.validation_status != "Valid":
            frappe.throw(
                _("Cannot submit packaging hierarchy with validation errors"),
                title=_("Validation Required")
            )


# =============================================================================
# API Functions
# =============================================================================

@frappe.whitelist()
def get_product_packaging_hierarchy(product: str, target_market: str = None):
    """Get the active packaging hierarchy for a product.

    Args:
        product: Product Master name
        target_market: Optional target market country

    Returns:
        dict: Packaging hierarchy data or None
    """
    filters = {
        "product": product,
        "status": "Active"
    }
    if target_market:
        filters["target_market"] = target_market

    hierarchy = frappe.get_all(
        "GS1 Packaging Hierarchy",
        filters=filters,
        order_by="modified desc",
        limit=1
    )

    if hierarchy:
        return frappe.get_doc("GS1 Packaging Hierarchy", hierarchy[0].name).as_dict()

    return None


@frappe.whitelist()
def validate_hierarchy_gtin(gtin: str, level: str = "base"):
    """Validate a GTIN for a specific packaging level.

    Args:
        gtin: GTIN string to validate
        level: Packaging level (base, inner, case, pallet)

    Returns:
        dict: Validation result
    """
    from frappe_pim.pim.utils.gs1_validation import validate_gtin, validate_gtin14

    if level == "base":
        result = validate_gtin(gtin)
    else:
        result = validate_gtin14(gtin)

    response = result.to_dict()

    # Add level-specific guidance
    if level != "base" and result.is_valid:
        indicator = gtin[0] if len(gtin) == 14 else None
        response["indicator_digit"] = indicator

        level_recommendations = {
            "inner": "1-3",
            "case": "4-6",
            "pallet": "7-9"
        }
        response["recommended_indicator_range"] = level_recommendations.get(level, "1-9")

    return response


@frappe.whitelist()
def calculate_packaging_totals(
    has_inner_pack: bool,
    inner_pack_quantity: int,
    has_case: bool,
    case_quantity: int,
    has_pallet: bool,
    pallet_quantity: int
):
    """Calculate total quantities across packaging levels.

    Args:
        has_inner_pack: Whether inner pack level is enabled
        inner_pack_quantity: Base units per inner pack
        has_case: Whether case level is enabled
        case_quantity: Inner packs (or base units) per case
        has_pallet: Whether pallet level is enabled
        pallet_quantity: Cases per pallet

    Returns:
        dict: Calculated totals
    """
    has_inner_pack = cint(has_inner_pack)
    inner_pack_quantity = cint(inner_pack_quantity)
    has_case = cint(has_case)
    case_quantity = cint(case_quantity)
    has_pallet = cint(has_pallet)
    pallet_quantity = cint(pallet_quantity)

    # Calculate base units per case
    if has_case:
        if has_inner_pack:
            base_units_per_case = inner_pack_quantity * case_quantity
        else:
            base_units_per_case = case_quantity
    else:
        base_units_per_case = 0

    # Calculate base units per pallet
    if has_pallet and has_case:
        base_units_per_pallet = base_units_per_case * pallet_quantity
    else:
        base_units_per_pallet = 0

    # Count hierarchy levels
    levels = 1  # Base unit
    if has_inner_pack:
        levels += 1
    if has_case:
        levels += 1
    if has_pallet:
        levels += 1

    return {
        "total_base_units_per_case": base_units_per_case,
        "total_base_units_per_pallet": base_units_per_pallet,
        "hierarchy_levels": levels,
        "inner_packs_per_case": case_quantity if has_inner_pack and has_case else 0,
        "cases_per_pallet": pallet_quantity if has_pallet else 0
    }


@frappe.whitelist()
def generate_gtin14_for_level(base_gtin: str, indicator_digit: str):
    """Generate a GTIN-14 for a packaging level based on base GTIN.

    Args:
        base_gtin: Base unit GTIN (GTIN-13 or GTIN-14 with indicator 0)
        indicator_digit: Indicator digit for the new packaging level (1-9)

    Returns:
        dict: Generated GTIN-14 or error
    """
    from frappe_pim.pim.utils.gs1_validation import (
        validate_gtin,
        normalize_gtin,
        calculate_check_digit
    )

    # Validate base GTIN
    result = validate_gtin(base_gtin)
    if not result.is_valid:
        return {
            "success": False,
            "error": _("Invalid base GTIN: {0}").format(", ".join(result.errors))
        }

    # Normalize to 14 digits
    normalized = normalize_gtin(result.normalized, 14)
    if not normalized:
        return {
            "success": False,
            "error": _("Could not normalize GTIN to 14 digits")
        }

    # Validate indicator digit
    indicator = str(indicator_digit)
    if not indicator.isdigit() or int(indicator) < 1 or int(indicator) > 9:
        return {
            "success": False,
            "error": _("Indicator digit must be 1-9 for packaging levels")
        }

    # Replace first digit (indicator) and recalculate check digit
    data_digits = indicator + normalized[1:-1]  # New indicator + digits without check
    check_digit = calculate_check_digit(data_digits)

    new_gtin = data_digits + check_digit

    return {
        "success": True,
        "gtin14": new_gtin,
        "indicator_digit": indicator,
        "check_digit": check_digit
    }


@frappe.whitelist()
def get_packaging_hierarchy_summary(product: str):
    """Get a summary of all packaging hierarchies for a product.

    Args:
        product: Product Master name

    Returns:
        list: Summary of packaging hierarchies
    """
    hierarchies = frappe.get_all(
        "GS1 Packaging Hierarchy",
        filters={"product": product},
        fields=[
            "name",
            "hierarchy_name",
            "status",
            "target_market",
            "base_unit_gtin",
            "has_inner_pack",
            "has_case",
            "has_pallet",
            "total_base_units_per_case",
            "total_base_units_per_pallet",
            "hierarchy_levels",
            "validation_status",
            "modified"
        ],
        order_by="modified desc"
    )

    return hierarchies
