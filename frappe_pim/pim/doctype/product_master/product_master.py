# Copyright (c) 2024, Your Company and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cstr, flt, getdate, nowdate


# Mapping of Product Master fields to ERPNext Item fields
# Format: {PM field: Item field}
PM_TO_ITEM_MAPPING = {
    # Core identity fields
    "product_code": "item_code",
    "product_name": "item_name",
    "short_description": "description",
    "brand": "brand",
    "manufacturer": "manufacturer",

    # Stock fields
    "stock_uom": "stock_uom",
    "is_stock_item": "is_stock_item",

    # Dimensions and weight
    "weight_net": "weight_per_unit",
    "weight_uom": "weight_uom",

    # Images
    "main_image": "image",

    # Pricing fields (mapped to Item standard fields)
    "base_price": "standard_rate",

    # Flags
    "is_template": "has_variants",

    # The following are custom fields added to Item via fixtures
    # They map 1:1 with the same field name
    "sku": "custom_pim_sku",
    "lifecycle_stage": "custom_pim_lifecycle_stage",
    "workflow_state": "custom_pim_workflow_state",
    "status": "custom_pim_status",
    "barcode": "custom_pim_barcode",
    "ean": "custom_pim_ean",
    "upc": "custom_pim_upc",
    "mpn": "custom_pim_mpn",
    "gtin": "custom_pim_gtin",
    "cost_price": "custom_pim_cost_price",
    "min_stock_level": "custom_pim_min_stock_level",
    "max_stock_level": "custom_pim_max_stock_level",
    "reorder_level": "custom_pim_reorder_level",
    "lead_time_days": "custom_pim_lead_time_days",
    "shelf_life_days": "custom_pim_shelf_life_days",
    "weight_gross": "custom_pim_weight_gross",
    "length": "custom_pim_length",
    "width": "custom_pim_width",
    "height": "custom_pim_height",
    "dimension_uom": "custom_pim_dimension_uom",
    "volume": "custom_pim_volume",
    "volume_uom": "custom_pim_volume_uom",
    "country_of_origin": "country_of_origin",
    "seo_title": "custom_pim_seo_title",
    "meta_description": "custom_pim_meta_description",
    "url_slug": "custom_pim_url_slug",
    "meta_keywords": "custom_pim_meta_keywords",
    "canonical_url": "custom_pim_canonical_url",
    "warranty_months": "custom_pim_warranty_months",
    "hs_code": "customs_tariff_number",
    "hazardous_material": "custom_pim_hazardous_material",
    "age_restriction": "custom_pim_age_restriction",
}

# Reverse mapping for Item to Product Master sync
ITEM_TO_PM_MAPPING = {v: k for k, v in PM_TO_ITEM_MAPPING.items()}

# Aliases used in tests and external code
PRODUCT_TO_ITEM_FIELDS = PM_TO_ITEM_MAPPING
ITEM_TO_PRODUCT_FIELDS = ITEM_TO_PM_MAPPING

# Child table field names that need to be loaded separately
CHILD_TABLE_FIELDS = [
    "product_media",
    "attribute_values",
    "price_items",
    "channels",
    "product_relations",
    "supplier_items",
    "certifications",
    "translations",
]


