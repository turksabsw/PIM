"""
PIM Sync Conflict Rule Controller
Conflict resolution policies for bidirectional ERPNext sync
"""

import frappe
from frappe import _
from frappe.model.document import Document

# Defer frappe import to function level for module import without Frappe context
import re

class PIMSyncConflictRule(Document):

        def validate(self):
            self.validate_rule_code()
            self.validate_condition_fields()
            self.validate_notification_settings()

        def validate_rule_code(self):
            """Validate and auto-generate rule code if needed"""
            if not self.rule_code:
                # Generate from rule_name
                self.rule_code = self.generate_rule_code(self.rule_name)
            else:
                # Validate format - URL-safe slug
                if not re.match(r'^[a-z0-9][a-z0-9_-]*$', self.rule_code):
                    frappe.throw(
                        _("Rule Code must be URL-safe (lowercase letters, numbers, hyphens, underscores, "
                          "starting with letter or number): {0}").format(self.rule_code),
                        title=_("Invalid Rule Code")
                    )

        def generate_rule_code(self, name):
            """Generate URL-safe rule code from name"""
            if not name:
                return ""
            # Convert to lowercase, replace spaces and special chars with hyphens
            code = name.lower()
            code = re.sub(r'[^a-z0-9]+', '-', code)
            code = code.strip('-')
            return code

        def validate_condition_fields(self):
            """Validate condition-related fields"""
            if self.condition_type == "Field Value":
                if not self.condition_field:
                    frappe.throw(
                        _("Condition Field is required when Condition Type is 'Field Value'"),
                        title=_("Missing Condition Field")
                    )
                if not self.condition_operator:
                    frappe.throw(
                        _("Condition Operator is required when Condition Type is 'Field Value'"),
                        title=_("Missing Condition Operator")
                    )
                # Some operators don't need a value
                value_not_required = ["is set", "is not set"]
                if self.condition_operator not in value_not_required and not self.condition_value:
                    frappe.throw(
                        _("Condition Value is required for operator '{0}'").format(self.condition_operator),
                        title=_("Missing Condition Value")
                    )

            elif self.condition_type == "Time Based":
                if not self.time_window_hours or self.time_window_hours <= 0:
                    frappe.throw(
                        _("Time Window (Hours) must be a positive number when Condition Type is 'Time Based'"),
                        title=_("Invalid Time Window")
                    )

            elif self.condition_type == "Custom":
                if not self.custom_condition:
                    frappe.throw(
                        _("Custom Condition is required when Condition Type is 'Custom'"),
                        title=_("Missing Custom Condition")
                    )
                # Validate Python syntax
                try:
                    compile(self.custom_condition, '<string>', 'eval')
                except SyntaxError as e:
                    frappe.throw(
                        _("Custom Condition has invalid Python syntax: {0}").format(str(e)),
                        title=_("Invalid Custom Condition")
                    )

        def validate_notification_settings(self):
            """Validate notification settings"""
            if self.notify_on_conflict and not self.notification_recipients:
                frappe.throw(
                    _("Notification Recipients is required when 'Notify on Conflict' is enabled"),
                    title=_("Missing Notification Recipients")
                )

        def before_save(self):
            """Before save hook"""
            # Auto-generate rule_code if empty
            if not self.rule_code:
                self.rule_code = self.generate_rule_code(self.rule_name)

        def on_update(self):
            """After update - invalidate cache"""
            self.invalidate_cache()

        def on_trash(self):
            """Before delete - invalidate cache"""
            self.invalidate_cache()

        def invalidate_cache(self):
            """Invalidate related caches"""
            frappe.cache().delete_key("pim_sync_conflict_rules")
            frappe.cache().delete_key(f"pim_sync_conflict_rules_{self.doctype_name or 'all'}")

        def record_trigger(self):
            """Record that this rule was triggered"""
            self.db_set({
                "times_triggered": (self.times_triggered or 0) + 1,
                "last_triggered": now_datetime()
            })

        def evaluate_condition(self, doc=None, conflict_data=None, pim_value=None, erp_value=None):
            """Evaluate if this rule's condition is met

            Args:
                doc: The document being synced
                conflict_data: Dict with conflict details
                pim_value: Value from PIM
                erp_value: Value from ERP

            Returns:
                bool: True if condition is met
            """
            if not self.is_active:
                return False

            condition_type = self.condition_type or "Always"

            if condition_type == "Always":
                return True

            elif condition_type == "Field Value":
                return self._evaluate_field_condition(doc, pim_value, erp_value)

            elif condition_type == "Time Based":
                return self._evaluate_time_condition(conflict_data)

            elif condition_type == "Custom":
                return self._evaluate_custom_condition(doc, conflict_data, pim_value, erp_value)

            return False

        def _evaluate_field_condition(self, doc, pim_value, erp_value):
            """Evaluate field-based condition"""
            if not doc or not self.condition_field:
                return False

            field_value = doc.get(self.condition_field)
            compare_value = self.condition_value
            operator = self.condition_operator

            if operator == "=":
                return str(field_value) == str(compare_value)
            elif operator == "!=":
                return str(field_value) != str(compare_value)
            elif operator == ">":
                return float(field_value or 0) > float(compare_value or 0)
            elif operator == "<":
                return float(field_value or 0) < float(compare_value or 0)
            elif operator == ">=":
                return float(field_value or 0) >= float(compare_value or 0)
            elif operator == "<=":
                return float(field_value or 0) <= float(compare_value or 0)
            elif operator == "contains":
                return str(compare_value or "") in str(field_value or "")
            elif operator == "not contains":
                return str(compare_value or "") not in str(field_value or "")
            elif operator == "is set":
                return bool(field_value)
            elif operator == "is not set":
                return not bool(field_value)

            return False

        def _evaluate_time_condition(self, conflict_data):
            """Evaluate time-based condition"""
            if not conflict_data:
                return True

            from frappe.utils import time_diff_in_hours, now_datetime, get_datetime

            pim_modified = conflict_data.get("pim_modified")
            erp_modified = conflict_data.get("erp_modified")

            if not pim_modified or not erp_modified:
                return True

            # Check if both modifications are within the time window
            now = now_datetime()
            pim_diff = abs(time_diff_in_hours(now, get_datetime(pim_modified)))
            erp_diff = abs(time_diff_in_hours(now, get_datetime(erp_modified)))

            return pim_diff <= (self.time_window_hours or 24) and erp_diff <= (self.time_window_hours or 24)

        def _evaluate_custom_condition(self, doc, conflict_data, pim_value, erp_value):
            """Evaluate custom Python condition"""
            import frappe

            if not self.custom_condition:
                return False

            try:
                # Create evaluation context
                context = {
                    "doc": doc,
                    "conflict_data": conflict_data or {},
                    "pim_value": pim_value,
                    "erp_value": erp_value,
                    "frappe": frappe
                }

                result = frappe.safe_eval(self.custom_condition, context)
                return bool(result)
            except Exception:
                # Log but don't fail - treat as condition not met
                return False

        def get_resolution(self, conflict_data=None):
            """Get the resolution action based on this rule

            Args:
                conflict_data: Dict with pim_value, erp_value, pim_modified, erp_modified

            Returns:
                dict with 'winner' (pim/erp) and 'strategy' (overwrite/merge/skip/review)
            """
            priority_source = self.priority_source
            strategy = self.resolution_strategy or "Overwrite"

            if priority_source == "Latest":
                # Determine winner by modification timestamp
                winner = self._get_latest_winner(conflict_data)
            elif priority_source == "Manual":
                winner = None  # Will require manual review
                strategy = "Queue for Review"
            else:
                winner = priority_source.lower()  # "pim" or "erp"

            return {
                "winner": winner,
                "strategy": strategy,
                "rule_name": self.name,
                "rule_code": self.rule_code
            }

        def _get_latest_winner(self, conflict_data):
            """Determine winner based on latest modification"""
            if not conflict_data:
                return "pim"  # Default to PIM

            from frappe.utils import get_datetime

            pim_modified = conflict_data.get("pim_modified")
            erp_modified = conflict_data.get("erp_modified")

            if not pim_modified:
                return "erp"
            if not erp_modified:
                return "pim"

            pim_dt = get_datetime(pim_modified)
            erp_dt = get_datetime(erp_modified)

            return "pim" if pim_dt >= erp_dt else "erp"
