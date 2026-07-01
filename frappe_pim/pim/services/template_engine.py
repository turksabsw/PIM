"""Template Engine Service

Loads industry archetype templates and applies them to create PIM
configuration entities (Product Types, Attribute Types, Attribute Groups,
Attributes, Product Families, Categories). Entirely configuration-driven
with no hardcoded sector logic.

Supports two template sources:
1. **JSON fixtures** — archetype template files in the ``fixtures/`` dir
   (legacy, always available).
2. **Industry Template DocType** — versioned sector templates stored in
   the database with active-version management (preferred for production).

The engine checks the DocType source first (if available) and falls back
to fixture files, preserving full backward compatibility.

Key Concepts:
- Archetype Template: A JSON fixture describing a complete industry
  configuration (e.g., fashion, industrial, food).
- Industry Template: A versioned DocType record for the same purpose,
  with active-version selection per template_code.
- Base Template: Common configuration shared across all archetypes.
- Template Application: The process of reading a template and creating
  the corresponding DocType records idempotently.
- Onboarding Integration: After successful application the onboarding
  state is updated via ``PIMOnboardingState.mark_template_applied()``.

Template JSON Schema (fixture format):
{
    "archetype": "fashion",
    "version": "1.0",
    "label": "Fashion & Apparel",
    "description": "...",
    "extends": "base",              // optional base template to apply first
    "attribute_groups": [...],
    "attribute_types": [...],
    "attributes": [...],
    "product_types": [...],
    "product_families": [...],
    "categories": [...]
}

Each entity list contains dicts whose keys match the target DocType fields.
The engine creates records idempotently: if a record with the same primary
key already exists it is skipped (not overwritten).

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

import json
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# =============================================================================
# Constants and Enums
# =============================================================================

class TemplateStatus(Enum):
    """Status of a template application."""
    PENDING = "pending"
    VALIDATING = "validating"
    APPLYING = "applying"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class TemplateSource(Enum):
    """Where a template was loaded from."""
    FIXTURE = "fixture"
    DOCTYPE = "doctype"


class EntityType(Enum):
    """Supported entity types in a template."""
    ATTRIBUTE_GROUP = "attribute_groups"
    ATTRIBUTE_TYPE = "attribute_types"
    ATTRIBUTE = "attributes"
    PRODUCT_TYPE = "product_types"
    PRODUCT_FAMILY = "product_families"
    CATEGORY = "categories"


# Map from template section key to Frappe DocType name
ENTITY_DOCTYPE_MAP: Dict[str, str] = {
    "attribute_groups": "PIM Attribute Group",
    "attribute_types": "PIM Attribute Type",
    "attributes": "PIM Attribute",
    "product_types": "PIM Product Type",
    "product_families": "Product Family",
    "categories": "Category",
}

# Map from template section key to the unique-key field used for idempotency
ENTITY_KEY_FIELD_MAP: Dict[str, str] = {
    "attribute_groups": "group_code",
    "attribute_types": "type_code",
    "attributes": "attribute_code",
    "product_types": "type_name",
    "product_families": "family_code",
    "categories": "category_name",
}

# Ordered list of entity types — the order matters because of dependencies
# (e.g., Attributes depend on Attribute Groups and Attribute Types).
ENTITY_APPLY_ORDER: List[str] = [
    "attribute_groups",
    "attribute_types",
    "attributes",
    "product_types",
    "product_families",
    "categories",
]

# Fixtures directory (relative to this file)
FIXTURES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "fixtures",
)

# Base template filename
BASE_TEMPLATE_FILENAME = "base_template.json"

# Industry Template DocType name
INDUSTRY_TEMPLATE_DOCTYPE = "Industry Template"

# JSON data fields on the Industry Template DocType
INDUSTRY_TEMPLATE_JSON_FIELDS = (
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


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class EntityResult:
    """Result of creating a single entity."""
    entity_type: str
    key: str
    created: bool
    skipped: bool = False
    error: Optional[str] = None


@dataclass
class TemplateResult:
    """Aggregate result of applying a template."""
    archetype: str
    status: str = "pending"
    entities_created: int = 0
    entities_skipped: int = 0
    entities_failed: int = 0
    details: Dict[str, Dict[str, int]] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    messages: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict for JSON storage."""
        return {
            "archetype": self.archetype,
            "status": self.status,
            "entities_created": self.entities_created,
            "entities_skipped": self.entities_skipped,
            "entities_failed": self.entities_failed,
            "details": self.details,
            "errors": self.errors,
            "messages": self.messages,
        }


