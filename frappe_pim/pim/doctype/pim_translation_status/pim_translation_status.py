"""
PIM Translation Status Controller
Track translation completeness for translatable PIM fields
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime
import hashlib


class PIMTranslationStatus(Document):
    def validate(self):
        self.validate_unique_combination()
        self.validate_source_document()
        self.update_source_hash()

    def validate_unique_combination(self):
        """Ensure unique combination of source_doctype, source_name, language, field_name"""
        existing = frappe.db.exists(
            "PIM Translation Status",
            {
                "source_doctype": self.source_doctype,
                "source_name": self.source_name,
                "language": self.language,
                "field_name": self.field_name,
                "name": ["!=", self.name or ""]
            }
        )
        if existing:
            frappe.throw(
                _("Translation status already exists for {0} {1}, field '{2}' in language {3}").format(
                    self.source_doctype, self.source_name, self.field_name, self.language
                ),
                title=_("Duplicate Translation Status")
            )

    def validate_source_document(self):
        """Validate that source document exists and has the specified field"""
        meta = frappe.get_meta(self.source_doctype)
        
        # Check if field exists in the DocType first
        if not meta.has_field(self.field_name):
            frappe.throw(
            _("Field '{0}' does not exist in DocType '{1}'").format(
                self.field_name, self.source_doctype
            ),
            title=_("Invalid Field Name")
        )
        
        # For Virtual DocTypes, skip the exists check as they don't have db tables
        # Virtual DocTypes handle their own data storage
        if meta.is_virtual:
            # Try to get the document to validate it exists
            try:
                frappe.get_doc(self.source_doctype, self.source_name)
            except frappe.DoesNotExistError:
                frappe.throw(
                    _("Source document {0} {1} does not exist").format(
                        self.source_doctype, self.source_name
                    ),
                    title=_("Invalid Source Document")
                )
        else:
            # Standard DocType - use db.exists
            if not frappe.db.exists(self.source_doctype, self.source_name):
                frappe.throw(
                    _("Source document {0} {1} does not exist").format(
                        self.source_doctype, self.source_name
                    ),
                    title=_("Invalid Source Document")
                )

    def update_source_hash(self):
        """Update hash of source value for change detection"""
        if self.source_value:
            new_hash = hashlib.md5(self.source_value.encode()).hexdigest()
            if self.source_hash and self.source_hash != new_hash:
                # Source has changed, mark for update
                self.needs_update = 1
            self.source_hash = new_hash

    def before_save(self):
        """Before save hook"""
        # Update translation_modified when translated_value changes
        if self.has_value_changed("translated_value"):
            self.translation_modified = now_datetime()
            self.translated_by = frappe.session.user

        # Update is_translated status
        if self.translated_value and not self.is_translated:
            self.is_translated = 1

        # Calculate translation score
        self.calculate_translation_score()

        # Update source_modified if source_value changed
        if self.has_value_changed("source_value"):
            self.source_modified = now_datetime()

    def calculate_translation_score(self):
        """Calculate translation quality/completeness score"""
        score = 0

        if self.translated_value:
            score += 50  # Has translation

            # Length comparison (translation shouldn't be dramatically different)
            if self.source_value:
                source_len = len(self.source_value)
                trans_len = len(self.translated_value)
                if source_len > 0:
                    ratio = trans_len / source_len
                    # Good if ratio is between 0.5 and 2.0
                    if 0.5 <= ratio <= 2.0:
                        score += 20

            # Status-based scoring
            if self.translation_status == "Approved":
                score += 30
            elif self.translation_status == "Translated":
                score += 20
            elif self.translation_status == "Needs Review":
                score += 10

            # Penalize if needs update
            if self.needs_update:
                score -= 20

        self.translation_score = max(0, min(100, score))

    def on_update(self):
        """After update - sync with Frappe Translation if configured"""
        if self.use_frappe_translation and self.is_translated:
            self.sync_to_frappe_translation()
        self.invalidate_cache()

    def on_trash(self):
        """Before delete - cleanup"""
        self.invalidate_cache()

    def invalidate_cache(self):
        """Invalidate related caches"""
        frappe.cache().delete_key(f"pim_translation_status_{self.source_doctype}_{self.source_name}")
        frappe.cache().delete_key(f"pim_translation_completeness_{self.source_doctype}_{self.source_name}")

    def sync_to_frappe_translation(self):
        """Sync to Frappe's built-in Translation system"""
        if not self.source_value or not self.translated_value:
            return

        try:
            # Check if translation exists
            existing = frappe.db.get_value(
                "Translation",
                {
                    "source_text": self.source_value,
                    "language": self.language
                },
                "name"
            )

            if existing:
                # Update existing
                frappe.db.set_value(
                    "Translation", existing,
                    "translated_text", self.translated_value,
                    update_modified=True
                )
                self.db_set("frappe_translation_name", existing, update_modified=False)
            else:
                # Create new
                trans_doc = frappe.new_doc("Translation")
                trans_doc.source_text = self.source_value
                trans_doc.translated_text = self.translated_value
                trans_doc.language = self.language
                trans_doc.insert(ignore_permissions=True)
                self.db_set("frappe_translation_name", trans_doc.name, update_modified=False)

            self.db_set("last_synced", now_datetime(), update_modified=False)

        except Exception as e:
            frappe.log_error(
                title="Translation Sync Failed",
                message=f"Failed to sync translation {self.name}: {str(e)}"
            )

    def mark_as_translated(self, translated_value, method="Manual"):
        """Mark this field as translated

        Args:
            translated_value: The translated content
            method: Translation method (Manual, Machine Translation, etc.)
        """
        self.translated_value = translated_value
        self.translation_method = method
        self.translation_status = "Translated"
        self.is_translated = 1
        self.needs_update = 0
        self.translation_modified = now_datetime()
        self.translated_by = frappe.session.user
        self.save(ignore_permissions=True)

    def mark_for_review(self, reviewer=None, notes=None):
        """Mark translation for review

        Args:
            reviewer: User to assign review to
            notes: Review notes
        """
        self.translation_status = "Needs Review"
        if notes:
            self.review_notes = notes
        self.save(ignore_permissions=True)

    def approve_translation(self, notes=None):
        """Approve the translation"""
        self.translation_status = "Approved"
        self.reviewed_by = frappe.session.user
        self.review_date = now_datetime()
        if notes:
            self.review_notes = notes
        self.save(ignore_permissions=True)

    def reject_translation(self, notes=None):
        """Reject the translation"""
        self.translation_status = "Rejected"
        self.reviewed_by = frappe.session.user
        self.review_date = now_datetime()
        if notes:
            self.review_notes = notes
        self.save(ignore_permissions=True)

    def refresh_source_value(self):
        """Refresh source value from the source document"""
        source_doc = frappe.get_doc(self.source_doctype, self.source_name)
        current_value = source_doc.get(self.field_name) or ""

        if current_value != self.source_value:
            old_hash = self.source_hash
            self.source_value = current_value
            self.source_modified = now_datetime()
            self.update_source_hash()

            if old_hash and old_hash != self.source_hash:
                self.needs_update = 1
                self.translation_status = "Needs Review"

            self.save(ignore_permissions=True)
            return True

        return False


