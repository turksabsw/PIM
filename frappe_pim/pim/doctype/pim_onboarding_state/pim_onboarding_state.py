"""
PIM Onboarding State Controller
Implements a state machine for the SaaS onboarding wizard.

Steps (12 total):
  pending → company_info → industry_selection → product_structure →
  channel_setup → workflow_preferences → compliance_setup →
  template_applied → customization_review → first_data →
  guided_tour → completed
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime
from typing import Dict, List, Optional, Any
import json


# Ordered list of onboarding steps forming the state machine
ONBOARDING_STEPS = (
    "pending",
    "company_info",
    "industry_selection",
    "product_structure",
    "channel_setup",
    "workflow_preferences",
    "compliance_setup",
    "template_applied",
    "customization_review",
    "first_data",
    "guided_tour",
    "completed",
)

# Steps that collect user form data (maps step name → JSON field)
STEP_DATA_FIELDS = {
    "company_info": "company_info_data",
    "industry_selection": "industry_selection_data",
    "product_structure": "product_structure_data",
    "channel_setup": "channel_setup_data",
    "workflow_preferences": "workflow_preferences_data",
    "compliance_setup": "compliance_setup_data",
    "customization_review": "customization_review_data",
    "first_data": "first_data_data",
    "guided_tour": "guided_tour_data",
}

# Total number of actionable steps (excluding pending and completed)
TOTAL_ACTIONABLE_STEPS = len(ONBOARDING_STEPS) - 2


class PIMOnboardingState(Document):

    def _validate_links(self):
        """Skip User link validation — user email is validated by validate_user().

        The User DocType may not have an entry for every tenant user (e.g.,
        test users or SaaS users authenticated via an external provider).
        """
        self.flags.ignore_links = True
        super()._validate_links()

    def validate(self):
        self.validate_step()
        self.validate_user()
        self.update_progress()

    def validate_step(self):
        """Ensure current_step is a valid step in the state machine."""
        if self.current_step not in ONBOARDING_STEPS:
            frappe.throw(
                _("Invalid onboarding step: {0}. Valid steps are: {1}").format(
                    self.current_step, ", ".join(ONBOARDING_STEPS)
                ),
                title=_("Invalid Step")
            )

    def validate_user(self):
        """Ensure user field is set and valid."""
        if not self.user:
            frappe.throw(
                _("User is required for onboarding state"),
                title=_("Missing User")
            )

    def update_progress(self):
        """Calculate and update progress percentage based on current step."""
        if self.current_step == "pending":
            self.progress_percent = 0
        elif self.current_step == "completed":
            self.progress_percent = 100
        else:
            step_index = ONBOARDING_STEPS.index(self.current_step)
            # pending=0, completed=last; progress counts steps entered (1-based)
            self.progress_percent = round(
                (step_index / TOTAL_ACTIONABLE_STEPS) * 100, 1
            )

    def before_save(self):
        """Set timestamps and completion flags."""
        if self.current_step != "pending" and not self.started_at:
            self.started_at = now_datetime()

        if self.current_step == "completed" and not self.completed_at:
            self.completed_at = now_datetime()
            self.is_completed = 1

    def on_update(self):
        """Post-save hooks."""
        self._invalidate_cache()

    def advance_step(self, form_data: Optional[Dict] = None) -> str:
        """Advance to the next step in the onboarding state machine.

        Saves form data for the current step (if provided), marks the current
        step as completed, and moves to the next step.

        Args:
            form_data: Optional dict of form data collected during the current step

        Returns:
            The new current step name

        Raises:
            frappe.ValidationError: If already at the last step or step is invalid
        """
        if self.current_step == "completed":
            frappe.throw(
                _("Onboarding is already completed"),
                title=_("Already Completed")
            )

        if self.is_skipped:
            frappe.throw(
                _("Onboarding was skipped and cannot be advanced"),
                title=_("Onboarding Skipped")
            )

        # Save form data for current step
        if form_data and self.current_step in STEP_DATA_FIELDS:
            self._save_step_data(self.current_step, form_data)

        # Mark current step as completed
        self._mark_step_completed(self.current_step)

        # Advance to next step
        current_index = ONBOARDING_STEPS.index(self.current_step)
        next_step = ONBOARDING_STEPS[current_index + 1]
        self.current_step = next_step
        self.last_step_completed_at = now_datetime()

        self.save(ignore_permissions=True)

        return next_step

    def go_to_step(self, step: str) -> str:
        """Navigate to a specific step (allows going back).

        Only allows navigating to previously completed steps or
        the current step. Cannot skip ahead.

        Args:
            step: The step name to navigate to

        Returns:
            The new current step name

        Raises:
            frappe.ValidationError: If the step is invalid or ahead of current
        """
        if step not in ONBOARDING_STEPS:
            frappe.throw(
                _("Invalid step: {0}").format(step),
                title=_("Invalid Step")
            )

        if self.is_completed and step != "completed":
            frappe.throw(
                _("Onboarding is already completed. Cannot navigate to step: {0}").format(step),
                title=_("Already Completed")
            )

        target_index = ONBOARDING_STEPS.index(step)
        current_index = ONBOARDING_STEPS.index(self.current_step)

        # Allow going back to completed steps or staying on current
        if target_index > current_index:
            frappe.throw(
                _("Cannot skip ahead to step '{0}'. Complete the current step first.").format(step),
                title=_("Cannot Skip Steps")
            )

        self.current_step = step
        self.save(ignore_permissions=True)

        return step

    def save_step_data(self, step: str, form_data: Dict) -> None:
        """Save form data for a specific step without advancing.

        Allows partial saves / drafts during a step.

        Args:
            step: The step name to save data for
            form_data: Dict of form data to save

        Raises:
            frappe.ValidationError: If step doesn't accept form data
        """
        if step not in STEP_DATA_FIELDS:
            frappe.throw(
                _("Step '{0}' does not accept form data").format(step),
                title=_("Invalid Step for Data")
            )

        self._save_step_data(step, form_data)
        self.save(ignore_permissions=True)

    def skip_onboarding(self) -> None:
        """Mark onboarding as skipped.

        The user can choose to skip the wizard entirely and
        configure PIM manually.
        """
        if self.is_completed:
            frappe.throw(
                _("Onboarding is already completed and cannot be skipped"),
                title=_("Already Completed")
            )

        self.is_skipped = 1
        self.current_step = "completed"
        self.completed_at = now_datetime()
        self.is_completed = 1
        self.save(ignore_permissions=True)

    def reset_onboarding(self) -> None:
        """Reset onboarding to initial state.

        Clears all step data and resets to 'pending'.
        Only System Manager can perform this.
        """
        if not frappe.has_permission("PIM Onboarding State", "write", user=frappe.session.user):
            frappe.throw(_("Not permitted"), frappe.PermissionError)

        self.current_step = "pending"
        self.is_completed = 0
        self.is_skipped = 0
        self.started_at = None
        self.completed_at = None
        self.selected_archetype = None
        self.template_applied = 0
        self.template_applied_at = None
        self.template_result = None
        self.steps_completed = None
        self.progress_percent = 0
        self.last_step_completed_at = None
        self.error_log = None

        # Clear all step data fields
        for field in STEP_DATA_FIELDS.values():
            self.set(field, None)

        self.save(ignore_permissions=True)

    def mark_template_applied(self, archetype: str, result: Dict) -> None:
        """Mark that an industry archetype template has been applied.

        Called by the template engine after successful application.

        Args:
            archetype: Name of the archetype that was applied
            result: Summary dict of entities created
        """
        self.selected_archetype = archetype
        self.template_applied = 1
        self.template_applied_at = now_datetime()
        self.template_result = json.dumps(result, indent=2, default=str)
        self.save(ignore_permissions=True)

    def get_step_data(self, step: str) -> Optional[Dict]:
        """Retrieve stored form data for a specific step.

        Args:
            step: The step name to get data for

        Returns:
            Dict of form data, or None if no data stored
        """
        if step not in STEP_DATA_FIELDS:
            return None

        field = STEP_DATA_FIELDS[step]
        raw = self.get(field)

        if not raw:
            return None

        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return None

        return raw

    def get_all_step_data(self) -> Dict[str, Any]:
        """Retrieve form data for all steps.

        Returns:
            Dict mapping step names to their form data
        """
        result = {}
        for step, field in STEP_DATA_FIELDS.items():
            data = self.get_step_data(step)
            if data:
                result[step] = data
        return result

    def get_completed_steps(self) -> List[str]:
        """Get list of completed step names.

        Returns:
            List of step name strings that have been completed
        """
        raw = self.steps_completed
        if not raw:
            return []

        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return []

        return raw if isinstance(raw, list) else []

    def get_next_step(self) -> Optional[str]:
        """Get the next step after the current one.

        Returns:
            Next step name, or None if at the last step
        """
        if self.current_step == "completed":
            return None

        current_index = ONBOARDING_STEPS.index(self.current_step)
        if current_index < len(ONBOARDING_STEPS) - 1:
            return ONBOARDING_STEPS[current_index + 1]

        return None

    def get_previous_step(self) -> Optional[str]:
        """Get the previous step before the current one.

        Returns:
            Previous step name, or None if at the first step
        """
        if self.current_step == "pending":
            return None

        current_index = ONBOARDING_STEPS.index(self.current_step)
        if current_index > 0:
            return ONBOARDING_STEPS[current_index - 1]

        return None

    def get_status_summary(self) -> Dict:
        """Get a summary of the onboarding state for API responses.

        Returns:
            Dict with current state, progress, and step details
        """
        completed_steps = self.get_completed_steps()

        return {
            "user": self.user,
            "current_step": self.current_step,
            "is_completed": bool(self.is_completed),
            "is_skipped": bool(self.is_skipped),
            "progress_percent": self.progress_percent or 0,
            "selected_archetype": self.selected_archetype,
            "template_applied": bool(self.template_applied),
            "started_at": str(self.started_at) if self.started_at else None,
            "completed_at": str(self.completed_at) if self.completed_at else None,
            "completed_steps": completed_steps,
            "next_step": self.get_next_step(),
            "previous_step": self.get_previous_step(),
            "total_steps": len(ONBOARDING_STEPS),
            "steps": [
                {
                    "name": step,
                    "index": idx,
                    "is_completed": step in completed_steps,
                    "is_current": step == self.current_step,
                    "has_data": step in STEP_DATA_FIELDS and bool(self.get(STEP_DATA_FIELDS[step])),
                }
                for idx, step in enumerate(ONBOARDING_STEPS)
            ],
        }

    def log_error(self, step: str, error_message: str) -> None:
        """Log an error that occurred during a step.

        Args:
            step: The step where the error occurred
            error_message: Description of the error
        """
        errors = []
        if self.error_log:
            try:
                errors = json.loads(self.error_log) if isinstance(self.error_log, str) else self.error_log
            except (json.JSONDecodeError, TypeError):
                errors = []

        errors.append({
            "step": step,
            "error": error_message,
            "timestamp": str(now_datetime()),
        })

        self.error_log = json.dumps(errors, indent=2, default=str)
        self.save(ignore_permissions=True)

    # --- Private helpers ---

    def _save_step_data(self, step: str, form_data: Dict) -> None:
        """Internal helper to save form data for a step.

        Args:
            step: The step name
            form_data: Dict of form data
        """
        field = STEP_DATA_FIELDS.get(step)
        if not field:
            return

        self.set(field, json.dumps(form_data, indent=2, default=str))

    def _mark_step_completed(self, step: str) -> None:
        """Internal helper to add a step to the completed list.

        Args:
            step: The step name to mark as completed
        """
        completed = self.get_completed_steps()
        if step not in completed:
            completed.append(step)
            self.steps_completed = json.dumps(completed)

    def _invalidate_cache(self):
        """Invalidate onboarding-related caches."""
        try:
            from frappe_pim.pim.utils.cache import invalidate_cache
            invalidate_cache("onboarding_state", self.name)
        except (ImportError, AttributeError):
            pass


@frappe.whitelist()
def get_or_create_onboarding_state(user: Optional[str] = None) -> Dict:
    """Get the onboarding state for a user, creating one if it doesn't exist.

    Args:
        user: User email. Defaults to current session user.

    Returns:
        Dict with the onboarding state summary
    """
    if not user:
        user = frappe.session.user

    if not frappe.has_permission("PIM Onboarding State", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    existing = frappe.db.exists("PIM Onboarding State", {"user": user})

    if existing:
        doc = frappe.get_doc("PIM Onboarding State", existing)
    else:
        doc = frappe.new_doc("PIM Onboarding State")
        doc.user = user
        doc.current_step = "pending"
        doc.flags.ignore_links = True
        doc.insert(ignore_permissions=True)
        frappe.db.commit()

    return doc.get_status_summary()


@frappe.whitelist()
def advance_onboarding_step(user: Optional[str] = None, form_data: Optional[str] = None) -> Dict:
    """Advance the onboarding wizard to the next step.

    Args:
        user: User email. Defaults to current session user.
        form_data: JSON string of form data for the current step.

    Returns:
        Dict with the updated onboarding state summary
    """
    if not user:
        user = frappe.session.user

    existing = frappe.db.exists("PIM Onboarding State", {"user": user})
    if not existing:
        frappe.throw(
            _("No onboarding state found for user {0}").format(user),
            title=_("Not Found")
        )

    doc = frappe.get_doc("PIM Onboarding State", existing)

    parsed_data = None
    if form_data:
        if isinstance(form_data, str):
            try:
                parsed_data = json.loads(form_data)
            except (json.JSONDecodeError, TypeError):
                frappe.throw(_("Invalid form_data JSON"), title=_("Invalid Data"))
        else:
            parsed_data = form_data

    doc.advance_step(form_data=parsed_data)

    return doc.get_status_summary()


@frappe.whitelist()
def save_onboarding_step_data(
    step: str,
    form_data: str,
    user: Optional[str] = None,
) -> Dict:
    """Save form data for a specific onboarding step without advancing.

    Args:
        step: The step name to save data for
        form_data: JSON string of form data
        user: User email. Defaults to current session user.

    Returns:
        Dict with the updated onboarding state summary
    """
    if not user:
        user = frappe.session.user

    existing = frappe.db.exists("PIM Onboarding State", {"user": user})
    if not existing:
        frappe.throw(
            _("No onboarding state found for user {0}").format(user),
            title=_("Not Found")
        )

    doc = frappe.get_doc("PIM Onboarding State", existing)

    parsed_data = json.loads(form_data) if isinstance(form_data, str) else form_data
    doc.save_step_data(step, parsed_data)

    return doc.get_status_summary()


@frappe.whitelist()
def skip_onboarding(user: Optional[str] = None) -> Dict:
    """Skip the onboarding wizard entirely.

    Args:
        user: User email. Defaults to current session user.

    Returns:
        Dict with the updated onboarding state summary
    """
    if not user:
        user = frappe.session.user

    existing = frappe.db.exists("PIM Onboarding State", {"user": user})
    if not existing:
        frappe.throw(
            _("No onboarding state found for user {0}").format(user),
            title=_("Not Found")
        )

    doc = frappe.get_doc("PIM Onboarding State", existing)
    doc.skip_onboarding()

    return doc.get_status_summary()


@frappe.whitelist()
def get_onboarding_steps() -> List[Dict]:
    """Get the list of onboarding steps with metadata.

    Returns:
        List of dicts with step name, index, and data field info
    """
    return [
        {
            "name": step,
            "index": idx,
            "has_data_field": step in STEP_DATA_FIELDS,
            "data_field": STEP_DATA_FIELDS.get(step),
        }
        for idx, step in enumerate(ONBOARDING_STEPS)
    ]
