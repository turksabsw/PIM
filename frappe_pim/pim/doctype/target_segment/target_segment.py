# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class TargetSegment(Document):
    """Target Segment DocType for market segment definitions.

    Used to define demographics, interests, geographic, behavioral, and other
    market segmentation criteria for product targeting.
    """

    def validate(self):
        """Validate segment data before saving."""
        self.validate_segment_code()
        self.validate_parent_segment()
        self.validate_age_range()
        self.validate_market_metrics()

    def validate_segment_code(self):
        """Validate segment_code format.

        Ensures the segment code follows slug conventions:
        - Lowercase letters, numbers, and hyphens only
        - No spaces or special characters
        """
        if self.segment_code:
            import re
            # Allow alphanumeric and hyphens
            if not re.match(r'^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$', self.segment_code.lower()):
                frappe.throw(
                    _("Segment Code should contain only lowercase letters, numbers, and hyphens. "
                      "It should not start or end with a hyphen.")
                )
            # Normalize to lowercase
            self.segment_code = self.segment_code.lower()

    def validate_parent_segment(self):
        """Validate parent segment to prevent circular references."""
        if self.parent_segment:
            # Cannot be its own parent
            if self.parent_segment == self.name:
                frappe.throw(_("A segment cannot be its own parent"))

            # Check for circular reference
            visited = set()
            current = self.parent_segment

            while current:
                if current in visited:
                    frappe.throw(_("Circular reference detected in segment hierarchy"))
                visited.add(current)

                parent_doc = frappe.db.get_value(
                    "Target Segment",
                    current,
                    "parent_segment"
                )

                if parent_doc == self.name:
                    frappe.throw(_("Circular reference detected: this segment appears in the parent chain"))

                current = parent_doc

    def validate_age_range(self):
        """Validate age range values for demographic segments."""
        if self.segment_type == "Demographics":
            if self.age_range_start and self.age_range_end:
                if self.age_range_start < 0:
                    frappe.throw(_("Age Range Start cannot be negative"))
                if self.age_range_end < 0:
                    frappe.throw(_("Age Range End cannot be negative"))
                if self.age_range_start > self.age_range_end:
                    frappe.throw(_("Age Range Start cannot be greater than Age Range End"))
                if self.age_range_end > 120:
                    frappe.msgprint(_("Age Range End seems unusually high"), indicator="orange")

    def validate_market_metrics(self):
        """Validate market size and potential metrics."""
        if self.estimated_size and self.estimated_size < 0:
            frappe.throw(_("Estimated Segment Size cannot be negative"))

        if self.market_potential and self.market_potential < 0:
            frappe.throw(_("Market Potential cannot be negative"))

        if self.growth_rate:
            if self.growth_rate < -100:
                frappe.throw(_("Growth Rate cannot be less than -100%"))
            if self.growth_rate > 1000:
                frappe.msgprint(
                    _("Growth Rate of {0}% seems unusually high").format(self.growth_rate),
                    indicator="orange"
                )

        if self.penetration_rate:
            if self.penetration_rate < 0 or self.penetration_rate > 100:
                frappe.throw(_("Penetration Rate must be between 0% and 100%"))

    def before_save(self):
        """Actions to perform before saving."""
        # Auto-generate segment code from name if not provided
        if not self.segment_code and self.segment_name:
            self.segment_code = frappe.scrub(self.segment_name).replace("_", "-")


@frappe.whitelist()
def get_active_segments(segment_type=None):
    """Get all active target segments, optionally filtered by type.

    Args:
        segment_type: Optional segment type filter

    Returns:
        List of active segments with basic info
    """
    filters = {"is_active": 1}
    if segment_type:
        filters["segment_type"] = segment_type

    return frappe.get_all(
        "Target Segment",
        filters=filters,
        fields=["name", "segment_name", "segment_code", "segment_type", "priority", "color"],
        order_by="display_order asc, segment_name asc"
    )


@frappe.whitelist()
def get_segment_hierarchy(parent=None):
    """Get target segments in hierarchical structure.

    Args:
        parent: Optional parent segment to start from

    Returns:
        List of segments with nested children
    """
    filters = {"parent_segment": parent or ["is", "not set"]}

    segments = frappe.get_all(
        "Target Segment",
        filters=filters,
        fields=["name", "segment_name", "segment_code", "segment_type",
                "is_active", "priority", "color", "display_order"],
        order_by="display_order asc, segment_name asc"
    )

    for segment in segments:
        children = get_segment_hierarchy(segment.name)
        if children:
            segment["children"] = children

    return segments


@frappe.whitelist()
def get_segments_by_type():
    """Get segments grouped by segment type.

    Returns:
        Dict with segment types as keys and list of segments as values
    """
    segments = frappe.get_all(
        "Target Segment",
        filters={"is_active": 1},
        fields=["name", "segment_name", "segment_code", "segment_type",
                "priority", "color", "display_order"],
        order_by="segment_type asc, display_order asc, segment_name asc"
    )

    grouped = {}
    for segment in segments:
        segment_type = segment.segment_type
        if segment_type not in grouped:
            grouped[segment_type] = []
        grouped[segment_type].append(segment)

    return grouped


@frappe.whitelist()
def get_product_count_for_segment(segment_name):
    """Get count of products tagged with a specific segment.

    Args:
        segment_name: Name of the target segment

    Returns:
        Count of products using this segment
    """
    return frappe.db.count(
        "Product Segment Tag",
        filters={"target_segment": segment_name}
    )


@frappe.whitelist()
def get_segment_statistics():
    """Get statistics about target segments.

    Returns:
        Dict with segment statistics
    """
    total_segments = frappe.db.count("Target Segment")
    active_segments = frappe.db.count("Target Segment", {"is_active": 1})

    # Count by type
    type_counts = frappe.get_all(
        "Target Segment",
        filters={"is_active": 1},
        fields=["segment_type", "count(*) as count"],
        group_by="segment_type"
    )

    # Count by priority
    priority_counts = frappe.get_all(
        "Target Segment",
        filters={"is_active": 1},
        fields=["priority", "count(*) as count"],
        group_by="priority"
    )

    return {
        "total_segments": total_segments,
        "active_segments": active_segments,
        "inactive_segments": total_segments - active_segments,
        "by_type": {item.segment_type: item.count for item in type_counts},
        "by_priority": {item.priority: item.count for item in priority_counts}
    }


@frappe.whitelist()
def search_segments(query, limit=10):
    """Search segments by name, code, or keywords.

    Args:
        query: Search query string
        limit: Maximum number of results

    Returns:
        List of matching segments
    """
    if not query:
        return []

    query = f"%{query}%"

    return frappe.db.sql("""
        SELECT name, segment_name, segment_code, segment_type, priority, color
        FROM `tabTarget Segment`
        WHERE is_active = 1
          AND (
            segment_name LIKE %(query)s
            OR segment_code LIKE %(query)s
            OR keywords LIKE %(query)s
            OR tags LIKE %(query)s
          )
        ORDER BY display_order ASC, segment_name ASC
        LIMIT %(limit)s
    """, {"query": query, "limit": limit}, as_dict=True)
