"""
Chemical Usage Instruction Controller
Manages chemical mixing ratios, application areas, and safety warnings for products
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today, now_datetime


class ChemicalUsageInstruction(Document):
    def validate(self):
        self.validate_instruction_code()
        self.validate_dates()
        self.validate_mixing_ratios()
        self.validate_concentrations()
        self.validate_temperatures()
        self.validate_product_link()
        self.set_created_by()

    def validate_instruction_code(self):
        """Generate instruction code if not provided"""
        if not self.instruction_code:
            # Generate a code based on product and instruction type
            product_code = ""
            if self.linked_product:
                product_code = frappe.db.get_value(
                    "Product Master", self.linked_product, "product_code"
                ) or ""

            instruction_type_abbrev = {
                "General Use": "GU",
                "Agricultural Application": "AG",
                "Industrial Application": "IN",
                "Domestic Use": "DM",
                "Professional Use": "PR",
                "Dilution Guide": "DL",
                "Mixing Guide": "MX",
                "Safety Protocol": "SF",
                "Emergency Procedure": "EM",
                "Storage Guideline": "ST",
                "Other": "OT"
            }
            type_code = instruction_type_abbrev.get(self.instruction_type, "GU")

            # Generate unique code
            base_code = f"{product_code}-{type_code}" if product_code else type_code

            # Check for existing codes and generate unique one
            existing_count = frappe.db.count(
                "Chemical Usage Instruction",
                filters={"instruction_code": ["like", f"{base_code}%"]}
            )
            self.instruction_code = f"{base_code}-{existing_count + 1:03d}"

    def validate_dates(self):
        """Validate date field consistency"""
        # Check valid_from is not after valid_to
        if self.valid_from and self.valid_to:
            if getdate(self.valid_from) > getdate(self.valid_to):
                frappe.throw(
                    _("Valid From date cannot be after Valid To date"),
                    title=_("Invalid Date Range")
                )

        # Check next_review_date is not too far in the past
        if self.next_review_date:
            if getdate(self.next_review_date) < getdate(today()):
                frappe.msgprint(
                    _("Next Review Date is in the past. Consider updating it."),
                    indicator="orange",
                    title=_("Review Date Warning")
                )

    def validate_mixing_ratios(self):
        """Validate mixing ratio fields"""
        # Check that quantities make sense
        if self.product_quantity is not None and self.product_quantity < 0:
            frappe.throw(
                _("Product Quantity cannot be negative"),
                title=_("Invalid Quantity")
            )

        if self.diluent_quantity is not None and self.diluent_quantity < 0:
            frappe.throw(
                _("Diluent Quantity cannot be negative"),
                title=_("Invalid Quantity")
            )

        # Validate dilution ratio format if provided
        if self.dilution_ratio:
            import re
            pattern = r'^\d+:\d+$'
            if not re.match(pattern, self.dilution_ratio.strip()):
                frappe.msgprint(
                    _("Dilution ratio should be in format 'X:Y' (e.g., '1:100')"),
                    indicator="orange",
                    title=_("Format Suggestion")
                )

    def validate_concentrations(self):
        """Validate concentration percentages"""
        # Check concentration is within valid range
        if self.concentration_percentage is not None:
            if self.concentration_percentage < 0 or self.concentration_percentage > 100:
                frappe.throw(
                    _("Concentration percentage must be between 0 and 100"),
                    title=_("Invalid Concentration")
                )

        # Check min/max concentrations
        if self.minimum_concentration is not None:
            if self.minimum_concentration < 0 or self.minimum_concentration > 100:
                frappe.throw(
                    _("Minimum concentration must be between 0 and 100"),
                    title=_("Invalid Concentration")
                )

        if self.maximum_concentration is not None:
            if self.maximum_concentration < 0 or self.maximum_concentration > 100:
                frappe.throw(
                    _("Maximum concentration must be between 0 and 100"),
                    title=_("Invalid Concentration")
                )

        # Check min is not greater than max
        if (self.minimum_concentration is not None and
            self.maximum_concentration is not None and
            self.minimum_concentration > self.maximum_concentration):
            frappe.throw(
                _("Minimum concentration cannot be greater than maximum concentration"),
                title=_("Invalid Concentration Range")
            )

    def validate_temperatures(self):
        """Validate temperature fields"""
        if (self.min_temperature_celsius is not None and
            self.max_temperature_celsius is not None):
            if self.min_temperature_celsius > self.max_temperature_celsius:
                frappe.throw(
                    _("Minimum temperature cannot be greater than maximum temperature"),
                    title=_("Invalid Temperature Range")
                )

        # Warn about extreme temperatures
        if self.max_temperature_celsius is not None and self.max_temperature_celsius > 50:
            frappe.msgprint(
                _("Maximum temperature seems high ({0}C). Please verify.").format(
                    self.max_temperature_celsius
                ),
                indicator="orange",
                title=_("Temperature Warning")
            )

        if self.min_temperature_celsius is not None and self.min_temperature_celsius < -20:
            frappe.msgprint(
                _("Minimum temperature seems low ({0}C). Please verify.").format(
                    self.min_temperature_celsius
                ),
                indicator="orange",
                title=_("Temperature Warning")
            )

    def validate_product_link(self):
        """Validate product link and related fields"""
        # Check if linked variant belongs to linked product
        if self.linked_product and self.linked_variant:
            variant_product = frappe.db.get_value(
                "Product Variant", self.linked_variant, "product"
            )
            if variant_product and variant_product != self.linked_product:
                frappe.throw(
                    _("Selected variant does not belong to the linked product"),
                    title=_("Invalid Variant")
                )

    def set_created_by(self):
        """Set the created_by_user field"""
        if self.is_new() and not self.created_by_user:
            self.created_by_user = frappe.session.user

    def before_save(self):
        """Prepare data before saving"""
        self.update_approval_status()
        self.increment_version_if_changed()

    def update_approval_status(self):
        """Update approval-related fields based on status changes"""
        if self.has_value_changed("status"):
            if self.status == "Approved":
                self.approved_by = frappe.session.user
                self.approval_date = today()
            elif self.status in ["Draft", "Under Review"]:
                # Clear approval info if going back to draft/review
                if self.get_doc_before_save() and \
                   self.get_doc_before_save().status == "Approved":
                    self.approved_by = None
                    self.approval_date = None

    def increment_version_if_changed(self):
        """Increment version number if significant fields changed"""
        if not self.is_new():
            significant_fields = [
                "mixing_ratio_description", "product_quantity", "diluent_quantity",
                "concentration_percentage", "dilution_ratio", "application_rate",
                "safety_warnings", "mixing_instructions", "application_instructions"
            ]

            for field in significant_fields:
                if self.has_value_changed(field):
                    self.version = (self.version or 1) + 1
                    break

    def on_update(self):
        """Handle post-update actions"""
        self.invalidate_cache()

    def on_trash(self):
        """Cleanup before deletion"""
        self.invalidate_cache()

    def invalidate_cache(self):
        """Clear relevant caches"""
        try:
            frappe.cache().delete_key(f"pim:chemical_instruction:{self.name}")
            if self.linked_product:
                frappe.cache().delete_key(
                    f"pim:product_instructions:{self.linked_product}"
                )
            if self.linked_product_family:
                frappe.cache().delete_key(
                    f"pim:family_instructions:{self.linked_product_family}"
                )
        except Exception:
            pass

    @frappe.whitelist()
    def mark_reviewed(self, notes=None):
        """Mark the instruction as reviewed"""
        self.last_review_date = today()
        self.reviewed_by = frappe.session.user

        if notes:
            existing_notes = self.internal_notes or ""
            self.internal_notes = f"{existing_notes}\n\n[Reviewed on {today()}]\n{notes}"

        self.save()

        return {
            "status": "success",
            "message": _("Instruction marked as reviewed")
        }

    @frappe.whitelist()
    def approve_instruction(self, notes=None):
        """Approve the instruction"""
        if self.status == "Approved":
            frappe.throw(_("Instruction is already approved"))

        self.status = "Approved"
        self.approved_by = frappe.session.user
        self.approval_date = today()

        if notes:
            existing_notes = self.internal_notes or ""
            self.internal_notes = f"{existing_notes}\n\n[Approved on {today()}]\n{notes}"

        self.save()

        return {
            "status": "success",
            "message": _("Instruction approved successfully")
        }

    @frappe.whitelist()
    def deprecate_instruction(self, replacement_instruction=None, notes=None):
        """Deprecate the instruction"""
        self.status = "Deprecated"

        note_text = f"[Deprecated on {today()}]"
        if replacement_instruction:
            note_text += f"\nReplaced by: {replacement_instruction}"
        if notes:
            note_text += f"\n{notes}"

        existing_notes = self.internal_notes or ""
        self.internal_notes = f"{existing_notes}\n\n{note_text}"

        self.save()

        return {
            "status": "success",
            "message": _("Instruction deprecated successfully")
        }

    @frappe.whitelist()
    def duplicate_instruction(self, new_title=None):
        """Create a duplicate of this instruction"""
        new_doc = frappe.copy_doc(self)
        new_doc.instruction_title = new_title or f"{self.instruction_title} (Copy)"
        new_doc.instruction_code = None  # Will be auto-generated
        new_doc.status = "Draft"
        new_doc.version = 1
        new_doc.approved_by = None
        new_doc.approval_date = None
        new_doc.reviewed_by = None
        new_doc.last_review_date = None
        new_doc.created_by_user = frappe.session.user
        new_doc.insert()

        return {
            "status": "success",
            "message": _("Instruction duplicated successfully"),
            "new_instruction": new_doc.name
        }


@frappe.whitelist()
def get_product_instructions(
    product=None,
    product_family=None,
    instruction_type=None,
    status=None,
    hazard_level=None,
    limit=20,
    offset=0
):
    """Get chemical usage instructions with optional filtering

    Args:
        product: Filter by linked product
        product_family: Filter by product family
        instruction_type: Filter by instruction type
        status: Filter by status
        hazard_level: Filter by hazard level
        limit: Maximum results to return
        offset: Results offset for pagination
    """
    filters = {}

    if product:
        filters["linked_product"] = product
    if product_family:
        filters["linked_product_family"] = product_family
    if instruction_type:
        filters["instruction_type"] = instruction_type
    if status:
        filters["status"] = status
    if hazard_level:
        filters["hazard_level"] = hazard_level

    return frappe.get_all(
        "Chemical Usage Instruction",
        filters=filters,
        fields=[
            "name", "instruction_title", "instruction_code", "instruction_type",
            "status", "hazard_level", "linked_product", "linked_product_family",
            "usage_scenario", "target_application", "dilution_ratio",
            "concentration_percentage", "application_method",
            "valid_from", "valid_to", "creation", "modified"
        ],
        order_by="creation desc",
        limit_start=offset,
        limit_page_length=limit
    )


@frappe.whitelist()
def get_instructions_for_product(product, include_family=True, active_only=True):
    """Get all usage instructions for a specific product

    Args:
        product: Product name to get instructions for
        include_family: Also include family-level instructions
        active_only: Only return active/approved instructions
    """
    if not product:
        frappe.throw(_("Product is required"))

    conditions = []
    params = []

    # Build conditions for product
    conditions.append("linked_product = %s")
    params.append(product)

    # Include family instructions if requested
    if include_family:
        product_family = frappe.db.get_value(
            "Product Master", product, "product_family"
        )
        if product_family:
            conditions.append(
                "(linked_product_family = %s AND applies_to_all_variants = 1)"
            )
            params.append(product_family)

    # Status filter
    if active_only:
        status_condition = "status IN ('Active', 'Approved')"
    else:
        status_condition = "status != 'Archived'"

    where_clause = f"({' OR '.join(conditions)}) AND {status_condition}"

    return frappe.db.sql(f"""
        SELECT
            name, instruction_title, instruction_code, instruction_type,
            status, hazard_level, usage_scenario, target_application,
            mixing_ratio_description, dilution_ratio, concentration_percentage,
            application_rate, application_rate_uom, application_method,
            safety_warnings, ppe_required, signal_word,
            valid_from, valid_to, version, creation
        FROM `tabChemical Usage Instruction`
        WHERE {where_clause}
        ORDER BY
            FIELD(hazard_level, 'Extreme', 'Very High', 'High', 'Moderate', 'Low'),
            instruction_type,
            creation DESC
    """, params, as_dict=True)


@frappe.whitelist()
def get_instruction_statistics(product=None, product_family=None):
    """Get statistics about chemical usage instructions

    Args:
        product: Product name to get statistics for
        product_family: Product family name to get statistics for
    """
    conditions = ["status != 'Archived'"]
    params = []

    if product:
        conditions.append("linked_product = %s")
        params.append(product)
    elif product_family:
        conditions.append("linked_product_family = %s")
        params.append(product_family)

    where_clause = " AND ".join(conditions)

    stats = frappe.db.sql(f"""
        SELECT
            COUNT(*) as total_instructions,
            SUM(CASE WHEN status = 'Active' THEN 1 ELSE 0 END) as active_count,
            SUM(CASE WHEN status = 'Approved' THEN 1 ELSE 0 END) as approved_count,
            SUM(CASE WHEN status = 'Draft' THEN 1 ELSE 0 END) as draft_count,
            SUM(CASE WHEN status = 'Deprecated' THEN 1 ELSE 0 END) as deprecated_count,
            SUM(CASE WHEN hazard_level = 'High' THEN 1 ELSE 0 END) as high_hazard,
            SUM(CASE WHEN hazard_level = 'Very High' THEN 1 ELSE 0 END) as very_high_hazard,
            SUM(CASE WHEN hazard_level = 'Extreme' THEN 1 ELSE 0 END) as extreme_hazard,
            SUM(CASE WHEN instruction_type = 'Mixing Guide' THEN 1 ELSE 0 END) as mixing_guides,
            SUM(CASE WHEN instruction_type = 'Dilution Guide' THEN 1 ELSE 0 END) as dilution_guides,
            SUM(CASE WHEN instruction_type = 'Safety Protocol' THEN 1 ELSE 0 END) as safety_protocols
        FROM `tabChemical Usage Instruction`
        WHERE {where_clause}
    """, params, as_dict=True)

    return stats[0] if stats else {}


@frappe.whitelist()
def get_high_hazard_instructions(limit=10):
    """Get instructions with high or extreme hazard levels

    Args:
        limit: Maximum results to return
    """
    return frappe.get_all(
        "Chemical Usage Instruction",
        filters={
            "status": ["in", ["Active", "Approved"]],
            "hazard_level": ["in", ["High", "Very High", "Extreme"]]
        },
        fields=[
            "name", "instruction_title", "instruction_code", "instruction_type",
            "status", "hazard_level", "linked_product", "linked_product_family",
            "usage_scenario", "signal_word", "ppe_required", "primary_hazards",
            "creation"
        ],
        order_by="FIELD(hazard_level, 'Extreme', 'Very High', 'High'), creation desc",
        limit_page_length=limit
    )


@frappe.whitelist()
def get_instructions_needing_review(days_ahead=30, limit=20):
    """Get instructions due for review within specified days

    Args:
        days_ahead: Number of days to look ahead (default: 30)
        limit: Maximum results to return
    """
    from frappe.utils import add_days

    review_date_limit = add_days(today(), days_ahead)

    return frappe.get_all(
        "Chemical Usage Instruction",
        filters={
            "status": ["not in", ["Draft", "Archived", "Deprecated"]],
            "next_review_date": ["<=", review_date_limit],
            "next_review_date": [">=", today()]
        },
        fields=[
            "name", "instruction_title", "instruction_code", "instruction_type",
            "status", "hazard_level", "linked_product", "linked_product_family",
            "next_review_date", "last_review_date", "reviewed_by", "version"
        ],
        order_by="next_review_date asc",
        limit_page_length=limit
    )


@frappe.whitelist()
def search_instructions_by_scenario(search_term, limit=20):
    """Search instructions by usage scenario, target pests, or target crops

    Args:
        search_term: Text to search for
        limit: Maximum results to return
    """
    if not search_term:
        return []

    search_pattern = f"%{search_term}%"

    return frappe.db.sql("""
        SELECT
            name, instruction_title, instruction_code, instruction_type,
            status, hazard_level, linked_product, linked_product_family,
            usage_scenario, target_application, target_pests, target_crops,
            creation
        FROM `tabChemical Usage Instruction`
        WHERE
            status NOT IN ('Archived', 'Deprecated')
            AND (
                usage_scenario LIKE %s
                OR target_pests LIKE %s
                OR target_crops LIKE %s
                OR instruction_title LIKE %s
            )
        ORDER BY creation DESC
        LIMIT %s
    """, (search_pattern, search_pattern, search_pattern, search_pattern, limit),
        as_dict=True)


@frappe.whitelist()
def bulk_update_status(instruction_list, new_status, notes=None):
    """Update status for multiple instruction records

    Args:
        instruction_list: JSON string of list of instruction names
        new_status: New status to set
        notes: Optional notes for the status change
    """
    import json

    if isinstance(instruction_list, str):
        instruction_list = json.loads(instruction_list)

    valid_statuses = ["Draft", "Active", "Under Review", "Approved", "Deprecated", "Archived"]
    if new_status not in valid_statuses:
        frappe.throw(_("Invalid status: {0}").format(new_status))

    updated = []
    for instruction_name in instruction_list:
        try:
            doc = frappe.get_doc("Chemical Usage Instruction", instruction_name)
            doc.status = new_status
            if notes:
                existing_notes = doc.internal_notes or ""
                doc.internal_notes = (
                    f"{existing_notes}\n\n"
                    f"[Status changed to {new_status} on {today()}]\n{notes}"
                )
            doc.save()
            updated.append(instruction_name)
        except Exception as e:
            frappe.log_error(
                message=f"Error updating instruction {instruction_name}: {str(e)}",
                title="Bulk Status Update Error"
            )

    return {
        "status": "success",
        "updated_count": len(updated),
        "updated": updated
    }


@frappe.whitelist()
def calculate_dilution(
    product_quantity,
    diluent_quantity,
    target_volume=None
):
    """Calculate dilution ratio and concentration

    Args:
        product_quantity: Amount of product
        diluent_quantity: Amount of diluent
        target_volume: Optional target final volume for scaling
    """
    try:
        product_qty = float(product_quantity)
        diluent_qty = float(diluent_quantity)
    except (ValueError, TypeError):
        frappe.throw(_("Invalid quantity values"))

    if product_qty <= 0 or diluent_qty <= 0:
        frappe.throw(_("Quantities must be greater than zero"))

    total_volume = product_qty + diluent_qty
    concentration = (product_qty / total_volume) * 100

    # Calculate ratio (normalize to 1:X format)
    if product_qty <= diluent_qty:
        ratio = f"1:{int(diluent_qty / product_qty)}"
    else:
        ratio = f"{int(product_qty / diluent_qty)}:1"

    result = {
        "concentration_percentage": round(concentration, 4),
        "dilution_ratio": ratio,
        "total_volume": total_volume,
        "product_percentage": round(concentration, 2),
        "diluent_percentage": round(100 - concentration, 2)
    }

    # Scale to target volume if provided
    if target_volume:
        try:
            target_vol = float(target_volume)
            scale_factor = target_vol / total_volume
            result["scaled_product_quantity"] = round(product_qty * scale_factor, 4)
            result["scaled_diluent_quantity"] = round(diluent_qty * scale_factor, 4)
            result["target_volume"] = target_vol
        except (ValueError, TypeError):
            pass

    return result
