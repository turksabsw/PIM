"""PIM Onboarding API Endpoints

This module provides API endpoints for the SaaS onboarding wizard.
All functions support both synchronous use and whitelisted API access.

Legacy Endpoints (backward compatible, use PIM Onboarding State only):
- start_onboarding: Start/resume onboarding for the current user
- get_onboarding_state: Get current onboarding state and progress
- save_step_data: Save form data for a specific step (partial save)
- apply_archetype_template: Apply an industry archetype template
- complete_onboarding: Advance through steps or complete onboarding
- get_available_archetypes: List available industry archetype templates
- skip_onboarding: Skip the onboarding wizard entirely
- reset_onboarding: Reset onboarding to initial state
- preview_archetype: Preview what an archetype template will create

New Endpoints (use Tenant Config + OnboardingService pattern):
- get_onboarding_status: Get combined status from Tenant Config + state
- save_step: Save step data with dual-write to Tenant Config
- skip_step: Skip individual steps (9-11) after step 8
- get_template_preview: Preview industry template from Industry Template DocType
- apply_template: Apply template using Tenant Config sector selection
- v2_complete_onboarding: Complete onboarding with Tenant Config update
- update_post_onboarding: Edit configuration after onboarding completion

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

import frappe


@frappe.whitelist()
def start_onboarding(user=None):
    """Start or resume onboarding for a user.

    Creates a new PIM Onboarding State document if one doesn't exist
    for the specified user, or returns the existing state.

    Args:
        user: User email. Defaults to current session user.

    Returns:
        dict: Onboarding state summary
            - user: User email
            - current_step: Current step in the wizard
            - is_completed: Whether onboarding is finished
            - is_skipped: Whether onboarding was skipped
            - progress_percent: Completion percentage (0-100)
            - selected_archetype: Chosen industry archetype (if any)
            - template_applied: Whether a template has been applied
            - started_at: When onboarding began
            - completed_at: When onboarding finished
            - completed_steps: List of completed step names
            - next_step: Next step to complete
            - previous_step: Previous step (for back navigation)
            - total_steps: Total number of steps
            - steps: Detailed step list with status

    Example:
        >>> state = start_onboarding()
        >>> print(f"Current step: {state['current_step']}")
    """
    import frappe
    from frappe import _

    if not user:
        user = frappe.session.user

    # Permission check
    if not frappe.has_permission("PIM Onboarding State", "read"):
        frappe.throw(_("Not permitted to access onboarding"), frappe.PermissionError)

    # Find existing state for this user
    existing = frappe.db.exists("PIM Onboarding State", {"user": user})

    if existing:
        doc = frappe.get_doc("PIM Onboarding State", existing)
    else:
        # Create a new onboarding state
        doc = frappe.new_doc("PIM Onboarding State")
        doc.user = user
        doc.current_step = "pending"
        doc.flags.ignore_links = True
        doc.insert(ignore_permissions=True)
        frappe.db.commit()

    # If still at pending, advance to company_info to start
    try:
        if doc.current_step == "pending":
            doc.advance_step()
        return doc.get_status_summary()
    except frappe.ValidationError as e:
        return {
            "user": user,
            "current_step": doc.current_step,
            "is_completed": False,
            "is_skipped": False,
            "progress_percent": 0,
            "error": str(e),
        }


@frappe.whitelist()
def get_onboarding_state(user=None):
    """Get the current onboarding state for a user.

    Returns the full onboarding state including progress, step data,
    and template application status.

    Args:
        user: User email. Defaults to current session user.

    Returns:
        dict: Onboarding state summary with all step details.
            Returns a 'not_started' state if no onboarding exists.

    Example:
        >>> state = get_onboarding_state()
        >>> if state['is_completed']:
        ...     print("Onboarding complete!")
        >>> else:
        ...     print(f"Progress: {state['progress_percent']}%")
    """
    import frappe
    from frappe import _

    if not user:
        user = frappe.session.user

    if not frappe.has_permission("PIM Onboarding State", "read"):
        frappe.throw(_("Not permitted to access onboarding"), frappe.PermissionError)

    existing = frappe.db.exists("PIM Onboarding State", {"user": user})

    if not existing:
        return {
            "user": user,
            "current_step": "not_started",
            "is_completed": False,
            "is_skipped": False,
            "progress_percent": 0,
            "selected_archetype": None,
            "template_applied": False,
            "started_at": None,
            "completed_at": None,
            "completed_steps": [],
            "next_step": None,
            "previous_step": None,
            "total_steps": 12,
            "steps": [],
        }

    doc = frappe.get_doc("PIM Onboarding State", existing)
    summary = doc.get_status_summary()

    # Include step data for the current step (useful for resuming forms)
    current_data = doc.get_step_data(doc.current_step)
    if current_data:
        summary["current_step_data"] = current_data

    return summary


@frappe.whitelist()
def save_step_data(step, form_data, user=None, advance=False):
    """Save form data for a specific onboarding step.

    Allows partial saves (drafts) during a step. Optionally
    advances to the next step after saving.

    Args:
        step: The step name to save data for (e.g., "company_info",
            "industry_selection", "product_structure")
        form_data: JSON string or dict of form data collected during the step
        user: User email. Defaults to current session user.
        advance: If True, also advance to the next step after saving

    Returns:
        dict: Updated onboarding state summary

    Example:
        >>> result = save_step_data(
        ...     step="company_info",
        ...     form_data='{"company_name": "Acme Corp", "industry": "retail"}',
        ...     advance=True
        ... )
        >>> print(f"Now at step: {result['current_step']}")
    """
    import frappe
    from frappe import _
    import json

    if not user:
        user = frappe.session.user

    if not frappe.has_permission("PIM Onboarding State", "write"):
        frappe.throw(_("Not permitted to modify onboarding"), frappe.PermissionError)

    # Find onboarding state
    existing = frappe.db.exists("PIM Onboarding State", {"user": user})
    if not existing:
        return {"current_step": "pending", "is_completed": False, "error": _("No onboarding state. Start onboarding first.")}

    doc = frappe.get_doc("PIM Onboarding State", existing)

    # Parse form_data if it's a JSON string (avoid 417)
    if isinstance(form_data, str):
        try:
            parsed_data = json.loads(form_data)
        except (json.JSONDecodeError, TypeError):
            return {"current_step": doc.current_step, "is_completed": False, "error": _("Invalid form_data: must be valid JSON")}
    else:
        parsed_data = form_data

    if not isinstance(parsed_data, dict):
        return {"current_step": doc.current_step, "is_completed": False, "error": _("form_data must be a JSON object (dict)")}

    try:
        doc.save_step_data(step, parsed_data)
        if advance:
            doc.advance_step()
        return doc.get_status_summary()
    except frappe.ValidationError as e:
        return {"current_step": doc.current_step, "is_completed": False, "error": str(e)}


@frappe.whitelist()
def apply_archetype_template(archetype, user=None, dry_run=False):
    """Apply an industry archetype template to configure PIM.

    Loads the specified archetype template (and its base template if
    declared) and creates all configuration entities: attribute groups,
    attribute types, attributes, product types, product families, and
    categories.

    Args:
        archetype: Archetype identifier (e.g., "fashion", "industrial",
            "food", "base")
        user: User email. Defaults to current session user.
        dry_run: If True, validate and preview without creating records

    Returns:
        dict: Template application result
            - success: Whether application succeeded
            - archetype: The archetype that was applied
            - status: Application status (completed, partial, failed)
            - entities_created: Number of entities created
            - entities_skipped: Number of entities skipped (already exist)
            - entities_failed: Number of entities that failed
            - details: Per-section breakdown
            - errors: List of error messages
            - messages: List of informational messages

    Example:
        >>> result = apply_archetype_template("fashion")
        >>> if result['success']:
        ...     print(f"Created {result['entities_created']} entities")
    """
    import frappe
    from frappe import _

    if not user:
        user = frappe.session.user

    if not frappe.has_permission("PIM Onboarding State", "write"):
        frappe.throw(_("Not permitted to apply templates"), frappe.PermissionError)

    # Resolve onboarding state name for integration
    onboarding_state_name = None
    existing = frappe.db.exists("PIM Onboarding State", {"user": user})
    if existing:
        onboarding_state_name = existing

    # Apply via the template engine
    from frappe_pim.pim.services.template_engine import TemplateEngine

    try:
        template_result = TemplateEngine.apply_template(
            archetype_name=archetype,
            onboarding_state_name=onboarding_state_name if not dry_run else None,
            dry_run=dry_run,
        )
    except Exception as e:
        frappe.log_error(
            message=f"Template application failed for archetype '{archetype}': {str(e)}",
            title="PIM Onboarding Template Error"
        )
        return {
            "success": False,
            "archetype": archetype,
            "status": "failed",
            "entities_created": 0,
            "entities_skipped": 0,
            "entities_failed": 0,
            "details": {},
            "errors": [str(e)],
            "messages": [],
        }

    result_dict = template_result.to_dict()
    success = result_dict["status"] in ("completed", "partial")

    return {
        "success": success,
        "archetype": result_dict["archetype"],
        "status": result_dict["status"],
        "entities_created": result_dict["entities_created"],
        "entities_skipped": result_dict["entities_skipped"],
        "entities_failed": result_dict["entities_failed"],
        "details": result_dict["details"],
        "errors": result_dict["errors"],
        "messages": result_dict["messages"],
        "dry_run": dry_run,
    }


@frappe.whitelist()
def complete_onboarding(user=None, form_data=None):
    """Advance the onboarding wizard to the next step, or complete it.

    If on the last actionable step, marks onboarding as completed.
    Saves form data for the current step if provided.

    Args:
        user: User email. Defaults to current session user.
        form_data: Optional JSON string or dict of form data for the
            current step before advancing.

    Returns:
        dict: Updated onboarding state summary

    Example:
        >>> result = complete_onboarding(
        ...     form_data='{"confirm": true}'
        ... )
        >>> if result['is_completed']:
        ...     print("Onboarding finished!")
    """
    import frappe
    from frappe import _
    import json

    if not user:
        user = frappe.session.user

    if not frappe.has_permission("PIM Onboarding State", "write"):
        frappe.throw(_("Not permitted to modify onboarding"), frappe.PermissionError)

    existing = frappe.db.exists("PIM Onboarding State", {"user": user})
    if not existing:
        frappe.throw(
            _("No onboarding state found for user {0}. Call start_onboarding first.").format(user),
            title=_("Not Found")
        )

    doc = frappe.get_doc("PIM Onboarding State", existing)

    if doc.is_completed:
        return doc.get_status_summary()

    # Parse form_data
    parsed_data = None
    if form_data:
        if isinstance(form_data, str):
            try:
                parsed_data = json.loads(form_data)
            except (json.JSONDecodeError, TypeError):
                frappe.throw(
                    _("Invalid form_data: must be valid JSON"),
                    title=_("Invalid Data")
                )
        else:
            parsed_data = form_data

    # Advance to next step (handles completion automatically)
    doc.advance_step(form_data=parsed_data)

    return doc.get_status_summary()


@frappe.whitelist()
def get_available_archetypes():
    """Get list of available industry archetype templates.

    Scans the PIM fixtures directory for archetype template JSON files
    and returns metadata for each.

    Returns:
        dict: Available archetypes information
            - archetypes: List of archetype dicts, each containing:
                - archetype: Identifier (e.g., "fashion")
                - label: Human-readable name (e.g., "Fashion & Apparel")
                - description: Brief description
                - version: Template version
            - total: Total number of available archetypes

    Example:
        >>> result = get_available_archetypes()
        >>> for arch in result['archetypes']:
        ...     print(f"{arch['label']}: {arch['description']}")
    """
    import frappe
    from frappe import _

    if not frappe.has_permission("PIM Onboarding State", "read"):
        frappe.throw(_("Not permitted to view archetypes"), frappe.PermissionError)

    from frappe_pim.pim.services.template_engine import TemplateEngine

    archetypes = TemplateEngine.get_available_archetypes()

    # Remove internal file_path from response
    for arch in archetypes:
        arch.pop("file_path", None)

    return {
        "archetypes": archetypes,
        "total": len(archetypes),
    }


@frappe.whitelist()
def skip_onboarding(user=None):
    """Skip the onboarding wizard entirely.

    Marks the onboarding as skipped so the user can configure
    PIM manually without the guided wizard.

    Args:
        user: User email. Defaults to current session user.

    Returns:
        dict: Updated onboarding state summary with is_skipped=True

    Example:
        >>> result = skip_onboarding()
        >>> assert result['is_skipped'] is True
    """
    import frappe
    from frappe import _

    if not user:
        user = frappe.session.user

    if not frappe.has_permission("PIM Onboarding State", "write"):
        frappe.throw(_("Not permitted to modify onboarding"), frappe.PermissionError)

    existing = frappe.db.exists("PIM Onboarding State", {"user": user})
    if not existing:
        frappe.throw(
            _("No onboarding state found for user {0}. Call start_onboarding first.").format(user),
            title=_("Not Found")
        )

    doc = frappe.get_doc("PIM Onboarding State", existing)
    doc.skip_onboarding()

    return doc.get_status_summary()


@frappe.whitelist()
def reset_onboarding(user=None):
    """Reset onboarding to initial state.

    Clears all step data, template application, and resets progress
    to zero. Requires System Manager role.

    Args:
        user: User email. Defaults to current session user.

    Returns:
        dict: Reset onboarding state summary

    Example:
        >>> result = reset_onboarding()
        >>> assert result['current_step'] == 'pending'
        >>> assert result['progress_percent'] == 0
    """
    import frappe
    from frappe import _

    if not user:
        user = frappe.session.user

    if not frappe.has_permission("PIM Onboarding State", "write"):
        frappe.throw(_("Not permitted to reset onboarding"), frappe.PermissionError)

    existing = frappe.db.exists("PIM Onboarding State", {"user": user})
    if not existing:
        frappe.throw(
            _("No onboarding state found for user {0}").format(user),
            title=_("Not Found")
        )

    doc = frappe.get_doc("PIM Onboarding State", existing)
    doc.reset_onboarding()

    return doc.get_status_summary()


@frappe.whitelist()
def preview_archetype(archetype):
    """Preview what an archetype template will create without applying it.

    Returns a summary of all entities that would be created, including
    counts and item keys per section.

    Args:
        archetype: Archetype identifier (e.g., "fashion", "industrial")

    Returns:
        dict: Preview information
            - archetype: Archetype identifier
            - label: Human-readable name
            - description: Brief description
            - version: Template version
            - extends: Base template name (if any)
            - sections: Per-section details with counts and item keys

    Example:
        >>> preview = preview_archetype("fashion")
        >>> print(f"Will create {preview['sections']['attributes']['count']} attributes")
    """
    import frappe
    from frappe import _

    if not frappe.has_permission("PIM Onboarding State", "read"):
        frappe.throw(_("Not permitted to preview archetypes"), frappe.PermissionError)

    from frappe_pim.pim.services.template_engine import TemplateEngine

    try:
        return TemplateEngine.preview_template(archetype)
    except FileNotFoundError:
        frappe.throw(
            _("Archetype template '{0}' not found").format(archetype),
            title=_("Template Not Found")
        )
    except ValueError as e:
        frappe.throw(
            _("Invalid template: {0}").format(str(e)),
            title=_("Template Error")
        )


# ============================================================================
# New Endpoints (Tenant Config + OnboardingService pattern)
# ============================================================================


def _default_onboarding_steps_response(current_step: int = 1):
    """Return a minimal step list so the UI can render when status API fails."""
    step_ids = (
        "company_info", "industry_selection", "product_structure", "attribute_config",
        "taxonomy", "channel_setup", "localization", "workflow_preferences",
        "quality_scoring", "integrations", "compliance", "summary_launch",
    )
    return [
        {
            "step_id": step_id,
            "step_number": idx + 1,
            "is_completed": False,
            "is_current": (idx + 1) == current_step,
            "is_skippable": idx + 1 in (9, 10, 11),
            "is_mandatory": idx + 1 not in (9, 10, 11) and idx + 1 != 12,
            "was_skipped": False,
        }
        for idx, step_id in enumerate(step_ids)
    ]


@frappe.whitelist()
def get_onboarding_status():
    """Get the combined onboarding status from Tenant Config and state.

    Reads ``Tenant Config.onboarding_status`` for the gate check
    (is the tenant onboarded?) and ``PIM Onboarding State`` for
    step-level progress.

    Returns:
        dict: Combined onboarding status
            - status: Onboarding status (not_started, in_progress, completed)
            - current_step: Current step number (1-12)
            - total_steps: Total number of steps (12)
            - completed_steps: List of completed step IDs
            - can_skip_remaining: Whether remaining steps can be skipped
            - started_at: When onboarding began
            - completed_at: When onboarding finished
            - selected_industry: Chosen industry sector
            - template_applied: Whether a template has been applied
            - progress_percent: Completion percentage (0-100)
            - steps: Per-step metadata list

    Example:
        >>> status = get_onboarding_status()
        >>> if status['status'] == 'completed':
        ...     print("Tenant is fully onboarded")
        >>> else:
        ...     print(f"Step {status['current_step']} of {status['total_steps']}")
    """
    import frappe
    from frappe import _

    if not frappe.has_permission("PIM Onboarding State", "read"):
        frappe.throw(_("Not permitted to access onboarding status"), frappe.PermissionError)

    try:
        from frappe_pim.pim.services.onboarding_service import OnboardingService
        return OnboardingService.get_status()
    except frappe.ValidationError as e:
        return {
            "status": "error",
            "message": str(e),
            "current_step": 0,
            "total_steps": 12,
            "completed_steps": [],
            "can_skip_remaining": False,
            "steps": _default_onboarding_steps_response(1),
            "progress_percent": 0.0,
        }
    except Exception as e:
        frappe.log_error(
            title="PIM get_onboarding_status failed",
            message=frappe.get_traceback(),
        )
        return {
            "status": "error",
            "message": str(e),
            "current_step": 1,
            "total_steps": 12,
            "completed_steps": [],
            "can_skip_remaining": False,
            "steps": _default_onboarding_steps_response(1),
            "progress_percent": 0.0,
        }


@frappe.whitelist()
def save_step(step_id, step_number, form_data, advance=False):
    """Save form data for a specific onboarding step with dual-write.

    Writes to both ``PIM Onboarding State`` (per-user progress) and
    ``Tenant Config`` (per-site configuration). Creates an audit trail
    entry in ``Onboarding Step Log``.

    Args:
        step_id: Step identifier (e.g., "company_info", "industry_selection",
            "product_structure", "attribute_config", "taxonomy",
            "channel_setup", "localization", "workflow_preferences",
            "quality_scoring", "integrations", "compliance", "summary_launch")
        step_number: Step number (1-12)
        form_data: JSON string or dict of form data for the step
        advance: If True, advance to the next step after saving

    Returns:
        dict: Save result
            - success: Whether save succeeded
            - step_id: The step that was saved
            - step_number: The step number
            - next_step: Next step number (if advance=True)
            - validation_errors: List of validation error messages
            - message: Status message

    Example:
        >>> result = save_step(
        ...     step_id="company_info",
        ...     step_number=1,
        ...     form_data='{"company_name": "Acme Corp", "company_size": "51-200"}',
        ...     advance=True
        ... )
        >>> if result['success']:
        ...     print(f"Saved, next step: {result['next_step']}")
    """
    import frappe
    from frappe import _
    import json

    if not frappe.has_permission("PIM Onboarding State", "write"):
        frappe.throw(_("Not permitted to modify onboarding"), frappe.PermissionError)

    # Parse form_data if it's a JSON string
    if isinstance(form_data, str):
        try:
            parsed_data = json.loads(form_data)
        except (json.JSONDecodeError, TypeError):
            return {
                "success": False,
                "step_id": step_id,
                "step_number": step_number,
                "validation_errors": [_("Invalid form_data: must be valid JSON")],
                "message": _("Invalid form_data: must be valid JSON"),
            }
    else:
        parsed_data = form_data

    if not isinstance(parsed_data, dict):
        return {
            "success": False,
            "step_id": step_id,
            "step_number": step_number,
            "validation_errors": [_("form_data must be a JSON object (dict)")],
            "message": _("form_data must be a JSON object (dict)"),
        }

    # Coerce step_number to int (Frappe API may pass string)
    try:
        step_number = int(step_number)
    except (TypeError, ValueError):
        return {
            "success": False,
            "step_id": step_id,
            "step_number": step_number,
            "validation_errors": [_("step_number must be an integer (1-12)")],
            "message": _("step_number must be an integer (1-12)"),
        }

    try:
        from frappe_pim.pim.services.onboarding_service import OnboardingService
        return OnboardingService.save_step(
            step_id=step_id,
            step_number=step_number,
            form_data=parsed_data,
            advance=bool(advance),
        )
    except frappe.ValidationError as e:
        return {
            "success": False,
            "step_id": step_id,
            "step_number": step_number,
            "validation_errors": [str(e)],
            "message": str(e),
        }


@frappe.whitelist()
def skip_step(step_id, step_number):
    """Skip an individual onboarding step.

    Only steps 9-11 (quality_scoring, integrations, compliance) are
    skippable, and only after step 8 (workflow_preferences) has been
    completed.

    Args:
        step_id: Step identifier to skip (e.g., "quality_scoring",
            "integrations", "compliance")
        step_number: Step number to skip (9, 10, or 11)

    Returns:
        dict: Skip result
            - success: Whether skip succeeded
            - step_id: The step that was skipped
            - step_number: The step number
            - next_step: Next step number after the skipped one
            - validation_errors: List of validation error messages
            - message: Status message

    Example:
        >>> result = skip_step(step_id="quality_scoring", step_number=9)
        >>> if result['success']:
        ...     print(f"Skipped, next step: {result['next_step']}")
    """
    import frappe
    from frappe import _

    if not frappe.has_permission("PIM Onboarding State", "write"):
        frappe.throw(_("Not permitted to modify onboarding"), frappe.PermissionError)

    # Coerce step_number to int
    try:
        step_number = int(step_number)
    except (TypeError, ValueError):
        return {
            "success": False,
            "step_id": step_id,
            "step_number": step_number,
            "validation_errors": [_("step_number must be an integer")],
            "message": _("step_number must be an integer"),
        }

    try:
        from frappe_pim.pim.services.onboarding_service import OnboardingService
        return OnboardingService.skip_step(
            step_id=step_id,
            step_number=step_number,
        )
    except frappe.ValidationError as e:
        return {
            "success": False,
            "step_id": step_id,
            "step_number": step_number,
            "validation_errors": [str(e)],
            "message": str(e),
        }


@frappe.whitelist()
def get_template_preview(industry=None):
    """Preview what an industry template will create.

    Returns a summary of all entities that would be created by the
    selected industry template, including attribute groups, product
    families, channels, compliance modules, and scoring weights.

    Uses the ``Industry Template`` DocType instead of fixture JSON
    files for versioned template data.

    Args:
        industry: Industry sector code (e.g., "fashion", "industrial",
            "food", "electronics", "health_beauty", "automotive",
            "custom"). If None, uses the industry selected in
            Tenant Config.

    Returns:
        dict: Template preview information
            - display_name: Human-readable industry name
            - attribute_count: Total number of attributes
            - attribute_groups: List of attribute group names
            - product_families: List of product family definitions
            - default_channels: List of default channel identifiers
            - coming_soon_channels: List of upcoming channels
            - compliance_modules: List of compliance module names
            - quality_threshold: Default quality threshold
            - scoring_weights: Quality scoring weight breakdown
            - default_languages: List of default language codes
            - estimated_setup_minutes: Estimated setup time
            - demo_products: Number of demo products available

    Example:
        >>> preview = get_template_preview("fashion")
        >>> print(f"Will create {preview['attribute_count']} attributes")
        >>> print(f"Groups: {', '.join(preview['attribute_groups'])}")
    """
    import frappe
    from frappe import _

    if not frappe.has_permission("PIM Onboarding State", "read"):
        frappe.throw(_("Not permitted to preview templates"), frappe.PermissionError)

    try:
        from frappe_pim.pim.services.onboarding_service import OnboardingService
        return OnboardingService.get_template_preview(industry=industry)
    except frappe.ValidationError as e:
        return {
            "display_name": "",
            "attribute_count": 0,
            "attribute_groups": [],
            "product_families": [],
            "default_channels": [],
            "error": str(e),
        }


@frappe.whitelist()
def apply_template(create_demo_products=False):
    """Apply the industry template based on Tenant Config selection.

    Reads the selected industry from ``Tenant Config.selected_industry``
    and applies the corresponding industry template. Optionally creates
    demo products for the tenant.

    Args:
        create_demo_products: If True, also create demo products from the
            template. Defaults to False.

    Returns:
        dict: Template application result
            - success: Whether application succeeded
            - status: Application status (completed, partial, failed)
            - entities_created: Dict of entity type counts
            - demo_products_created: Number of demo products created
            - onboarding_completed_at: Completion timestamp
            - redirect_to: Post-completion redirect URL
            - errors: List of error messages
            - messages: List of informational messages

    Example:
        >>> result = apply_template(create_demo_products=True)
        >>> if result['success']:
        ...     print(f"Created {result['entities_created']} entities")
    """
    import frappe
    from frappe import _

    if not frappe.has_permission("PIM Onboarding State", "write"):
        frappe.throw(_("Not permitted to apply templates"), frappe.PermissionError)

    try:
        from frappe_pim.pim.services.onboarding_service import OnboardingService
        return OnboardingService.apply_template(
            create_demo_products=bool(create_demo_products),
        )
    except frappe.ValidationError as e:
        return {
            "success": False,
            "status": "failed",
            "errors": [str(e)],
            "message": str(e),
            "redirect_to": None,
        }


@frappe.whitelist()
def v2_complete_onboarding(form_data=None):
    """Complete the onboarding wizard with Tenant Config update.

    Aggregates all step data, applies the selected industry template,
    updates feature flags, and marks both ``PIM Onboarding State`` and
    ``Tenant Config`` as completed. This is the new version that
    coordinates with the Tenant Config singleton.

    Args:
        form_data: Optional JSON string or dict of final form data from
            the summary/launch step.

    Returns:
        dict: Completion result
            - success: Whether completion succeeded
            - status: Final status (completed, failed)
            - entities_created: Dict of entity type counts
            - demo_products_created: Number of demo products created
            - onboarding_completed_at: Completion timestamp
            - redirect_to: Post-completion redirect URL
            - errors: List of error messages
            - messages: List of informational messages

    Example:
        >>> result = v2_complete_onboarding(
        ...     form_data='{"confirm_launch": true}'
        ... )
        >>> if result['success']:
        ...     print(f"Onboarding complete! Go to {result['redirect_to']}")
    """
    import frappe
    from frappe import _
    import json

    if not frappe.has_permission("PIM Onboarding State", "write"):
        frappe.throw(_("Not permitted to complete onboarding"), frappe.PermissionError)

    # Parse form_data if it's a JSON string (avoid 417: return error dict instead of throw)
    parsed_data = None
    if form_data:
        if isinstance(form_data, str):
            try:
                parsed_data = json.loads(form_data)
            except (json.JSONDecodeError, TypeError):
                return {
                    "success": False,
                    "status": "failed",
                    "errors": [_("Invalid form_data: must be valid JSON")],
                    "message": _("Invalid form_data: must be valid JSON"),
                    "redirect_to": None,
                }
        else:
            parsed_data = form_data

    try:
        from frappe_pim.pim.services.onboarding_service import OnboardingService
        return OnboardingService.complete_onboarding(form_data=parsed_data)
    except frappe.ValidationError as e:
        return {
            "success": False,
            "status": "failed",
            "errors": [str(e)],
            "message": str(e),
            "redirect_to": None,
        }


@frappe.whitelist()
def update_post_onboarding(section, form_data):
    """Update tenant configuration after onboarding completion.

    Allows editing of onboarding-configured sections in
    ``Tenant Config`` after the wizard has been completed.
    Used by the post-onboarding Settings > Onboarding Configuration
    editor.

    If ``section`` is "industry" and the value changes, returns an
    ``impact_warning`` with affected entity counts.

    Args:
        section: Configuration section to update. Valid sections:
            "company_info", "industry", "product_structure", "attributes",
            "taxonomy", "channels", "localization", "workflow", "quality",
            "integrations", "compliance"
        form_data: JSON string or dict of field values to update

    Returns:
        dict: Update result
            - success: Whether update succeeded
            - updated_fields: List of field names that were updated
            - impact_warning: Impact analysis if industry changed (or None)
            - message: Status message

    Example:
        >>> result = update_post_onboarding(
        ...     section="company_info",
        ...     form_data='{"company_name": "New Corp Name"}'
        ... )
        >>> if result['success']:
        ...     print(f"Updated: {result['updated_fields']}")
    """
    import frappe
    from frappe import _
    import json

    if not frappe.has_permission("PIM Onboarding State", "write"):
        frappe.throw(_("Not permitted to update onboarding configuration"), frappe.PermissionError)

    # Parse form_data if it's a JSON string
    if isinstance(form_data, str):
        try:
            parsed_data = json.loads(form_data)
        except (json.JSONDecodeError, TypeError):
            frappe.throw(
                _("Invalid form_data: must be valid JSON"),
                title=_("Invalid Data")
            )
    else:
        parsed_data = form_data

    if not isinstance(parsed_data, dict):
        return {
            "success": False,
            "updated_fields": [],
            "impact_warning": None,
            "message": _("form_data must be a JSON object (dict)"),
        }

    try:
        from frappe_pim.pim.services.onboarding_service import OnboardingService
        return OnboardingService.update_post_onboarding(
            section=section,
            form_data=parsed_data,
        )
    except frappe.ValidationError as e:
        return {
            "success": False,
            "updated_fields": [],
            "impact_warning": None,
            "message": str(e),
        }


