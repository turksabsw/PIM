# Copyright (c) 2024, Frappe PIM Team and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class PackageVariant(Document):
    """Package Variant DocType for managing different pack sizes with separate barcodes.

    Represents packaging configurations like 6-pack, 12-pack, case, pallet, etc.
    Each package variant can have its own barcodes, pricing, and content.
    """

    def validate(self):
        """Validate package variant data before saving."""
        self.validate_product_links()
        self.validate_dates()
        self.validate_weights()
        self.validate_default_package()
        self.validate_replacement_package()
        self.calculate_derived_fields()

    def validate_product_links(self):
        """Ensure at least one product link is provided."""
        if not self.product_master and not self.product_variant:
            frappe.throw(
                _("Either Product Master or Product Variant must be specified"),
                title=_("Missing Product Link")
            )

        # If product_variant is set, auto-fill product_master from variant
        if self.product_variant and not self.product_master:
            variant_doc = frappe.get_doc("Product Variant", self.product_variant)
            self.product_master = variant_doc.product_master

    def validate_dates(self):
        """Validate date ranges."""
        if self.valid_from and self.valid_to:
            if self.valid_from > self.valid_to:
                frappe.throw(
                    _("Valid From date cannot be after Valid To date"),
                    title=_("Invalid Date Range")
                )

        if self.launch_date and self.discontinue_date:
            if self.launch_date > self.discontinue_date:
                frappe.throw(
                    _("Launch Date cannot be after Discontinue Date"),
                    title=_("Invalid Date Range")
                )

    def validate_weights(self):
        """Validate weight values."""
        if self.gross_weight and self.gross_weight < 0:
            frappe.throw(_("Gross Weight cannot be negative"))

        if self.net_weight and self.net_weight < 0:
            frappe.throw(_("Net Weight cannot be negative"))

        if self.gross_weight and self.net_weight:
            if self.net_weight > self.gross_weight:
                frappe.throw(
                    _("Net Weight cannot exceed Gross Weight"),
                    title=_("Invalid Weight")
                )

    def validate_default_package(self):
        """Ensure only one default package per product."""
        if self.is_default_package and self.product_master:
            existing_default = frappe.db.exists(
                "Package Variant",
                {
                    "product_master": self.product_master,
                    "is_default_package": 1,
                    "name": ["!=", self.name or ""]
                }
            )
            if existing_default:
                frappe.throw(
                    _("A default package already exists for this product. "
                      "Please unmark the existing default first."),
                    title=_("Duplicate Default Package")
                )

    def validate_replacement_package(self):
        """Prevent circular replacement references."""
        if self.replacement_package:
            if self.replacement_package == self.name:
                frappe.throw(
                    _("A package cannot be its own replacement"),
                    title=_("Circular Reference")
                )

            # Check for indirect circular references
            replacement = frappe.db.get_value(
                "Package Variant",
                self.replacement_package,
                "replacement_package"
            )
            if replacement == self.name:
                frappe.throw(
                    _("Circular replacement reference detected"),
                    title=_("Circular Reference")
                )

    def calculate_derived_fields(self):
        """Calculate derived field values."""
        # Calculate tare weight
        if self.gross_weight and self.net_weight:
            self.tare_weight = self.gross_weight - self.net_weight
        else:
            self.tare_weight = 0

        # Calculate volume
        if self.length and self.width and self.height:
            self.volume = self.length * self.width * self.height
        else:
            self.volume = 0

        # Calculate desi (volumetric weight)
        if self.volume:
            self.desi = self.volume / 3000
        else:
            self.desi = 0

        # Calculate chargeable weight (higher of gross weight or desi)
        self.chargeable_weight = max(self.gross_weight or 0, self.desi or 0)

        # Calculate price per unit
        if self.price and self.units_per_package and self.units_per_package > 0:
            self.price_per_unit = self.price / self.units_per_package
        else:
            self.price_per_unit = 0

    def before_save(self):
        """Actions before saving the document."""
        # Auto-set status to Discontinued if discontinue_date is in the past
        if self.discontinue_date:
            from frappe.utils import getdate, today
            if getdate(self.discontinue_date) < getdate(today()):
                self.status = "Discontinued"


