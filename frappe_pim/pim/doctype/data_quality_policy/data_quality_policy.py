"""
Data Quality Policy Controller

Manages configurable validation rules for product data quality.
Policies can be scoped globally, by product family, channel, or brand.
Each policy contains multiple validation rules that are evaluated
during product save, import, or scheduled quality scans.
"""

import re
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, cstr


class DataQualityPolicy(Document):
    """Data Quality Policy DocType controller.

    Manages validation rules for product data quality. Supports multiple
    rule types including required fields, format validation, length constraints,
    value ranges, regex patterns, and custom scripts.
    """

    def validate(self):
        """Validate the policy before save."""
        self.validate_policy_code()
        self.validate_rules()
        self.validate_scope()
        self.validate_scoring_config()

    def validate_policy_code(self):
        """Ensure policy code is URL-safe slug format."""
        if self.policy_code:
            # Convert to lowercase and replace spaces with hyphens
            normalized = self.policy_code.lower().strip()
            normalized = re.sub(r'[^a-z0-9-]', '-', normalized)
            normalized = re.sub(r'-+', '-', normalized)  # Remove consecutive hyphens
            normalized = normalized.strip('-')

            if normalized != self.policy_code:
                self.policy_code = normalized
                frappe.msgprint(
                    _("Policy code normalized to: {0}").format(normalized),
                    indicator="blue"
                )

    def validate_rules(self):
        """Validate the configuration of each rule."""
        if not self.rules:
            frappe.throw(
                _("At least one validation rule is required"),
                title=_("Missing Rules")
            )

        rule_names = []
        for rule in self.rules:
            # Check for duplicate rule names
            if rule.rule_name in rule_names:
                frappe.throw(
                    _("Duplicate rule name: {0}").format(rule.rule_name),
                    title=_("Duplicate Rule")
                )
            rule_names.append(rule.rule_name)

            # Validate rule-specific configuration
            self._validate_rule_config(rule)

    def _validate_rule_config(self, rule):
        """Validate configuration for a specific rule type."""
        rule_type = rule.rule_type

        if rule_type == "Field Length":
            if rule.min_length and rule.max_length:
                if cint(rule.min_length) > cint(rule.max_length):
                    frappe.throw(
                        _("Rule '{0}': Minimum length cannot exceed maximum length").format(
                            rule.rule_name
                        ),
                        title=_("Invalid Rule Configuration")
                    )

        elif rule_type == "Value Range":
            if rule.min_value is not None and rule.max_value is not None:
                if flt(rule.min_value) > flt(rule.max_value):
                    frappe.throw(
                        _("Rule '{0}': Minimum value cannot exceed maximum value").format(
                            rule.rule_name
                        ),
                        title=_("Invalid Rule Configuration")
                    )

        elif rule_type == "Regex Pattern":
            if not rule.regex_pattern:
                frappe.throw(
                    _("Rule '{0}': Regex pattern is required for Regex Pattern rule type").format(
                        rule.rule_name
                    ),
                    title=_("Invalid Rule Configuration")
                )
            # Validate regex pattern
            try:
                re.compile(rule.regex_pattern)
            except re.error as e:
                frappe.throw(
                    _("Rule '{0}': Invalid regex pattern: {1}").format(
                        rule.rule_name, str(e)
                    ),
                    title=_("Invalid Regex Pattern")
                )

        elif rule_type == "Conditional Required":
            if not rule.condition_field:
                frappe.throw(
                    _("Rule '{0}': Condition field is required for Conditional Required rule type").format(
                        rule.rule_name
                    ),
                    title=_("Invalid Rule Configuration")
                )
            if not rule.condition_operator:
                frappe.throw(
                    _("Rule '{0}': Condition operator is required for Conditional Required rule type").format(
                        rule.rule_name
                    ),
                    title=_("Invalid Rule Configuration")
                )

        elif rule_type == "Image Dimension":
            if not any([rule.min_width, rule.min_height, rule.max_width, rule.max_height]):
                frappe.throw(
                    _("Rule '{0}': At least one dimension constraint is required").format(
                        rule.rule_name
                    ),
                    title=_("Invalid Rule Configuration")
                )

        elif rule_type == "Custom Script":
            if not rule.custom_script:
                frappe.throw(
                    _("Rule '{0}': Custom script is required for Custom Script rule type").format(
                        rule.rule_name
                    ),
                    title=_("Invalid Rule Configuration")
                )

    def validate_scope(self):
        """Validate policy scope configuration."""
        if self.policy_type == "Product Family" and not self.apply_to_product_families:
            frappe.throw(
                _("Product Family policy type requires at least one product family to be selected"),
                title=_("Invalid Scope")
            )

        if self.policy_type == "Channel" and not self.apply_to_channels:
            frappe.throw(
                _("Channel policy type requires at least one channel to be selected"),
                title=_("Invalid Scope")
            )

        if self.policy_type == "Brand" and not self.apply_to_brands:
            frappe.throw(
                _("Brand policy type requires at least one brand to be selected"),
                title=_("Invalid Scope")
            )

    def validate_scoring_config(self):
        """Validate scoring configuration."""
        if self.include_in_score:
            if flt(self.policy_weight) <= 0:
                frappe.throw(
                    _("Policy weight must be greater than 0 when included in score calculation"),
                    title=_("Invalid Weight")
                )

    def on_update(self):
        """Actions after saving the policy."""
        # Clear cached policies
        frappe.cache().delete_key("data_quality_policies")

    def evaluate_product(self, product_doc):
        """Evaluate a product against this policy's rules.

        Args:
            product_doc: The product document to evaluate

        Returns:
            dict: Evaluation result with passed/failed rules and details
        """
        if not self.enabled:
            return {
                "policy": self.name,
                "policy_name": self.policy_name,
                "skipped": True,
                "reason": "Policy is disabled"
            }

        # Check if policy applies to this product
        if not self._applies_to_product(product_doc):
            return {
                "policy": self.name,
                "policy_name": self.policy_name,
                "skipped": True,
                "reason": "Policy does not apply to this product"
            }

        results = {
            "policy": self.name,
            "policy_name": self.policy_name,
            "skipped": False,
            "passed_rules": [],
            "failed_rules": [],
            "warnings": [],
            "total_rules": 0,
            "passed": True,
            "score": 100.0
        }

        enabled_rules = [r for r in self.rules if r.enabled]
        results["total_rules"] = len(enabled_rules)

        for rule in enabled_rules:
            rule_result = self._evaluate_rule(rule, product_doc)

            if rule_result["passed"]:
                results["passed_rules"].append({
                    "rule_name": rule.rule_name,
                    "target_field": rule.target_field
                })
            else:
                if rule.severity == "Error":
                    results["failed_rules"].append({
                        "rule_name": rule.rule_name,
                        "target_field": rule.target_field,
                        "severity": rule.severity,
                        "error_message": rule_result["error_message"],
                        "remediation_hint": rule.remediation_hint
                    })
                    results["passed"] = False
                elif rule.severity == "Warning":
                    results["warnings"].append({
                        "rule_name": rule.rule_name,
                        "target_field": rule.target_field,
                        "severity": rule.severity,
                        "error_message": rule_result["error_message"],
                        "remediation_hint": rule.remediation_hint
                    })
                # Info severity is logged but doesn't affect pass status

        # Calculate score
        if results["total_rules"] > 0:
            passed_count = len(results["passed_rules"])
            results["score"] = (passed_count / results["total_rules"]) * 100

            # Check minimum pass rate
            if results["score"] < flt(self.minimum_pass_rate):
                results["passed"] = False

        return results

    def _applies_to_product(self, product_doc):
        """Check if this policy applies to the given product."""
        if self.policy_type == "Global":
            # Check exclusions
            if self.exclude_product_families:
                excluded = [pf.product_family for pf in self.exclude_product_families]
                if product_doc.get("product_family") in excluded:
                    return False
            return True

        elif self.policy_type == "Product Family":
            if self.apply_to_product_families:
                families = [pf.product_family for pf in self.apply_to_product_families]
                return product_doc.get("product_family") in families
            return False

        elif self.policy_type == "Channel":
            if self.apply_to_channels:
                channels = [ch.channel for ch in self.apply_to_channels]
                # Check if product is assigned to any of these channels
                product_channels = product_doc.get("channels") or []
                if isinstance(product_channels, str):
                    product_channels = [product_channels]
                else:
                    product_channels = [c.channel if hasattr(c, 'channel') else c
                                       for c in product_channels]
                return bool(set(channels) & set(product_channels))
            return False

        elif self.policy_type == "Brand":
            if self.apply_to_brands:
                brands = [b.brand for b in self.apply_to_brands]
                return product_doc.get("brand") in brands
            return False

        elif self.policy_type == "Custom":
            # Custom policies can have multiple scope types
            matches = True

            if self.apply_to_product_families:
                families = [pf.product_family for pf in self.apply_to_product_families]
                if product_doc.get("product_family") not in families:
                    matches = False

            if self.apply_to_channels:
                channels = [ch.channel for ch in self.apply_to_channels]
                product_channels = product_doc.get("channels") or []
                if isinstance(product_channels, str):
                    product_channels = [product_channels]
                else:
                    product_channels = [c.channel if hasattr(c, 'channel') else c
                                       for c in product_channels]
                if not (set(channels) & set(product_channels)):
                    matches = False

            if self.apply_to_brands:
                brands = [b.brand for b in self.apply_to_brands]
                if product_doc.get("brand") not in brands:
                    matches = False

            return matches

        return True

    def _evaluate_rule(self, rule, product_doc):
        """Evaluate a single rule against a product."""
        result = {"passed": True, "error_message": ""}

        field_value = product_doc.get(rule.target_field)
        rule_type = rule.rule_type

        try:
            if rule_type == "Required Field":
                result = self._check_required(rule, field_value)

            elif rule_type == "Field Length":
                result = self._check_length(rule, field_value)

            elif rule_type == "Format Validation":
                result = self._check_format(rule, field_value)

            elif rule_type == "Value Range":
                result = self._check_range(rule, field_value)

            elif rule_type == "Allowed Values":
                result = self._check_allowed_values(rule, field_value)

            elif rule_type == "Regex Pattern":
                result = self._check_regex(rule, field_value)

            elif rule_type == "Unique Value":
                result = self._check_unique(rule, field_value, product_doc)

            elif rule_type == "Conditional Required":
                result = self._check_conditional_required(rule, field_value, product_doc)

            elif rule_type == "Image Dimension":
                result = self._check_image_dimension(rule, field_value)

            elif rule_type == "File Size":
                result = self._check_file_size(rule, field_value)

            elif rule_type == "Custom Script":
                result = self._check_custom_script(rule, field_value, product_doc)

        except Exception as e:
            result = {
                "passed": False,
                "error_message": _("Error evaluating rule: {0}").format(str(e))
            }

        # Use custom error message if provided
        if not result["passed"] and rule.error_message:
            result["error_message"] = rule.error_message

        return result

    def _check_required(self, rule, field_value):
        """Check if a required field has a value."""
        if field_value is None or field_value == "" or field_value == []:
            return {
                "passed": False,
                "error_message": _("{0} is required").format(rule.target_field)
            }
        return {"passed": True, "error_message": ""}

    def _check_length(self, rule, field_value):
        """Check field length constraints."""
        if field_value is None or field_value == "":
            return {"passed": True, "error_message": ""}  # Empty is OK for length check

        length = len(cstr(field_value))

        if rule.min_length and length < cint(rule.min_length):
            return {
                "passed": False,
                "error_message": _("{0} must be at least {1} characters (currently {2})").format(
                    rule.target_field, rule.min_length, length
                )
            }

        if rule.max_length and length > cint(rule.max_length):
            return {
                "passed": False,
                "error_message": _("{0} must not exceed {1} characters (currently {2})").format(
                    rule.target_field, rule.max_length, length
                )
            }

        return {"passed": True, "error_message": ""}

    def _check_format(self, rule, field_value):
        """Check format validation."""
        if not field_value:
            return {"passed": True, "error_message": ""}  # Empty is OK for format check

        format_type = rule.format_type
        value = cstr(field_value)

        patterns = {
            "Email": r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$',
            "URL": r'^https?://[^\s/$.?#].[^\s]*$',
            "Phone": r'^[\+]?[(]?[0-9]{1,3}[)]?[-\s\.]?[(]?[0-9]{1,4}[)]?[-\s\.]?[0-9]{1,4}[-\s\.]?[0-9]{1,9}$',
            "GTIN": r'^(\d{8}|\d{12}|\d{13}|\d{14})$',
            "SKU": r'^[A-Za-z0-9\-_]+$',
            "Date": r'^\d{4}-\d{2}-\d{2}$',
            "Currency": r'^\d+\.?\d{0,2}$',
            "Postal Code": r'^[A-Za-z0-9\s\-]{3,10}$'
        }

        if format_type in patterns:
            if not re.match(patterns[format_type], value):
                return {
                    "passed": False,
                    "error_message": _("{0} is not a valid {1}").format(
                        rule.target_field, format_type
                    )
                }

        # Additional GTIN check digit validation
        if format_type == "GTIN" and re.match(patterns["GTIN"], value):
            if not self._validate_gtin_check_digit(value):
                return {
                    "passed": False,
                    "error_message": _("{0} has invalid GTIN check digit").format(
                        rule.target_field
                    )
                }

        return {"passed": True, "error_message": ""}

    def _validate_gtin_check_digit(self, gtin):
        """Validate GTIN check digit using GS1 algorithm."""
        try:
            digits = [int(d) for d in gtin]
            # Reverse for consistent algorithm
            reversed_digits = digits[::-1]
            # Skip check digit (index 0), apply multipliers
            total = 0
            for i, digit in enumerate(reversed_digits[1:], 1):
                multiplier = 3 if i % 2 == 1 else 1
                total += digit * multiplier
            calculated = (10 - (total % 10)) % 10
            return calculated == reversed_digits[0]
        except (ValueError, IndexError):
            return False

    def _check_range(self, rule, field_value):
        """Check value range constraints."""
        if field_value is None or field_value == "":
            return {"passed": True, "error_message": ""}

        try:
            value = flt(field_value)
        except (ValueError, TypeError):
            return {
                "passed": False,
                "error_message": _("{0} must be a numeric value").format(rule.target_field)
            }

        if rule.min_value is not None and value < flt(rule.min_value):
            return {
                "passed": False,
                "error_message": _("{0} must be at least {1}").format(
                    rule.target_field, rule.min_value
                )
            }

        if rule.max_value is not None and value > flt(rule.max_value):
            return {
                "passed": False,
                "error_message": _("{0} must not exceed {1}").format(
                    rule.target_field, rule.max_value
                )
            }

        return {"passed": True, "error_message": ""}

    def _check_allowed_values(self, rule, field_value):
        """Check if value is in allowed list."""
        if not field_value:
            return {"passed": True, "error_message": ""}

        if not rule.allowed_values:
            return {"passed": True, "error_message": ""}

        allowed = [v.strip() for v in rule.allowed_values.split(",")]
        if cstr(field_value) not in allowed:
            return {
                "passed": False,
                "error_message": _("{0} must be one of: {1}").format(
                    rule.target_field, ", ".join(allowed)
                )
            }

        return {"passed": True, "error_message": ""}

    def _check_regex(self, rule, field_value):
        """Check regex pattern match."""
        if not field_value:
            return {"passed": True, "error_message": ""}

        if not re.match(rule.regex_pattern, cstr(field_value)):
            return {
                "passed": False,
                "error_message": _("{0} does not match required pattern").format(
                    rule.target_field
                )
            }

        return {"passed": True, "error_message": ""}

    def _check_unique(self, rule, field_value, product_doc):
        """Check if value is unique across products."""
        if not field_value:
            return {"passed": True, "error_message": ""}

        # Check for existing products with same value
        filters = {rule.target_field: field_value}
        if product_doc.get("name"):
            filters["name"] = ["!=", product_doc.name]

        existing = frappe.db.count("Product Master", filters)
        if existing > 0:
            return {
                "passed": False,
                "error_message": _("{0} value '{1}' already exists in another product").format(
                    rule.target_field, field_value
                )
            }

        return {"passed": True, "error_message": ""}

    def _check_conditional_required(self, rule, field_value, product_doc):
        """Check conditional required field."""
        condition_value = product_doc.get(rule.condition_field)
        operator = rule.condition_operator
        expected = rule.condition_value

        condition_met = False

        if operator == "Equals":
            condition_met = cstr(condition_value) == cstr(expected)
        elif operator == "Not Equals":
            condition_met = cstr(condition_value) != cstr(expected)
        elif operator == "In":
            allowed = [v.strip() for v in cstr(expected).split(",")]
            condition_met = cstr(condition_value) in allowed
        elif operator == "Not In":
            disallowed = [v.strip() for v in cstr(expected).split(",")]
            condition_met = cstr(condition_value) not in disallowed
        elif operator == "Is Set":
            condition_met = bool(condition_value)
        elif operator == "Is Not Set":
            condition_met = not bool(condition_value)

        if condition_met and not field_value:
            return {
                "passed": False,
                "error_message": _("{0} is required when {1} {2} {3}").format(
                    rule.target_field,
                    rule.condition_field,
                    operator.lower(),
                    expected or ""
                ).strip()
            }

        return {"passed": True, "error_message": ""}

    def _check_image_dimension(self, rule, field_value):
        """Check image dimension constraints."""
        if not field_value:
            return {"passed": True, "error_message": ""}

        # This would need actual image processing in production
        # For now, return passed if we can't verify
        try:
            from PIL import Image
            import io

            # Get file content
            file_doc = frappe.get_doc("File", {"file_url": field_value})
            if not file_doc:
                return {"passed": True, "error_message": ""}

            file_path = file_doc.get_full_path()
            with Image.open(file_path) as img:
                width, height = img.size

                if rule.min_width and width < cint(rule.min_width):
                    return {
                        "passed": False,
                        "error_message": _("Image width ({0}px) is less than minimum ({1}px)").format(
                            width, rule.min_width
                        )
                    }

                if rule.min_height and height < cint(rule.min_height):
                    return {
                        "passed": False,
                        "error_message": _("Image height ({0}px) is less than minimum ({1}px)").format(
                            height, rule.min_height
                        )
                    }

                if rule.max_width and width > cint(rule.max_width):
                    return {
                        "passed": False,
                        "error_message": _("Image width ({0}px) exceeds maximum ({1}px)").format(
                            width, rule.max_width
                        )
                    }

                if rule.max_height and height > cint(rule.max_height):
                    return {
                        "passed": False,
                        "error_message": _("Image height ({0}px) exceeds maximum ({1}px)").format(
                            height, rule.max_height
                        )
                    }

        except ImportError:
            # PIL not available, skip image validation
            pass
        except Exception:
            # Can't verify image, pass silently
            pass

        return {"passed": True, "error_message": ""}

    def _check_file_size(self, rule, field_value):
        """Check file size constraints."""
        if not field_value:
            return {"passed": True, "error_message": ""}

        try:
            file_doc = frappe.get_doc("File", {"file_url": field_value})
            if not file_doc:
                return {"passed": True, "error_message": ""}

            file_size_mb = (file_doc.file_size or 0) / (1024 * 1024)

            if rule.max_file_size_mb and file_size_mb > flt(rule.max_file_size_mb):
                return {
                    "passed": False,
                    "error_message": _("File size ({0:.2f}MB) exceeds maximum ({1}MB)").format(
                        file_size_mb, rule.max_file_size_mb
                    )
                }

            if rule.allowed_extensions:
                allowed = [e.strip().lower() for e in rule.allowed_extensions.split(",")]
                ext = (file_doc.file_name or "").split(".")[-1].lower()
                if ext not in allowed:
                    return {
                        "passed": False,
                        "error_message": _("File type '{0}' not allowed. Allowed: {1}").format(
                            ext, ", ".join(allowed)
                        )
                    }

        except Exception:
            pass

        return {"passed": True, "error_message": ""}

    def _check_custom_script(self, rule, field_value, product_doc):
        """Execute custom validation script."""
        if not rule.custom_script:
            return {"passed": True, "error_message": ""}

        try:
            # Create execution context
            exec_globals = {
                "doc": product_doc,
                "field_value": field_value,
                "frappe": frappe,
                "_": _,
                "result": True,
                "error_message": ""
            }

            # Execute script
            exec(rule.custom_script, exec_globals)

            if not exec_globals.get("result", True):
                return {
                    "passed": False,
                    "error_message": exec_globals.get("error_message", _("Custom validation failed"))
                }

        except Exception as e:
            return {
                "passed": False,
                "error_message": _("Custom script error: {0}").format(str(e))
            }

        return {"passed": True, "error_message": ""}

    def update_statistics(self, passed, failed):
        """Update policy statistics after evaluation."""
        self.total_products_evaluated = cint(self.total_products_evaluated) + passed + failed
        self.total_products_passed = cint(self.total_products_passed) + passed
        self.total_products_failed = cint(self.total_products_failed) + failed
        self.last_scan_date = frappe.utils.now()

        if self.total_products_evaluated > 0:
            self.pass_rate = (self.total_products_passed / self.total_products_evaluated) * 100

        self.db_update()


