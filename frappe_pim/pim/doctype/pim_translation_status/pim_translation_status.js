// PIM Translation Status Client Script

frappe.ui.form.on('PIM Translation Status', {
    source_doctype: function(frm) {
        // Set custom query for source_name based on source_doctype
        if (frm.doc.source_doctype === 'Product Master') {
            frm.set_query('source_name', function() {
                return {
                    query: 'frappe_pim.pim.api.search.search_product_master'
                };
            });
        } else if (frm.doc.source_doctype === 'Product Variant') {
            frm.set_query('source_name', function() {
                return {
                    query: 'frappe_pim.pim.api.search.search_product_variant'
                };
            });
        } else {
            // Clear custom query for other DocTypes
            frm.set_query('source_name', function() {
                return {};
            });
        }
    },
    
    refresh: function(frm) {
        // Trigger source_doctype handler on form load
        if (frm.doc.source_doctype) {
            frm.trigger('source_doctype');
        }
    }
});

