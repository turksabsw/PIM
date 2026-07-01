"""Run with: bench --site frappe.local execute frappe_pim.create_silso_variants.run"""

def run():
    import frappe
    log = []

    # Get first PIM Attribute Type
    atype = frappe.db.sql("SELECT name FROM `tabPIM Attribute Type` LIMIT 1", as_dict=True)
    if not atype:
        log.append("ERROR: No PIM Attribute Type found")
        return "\n".join(log)

    atype_name = atype[0]['name']
    log.append(f"Using attribute type: {atype_name}")

    # Step 1: Create grade PIM Attribute
    if not frappe.db.exists('PIM Attribute', 'silicone_foam_grade'):
        attr = frappe.new_doc('PIM Attribute')
        attr.attribute_name = 'Silicone Foam Grade'
        attr.attribute_code = 'silicone_foam_grade'
        attr.attribute_type = atype_name
        attr.is_variant_axis = 1
        attr.insert(ignore_permissions=True)
        frappe.db.commit()
        log.append("Created PIM Attribute: silicone_foam_grade")
    else:
        log.append("PIM Attribute silicone_foam_grade exists")

    # Step 2: Create 3 Product Variants
    variants_data = [
        ('SILSO-LITE-21010', 'SilSo Lite 21010', '21010', 'Grade 21010 - 80 kg/m3 density'),
        ('SILSO-LITE-21025', 'SilSo Lite 21025', '21025', 'Grade 21025 - 200 kg/m3 density'),
        ('SILSO-LITE-21030', 'SilSo Lite 21030', '21030', 'Grade 21030 - 350 kg/m3 density'),
    ]

    for code, name, grade, desc in variants_data:
        if frappe.db.exists('Product Variant', code):
            log.append(f"Already exists: {code}")
            continue

        doc = frappe.new_doc('Product Variant')
        doc.variant_code = code
        doc.variant_name = name
        doc.parent_product = 'SILSO-LITE'
        doc.product_family = 'silicone_foam'
        doc.status = 'Approved'
        doc.brand = 'cht-silicones'
        doc.manufacturer = 'cht-germany-gmbh'
        doc.erp_item = code
        doc.variant_level = 1
        doc.description = desc

        doc.append('axis_values', {
            'attribute': 'silicone_foam_grade',
            'attribute_value': grade,
            'display_value': f'Grade {grade}',
        })

        try:
            doc.insert(ignore_permissions=True)
            frappe.db.commit()
            log.append(f"Created: {code}")
        except Exception as e:
            log.append(f"Error {code}: {e}")
            frappe.db.rollback()

    # Final check
    result = frappe.db.get_all('Product Variant',
        filters={'parent_product': 'SILSO-LITE'},
        fields=['name', 'status'])
    log.append(f"Final variants: {result}")

    return "\n".join(log)