# =============================================================================
# API Functions
# =============================================================================

@frappe.whitelist()
def get_policies_for_product(product_name):
    """Get all applicable policies for a product.

    Args:
        product_name: Name of the Product Master document

    Returns:
        list: List of applicable policy names
    """
    product = frappe.get_doc("Product Master", product_name)
    policies = get_enabled_policies()

    applicable = []
    for policy in policies:
        policy_doc = frappe.get_doc("Data Quality Policy", policy.name)
        if policy_doc._applies_to_product(product):
            applicable.append({
                "name": policy_doc.name,
                "policy_name": policy_doc.policy_name,
                "policy_type": policy_doc.policy_type,
                "priority": policy_doc.priority
            })

    return sorted(applicable, key=lambda x: x["priority"])


@frappe.whitelist()
def evaluate_product_quality(product_name, policy_name=None):
    """Evaluate a product against quality policies.

    Args:
        product_name: Name of the Product Master document
        policy_name: Optional specific policy to evaluate (evaluates all if not specified)

    Returns:
        dict: Evaluation results
    """
    product = frappe.get_doc("Product Master", product_name)

    if policy_name:
        policies = [frappe.get_doc("Data Quality Policy", policy_name)]
    else:
        policies = [frappe.get_doc("Data Quality Policy", p.name)
                   for p in get_enabled_policies()]

    results = {
        "product": product_name,
        "overall_passed": True,
        "overall_score": 0.0,
        "policy_results": [],
        "all_errors": [],
        "all_warnings": []
    }

    total_weight = 0
    weighted_score = 0

    for policy in policies:
        policy_result = policy.evaluate_product(product)

        if not policy_result.get("skipped"):
            results["policy_results"].append(policy_result)

            if not policy_result.get("passed"):
                results["overall_passed"] = False

            results["all_errors"].extend(policy_result.get("failed_rules", []))
            results["all_warnings"].extend(policy_result.get("warnings", []))

            # Calculate weighted score
            if policy.include_in_score:
                weight = flt(policy.policy_weight) or 1.0
                total_weight += weight
                weighted_score += policy_result.get("score", 0) * weight

    if total_weight > 0:
        results["overall_score"] = weighted_score / total_weight

    return results