class ProductMaster(Document):
    """
    Virtual DocType controller for Product Master.

    Product Master is a Virtual DocType that maps to ERPNext Item.
    It does NOT create its own database table. Instead:
    - Item-mapped fields are stored in ERPNext Item
    - Custom fields on Item store PIM-specific data
    - Child tables create their own database tables
    - Computed fields are calculated at runtime
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Initialize _table_fieldnames for Virtual DocType
        if not hasattr(self, "_table_fieldnames") or self._table_fieldnames is None:
            self._table_fieldnames = set()
        # Pre-initialize ALL child table fields to [] so Frappe core methods
        # (e.g. update_global_search) never receive None when calling doc.get(fieldname).
        _all_table_fields = [
            "product_media", "attribute_values", "price_items", "channels",
            "product_relations", "supplier_items", "certifications", "translations",
            "contract_prices", "applicable_price_rules", "package_variants",
            "marketplace_listings", "social_media_links", "qa_notes", "feedbacks",
            "chemical_instructions", "competitor_analyses", "market_insights",
            "target_segments", "customer_segments", "notification_rules",
            "export_profiles",
        ]
        for _f in _all_table_fields:
            if self.__dict__.get(_f) is None:
                self.__dict__[_f] = []

    def get(self, key=None, filters=None, limit=None, default=None):
        """Override get() to ensure child table fields always return a list.

        Frappe's update_global_search calls ``doc.get(child.fieldname)`` and
        iterates the result.  For a Virtual DocType, unmapped Table/Table
        MultiSelect fields would return None, causing a TypeError.  We
        intercept those cases and return [] so Frappe core never crashes.
        """
        value = super().get(key=key, filters=filters, limit=limit, default=default)
        if key and value is None:
            try:
                meta_field = frappe.get_meta(self.doctype).get_field(key)
                if meta_field and meta_field.fieldtype in ("Table", "Table MultiSelect"):
                    return []
            except Exception:
                pass
        return value

    @staticmethod
    def get_list(args):
        """Get list of Product Masters by querying Items with PIM data."""
        # Build filters for Item query
        filters = {}
        raw_filters = args.get("filters")
        if raw_filters:
            if isinstance(raw_filters, dict):
                # Dict filter: {"fieldname": value}
                for k, v in raw_filters.items():
                    item_field = PM_TO_ITEM_MAPPING.get(k, k)
                    filters[item_field] = v
            else:
                # List filter: [["fieldname", "=", value], ...] or
                # [["Doctype", "fieldname", "=", value], ...]
                for f in raw_filters:
                    if isinstance(f, (list, tuple)):
                        if len(f) == 4:
                            # Frappe internal format: [doctype, fieldname, operator, value]
                            _, fieldname, operator, value = f
                        elif len(f) == 3:
                            # Short format: [fieldname, operator, value]
                            fieldname, operator, value = f
                        else:
                            continue
                        item_field = PM_TO_ITEM_MAPPING.get(fieldname, fieldname)
                        filters[item_field] = [operator, value]
                    elif isinstance(f, dict):
                        for k, v in f.items():
                            item_field = PM_TO_ITEM_MAPPING.get(k, k)
                            filters[item_field] = v

        # Query Items with all needed fields
        items = frappe.get_all(
            "Item",
            filters=filters,
            fields=[
                "name", "item_name", "item_code", "image", "modified",
                "creation", "owner", "custom_pim_status", "custom_pim_product_family",
                "custom_pim_workflow_state"
            ],
            limit_page_length=args.get("limit_page_length", 20),
            limit_start=args.get("limit_start", 0),
            order_by="modified desc",
        )

        # Transform to Product Master format
        result = []
        for item in items:
            result.append({
                "name": item.name,
                "product_name": item.item_name,
                "product_code": item.item_code,
                "main_image": item.image,
                "modified": item.modified,
                "creation": item.creation,
                "owner": item.owner,
                "status": item.custom_pim_status or "Draft",
                "product_family": item.custom_pim_product_family,
                "workflow_state": item.custom_pim_workflow_state,
            })

        return result

    @staticmethod
    def get_count(args):
        """Get count of Product Masters by counting Items with mapped filters."""
        filters = {}
        if args.get("filters"):
            raw_filters = args.get("filters", {})
            if isinstance(raw_filters, dict):
                for k, v in raw_filters.items():
                    item_field = PM_TO_ITEM_MAPPING.get(k, k)
                    filters[item_field] = v
            elif isinstance(raw_filters, (list, tuple)):
                for f in raw_filters:
                    if isinstance(f, (list, tuple)) and len(f) >= 3:
                        fieldname, operator, value = f[0], f[1], f[2]
                        item_field = PM_TO_ITEM_MAPPING.get(fieldname, fieldname)
                        filters[item_field] = [operator, value]
            else:
                filters = raw_filters
        return frappe.db.count("Item", filters)

    @staticmethod
    def get_stats(args):
        """Get sidebar stats for Product Master list view.

        Returns aggregated counts by filterable fields (status, lifecycle_stage,
        product_family, brand) so the Frappe list sidebar can show grouped counts.
        """
        stat_fields = args.get("stats") or []
        result = {}

        # Mapping from PM stat field names to Item field names
        stat_field_map = {
            "status": "custom_pim_status",
            "lifecycle_stage": "custom_pim_lifecycle_stage",
            "product_family": "custom_pim_product_family",
            "product_type": "custom_pim_product_type",
            "brand": "brand",
            "owner": "owner",
        }

        for field in stat_fields:
            if field not in stat_field_map:
                # Only allow known fields to prevent SQL injection
                result[field] = {}
                continue

            item_field = stat_field_map[field]
            try:
                counts = frappe.db.sql(
                    """SELECT `{field}`, COUNT(*) as count
                    FROM `tabItem`
                    WHERE IFNULL(`{field}`, '') != ''
                    GROUP BY `{field}`
                    ORDER BY count DESC""".format(field=item_field),
                    as_dict=True
                )
                result[field] = {
                    row.get(item_field, ""): row.get("count", 0)
                    for row in counts
                }
            except Exception:
                result[field] = {}

        return result

    @staticmethod
    def _map_fields_to_item(fields):
        """Map Product Master field names to Item field names for queries."""
        result = []
        for f in fields:
            result.append(PM_TO_ITEM_MAPPING.get(f, f))
        return result

    @staticmethod
    def _map_filters_to_item(filters):
        """Map Product Master filter keys to Item field names."""
        if isinstance(filters, dict):
            return {PM_TO_ITEM_MAPPING.get(k, k): v for k, v in filters.items()}
        return filters

    @staticmethod
    def _transform_item_to_product(item_dict):
        """Transform an Item dict to Product Master field names."""
        result = {}
        for item_field, value in item_dict.items():
            pm_field = ITEM_TO_PM_MAPPING.get(item_field, item_field)
            result[pm_field] = value
        return result

    @staticmethod
    def _map_order_by(order_by):
        """Map Product Master order_by field to Item field."""
        if not order_by:
            return "modified desc"
        parts = order_by.split()
        if parts:
            item_field = PM_TO_ITEM_MAPPING.get(parts[0], parts[0])
            parts[0] = item_field
        return " ".join(parts)

    def load_from_db(self):
        """Load Product Master data from ERPNext Item."""
        if not self.name:
            return

        # Check if Item exists
        if not frappe.db.exists("Item", self.name):
            frappe.throw(_("Item {0} not found").format(self.name), frappe.DoesNotExistError)

        # Load Item document
        item = frappe.get_doc("Item", self.name)

        # Map Item fields to Product Master fields
        for pm_field, item_field in PM_TO_ITEM_MAPPING.items():
            value = item.get(item_field)
            if value is not None:
                self.__dict__[pm_field] = value

        # Set name explicitly
        self.__dict__["name"] = item.name

        # Load additional fields that don't need mapping
        self.__dict__["modified"] = item.modified
        self.__dict__["creation"] = item.creation
        self.__dict__["modified_by"] = item.modified_by
        self.__dict__["owner"] = item.owner

        # Load Link fields that need special handling
        link_fields = [
            "product_family", "product_series", "product_collection",
            "product_type", "product_category", "taxonomy_node",
            "attribute_template", "variant_based_on", "bundle_ref",
            "parent_product", "currency", "tax_category",
            "gs1_packaging", "nutrition_facts", "display_template",
            "data_quality_policy", "product_score", "golden_record",
            "source_system", "data_steward", "survivorship_rule",
            "ai_enrichment_job", "ai_prompt_template", "webhook_config",
            "import_source",
        ]
        for field in link_fields:
            custom_field = f"custom_pim_{field}"
            value = item.get(custom_field)
            if value is not None:
                self.__dict__[field] = value

        # Load additional simple fields from Item custom fields
        additional_fields = [
            "long_description", "internal_notes", "has_variants",
            "is_bundle", "thumbnail", "variant_attributes",
            "data_quality_score", "sync_status", "last_sync_time",
            "sync_error_message", "ai_enrichment_status",
            "ai_generated_content", "import_date", "import_reference",
            "legal_disclaimer",
        ]
        for field in additional_fields:
            custom_field = f"custom_pim_{field}"
            value = item.get(custom_field)
            if value is not None:
                self.__dict__[field] = value

        # Load child tables from their own tables
        self._load_child_tables()

    def _load_child_tables(self):
        """Load child table data for this Product Master."""
        child_table_config = {
            "product_media": "Product Media",
            "attribute_values": "Product Attribute Value",
            "price_items": "Product Price Item",
            "channels": "Product Channel",
            "product_relations": "Product Relation",
            "supplier_items": "Product Supplier Item",
            "certifications": "Product Certification Item",
            "translations": "Product Translation Item",
        }

        for fieldname, doctype in child_table_config.items():
            try:
                children = frappe.get_all(
                    doctype,
                    filters={"parent": self.name, "parenttype": "Product Master"},
                    fields=["*"],
                    order_by="idx asc",
                )
                self.__dict__[fieldname] = children
            except Exception:
                # Table might not exist yet
                self.__dict__[fieldname] = []

    def db_insert(self, *args, **kwargs):
        """Create ERPNext Item when Product Master is created."""
        # Skip if called from ERPNext sync to prevent infinite loop
        if getattr(self, "_from_erpnext_sync", False):
            return

        # Prepare Item data
        item_data = self._prepare_item_data()

        # Create Item
        item = frappe.new_doc("Item")
        item.update(item_data)
        item.flags._from_pim_sync = True  # Prevent sync loop

        try:
            item.insert(ignore_permissions=True)
            self.__dict__["name"] = item.name
            # Reload item to get creation/modified timestamps
            item.reload()
        except frappe.DuplicateEntryError:
            raise
        except Exception as e:
            frappe.throw(_("Failed to create Item: {0}").format(str(e)))

        # Sync timestamps from Item to Product Master
        self.__dict__["modified"] = item.modified
        self.__dict__["creation"] = item.creation
        self.__dict__["modified_by"] = item.modified_by
        self.__dict__["owner"] = item.owner

        # Save child tables
        self._save_child_tables()

    def db_update(self):
        """Update ERPNext Item when Product Master is updated."""
        # Skip if called from ERPNext sync to prevent infinite loop
        if getattr(self, "_from_erpnext_sync", False):
            return

        if not frappe.db.exists("Item", self.name):
            frappe.throw(_("Item {0} not found").format(self.name))

        # Get existing Item
        item = frappe.get_doc("Item", self.name)

        # Prepare and update Item data
        item_data = self._prepare_item_data()
        item.update(item_data)
        item.flags._from_pim_sync = True  # Prevent sync loop

        try:
            item.save(ignore_permissions=True)
            # Reload item to get updated timestamp
            item.reload()
        except Exception as e:
            frappe.throw(_("Failed to update Item: {0}").format(str(e)))

        # Sync modified timestamp from Item to Product Master
        # This prevents "Document has been modified" errors
        self.__dict__["modified"] = item.modified
        self.__dict__["modified_by"] = item.modified_by

        # Update child tables
        self._save_child_tables()

    def update_children(self):
        """Override update_children for Virtual DocType.
        
        Virtual DocTypes don't have a database table, so Frappe's standard
        child table update mechanism doesn't work. We handle child tables
        manually in _save_child_tables().
        """
        # Do nothing - child tables are handled in _save_child_tables()
        pass

    def _prepare_item_data(self):
        """Prepare Item data from Product Master fields."""
        item_data = {
            "doctype": "Item",
            "item_group": self._get_item_group(),
        }

        # Map Product Master fields to Item fields
        for pm_field, item_field in PM_TO_ITEM_MAPPING.items():
            value = self.get(pm_field)
            if value is not None:
                item_data[item_field] = value

        # Set item_code if product_code is provided
        if self.get("product_code"):
            item_data["item_code"] = self.product_code

        # Set item_name if product_name is provided
        if self.get("product_name"):
            item_data["item_name"] = self.product_name

        # Ensure stock_uom always has a value (Item requires it)
        if not item_data.get("stock_uom"):
            item_data["stock_uom"] = (
                frappe.db.get_single_value("Stock Settings", "stock_uom") or "Nos"
            )

        # Handle Link fields stored as custom fields
        link_fields = [
            "product_family", "product_series", "product_collection",
            "product_type", "product_category", "taxonomy_node",
            "attribute_template", "variant_based_on", "bundle_ref",
            "parent_product", "currency", "tax_category",
            "gs1_packaging", "nutrition_facts", "display_template",
            "data_quality_policy", "product_score", "golden_record",
            "source_system", "data_steward", "survivorship_rule",
            "ai_enrichment_job", "ai_prompt_template", "webhook_config",
            "import_source",
        ]
        for field in link_fields:
            value = self.get(field)
            if value is not None:
                item_data[f"custom_pim_{field}"] = value

        # Handle additional simple fields
        # Note: variant_attributes and ai_generated_content have json_valid() CHECK
        # constraints on tabItem — never send empty strings for these columns.
        additional_fields = [
            "long_description", "internal_notes", "has_variants",
            "is_bundle", "thumbnail", "variant_attributes",
            "data_quality_score", "sync_status", "last_sync_time",
            "sync_error_message", "ai_enrichment_status",
            "ai_generated_content", "import_date", "import_reference",
            "legal_disclaimer",
        ]
        json_constrained = {"variant_attributes", "ai_generated_content"}
        for field in additional_fields:
            value = self.get(field)
            if value is None:
                continue
            if field in json_constrained and not value:
                continue  # skip empty string — would fail json_valid() CHECK
            item_data[f"custom_pim_{field}"] = value

        return item_data

    def _get_item_group(self):
        """Get or create default item group for PIM products."""
        default_group = "Products"
        if not frappe.db.exists("Item Group", default_group):
            # Try to get first available item group
            item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
            if item_group:
                return item_group
            # Fallback to All Item Groups
            return "All Item Groups"
        return default_group

    def _save_child_tables(self):
        """Save child table data for this Product Master."""
        child_table_config = {
            "product_media": "Product Media",
            "attribute_values": "Product Attribute Value",
            "price_items": "Product Price Item",
            "channels": "Product Channel",
            "product_relations": "Product Relation",
            "supplier_items": "Product Supplier Item",
            "certifications": "Product Certification Item",
            "translations": "Product Translation Item",
        }

        for fieldname, doctype in child_table_config.items():
            children = self.get(fieldname) or []

            # Delete existing children
            frappe.db.delete(
                doctype,
                {"parent": self.name, "parenttype": "Product Master"}
            )

            # Insert new children
            for idx, child_data in enumerate(children, start=1):
                if isinstance(child_data, dict):
                    child = frappe.new_doc(doctype)
                    child.update(child_data)
                    child.parent = self.name
                    child.parenttype = "Product Master"
                    child.parentfield = fieldname
                    child.idx = idx
                    child.insert(ignore_permissions=True)

    def delete(self):
        """Delete Product Master and associated Item."""
        # Skip if called from ERPNext sync
        if getattr(self, "_from_erpnext_sync", False):
            return

        # Delete child tables first
        self._delete_child_tables()

        # Delete associated Item
        if frappe.db.exists("Item", self.name):
            item = frappe.get_doc("Item", self.name)
            item.flags._from_pim_sync = True
            item.delete(ignore_permissions=True)

    def _delete_child_tables(self):
        """Delete all child table records for this Product Master."""
        child_tables = [
            "Product Media",
            "Product Attribute Value",
            "Product Price Item",
            "Product Channel",
            "Product Relation",
            "Product Supplier Item",
            "Product Certification Item",
            "Product Translation Item",
        ]

        for doctype in child_tables:
            frappe.db.delete(
                doctype,
                {"parent": self.name, "parenttype": "Product Master"}
            )

    def validate(self):
        """Validate Product Master data before save."""
        self.validate_circular_relations()
        self.validate_parent_product()
        self.validate_variant_settings()
        self.validate_price_items()
        self.validate_certification_dates()
        self.update_has_variants_flag()
        self.validate_publish_workflow()

    def validate_circular_relations(self):
        """Prevent product from being related to itself."""
        product_relations = self.get("product_relations") or []
        for relation in product_relations:
            if isinstance(relation, dict):
                related_product = relation.get("related_product")
            else:
                related_product = relation.related_product if hasattr(relation, "related_product") else None

            if related_product and related_product == self.name:
                frappe.throw(
                    _("Product cannot be related to itself. Please remove the circular relationship.")
                )

    def validate_parent_product(self):
        """Validate parent product reference to prevent self-reference."""
        if self.get("parent_product"):
            if self.parent_product == self.name:
                frappe.throw(
                    _("Product cannot be its own parent. Please select a different parent product.")
                )

            # Validate parent exists
            if not frappe.db.exists("Item", self.parent_product):
                frappe.throw(
                    _("Parent product {0} does not exist.").format(self.parent_product)
                )

    def validate_variant_settings(self):
        """Validate variant template and variant settings."""
        if self.get("is_template"):
            # Template products should have variant_based_on set
            if not self.get("variant_based_on") and not self.get("attribute_template"):
                frappe.msgprint(
                    _("Consider setting an attribute template for variant generation."),
                    indicator="yellow",
                    alert=True
                )

        if self.get("parent_product"):
            # Variant products cannot be templates
            if self.get("is_template"):
                frappe.throw(
                    _("A product variant cannot also be a template. Please uncheck 'Is Template'.")
                )

    def validate_price_items(self):
        """Validate price item data."""
        price_items = self.get("price_items") or []
        seen_price_lists = {}

        for idx, item in enumerate(price_items, start=1):
            if isinstance(item, dict):
                price_list = item.get("price_list")
                price = item.get("price")
                valid_from = item.get("valid_from")
                valid_to = item.get("valid_to")
            else:
                price_list = getattr(item, "price_list", None)
                price = getattr(item, "price", None)
                valid_from = getattr(item, "valid_from", None)
                valid_to = getattr(item, "valid_to", None)

            # Check for negative prices
            if price is not None and flt(price) < 0:
                frappe.throw(
                    _("Row {0}: Price cannot be negative.").format(idx)
                )

            # Check date range validity
            if valid_from and valid_to:
                if getdate(valid_from) > getdate(valid_to):
                    frappe.throw(
                        _("Row {0}: Valid From date cannot be after Valid To date.").format(idx)
                    )

            # Warn about duplicate price lists without date ranges
            if price_list:
                key = (price_list, valid_from, valid_to)
                if key in seen_price_lists:
                    frappe.msgprint(
                        _("Row {0}: Duplicate entry for price list {1} with same date range.").format(
                            idx, price_list
                        ),
                        indicator="orange",
                        alert=True
                    )
                seen_price_lists[key] = True

    def validate_certification_dates(self):
        """Validate certification date ranges."""
        certifications = self.get("certifications") or []

        for idx, cert in enumerate(certifications, start=1):
            if isinstance(cert, dict):
                valid_from = cert.get("valid_from")
                valid_to = cert.get("valid_to")
            else:
                valid_from = getattr(cert, "valid_from", None)
                valid_to = getattr(cert, "valid_to", None)

            if valid_from and valid_to:
                if getdate(valid_from) > getdate(valid_to):
                    frappe.throw(
                        _("Certification Row {0}: Valid From date cannot be after Valid To date.").format(idx)
                    )

            # Warn about expired certifications
            if valid_to and getdate(valid_to) < getdate(nowdate()):
                frappe.msgprint(
                    _("Certification Row {0}: Certification has expired.").format(idx),
                    indicator="orange",
                    alert=True
                )

    def update_has_variants_flag(self):
        """Update has_variants flag based on existing variants."""
        if self.name:
            variant_count = frappe.db.count(
                "Item",
                {"custom_pim_parent_product": self.name}
            )
            self.has_variants = variant_count > 0

    def validate_publish_workflow(self):
        """
        C) Company-size workflow requirement.
        Companies with 201+ employees must go through 'In Review' status
        before a product can be set to 'Published'.
        Prevents direct Draft → Published transitions.
        """
        if self.get("status") != "Published":
            return

        try:
            company_size = frappe.db.get_single_value("Tenant Config", "company_size")
        except Exception:
            return  # Tenant Config unavailable — skip restriction

        LARGE_COMPANY_SIZES = {"201-500", "501-1000", "1000+"}
        if company_size not in LARGE_COMPANY_SIZES:
            return  # Small/medium companies can publish directly

        # Check if the product was previously "In Review"
        old_status = frappe.db.get_value("Item", self.name, "custom_pim_status") if self.name else None
        if old_status != "In Review":
            frappe.throw(
                _(
                    "Products must go through 'In Review' status before being Published. "
                    "This is required for companies with 201+ employees. "
                    "Please set the status to 'In Review' first."
                ),
                title=_("Approval Required"),
            )

    @frappe.whitelist()
    def calculate_completeness(self):
        """
        Calculate data completeness score as a percentage.

        The score is based on how many important fields are filled.
        Returns a dictionary with score and breakdown.
        """
        # Define field weights by category
        field_weights = {
            "required": {
                "fields": ["product_name", "product_code"],
                "weight": 30
            },
            "identity": {
                "fields": ["sku", "brand", "manufacturer", "product_type", "product_category"],
                "weight": 15
            },
            "description": {
                "fields": ["short_description", "long_description"],
                "weight": 15
            },
            "media": {
                "fields": ["main_image", "thumbnail"],
                "weight": 10
            },
            "pricing": {
                "fields": ["base_price", "cost_price", "currency"],
                "weight": 10
            },
            "stock": {
                "fields": ["stock_uom", "is_stock_item"],
                "weight": 5
            },
            "seo": {
                "fields": ["seo_title", "meta_description", "url_slug"],
                "weight": 10
            },
            "compliance": {
                "fields": ["country_of_origin", "hs_code"],
                "weight": 5
            }
        }

        total_score = 0
        breakdown = {}

        for category, config in field_weights.items():
            fields = config["fields"]
            weight = config["weight"]
            filled_count = 0

            for field in fields:
                value = self.get(field)
                if value not in [None, "", 0, []]:
                    filled_count += 1

            category_score = (filled_count / len(fields)) * weight if fields else 0
            total_score += category_score
            breakdown[category] = {
                "score": round(category_score, 2),
                "max": weight,
                "filled": filled_count,
                "total": len(fields)
            }

        # Add bonus points for child tables
        child_table_bonus = 0
        if self.get("attribute_values"):
            child_table_bonus += 2
        if self.get("price_items"):
            child_table_bonus += 2
        if self.get("product_media"):
            child_table_bonus += 2
        if self.get("channels"):
            child_table_bonus += 2
        if self.get("translations"):
            child_table_bonus += 2

        total_score = min(100, total_score + child_table_bonus)

        # Update data_quality_score field
        self.data_quality_score = round(total_score, 2)

        return {
            "score": round(total_score, 2),
            "breakdown": breakdown,
            "child_tables_bonus": child_table_bonus,
            "status": self._get_quality_status(total_score)
        }

    def _get_quality_status(self, score):
        """Get quality status based on score."""
        if score >= 80:
            return "Excellent"
        elif score >= 60:
            return "Good"
        elif score >= 40:
            return "Fair"
        elif score >= 20:
            return "Poor"
        else:
            return "Critical"

    @frappe.whitelist()
    def get_variants(self):
        """
        Get all variant products for this template product.

        Returns a list of variant products with key information.
        """
        if not self.name:
            return []

        if not self.get("is_template"):
            frappe.throw(_("Only template products can have variants."))

        variants = frappe.get_all(
            "Item",
            filters={"custom_pim_parent_product": self.name},
            fields=[
                "name", "item_name", "item_code", "image",
                "custom_pim_status", "custom_pim_sku",
                "modified"
            ],
            order_by="item_name asc"
        )

        result = []
        for v in variants:
            result.append({
                "name": v.name,
                "product_name": v.item_name,
                "product_code": v.item_code,
                "main_image": v.image,
                "status": v.custom_pim_status,
                "sku": v.custom_pim_sku,
                "modified": v.modified
            })

        return result

    @frappe.whitelist()
    def generate_variants(self, attribute_combinations=None):
        """
        Generate variant products based on attribute combinations.

        Args:
            attribute_combinations: List of dicts with attribute values
                                   Example: [{"Color": "Red", "Size": "M"}, ...]

        Returns:
            List of created variant names
        """
        if not self.name:
            frappe.throw(_("Please save the product first."))

        if not self.get("is_template"):
            frappe.throw(_("Only template products can generate variants."))

        if not attribute_combinations:
            # Try to generate from attribute template
            attribute_combinations = self._get_attribute_combinations_from_template()

        if not attribute_combinations:
            frappe.throw(
                _("No attribute combinations provided or found in template. "
                  "Please set attribute values or provide combinations.")
            )

        created_variants = []

        for combo in attribute_combinations:
            try:
                variant_name = self._create_variant(combo)
                if variant_name:
                    created_variants.append(variant_name)
            except Exception as e:
                frappe.log_error(
                    message=str(e),
                    title=f"Variant Creation Error for {self.name}"
                )
                frappe.msgprint(
                    _("Failed to create variant for {0}: {1}").format(
                        str(combo), str(e)
                    ),
                    indicator="red"
                )

        if created_variants:
            # Update has_variants flag
            self.has_variants = 1
            frappe.db.set_value(
                "Item", self.name, "has_variants", 1
            )

            frappe.msgprint(
                _("Successfully created {0} variant(s).").format(len(created_variants)),
                indicator="green"
            )

        return created_variants

    def _get_attribute_combinations_from_template(self):
        """
        Get attribute combinations from the attribute template.

        Returns list of attribute value combinations.
        """
        template_name = self.get("attribute_template") or self.get("variant_based_on")

        if not template_name:
            return []

        # Get template attributes
        template = frappe.get_doc("PIM Attribute Template", template_name)
        if not template:
            return []

        # Get attribute options for each attribute in the template
        attribute_options = {}
        for attr in template.get("attributes", []):
            attr_name = attr.get("attribute") if isinstance(attr, dict) else attr.attribute
            if attr_name:
                # Get options for this attribute
                options = frappe.get_all(
                    "PIM Attribute Option",
                    filters={"parent": attr_name},
                    fields=["option_value"],
                    order_by="idx asc"
                )
                if options:
                    attribute_options[attr_name] = [o.option_value for o in options]

        if not attribute_options:
            return []

        # Generate all combinations using itertools
        import itertools
        keys = list(attribute_options.keys())
        values = [attribute_options[k] for k in keys]

        combinations = []
        for combo in itertools.product(*values):
            combinations.append(dict(zip(keys, combo)))

        return combinations

    def _create_variant(self, attribute_combo):
        """
        Create a single variant product.

        Args:
            attribute_combo: Dict of attribute name -> value

        Returns:
            Name of created variant
        """
        # Generate variant code/name
        combo_suffix = "-".join(str(v) for v in attribute_combo.values())
        variant_code = f"{self.product_code}-{combo_suffix}"
        variant_name = f"{self.product_name} ({combo_suffix})"

        # Check if variant already exists
        if frappe.db.exists("Item", variant_code):
            frappe.msgprint(
                _("Variant {0} already exists, skipping.").format(variant_code)
            )
            return None

        # Create variant Item
        variant_item = frappe.new_doc("Item")

        # Copy basic fields from template
        variant_item.item_code = variant_code
        variant_item.item_name = variant_name
        variant_item.item_group = self._get_item_group()
        variant_item.stock_uom = self.get("stock_uom") or "Unit"
        variant_item.is_stock_item = self.get("is_stock_item", 1)

        # Set parent reference
        variant_item.custom_pim_parent_product = self.name
        variant_item.custom_pim_status = "Draft"

        # Copy other fields
        if self.get("brand"):
            variant_item.brand = self.brand
        if self.get("description"):
            variant_item.description = self.description
        if self.get("main_image"):
            variant_item.image = self.main_image

        # Store variant attributes as JSON
        import json
        variant_item.custom_pim_variant_attributes = json.dumps(attribute_combo)

        variant_item.flags._from_pim_sync = True
        variant_item.insert(ignore_permissions=True)

        return variant_item.name

    @frappe.whitelist()
    def get_channel_status(self):
        """
        Get sync status for all configured channels.

        Returns a summary of channel sync statuses.
        """
        channels = self.get("channels") or []
        if not channels:
            return {
                "total": 0,
                "synced": 0,
                "pending": 0,
                "error": 0,
                "channels": []
            }

        status_count = {"Synced": 0, "Pending": 0, "Error": 0, "InProgress": 0}
        channel_details = []

        for ch in channels:
            if isinstance(ch, dict):
                channel_name = ch.get("channel")
                sync_status = ch.get("sync_status", "Pending")
                last_sync = ch.get("last_sync")
                error_message = ch.get("error_message")
            else:
                channel_name = getattr(ch, "channel", None)
                sync_status = getattr(ch, "sync_status", "Pending")
                last_sync = getattr(ch, "last_sync", None)
                error_message = getattr(ch, "error_message", None)

            status_count[sync_status] = status_count.get(sync_status, 0) + 1

            channel_details.append({
                "channel": channel_name,
                "status": sync_status,
                "last_sync": last_sync,
                "error": error_message
            })

        return {
            "total": len(channels),
            "synced": status_count.get("Synced", 0),
            "pending": status_count.get("Pending", 0),
            "error": status_count.get("Error", 0),
            "in_progress": status_count.get("InProgress", 0),
            "channels": channel_details
        }

    @frappe.whitelist()
    def sync_to_channels(self, channel_names=None):
        """
        Trigger sync to specified channels or all configured channels.

        Args:
            channel_names: List of channel names to sync, or None for all

        Returns:
            Dict with sync status
        """
        channels = self.get("channels") or []

        if not channels:
            frappe.throw(_("No channels configured for this product."))

        synced = []
        failed = []

        for ch in channels:
            if isinstance(ch, dict):
                channel_name = ch.get("channel")
            else:
                channel_name = getattr(ch, "channel", None)

            # Filter by channel_names if provided
            if channel_names and channel_name not in channel_names:
                continue

            try:
                # Update status to InProgress
                self._update_channel_status(channel_name, "InProgress")

                # Here you would call the actual channel sync API
                # For now, we just simulate success
                # frappe.enqueue(
                #     "frappe_pim.pim.api.channel.sync_product_to_channel",
                #     product=self.name,
                #     channel=channel_name
                # )

                synced.append(channel_name)

            except Exception as e:
                self._update_channel_status(channel_name, "Error", str(e))
                failed.append({"channel": channel_name, "error": str(e)})

        return {
            "synced": synced,
            "failed": failed,
            "message": _("Sync initiated for {0} channel(s).").format(len(synced))
        }

    def _update_channel_status(self, channel_name, status, error_message=None):
        """Update sync status for a specific channel."""
        channels = self.get("channels") or []

        for ch in channels:
            if isinstance(ch, dict):
                if ch.get("channel") == channel_name:
                    ch["sync_status"] = status
                    ch["last_sync"] = nowdate() if status == "Synced" else ch.get("last_sync")
                    if error_message:
                        ch["error_message"] = error_message
            else:
                if getattr(ch, "channel", None) == channel_name:
                    ch.sync_status = status
                    if status == "Synced":
                        ch.last_sync = nowdate()
                    if error_message:
                        ch.error_message = error_message

    @frappe.whitelist()
    def get_quick_stats(self):
        """
        Get quick statistics for the product.

        Returns data for the Quick Stats HTML field.
        """
        stats = {
            "completeness": self.calculate_completeness(),
            "variants_count": 0,
            "channels_count": 0,
            "channels_synced": 0,
            "media_count": 0,
            "prices_count": 0,
            "relations_count": 0,
        }

        # Count variants
        if self.name and self.get("is_template"):
            stats["variants_count"] = frappe.db.count(
                "Item",
                {"custom_pim_parent_product": self.name}
            )

        # Count channels
        channels = self.get("channels") or []
        stats["channels_count"] = len(channels)
        stats["channels_synced"] = sum(
            1 for ch in channels
            if (ch.get("sync_status") if isinstance(ch, dict) else getattr(ch, "sync_status", None)) == "Synced"
        )

        # Count media
        stats["media_count"] = len(self.get("product_media") or [])

        # Count prices
        stats["prices_count"] = len(self.get("price_items") or [])

        # Count relations
        stats["relations_count"] = len(self.get("product_relations") or [])

        return stats


# Standalone whitelisted functions for client-side calls

@frappe.whitelist()
def calculate_product_completeness(product_name):
    """Calculate completeness score for a product."""
    if not product_name:
        return {"score": 0, "status": "Unknown"}

    doc = frappe.get_doc("Product Master", product_name)
    return doc.calculate_completeness()


@frappe.whitelist()
def get_product_variants(product_name):
    """Get variants for a product."""
    if not product_name:
        return []

    doc = frappe.get_doc("Product Master", product_name)
    return doc.get_variants()


@frappe.whitelist()
def generate_product_variants(product_name, attribute_combinations=None):
    """Generate variants for a template product."""
    if not product_name:
        frappe.throw(_("Product name is required."))

    doc = frappe.get_doc("Product Master", product_name)

    if attribute_combinations and isinstance(attribute_combinations, str):
        import json
        attribute_combinations = json.loads(attribute_combinations)

    return doc.generate_variants(attribute_combinations)


@frappe.whitelist()
def get_product_quick_stats(product_name):
    """Get quick stats for a product."""
    if not product_name:
        return {}

    doc = frappe.get_doc("Product Master", product_name)
    return doc.get_quick_stats()


@frappe.whitelist()
def sync_product_to_channels(product_name, channel_names=None):
    """Sync product to channels."""
    if not product_name:
        frappe.throw(_("Product name is required."))

    doc = frappe.get_doc("Product Master", product_name)

    if channel_names and isinstance(channel_names, str):
        import json
        channel_names = json.loads(channel_names)

    return doc.sync_to_channels(channel_names)


@frappe.whitelist()
def get_family_attributes(family_name):
    """Get attributes for a product family.

    Returns list of attribute dicts from Family Attribute Template child table.
    """
    if not family_name:
        frappe.throw(_("Family name is required."))

    attributes = frappe.get_all(
        "Family Attribute Template",
        filters={"parent": family_name},
        fields=["attribute", "is_required_in_family", "default_value", "sort_order"],
        order_by="sort_order"
    )
    return attributes


@frappe.whitelist()
def bulk_update_attribute(products, attribute, value, locale=None):
    """Bulk update an attribute value across multiple products.

    Args:
        products: List of Product Master names
        attribute: PIM Attribute name
        value: Value to set
        locale: Optional locale code

    Returns:
        dict with 'updated' count and 'errors' list
    """
    if isinstance(products, str):
        import json
        products = json.loads(products)

    updated = 0
    errors = []

    for product_name in products:
        try:
            # Check product exists
            if not frappe.db.exists("Item", product_name):
                errors.append({"product": product_name, "error": "Product not found"})
                continue

            # Upsert attribute value in Product Attribute Value child table
            existing = frappe.db.get_value(
                "Product Attribute Value",
                {"parent": product_name, "attribute": attribute, "locale": locale or ""},
                "name"
            )
            if existing:
                frappe.db.set_value("Product Attribute Value", existing, "value_text", value)
            else:
                av = frappe.get_doc({
                    "doctype": "Product Attribute Value",
                    "parent": product_name,
                    "parenttype": "Product Master",
                    "parentfield": "attribute_values",
                    "attribute": attribute,
                    "value_text": value,
                    "locale": locale or "",
                })
                av.insert(ignore_permissions=True, ignore_links=True)
            updated += 1
        except Exception as e:
            errors.append({"product": product_name, "error": str(e)})

    return {"updated": updated, "errors": errors}


@frappe.whitelist()
def duplicate_product(product_name, new_code=None):
    """Duplicate a Product Master.

    Creates a new product with "(Copy)" appended to the name,
    a new unique product code, and status reset to Draft.

    Args:
        product_name: Name of the product to duplicate
        new_code: Optional explicit code for the new product

    Returns:
        Name of the newly created product
    """
    from frappe.utils import random_string

    if not product_name:
        frappe.throw(_("Product name is required."))

    source = frappe.get_doc("Product Master", product_name)

    if not new_code:
        new_code = f"{source.product_code}-COPY-{random_string(4).upper()}"

    new_doc = frappe.get_doc({
        "doctype": "Product Master",
        "product_name": f"{source.product_name} (Copy)",
        "product_code": new_code,
        "short_description": source.short_description,
        "status": "Draft",
        "product_family": source.product_family,
        "brand": source.brand,
        "manufacturer": source.manufacturer,
        "is_template": source.is_template,
    })
    new_doc.insert(ignore_permissions=True)
    return new_doc.name
