"""Patch: Seed Industry Template records for all 7 sectors.

Creates Industry Template v1.0 records for the onboarding wizard:
fashion, industrial, food, electronics, health_beauty, automotive, custom.

Each template contains sector-specific attribute groups, product families,
default channels, compliance modules, scoring weights, category trees,
default languages, and demo product definitions stored as JSON.

All operations are idempotent — safe to run multiple times.

This patch runs during `bench migrate` for v1.0 installations.
"""

import frappe
from frappe import _
import json


def execute():
    """Main patch entry point.

    Performs the following setup steps:
    1. Check that Industry Template DocType exists
    2. Seed all 7 sector templates (skip existing ones)
    """
    _seed_industry_templates()


def _seed_industry_templates():
    """Create Industry Template records for all 7 sectors.

    Each template is created as v1.0 and marked as active. If a template
    with the same code and version already exists, it is skipped.

    Silently skips if the DocType doesn't exist yet (first install).
    """
    if not frappe.db.exists("DocType", "Industry Template"):
        return

    try:
        templates = _get_template_definitions()

        for template_data in templates:
            _create_template_if_not_exists(template_data)

        frappe.db.commit()

    except Exception:
        frappe.log_error(
            title="PIM Patch: Failed to seed industry templates",
            message=frappe.get_traceback(),
        )


def _create_template_if_not_exists(data):
    """Create a single Industry Template record if it doesn't exist.

    Args:
        data: Dict with template field values
    """
    template_code = data.get("template_code")
    version = data.get("version", "1.0")

    # Check if this template+version already exists
    existing = frappe.db.exists(
        "Industry Template",
        {"template_code": template_code, "version": version},
    )

    if existing:
        return

    doc = frappe.new_doc("Industry Template")
    doc.template_code = template_code
    doc.display_name = data.get("display_name", "")
    doc.version = version
    doc.is_active = data.get("is_active", 1)
    doc.description = data.get("description", "")
    doc.estimated_setup_minutes = data.get("estimated_setup_minutes", 15)
    doc.quality_threshold = data.get("quality_threshold", 70)

    # JSON fields — serialize lists/dicts to JSON strings
    json_fields = (
        "attribute_groups",
        "product_families",
        "default_channels",
        "coming_soon_channels",
        "compliance_modules",
        "scoring_weights",
        "default_languages",
        "category_tree",
        "demo_products",
    )

    for field in json_fields:
        value = data.get(field)
        if value is not None:
            if isinstance(value, (list, dict)):
                doc.set(field, json.dumps(value, indent=2))
            else:
                doc.set(field, value)

    doc.insert(ignore_permissions=True)


def _get_template_definitions():
    """Return the full list of 7 industry template definitions.

    Returns:
        List of dicts, each defining one Industry Template record.
    """
    return [
        _fashion_template(),
        _industrial_template(),
        _food_template(),
        _electronics_template(),
        _health_beauty_template(),
        _automotive_template(),
        _custom_template(),
    ]


# ---------------------------------------------------------------------------
# Template definitions — one function per sector
# ---------------------------------------------------------------------------


