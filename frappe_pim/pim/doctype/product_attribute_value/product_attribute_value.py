# Copyright (c) 2024, Your Company and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ProductAttributeValue(Document):
    def get_formatted_value(self):
        """Get formatted value with prefix and suffix from PIM Attribute.
        
        Returns:
            str: Formatted value with prefix and suffix if defined in PIM Attribute
        """
        if not self.attribute:
            return self.get_display_value()
        
        try:
            # Get attribute doc
            attr_doc = frappe.get_doc("PIM Attribute", self.attribute)
            
            # Get raw value
            raw_value = self.get_display_value()
            if not raw_value:
                return ""
            
            # Get prefix and suffix
            prefix = attr_doc.value_prefix or ""
            suffix = attr_doc.value_suffix or ""
            
            # Apply prefix and suffix
            formatted = raw_value
            if prefix:
                formatted = f"{prefix}{formatted}"
            if suffix:
                formatted = f"{formatted}{suffix}"
            
            return formatted
        except Exception:
            return self.get_display_value()
    
    def get_display_value(self):
        """Get the display value from the appropriate value field.
        
        Returns:
            str: The display value or empty string
        """
        # Priority order for value columns
        value_fields = [
            "value_text",
            "value_long_text",
            "value_link",
            "value_int",
            "value_float",
            "value_boolean",
            "value_date",
            "value_datetime",
        ]
        
        for field in value_fields:
            value = self.get(field)
            if value is not None:
                if isinstance(value, str) and not value.strip():
                    continue
                if field == "value_boolean":
                    return "Yes" if value else "No"
                elif field == "value_int":
                    return f"{int(value):,}"
                elif field == "value_float":
                    return f"{float(value):,.2f}"
                else:
                    return str(value)
        
        return ""
