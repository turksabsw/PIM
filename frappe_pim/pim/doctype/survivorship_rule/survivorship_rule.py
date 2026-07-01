"""
Survivorship Rule Controller
Manages value selection rules for Golden Record merges in PIM MDM
"""

import frappe
from frappe import _
from frappe.model.document import Document
from typing import Optional, List, Dict, Any
import re


class SurvivorshipRule(Document):
    def validate(self):
        self.validate_rule_code()
        self.validate_rule_type_config()
        self.validate_scope_config()
        self.validate_custom_method()
        self.validate_default_rule()

    def validate_rule_code(self):
        """Ensure rule_code is URL-safe slug"""
        if not self.rule_code:
            self.rule_code = frappe.scrub(self.rule_name)

        if not re.match(r'^[a-z][a-z0-9_-]*$', self.rule_code):
            frappe.throw(
                _("Rule Code must start with a letter and contain only lowercase letters, numbers, underscores, and hyphens"),
                title=_("Invalid Rule Code")
            )

    def validate_rule_type_config(self):
        """Validate configuration based on rule type"""
        if self.rule_type == "Source Priority":
            if not self.source_priorities or len(self.source_priorities) == 0:
                frappe.throw(
                    _("Source Priority rule type requires at least one source priority entry"),
                    title=_("Missing Source Priorities")
                )

        elif self.rule_type == "Authoritative Source":
            if not self.authoritative_source:
                frappe.throw(
                    _("Authoritative Source rule type requires an authoritative source system to be selected"),
                    title=_("Missing Authoritative Source")
                )

            if self.allow_fallback and not self.fallback_rule_type:
                frappe.throw(
                    _("Fallback Rule Type is required when 'Allow Fallback' is enabled"),
                    title=_("Missing Fallback Rule Type")
                )

        elif self.rule_type == "Custom":
            if not self.custom_method:
                frappe.throw(
                    _("Custom rule type requires a custom method to be specified"),
                    title=_("Missing Custom Method")
                )

    def validate_scope_config(self):
        """Validate field scope configuration"""
        if self.applies_to == "Specific Fields":
            if not self.specific_fields:
                frappe.throw(
                    _("Specific Fields must be provided when 'Applies To' is set to 'Specific Fields'"),
                    title=_("Missing Specific Fields")
                )

        elif self.applies_to == "Field Pattern":
            if not self.field_pattern:
                frappe.throw(
                    _("Field Pattern must be provided when 'Applies To' is set to 'Field Pattern'"),
                    title=_("Missing Field Pattern")
                )
            try:
                re.compile(self.field_pattern)
            except re.error as e:
                frappe.throw(
                    _("Invalid regex pattern for Field Pattern: {0}").format(str(e)),
                    title=_("Invalid Field Pattern")
                )

        elif self.applies_to == "Field Groups":
            if not self.field_groups:
                frappe.throw(
                    _("Field Groups must be provided when 'Applies To' is set to 'Field Groups'"),
                    title=_("Missing Field Groups")
                )

    def validate_custom_method(self):
        """Validate custom method path format"""
        if self.rule_type == "Custom" and self.custom_method:
            if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_.]*$', self.custom_method):
                frappe.throw(
                    _("Custom Method must be a valid Python dotted path (e.g., module.submodule.function)"),
                    title=_("Invalid Custom Method Path")
                )

    def validate_default_rule(self):
        """Ensure only one default rule exists"""
        if self.is_default:
            existing_default = frappe.db.get_value(
                "Survivorship Rule",
                {"is_default": 1, "name": ["!=", self.name]},
                "name"
            )
            if existing_default:
                frappe.throw(
                    _("Another rule '{0}' is already set as default. Only one default rule is allowed.").format(existing_default),
                    title=_("Multiple Default Rules")
                )

    def on_update(self):
        """Handle post-update actions"""
        self.invalidate_cache()

    def on_trash(self):
        """Cleanup before deletion"""
        if self.is_default:
            frappe.throw(
                _("Cannot delete the default survivorship rule. Please set another rule as default first."),
                title=_("Cannot Delete Default Rule")
            )

        golden_record_count = frappe.db.count("Golden Record", {"survivorship_rule": self.name})
        if golden_record_count > 0:
            frappe.throw(
                _("Cannot delete survivorship rule '{0}' as it is referenced by {1} golden record(s). "
                  "Please update those records first.").format(
                    self.rule_name, golden_record_count
                ),
                title=_("Survivorship Rule In Use")
            )

    def invalidate_cache(self):
        """Clear relevant caches"""
        try:
            frappe.cache().delete_key(f"pim:survivorship_rule:{self.name}")
            frappe.cache().delete_key("pim:all_survivorship_rules")
            frappe.cache().delete_key("pim:default_survivorship_rule")
        except Exception:
            pass

    def get_specific_fields_list(self) -> List[str]:
        """Get list of specific field names"""
        if self.specific_fields:
            return [field.strip() for field in self.specific_fields.split(",")]
        return []

    def get_field_groups_list(self) -> List[str]:
        """Get list of field groups"""
        if self.field_groups:
            return [group.strip() for group in self.field_groups.split(",")]
        return []

    def applies_to_field(self, field_name: str, field_group: Optional[str] = None) -> bool:
        """Check if this rule applies to a specific field

        Args:
            field_name: Name of the field to check
            field_group: Optional attribute group the field belongs to
        """
        if self.applies_to == "All Fields":
            return True

        elif self.applies_to == "Specific Fields":
            return field_name in self.get_specific_fields_list()

        elif self.applies_to == "Field Pattern":
            try:
                return bool(re.match(self.field_pattern, field_name))
            except re.error:
                return False

        elif self.applies_to == "Field Groups":
            if not field_group:
                return False
            return field_group in self.get_field_groups_list()

        return False

    def apply_rule(self, field_values: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Apply this survivorship rule to select the winning value

        Args:
            field_values: List of dicts with 'value', 'source_system', 'timestamp', 'confidence'

        Returns:
            The winning value entry or None if no valid values
        """
        if not field_values:
            return None

        if len(field_values) == 1:
            return field_values[0]

        filtered_values = self._filter_values(field_values)
        if not filtered_values:
            return None

        if self.rule_type == "Source Priority":
            return self._apply_source_priority(filtered_values)
        elif self.rule_type == "Most Recent":
            return self._apply_most_recent(filtered_values)
        elif self.rule_type == "Highest Confidence":
            return self._apply_highest_confidence(filtered_values)
        elif self.rule_type == "Authoritative Source":
            return self._apply_authoritative_source(filtered_values)
        elif self.rule_type == "Most Complete":
            return self._apply_most_complete(filtered_values)
        elif self.rule_type == "Custom":
            return self._apply_custom(filtered_values)

        return filtered_values[0]

    def _filter_values(self, field_values: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter values based on rule settings"""
        result = field_values.copy()

        if self.prefer_non_empty:
            non_empty = [v for v in result if self._is_non_empty(v.get("value"))]
            if non_empty:
                result = non_empty

        if self.trim_whitespace:
            for v in result:
                if isinstance(v.get("value"), str):
                    v["value"] = v["value"].strip()

        return result

    def _is_non_empty(self, value: Any) -> bool:
        """Check if a value is non-empty"""
        if value is None:
            return False
        if isinstance(value, str) and not value.strip():
            return False
        if isinstance(value, (list, dict)) and len(value) == 0:
            return False
        return True

    def _apply_source_priority(self, field_values: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Apply source priority rule"""
        source_ranks = {}
        for item in self.source_priorities:
            source_ranks[item.source_system] = item.rank

        def get_rank(entry):
            return source_ranks.get(entry.get("source_system"), 999)

        sorted_values = sorted(field_values, key=get_rank)

        top_rank = get_rank(sorted_values[0])
        ties = [v for v in sorted_values if get_rank(v) == top_rank]

        if len(ties) > 1:
            return self._apply_tiebreaker(ties)

        return sorted_values[0]

    def _apply_most_recent(self, field_values: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Apply most recent rule"""
        sorted_values = sorted(
            field_values,
            key=lambda x: x.get("timestamp") or "",
            reverse=True
        )

        if len(sorted_values) > 1:
            top_ts = sorted_values[0].get("timestamp")
            ties = [v for v in sorted_values if v.get("timestamp") == top_ts]
            if len(ties) > 1:
                return self._apply_tiebreaker(ties)

        return sorted_values[0]

    def _apply_highest_confidence(self, field_values: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Apply highest confidence rule"""
        filtered = field_values
        if self.min_confidence_threshold and self.min_confidence_threshold > 0:
            filtered = [v for v in field_values if (v.get("confidence") or 0) >= self.min_confidence_threshold]
            if not filtered:
                filtered = field_values

        sorted_values = sorted(
            filtered,
            key=lambda x: x.get("confidence") or 0,
            reverse=True
        )

        if len(sorted_values) > 1:
            top_conf = sorted_values[0].get("confidence")
            ties = [v for v in sorted_values if v.get("confidence") == top_conf]
            if len(ties) > 1:
                return self._apply_tiebreaker(ties)

        return sorted_values[0]

    def _apply_authoritative_source(self, field_values: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Apply authoritative source rule"""
        for entry in field_values:
            if entry.get("source_system") == self.authoritative_source:
                if self._is_non_empty(entry.get("value")):
                    return entry

        if self.allow_fallback:
            if self.fallback_rule_type == "Source Priority":
                return self._apply_source_priority(field_values)
            elif self.fallback_rule_type == "Most Recent":
                return self._apply_most_recent(field_values)
            elif self.fallback_rule_type == "Highest Confidence":
                return self._apply_highest_confidence(field_values)

        return None

    def _apply_most_complete(self, field_values: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Apply most complete rule - select value with most data/length"""
        def get_completeness(entry):
            value = entry.get("value")
            if value is None:
                return 0
            if isinstance(value, str):
                return len(value)
            if isinstance(value, (list, dict)):
                return len(value)
            return 1

        sorted_values = sorted(field_values, key=get_completeness, reverse=True)

        if len(sorted_values) > 1:
            top_completeness = get_completeness(sorted_values[0])
            ties = [v for v in sorted_values if get_completeness(v) == top_completeness]
            if len(ties) > 1:
                return self._apply_tiebreaker(ties)

        return sorted_values[0]

    def _apply_custom(self, field_values: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Apply custom rule via specified method"""
        if not self.custom_method:
            return field_values[0]

        try:
            parts = self.custom_method.rsplit(".", 1)
            if len(parts) != 2:
                frappe.log_error(
                    f"Invalid custom method path: {self.custom_method}",
                    "Survivorship Rule Custom Method Error"
                )
                return field_values[0]

            module_path, method_name = parts
            module = frappe.get_module(module_path)
            method = getattr(module, method_name)

            params = frappe.parse_json(self.custom_params) if self.custom_params else {}
            return method(field_values, **params)

        except Exception as e:
            frappe.log_error(
                f"Error executing custom survivorship rule: {str(e)}",
                "Survivorship Rule Custom Method Error"
            )
            return field_values[0]

    def _apply_tiebreaker(self, tied_values: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Apply tie-breaker rule to tied values"""
        if not tied_values:
            return None

        if len(tied_values) == 1:
            return tied_values[0]

        if self.tiebreaker_rule == "Most Recent":
            sorted_values = sorted(
                tied_values,
                key=lambda x: x.get("timestamp") or "",
                reverse=True
            )
            return sorted_values[0]

        elif self.tiebreaker_rule == "First Encountered":
            return tied_values[0]

        elif self.tiebreaker_rule == "Longest Value":
            sorted_values = sorted(
                tied_values,
                key=lambda x: len(str(x.get("value") or "")),
                reverse=True
            )
            return sorted_values[0]

        elif self.tiebreaker_rule == "Shortest Value":
            sorted_values = sorted(
                tied_values,
                key=lambda x: len(str(x.get("value") or ""))
            )
            return sorted_values[0]

        elif self.tiebreaker_rule == "Alphabetical":
            sorted_values = sorted(
                tied_values,
                key=lambda x: str(x.get("value") or "").lower()
            )
            return sorted_values[0]

        return tied_values[0]

    def update_stats(self, fields_count: int = 1, candidates_count: int = 0):
        """Update usage statistics after applying rule"""
        updates = {
            "times_applied": (self.times_applied or 0) + 1,
            "fields_affected": (self.fields_affected or 0) + fields_count,
            "last_applied_at": frappe.utils.now_datetime()
        }

        if candidates_count > 0:
            current_avg = self.average_candidates or 0
            current_times = self.times_applied or 0
            new_avg = ((current_avg * current_times) + candidates_count) / (current_times + 1)
            updates["average_candidates"] = round(new_avg, 2)

        frappe.db.set_value("Survivorship Rule", self.name, updates, update_modified=False)


@frappe.whitelist()
def get_survivorship_rules(
    enabled_only: bool = True,
    rule_type: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Get all survivorship rules with optional filters

    Args:
        enabled_only: If True, return only enabled rules
        rule_type: Filter by rule type
    """
    filters = {}
    if enabled_only:
        filters["enabled"] = 1
    if rule_type:
        filters["rule_type"] = rule_type

    return frappe.get_all(
        "Survivorship Rule",
        filters=filters,
        fields=[
            "name", "rule_name", "rule_code", "rule_type",
            "applies_to", "enabled", "is_default",
            "times_applied", "last_applied_at"
        ],
        order_by="rule_name asc"
    )


@frappe.whitelist()
def get_default_rule() -> Optional[Dict[str, Any]]:
    """Get the default survivorship rule

    Returns:
        Default rule details or None
    """
    rule_name = frappe.db.get_value(
        "Survivorship Rule",
        {"is_default": 1, "enabled": 1},
        "name"
    )

    if rule_name:
        return frappe.get_doc("Survivorship Rule", rule_name).as_dict()

    return None


@frappe.whitelist()
def get_rule_for_field(
    field_name: str,
    field_group: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Get the most appropriate survivorship rule for a field

    Args:
        field_name: Name of the field
        field_group: Optional attribute group

    Returns:
        Matching rule or default rule
    """
    rules = frappe.get_all(
        "Survivorship Rule",
        filters={"enabled": 1},
        fields=["name", "applies_to", "specific_fields", "field_pattern", "field_groups", "is_default"],
        order_by="is_default asc"
    )

    for rule_data in rules:
        doc = frappe.get_doc("Survivorship Rule", rule_data.name)
        if doc.applies_to_field(field_name, field_group):
            if doc.applies_to != "All Fields":
                return doc.as_dict()

    for rule_data in rules:
        if rule_data.is_default:
            return frappe.get_doc("Survivorship Rule", rule_data.name).as_dict()

    return None


@frappe.whitelist()
def apply_survivorship_rule(
    rule_name: str,
    field_values: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Apply a specific survivorship rule to select the winning value

    Args:
        rule_name: Name of the Survivorship Rule document
        field_values: List of dicts with 'value', 'source_system', 'timestamp', 'confidence'

    Returns:
        The winning value entry or None
    """
    if isinstance(field_values, str):
        field_values = frappe.parse_json(field_values)

    doc = frappe.get_doc("Survivorship Rule", rule_name)
    result = doc.apply_rule(field_values)

    doc.update_stats(fields_count=1, candidates_count=len(field_values))

    return result


@frappe.whitelist()
def test_survivorship_rule(
    rule_name: str,
    test_values: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Test a survivorship rule with sample values without updating stats

    Args:
        rule_name: Name of the Survivorship Rule document
        test_values: List of test value entries

    Returns:
        Dict with result and explanation
    """
    if isinstance(test_values, str):
        test_values = frappe.parse_json(test_values)

    doc = frappe.get_doc("Survivorship Rule", rule_name)
    result = doc.apply_rule(test_values)

    return {
        "rule_name": doc.rule_name,
        "rule_type": doc.rule_type,
        "input_count": len(test_values),
        "winning_value": result,
        "explanation": _("Rule '{0}' selected value from source '{1}'").format(
            doc.rule_name,
            result.get("source_system") if result else "None"
        )
    }
