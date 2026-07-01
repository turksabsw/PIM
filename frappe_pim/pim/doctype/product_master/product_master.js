// Copyright (c) 2024, Your Company and contributors
// For license information, please see license.txt

frappe.ui.form.on("Product Master", {
    setup: function(frm) {
        // Setup filters for Link fields
        frm.set_query("product_series", function() {
            let filters = {};
            if (frm.doc.product_family) {
                filters["linked_family"] = frm.doc.product_family;
            }
            return {
                filters: filters
            };
        });

        frm.set_query("parent_product", function() {
            return {
                filters: {
                    "is_template": 1,
                    "name": ["!=", frm.doc.name || ""]
                }
            };
        });

        frm.set_query("variant_based_on", function() {
            return {
                filters: {
                    "is_active": 1
                }
            };
        });
    },

    onload: function(frm) {
        // Initialize field dependencies on load
        frm.trigger("toggle_variant_fields");
        frm.trigger("toggle_bundle_fields");
    },

    refresh: function(frm) {
        // Render Quick Stats
        frm.trigger("render_quick_stats");

        // Toggle fields based on current values
        frm.trigger("toggle_variant_fields");
        frm.trigger("toggle_bundle_fields");

        // Calculate and display completeness score
        if (frm.doc.name && !frm.is_new()) {
            frm.trigger("update_completeness_indicator");
        }

        // Add custom action buttons for saved documents
        if (!frm.is_new()) {
            // Generate Variants button (only for template products)
            if (frm.doc.is_template) {
                frm.add_custom_button(__("Generate Variants"), function() {
                    frm.trigger("generate_variants_action");
                }, __("Actions"));
            }

            // Sync to Channels button (if channels are configured)
            if (frm.doc.channels && frm.doc.channels.length > 0) {
                frm.add_custom_button(__("Sync to Channels"), function() {
                    frm.trigger("sync_to_channels_action");
                }, __("Actions"));
            }

            // AI Enrichment button
            frm.add_custom_button(__("AI Enrichment"), function() {
                frm.trigger("run_ai_enrichment_action");
            }, __("Actions"));
        }

        // Render variant matrix for template products
        if (frm.doc.is_template && !frm.is_new()) {
            frm.trigger("render_variant_matrix");
        }
    },

    validate: function(frm) {
        // Client-side validations
        frm.trigger("validate_product_code");
    },

    // Field change handlers
    is_template: function(frm) {
        frm.trigger("toggle_variant_fields");
    },

    is_bundle: function(frm) {
        frm.trigger("toggle_bundle_fields");
    },

    product_family: function(frm) {
        // Clear product_series when product_family changes
        if (frm.doc.product_series) {
            frm.set_value("product_series", "");
        }
    },

    attribute_template: function(frm) {
        // Copy attribute_template to variant_based_on for templates
        if (frm.doc.is_template && frm.doc.attribute_template) {
            frm.set_value("variant_based_on", frm.doc.attribute_template);
        }
    },

    // Custom methods
    toggle_variant_fields: function(frm) {
        // Show/hide variant-related fields based on is_template
        var is_template = frm.doc.is_template;
        var has_parent = frm.doc.parent_product;

        // Template-specific fields
        frm.toggle_display("variant_based_on", is_template);
        frm.toggle_display("variant_html", is_template);

        // Variant-specific fields (when product has a parent)
        frm.toggle_display("parent_product", !is_template);
        frm.toggle_display("variant_attributes", has_parent);

        // Set has_variants as read only
        frm.set_df_property("has_variants", "read_only", 1);
    },

    toggle_bundle_fields: function(frm) {
        // Show/hide bundle-related fields
        var is_bundle = frm.doc.is_bundle;
        frm.toggle_display("bundle_ref", is_bundle);
    },

    render_quick_stats: function(frm) {
        // Render Quick Stats HTML field
        if (!frm.fields_dict.quick_stats || !frm.fields_dict.quick_stats.$wrapper) {
            return;
        }

        var wrapper = frm.fields_dict.quick_stats.$wrapper;

        if (frm.is_new()) {
            wrapper.html(frm.render_new_product_stats());
            return;
        }

        // Fetch quick stats from server
        frappe.call({
            method: "frappe_pim.pim.doctype.product_master.product_master.get_product_quick_stats",
            args: {
                product_name: frm.doc.name
            },
            callback: function(r) {
                if (r.message) {
                    wrapper.html(frm.render_quick_stats_html(r.message));
                }
            }
        });
    },

    render_new_product_stats: function() {
        // Render placeholder stats for new products
        return `
            <div class="quick-stats-container" style="display: flex; gap: 16px; flex-wrap: wrap; padding: 12px 0;">
                <div class="stat-card" style="flex: 1; min-width: 120px; background: var(--bg-color); border: 1px solid var(--border-color); border-radius: 8px; padding: 12px; text-align: center;">
                    <div style="font-size: 24px; font-weight: 600; color: var(--text-muted);">--</div>
                    <div style="font-size: 12px; color: var(--text-muted);">${__("Data Quality")}</div>
                </div>
                <div class="stat-card" style="flex: 1; min-width: 120px; background: var(--bg-color); border: 1px solid var(--border-color); border-radius: 8px; padding: 12px; text-align: center;">
                    <div style="font-size: 24px; font-weight: 600; color: var(--text-muted);">0</div>
                    <div style="font-size: 12px; color: var(--text-muted);">${__("Variants")}</div>
                </div>
                <div class="stat-card" style="flex: 1; min-width: 120px; background: var(--bg-color); border: 1px solid var(--border-color); border-radius: 8px; padding: 12px; text-align: center;">
                    <div style="font-size: 24px; font-weight: 600; color: var(--text-muted);">0</div>
                    <div style="font-size: 12px; color: var(--text-muted);">${__("Channels")}</div>
                </div>
                <div class="stat-card" style="flex: 1; min-width: 120px; background: var(--bg-color); border: 1px solid var(--border-color); border-radius: 8px; padding: 12px; text-align: center;">
                    <div style="font-size: 24px; font-weight: 600; color: var(--text-muted);">0</div>
                    <div style="font-size: 12px; color: var(--text-muted);">${__("Media")}</div>
                </div>
            </div>
            <p style="color: var(--text-muted); font-size: 12px; margin-top: 8px;">
                ${__("Save the product to view statistics")}
            </p>
        `;
    },

    render_quick_stats_html: function(stats) {
        // Render Quick Stats based on data from server
        var completeness = stats.completeness || {};
        var score = completeness.score || 0;
        var status = completeness.status || "Unknown";

        // Determine color based on score
        var score_color = frm.get_score_color(score);
        var status_color = frm.get_status_color(status);

        var variants_count = stats.variants_count || 0;
        var channels_count = stats.channels_count || 0;
        var channels_synced = stats.channels_synced || 0;
        var media_count = stats.media_count || 0;
        var prices_count = stats.prices_count || 0;
        var relations_count = stats.relations_count || 0;

        return `
            <div class="quick-stats-container" style="display: flex; gap: 16px; flex-wrap: wrap; padding: 12px 0;">
                <div class="stat-card" style="flex: 1; min-width: 120px; background: var(--bg-color); border: 1px solid var(--border-color); border-radius: 8px; padding: 12px; text-align: center;">
                    <div style="font-size: 24px; font-weight: 600; color: ${score_color};">${Math.round(score)}%</div>
                    <div style="font-size: 12px; color: var(--text-muted);">${__("Data Quality")}</div>
                    <span class="badge" style="background: ${status_color}; color: white; font-size: 10px; padding: 2px 6px; border-radius: 4px; margin-top: 4px; display: inline-block;">${__(status)}</span>
                </div>
                <div class="stat-card" style="flex: 1; min-width: 120px; background: var(--bg-color); border: 1px solid var(--border-color); border-radius: 8px; padding: 12px; text-align: center;">
                    <div style="font-size: 24px; font-weight: 600; color: var(--primary-color);">${variants_count}</div>
                    <div style="font-size: 12px; color: var(--text-muted);">${__("Variants")}</div>
                </div>
                <div class="stat-card" style="flex: 1; min-width: 120px; background: var(--bg-color); border: 1px solid var(--border-color); border-radius: 8px; padding: 12px; text-align: center;">
                    <div style="font-size: 24px; font-weight: 600; color: var(--primary-color);">${channels_synced}/${channels_count}</div>
                    <div style="font-size: 12px; color: var(--text-muted);">${__("Channels Synced")}</div>
                </div>
                <div class="stat-card" style="flex: 1; min-width: 120px; background: var(--bg-color); border: 1px solid var(--border-color); border-radius: 8px; padding: 12px; text-align: center;">
                    <div style="font-size: 24px; font-weight: 600; color: var(--primary-color);">${media_count}</div>
                    <div style="font-size: 12px; color: var(--text-muted);">${__("Media")}</div>
                </div>
                <div class="stat-card" style="flex: 1; min-width: 120px; background: var(--bg-color); border: 1px solid var(--border-color); border-radius: 8px; padding: 12px; text-align: center;">
                    <div style="font-size: 24px; font-weight: 600; color: var(--primary-color);">${prices_count}</div>
                    <div style="font-size: 12px; color: var(--text-muted);">${__("Price Lists")}</div>
                </div>
                <div class="stat-card" style="flex: 1; min-width: 120px; background: var(--bg-color); border: 1px solid var(--border-color); border-radius: 8px; padding: 12px; text-align: center;">
                    <div style="font-size: 24px; font-weight: 600; color: var(--primary-color);">${relations_count}</div>
                    <div style="font-size: 12px; color: var(--text-muted);">${__("Relations")}</div>
                </div>
            </div>
        `;
    },

    get_score_color: function(score) {
        if (score >= 80) return "var(--green-500)";
        if (score >= 60) return "var(--blue-500)";
        if (score >= 40) return "var(--yellow-500)";
        if (score >= 20) return "var(--orange-500)";
        return "var(--red-500)";
    },

    get_status_color: function(status) {
        var colors = {
            "Excellent": "var(--green-500)",
            "Good": "var(--blue-500)",
            "Fair": "var(--yellow-500)",
            "Poor": "var(--orange-500)",
            "Critical": "var(--red-500)"
        };
        return colors[status] || "var(--text-muted)";
    },

    update_completeness_indicator: function(frm) {
        // Update completeness score and indicator in sidebar/header
        frappe.call({
            method: "frappe_pim.pim.doctype.product_master.product_master.calculate_product_completeness",
            args: {
                product_name: frm.doc.name
            },
            callback: function(r) {
                if (r.message) {
                    var score = r.message.score;
                    var status = r.message.status;

                    // Update the data_quality_score field if visible
                    if (frm.fields_dict.data_quality_score) {
                        frm.set_value("data_quality_score", score);
                    }
                }
            }
        });
    },

    validate_product_code: function(frm) {
        // Validate product code format
        if (frm.doc.product_code) {
            var code = frm.doc.product_code.trim();

            // Check for invalid characters
            if (/[<>"'&]/.test(code)) {
                frappe.throw(__("Product Code cannot contain special characters like < > \" ' &"));
            }

            // Update with trimmed value
            if (code !== frm.doc.product_code) {
                frm.set_value("product_code", code);
            }
        }
    },

    // Action button handlers
    generate_variants_action: function(frm) {
        // Confirm before generating variants
        frappe.confirm(
            __("This will generate variant products based on the attribute template. Continue?"),
            function() {
                frappe.call({
                    method: "frappe_pim.pim.doctype.product_master.product_master.generate_product_variants",
                    args: {
                        product_name: frm.doc.name
                    },
                    freeze: true,
                    freeze_message: __("Generating variants..."),
                    callback: function(r) {
                        if (r.message && r.message.length > 0) {
                            frappe.msgprint({
                                title: __("Variants Generated"),
                                message: __("Successfully created {0} variant(s).", [r.message.length]),
                                indicator: "green"
                            });
                            // Refresh the form and variant matrix
                            frm.reload_doc();
                        } else if (r.message && r.message.length === 0) {
                            frappe.msgprint({
                                title: __("No Variants Created"),
                                message: __("No new variants were created. Variants may already exist."),
                                indicator: "orange"
                            });
                        }
                    }
                });
            }
        );
    },

    sync_to_channels_action: function(frm) {
        // Show dialog to select channels
        var channels = frm.doc.channels || [];
        if (channels.length === 0) {
            frappe.msgprint(__("No channels configured for this product."));
            return;
        }

        var channel_options = channels.map(function(ch) {
            return {
                label: ch.channel + " (" + (ch.sync_status || "Pending") + ")",
                value: ch.channel
            };
        });

        var d = new frappe.ui.Dialog({
            title: __("Sync to Channels"),
            fields: [
                {
                    fieldname: "channel_select",
                    fieldtype: "MultiSelect",
                    label: __("Select Channels"),
                    options: channel_options.map(function(o) { return o.value; }),
                    description: __("Leave empty to sync all channels")
                }
            ],
            primary_action_label: __("Sync"),
            primary_action: function(values) {
                var selected_channels = values.channel_select ? values.channel_select.split(",").filter(Boolean) : null;

                frappe.call({
                    method: "frappe_pim.pim.doctype.product_master.product_master.sync_product_to_channels",
                    args: {
                        product_name: frm.doc.name,
                        channel_names: selected_channels
                    },
                    freeze: true,
                    freeze_message: __("Syncing to channels..."),
                    callback: function(r) {
                        if (r.message) {
                            var synced = r.message.synced || [];
                            var failed = r.message.failed || [];

                            if (synced.length > 0) {
                                frappe.msgprint({
                                    title: __("Sync Initiated"),
                                    message: __("Sync initiated for {0} channel(s): {1}", [synced.length, synced.join(", ")]),
                                    indicator: "green"
                                });
                            }

                            if (failed.length > 0) {
                                frappe.msgprint({
                                    title: __("Sync Errors"),
                                    message: __("Failed to sync to {0} channel(s)", [failed.length]),
                                    indicator: "red"
                                });
                            }

                            frm.reload_doc();
                        }
                    }
                });

                d.hide();
            }
        });

        d.show();
    },

    run_ai_enrichment_action: function(frm) {
        // Show dialog for AI enrichment options
        var d = new frappe.ui.Dialog({
            title: __("AI Enrichment"),
            fields: [
                {
                    fieldname: "enrichment_type",
                    fieldtype: "Select",
                    label: __("Enrichment Type"),
                    options: [
                        { label: __("Generate Description"), value: "description" },
                        { label: __("Generate SEO Content"), value: "seo" },
                        { label: __("Generate All"), value: "all" }
                    ],
                    default: "all"
                },
                {
                    fieldname: "ai_prompt_template",
                    fieldtype: "Link",
                    label: __("AI Prompt Template"),
                    options: "AI Prompt Template",
                    description: __("Optional: Select a specific prompt template")
                }
            ],
            primary_action_label: __("Run AI Enrichment"),
            primary_action: function(values) {
                // Update AI enrichment status
                frm.set_value("ai_enrichment_status", "Pending");

                frappe.call({
                    method: "frappe.client.save",
                    args: {
                        doc: frm.doc
                    },
                    freeze: true,
                    freeze_message: __("Initiating AI enrichment..."),
                    callback: function(r) {
                        if (!r.exc) {
                            frappe.msgprint({
                                title: __("AI Enrichment"),
                                message: __("AI enrichment has been queued. The product will be updated when processing is complete."),
                                indicator: "blue"
                            });
                            frm.reload_doc();
                        }
                    }
                });

                d.hide();
            }
        });

        d.show();
    },

    render_variant_matrix: function(frm) {
        // Render Variant Matrix HTML field for template products
        if (!frm.fields_dict.variant_html || !frm.fields_dict.variant_html.$wrapper) {
            return;
        }

        var wrapper = frm.fields_dict.variant_html.$wrapper;

        if (!frm.doc.is_template) {
            wrapper.html("");
            return;
        }

        // Fetch variants from server
        frappe.call({
            method: "frappe_pim.pim.doctype.product_master.product_master.get_product_variants",
            args: {
                product_name: frm.doc.name
            },
            callback: function(r) {
                if (r.message) {
                    wrapper.html(frm.render_variant_matrix_html(r.message));
                } else {
                    wrapper.html(frm.render_empty_variant_matrix());
                }
            }
        });
    },

    render_empty_variant_matrix: function() {
        // Render empty state for variant matrix
        return '<div class="variant-matrix-empty" style="text-align: center; padding: 40px 20px; background: var(--bg-color); border: 1px dashed var(--border-color); border-radius: 8px;">' +
            '<div style="font-size: 48px; color: var(--text-muted); margin-bottom: 16px;">' +
                '<i class="fa fa-th"></i>' +
            '</div>' +
            '<div style="font-size: 14px; color: var(--text-muted); margin-bottom: 16px;">' +
                __("No variants have been generated yet.") +
            '</div>' +
            '<div style="font-size: 12px; color: var(--text-light);">' +
                __('Click "Generate Variants" in the Actions menu to create variant products based on your attribute template.') +
            '</div>' +
        '</div>';
    },

    render_variant_matrix_html: function(variants) {
        // Render variant matrix with variant cards
        if (!variants || variants.length === 0) {
            return frm.render_empty_variant_matrix();
        }

        var html = '<div class="variant-matrix-container">';

        // Header with count
        html += '<div class="variant-matrix-header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">';
        html += '<div style="font-size: 14px; font-weight: 500; color: var(--heading-color);">';
        html += __("{0} Variant(s)", [variants.length]);
        html += '</div>';
        html += '<div style="font-size: 12px; color: var(--text-muted);">';
        html += __("Click on a variant to open it");
        html += '</div>';
        html += '</div>';

        // Variant grid
        html += '<div class="variant-grid" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px;">';

        variants.forEach(function(variant) {
            var status_color = frm.get_variant_status_color(variant.status);
            var image_html = variant.main_image
                ? '<img src="' + variant.main_image + '" style="width: 100%; height: 120px; object-fit: cover; border-radius: 4px 4px 0 0;">'
                : '<div style="width: 100%; height: 120px; background: var(--bg-light-gray); border-radius: 4px 4px 0 0; display: flex; align-items: center; justify-content: center;"><i class="fa fa-image" style="font-size: 32px; color: var(--text-muted);"></i></div>';

            html += '<div class="variant-card" data-name="' + variant.name + '" style="background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 8px; cursor: pointer; transition: box-shadow 0.2s, transform 0.2s;" onmouseover="this.style.boxShadow=\'0 4px 12px rgba(0,0,0,0.1)\'; this.style.transform=\'translateY(-2px)\';" onmouseout="this.style.boxShadow=\'none\'; this.style.transform=\'translateY(0)\';">';
            html += image_html;
            html += '<div style="padding: 12px;">';
            html += '<div style="font-size: 13px; font-weight: 500; color: var(--heading-color); margin-bottom: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="' + (variant.product_name || "") + '">' + (variant.product_name || variant.name) + '</div>';
            html += '<div style="font-size: 11px; color: var(--text-muted); margin-bottom: 8px;">' + (variant.sku || variant.product_code || "") + '</div>';
            html += '<span style="display: inline-block; padding: 2px 8px; font-size: 10px; border-radius: 4px; background: ' + status_color + '; color: white;">' + (variant.status || "Draft") + '</span>';
            html += '</div>';
            html += '</div>';
        });

        html += '</div>';
        html += '</div>';

        // Add click handler script
        html += '<script>';
        html += 'document.querySelectorAll(".variant-card").forEach(function(card) {';
        html += '  card.addEventListener("click", function() {';
        html += '    var name = this.getAttribute("data-name");';
        html += '    if (name) { frappe.set_route("Form", "Product Master", name); }';
        html += '  });';
        html += '});';
        html += '</script>';

        return html;
    },

    get_variant_status_color: function(status) {
        var colors = {
            "Draft": "var(--gray-500)",
            "Active": "var(--green-500)",
            "Inactive": "var(--yellow-500)",
            "Discontinued": "var(--red-500)",
            "Archived": "var(--gray-600)"
        };
        return colors[status] || "var(--gray-500)";
    }
});

// Child table event handlers
frappe.ui.form.on("Product Price Item", {
    price_items_add: function(frm, cdt, cdn) {
        // Set default currency from parent
        if (frm.doc.currency) {
            frappe.model.set_value(cdt, cdn, "currency", frm.doc.currency);
        }
    },

    valid_from: function(frm, cdt, cdn) {
        // Validate date range
        var row = locals[cdt][cdn];
        if (row.valid_from && row.valid_to && row.valid_from > row.valid_to) {
            frappe.msgprint(__("Row {0}: Valid From cannot be after Valid To", [row.idx]));
            frappe.model.set_value(cdt, cdn, "valid_from", "");
        }
    },

    valid_to: function(frm, cdt, cdn) {
        // Validate date range
        var row = locals[cdt][cdn];
        if (row.valid_from && row.valid_to && row.valid_from > row.valid_to) {
            frappe.msgprint(__("Row {0}: Valid From cannot be after Valid To", [row.idx]));
            frappe.model.set_value(cdt, cdn, "valid_to", "");
        }
    }
});

frappe.ui.form.on("Product Certification Item", {
    valid_from: function(frm, cdt, cdn) {
        // Validate certification date range
        var row = locals[cdt][cdn];
        if (row.valid_from && row.valid_to && row.valid_from > row.valid_to) {
            frappe.msgprint(__("Certification Row {0}: Valid From cannot be after Valid To", [row.idx]));
            frappe.model.set_value(cdt, cdn, "valid_from", "");
        }
    },

    valid_to: function(frm, cdt, cdn) {
        // Validate certification date range
        var row = locals[cdt][cdn];
        if (row.valid_from && row.valid_to && row.valid_from > row.valid_to) {
            frappe.msgprint(__("Certification Row {0}: Valid From cannot be after Valid To", [row.idx]));
            frappe.model.set_value(cdt, cdn, "valid_to", "");
        }

        // Warn if certification is expired
        if (row.valid_to && frappe.datetime.get_diff(row.valid_to, frappe.datetime.get_today()) < 0) {
            frappe.msgprint({
                title: __("Expired Certification"),
                message: __("Certification Row {0}: This certification has expired.", [row.idx]),
                indicator: "orange"
            });
        }
    }
});

frappe.ui.form.on("Product Channel", {
    channel: function(frm, cdt, cdn) {
        // Set default sync status when channel is added
        var row = locals[cdt][cdn];
        if (row.channel && !row.sync_status) {
            frappe.model.set_value(cdt, cdn, "sync_status", "Pending");
        }
    }
});

frappe.ui.form.on("Product Relation", {
    related_product: function(frm, cdt, cdn) {
        // Prevent self-reference
        var row = locals[cdt][cdn];
        if (row.related_product && row.related_product === frm.doc.name) {
            frappe.msgprint(__("A product cannot be related to itself."));
            frappe.model.set_value(cdt, cdn, "related_product", "");
        }
    }
});

frappe.ui.form.on("Product Supplier Item", {
    supplier_items_add: function(frm, cdt, cdn) {
        // Set default currency from parent
        if (frm.doc.currency) {
            frappe.model.set_value(cdt, cdn, "currency", frm.doc.currency);
        }
    }
});
