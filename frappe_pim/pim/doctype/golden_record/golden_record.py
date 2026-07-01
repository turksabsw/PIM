"""
Golden Record Controller
Manages canonical/master product data with survivorship rules for MDM governance.

Golden Records represent the "single source of truth" for product data in an MDM context.
They aggregate data from multiple source records (duplicates, imports, external systems)
and apply survivorship rules to determine the winning values for each field.

Survivorship Rules:
- Most Recent: Take value from most recently updated source
- Highest Confidence: Take value with highest confidence score
- Source Priority: Follow configured source system priority order
- Manual Override: Require manual selection of values
- Most Complete: Take value from source with most populated fields
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, cint, flt, cstr
import json


class GoldenRecord(Document):
    """Golden Record - Master data record with survivorship rules for MDM governance."""

    def validate(self):
        """Validate the golden record before saving."""
        self.validate_golden_record_code()
        self.validate_source_priority()
        self.validate_auto_merge_threshold()

    def validate_golden_record_code(self):
        """Generate golden record code if not provided."""
        if not self.golden_record_code:
            # Auto-generate code based on product_master or sequence
            if self.product_master:
                self.golden_record_code = f"GR-{self.product_master}"
            else:
                # Generate sequence-based code
                current = frappe.db.sql("""
                    SELECT MAX(CAST(SUBSTRING(golden_record_code, 4) AS UNSIGNED))
                    FROM `tabGolden Record`
                    WHERE golden_record_code LIKE 'GR-%'
                """)
                next_num = (current[0][0] or 0) + 1 if current and current[0][0] else 1
                self.golden_record_code = f"GR-{next_num:06d}"

    def validate_source_priority(self):
        """Validate source priority order when survivorship rule is Source Priority."""
        if self.survivorship_rule == "Source Priority" and not self.source_priority_order:
            frappe.throw(
                _("Source Priority Order is required when Survivorship Rule is 'Source Priority'"),
                title=_("Missing Source Priority")
            )

    def validate_auto_merge_threshold(self):
        """Validate auto-merge threshold is within valid range."""
        if self.merge_mode == "Automatic":
            threshold = flt(self.auto_merge_threshold)
            if threshold < 0 or threshold > 100:
                frappe.throw(
                    _("Auto-Merge Confidence Threshold must be between 0 and 100"),
                    title=_("Invalid Threshold")
                )

    def before_save(self):
        """Actions before saving the record."""
        # Track data steward assignment
        if self.has_value_changed("data_steward"):
            self.steward_assigned_at = now_datetime()

    def on_update(self):
        """Actions after the record is saved."""
        self.update_quality_metrics()

    def update_quality_metrics(self):
        """Calculate and update data quality metrics."""
        # Calculate data completeness
        completeness = self.calculate_completeness()

        # Calculate overall confidence
        confidence = self.calculate_confidence()

        # Identify quality issues
        issues = self.identify_quality_issues()

        # Update without triggering events
        frappe.db.set_value(
            "Golden Record",
            self.name,
            {
                "data_completeness": completeness,
                "confidence_score": confidence,
                "quality_issues": "; ".join(issues) if issues else None
            },
            update_modified=False
        )

    def calculate_completeness(self):
        """Calculate data completeness percentage.

        Returns:
            float: Completeness percentage (0-100)
        """
        required_fields = [
            "record_name",
            "golden_record_code",
            "product_master",
            "survivorship_rule",
            "data_steward"
        ]

        filled = sum(1 for f in required_fields if self.get(f))
        return (filled / len(required_fields)) * 100 if required_fields else 0

    def calculate_confidence(self):
        """Calculate overall confidence score based on source records.

        Returns:
            float: Confidence score (0-100)
        """
        if not self.source_records:
            return 0

        # Average confidence from source records
        total_confidence = 0
        count = 0

        for source in self.source_records:
            if source.confidence_score:
                total_confidence += flt(source.confidence_score)
                count += 1

        return total_confidence / count if count > 0 else 0

    def identify_quality_issues(self):
        """Identify data quality issues with the golden record.

        Returns:
            list: List of quality issue descriptions
        """
        issues = []

        if not self.product_master:
            issues.append("No product master linked")

        if not self.data_steward:
            issues.append("No data steward assigned")

        if not self.source_records or len(self.source_records) == 0:
            issues.append("No source records defined")

        if self.merge_mode == "Automatic" and flt(self.auto_merge_threshold) < 80:
            issues.append("Low auto-merge threshold may cause data quality issues")

        if self.validation_status == "Invalid":
            issues.append("Record failed validation")

        return issues

    # ─────────────────────────────────────────────────────────────────────
    # Merge Operations
    # ─────────────────────────────────────────────────────────────────────

    def merge_source_record(self, source_product, source_system=None, confidence=None):
        """Merge a source record into this golden record.

        Args:
            source_product: Product Master name or dict with product data
            source_system: Name of the source system (e.g., 'ERP', 'Import', 'PIM')
            confidence: Confidence score for this source (0-100)

        Returns:
            dict: Result of the merge operation
        """
        if isinstance(source_product, str):
            product_name = source_product
        else:
            product_name = source_product.get("name") or source_product.get("product_code")

        # Check if source already exists
        existing = None
        for row in self.source_records:
            if row.source_product == product_name:
                existing = row
                break

        if existing:
            # Update existing source
            existing.source_system = source_system or existing.source_system
            existing.confidence_score = confidence or existing.confidence_score
            existing.last_synced_at = now_datetime()
        else:
            # Add new source
            self.append("source_records", {
                "source_product": product_name,
                "source_system": source_system or "Manual",
                "confidence_score": confidence or 50,
                "is_primary": len(self.source_records) == 0,
                "added_at": now_datetime(),
                "last_synced_at": now_datetime()
            })

        # Update merge tracking
        self.merge_count = cint(self.merge_count) + 1
        self.last_merged_at = now_datetime()

        # Apply survivorship rules to update field sources
        self.apply_survivorship_rules()

        self.save()

        return {
            "status": "success",
            "message": _("Source record merged successfully"),
            "golden_record": self.name,
            "source_product": product_name
        }

    def apply_survivorship_rules(self):
        """Apply survivorship rules to determine winning field values.

        Based on the configured survivorship_rule, determines which source
        record should provide each field value.
        """
        if not self.source_records:
            return

        rule = self.survivorship_rule
        field_sources = {}
        field_confidence = {}

        if rule == "Most Recent":
            # Sort by last_synced_at, take most recent
            primary = self._get_most_recent_source()
        elif rule == "Highest Confidence":
            # Sort by confidence_score, take highest
            primary = self._get_highest_confidence_source()
        elif rule == "Source Priority":
            # Follow source priority order
            primary = self._get_priority_source()
        elif rule == "Most Complete":
            # Source with most complete data
            primary = self._get_most_complete_source()
        else:
            # Manual Override - use primary source
            primary = self._get_primary_source()

        if primary:
            # Mark the winning source
            for row in self.source_records:
                row.is_winning = (row.source_product == primary.source_product)

            # Track which source provides the main record data
            field_sources["_primary"] = primary.source_product
            field_confidence["_primary"] = primary.confidence_score

        # Store field-level tracking as JSON
        self.field_sources = json.dumps(field_sources)
        self.field_confidence = json.dumps(field_confidence)

    def _get_most_recent_source(self):
        """Get the most recently updated source record."""
        sorted_sources = sorted(
            self.source_records,
            key=lambda x: x.last_synced_at or x.added_at or "",
            reverse=True
        )
        return sorted_sources[0] if sorted_sources else None

    def _get_highest_confidence_source(self):
        """Get the source with highest confidence score."""
        sorted_sources = sorted(
            self.source_records,
            key=lambda x: flt(x.confidence_score),
            reverse=True
        )
        return sorted_sources[0] if sorted_sources else None

    def _get_priority_source(self):
        """Get the source based on priority order."""
        if not self.source_priority_order:
            return self._get_primary_source()

        priority_list = [s.strip() for s in self.source_priority_order.split(",")]

        for priority_system in priority_list:
            for source in self.source_records:
                if source.source_system == priority_system:
                    return source

        # Fallback to primary source
        return self._get_primary_source()

    def _get_most_complete_source(self):
        """Get the source with most complete data.

        Note: In a full implementation, this would query the actual
        source product records to compare completeness.
        """
        # For now, use confidence as a proxy for completeness
        return self._get_highest_confidence_source()

    def _get_primary_source(self):
        """Get the designated primary source record."""
        for source in self.source_records:
            if source.is_primary:
                return source
        # Fallback to first source
        return self.source_records[0] if self.source_records else None

    # ─────────────────────────────────────────────────────────────────────
    # Validation Operations
    # ─────────────────────────────────────────────────────────────────────

    def validate_record(self):
        """Validate the golden record and update validation status.

        Returns:
            dict: Validation result with status and any issues found
        """
        issues = []

        # Check for linked product master
        if self.product_master:
            if not frappe.db.exists("Product Master", self.product_master):
                issues.append(_("Linked Product Master does not exist"))

        # Check source records validity
        for source in self.source_records:
            if source.source_product:
                if not frappe.db.exists("Product Master", source.source_product):
                    issues.append(_("Source product {0} does not exist").format(
                        source.source_product
                    ))

        # Check data steward validity
        if self.data_steward:
            if not frappe.db.exists("User", self.data_steward):
                issues.append(_("Data steward {0} is not a valid user").format(
                    self.data_steward
                ))

        # Update validation status
        if issues:
            self.validation_status = "Invalid"
        else:
            self.validation_status = "Valid"

        self.last_validated_at = now_datetime()
        self.save()

        return {
            "status": "valid" if not issues else "invalid",
            "issues": issues,
            "validated_at": cstr(self.last_validated_at)
        }

    # ─────────────────────────────────────────────────────────────────────
    # Approval Workflow
    # ─────────────────────────────────────────────────────────────────────

    def approve(self, user=None):
        """Approve the golden record.

        Args:
            user: User who is approving (defaults to current user)

        Returns:
            dict: Approval result
        """
        if self.status != "Active":
            # First validate
            validation = self.validate_record()
            if validation["status"] != "valid":
                frappe.throw(
                    _("Cannot approve: Record has validation issues - {0}").format(
                        ", ".join(validation["issues"])
                    ),
                    title=_("Validation Failed")
                )

        self.approved_by = user or frappe.session.user
        self.approved_at = now_datetime()
        self.status = "Active"
        self.save()

        return {
            "status": "success",
            "message": _("Golden Record approved"),
            "approved_by": self.approved_by,
            "approved_at": cstr(self.approved_at)
        }

    def archive(self, reason=None):
        """Archive the golden record.

        Args:
            reason: Optional reason for archiving

        Returns:
            dict: Archive result
        """
        self.status = "Archived"
        if reason:
            current_notes = self.notes or ""
            self.notes = f"{current_notes}\n\nArchived on {now_datetime()}: {reason}".strip()
        self.save()

        return {
            "status": "success",
            "message": _("Golden Record archived")
        }


# ─────────────────────────────────────────────────────────────────────────
# API Functions
# ─────────────────────────────────────────────────────────────────────────

@frappe.whitelist()
def merge_product_into_golden_record(golden_record, source_product, source_system=None, confidence=None):
    """Merge a product into an existing golden record.

    Args:
        golden_record: Golden Record name
        source_product: Product Master name to merge
        source_system: Name of the source system
        confidence: Confidence score (0-100)

    Returns:
        dict: Merge result
    """
    doc = frappe.get_doc("Golden Record", golden_record)
    return doc.merge_source_record(
        source_product,
        source_system=source_system,
        confidence=flt(confidence) if confidence else None
    )


@frappe.whitelist()
def create_golden_record_from_product(product_name, record_name=None, survivorship_rule="Most Recent"):
    """Create a new golden record from a product master.

    Args:
        product_name: Product Master name to use as the canonical product
        record_name: Optional display name for the golden record
        survivorship_rule: Survivorship rule to apply

    Returns:
        dict: Created golden record details
    """
    product = frappe.get_doc("Product Master", product_name)

    gr = frappe.new_doc("Golden Record")
    gr.record_name = record_name or product.product_name
    gr.product_master = product_name
    gr.survivorship_rule = survivorship_rule
    gr.status = "Draft"

    # Add the product as the primary source
    gr.append("source_records", {
        "source_product": product_name,
        "source_system": "PIM",
        "confidence_score": 100,
        "is_primary": 1,
        "added_at": now_datetime(),
        "last_synced_at": now_datetime()
    })

    gr.insert()

    return {
        "status": "success",
        "golden_record": gr.name,
        "golden_record_code": gr.golden_record_code,
        "message": _("Golden Record created successfully")
    }


@frappe.whitelist()
def validate_golden_record(golden_record):
    """Validate a golden record.

    Args:
        golden_record: Golden Record name

    Returns:
        dict: Validation result
    """
    doc = frappe.get_doc("Golden Record", golden_record)
    return doc.validate_record()


@frappe.whitelist()
def approve_golden_record(golden_record):
    """Approve a golden record.

    Args:
        golden_record: Golden Record name

    Returns:
        dict: Approval result
    """
    doc = frappe.get_doc("Golden Record", golden_record)
    return doc.approve()


@frappe.whitelist()
def get_golden_record_for_product(product_name):
    """Get the golden record linked to a product.

    Args:
        product_name: Product Master name

    Returns:
        dict or None: Golden record details if found
    """
    golden_records = frappe.get_all(
        "Golden Record",
        filters={"product_master": product_name},
        fields=["name", "golden_record_code", "record_name", "status", "confidence_score"]
    )

    if golden_records:
        return golden_records[0]

    # Also check source records
    source_records = frappe.get_all(
        "Golden Record Source",
        filters={"source_product": product_name},
        fields=["parent"]
    )

    if source_records:
        gr_name = source_records[0].parent
        return frappe.get_doc("Golden Record", gr_name).as_dict()

    return None


@frappe.whitelist()
def find_potential_duplicates(product_name, threshold=80):
    """Find potential duplicate products that could be merged.

    Args:
        product_name: Product Master name to find duplicates for
        threshold: Minimum similarity threshold (0-100)

    Returns:
        list: List of potential duplicate products
    """
    product = frappe.get_doc("Product Master", product_name)

    # Simple duplicate detection based on name similarity
    # In a full implementation, this would use more sophisticated matching
    all_products = frappe.get_all(
        "Product Master",
        filters={"name": ["!=", product_name]},
        fields=["name", "product_name", "product_code", "brand"]
    )

    duplicates = []
    for p in all_products:
        # Basic similarity check
        similarity = _calculate_similarity(
            product.product_name.lower(),
            p.product_name.lower()
        )

        if similarity >= threshold:
            duplicates.append({
                "product": p.name,
                "product_name": p.product_name,
                "product_code": p.product_code,
                "brand": p.brand,
                "similarity_score": similarity
            })

    # Sort by similarity
    duplicates.sort(key=lambda x: x["similarity_score"], reverse=True)

    return duplicates


def _calculate_similarity(str1, str2):
    """Calculate simple similarity between two strings.

    Uses Jaccard similarity on word sets.

    Args:
        str1: First string
        str2: Second string

    Returns:
        float: Similarity score (0-100)
    """
    if not str1 or not str2:
        return 0

    words1 = set(str1.split())
    words2 = set(str2.split())

    if not words1 or not words2:
        return 0

    intersection = len(words1 & words2)
    union = len(words1 | words2)

    return (intersection / union) * 100 if union > 0 else 0
