"""
Import Configuration Controller
Manages product data import configurations with field mapping support
"""

import frappe
from frappe import _
from frappe.model.document import Document
from typing import Optional, List, Dict, Any
import json
import re


class ImportConfiguration(Document):
    def validate(self):
        self.validate_config_name()
        self.validate_field_mappings()
        self.validate_identifier_mapping()
        self.validate_format_settings()
        self.validate_scripts()

    def validate_config_name(self):
        """Ensure config_name is a valid slug"""
        if self.config_name:
            # Auto-clean the config name
            cleaned = frappe.scrub(self.config_name).replace("-", "_")
            if cleaned != self.config_name:
                self.config_name = cleaned

            # Validate format
            if not re.match(r'^[a-z][a-z0-9_]*$', self.config_name):
                frappe.throw(
                    _("Configuration Name must start with a letter and contain only lowercase letters, numbers, and underscores"),
                    title=_("Invalid Configuration Name")
                )

    def validate_field_mappings(self):
        """Validate field mappings configuration"""
        if not self.field_mappings:
            frappe.throw(
                _("At least one field mapping is required"),
                title=_("Missing Field Mappings")
            )

        # Check for duplicate target fields
        target_fields = []
        identifier_found = False

        for mapping in self.field_mappings:
            if not mapping.enabled:
                continue

            # Check for duplicate targets (except for attributes which can have multiple scopes)
            if mapping.field_type != "Attribute":
                if mapping.target_field in target_fields:
                    frappe.throw(
                        _("Duplicate target field '{0}' in field mappings").format(mapping.target_field),
                        title=_("Duplicate Field Mapping")
                    )
                target_fields.append(mapping.target_field)

            # Check if identifier field is mapped
            if mapping.is_identifier:
                identifier_found = True

            # Validate attribute mappings
            if mapping.field_type == "Attribute" and not mapping.attribute_code:
                frappe.throw(
                    _("Attribute code is required for field mapping '{0}' with Attribute field type").format(
                        mapping.source_field
                    ),
                    title=_("Missing Attribute Code")
                )

            # Validate transformation config
            if mapping.transformation in ["Number Format", "Date Parse", "Split to Array", "Custom Script"]:
                if mapping.transformation_config:
                    try:
                        json.loads(mapping.transformation_config)
                    except json.JSONDecodeError:
                        frappe.throw(
                            _("Invalid JSON in transformation config for field '{0}'").format(mapping.source_field),
                            title=_("Invalid Transformation Config")
                        )

            # Validate regex pattern
            if mapping.validation_regex:
                try:
                    re.compile(mapping.validation_regex)
                except re.error as e:
                    frappe.throw(
                        _("Invalid regex pattern for field '{0}': {1}").format(mapping.source_field, str(e)),
                        title=_("Invalid Validation Regex")
                    )

        # Warn if no identifier mapping exists
        if not identifier_found:
            frappe.msgprint(
                _("No field is marked as identifier. Make sure the identifier field '{0}' is correctly mapped.").format(
                    self.identifier_field
                ),
                title=_("No Identifier Field"),
                indicator="orange"
            )

    def validate_identifier_mapping(self):
        """Validate identifier field configuration"""
        if not self.identifier_field:
            frappe.throw(
                _("Identifier field is required"),
                title=_("Missing Identifier Field")
            )

        # Check if identifier field is valid for target doctype
        valid_identifiers = {
            "Product Master": ["sku", "external_id", "name"],
            "Product Variant": ["sku", "variant_sku", "external_id", "name"],
            "Digital Asset": ["asset_id", "file_name", "name"],
            "Brand": ["brand_code", "brand_name", "name"],
            "Manufacturer": ["manufacturer_code", "name"],
            "Product Family": ["family_code", "name"],
            "Taxonomy Node": ["node_code", "node_key", "name"]
        }

        target_identifiers = valid_identifiers.get(self.target_doctype, ["name"])
        if self.identifier_field not in target_identifiers:
            frappe.msgprint(
                _("Identifier field '{0}' may not be valid for {1}. Common identifiers: {2}").format(
                    self.identifier_field,
                    self.target_doctype,
                    ", ".join(target_identifiers)
                ),
                title=_("Identifier Field Warning"),
                indicator="orange"
            )

    def validate_format_settings(self):
        """Validate file format specific settings"""
        # Validate JSON root path
        if self.file_format == "JSON" and self.json_root_path:
            if not self.json_root_path.startswith("$"):
                frappe.throw(
                    _("JSON Root Path should start with '$' (e.g., $.data.products)"),
                    title=_("Invalid JSON Root Path")
                )

        # Validate XML XPath
        if self.file_format == "XML" and self.xml_record_xpath:
            if not self.xml_record_xpath.startswith("/") and not self.xml_record_xpath.startswith("."):
                frappe.throw(
                    _("XML Record XPath should start with '/' or '.' (e.g., //Product or ./products/product)"),
                    title=_("Invalid XML XPath")
                )

        # Validate batch size
        if self.batch_size is not None and self.batch_size < 1:
            frappe.throw(
                _("Batch size must be at least 1"),
                title=_("Invalid Batch Size")
            )

    def validate_scripts(self):
        """Validate pre/post import scripts for basic Python syntax"""
        for script_field in ["pre_import_script", "post_import_script"]:
            script = getattr(self, script_field, None)
            if script:
                try:
                    compile(script, f"<{script_field}>", "exec")
                except SyntaxError as e:
                    frappe.throw(
                        _("Syntax error in {0}: {1}").format(script_field.replace("_", " ").title(), str(e)),
                        title=_("Invalid Script")
                    )

    def on_update(self):
        """Handle post-update actions"""
        self.invalidate_cache()

    def invalidate_cache(self):
        """Clear relevant caches"""
        try:
            frappe.cache().delete_key(f"pim:import_config:{self.name}")
            frappe.cache().delete_key("pim:all_import_configs")
        except Exception:
            pass

    def get_delimiter_char(self) -> str:
        """Get the actual delimiter character from the option"""
        delimiter_map = {
            "Comma (,)": ",",
            "Semicolon (;)": ";",
            "Tab": "\t",
            "Pipe (|)": "|"
        }
        return delimiter_map.get(self.csv_delimiter, ",")

    def get_quote_char(self) -> Optional[str]:
        """Get the actual quote character from the option"""
        quote_map = {
            "Double Quote (\")": '"',
            "Single Quote (')": "'",
            "None": None
        }
        return quote_map.get(self.csv_quotechar, '"')

    def get_field_mapping_dict(self) -> Dict[str, Dict[str, Any]]:
        """Get field mappings as a dictionary keyed by source field"""
        mappings = {}
        for mapping in self.field_mappings:
            if mapping.enabled:
                mappings[mapping.source_field] = {
                    "target_field": mapping.target_field,
                    "field_type": mapping.field_type,
                    "attribute_code": mapping.attribute_code,
                    "data_type": mapping.data_type,
                    "is_required": mapping.is_required,
                    "is_identifier": mapping.is_identifier,
                    "transformation": mapping.transformation,
                    "transformation_config": mapping.transformation_config,
                    "default_value": mapping.default_value,
                    "validation_regex": mapping.validation_regex,
                    "validation_error_message": mapping.validation_error_message,
                    "lookup_doctype": mapping.lookup_doctype,
                    "lookup_field": mapping.lookup_field,
                    "create_if_missing": mapping.create_if_missing,
                    "scope_locale": mapping.scope_locale,
                    "scope_channel": mapping.scope_channel
                }
        return mappings

    def get_required_source_fields(self) -> List[str]:
        """Get list of required source fields"""
        return [
            mapping.source_field
            for mapping in self.field_mappings
            if mapping.enabled and mapping.is_required
        ]

    def get_identifier_source_field(self) -> str:
        """Get the source field name for the identifier"""
        if self.identifier_source_field:
            return self.identifier_source_field

        # Find from field mappings
        for mapping in self.field_mappings:
            if mapping.enabled and mapping.is_identifier:
                return mapping.source_field

        # Fall back to identifier field name
        return self.identifier_field

    def update_import_stats(
        self,
        records_imported: int = 0,
        records_updated: int = 0,
        records_skipped: int = 0,
        errors: int = 0,
        status: str = "Completed",
        filename: Optional[str] = None,
        total_records: int = 0,
        duration: float = 0.0,
        error_log: Optional[str] = None
    ):
        """Update import statistics after an import run"""
        updates = {
            "total_imports": (self.total_imports or 0) + 1,
            "total_records_imported": (self.total_records_imported or 0) + records_imported,
            "total_records_updated": (self.total_records_updated or 0) + records_updated,
            "total_records_skipped": (self.total_records_skipped or 0) + records_skipped,
            "total_errors": (self.total_errors or 0) + errors,
            "last_import_at": frappe.utils.now_datetime(),
            "last_import_status": status,
            "last_import_records": total_records,
            "last_import_success": records_imported + records_updated,
            "last_import_errors": errors,
            "last_import_duration": duration
        }

        if filename:
            updates["last_import_file"] = filename

        if error_log:
            updates["last_error_log"] = error_log

        frappe.db.set_value("Import Configuration", self.name, updates, update_modified=False)