def _fashion_template():
    """Fashion & Apparel industry template."""
    return {
        "template_code": "fashion",
        "display_name": "Fashion & Apparel",
        "version": "1.0",
        "is_active": 1,
        "description": (
            "Complete PIM setup for fashion, apparel, footwear, and accessories "
            "retailers. Includes product families for clothing categories, variant "
            "axes for color/size, seasonal collection attributes, and a "
            "merchandising-oriented category tree."
        ),
        "estimated_setup_minutes": 12,
        "quality_threshold": 75,
        "attribute_groups": [
            {
                "group_name": "Fashion",
                "group_code": "fashion",
                "description": "Fashion-specific attributes: season, collection, style, fit",
                "attributes": [
                    {"name": "Season", "code": "season", "type": "Select",
                     "options": ["SS24", "AW24", "SS25", "AW25", "Resort", "Pre-Fall"]},
                    {"name": "Collection", "code": "collection", "type": "Data"},
                    {"name": "Style", "code": "style", "type": "Select",
                     "options": ["Casual", "Formal", "Sport", "Streetwear", "Evening"]},
                    {"name": "Fit", "code": "fit", "type": "Select",
                     "options": ["Slim", "Regular", "Relaxed", "Oversized", "Tailored"]},
                    {"name": "Gender", "code": "gender", "type": "Select",
                     "options": ["Men", "Women", "Unisex", "Kids", "Baby"]},
                    {"name": "Age Group", "code": "age_group", "type": "Select",
                     "options": ["Adult", "Teen", "Child", "Infant"]},
                ],
            },
            {
                "group_name": "Sizing",
                "group_code": "sizing",
                "description": "Size charts, fit guides, and measurement attributes",
                "attributes": [
                    {"name": "Size", "code": "size", "type": "Select",
                     "options": ["XXS", "XS", "S", "M", "L", "XL", "XXL", "3XL"]},
                    {"name": "Size System", "code": "size_system", "type": "Select",
                     "options": ["EU", "US", "UK", "IT", "FR", "JP"]},
                    {"name": "Chest (cm)", "code": "chest_cm", "type": "Number"},
                    {"name": "Waist (cm)", "code": "waist_cm", "type": "Number"},
                    {"name": "Hip (cm)", "code": "hip_cm", "type": "Number"},
                    {"name": "Length (cm)", "code": "length_cm", "type": "Number"},
                ],
            },
            {
                "group_name": "Care & Composition",
                "group_code": "care_composition",
                "description": "Fabric composition, care instructions, and material properties",
                "attributes": [
                    {"name": "Main Fabric", "code": "main_fabric", "type": "Data"},
                    {"name": "Fabric Composition", "code": "fabric_composition", "type": "Data"},
                    {"name": "Care Instructions", "code": "care_instructions", "type": "Multi Select",
                     "options": ["Machine Wash", "Hand Wash", "Dry Clean", "Do Not Bleach",
                                 "Tumble Dry Low", "Iron Low", "Do Not Iron"]},
                    {"name": "Lining Material", "code": "lining_material", "type": "Data"},
                ],
            },
        ],
        "product_families": [
            {"name": "Tops", "code": "tops", "children": [
                {"name": "T-Shirts", "code": "tshirts"},
                {"name": "Shirts", "code": "shirts"},
                {"name": "Blouses", "code": "blouses"},
                {"name": "Sweaters", "code": "sweaters"},
            ]},
            {"name": "Bottoms", "code": "bottoms", "children": [
                {"name": "Jeans", "code": "jeans"},
                {"name": "Trousers", "code": "trousers"},
                {"name": "Shorts", "code": "shorts"},
                {"name": "Skirts", "code": "skirts"},
            ]},
            {"name": "Outerwear", "code": "outerwear", "children": [
                {"name": "Jackets", "code": "jackets"},
                {"name": "Coats", "code": "coats"},
            ]},
            {"name": "Footwear", "code": "footwear", "children": [
                {"name": "Sneakers", "code": "sneakers"},
                {"name": "Boots", "code": "boots"},
                {"name": "Sandals", "code": "sandals"},
            ]},
            {"name": "Accessories", "code": "accessories", "children": [
                {"name": "Bags", "code": "bags"},
                {"name": "Belts", "code": "belts"},
                {"name": "Jewelry", "code": "jewelry"},
                {"name": "Scarves", "code": "scarves"},
            ]},
        ],
        "default_channels": [
            {"code": "webshop", "name": "Web Shop", "type": "ecommerce"},
            {"code": "trendyol", "name": "Trendyol", "type": "marketplace"},
            {"code": "hepsiburada", "name": "Hepsiburada", "type": "marketplace"},
            {"code": "amazon", "name": "Amazon", "type": "marketplace"},
        ],
        "coming_soon_channels": [
            {"code": "zalando", "name": "Zalando", "type": "marketplace"},
            {"code": "instagram_shop", "name": "Instagram Shop", "type": "social"},
        ],
        "compliance_modules": [
            {"code": "textile_labeling", "name": "Textile Labeling Regulation",
             "description": "EU/TR textile fiber composition labeling requirements"},
            {"code": "reach", "name": "REACH Compliance",
             "description": "Registration, Evaluation, Authorisation of Chemicals"},
        ],
        "scoring_weights": {
            "attributes": 30,
            "content": 25,
            "media": 25,
            "seo": 10,
            "compliance": 10,
        },
        "default_languages": ["tr", "en"],
        "category_tree": [
            {"name": "Women", "code": "women", "children": [
                {"name": "Clothing", "code": "women_clothing"},
                {"name": "Shoes", "code": "women_shoes"},
                {"name": "Accessories", "code": "women_accessories"},
            ]},
            {"name": "Men", "code": "men", "children": [
                {"name": "Clothing", "code": "men_clothing"},
                {"name": "Shoes", "code": "men_shoes"},
                {"name": "Accessories", "code": "men_accessories"},
            ]},
            {"name": "Kids", "code": "kids", "children": [
                {"name": "Girls", "code": "kids_girls"},
                {"name": "Boys", "code": "kids_boys"},
                {"name": "Baby", "code": "kids_baby"},
            ]},
        ],
        "demo_products": [
            {"name": "Cotton Crew T-Shirt", "family": "tshirts",
             "attributes": {"main_fabric": "100% Cotton", "fit": "Regular",
                            "gender": "Unisex"}},
            {"name": "Slim Fit Denim Jeans", "family": "jeans",
             "attributes": {"main_fabric": "98% Cotton, 2% Elastane",
                            "fit": "Slim", "gender": "Men"}},
        ],
    }