@frappe.whitelist()
def get_product_packages(product_master, include_inactive=False):
    """Get all package variants for a product.

    Args:
        product_master: Product Master name
        include_inactive: Whether to include inactive packages

    Returns:
        List of package variant records
    """
    filters = {"product_master": product_master}

    if not include_inactive:
        filters["status"] = ["in", ["Draft", "Active"]]

    return frappe.get_all(
        "Package Variant",
        filters=filters,
        fields=[
            "name", "package_name", "package_code", "package_type",
            "units_per_package", "primary_barcode", "price", "price_per_unit",
            "status", "is_default_package", "image"
        ],
        order_by="display_order, units_per_package"
    )


@frappe.whitelist()
def get_package_by_barcode(barcode):
    """Find a package variant by barcode.

    Args:
        barcode: Barcode to search for

    Returns:
        Package variant name or None
    """
    # Search across all barcode fields
    package = frappe.db.get_value(
        "Package Variant",
        filters={
            "primary_barcode": barcode
        },
        fieldname="name"
    )

    if not package:
        package = frappe.db.get_value(
            "Package Variant",
            filters={
                "secondary_barcode": barcode
            },
            fieldname="name"
        )

    if not package:
        package = frappe.db.get_value(
            "Package Variant",
            filters={
                "case_barcode": barcode
            },
            fieldname="name"
        )

    if not package:
        package = frappe.db.get_value(
            "Package Variant",
            filters={
                "gtin": barcode
            },
            fieldname="name"
        )

    return package


@frappe.whitelist()
def get_default_package(product_master):
    """Get the default package variant for a product.

    Args:
        product_master: Product Master name

    Returns:
        Default package variant name or None
    """
    return frappe.db.get_value(
        "Package Variant",
        filters={
            "product_master": product_master,
            "is_default_package": 1,
            "status": "Active"
        },
        fieldname="name"
    )


@frappe.whitelist()
def get_package_statistics(product_master=None):
    """Get statistics about package variants.

    Args:
        product_master: Optional product to filter by

    Returns:
        Dictionary with package statistics
    """
    filters = {}
    if product_master:
        filters["product_master"] = product_master

    total = frappe.db.count("Package Variant", filters)

    filters["status"] = "Active"
    active = frappe.db.count("Package Variant", filters)

    filters["status"] = "Discontinued"
    discontinued = frappe.db.count("Package Variant", filters)

    # Get package type distribution
    type_distribution = frappe.db.sql("""
        SELECT package_type, COUNT(*) as count
        FROM `tabPackage Variant`
        WHERE 1=1
        {product_filter}
        GROUP BY package_type
        ORDER BY count DESC
    """.format(
        product_filter="AND product_master = %s" if product_master else ""
    ), (product_master,) if product_master else (), as_dict=True)

    return {
        "total": total,
        "active": active,
        "discontinued": discontinued,
        "type_distribution": type_distribution
    }


@frappe.whitelist()
def duplicate_package(package_name, new_package_code, new_package_name=None):
    """Create a copy of an existing package variant.

    Args:
        package_name: Source package variant name
        new_package_code: Code for the new package
        new_package_name: Optional name for the new package

    Returns:
        Name of the newly created package
    """
    source = frappe.get_doc("Package Variant", package_name)

    new_package = frappe.copy_doc(source)
    new_package.package_code = new_package_code
    new_package.package_name = new_package_name or f"Copy of {source.package_name}"
    new_package.is_default_package = 0
    new_package.status = "Draft"
    new_package.primary_barcode = None
    new_package.secondary_barcode = None
    new_package.case_barcode = None
    new_package.pallet_barcode = None
    new_package.gtin = None
    new_package.internal_sku = None

    new_package.insert()

    return new_package.name
