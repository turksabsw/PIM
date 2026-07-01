"""
PIM Template Attribute Controller
Child table for PIM Attribute Template - defines attributes within a template
"""

import frappe
from frappe import _
from frappe.model.document import Document

# Defer frappe import to function level for module import without Frappe context

class PIMTemplateAttribute(Document):

        # Child tables typically don't need much validation
        # as they are validated at the parent level
        pass