# =============================================================================
# Template Engine
# =============================================================================

class TemplateEngine:
    """Configuration-driven template engine for PIM industry archetypes.

    Usage::

        engine = TemplateEngine()
        archetypes = engine.get_available_archetypes()
        template = engine.load_template("fashion")
        validation = engine.validate_template(template)
        if validation["valid"]:
            result = engine.apply_template("fashion")
    """

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    @staticmethod
    def get_available_archetypes(
        include_fixtures: bool = True,
        include_doctype: bool = True,
    ) -> List[Dict[str, Any]]:
        """Return metadata for all available archetype templates.

        Merges templates from both fixture files and the Industry Template
        DocType. When a template_code exists in both sources, the DocType
        version takes precedence (source is marked accordingly).

        Args:
            include_fixtures: Include fixture-based templates.
            include_doctype: Include Industry Template DocType records.

        Returns:
            List of dicts with ``archetype``, ``label``, ``description``,
            ``version``, ``source``, and optionally ``file_path`` keys.
        """
        archetypes: List[Dict[str, Any]] = []
        seen_codes: set = set()

        # 1. Industry Template DocType (preferred source)
        if include_doctype:
            for entry in TemplateEngine.get_available_industry_templates():
                archetypes.append(entry)
                seen_codes.add(entry["archetype"])

        # 2. Fixture files (fallback for codes not in DocType)
        if include_fixtures:
            for entry in TemplateEngine._get_fixture_archetypes():
                if entry["archetype"] not in seen_codes:
                    archetypes.append(entry)
                    seen_codes.add(entry["archetype"])

        return archetypes

    @staticmethod
    def load_template(archetype_name: str) -> Dict[str, Any]:
        """Load a template by archetype name.

        Resolution order:
        1. Try fixture file on disk (backward compatible).
        2. Fall back to the active Industry Template DocType record.

        Args:
            archetype_name: Identifier such as ``"fashion"`` or ``"industrial"``.

        Returns:
            Parsed template dict (fixture format).

        Raises:
            FileNotFoundError: If no matching template is found in either source.
            ValueError: If the fixture file cannot be parsed as JSON.
        """
        # 1. Try fixture file first (backward compat)
        filepath = _resolve_template_path(archetype_name)
        if filepath:
            try:
                with open(filepath, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Template file for '{archetype_name}' is not valid JSON: {exc}"
                ) from exc
            return data

        # 2. Fall back to Industry Template DocType
        try:
            return TemplateEngine.load_industry_template(archetype_name)
        except FileNotFoundError:
            raise FileNotFoundError(
                f"No template found for archetype '{archetype_name}' "
                f"in fixtures or Industry Template DocType"
            )

    @staticmethod
    def validate_template(template_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate the structure and references in a template dict.

        Checks:
        - Required top-level keys (``archetype``, ``version``).
        - Each entity section is a list of dicts.
        - Each entity dict contains the required key field.
        - Forward references are consistent (e.g., an attribute's
          ``attribute_group`` exists within the same template or in the
          base template).

        Args:
            template_data: Parsed template dict.

        Returns:
            Dict with ``valid`` (bool), ``errors`` (list of strings),
            and ``warnings`` (list of strings).
        """
        errors: List[str] = []
        warnings: List[str] = []

        # Top-level keys — accept both fixture ("archetype") and DocType ("template_code")
        if not template_data.get("archetype") and not template_data.get("template_code"):
            errors.append("Missing required key: 'archetype' (or 'template_code')")
        if not template_data.get("version"):
            warnings.append("Missing 'version' key; defaulting to '1.0'")

        # Entity sections
        for section_key, doctype_name in ENTITY_DOCTYPE_MAP.items():
            section = template_data.get(section_key)
            if section is None:
                continue  # section is optional

            if not isinstance(section, list):
                errors.append(
                    f"Section '{section_key}' must be a list, "
                    f"got {type(section).__name__}"
                )
                continue

            key_field = ENTITY_KEY_FIELD_MAP[section_key]
            for idx, entry in enumerate(section):
                if not isinstance(entry, dict):
                    errors.append(
                        f"{section_key}[{idx}]: expected dict, "
                        f"got {type(entry).__name__}"
                    )
                    continue
                if not entry.get(key_field):
                    errors.append(
                        f"{section_key}[{idx}]: missing required key "
                        f"'{key_field}'"
                    )

        # Cross-reference validation: attributes → attribute_groups
        _validate_cross_references(template_data, errors, warnings)

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }

    @staticmethod
    def apply_template(
        archetype_name: str,
        onboarding_state_name: Optional[str] = None,
        skip_base: bool = False,
        dry_run: bool = False,
    ) -> TemplateResult:
        """Apply an industry archetype template.

        Loads the template (and its base, if any), validates it, and creates
        all configuration entities idempotently.

        Args:
            archetype_name: Archetype identifier (e.g., ``"fashion"``).
            onboarding_state_name: Optional name of the ``PIM Onboarding State``
                document to update after successful application.
            skip_base: If *True*, skip applying the base template even if
                the archetype declares ``"extends": "base"``.
            dry_run: If *True*, validate and count entities but do not
                write to the database.

        Returns:
            A :class:`TemplateResult` with counts and status.
        """
        import frappe
        from frappe import _

        result = TemplateResult(archetype=archetype_name)

        try:
            # 1. Load the template
            try:
                template_data = TemplateEngine.load_template(archetype_name)
            except (FileNotFoundError, ValueError) as exc:
                result.status = TemplateStatus.FAILED.value
                result.errors.append(str(exc))
                return result

            # 2. Validate
            result.status = TemplateStatus.VALIDATING.value
            validation = TemplateEngine.validate_template(template_data)
            if not validation["valid"]:
                result.status = TemplateStatus.FAILED.value
                result.errors.extend(validation["errors"])
                return result
            if validation.get("warnings"):
                result.messages.extend(validation["warnings"])

            # 3. Apply base template first (if declared)
            extends = template_data.get("extends")
            if extends and not skip_base:
                base_result = TemplateEngine._apply_template_data(
                    archetype_name=extends,
                    template_data=TemplateEngine.load_template(extends),
                    dry_run=dry_run,
                )
                _merge_results(result, base_result)
                result.messages.append(
                    f"Base template '{extends}' applied: "
                    f"{base_result.entities_created} created, "
                    f"{base_result.entities_skipped} skipped."
                )

            # 4. Apply main template
            result.status = TemplateStatus.APPLYING.value
            main_result = TemplateEngine._apply_template_data(
                archetype_name=archetype_name,
                template_data=template_data,
                dry_run=dry_run,
            )
            _merge_results(result, main_result)

            # 5. Determine final status
            if result.entities_failed > 0 and result.entities_created > 0:
                result.status = TemplateStatus.PARTIAL.value
            elif result.entities_failed > 0:
                result.status = TemplateStatus.FAILED.value
            else:
                result.status = TemplateStatus.COMPLETED.value

            # 6. Commit and update onboarding state
            if not dry_run:
                frappe.db.commit()

                if onboarding_state_name:
                    _update_onboarding_state(
                        onboarding_state_name, archetype_name, result
                    )

            result.messages.append(
                f"Template '{archetype_name}' application "
                f"{'(dry run) ' if dry_run else ''}"
                f"finished: {result.entities_created} created, "
                f"{result.entities_skipped} skipped, "
                f"{result.entities_failed} failed."
            )

        except Exception as exc:
            result.status = TemplateStatus.FAILED.value
            result.errors.append(f"Unexpected error: {exc}")
            try:
                frappe.log_error(
                    title=_("Template Engine Error"),
                    message=f"Archetype: {archetype_name}\n{exc}",
                )
            except Exception:
                pass

        return result

    @staticmethod
    def preview_template(archetype_name: str) -> Dict[str, Any]:
        """Return a summary of what a template will create without applying.

        Args:
            archetype_name: Archetype identifier.

        Returns:
            Dict with entity counts and sample data per section.
        """
        template_data = TemplateEngine.load_template(archetype_name)
        preview: Dict[str, Any] = {
            "archetype": template_data.get("archetype"),
            "label": template_data.get("label", ""),
            "description": template_data.get("description", ""),
            "version": template_data.get("version", "1.0"),
            "extends": template_data.get("extends"),
            "sections": {},
        }

        for section_key in ENTITY_APPLY_ORDER:
            items = template_data.get(section_key, [])
            key_field = ENTITY_KEY_FIELD_MAP.get(section_key, "name")
            preview["sections"][section_key] = {
                "count": len(items),
                "doctype": ENTITY_DOCTYPE_MAP.get(section_key, ""),
                "items": [
                    item.get(key_field, f"item-{idx}")
                    for idx, item in enumerate(items)
                ],
            }

        return preview

    # -----------------------------------------------------------------
    # Industry Template DocType API
    # -----------------------------------------------------------------

    @staticmethod
    def load_industry_template(
        template_code: str,
        version: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Load template data from the Industry Template DocType.

        Retrieves the active version by default, or a specific version
        if *version* is provided.

        Args:
            template_code: Sector identifier (e.g., ``"fashion"``).
            version: Specific version string (e.g., ``"1.0"``).
                If *None*, the active version is loaded.

        Returns:
            Dict with the full template data from the DocType
            (as returned by ``IndustryTemplate.get_template_data()``).

        Raises:
            FileNotFoundError: If the Industry Template DocType is
                unavailable or no matching record exists.
        """
        import frappe

        if not _industry_template_doctype_exists():
            raise FileNotFoundError(
                "Industry Template DocType is not available. "
                "Use load_template() for fixture-based loading."
            )

        filters: Dict[str, Any] = {"template_code": template_code}
        if version:
            filters["version"] = version
        else:
            filters["is_active"] = 1

        name = frappe.db.get_value(
            INDUSTRY_TEMPLATE_DOCTYPE, filters, "name"
        )

        if not name:
            version_info = f" version '{version}'" if version else " (active)"
            raise FileNotFoundError(
                f"No Industry Template found for code "
                f"'{template_code}'{version_info}"
            )

        doc = frappe.get_doc(INDUSTRY_TEMPLATE_DOCTYPE, name)
        return doc.get_template_data()

    # Alias for verification compatibility
    load_from_doctype = load_industry_template

    @staticmethod
    def get_available_industry_templates() -> List[Dict[str, Any]]:
        """Return metadata for all active Industry Template DocType records.

        Returns:
            List of dicts with ``archetype``, ``label``, ``description``,
            ``version``, and ``source`` keys. Returns an empty list if the
            DocType is unavailable.
        """
        if not _industry_template_doctype_exists():
            return []

        import frappe

        templates = frappe.get_all(
            INDUSTRY_TEMPLATE_DOCTYPE,
            filters={"is_active": 1},
            fields=[
                "name", "template_code", "display_name",
                "description", "version",
            ],
            order_by="template_code asc",
        )

        return [
            {
                "archetype": t.template_code,
                "label": t.display_name or t.template_code.replace("_", " ").title(),
                "description": t.description or "",
                "version": t.version or "1.0",
                "source": TemplateSource.DOCTYPE.value,
                "doctype_name": t.name,
            }
            for t in templates
        ]

    @staticmethod
    def list_template_versions(template_code: str) -> List[Dict[str, Any]]:
        """List all available versions of an industry template.

        Args:
            template_code: Sector identifier (e.g., ``"fashion"``).

        Returns:
            List of dicts with ``version``, ``is_active``, ``name``,
            and ``modified`` keys, sorted by version descending.
            Returns an empty list if the DocType is unavailable.
        """
        if not _industry_template_doctype_exists():
            return []

        import frappe

        versions = frappe.get_all(
            INDUSTRY_TEMPLATE_DOCTYPE,
            filters={"template_code": template_code},
            fields=["name", "version", "is_active", "modified"],
            order_by="version desc",
        )

        return [
            {
                "name": v.name,
                "version": v.version,
                "is_active": bool(v.is_active),
                "modified": str(v.modified) if v.modified else None,
            }
            for v in versions
        ]

    @staticmethod
    def get_active_version(template_code: str) -> Optional[Dict[str, Any]]:
        """Get the active version metadata for a template code.

        Args:
            template_code: Sector identifier (e.g., ``"fashion"``).

        Returns:
            Dict with ``name``, ``version``, ``is_active``, and
            ``modified`` keys, or *None* if no active version exists.
        """
        if not _industry_template_doctype_exists():
            return None

        import frappe

        name = frappe.db.get_value(
            INDUSTRY_TEMPLATE_DOCTYPE,
            {"template_code": template_code, "is_active": 1},
            "name",
        )

        if not name:
            return None

        doc_data = frappe.db.get_value(
            INDUSTRY_TEMPLATE_DOCTYPE,
            name,
            ["name", "version", "is_active", "modified"],
            as_dict=True,
        )

        return {
            "name": doc_data.name,
            "version": doc_data.version,
            "is_active": bool(doc_data.is_active),
            "modified": str(doc_data.modified) if doc_data.modified else None,
        }

    @staticmethod
    def preview_industry_template(
        template_code: str,
        version: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return a preview of an Industry Template DocType record.

        Similar to :meth:`preview_template` but reads from the DocType
        instead of a fixture file.

        Args:
            template_code: Sector identifier.
            version: Optional specific version. Defaults to active.

        Returns:
            Dict with preview data from ``IndustryTemplate.get_preview_data()``.

        Raises:
            FileNotFoundError: If no matching template is found.
        """
        import frappe

        if not _industry_template_doctype_exists():
            raise FileNotFoundError(
                "Industry Template DocType is not available."
            )

        filters: Dict[str, Any] = {"template_code": template_code}
        if version:
            filters["version"] = version
        else:
            filters["is_active"] = 1

        name = frappe.db.get_value(
            INDUSTRY_TEMPLATE_DOCTYPE, filters, "name"
        )

        if not name:
            version_info = f" version '{version}'" if version else " (active)"
            raise FileNotFoundError(
                f"No Industry Template found for code "
                f"'{template_code}'{version_info}"
            )

        doc = frappe.get_doc(INDUSTRY_TEMPLATE_DOCTYPE, name)
        return doc.get_preview_data()

    # -----------------------------------------------------------------
    # Internal helpers (fixture loading)
    # -----------------------------------------------------------------

    @staticmethod
    def _get_fixture_archetypes() -> List[Dict[str, Any]]:
        """Return metadata for archetype templates found in the fixtures dir.

        This is the original fixture-only logic, now extracted for reuse
        by :meth:`get_available_archetypes`.

        Returns:
            List of dicts with ``archetype``, ``label``, ``description``,
            ``version``, ``source``, and ``file_path`` keys.
        """
        archetypes: List[Dict[str, Any]] = []

        if not os.path.isdir(FIXTURES_DIR):
            return archetypes

        for filename in sorted(os.listdir(FIXTURES_DIR)):
            if not filename.endswith("_template.json"):
                continue
            filepath = os.path.join(FIXTURES_DIR, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as fh:
                    data = json.load(fh)

                archetype_name = data.get("archetype")
                if not archetype_name:
                    continue

                archetypes.append({
                    "archetype": archetype_name,
                    "label": data.get("label", archetype_name.replace("_", " ").title()),
                    "description": data.get("description", ""),
                    "version": data.get("version", "1.0"),
                    "source": TemplateSource.FIXTURE.value,
                    "file_path": filepath,
                })
            except (json.JSONDecodeError, OSError):
                continue

        return archetypes

    # -----------------------------------------------------------------
    # Internal helpers (template application)
    # -----------------------------------------------------------------

    @staticmethod
    def _apply_template_data(
        archetype_name: str,
        template_data: Dict[str, Any],
        dry_run: bool = False,
    ) -> TemplateResult:
        """Apply a single template dict (no base-resolution logic).

        Iterates entity sections in dependency order and creates records
        idempotently.
        """
        result = TemplateResult(archetype=archetype_name)

        for section_key in ENTITY_APPLY_ORDER:
            entities = template_data.get(section_key, [])
            if not entities:
                continue

            section_result = _apply_entity_section(
                section_key=section_key,
                entities=entities,
                dry_run=dry_run,
            )

            # Accumulate
            result.details[section_key] = section_result
            result.entities_created += section_result["created"]
            result.entities_skipped += section_result["skipped"]
            result.entities_failed += section_result["failed"]
            result.errors.extend(section_result.get("errors", []))

        return result


# =============================================================================
# Private Module-Level Helpers
# =============================================================================

def _industry_template_doctype_exists() -> bool:
    """Check whether the Industry Template DocType is available.

    Uses a deferred import and caches the result for the duration of the
    process.  Returns *False* if Frappe is not initialised or the DocType
    has not been created yet.
    """
    try:
        import frappe
        return bool(frappe.db.exists("DocType", INDUSTRY_TEMPLATE_DOCTYPE))
    except Exception:
        return False


def _resolve_template_path(archetype_name: str) -> Optional[str]:
    """Resolve the filesystem path for an archetype template.

    Tries two naming conventions:
    1. ``<archetype>_template.json``
    2. Scan all ``*_template.json`` files for matching ``archetype`` key.

    Args:
        archetype_name: The archetype identifier.

    Returns:
        Absolute path to the template file, or *None* if not found.
    """
    if not os.path.isdir(FIXTURES_DIR):
        return None

    # Convention: <archetype>_template.json
    direct = os.path.join(FIXTURES_DIR, f"{archetype_name}_template.json")
    if os.path.isfile(direct):
        return direct

    # Fallback: scan files for matching archetype key
    for filename in os.listdir(FIXTURES_DIR):
        if not filename.endswith("_template.json"):
            continue
        filepath = os.path.join(FIXTURES_DIR, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if data.get("archetype") == archetype_name:
                return filepath
        except (json.JSONDecodeError, OSError):
            continue

    return None


def _apply_entity_section(
    section_key: str,
    entities: List[Dict[str, Any]],
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Apply a list of entity definitions for a single section.

    Args:
        section_key: One of ``ENTITY_APPLY_ORDER`` keys.
        entities: List of entity dicts from the template.
        dry_run: If *True*, count but don't create.

    Returns:
        Dict with ``created``, ``skipped``, ``failed``, ``errors`` keys.
    """
    import frappe

    doctype = ENTITY_DOCTYPE_MAP[section_key]
    key_field = ENTITY_KEY_FIELD_MAP[section_key]

    section_result: Dict[str, Any] = {
        "created": 0,
        "skipped": 0,
        "failed": 0,
        "errors": [],
    }

    for entry in entities:
        key_value = entry.get(key_field)
        if not key_value:
            section_result["failed"] += 1
            section_result["errors"].append(
                f"{section_key}: entry missing key field '{key_field}'"
            )
            continue

        try:
            # Idempotency: skip if record already exists
            if frappe.db.exists(doctype, key_value):
                section_result["skipped"] += 1
                continue

            if dry_run:
                section_result["created"] += 1
                continue

            # Create the document
            doc = frappe.new_doc(doctype)

            # Apply fields from template entry
            _apply_fields_to_doc(doc, entry, section_key)

            doc.insert(ignore_permissions=True)
            section_result["created"] += 1

        except Exception as exc:
            section_result["failed"] += 1
            section_result["errors"].append(
                f"{section_key}/{key_value}: {exc}"
            )

    return section_result


def _apply_fields_to_doc(
    doc: Any,
    entry: Dict[str, Any],
    section_key: str,
) -> None:
    """Set fields on a Frappe document from a template entry dict.

    Handles both simple fields and child table entries.

    Args:
        doc: The Frappe document (``frappe.new_doc(...)``).
        entry: Dict of field values from the template.
        section_key: The entity section key for context.
    """
    child_table_fields = _get_child_table_fields(section_key)

    for field_name, value in entry.items():
        if field_name in child_table_fields and isinstance(value, list):
            # Child table: append rows
            for row_data in value:
                row = doc.append(field_name, {})
                for row_field, row_value in row_data.items():
                    row.set(row_field, row_value)
        else:
            doc.set(field_name, value)


def _get_child_table_fields(section_key: str) -> set:
    """Return the set of fields that are child tables for a given entity type.

    This avoids hard-coding by inspecting the DocType meta at runtime.
    Falls back to a known set when meta inspection is not possible.
    """
    try:
        import frappe

        doctype = ENTITY_DOCTYPE_MAP.get(section_key)
        if not doctype:
            return set()

        meta = frappe.get_meta(doctype)
        return {
            df.fieldname
            for df in meta.fields
            if df.fieldtype in ("Table", "Table MultiSelect")
        }
    except Exception:
        # Fallback: known child table fields per entity type
        return _KNOWN_CHILD_TABLE_FIELDS.get(section_key, set())


# Known child table fields as a fallback when frappe.get_meta is unavailable
_KNOWN_CHILD_TABLE_FIELDS: Dict[str, set] = {
    "product_types": {"type_fields", "allowed_families"},
    "product_families": {"attributes", "variant_attributes"},
    "attributes": {"options"},
    "categories": set(),
    "attribute_groups": set(),
    "attribute_types": set(),
}


def _validate_cross_references(
    template_data: Dict[str, Any],
    errors: List[str],
    warnings: List[str],
) -> None:
    """Validate cross-references within a template.

    For example, if an attribute references ``attribute_group: "dimensions"``,
    check that ``"dimensions"`` exists in the template's ``attribute_groups``
    section.
    """
    # Collect defined keys per section
    defined_keys: Dict[str, set] = {}
    for section_key, key_field in ENTITY_KEY_FIELD_MAP.items():
        section = template_data.get(section_key, [])
        if isinstance(section, list):
            defined_keys[section_key] = {
                entry.get(key_field)
                for entry in section
                if isinstance(entry, dict) and entry.get(key_field)
            }
        else:
            defined_keys[section_key] = set()

    # Validate attributes → attribute_groups
    for idx, attr in enumerate(template_data.get("attributes", [])):
        if not isinstance(attr, dict):
            continue
        group_ref = attr.get("attribute_group")
        if group_ref and group_ref not in defined_keys.get("attribute_groups", set()):
            warnings.append(
                f"attributes[{idx}]: attribute_group '{group_ref}' not "
                f"defined in this template (may exist in base or database)"
            )

    # Validate attributes → attribute_types (via attribute_type field)
    for idx, attr in enumerate(template_data.get("attributes", [])):
        if not isinstance(attr, dict):
            continue
        type_ref = attr.get("attribute_type")
        if type_ref and type_ref not in defined_keys.get("attribute_types", set()):
            warnings.append(
                f"attributes[{idx}]: attribute_type '{type_ref}' not "
                f"defined in this template (may exist in base or database)"
            )

    # Validate product_families → parent_family
    for idx, family in enumerate(template_data.get("product_families", [])):
        if not isinstance(family, dict):
            continue
        parent = family.get("parent_family")
        if parent and parent not in defined_keys.get("product_families", set()):
            warnings.append(
                f"product_families[{idx}]: parent_family '{parent}' not "
                f"defined in this template (may exist in base or database)"
            )

    # Validate categories → parent_category
    for idx, cat in enumerate(template_data.get("categories", [])):
        if not isinstance(cat, dict):
            continue
        parent = cat.get("parent_category")
        if parent and parent not in defined_keys.get("categories", set()):
            warnings.append(
                f"categories[{idx}]: parent_category '{parent}' not "
                f"defined in this template (may exist in base or database)"
            )


def _update_onboarding_state(
    state_name: str,
    archetype_name: str,
    result: TemplateResult,
) -> None:
    """Update the PIM Onboarding State after template application.

    Args:
        state_name: Name (primary key) of the PIM Onboarding State doc.
        archetype_name: Applied archetype.
        result: The template application result.
    """
    import frappe

    try:
        doc = frappe.get_doc("PIM Onboarding State", state_name)
        doc.mark_template_applied(archetype_name, result.to_dict())
    except Exception as exc:
        result.messages.append(
            f"Warning: failed to update onboarding state '{state_name}': {exc}"
        )


def _merge_results(target: TemplateResult, source: TemplateResult) -> None:
    """Merge counters and messages from *source* into *target*."""
    target.entities_created += source.entities_created
    target.entities_skipped += source.entities_skipped
    target.entities_failed += source.entities_failed
    target.errors.extend(source.errors)
    target.messages.extend(source.messages)

    for section_key, section_data in source.details.items():
        if section_key in target.details:
            for counter in ("created", "skipped", "failed"):
                target.details[section_key][counter] = (
                    target.details[section_key].get(counter, 0)
                    + section_data.get(counter, 0)
                )
            existing_errors = target.details[section_key].get("errors", [])
            existing_errors.extend(section_data.get("errors", []))
            target.details[section_key]["errors"] = existing_errors
        else:
            target.details[section_key] = dict(section_data)


# =============================================================================
# Convenience Functions (module-level API)
# =============================================================================

def load_template(archetype_name: str) -> Dict[str, Any]:
    """Convenience wrapper for :meth:`TemplateEngine.load_template`."""
    return TemplateEngine.load_template(archetype_name)


def apply_template(
    archetype_name: str,
    onboarding_state_name: Optional[str] = None,
    skip_base: bool = False,
    dry_run: bool = False,
) -> TemplateResult:
    """Convenience wrapper for :meth:`TemplateEngine.apply_template`."""
    return TemplateEngine.apply_template(
        archetype_name=archetype_name,
        onboarding_state_name=onboarding_state_name,
        skip_base=skip_base,
        dry_run=dry_run,
    )


def validate_template(template_data: Dict[str, Any]) -> Dict[str, Any]:
    """Convenience wrapper for :meth:`TemplateEngine.validate_template`."""
    return TemplateEngine.validate_template(template_data)


def get_available_archetypes() -> List[Dict[str, Any]]:
    """Convenience wrapper for :meth:`TemplateEngine.get_available_archetypes`."""
    return TemplateEngine.get_available_archetypes()


def preview_template(archetype_name: str) -> Dict[str, Any]:
    """Convenience wrapper for :meth:`TemplateEngine.preview_template`."""
    return TemplateEngine.preview_template(archetype_name)


def load_industry_template(
    template_code: str,
    version: Optional[str] = None,
) -> Dict[str, Any]:
    """Convenience wrapper for :meth:`TemplateEngine.load_industry_template`."""
    return TemplateEngine.load_industry_template(template_code, version)


def get_available_industry_templates() -> List[Dict[str, Any]]:
    """Convenience wrapper for :meth:`TemplateEngine.get_available_industry_templates`."""
    return TemplateEngine.get_available_industry_templates()


def list_template_versions(template_code: str) -> List[Dict[str, Any]]:
    """Convenience wrapper for :meth:`TemplateEngine.list_template_versions`."""
    return TemplateEngine.list_template_versions(template_code)


def get_active_version(template_code: str) -> Optional[Dict[str, Any]]:
    """Convenience wrapper for :meth:`TemplateEngine.get_active_version`."""
    return TemplateEngine.get_active_version(template_code)


def preview_industry_template(
    template_code: str,
    version: Optional[str] = None,
) -> Dict[str, Any]:
    """Convenience wrapper for :meth:`TemplateEngine.preview_industry_template`."""
    return TemplateEngine.preview_industry_template(template_code, version)