def _industrial_template():
    """Industrial & Manufacturing industry template."""
    return {
        "template_code": "industrial",
        "display_name": "Industrial & Manufacturing",
        "version": "1.0",
        "is_active": 1,
        "description": (
            "PIM configuration for industrial equipment, machinery parts, and "
            "manufacturing components. Emphasizes technical specifications, "
            "certifications, safety data sheets, and B2B catalog requirements."
        ),
        "estimated_setup_minutes": 15,
        "quality_threshold": 80,
        "attribute_groups": [
            {
                "group_name": "Technical Specifications",
                "group_code": "technical_specs",
                "description": "Detailed engineering and performance specifications",
                "attributes": [
                    {"name": "Power Rating", "code": "power_rating", "type": "Data"},
                    {"name": "Voltage", "code": "voltage", "type": "Select",
                     "options": ["12V", "24V", "110V", "220V", "380V", "Custom"]},
                    {"name": "Operating Temperature", "code": "operating_temp", "type": "Data"},
                    {"name": "IP Rating", "code": "ip_rating", "type": "Select",
                     "options": ["IP20", "IP44", "IP54", "IP65", "IP67", "IP68"]},
                    {"name": "Material Grade", "code": "material_grade", "type": "Data"},
                    {"name": "Tolerance", "code": "tolerance", "type": "Data"},
                ],
            },
            {
                "group_name": "Certifications & Standards",
                "group_code": "certifications",
                "description": "Industry certifications, test reports, and compliance marks",
                "attributes": [
                    {"name": "CE Marking", "code": "ce_marking", "type": "Check"},
                    {"name": "ISO Standard", "code": "iso_standard", "type": "Data"},
                    {"name": "UL Listed", "code": "ul_listed", "type": "Check"},
                    {"name": "RoHS Compliant", "code": "rohs_compliant", "type": "Check"},
                    {"name": "SDS Available", "code": "sds_available", "type": "Check"},
                ],
            },
            {
                "group_name": "Compatibility",
                "group_code": "compatibility",
                "description": "Machine compatibility and replacement part information",
                "attributes": [
                    {"name": "Compatible Models", "code": "compatible_models", "type": "Data"},
                    {"name": "OEM Part Number", "code": "oem_part_number", "type": "Data"},
                    {"name": "Cross Reference", "code": "cross_reference", "type": "Data"},
                ],
            },
        ],
        "product_families": [
            {"name": "Machinery", "code": "machinery", "children": [
                {"name": "CNC Machines", "code": "cnc_machines"},
                {"name": "Pumps", "code": "pumps"},
                {"name": "Compressors", "code": "compressors"},
            ]},
            {"name": "Components", "code": "components", "children": [
                {"name": "Bearings", "code": "bearings"},
                {"name": "Seals & Gaskets", "code": "seals_gaskets"},
                {"name": "Fasteners", "code": "fasteners"},
                {"name": "Valves", "code": "valves"},
            ]},
            {"name": "Electrical", "code": "electrical", "children": [
                {"name": "Motors", "code": "motors"},
                {"name": "Drives", "code": "drives"},
                {"name": "Sensors", "code": "sensors"},
                {"name": "Controllers", "code": "controllers"},
            ]},
            {"name": "Safety Equipment", "code": "safety_equipment", "children": [
                {"name": "PPE", "code": "ppe"},
                {"name": "Fire Safety", "code": "fire_safety"},
            ]},
        ],
        "default_channels": [
            {"code": "b2b_portal", "name": "B2B Portal", "type": "ecommerce"},
            {"code": "edi", "name": "EDI Integration", "type": "integration"},
            {"code": "catalog_pdf", "name": "PDF Catalog", "type": "print"},
        ],
        "coming_soon_channels": [
            {"code": "amazon_business", "name": "Amazon Business", "type": "marketplace"},
            {"code": "alibaba", "name": "Alibaba", "type": "marketplace"},
        ],
        "compliance_modules": [
            {"code": "ce_marking", "name": "CE Marking",
             "description": "European Conformity marking for machinery and equipment"},
            {"code": "rohs", "name": "RoHS Directive",
             "description": "Restriction of Hazardous Substances in electronic equipment"},
            {"code": "iso_9001", "name": "ISO 9001 Quality",
             "description": "Quality management system certification tracking"},
            {"code": "atex", "name": "ATEX Directive",
             "description": "Equipment for use in explosive atmospheres"},
        ],
        "scoring_weights": {
            "attributes": 35,
            "content": 15,
            "media": 15,
            "seo": 5,
            "compliance": 30,
        },
        "default_languages": ["tr", "en"],
        "category_tree": [
            {"name": "Machinery & Equipment", "code": "machinery_equipment", "children": [
                {"name": "CNC & Machining", "code": "cnc_machining"},
                {"name": "Hydraulics & Pneumatics", "code": "hydraulics_pneumatics"},
            ]},
            {"name": "Spare Parts", "code": "spare_parts", "children": [
                {"name": "Mechanical Parts", "code": "mechanical_parts"},
                {"name": "Electrical Parts", "code": "electrical_parts"},
            ]},
            {"name": "Tools & Consumables", "code": "tools_consumables", "children": [
                {"name": "Cutting Tools", "code": "cutting_tools"},
                {"name": "Measuring Instruments", "code": "measuring_instruments"},
            ]},
        ],
        "demo_products": [
            {"name": "Deep Groove Ball Bearing 6205", "family": "bearings",
             "attributes": {"material_grade": "Chrome Steel GCr15",
                            "ip_rating": "IP54", "ce_marking": True}},
        ],
    }