# Module-level helper functions

def get_active_rules(doctype_name=None, field_name=None, sync_direction=None):
    """Get active conflict resolution rules

    Args:
        doctype_name: Optional filter by DocType
        field_name: Optional filter by field name
        sync_direction: Optional filter by sync direction

    Returns:
        List of PIM Sync Conflict Rule documents
    """
    import frappe

    filters = {"is_active": 1}

    if doctype_name:
        filters["doctype_name"] = ["in", [doctype_name, None, ""]]
    if field_name:
        filters["field_name"] = ["in", [field_name, None, ""]]
    if sync_direction:
        filters["sync_direction"] = ["in", [sync_direction, "Bidirectional", None, ""]]

    rules = frappe.get_all(
        "PIM Sync Conflict Rule",
        filters=filters,
        fields=["name"],
        order_by="priority desc, creation asc"
    )

    return [frappe.get_doc("PIM Sync Conflict Rule", r.name) for r in rules]

def get_rule_by_code(rule_code):
    """Get conflict rule by its code

    Args:
        rule_code: The rule code

    Returns:
        PIM Sync Conflict Rule document or None
    """
    import frappe

    if not rule_code:
        return None

    rule_name = frappe.db.get_value(
        "PIM Sync Conflict Rule",
        {"rule_code": rule_code, "is_active": 1},
        "name"
    )

    if rule_name:
        return frappe.get_doc("PIM Sync Conflict Rule", rule_name)

    return None

