// Copyright (c) 2024, PIM and contributors
// For license information, please see license.txt

frappe.ui.form.on('Product Variant', {
    setup: function(frm) {
        // Filter parent_product to show only relevant Items
        frm.set_query('parent_product', function() {
            return {
                filters: {
                    // Only show items that are not disabled
                    'disabled': 0
                }
            };
        });
    },
    
    refresh: function(frm) {
        // Additional refresh logic if needed
    },
    
    parent_product: function(frm) {
        // When parent product changes, inherit attributes from Item
        if (frm.doc.parent_product) {
            frappe.db.get_doc('Item', frm.doc.parent_product).then(item => {
                if (item) {
                    // Inherit product family if not set
                    if (!frm.doc.product_family && item.product_family) {
                        frm.set_value('product_family', item.product_family);
                    }
                    // Inherit brand if not set (from PIM custom field)
                    if (!frm.doc.brand && item.pim_brand) {
                        frm.set_value('brand', item.pim_brand);
                    }
                    // Inherit manufacturer if not set (from PIM custom field)
                    if (!frm.doc.manufacturer && item.pim_manufacturer) {
                        frm.set_value('manufacturer', item.pim_manufacturer);
                    }
                    // Inherit description if not set
                    if (!frm.doc.description && item.description) {
                        frm.set_value('description', item.description);
                    }
                }
            });
        }
    }
});