def _food_template():
    """Food & Beverage industry template."""
    return {
        "template_code": "food",
        "display_name": "Food & Beverage",
        "version": "1.0",
        "is_active": 1,
        "description": (
            "PIM configuration for food, beverage, and FMCG products. "
            "Focuses on nutritional information, allergen declarations, "
            "shelf life management, storage conditions, and food safety "
            "compliance (HACCP, FDA, EU food regulations)."
        ),
        "estimated_setup_minutes": 15,
        "quality_threshold": 85,
        "attribute_groups": [
            {
                "group_name": "Nutrition",
                "group_code": "nutrition",
                "description": "Nutritional facts, serving sizes, and dietary information",
                "attributes": [
                    {"name": "Serving Size", "code": "serving_size", "type": "Data"},
                    {"name": "Calories (kcal)", "code": "calories", "type": "Number"},
                    {"name": "Protein (g)", "code": "protein", "type": "Number"},
                    {"name": "Total Fat (g)", "code": "total_fat", "type": "Number"},
                    {"name": "Carbohydrates (g)", "code": "carbohydrates", "type": "Number"},
                    {"name": "Sugar (g)", "code": "sugar", "type": "Number"},
                    {"name": "Sodium (mg)", "code": "sodium", "type": "Number"},
                    {"name": "Fiber (g)", "code": "fiber", "type": "Number"},
                ],
            },
            {
                "group_name": "Allergens & Dietary",
                "group_code": "allergens",
                "description": "Allergen declarations and dietary classification",
                "attributes": [
                    {"name": "Contains Allergens", "code": "allergens_list", "type": "Multi Select",
                     "options": ["Gluten", "Dairy", "Eggs", "Nuts", "Peanuts", "Soy",
                                 "Fish", "Shellfish", "Sesame", "Celery", "Mustard",
                                 "Lupin", "Molluscs", "Sulphites"]},
                    {"name": "Dietary Labels", "code": "dietary_labels", "type": "Multi Select",
                     "options": ["Vegan", "Vegetarian", "Organic", "Gluten-Free",
                                 "Halal", "Kosher", "Sugar-Free", "Lactose-Free"]},
                ],
            },
            {
                "group_name": "Storage & Shelf Life",
                "group_code": "storage",
                "description": "Storage requirements, shelf life, and handling instructions",
                "attributes": [
                    {"name": "Storage Temperature", "code": "storage_temp", "type": "Select",
                     "options": ["Ambient", "Chilled (2-8C)", "Frozen (-18C)", "Cool & Dry"]},
                    {"name": "Shelf Life (days)", "code": "shelf_life_days", "type": "Number"},
                    {"name": "After Opening (days)", "code": "after_opening_days", "type": "Number"},
                    {"name": "Batch Tracking", "code": "batch_tracking", "type": "Check"},
                ],
            },
        ],
        "product_families": [
            {"name": "Dairy", "code": "dairy", "children": [
                {"name": "Milk", "code": "milk"},
                {"name": "Cheese", "code": "cheese"},
                {"name": "Yogurt", "code": "yogurt"},
            ]},
            {"name": "Bakery", "code": "bakery", "children": [
                {"name": "Bread", "code": "bread"},
                {"name": "Pastry", "code": "pastry"},
            ]},
            {"name": "Beverages", "code": "beverages", "children": [
                {"name": "Juices", "code": "juices"},
                {"name": "Soft Drinks", "code": "soft_drinks"},
                {"name": "Water", "code": "water"},
            ]},
            {"name": "Snacks", "code": "snacks", "children": [
                {"name": "Chips & Crisps", "code": "chips"},
                {"name": "Nuts & Dried Fruit", "code": "nuts_dried"},
                {"name": "Confectionery", "code": "confectionery"},
            ]},
            {"name": "Frozen Foods", "code": "frozen", "children": [
                {"name": "Ready Meals", "code": "ready_meals"},
                {"name": "Ice Cream", "code": "ice_cream"},
            ]},
        ],
        "default_channels": [
            {"code": "retail", "name": "Retail Stores", "type": "physical"},
            {"code": "online_grocery", "name": "Online Grocery", "type": "ecommerce"},
            {"code": "getir", "name": "Getir", "type": "marketplace"},
            {"code": "migros_sanal", "name": "Migros Sanal Market", "type": "marketplace"},
        ],
        "coming_soon_channels": [
            {"code": "trendyol_market", "name": "Trendyol Market", "type": "marketplace"},
        ],
        "compliance_modules": [
            {"code": "food_safety", "name": "Food Safety (HACCP)",
             "description": "Hazard Analysis and Critical Control Points compliance"},
            {"code": "nutrition_labeling", "name": "Nutrition Labeling",
             "description": "EU/TR mandatory nutrition information labeling"},
            {"code": "allergen_declaration", "name": "Allergen Declaration",
             "description": "Mandatory allergen information per EU Regulation 1169/2011"},
            {"code": "organic_cert", "name": "Organic Certification",
             "description": "EU/TR organic product certification tracking"},
        ],
        "scoring_weights": {
            "attributes": 25,
            "content": 15,
            "media": 15,
            "seo": 5,
            "compliance": 40,
        },
        "default_languages": ["tr", "en"],
        "category_tree": [
            {"name": "Fresh Foods", "code": "fresh_foods", "children": [
                {"name": "Dairy & Eggs", "code": "dairy_eggs"},
                {"name": "Meat & Poultry", "code": "meat_poultry"},
                {"name": "Fruits & Vegetables", "code": "fruits_vegetables"},
            ]},
            {"name": "Packaged Foods", "code": "packaged_foods", "children": [
                {"name": "Snacks", "code": "cat_snacks"},
                {"name": "Canned & Jarred", "code": "canned_jarred"},
                {"name": "Cereals & Grains", "code": "cereals_grains"},
            ]},
            {"name": "Beverages", "code": "cat_beverages", "children": [
                {"name": "Hot Drinks", "code": "hot_drinks"},
                {"name": "Cold Drinks", "code": "cold_drinks"},
            ]},
        ],
        "demo_products": [
            {"name": "Organic Whole Milk 1L", "family": "milk",
             "attributes": {"storage_temp": "Chilled (2-8C)",
                            "shelf_life_days": 14,
                            "dietary_labels": ["Organic"]}},
        ],
    }