def resolve_conflict(doctype_name, field_name, pim_value, erp_value,
                     sync_direction="PIM to ERP", doc=None, conflict_data=None):
    """Resolve a sync conflict using configured rules

    Args:
        doctype_name: DocType being synced
        field_name: Field with conflict
        pim_value: Value from PIM
        erp_value: Value from ERP
        sync_direction: Direction of sync
        doc: The document being synced
        conflict_data: Additional conflict details

    Returns:
        dict with resolution details:
        - winner: 'pim', 'erp', or None (manual)
        - value: The winning value
        - strategy: Resolution strategy
        - rule_name: Name of rule that was applied
    """
    import frappe

    # Get applicable rules
    rules = get_active_rules(
        doctype_name=doctype_name,
        field_name=field_name,
        sync_direction=sync_direction
    )

    if not rules:
        # Default: PIM wins
        return {
            "winner": "pim",
            "value": pim_value,
            "strategy": "Overwrite",
            "rule_name": None
        }

    # Prepare conflict data
    if not conflict_data:
        conflict_data = {}

    conflict_data.update({
        "pim_value": pim_value,
        "erp_value": erp_value,
        "doctype_name": doctype_name,
        "field_name": field_name
    })

    # Evaluate rules in priority order
    for rule in rules:
        if rule.evaluate_condition(doc, conflict_data, pim_value, erp_value):
            resolution = rule.get_resolution(conflict_data)

            # Determine the winning value
            if resolution["winner"] == "pim":
                resolution["value"] = pim_value
            elif resolution["winner"] == "erp":
                resolution["value"] = erp_value
            else:
                resolution["value"] = None  # Manual review needed

            # Record that this rule was triggered
            rule.record_trigger()

            # Send notification if configured
            if rule.notify_on_conflict:
                _send_conflict_notification(rule, conflict_data)

            return resolution

    # No matching rule found - default to PIM wins
    return {
        "winner": "pim",
        "value": pim_value,
        "strategy": "Overwrite",
        "rule_name": None
    }

def _send_conflict_notification(rule, conflict_data):
    """Send notification for conflict resolution

    Args:
        rule: The PIM Sync Conflict Rule document
        conflict_data: Dict with conflict details
    """
    import frappe
    from frappe import _

    if not rule.notification_recipients:
        return

    recipients = [r.strip() for r in rule.notification_recipients.split(",") if r.strip()]

    if not recipients:
        return

    subject = _("Sync Conflict Resolved: {0}").format(rule.rule_name)

    message = _("""
<p>A sync conflict was automatically resolved using rule: <b>{rule_name}</b></p>

<table>
<tr><td><b>DocType:</b></td><td>{doctype_name}</td></tr>
<tr><td><b>Field:</b></td><td>{field_name}</td></tr>
<tr><td><b>PIM Value:</b></td><td>{pim_value}</td></tr>
<tr><td><b>ERP Value:</b></td><td>{erp_value}</td></tr>
<tr><td><b>Winner:</b></td><td>{priority_source}</td></tr>
</table>
""").format(
        rule_name=rule.rule_name,
        doctype_name=conflict_data.get("doctype_name", ""),
        field_name=conflict_data.get("field_name", ""),
        pim_value=conflict_data.get("pim_value", ""),
        erp_value=conflict_data.get("erp_value", ""),
        priority_source=rule.priority_source
    )

    try:
        frappe.sendmail(
            recipients=recipients,
            subject=subject,
            message=message,
            delayed=True
        )
    except Exception:
        # Don't fail sync because notification failed
        frappe.log_error(
            title="Conflict Notification Failed",
            message=f"Failed to send notification for rule {rule.name}"
        )

