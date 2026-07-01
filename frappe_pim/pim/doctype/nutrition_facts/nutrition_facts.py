"""
Nutrition Facts Controller

Manages nutrition and allergen data for products following GS1/GDSN standards.
Supports comprehensive nutrition labeling including:
- Energy values (kJ/kcal)
- Macronutrients (fat, carbohydrates, protein)
- Micronutrients (vitamins, minerals)
- Allergen declarations per GS1 allergen type codes
- Dietary information (organic, vegan, halal, etc.)

Compliant with:
- GS1 Global Data Standards for nutrition
- US FDA Nutrition Facts labeling
- EU Food Information Regulation (FIR)
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, cint, now_datetime


# GS1 Allergen Type Codes mapping
GS1_ALLERGEN_TYPE_CODES = {
    "Cereals containing gluten": "AW",
    "Crustaceans": "AC",
    "Eggs": "AE",
    "Fish": "AF",
    "Peanuts": "AP",
    "Soybeans": "AY",
    "Milk": "AM",
    "Tree nuts": "AN",
    "Celery": "BC",
    "Mustard": "BM",
    "Sesame seeds": "BS",
    "Sulphur dioxide and sulphites": "AU",
    "Lupin": "NL",
    "Molluscs": "UM",
    "Other": "X99"
}

# Daily Reference Values (US FDA 2020 for 2000 calorie diet)
DAILY_REFERENCE_VALUES = {
    "total_fat": 78,  # g
    "saturated_fat": 20,  # g
    "cholesterol": 300,  # mg
    "sodium": 2300,  # mg
    "total_carbohydrate": 275,  # g
    "dietary_fiber": 28,  # g
    "added_sugars": 50,  # g
    "protein": 50,  # g
    "vitamin_d": 20,  # mcg
    "calcium": 1300,  # mg
    "iron": 18,  # mg
    "potassium": 4700,  # mg
    "vitamin_a": 900,  # mcg RAE
    "vitamin_c": 90,  # mg
    "vitamin_e": 15,  # mg
    "vitamin_k": 120,  # mcg
    "thiamin": 1.2,  # mg
    "riboflavin": 1.3,  # mg
    "niacin": 16,  # mg NE
    "vitamin_b6": 1.7,  # mg
    "vitamin_b12": 2.4,  # mcg
    "folate": 400,  # mcg DFE
    "biotin": 30,  # mcg
    "pantothenic_acid": 5,  # mg
    "choline": 550,  # mg
    "magnesium": 420,  # mg
    "zinc": 11,  # mg
    "selenium": 55,  # mcg
    "copper": 0.9,  # mg
    "phosphorus": 1250,  # mg
}

# Required fields for different regulatory frameworks
REQUIRED_FIELDS_FDA = [
    "energy_kcal", "total_fat", "saturated_fat", "trans_fat",
    "cholesterol", "sodium", "total_carbohydrate", "dietary_fiber",
    "total_sugars", "added_sugars", "protein", "vitamin_d",
    "calcium", "iron", "potassium"
]

REQUIRED_FIELDS_EU = [
    "energy_kj", "energy_kcal", "total_fat", "saturated_fat",
    "total_carbohydrate", "total_sugars", "protein", "salt"
]


class NutritionFacts(Document):
    """Nutrition Facts DocType controller.

    Manages nutrition and allergen information for products
    following GS1/GDSN standards for food labeling compliance.
    """

    def validate(self):
        """Validate the nutrition facts before save."""
        self.validate_energy_values()
        self.validate_nutrient_values()
        self.validate_allergens()
        self.set_allergen_type_codes()
        self.generate_allergen_statement()
        self.calculate_completeness()
        self.run_validation()

    def validate_energy_values(self):
        """Validate energy value consistency.

        The relationship between kJ and kcal should be approximately 4.184.
        """
        if self.energy_kj and self.energy_kcal:
            # Calculate expected kcal from kJ
            expected_kcal = flt(self.energy_kj) / 4.184

            # Allow 5% variance for rounding
            variance = abs(flt(self.energy_kcal) - expected_kcal) / expected_kcal if expected_kcal else 0

            if variance > 0.05:
                frappe.msgprint(
                    _("Energy values may be inconsistent. "
                      "{0} kJ = {1} kcal (expected: {2} kcal)").format(
                        self.energy_kj, self.energy_kcal, round(expected_kcal, 1)
                    ),
                    title=_("Energy Value Warning"),
                    indicator="orange"
                )

    def validate_nutrient_values(self):
        """Validate that nutrient values are non-negative and consistent."""
        errors = []

        # All nutrition fields should be non-negative
        nutrition_fields = [
            "energy_kj", "energy_kcal", "energy_from_fat_kcal",
            "total_fat", "saturated_fat", "trans_fat",
            "polyunsaturated_fat", "monounsaturated_fat", "cholesterol",
            "total_carbohydrate", "dietary_fiber", "total_sugars",
            "added_sugars", "sugar_alcohol", "protein", "sodium", "salt",
            "serving_size", "servings_per_container"
        ]

        for field in nutrition_fields:
            value = self.get(field)
            if value is not None and flt(value) < 0:
                errors.append(
                    _("{0} cannot be negative").format(
                        self.meta.get_label(field)
                    )
                )

        # Validate fat components don't exceed total fat
        if self.total_fat:
            fat_components = (
                flt(self.saturated_fat) +
                flt(self.trans_fat) +
                flt(self.polyunsaturated_fat) +
                flt(self.monounsaturated_fat)
            )
            if fat_components > flt(self.total_fat) * 1.05:  # 5% tolerance
                errors.append(
                    _("Sum of fat components ({0}g) exceeds total fat ({1}g)").format(
                        round(fat_components, 1), self.total_fat
                    )
                )

        # Validate carb components don't exceed total carbs
        if self.total_carbohydrate:
            carb_components = (
                flt(self.dietary_fiber) +
                flt(self.total_sugars) +
                flt(self.sugar_alcohol)
            )
            if carb_components > flt(self.total_carbohydrate) * 1.05:  # 5% tolerance
                errors.append(
                    _("Sum of carbohydrate components ({0}g) exceeds total carbohydrate ({1}g)").format(
                        round(carb_components, 1), self.total_carbohydrate
                    )
                )

        # Validate added sugars don't exceed total sugars
        if self.added_sugars and self.total_sugars:
            if flt(self.added_sugars) > flt(self.total_sugars):
                errors.append(
                    _("Added sugars ({0}g) cannot exceed total sugars ({1}g)").format(
                        self.added_sugars, self.total_sugars
                    )
                )

        # Validate sodium/salt relationship (salt = sodium * 2.5 approximately)
        if self.sodium and self.salt:
            expected_salt = flt(self.sodium) * 2.5 / 1000  # mg to g
            if abs(flt(self.salt) - expected_salt) > expected_salt * 0.1:  # 10% tolerance
                frappe.msgprint(
                    _("Salt/Sodium ratio may be inconsistent. "
                      "{0}mg sodium = {1}g salt (expected: {2}g)").format(
                        self.sodium, self.salt, round(expected_salt, 2)
                    ),
                    title=_("Salt/Sodium Warning"),
                    indicator="orange"
                )

        if errors:
            frappe.throw(
                _("Nutrition Value Errors:<br>") + "<br>".join(errors),
                title=_("Validation Error")
            )

    def validate_allergens(self):
        """Validate allergen information consistency."""
        if self.has_allergens and not self.allergens:
            frappe.throw(
                _("Allergen information is required when 'Contains Allergens' is checked"),
                title=_("Allergen Validation Error")
            )

        if self.allergens and not self.has_allergens:
            self.has_allergens = 1

        # Check for duplicate allergen types
        allergen_types = [row.allergen_type for row in self.allergens]
        duplicates = set([x for x in allergen_types if allergen_types.count(x) > 1])

        if duplicates:
            frappe.throw(
                _("Duplicate allergen types: {0}").format(", ".join(duplicates)),
                title=_("Allergen Validation Error")
            )

        # Validate allergen containment logic
        for row in self.allergens:
            if row.level_of_containment == "FREE_FROM":
                # If free from, shouldn't be marked as containing
                pass
            elif row.level_of_containment == "CONTAINS":
                # Must have an allergen statement
                if not row.allergen_statement:
                    row.allergen_statement = _("Contains {0}").format(
                        row.allergen_type
                    )

    def set_allergen_type_codes(self):
        """Set GS1 allergen type codes for each allergen."""
        for row in self.allergens:
            if row.allergen_type in GS1_ALLERGEN_TYPE_CODES:
                row.allergen_type_code = GS1_ALLERGEN_TYPE_CODES[row.allergen_type]

    def generate_allergen_statement(self):
        """Generate combined allergen statement from individual allergens."""
        if not self.allergens:
            self.allergen_statement = ""
            return

        contains = []
        may_contain = []
        free_from = []

        for row in self.allergens:
            source = row.source_specification or row.allergen_type
            if row.level_of_containment == "CONTAINS":
                contains.append(source)
            elif row.level_of_containment == "MAY_CONTAIN":
                may_contain.append(source)
            elif row.level_of_containment == "FREE_FROM":
                free_from.append(source)

        statements = []

        if contains:
            statements.append(_("Contains: {0}").format(", ".join(contains)))

        if may_contain:
            statements.append(_("May contain: {0}").format(", ".join(may_contain)))

        if free_from:
            statements.append(_("Free from: {0}").format(", ".join(free_from)))

        self.allergen_statement = ". ".join(statements)

    def calculate_completeness(self):
        """Calculate completeness score based on target market requirements."""
        # Determine required fields based on target market
        if self.target_market:
            country = frappe.get_value("Country", self.target_market, "code")
            if country == "US":
                required_fields = REQUIRED_FIELDS_FDA
            elif country in ["GB", "DE", "FR", "IT", "ES", "NL", "BE", "AT", "CH"]:
                required_fields = REQUIRED_FIELDS_EU
            else:
                required_fields = REQUIRED_FIELDS_FDA  # Default to FDA
        else:
            required_fields = REQUIRED_FIELDS_FDA  # Default to FDA

        # Count completed fields
        completed = 0
        for field in required_fields:
            value = self.get(field)
            if value is not None and value != "" and value != 0:
                completed += 1

        # Calculate percentage
        if required_fields:
            self.completeness_score = (completed / len(required_fields)) * 100
        else:
            self.completeness_score = 100

    def run_validation(self):
        """Run comprehensive validation and set status."""
        errors = []

        # Check required serving information
        if self.serving_size is None or flt(self.serving_size) <= 0:
            errors.append(_("Serving size is required and must be positive"))

        # Check at least energy is provided
        if not self.energy_kj and not self.energy_kcal:
            errors.append(_("At least one energy value (kJ or kcal) is required"))

        # Check macronutrients
        if self.total_fat is None:
            errors.append(_("Total fat is required for nutrition labeling"))

        if self.total_carbohydrate is None:
            errors.append(_("Total carbohydrate is required for nutrition labeling"))

        if self.protein is None:
            errors.append(_("Protein is required for nutrition labeling"))

        # Check dietary flags consistency
        if self.is_vegan and not self.is_vegetarian:
            self.is_vegetarian = 1

        if self.is_gluten_free:
            # Check allergens don't include gluten
            for row in self.allergens:
                if (row.allergen_type == "Cereals containing gluten" and
                    row.level_of_containment == "CONTAINS"):
                    errors.append(
                        _("Product marked as gluten-free but contains cereals with gluten")
                    )

        if self.is_lactose_free:
            # Check allergens don't include milk
            for row in self.allergens:
                if (row.allergen_type == "Milk" and
                    row.level_of_containment == "CONTAINS"):
                    frappe.msgprint(
                        _("Product marked as lactose-free but contains milk allergen. "
                          "This may be valid for lactose-free dairy products."),
                        title=_("Allergen Check"),
                        indicator="blue"
                    )

        # Set validation status
        if errors:
            self.validation_status = "Invalid"
            self.validation_errors = "\n".join(errors)
        else:
            self.validation_status = "Valid"
            self.validation_errors = None

        self.last_validated = now_datetime()

    def on_update(self):
        """Actions after saving the nutrition facts."""
        # Set as default for product if active
        if self.product and self.status == "Active":
            self.set_as_default_nutrition()

    def set_as_default_nutrition(self):
        """Set this as the default nutrition facts for the product.

        Deactivates other nutrition facts for the same product/market.
        """
        if not self.product or self.status != "Active":
            return

        # Find other active nutrition facts for same product and market
        filters = {
            "product": self.product,
            "status": "Active",
            "name": ["!=", self.name]
        }
        if self.target_market:
            filters["target_market"] = self.target_market

        other_nutrition = frappe.get_all(
            "Nutrition Facts",
            filters=filters,
            pluck="name"
        )

        # Deprecate others
        for nutrition_name in other_nutrition:
            frappe.db.set_value(
                "Nutrition Facts",
                nutrition_name,
                "status",
                "Deprecated",
                update_modified=False
            )

        if other_nutrition:
            frappe.msgprint(
                _("Deprecated {0} other nutrition facts record(s) for this product").format(
                    len(other_nutrition)
                ),
                indicator="blue"
            )

    def before_submit(self):
        """Validate before submission."""
        if self.validation_status != "Valid":
            frappe.throw(
                _("Cannot submit nutrition facts with validation errors"),
                title=_("Validation Required")
            )


# =============================================================================
# API Functions
# =============================================================================

@frappe.whitelist()
def get_product_nutrition(product: str, target_market: str = None):
    """Get the active nutrition facts for a product.

    Args:
        product: Product Master name
        target_market: Optional target market country

    Returns:
        dict: Nutrition facts data or None
    """
    filters = {
        "product": product,
        "status": "Active"
    }
    if target_market:
        filters["target_market"] = target_market

    nutrition = frappe.get_all(
        "Nutrition Facts",
        filters=filters,
        order_by="modified desc",
        limit=1
    )

    if nutrition:
        return frappe.get_doc("Nutrition Facts", nutrition[0].name).as_dict()

    return None


@frappe.whitelist()
def calculate_daily_value_percentages(nutrition_facts_name: str):
    """Calculate % Daily Value for all nutrients.

    Args:
        nutrition_facts_name: Name of the Nutrition Facts document

    Returns:
        dict: Nutrient name to % Daily Value mapping
    """
    doc = frappe.get_doc("Nutrition Facts", nutrition_facts_name)
    percentages = {}

    for nutrient, daily_value in DAILY_REFERENCE_VALUES.items():
        value = doc.get(nutrient)
        if value is not None and daily_value:
            percentages[nutrient] = {
                "value": flt(value),
                "daily_value": daily_value,
                "percentage": round((flt(value) / daily_value) * 100, 0)
            }

    return percentages


@frappe.whitelist()
def validate_nutrition_for_market(nutrition_facts_name: str, market: str = "US"):
    """Validate nutrition facts against market-specific requirements.

    Args:
        nutrition_facts_name: Name of the Nutrition Facts document
        market: Target market code (US, EU, etc.)

    Returns:
        dict: Validation result with errors and warnings
    """
    doc = frappe.get_doc("Nutrition Facts", nutrition_facts_name)

    if market == "US":
        required_fields = REQUIRED_FIELDS_FDA
    else:
        required_fields = REQUIRED_FIELDS_EU

    missing = []
    for field in required_fields:
        value = doc.get(field)
        if value is None or value == "":
            missing.append(doc.meta.get_label(field))

    return {
        "market": market,
        "is_compliant": len(missing) == 0,
        "missing_fields": missing,
        "required_fields_count": len(required_fields),
        "completed_fields_count": len(required_fields) - len(missing),
        "completeness_percentage": round(
            ((len(required_fields) - len(missing)) / len(required_fields)) * 100, 1
        )
    }


@frappe.whitelist()
def get_allergen_types():
    """Get list of GS1 allergen types with codes.

    Returns:
        list: List of allergen types with GS1 codes
    """
    return [
        {"type": key, "code": value}
        for key, value in GS1_ALLERGEN_TYPE_CODES.items()
    ]


@frappe.whitelist()
def convert_energy(value: float, from_unit: str, to_unit: str):
    """Convert energy values between kJ and kcal.

    Args:
        value: Energy value to convert
        from_unit: Source unit (kj or kcal)
        to_unit: Target unit (kj or kcal)

    Returns:
        dict: Converted value with details
    """
    value = flt(value)
    from_unit = from_unit.lower()
    to_unit = to_unit.lower()

    if from_unit == to_unit:
        return {"value": value, "unit": to_unit}

    if from_unit == "kj" and to_unit == "kcal":
        converted = value / 4.184
    elif from_unit == "kcal" and to_unit == "kj":
        converted = value * 4.184
    else:
        frappe.throw(_("Invalid unit. Use 'kj' or 'kcal'"))

    return {
        "original_value": value,
        "original_unit": from_unit,
        "converted_value": round(converted, 1),
        "converted_unit": to_unit,
        "conversion_factor": 4.184
    }


@frappe.whitelist()
def generate_nutrition_label_data(nutrition_facts_name: str, format_type: str = "FDA"):
    """Generate structured data for nutrition label rendering.

    Args:
        nutrition_facts_name: Name of the Nutrition Facts document
        format_type: Label format (FDA, EU)

    Returns:
        dict: Structured data for label rendering
    """
    doc = frappe.get_doc("Nutrition Facts", nutrition_facts_name)

    # Calculate % Daily Values
    dv = {}
    for nutrient, daily_value in DAILY_REFERENCE_VALUES.items():
        value = doc.get(nutrient)
        if value is not None and daily_value:
            dv[nutrient] = round((flt(value) / daily_value) * 100, 0)

    if format_type == "FDA":
        return {
            "format": "FDA",
            "serving_size": doc.serving_size_description or f"{doc.serving_size}{doc.serving_size_uom}",
            "servings_per_container": doc.servings_per_container,
            "calories": doc.energy_kcal,
            "nutrients": [
                {"name": "Total Fat", "value": doc.total_fat, "unit": "g", "dv": dv.get("total_fat")},
                {"name": "Saturated Fat", "value": doc.saturated_fat, "unit": "g", "dv": dv.get("saturated_fat"), "indent": 1},
                {"name": "Trans Fat", "value": doc.trans_fat, "unit": "g", "indent": 1},
                {"name": "Cholesterol", "value": doc.cholesterol, "unit": "mg", "dv": dv.get("cholesterol")},
                {"name": "Sodium", "value": doc.sodium, "unit": "mg", "dv": dv.get("sodium")},
                {"name": "Total Carbohydrate", "value": doc.total_carbohydrate, "unit": "g", "dv": dv.get("total_carbohydrate")},
                {"name": "Dietary Fiber", "value": doc.dietary_fiber, "unit": "g", "dv": dv.get("dietary_fiber"), "indent": 1},
                {"name": "Total Sugars", "value": doc.total_sugars, "unit": "g", "indent": 1},
                {"name": "Added Sugars", "value": doc.added_sugars, "unit": "g", "dv": dv.get("added_sugars"), "indent": 2},
                {"name": "Protein", "value": doc.protein, "unit": "g", "dv": dv.get("protein")},
                {"name": "Vitamin D", "value": doc.vitamin_d, "unit": "mcg", "dv": dv.get("vitamin_d")},
                {"name": "Calcium", "value": doc.calcium, "unit": "mg", "dv": dv.get("calcium")},
                {"name": "Iron", "value": doc.iron, "unit": "mg", "dv": dv.get("iron")},
                {"name": "Potassium", "value": doc.potassium, "unit": "mg", "dv": dv.get("potassium")},
            ],
            "allergen_statement": doc.allergen_statement,
            "ingredient_statement": doc.ingredient_statement
        }
    else:  # EU format
        return {
            "format": "EU",
            "serving_size": f"{doc.serving_size}{doc.serving_size_uom}",
            "reference_quantity": doc.reference_quantity or "Per 100g",
            "nutrients": [
                {"name": "Energy", "value": doc.energy_kj, "unit": "kJ"},
                {"name": "Energy", "value": doc.energy_kcal, "unit": "kcal"},
                {"name": "Fat", "value": doc.total_fat, "unit": "g"},
                {"name": "of which saturates", "value": doc.saturated_fat, "unit": "g", "indent": 1},
                {"name": "Carbohydrate", "value": doc.total_carbohydrate, "unit": "g"},
                {"name": "of which sugars", "value": doc.total_sugars, "unit": "g", "indent": 1},
                {"name": "Protein", "value": doc.protein, "unit": "g"},
                {"name": "Salt", "value": doc.salt, "unit": "g"},
            ],
            "allergen_statement": doc.allergen_statement,
            "ingredient_statement": doc.ingredient_statement
        }


@frappe.whitelist()
def get_nutrition_facts_summary(product: str):
    """Get a summary of all nutrition facts for a product.

    Args:
        product: Product Master name

    Returns:
        list: Summary of nutrition facts records
    """
    nutrition_records = frappe.get_all(
        "Nutrition Facts",
        filters={"product": product},
        fields=[
            "name",
            "nutrition_facts_name",
            "status",
            "target_market",
            "energy_kcal",
            "total_fat",
            "total_carbohydrate",
            "protein",
            "has_allergens",
            "completeness_score",
            "validation_status",
            "modified"
        ],
        order_by="modified desc"
    )

    return nutrition_records