def _electronics_template():
    """Consumer Electronics industry template."""
    return {
        "template_code": "electronics",
        "display_name": "Consumer Electronics",
        "version": "1.0",
        "is_active": 1,
        "description": (
            "PIM configuration for consumer electronics, computers, mobile "
            "devices, and accessories. Covers technical specifications, "
            "connectivity options, energy ratings, warranty information, "
            "and WEEE/RoHS compliance."
        ),
        "estimated_setup_minutes": 15,
        "quality_threshold": 80,
        "attribute_groups": [
            {
                "group_name": "Electronics Specs",
                "group_code": "electronics_specs",
                "description": "Core electronic specifications and performance metrics",
                "attributes": [
                    {"name": "Processor", "code": "processor", "type": "Data"},
                    {"name": "RAM", "code": "ram", "type": "Data"},
                    {"name": "Storage", "code": "storage", "type": "Data"},
                    {"name": "Display Size", "code": "display_size", "type": "Data"},
                    {"name": "Display Resolution", "code": "display_resolution", "type": "Data"},
                    {"name": "Battery Capacity", "code": "battery_capacity", "type": "Data"},
                ],
            },
            {
                "group_name": "Connectivity",
                "group_code": "connectivity",
                "description": "Wireless, wired, and port connectivity options",
                "attributes": [
                    {"name": "WiFi Standard", "code": "wifi_standard", "type": "Select",
                     "options": ["WiFi 5", "WiFi 6", "WiFi 6E", "WiFi 7"]},
                    {"name": "Bluetooth", "code": "bluetooth_version", "type": "Select",
                     "options": ["5.0", "5.1", "5.2", "5.3"]},
                    {"name": "USB Ports", "code": "usb_ports", "type": "Data"},
                    {"name": "HDMI", "code": "hdmi_version", "type": "Data"},
                ],
            },
            {
                "group_name": "Energy & Environment",
                "group_code": "energy_environment",
                "description": "Energy efficiency ratings and environmental compliance",
                "attributes": [
                    {"name": "Energy Rating", "code": "energy_rating", "type": "Select",
                     "options": ["A+++", "A++", "A+", "A", "B", "C", "D"]},
                    {"name": "Power Consumption (W)", "code": "power_consumption", "type": "Number"},
                    {"name": "Standby Power (W)", "code": "standby_power", "type": "Number"},
                    {"name": "WEEE Category", "code": "weee_category", "type": "Data"},
                ],
            },
        ],
        "product_families": [
            {"name": "Computers", "code": "computers", "children": [
                {"name": "Laptops", "code": "laptops"},
                {"name": "Desktops", "code": "desktops"},
                {"name": "Tablets", "code": "tablets"},
            ]},
            {"name": "Mobile Devices", "code": "mobile_devices", "children": [
                {"name": "Smartphones", "code": "smartphones"},
                {"name": "Wearables", "code": "wearables"},
            ]},
            {"name": "Audio & Video", "code": "audio_video", "children": [
                {"name": "Headphones", "code": "headphones"},
                {"name": "Speakers", "code": "speakers"},
                {"name": "TVs & Monitors", "code": "tvs_monitors"},
            ]},
            {"name": "Accessories", "code": "elec_accessories", "children": [
                {"name": "Cables & Adapters", "code": "cables"},
                {"name": "Cases & Covers", "code": "cases"},
                {"name": "Chargers", "code": "chargers"},
            ]},
        ],
        "default_channels": [
            {"code": "webshop", "name": "Web Shop", "type": "ecommerce"},
            {"code": "trendyol", "name": "Trendyol", "type": "marketplace"},
            {"code": "hepsiburada", "name": "Hepsiburada", "type": "marketplace"},
            {"code": "n11", "name": "N11", "type": "marketplace"},
        ],
        "coming_soon_channels": [
            {"code": "amazon_tr", "name": "Amazon TR", "type": "marketplace"},
        ],
        "compliance_modules": [
            {"code": "weee", "name": "WEEE Directive",
             "description": "Waste Electrical and Electronic Equipment disposal requirements"},
            {"code": "rohs", "name": "RoHS Directive",
             "description": "Restriction of Hazardous Substances in electronics"},
            {"code": "energy_labeling", "name": "Energy Labeling",
             "description": "EU energy efficiency labeling requirements"},
            {"code": "ce_marking", "name": "CE Marking",
             "description": "European Conformity for electronic products"},
        ],
        "scoring_weights": {
            "attributes": 35,
            "content": 20,
            "media": 20,
            "seo": 10,
            "compliance": 15,
        },
        "default_languages": ["tr", "en"],
        "category_tree": [
            {"name": "Computers & Tablets", "code": "computers_tablets", "children": [
                {"name": "Laptops", "code": "cat_laptops"},
                {"name": "Desktops", "code": "cat_desktops"},
                {"name": "Tablets", "code": "cat_tablets"},
            ]},
            {"name": "Mobile", "code": "mobile", "children": [
                {"name": "Smartphones", "code": "cat_smartphones"},
                {"name": "Wearables", "code": "cat_wearables"},
            ]},
            {"name": "Audio & Video", "code": "cat_audio_video", "children": [
                {"name": "Headphones & Earbuds", "code": "cat_headphones"},
                {"name": "TVs & Displays", "code": "cat_tvs"},
            ]},
        ],
        "demo_products": [
            {"name": "Wireless Bluetooth Headphones", "family": "headphones",
             "attributes": {"bluetooth_version": "5.3", "battery_capacity": "800mAh",
                            "energy_rating": "A+"}},
        ],
    }