@frappe.whitelist()
def get_import_configurations(
    enabled_only: bool = True,
    target_doctype: Optional[str] = None,
    source_system: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Get all import configurations with optional filters

    Args:
        enabled_only: If True, return only enabled configurations
        target_doctype: Filter by target doctype
        source_system: Filter by source system

    Returns:
        List of import configurations
    """
    filters = {}
    if enabled_only:
        filters["enabled"] = 1
    if target_doctype:
        filters["target_doctype"] = target_doctype
    if source_system:
        filters["source_system"] = source_system

    return frappe.get_all(
        "Import Configuration",
        filters=filters,
        fields=[
            "name", "config_name", "description", "target_doctype",
            "source_system", "file_format", "enabled", "last_import_at",
            "last_import_status", "total_imports", "total_records_imported"
        ],
        order_by="config_name asc"
    )


@frappe.whitelist()
def get_import_configuration(config_name: str) -> Dict[str, Any]:
    """Get detailed import configuration including field mappings

    Args:
        config_name: Import configuration name

    Returns:
        Full configuration details
    """
    doc = frappe.get_doc("Import Configuration", config_name)

    return {
        "name": doc.name,
        "config_name": doc.config_name,
        "description": doc.description,
        "enabled": doc.enabled,
        "source_system": doc.source_system,
        "target_doctype": doc.target_doctype,
        "file_format": doc.file_format,
        "file_encoding": doc.file_encoding,
        "csv_delimiter": doc.csv_delimiter,
        "csv_quotechar": doc.csv_quotechar,
        "has_header_row": doc.has_header_row,
        "skip_rows": doc.skip_rows,
        "json_root_path": doc.json_root_path,
        "xml_record_xpath": doc.xml_record_xpath,
        "xlsx_sheet_name": doc.xlsx_sheet_name,
        "identifier_field": doc.identifier_field,
        "identifier_source_field": doc.identifier_source_field,
        "duplicate_handling": doc.duplicate_handling,
        "update_only_empty": doc.update_only_empty,
        "field_mappings": [
            {
                "source_field": m.source_field,
                "target_field": m.target_field,
                "field_type": m.field_type,
                "attribute_code": m.attribute_code,
                "data_type": m.data_type,
                "is_required": m.is_required,
                "is_identifier": m.is_identifier,
                "transformation": m.transformation,
                "default_value": m.default_value,
                "enabled": m.enabled
            }
            for m in doc.field_mappings
        ],
        "statistics": {
            "total_imports": doc.total_imports,
            "total_records_imported": doc.total_records_imported,
            "total_records_updated": doc.total_records_updated,
            "total_records_skipped": doc.total_records_skipped,
            "total_errors": doc.total_errors,
            "last_import_at": doc.last_import_at,
            "last_import_status": doc.last_import_status
        }
    }


@frappe.whitelist()
def validate_import_file(
    config_name: str,
    file_url: str
) -> Dict[str, Any]:
    """Validate an import file against a configuration

    Args:
        config_name: Import configuration name
        file_url: URL of the uploaded file

    Returns:
        Validation result with any errors found
    """
    import csv
    import io

    doc = frappe.get_doc("Import Configuration", config_name)

    if not doc.enabled:
        return {
            "valid": False,
            "errors": [_("Import configuration is disabled")]
        }

    # Get file content
    try:
        file_doc = frappe.get_doc("File", {"file_url": file_url})
        file_path = file_doc.get_full_path()

        with open(file_path, "r", encoding=doc.file_encoding or "UTF-8") as f:
            content = f.read()
    except Exception as e:
        return {
            "valid": False,
            "errors": [_("Failed to read file: {0}").format(str(e))]
        }

    errors = []
    warnings = []
    row_count = 0
    sample_rows = []

    if doc.file_format in ["CSV", "TSV"]:
        try:
            delimiter = doc.get_delimiter_char()
            quotechar = doc.get_quote_char()

            reader = csv.DictReader(
                io.StringIO(content),
                delimiter=delimiter,
                quotechar=quotechar if quotechar else '"'
            )

            headers = reader.fieldnames or []

            # Check required source fields are present
            mapping_dict = doc.get_field_mapping_dict()
            for source_field in mapping_dict.keys():
                if source_field not in headers:
                    errors.append(_("Source field '{0}' not found in file headers").format(source_field))

            # Check required fields
            required_fields = doc.get_required_source_fields()
            for field in required_fields:
                if field not in headers:
                    errors.append(_("Required field '{0}' not found in file headers").format(field))

            # Count rows and collect sample
            for i, row in enumerate(reader):
                row_count += 1
                if i < 5:
                    sample_rows.append(dict(row))

                # Stop after checking first 1000 rows for performance
                if i >= 1000:
                    break

        except csv.Error as e:
            errors.append(_("CSV parsing error: {0}").format(str(e)))

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "row_count": row_count,
        "sample_rows": sample_rows,
        "headers": headers if "headers" in dir() else []
    }


@frappe.whitelist()
def run_import(
    config_name: str,
    file_url: str,
    dry_run: bool = False
) -> Dict[str, Any]:
    """Start an import job

    Args:
        config_name: Import configuration name
        file_url: URL of the uploaded file
        dry_run: If True, validate without importing

    Returns:
        Import job details
    """
    doc = frappe.get_doc("Import Configuration", config_name)

    if not doc.enabled:
        frappe.throw(_("Import configuration is disabled"))

    # Validate file first
    validation = validate_import_file(config_name, file_url)
    if not validation.get("valid"):
        return {
            "success": False,
            "message": _("File validation failed"),
            "errors": validation.get("errors", [])
        }

    if dry_run:
        return {
            "success": True,
            "message": _("Validation passed. {0} rows found.").format(validation.get("row_count", 0)),
            "row_count": validation.get("row_count", 0),
            "sample_rows": validation.get("sample_rows", [])
        }

    # Queue background job if configured
    if doc.run_in_background:
        job = frappe.enqueue(
            "frappe_pim.pim.doctype.import_configuration.import_configuration.process_import",
            queue="long",
            timeout=3600,
            config_name=config_name,
            file_url=file_url
        )

        return {
            "success": True,
            "message": _("Import job queued"),
            "job_id": job.id if hasattr(job, "id") else None,
            "status": "Queued"
        }
    else:
        # Run synchronously
        result = process_import(config_name, file_url)
        return result


def process_import(config_name: str, file_url: str) -> Dict[str, Any]:
    """Process the actual import

    Args:
        config_name: Import configuration name
        file_url: URL of the uploaded file

    Returns:
        Import result
    """
    import csv
    import io
    import time

    start_time = time.time()

    doc = frappe.get_doc("Import Configuration", config_name)

    # Update status
    frappe.db.set_value("Import Configuration", config_name, "last_import_status", "In Progress")
    frappe.db.commit()

    # Get file content
    file_doc = frappe.get_doc("File", {"file_url": file_url})
    file_path = file_doc.get_full_path()

    with open(file_path, "r", encoding=doc.file_encoding or "UTF-8") as f:
        content = f.read()

    records_imported = 0
    records_updated = 0
    records_skipped = 0
    errors = []

    if doc.file_format in ["CSV", "TSV"]:
        delimiter = doc.get_delimiter_char()
        quotechar = doc.get_quote_char()

        reader = csv.DictReader(
            io.StringIO(content),
            delimiter=delimiter,
            quotechar=quotechar if quotechar else '"'
        )

        mapping_dict = doc.get_field_mapping_dict()
        identifier_source = doc.get_identifier_source_field()

        for i, row in enumerate(reader):
            try:
                # Apply global transformations
                if doc.trim_whitespace:
                    row = {k: v.strip() if isinstance(v, str) else v for k, v in row.items()}

                if doc.empty_string_as_null:
                    row = {k: None if v == "" else v for k, v in row.items()}

                # Run pre-import script
                if doc.pre_import_script:
                    exec_globals = {"row": row, "frappe": frappe}
                    exec(doc.pre_import_script, exec_globals)
                    row = exec_globals.get("row", row)

                # Get identifier value
                identifier_value = row.get(identifier_source)

                if not identifier_value:
                    if doc.skip_invalid_rows:
                        records_skipped += 1
                        errors.append({"row": i + 1, "error": "Missing identifier value"})
                        continue
                    else:
                        raise ValueError("Missing identifier value")

                # Check for existing record
                existing = frappe.db.get_value(
                    doc.target_doctype,
                    {doc.identifier_field: identifier_value},
                    "name"
                )

                is_update = existing is not None

                if is_update and doc.duplicate_handling == "Skip Duplicates":
                    records_skipped += 1
                    continue
                elif is_update and doc.duplicate_handling == "Fail on Duplicate":
                    raise ValueError(f"Duplicate record found: {identifier_value}")
                elif is_update and doc.duplicate_handling == "Create New":
                    is_update = False

                # Build document data
                doc_data = {}
                for source_field, mapping in mapping_dict.items():
                    value = row.get(source_field, mapping.get("default_value"))

                    if value is None:
                        continue

                    # Apply transformation
                    value = apply_transformation(value, mapping)

                    # Handle different field types
                    if mapping["field_type"] == "Standard Field":
                        target = mapping["target_field"]
                        if is_update and doc.update_only_empty:
                            current_value = frappe.db.get_value(doc.target_doctype, existing, target)
                            if current_value:
                                continue
                        doc_data[target] = value

                    elif mapping["field_type"] == "Attribute":
                        # Handle attribute values separately
                        pass  # Attributes are handled after document creation

                # Create or update document
                if is_update:
                    target_doc = frappe.get_doc(doc.target_doctype, existing)
                    target_doc.update(doc_data)
                    target_doc.flags.from_import = True
                    target_doc.save()
                    records_updated += 1
                else:
                    target_doc = frappe.new_doc(doc.target_doctype)
                    target_doc.update(doc_data)
                    target_doc.flags.from_import = True
                    target_doc.insert()
                    records_imported += 1

                # Run post-import script
                if doc.post_import_script:
                    exec_globals = {"doc": target_doc, "row": row, "frappe": frappe}
                    exec(doc.post_import_script, exec_globals)

                # Commit every batch_size records
                if (i + 1) % (doc.batch_size or 100) == 0:
                    frappe.db.commit()

            except Exception as e:
                if doc.stop_on_error:
                    raise

                records_skipped += 1
                errors.append({"row": i + 1, "error": str(e)})

                if doc.max_errors and len(errors) >= doc.max_errors:
                    break

    # Final commit
    frappe.db.commit()

    duration = time.time() - start_time
    total_records = records_imported + records_updated + records_skipped

    # Determine status
    if len(errors) == 0:
        status = "Completed"
    elif records_imported + records_updated > 0:
        status = "Completed with Errors"
    else:
        status = "Failed"

    # Update statistics
    doc.update_import_stats(
        records_imported=records_imported,
        records_updated=records_updated,
        records_skipped=records_skipped,
        errors=len(errors),
        status=status,
        filename=file_doc.file_name,
        total_records=total_records,
        duration=duration,
        error_log=json.dumps(errors[:100]) if errors else None
    )

    # Send notification if configured
    if doc.notify_on_complete and doc.notification_email:
        try:
            frappe.sendmail(
                recipients=[doc.notification_email],
                subject=_("PIM Import Complete: {0}").format(doc.config_name),
                message=_(
                    "Import completed with status: {0}\n"
                    "Records imported: {1}\n"
                    "Records updated: {2}\n"
                    "Records skipped: {3}\n"
                    "Errors: {4}"
                ).format(status, records_imported, records_updated, records_skipped, len(errors))
            )
        except Exception:
            pass

    return {
        "success": status != "Failed",
        "status": status,
        "records_imported": records_imported,
        "records_updated": records_updated,
        "records_skipped": records_skipped,
        "errors": errors[:100],
        "duration": duration
    }


def apply_transformation(value: Any, mapping: Dict[str, Any]) -> Any:
    """Apply transformation to a value based on mapping configuration

    Args:
        value: The value to transform
        mapping: The field mapping configuration

    Returns:
        Transformed value
    """
    transformation = mapping.get("transformation", "None")

    if transformation == "None" or not transformation:
        return value

    if transformation == "Uppercase":
        return str(value).upper()

    elif transformation == "Lowercase":
        return str(value).lower()

    elif transformation == "Trim":
        return str(value).strip()

    elif transformation == "Slugify":
        return frappe.scrub(str(value))

    elif transformation == "Number Format":
        try:
            config = json.loads(mapping.get("transformation_config") or "{}")
            decimal_places = config.get("decimal_places", 2)
            return round(float(value), decimal_places)
        except (ValueError, TypeError):
            return value

    elif transformation == "Date Parse":
        try:
            config = json.loads(mapping.get("transformation_config") or "{}")
            input_format = config.get("input_format", "%Y-%m-%d")
            from datetime import datetime
            return datetime.strptime(str(value), input_format).date()
        except (ValueError, TypeError):
            return value

    elif transformation == "Boolean Parse":
        true_values = ["true", "yes", "1", "y", "t"]
        return str(value).lower() in true_values

    elif transformation == "JSON Parse":
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value

    elif transformation == "Split to Array":
        config = json.loads(mapping.get("transformation_config") or "{}")
        delimiter = config.get("delimiter", ",")
        return [item.strip() for item in str(value).split(delimiter)]

    elif transformation == "Custom Script":
        config = json.loads(mapping.get("transformation_config") or "{}")
        script = config.get("script", "")
        if script:
            exec_globals = {"value": value, "frappe": frappe}
            exec(script, exec_globals)
            return exec_globals.get("result", value)

    return value


@frappe.whitelist()
def get_target_fields(target_doctype: str) -> List[Dict[str, Any]]:
    """Get available fields for a target DocType

    Args:
        target_doctype: The DocType to get fields for

    Returns:
        List of field definitions
    """
    meta = frappe.get_meta(target_doctype)

    fields = []
    for field in meta.fields:
        if field.fieldtype not in ["Section Break", "Column Break", "Tab Break", "HTML"]:
            fields.append({
                "fieldname": field.fieldname,
                "label": field.label,
                "fieldtype": field.fieldtype,
                "reqd": field.reqd,
                "options": field.options
            })

    return fields


@frappe.whitelist()
def duplicate_configuration(
    config_name: str,
    new_name: str
) -> Dict[str, Any]:
    """Duplicate an import configuration

    Args:
        config_name: Source configuration name
        new_name: Name for the new configuration

    Returns:
        New configuration details
    """
    source = frappe.get_doc("Import Configuration", config_name)

    new_doc = frappe.copy_doc(source)
    new_doc.config_name = frappe.scrub(new_name).replace("-", "_")

    # Reset statistics
    new_doc.total_imports = 0
    new_doc.total_records_imported = 0
    new_doc.total_records_updated = 0
    new_doc.total_records_skipped = 0
    new_doc.total_errors = 0
    new_doc.last_import_at = None
    new_doc.last_import_status = None
    new_doc.last_import_file = None
    new_doc.last_error_log = None

    new_doc.insert()

    return {
        "success": True,
        "name": new_doc.name,
        "config_name": new_doc.config_name
    }


@frappe.whitelist()
def get_import_statistics() -> Dict[str, Any]:
    """Get aggregated import statistics across all configurations

    Returns:
        Aggregated statistics
    """
    stats = frappe.db.sql("""
        SELECT
            COUNT(*) as total_configs,
            SUM(CASE WHEN enabled = 1 THEN 1 ELSE 0 END) as enabled_configs,
            SUM(total_imports) as total_imports,
            SUM(total_records_imported) as total_records_imported,
            SUM(total_records_updated) as total_records_updated,
            SUM(total_records_skipped) as total_records_skipped,
            SUM(total_errors) as total_errors
        FROM `tabImport Configuration`
    """, as_dict=True)[0]

    # Get recent imports
    recent = frappe.get_all(
        "Import Configuration",
        filters={"last_import_at": ["is", "set"]},
        fields=["config_name", "last_import_at", "last_import_status", "last_import_records"],
        order_by="last_import_at desc",
        limit=10
    )

    # Get imports by target doctype
    by_doctype = frappe.db.sql("""
        SELECT
            target_doctype,
            COUNT(*) as config_count,
            SUM(total_records_imported) as records_imported
        FROM `tabImport Configuration`
        GROUP BY target_doctype
    """, as_dict=True)

    return {
        "summary": stats,
        "recent_imports": recent,
        "by_target_doctype": by_doctype
    }