def get_default_rules():
    """Get a list of default conflict resolution rules

    Returns:
        List of dicts with default rule configurations
    """
    return [
        {
            "rule_name": "PIM Master for Descriptions",
            "rule_code": "pim-master-descriptions",
            "doctype_name": "",
            "field_name": "description",
            "priority_source": "PIM",
            "resolution_strategy": "Overwrite",
            "priority": 10,
            "is_active": 1,
            "description": "PIM always wins for description fields as it is the master for product content"
        },
        {
            "rule_name": "ERP Master for Stock Data",
            "rule_code": "erp-master-stock",
            "doctype_name": "Product Variant",
            "field_name": "",
            "priority_source": "ERP",
            "resolution_strategy": "Overwrite",
            "condition_type": "Field Value",
            "condition_field": "field_name",
            "condition_operator": "contains",
            "condition_value": "stock",
            "priority": 20,
            "is_active": 1,
            "description": "ERP always wins for stock-related fields"
        },
        {
            "rule_name": "Latest Wins for Pricing",
            "rule_code": "latest-wins-pricing",
            "doctype_name": "",
            "field_name": "",
            "priority_source": "Latest",
            "resolution_strategy": "Overwrite",
            "condition_type": "Field Value",
            "condition_field": "field_name",
            "condition_operator": "contains",
            "condition_value": "price",
            "priority": 15,
            "is_active": 1,
            "description": "Most recent update wins for pricing fields"
        },
        {
            "rule_name": "Default PIM Priority",
            "rule_code": "default-pim-priority",
            "doctype_name": "",
            "field_name": "",
            "priority_source": "PIM",
            "resolution_strategy": "Overwrite",
            "priority": 0,
            "is_active": 1,
            "description": "Default fallback: PIM wins for all unmatched conflicts"
        }
    ]

def create_default_rules():
    """Create default conflict resolution rules if they don't exist

    Returns:
        List of created rule names
    """
    import frappe

    created = []
    for rule_data in get_default_rules():
        if not frappe.db.exists("PIM Sync Conflict Rule", {"rule_code": rule_data["rule_code"]}):
            doc = frappe.new_doc("PIM Sync Conflict Rule")
            doc.update(rule_data)
            doc.insert(ignore_permissions=True)
            created.append(doc.name)

    if created:
        frappe.db.commit()

    return created

def get_conflict_stats():
    """Get statistics about conflict resolution

    Returns:
        dict with conflict statistics
    """
    import frappe

    stats = {
        "total_rules": 0,
        "active_rules": 0,
        "total_triggers": 0,
        "rules_by_source": {}
    }

    # Count rules
    stats["total_rules"] = frappe.db.count("PIM Sync Conflict Rule")
    stats["active_rules"] = frappe.db.count("PIM Sync Conflict Rule", {"is_active": 1})

    # Total triggers
    total_triggers = frappe.db.sql("""
        SELECT COALESCE(SUM(times_triggered), 0) as total
        FROM `tabPIM Sync Conflict Rule`
    """)
    stats["total_triggers"] = int(total_triggers[0][0]) if total_triggers else 0

    # Rules by priority source
    source_counts = frappe.db.sql("""
        SELECT priority_source, COUNT(*) as count
        FROM `tabPIM Sync Conflict Rule`
        WHERE is_active = 1
        GROUP BY priority_source
    """, as_dict=True)

    stats["rules_by_source"] = {r.priority_source: r["count"] for r in source_counts}

    return stats