def _health_beauty_template():
    """Health & Beauty industry template."""
    return {
        "template_code": "health_beauty",
        "display_name": "Health & Beauty",
        "version": "1.0",
        "is_active": 1,
        "description": (
            "PIM configuration for cosmetics, personal care, skincare, and "
            "health products. Covers ingredient lists (INCI), skin type "
            "targeting, SPF ratings, cruelty-free certifications, and "
            "cosmetics regulations compliance."
        ),
        "estimated_setup_minutes": 15,
        "quality_threshold": 80,
        "attribute_groups": [
            {
                "group_name": "Ingredients & Formulation",
                "group_code": "ingredients",
                "description": "Ingredient lists, INCI names, and formulation details",
                "attributes": [
                    {"name": "INCI List", "code": "inci_list", "type": "Long Text"},
                    {"name": "Key Ingredients", "code": "key_ingredients", "type": "Data"},
                    {"name": "Fragrance", "code": "fragrance", "type": "Select",
                     "options": ["Fragrance-Free", "Light", "Medium", "Strong"]},
                    {"name": "pH Level", "code": "ph_level", "type": "Number"},
                ],
            },
            {
                "group_name": "Targeting",
                "group_code": "targeting",
                "description": "Skin type, concern targeting, and application information",
                "attributes": [
                    {"name": "Skin Type", "code": "skin_type", "type": "Multi Select",
                     "options": ["Normal", "Dry", "Oily", "Combination", "Sensitive", "All"]},
                    {"name": "Concern", "code": "concern", "type": "Multi Select",
                     "options": ["Anti-Aging", "Hydration", "Acne", "Brightening",
                                 "Sun Protection", "Hair Loss", "Sensitivity"]},
                    {"name": "SPF Rating", "code": "spf_rating", "type": "Select",
                     "options": ["None", "SPF 15", "SPF 30", "SPF 50", "SPF 50+"]},
                    {"name": "Application Area", "code": "application_area", "type": "Select",
                     "options": ["Face", "Body", "Hair", "Lips", "Eyes", "Hands", "Full Body"]},
                ],
            },
            {
                "group_name": "Certifications",
                "group_code": "beauty_certs",
                "description": "Cruelty-free, organic, and clean beauty certifications",
                "attributes": [
                    {"name": "Cruelty-Free", "code": "cruelty_free", "type": "Check"},
                    {"name": "Vegan Formula", "code": "vegan_formula", "type": "Check"},
                    {"name": "Organic Certified", "code": "organic_certified", "type": "Check"},
                    {"name": "Dermatologically Tested", "code": "derm_tested", "type": "Check"},
                ],
            },
        ],
        "product_families": [
            {"name": "Skincare", "code": "skincare", "children": [
                {"name": "Cleansers", "code": "cleansers"},
                {"name": "Moisturizers", "code": "moisturizers"},
                {"name": "Serums", "code": "serums"},
                {"name": "Sunscreen", "code": "sunscreen"},
            ]},
            {"name": "Hair Care", "code": "hair_care", "children": [
                {"name": "Shampoo", "code": "shampoo"},
                {"name": "Conditioner", "code": "conditioner"},
                {"name": "Treatments", "code": "hair_treatments"},
            ]},
            {"name": "Makeup", "code": "makeup", "children": [
                {"name": "Foundation", "code": "foundation"},
                {"name": "Lipstick", "code": "lipstick"},
                {"name": "Eye Makeup", "code": "eye_makeup"},
            ]},
            {"name": "Personal Care", "code": "personal_care", "children": [
                {"name": "Body Wash", "code": "body_wash"},
                {"name": "Deodorant", "code": "deodorant"},
                {"name": "Oral Care", "code": "oral_care"},
            ]},
        ],
        "default_channels": [
            {"code": "webshop", "name": "Web Shop", "type": "ecommerce"},
            {"code": "trendyol", "name": "Trendyol", "type": "marketplace"},
            {"code": "watsons", "name": "Watsons", "type": "retail"},
            {"code": "gratis", "name": "Gratis", "type": "retail"},
        ],
        "coming_soon_channels": [
            {"code": "sephora", "name": "Sephora Online", "type": "marketplace"},
        ],
        "compliance_modules": [
            {"code": "cosmetics_regulation", "name": "EU Cosmetics Regulation",
             "description": "EC 1223/2009 cosmetics product safety and labeling"},
            {"code": "inci_labeling", "name": "INCI Labeling",
             "description": "International Nomenclature of Cosmetic Ingredients labeling"},
            {"code": "animal_testing", "name": "Animal Testing Ban",
             "description": "EU ban on animal-tested cosmetics compliance"},
        ],
        "scoring_weights": {
            "attributes": 30,
            "content": 25,
            "media": 20,
            "seo": 10,
            "compliance": 15,
        },
        "default_languages": ["tr", "en"],
        "category_tree": [
            {"name": "Skincare", "code": "cat_skincare", "children": [
                {"name": "Face Care", "code": "face_care"},
                {"name": "Body Care", "code": "body_care"},
                {"name": "Sun Care", "code": "sun_care"},
            ]},
            {"name": "Hair Care", "code": "cat_hair_care", "children": [
                {"name": "Shampoo & Conditioner", "code": "shampoo_conditioner"},
                {"name": "Styling", "code": "styling"},
            ]},
            {"name": "Makeup", "code": "cat_makeup", "children": [
                {"name": "Face", "code": "makeup_face"},
                {"name": "Eyes", "code": "makeup_eyes"},
                {"name": "Lips", "code": "makeup_lips"},
            ]},
        ],
        "demo_products": [
            {"name": "Hydrating Face Serum 30ml", "family": "serums",
             "attributes": {"skin_type": ["Dry", "Normal"], "concern": ["Hydration"],
                            "cruelty_free": True, "derm_tested": True}},
        ],
    }