@frappe.whitelist()
def get_enabled_policies():
    """Get all enabled data quality policies.

    Returns:
        list: List of enabled policies ordered by priority
    """
    return frappe.get_all(
        "Data Quality Policy",
        filters={"enabled": 1},
        fields=["name", "policy_name", "policy_type", "priority",
                "enforcement_mode", "include_in_score"],
        order_by="priority asc"
    )


@frappe.whitelist()
def validate_rule_config(rule_type, config):
    """Validate rule configuration before saving.

    Args:
        rule_type: Type of validation rule
        config: Rule configuration as JSON string

    Returns:
        dict: Validation result
    """
    import json

    try:
        if isinstance(config, str):
            config = json.loads(config)
    except json.JSONDecodeError:
        return {"valid": False, "error": _("Invalid JSON configuration")}

    # Validation based on rule type
    validations = {
        "Field Length": lambda c: not (
            c.get("min_length") and c.get("max_length") and
            cint(c["min_length"]) > cint(c["max_length"])
        ),
        "Value Range": lambda c: not (
            c.get("min_value") is not None and c.get("max_value") is not None and
            flt(c["min_value"]) > flt(c["max_value"])
        ),
        "Regex Pattern": lambda c: _validate_regex(c.get("regex_pattern", "")),
    }

    validator = validations.get(rule_type)
    if validator and not validator(config):
        return {"valid": False, "error": _("Invalid configuration for rule type")}

    return {"valid": True}


