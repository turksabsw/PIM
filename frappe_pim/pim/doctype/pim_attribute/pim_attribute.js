// Copyright (c) 2024, Frappe PIM Team and contributors
// For license information, please see license.txt

frappe.ui.form.on('PIM Attribute', {
	refresh: function(frm) {
		// Format min_value and max_value fields with prefix/suffix
		format_value_fields(frm);
		
		// Watch for changes
		frm.fields_dict['value_prefix']?.$input.on('input change', function() {
			format_value_fields(frm);
		});
		frm.fields_dict['value_suffix']?.$input.on('input change', function() {
			format_value_fields(frm);
		});
	},
	
	min_value: function(frm) {
		format_value_fields(frm);
	},
	
	max_value: function(frm) {
		format_value_fields(frm);
	},
	
	value_prefix: function(frm) {
		format_value_fields(frm);
	},
	
	value_suffix: function(frm) {
		format_value_fields(frm);
	}
});

function format_value_fields(frm) {
	const prefix = (frm.doc.value_prefix || '').trim();
	const suffix = (frm.doc.value_suffix || '').trim();
	
	// Format min_value field display
	if (frm.fields_dict['min_value']) {
		const minField = frm.fields_dict['min_value'];
		const $input = minField.$input;
		
		if ($input && $input.length) {
			// Remove existing helper
			$input.siblings('.value-helper').remove();
			
			// Get current value
			const minVal = frm.doc.min_value;
			
			if (minVal != null && (prefix || suffix)) {
				try {
					const numVal = parseFloat(minVal);
					if (!isNaN(numVal)) {
						// Format number
						const formatted = numVal.toLocaleString('tr-TR', {
							minimumFractionDigits: 0,
							maximumFractionDigits: 3
						});
						
						// Create display value
						const displayValue = prefix + formatted + suffix;
						
						// Add helper text below input
						const $helper = $(`
							<div class="value-helper" style="margin-top: 4px; color: #6c757d; font-size: 12px;">
								<strong>Görüntüleme:</strong> <span style="color: #495057; font-weight: 500;">${displayValue}</span>
							</div>
						`);
						$input.after($helper);
						
						// Also update placeholder
						$input.attr('placeholder', displayValue);
					}
				} catch (e) {
					// Ignore errors
				}
			} else {
				$input.attr('placeholder', '');
			}
		}
	}
	
	// Format max_value field display
	if (frm.fields_dict['max_value']) {
		const maxField = frm.fields_dict['max_value'];
		const $input = maxField.$input;
		
		if ($input && $input.length) {
			// Remove existing helper
			$input.siblings('.value-helper').remove();
			
			// Get current value
			const maxVal = frm.doc.max_value;
			
			if (maxVal != null && (prefix || suffix)) {
				try {
					const numVal = parseFloat(maxVal);
					if (!isNaN(numVal)) {
						// Format number
						const formatted = numVal.toLocaleString('tr-TR', {
							minimumFractionDigits: 0,
							maximumFractionDigits: 3
						});
						
						// Create display value
						const displayValue = prefix + formatted + suffix;
						
						// Add helper text below input
						const $helper = $(`
							<div class="value-helper" style="margin-top: 4px; color: #6c757d; font-size: 12px;">
								<strong>Görüntüleme:</strong> <span style="color: #495057; font-weight: 500;">${displayValue}</span>
							</div>
						`);
						$input.after($helper);
						
						// Also update placeholder
						$input.attr('placeholder', displayValue);
					}
				} catch (e) {
					// Ignore errors
				}
			} else {
				$input.attr('placeholder', '');
			}
		}
	}
}

