"""
Onboarding Step Log Controller
Per-step audit trail for the SaaS onboarding wizard.

Each log entry records a single user action (completed, skipped, saved)
on a specific wizard step, along with a snapshot of form data submitted
and timing information for analytics.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime
from typing import Dict, List, Optional, Any
import json


# Valid step identifiers matching the 12-step onboarding wizard
VALID_STEP_IDS = (
    "company_info",         # Step 1
    "industry_selection",   # Step 2
    "product_structure",    # Step 3
    "attribute_config",     # Step 4
    "taxonomy",             # Step 5
    "channel_setup",        # Step 6
    "localization",         # Step 7
    "workflow_preferences", # Step 8
    "quality_scoring",      # Step 9
    "integrations",         # Step 10
    "compliance",           # Step 11
    "summary_launch",       # Step 12
)

# Valid actions that can be logged
VALID_ACTIONS = ("completed", "skipped", "saved")

# Min/max step numbers
MIN_STEP_NUMBER = 1
MAX_STEP_NUMBER = 12


class OnboardingStepLog(Document):

    def validate(self):
        self.validate_step_id()
        self.validate_step_number()
        self.validate_action()
        self.validate_json_fields()
        self.set_timestamps()

    def validate_step_id(self):
        """Ensure step_id is a valid onboarding step identifier."""
        if self.step_id and self.step_id not in VALID_STEP_IDS:
            frappe.throw(
                _("Invalid step identifier: {0}. Valid steps are: {1}").format(
                    self.step_id, ", ".join(VALID_STEP_IDS)
                ),
                title=_("Invalid Step ID")
            )

    def validate_step_number(self):
        """Ensure step_number is within the valid range (1-12)."""
        if self.step_number is not None:
            if self.step_number < MIN_STEP_NUMBER or self.step_number > MAX_STEP_NUMBER:
                frappe.throw(
                    _("Step number must be between {0} and {1}, got: {2}").format(
                        MIN_STEP_NUMBER, MAX_STEP_NUMBER, self.step_number
                    ),
                    title=_("Invalid Step Number")
                )

    def validate_action(self):
        """Ensure action is a valid action type."""
        if self.action and self.action not in VALID_ACTIONS:
            frappe.throw(
                _("Invalid action: {0}. Valid actions are: {1}").format(
                    self.action, ", ".join(VALID_ACTIONS)
                ),
                title=_("Invalid Action")
            )

    def validate_json_fields(self):
        """Ensure JSON fields contain valid JSON if provided."""
        for fieldname in ("form_data", "validation_errors"):
            value = self.get(fieldname)
            if value and isinstance(value, str):
                try:
                    json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    frappe.throw(
                        _("Field '{0}' must contain valid JSON").format(fieldname),
                        title=_("Invalid JSON")
                    )

    def set_timestamps(self):
        """Auto-set completed_at timestamp when action is recorded."""
        if not self.completed_at and self.action in ("completed", "skipped"):
            self.completed_at = now_datetime()

    def calculate_time_spent(self):
        """Calculate time_spent_seconds from started_at and completed_at.

        Only calculates if both timestamps are present and time_spent_seconds
        is not already set.
        """
        if self.started_at and self.completed_at and not self.time_spent_seconds:
            from frappe.utils import time_diff_in_seconds
            diff = time_diff_in_seconds(self.completed_at, self.started_at)
            if diff > 0:
                self.time_spent_seconds = int(diff)

    def before_save(self):
        """Pre-save hook to calculate derived fields."""
        self.calculate_time_spent()


@frappe.whitelist()
def create_step_log(
    step_id: str,
    step_number: int,
    action: str,
    form_data: Optional[str] = None,
    started_at: Optional[str] = None,
    time_spent_seconds: Optional[int] = None,
    validation_errors: Optional[str] = None,
) -> Dict:
    """Create an onboarding step log entry.

    Args:
        step_id: Step identifier (e.g., "company_info")
        step_number: Step number (1-12)
        action: Action performed (completed, skipped, saved)
        form_data: JSON string of form data snapshot
        started_at: Datetime when the step was started
        time_spent_seconds: Time spent on the step in seconds
        validation_errors: JSON string of validation errors

    Returns:
        Dict with the created log entry details
    """
    # Always use session user for audit integrity — never accept user parameter
    user = frappe.session.user

    doc = frappe.new_doc("Onboarding Step Log")
    doc.user = user
    doc.step_id = step_id
    doc.step_number = int(step_number)
    doc.action = action

    if form_data:
        doc.form_data = form_data if isinstance(form_data, str) else json.dumps(form_data, default=str)

    if started_at:
        doc.started_at = started_at

    if time_spent_seconds is not None:
        doc.time_spent_seconds = int(time_spent_seconds)

    if validation_errors:
        doc.validation_errors = (
            validation_errors if isinstance(validation_errors, str)
            else json.dumps(validation_errors, default=str)
        )

    doc.insert(ignore_permissions=True)
    frappe.db.commit()

    return {
        "name": doc.name,
        "user": doc.user,
        "step_id": doc.step_id,
        "step_number": doc.step_number,
        "action": doc.action,
        "started_at": str(doc.started_at) if doc.started_at else None,
        "completed_at": str(doc.completed_at) if doc.completed_at else None,
        "time_spent_seconds": doc.time_spent_seconds,
    }


@frappe.whitelist()
def get_step_logs(
    user: Optional[str] = None,
    step_id: Optional[str] = None,
) -> List[Dict]:
    """Get onboarding step logs for a user, optionally filtered by step.

    Args:
        user: User email. Defaults to current session user.
        step_id: Optional step identifier to filter by.

    Returns:
        List of step log entry dicts
    """
    if not user:
        user = frappe.session.user

    # Restrict cross-user access to System Manager and PIM Manager roles
    if user and user != frappe.session.user:
        frappe.only_for(["System Manager", "PIM Manager"])

    filters = {"user": user}
    if step_id:
        filters["step_id"] = step_id

    logs = frappe.get_all(
        "Onboarding Step Log",
        filters=filters,
        fields=[
            "name", "user", "step_id", "step_number", "action",
            "started_at", "completed_at", "time_spent_seconds",
            "creation",
        ],
        order_by="creation desc",
    )

    return logs