# Module-level helper functions

def get_translation_status(source_doctype, source_name, language=None, field_name=None):
    """Get translation status for a document

    Args:
        source_doctype: DocType of source document
        source_name: Name of source document
        language: Optional language filter
        field_name: Optional field name filter

    Returns:
        List of PIM Translation Status documents
    """
    filters = {
        "source_doctype": source_doctype,
        "source_name": source_name
    }

    if language:
        filters["language"] = language
    if field_name:
        filters["field_name"] = field_name

    statuses = frappe.get_all(
        "PIM Translation Status",
        filters=filters,
        fields=["name", "field_name", "language", "is_translated",
            "translation_status", "translation_score", "needs_update"],
        order_by="field_name, language"
    )

    return statuses


    def get_translation_completeness(source_doctype, source_name, languages=None):
        """Calculate translation completeness for a document

    Args:
        source_doctype: DocType of source document
        source_name: Name of source document
        languages: List of languages to check (or all if None)

    Returns:
        dict with completeness data per language
    """
    # Get all translation statuses for this document
    filters = {
        "source_doctype": source_doctype,
        "source_name": source_name
    }

    if languages:
        filters["language"] = ["in", languages]

    statuses = frappe.get_all(
        "PIM Translation Status",
        filters=filters,
        fields=["language", "field_name", "is_translated", "translation_score", "needs_update"]
    )

    # Group by language
    completeness = {}
    for status in statuses:
        lang = status.language
        if lang not in completeness:
            completeness[lang] = {
            "total_fields": 0,
            "translated_fields": 0,
            "fields_needing_update": 0,
            "average_score": 0,
            "completeness_percent": 0
        }

        completeness[lang]["total_fields"] += 1
        if status.is_translated:
            completeness[lang]["translated_fields"] += 1
        if status.needs_update:
            completeness[lang]["fields_needing_update"] += 1

    # Calculate percentages and averages
    for lang, data in completeness.items():
        if data["total_fields"] > 0:
            data["completeness_percent"] = (data["translated_fields"] / data["total_fields"]) * 100

        # Get average score
        avg_score = frappe.db.sql("""
            SELECT AVG(translation_score) as avg
            FROM `tabPIM Translation Status`
            WHERE source_doctype = %s AND source_name = %s AND language = %s
        """, (source_doctype, source_name, lang))
        data["average_score"] = float(avg_score[0][0] or 0) if avg_score else 0

    return completeness


    def create_translation_status(source_doctype, source_name, field_name, language,
                           source_value=None, translated_value=None):
                               """Create a translation status record

    Args:
        source_doctype: DocType of source document
        source_name: Name of source document
        field_name: Name of the translatable field
        language: Target language code
        source_value: Optional source text
        translated_value: Optional translated text

    Returns:
        PIM Translation Status document
    """
    # Check if already exists
    existing = frappe.db.exists(
        "PIM Translation Status",
        {
        "source_doctype": source_doctype,
        "source_name": source_name,
        "field_name": field_name,
        "language": language
        }
    )

    if existing:
        return frappe.get_doc("PIM Translation Status", existing)

    # Get source value if not provided
    if not source_value:
        source_doc = frappe.get_doc(source_doctype, source_name)
        source_value = source_doc.get(field_name) or ""

    doc = frappe.new_doc("PIM Translation Status")
    doc.source_doctype = source_doctype
    doc.source_name = source_name
    doc.field_name = field_name
    doc.language = language
    doc.source_value = source_value

    if translated_value:
        doc.translated_value = translated_value
        doc.is_translated = 1
        doc.translation_status = "Translated"

    doc.insert(ignore_permissions=True)
    return doc


    def bulk_create_translation_status(source_doctype, source_name, fields, languages):
        """Bulk create translation status records for multiple fields and languages

    Args:
        source_doctype: DocType of source document
        source_name: Name of source document
        fields: List of field names to track
        languages: List of language codes

    Returns:
        List of created PIM Translation Status names
    """
    created = []
    source_doc = frappe.get_doc(source_doctype, source_name)

    for field_name in fields:
        source_value = source_doc.get(field_name) or ""

        for language in languages:
            # Check if already exists
            existing = frappe.db.exists(
            "PIM Translation Status",
            {
                "source_doctype": source_doctype,
                "source_name": source_name,
                "field_name": field_name,
                "language": language
            }
        )

        if not existing:
            doc = frappe.new_doc("PIM Translation Status")
            doc.source_doctype = source_doctype
            doc.source_name = source_name
            doc.field_name = field_name
            doc.language = language
            doc.source_value = source_value
            doc.insert(ignore_permissions=True)
            created.append(doc.name)

    if created:
        frappe.db.commit()

    return created


    def get_pending_translations(language=None, source_doctype=None, limit=50):
        """Get pending translation entries

    Args:
        language: Optional language filter
        source_doctype: Optional DocType filter
        limit: Maximum number of results

    Returns:
        List of pending translation statuses
    """
    filters = {
        "is_translated": 0
    }

    if language:
        filters["language"] = language
    if source_doctype:
        filters["source_doctype"] = source_doctype

    return frappe.get_all(
        "PIM Translation Status",
        filters=filters,
        fields=["name", "source_doctype", "source_name", "field_name",
            "language", "source_value", "translation_status"],
        order_by="creation asc",
        limit=limit
    )


    def get_translations_needing_update(language=None, source_doctype=None, limit=50):
        """Get translations that need updating due to source changes

    Args:
        language: Optional language filter
        source_doctype: Optional DocType filter
        limit: Maximum number of results

    Returns:
        List of translation statuses needing update
    """
    filters = {
        "needs_update": 1,
        "is_translated": 1
    }

    if language:
        filters["language"] = language
    if source_doctype:
        filters["source_doctype"] = source_doctype

    return frappe.get_all(
        "PIM Translation Status",
        filters=filters,
        fields=["name", "source_doctype", "source_name", "field_name",
            "language", "source_value", "translated_value",
            "translation_status"],
        order_by="source_modified desc",
        limit=limit
    )


    def get_translation_stats(source_doctype=None):
        """Get translation statistics

    Args:
        source_doctype: Optional DocType filter

    Returns:
        dict with translation statistics
    """
    doctype_filter = ""
    if source_doctype:
        doctype_filter = f"AND source_doctype = '{source_doctype}'"

    stats = {
        "total_entries": 0,
        "translated": 0,
        "pending": 0,
        "needs_update": 0,
        "by_language": {},
        "by_status": {},
        "average_score": 0
    }

    # Total counts
    total = frappe.db.sql(f"""
        SELECT
        COUNT(*) as total,
        SUM(CASE WHEN is_translated = 1 THEN 1 ELSE 0 END) as translated,
        SUM(CASE WHEN is_translated = 0 THEN 1 ELSE 0 END) as pending,
        SUM(CASE WHEN needs_update = 1 THEN 1 ELSE 0 END) as needs_update,
        AVG(translation_score) as avg_score
        FROM `tabPIM Translation Status`
        WHERE 1=1 {doctype_filter}
    """, as_dict=True)

    if total:
        stats["total_entries"] = int(total[0].total or 0)
        stats["translated"] = int(total[0].translated or 0)
        stats["pending"] = int(total[0].pending or 0)
        stats["needs_update"] = int(total[0].needs_update or 0)
        stats["average_score"] = float(total[0].avg_score or 0)

    # By language
    by_lang = frappe.db.sql(f"""
        SELECT
        language,
        COUNT(*) as total,
        SUM(CASE WHEN is_translated = 1 THEN 1 ELSE 0 END) as translated
        FROM `tabPIM Translation Status`
        WHERE 1=1 {doctype_filter}
        GROUP BY language
    """, as_dict=True)

    for row in by_lang:
        stats["by_language"][row.language] = {
        "total": int(row.total),
        "translated": int(row.translated),
        "percent": (int(row.translated) / int(row.total) * 100) if row.total else 0
        }

    # By status
    by_status = frappe.db.sql(f"""
        SELECT
        translation_status,
        COUNT(*) as count
        FROM `tabPIM Translation Status`
        WHERE 1=1 {doctype_filter}
        GROUP BY translation_status
    """, as_dict=True)

    stats["by_status"] = {row.translation_status: int(row["count"]) for row in by_status}

    return stats


    def get_translatable_fields(doctype_name):
        """Get list of translatable fields for a DocType

    Args:
        doctype_name: Name of the DocType

    Returns:
        List of field names that are translatable (Data, Text, Long Text, etc.)
    """
    meta = frappe.get_meta(doctype_name)
    translatable_types = ["Data", "Text", "Small Text", "Long Text", "Text Editor"]

    fields = []
    for field in meta.fields:
        if field.fieldtype in translatable_types:
            # Skip system fields
            if field.fieldname not in ["name", "owner", "modified_by"]:
                fields.append(field.fieldname)

    return fields


    def sync_all_to_frappe_translation(language=None):
        """Sync all approved translations to Frappe's built-in Translation system

    Args:
        language: Optional language filter

    Returns:
        Number of translations synced
    """
    filters = {
        "is_translated": 1,
        "translation_status": "Approved",
        "use_frappe_translation": 1
    }

    if language:
        filters["language"] = language

    statuses = frappe.get_all(
        "PIM Translation Status",
        filters=filters,
        fields=["name"]
    )

    synced = 0
    for status in statuses:
        try:
            doc = frappe.get_doc("PIM Translation Status", status.name)
            doc.sync_to_frappe_translation()
            synced += 1
        except Exception:
            pass

    return synced

    return synced