def _validate_regex(pattern):
    """Validate a regex pattern."""
    if not pattern:
        return False
    try:
        re.compile(pattern)
        return True
    except re.error:
        return False


@frappe.whitelist()
def get_rule_types():
    """Get available rule types with descriptions.

    Returns:
        list: Rule types with descriptions
    """
    return [
        {"value": "Required Field", "label": _("Required Field"),
         "description": _("Ensure field has a value")},
        {"value": "Field Length", "label": _("Field Length"),
         "description": _("Check minimum/maximum character length")},
        {"value": "Format Validation", "label": _("Format Validation"),
         "description": _("Validate format (email, URL, GTIN, etc.)")},
        {"value": "Value Range", "label": _("Value Range"),
         "description": _("Check numeric value is within range")},
        {"value": "Allowed Values", "label": _("Allowed Values"),
         "description": _("Ensure value is in allowed list")},
        {"value": "Regex Pattern", "label": _("Regex Pattern"),
         "description": _("Match against regular expression")},
        {"value": "Unique Value", "label": _("Unique Value"),
         "description": _("Ensure value is unique across products")},
        {"value": "Conditional Required", "label": _("Conditional Required"),
         "description": _("Required based on another field's value")},
        {"value": "Image Dimension", "label": _("Image Dimension"),
         "description": _("Check image width/height constraints")},
        {"value": "File Size", "label": _("File Size"),
         "description": _("Check file size and type constraints")},
        {"value": "Custom Script", "label": _("Custom Script"),
         "description": _("Custom Python validation logic")}
    ]


@frappe.whitelist()
def reset_policy_statistics(policy_name):
    """Reset statistics for a policy.

    Args:
        policy_name: Name of the policy to reset

    Returns:
        dict: Success status
    """
    frappe.db.set_value("Data Quality Policy", policy_name, {
        "total_products_evaluated": 0,
        "total_products_passed": 0,
        "total_products_failed": 0,
        "pass_rate": 0,
        "last_scan_date": None
    })

    return {"success": True}
