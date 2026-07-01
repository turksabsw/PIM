# Copyright (c) 2024, Your Company and contributors
# For license information, please see license.txt

app_name = "frappe_pim"
app_title = "Frappe PIM"
app_publisher = "Your Company"
app_description = "Product Information Management for ERPNext"
app_email = "info@yourcompany.com"
app_license = "MIT"

# Required apps
# required_apps = ["frappe", "erpnext"]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/frappe_pim/css/frappe_pim.css"
# app_include_js = "/assets/frappe_pim/js/frappe_pim.js"

# include js, css files in header of web template
# web_include_css = "/assets/frappe_pim/css/frappe_pim.css"
# web_include_js = "/assets/frappe_pim/js/frappe_pim.js"

# include custom scss in every website theme (without signing in)
# website_theme_scss = "frappe_pim/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
#     "Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Website Route Rules
# -------------------
# Proxy Vue.js frontend routes through Frappe's website system.
# Maps /onboarding/* URLs to the Vue onboarding wizard SPA.

website_route_rules = [
    {"from_route": "/onboarding/<path:app_path>", "to_route": "onboarding"},
]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
#     "methods": "frappe_pim.utils.jinja_methods",
#     "filters": "frappe_pim.utils.jinja_filters"
# }

# Boot Session
# ------------
# Inject PIM settings and onboarding status into every session boot.
# Allows frontend to check onboarding completion without extra API calls.

boot_session = "frappe_pim.pim.boot.boot_session"

# Installation
# ------------

# before_install = "frappe_pim.install.before_install"
# after_install = "frappe_pim.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "frappe_pim.uninstall.before_uninstall"
# after_uninstall = "frappe_pim.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/dependence, place the erpnext in setup.py

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "frappe_pim.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
#     "Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
#     "Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
#     "ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events
# Use this to sync ERPNext Item changes to Product Master (bidirectional sync)

doc_events = {
    "Item": {
        "on_update": "frappe_pim.pim.sync.item_sync.on_item_update",
        "on_trash": "frappe_pim.pim.sync.item_sync.on_item_trash",
        "after_insert": "frappe_pim.pim.sync.item_sync.on_item_insert",
    }
}

# Scheduled Tasks
# ---------------
# Sync queue processing for bidirectional PIM <-> ERPNext synchronization

scheduler_events = {
    "all": [
        "frappe_pim.pim.sync.queue_processor.process_sync_queue"
    ],
    "daily": [
        "frappe_pim.pim.sync.queue_processor.cleanup_old_sync_entries"
    ],
    "hourly": [
        "frappe_pim.pim.sync.queue_processor.retry_all_failed"
    ],
}

# Testing
# -------

# before_tests = "frappe_pim.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
#     "frappe.desk.doctype.event.event.get_events": "frappe_pim.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
#     "Task": "frappe_pim.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Fixtures
# --------
# Export custom fields and other data during app installation
# This includes fixtures for Custom Field definitions on ERPNext Item for PIM-specific fields

fixtures = [
    # Custom Field fixtures for PIM fields on Item (lifecycle_stage, pim_status, sku, etc.)
    {
        "dt": "Custom Field",
        "filters": [
            ["module", "=", "PIM"]
        ]
    },
    # Property Setter fixtures for PIM customizations
    {
        "dt": "Property Setter",
        "filters": [
            ["module", "=", "PIM"]
        ]
    },
    # Industry Template fixtures — export active sector templates
    # (fashion, industrial, food, electronics, health_beauty, automotive, custom)
    {
        "dt": "Industry Template",
        "filters": [
            ["is_active", "=", 1]
        ]
    },
]

# User Data Protection
# --------------------

# user_data_fields = [
#     {
#         "doctype": "{doctype_1}",
#         "filter_by": "{filter_by}",
#         "redact_fields": ["{field_1}", "{field_2}"],
#         "partial": 1,
#     },
#     {
#         "doctype": "{doctype_2}",
#         "filter_by": "{filter_by}",
#         "partial": 1,
#     },
#     {
#         "doctype": "{doctype_3}",
#         "strict": False,
#     },
#     {
#         "doctype": "{doctype_4}"
#     }
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
#     "frappe_pim.auth.validate"
# ]