def _automotive_template():
    """Automotive Parts & Accessories industry template."""
    return {
        "template_code": "automotive",
        "display_name": "Automotive Parts & Accessories",
        "version": "1.0",
        "is_active": 1,
        "description": (
            "PIM configuration for automotive parts, accessories, and aftermarket "
            "products. Includes vehicle compatibility (year/make/model fitment), "
            "OEM cross-references, TecDoc integration readiness, and automotive "
            "certification tracking."
        ),
        "estimated_setup_minutes": 18,
        "quality_threshold": 80,
        "attribute_groups": [
            {
                "group_name": "Vehicle Fitment",
                "group_code": "vehicle_fitment",
                "description": "Year/make/model compatibility and fitment data",
                "attributes": [
                    {"name": "Vehicle Make", "code": "vehicle_make", "type": "Data"},
                    {"name": "Vehicle Model", "code": "vehicle_model", "type": "Data"},
                    {"name": "Year Range", "code": "year_range", "type": "Data"},
                    {"name": "Engine Type", "code": "engine_type", "type": "Select",
                     "options": ["Gasoline", "Diesel", "Hybrid", "Electric", "LPG"]},
                    {"name": "Position", "code": "fitment_position", "type": "Select",
                     "options": ["Front", "Rear", "Left", "Right", "Front Left",
                                 "Front Right", "Rear Left", "Rear Right", "Universal"]},
                ],
            },
            {
                "group_name": "Part Identification",
                "group_code": "part_identification",
                "description": "OEM numbers, cross references, and TecDoc data",
                "attributes": [
                    {"name": "OEM Number", "code": "oem_number", "type": "Data"},
                    {"name": "Cross Reference", "code": "auto_cross_ref", "type": "Data"},
                    {"name": "TecDoc ID", "code": "tecdoc_id", "type": "Data"},
                    {"name": "Part Condition", "code": "part_condition", "type": "Select",
                     "options": ["New", "Remanufactured", "Used", "Refurbished"]},
                ],
            },
            {
                "group_name": "Performance",
                "group_code": "performance",
                "description": "Performance specifications and ratings",
                "attributes": [
                    {"name": "Material", "code": "auto_material", "type": "Data"},
                    {"name": "Load Rating", "code": "load_rating", "type": "Data"},
                    {"name": "Speed Rating", "code": "speed_rating", "type": "Data"},
                ],
            },
        ],
        "product_families": [
            {"name": "Engine Parts", "code": "engine_parts", "children": [
                {"name": "Filters", "code": "filters"},
                {"name": "Belts & Hoses", "code": "belts_hoses"},
                {"name": "Spark Plugs", "code": "spark_plugs"},
            ]},
            {"name": "Brake System", "code": "brake_system", "children": [
                {"name": "Brake Pads", "code": "brake_pads"},
                {"name": "Brake Discs", "code": "brake_discs"},
                {"name": "Brake Fluid", "code": "brake_fluid"},
            ]},
            {"name": "Suspension & Steering", "code": "suspension", "children": [
                {"name": "Shock Absorbers", "code": "shock_absorbers"},
                {"name": "Springs", "code": "springs"},
                {"name": "Steering Components", "code": "steering"},
            ]},
            {"name": "Electrical & Lighting", "code": "auto_electrical", "children": [
                {"name": "Batteries", "code": "batteries"},
                {"name": "Bulbs & LEDs", "code": "bulbs_leds"},
                {"name": "Starters & Alternators", "code": "starters_alternators"},
            ]},
            {"name": "Accessories", "code": "auto_accessories", "children": [
                {"name": "Floor Mats", "code": "floor_mats"},
                {"name": "Seat Covers", "code": "seat_covers"},
            ]},
        ],
        "default_channels": [
            {"code": "webshop", "name": "Web Shop", "type": "ecommerce"},
            {"code": "trendyol", "name": "Trendyol", "type": "marketplace"},
            {"code": "n11", "name": "N11", "type": "marketplace"},
        ],
        "coming_soon_channels": [
            {"code": "autodoc", "name": "Autodoc", "type": "marketplace"},
            {"code": "tecdoc_export", "name": "TecDoc Export", "type": "integration"},
        ],
        "compliance_modules": [
            {"code": "ece_regulations", "name": "ECE Regulations",
             "description": "UN Economic Commission for Europe vehicle part standards"},
            {"code": "type_approval", "name": "Type Approval",
             "description": "EU vehicle component type approval tracking"},
            {"code": "reach", "name": "REACH Compliance",
             "description": "Chemical substance registration for automotive materials"},
        ],
        "scoring_weights": {
            "attributes": 35,
            "content": 15,
            "media": 20,
            "seo": 5,
            "compliance": 25,
        },
        "default_languages": ["tr", "en"],
        "category_tree": [
            {"name": "Engine & Drivetrain", "code": "engine_drivetrain", "children": [
                {"name": "Engine Parts", "code": "cat_engine_parts"},
                {"name": "Transmission", "code": "transmission"},
            ]},
            {"name": "Braking & Suspension", "code": "braking_suspension", "children": [
                {"name": "Brakes", "code": "cat_brakes"},
                {"name": "Suspension", "code": "cat_suspension"},
            ]},
            {"name": "Body & Interior", "code": "body_interior", "children": [
                {"name": "Body Parts", "code": "body_parts"},
                {"name": "Interior Accessories", "code": "interior_accessories"},
            ]},
            {"name": "Electrical", "code": "cat_electrical", "children": [
                {"name": "Lighting", "code": "lighting"},
                {"name": "Batteries & Charging", "code": "batteries_charging"},
            ]},
        ],
        "demo_products": [
            {"name": "Ceramic Brake Pad Set - Front", "family": "brake_pads",
             "attributes": {"fitment_position": "Front",
                            "part_condition": "New",
                            "auto_material": "Ceramic Compound"}},
        ],
    }


def _custom_template():
    """Custom / Other industry template.

    Provides a minimal starting point for industries not covered by
    the standard sector templates. Users can fully customize their
    setup during the onboarding wizard.
    """
    return {
        "template_code": "custom",
        "display_name": "Custom / Other Industry",
        "version": "1.0",
        "is_active": 1,
        "description": (
            "Blank-slate template for industries not covered by the standard "
            "sector templates. Start with base PIM attributes and customize "
            "everything during onboarding. Ideal for niche markets, "
            "multi-category retailers, or unique product catalogs."
        ),
        "estimated_setup_minutes": 20,
        "quality_threshold": 70,
        "attribute_groups": [
            {
                "group_name": "Custom Attributes",
                "group_code": "custom",
                "description": "Add your own industry-specific attributes during onboarding",
                "attributes": [],
            },
        ],
        "product_families": [
            {"name": "General Products", "code": "general_products", "children": []},
        ],
        "default_channels": [
            {"code": "webshop", "name": "Web Shop", "type": "ecommerce"},
        ],
        "coming_soon_channels": [],
        "compliance_modules": [],
        "scoring_weights": {
            "attributes": 30,
            "content": 25,
            "media": 25,
            "seo": 10,
            "compliance": 10,
        },
        "default_languages": ["tr"],
        "category_tree": [],
        "demo_products": [],
    }
