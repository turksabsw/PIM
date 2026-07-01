"""
PIM Notification Rule Controller
Configurable notification rules for alerts and notifications
"""

import frappe
from frappe import _
from frappe.model.document import Document

# Defer frappe import to function level for module import without Frappe context

class PIMNotificationRule(Document):

        def validate(self):
            self.validate_event_configuration()
            self.validate_recipients()
            self.validate_schedule()
            self.validate_rate_limits()
            self.validate_templates()

        def validate_event_configuration(self):
            """Validate event type and related fields"""
            if self.event_type in ["Document Created", "Document Updated",
                                    "Document Deleted", "Field Changed", "Value Threshold"]:
                if not self.target_doctype:
                    frappe.throw(
                        _("Target DocType is required for event type: {0}").format(
                            self.event_type
                        ),
                        title=_("Missing Target DocType")
                    )

                # Validate target DocType exists
                if not frappe.db.exists("DocType", self.target_doctype):
                    frappe.throw(
                        _("DocType '{0}' does not exist").format(self.target_doctype),
                        title=_("Invalid DocType")
                    )

            if self.event_type == "Field Changed" and not self.watched_field:
                frappe.throw(
                    _("Watched Field is required for Field Changed event type"),
                    title=_("Missing Field")
                )

            if self.event_type == "Value Threshold":
                if not self.threshold_field:
                    frappe.throw(
                        _("Threshold Field is required for Value Threshold event type"),
                        title=_("Missing Threshold Field")
                    )
                if not self.threshold_operator:
                    frappe.throw(
                        _("Threshold Operator is required for Value Threshold event type"),
                        title=_("Missing Threshold Operator")
                    )
                if self.threshold_value is None or self.threshold_value == "":
                    frappe.throw(
                        _("Threshold Value is required for Value Threshold event type"),
                        title=_("Missing Threshold Value")
                    )

        def validate_recipients(self):
            """Validate at least one recipient method is configured"""
            has_recipients = any([
                self.send_to_document_owner,
                self.send_to_assigned_users,
                self.recipient_roles,
                self.recipient_users,
                self.recipient_email_list
            ])

            if not has_recipients:
                frappe.msgprint(
                    _("No recipients configured. Notification will have no recipients."),
                    indicator="orange"
                )

            # Validate recipient users exist
            if self.recipient_users:
                users = [u.strip() for u in self.recipient_users.split(",") if u.strip()]
                for user in users:
                    if not frappe.db.exists("User", user):
                        frappe.msgprint(
                            _("User '{0}' does not exist").format(user),
                            indicator="orange"
                        )

            # Validate recipient roles exist
            if self.recipient_roles:
                roles = [r.strip() for r in self.recipient_roles.split(",") if r.strip()]
                for role in roles:
                    if not frappe.db.exists("Role", role):
                        frappe.msgprint(
                            _("Role '{0}' does not exist").format(role),
                            indicator="orange"
                        )

        def validate_schedule(self):
            """Validate schedule configuration for scheduled events"""
            if self.event_type == "Scheduled":
                if not self.schedule_type:
                    frappe.throw(
                        _("Schedule Type is required for Scheduled event type"),
                        title=_("Missing Schedule Type")
                    )

                if self.schedule_type == "Weekly" and not self.schedule_day:
                    frappe.throw(
                        _("Day of Week is required for Weekly schedule"),
                        title=_("Missing Schedule Day")
                    )

                if self.schedule_type == "Monthly":
                    if not self.schedule_date:
                        frappe.throw(
                            _("Day of Month is required for Monthly schedule"),
                            title=_("Missing Schedule Date")
                        )
                    if self.schedule_date < 1 or self.schedule_date > 31:
                        frappe.throw(
                            _("Day of Month must be between 1 and 31"),
                            title=_("Invalid Schedule Date")
                        )

                if self.schedule_type == "Cron Expression" and not self.cron_expression:
                    frappe.throw(
                        _("Cron Expression is required for Cron Expression schedule type"),
                        title=_("Missing Cron Expression")
                    )

        def validate_rate_limits(self):
            """Validate rate limiting configuration"""
            if self.cooldown_minutes and self.cooldown_minutes < 0:
                frappe.throw(
                    _("Cooldown minutes cannot be negative"),
                    title=_("Invalid Cooldown")
                )

            if self.max_daily_notifications and self.max_daily_notifications < 0:
                frappe.throw(
                    _("Max daily notifications cannot be negative"),
                    title=_("Invalid Max Daily")
                )

            if self.aggregate_notifications:
                if not self.aggregate_interval_minutes or self.aggregate_interval_minutes < 1:
                    frappe.throw(
                        _("Aggregation interval must be at least 1 minute"),
                        title=_("Invalid Aggregation Interval")
                    )

        def validate_templates(self):
            """Validate message templates"""
            if not self.send_system_notification and not self.send_email and not self.publish_realtime:
                frappe.msgprint(
                    _("No notification channel selected. Rule will not send any notifications."),
                    indicator="orange"
                )

            if self.publish_realtime and not self.realtime_event_name:
                self.realtime_event_name = f"pim_notification_{frappe.scrub(self.rule_name)}"

        def before_save(self):
            """Update defaults before save"""
            self.reset_daily_counter_if_needed()

        def reset_daily_counter_if_needed(self):
            """Reset daily counter if date has changed"""
            current_date = today()
            if self.last_reset_date != current_date:
                self.sent_today = 0
                self.last_reset_date = current_date

        def on_update(self):
            """Actions after save"""
            self._invalidate_cache()

        def on_trash(self):
            """Cleanup when rule is deleted"""
            self._invalidate_cache()

        def _invalidate_cache(self):
            """Invalidate notification rule caches"""
            try:
                from frappe_pim.pim.utils.cache import invalidate_cache
                invalidate_cache("pim_notification_rule", self.name)
            except (ImportError, AttributeError):
                pass

        def should_trigger(self, doc, event=None, changed_fields=None):
            """Check if this rule should trigger for a given document

            Args:
                doc: The document that triggered the event
                event: The event type (create, update, delete)
                changed_fields: List of fields that changed (for update events)

            Returns:
                bool: True if rule should trigger
            """
            if not self.is_enabled:
                return False

            # Check rate limits
            if not self._check_rate_limits(doc.name if hasattr(doc, 'name') else None):
                return False

            # Check condition filters
            if self.condition_filters:
                try:
                    filters = json.loads(self.condition_filters)
                    if not self._match_filters(doc, filters):
                        return False
                except (json.JSONDecodeError, TypeError):
                    pass

            # Check custom condition
            if self.custom_condition:
                try:
                    result = frappe.safe_eval(
                        self.custom_condition,
                        eval_globals={"doc": doc, "frappe": frappe}
                    )
                    if not result:
                        return False
                except Exception:
                    return False

            # Check field changed
            if self.event_type == "Field Changed" and self.watched_field:
                watched = [f.strip() for f in self.watched_field.split(",")]
                if changed_fields:
                    if not any(f in watched for f in changed_fields):
                        return False
                else:
                    return False

            # Check threshold
            if self.event_type == "Value Threshold":
                if not self._check_threshold(doc):
                    return False

            return True

        def _check_rate_limits(self, doc_name=None):
            """Check if rate limits allow sending notification

            Args:
                doc_name: Document name for cooldown check

            Returns:
                bool: True if within rate limits
            """
            # Check daily limit
            if self.max_daily_notifications and self.max_daily_notifications > 0:
                self.reset_daily_counter_if_needed()
                if self.sent_today >= self.max_daily_notifications:
                    return False

            # Check cooldown
            if self.cooldown_minutes and self.cooldown_minutes > 0 and doc_name:
                if self.last_triggered:
                    from frappe.utils import time_diff_in_seconds
                    diff = time_diff_in_seconds(now_datetime(), self.last_triggered)
                    if diff < (self.cooldown_minutes * 60):
                        return False

            return True

        def _match_filters(self, doc, filters):
            """Check if document matches filter conditions

            Args:
                doc: Document to check
                filters: Dict of filter conditions

            Returns:
                bool: True if matches
            """
            for field, value in filters.items():
                doc_value = getattr(doc, field, None)
                if isinstance(value, list):
                    operator = value[0]
                    check_value = value[1]
                    if operator == "=" and doc_value != check_value:
                        return False
                    elif operator == "!=" and doc_value == check_value:
                        return False
                    elif operator == ">" and not (doc_value and doc_value > check_value):
                        return False
                    elif operator == "<" and not (doc_value and doc_value < check_value):
                        return False
                    elif operator == "in" and doc_value not in check_value:
                        return False
                    elif operator == "not in" and doc_value in check_value:
                        return False
                else:
                    if doc_value != value:
                        return False
            return True

        def _check_threshold(self, doc):
            """Check if document field meets threshold condition

            Args:
                doc: Document to check

            Returns:
                bool: True if threshold condition is met
            """
            field_value = getattr(doc, self.threshold_field, None)
            if field_value is None:
                return False

            try:
                # Try numeric comparison
                field_value = float(field_value)
                threshold = float(self.threshold_value)

                if self.threshold_operator == "=":
                    return field_value == threshold
                elif self.threshold_operator == "!=":
                    return field_value != threshold
                elif self.threshold_operator == "<":
                    return field_value < threshold
                elif self.threshold_operator == "<=":
                    return field_value <= threshold
                elif self.threshold_operator == ">":
                    return field_value > threshold
                elif self.threshold_operator == ">=":
                    return field_value >= threshold
            except (ValueError, TypeError):
                # String comparison
                if self.threshold_operator == "=":
                    return str(field_value) == str(self.threshold_value)
                elif self.threshold_operator == "!=":
                    return str(field_value) != str(self.threshold_value)

            return False

        def get_recipients(self, doc=None):
            """Get list of recipients for this notification

            Args:
                doc: The triggering document (for owner/assigned user lookup)

            Returns:
                list: List of user emails
            """
            recipients = set()

            # Document owner
            if self.send_to_document_owner and doc:
                owner = getattr(doc, 'owner', None)
                if owner:
                    recipients.add(owner)

            # Assigned users
            if self.send_to_assigned_users and doc:
                assigned = frappe.get_all(
                    "ToDo",
                    filters={
                        "reference_type": doc.doctype,
                        "reference_name": doc.name,
                        "status": "Open"
                    },
                    pluck="allocated_to"
                )
                recipients.update(assigned)

            # Recipient users
            if self.recipient_users:
                users = [u.strip() for u in self.recipient_users.split(",") if u.strip()]
                recipients.update(users)

            # Recipient roles
            if self.recipient_roles:
                roles = [r.strip() for r in self.recipient_roles.split(",") if r.strip()]
                for role in roles:
                    role_users = frappe.get_all(
                        "Has Role",
                        filters={"role": role, "parenttype": "User"},
                        pluck="parent"
                    )
                    # Filter out disabled users
                    for user in role_users:
                        if frappe.db.get_value("User", user, "enabled"):
                            recipients.add(user)

            return list(recipients)

        def get_external_emails(self):
            """Get list of external email addresses

            Returns:
                list: List of email addresses
            """
            if self.recipient_email_list:
                return [e.strip() for e in self.recipient_email_list.split(",") if e.strip()]
            return []

        def render_message(self, doc, context=None):
            """Render the notification message from template

            Args:
                doc: The triggering document
                context: Additional context variables

            Returns:
                dict with subject and message
            """
            from frappe.utils import get_url_to_form

            template_context = {
                "doc": doc,
                "frappe": frappe,
                "rule": self,
                "now": now_datetime()
            }

            if context:
                template_context.update(context)

            # Render subject
            subject = self.subject_template or f"PIM Notification: {self.rule_name}"
            try:
                subject = frappe.render_template(subject, template_context)
            except Exception:
                pass

            # Render message
            message = self.message_template or ""
            try:
                message = frappe.render_template(message, template_context)
            except Exception:
                pass

            # Add document link if configured
            if self.include_document_link and doc:
                doc_link = get_url_to_form(doc.doctype, doc.name)
                message += f"\n\n<a href='{doc_link}'>View Document</a>"

            return {
                "subject": subject,
                "message": message
            }

        def send_notification(self, doc, context=None):
            """Send notification for a document

            Args:
                doc: The triggering document
                context: Additional context variables

            Returns:
                dict with status and details
            """
            rendered = self.render_message(doc, context)
            recipients = self.get_recipients(doc)
            external_emails = self.get_external_emails()

            results = {
                "system_notifications": 0,
                "emails_sent": 0,
                "realtime_published": False
            }

            # Send system notifications
            if self.send_system_notification and recipients:
                for recipient in recipients:
                    try:
                        notification = frappe.new_doc("Notification Log")
                        notification.subject = rendered["subject"]
                        notification.email_content = rendered["message"]
                        notification.for_user = recipient
                        notification.type = "Alert"
                        notification.document_type = doc.doctype if doc else None
                        notification.document_name = doc.name if doc else None
                        notification.insert(ignore_permissions=True)
                        results["system_notifications"] += 1
                    except Exception:
                        pass

            # Send email notifications
            if self.send_email:
                all_emails = [r for r in recipients if "@" in r] + external_emails
                if all_emails:
                    try:
                        frappe.sendmail(
                            recipients=all_emails,
                            subject=rendered["subject"],
                            message=rendered["message"],
                            reference_doctype=doc.doctype if doc else None,
                            reference_name=doc.name if doc else None,
                            now=True
                        )
                        results["emails_sent"] = len(all_emails)
                    except Exception:
                        pass

            # Publish realtime event
            if self.publish_realtime:
                try:
                    frappe.publish_realtime(
                        event=self.realtime_event_name or "pim_notification",
                        message={
                            "rule": self.name,
                            "rule_name": self.rule_name,
                            "subject": rendered["subject"],
                            "message": rendered["message"],
                            "document_type": doc.doctype if doc else None,
                            "document_name": doc.name if doc else None,
                            "priority": self.priority
                        },
                        after_commit=True
                    )
                    results["realtime_published"] = True
                except Exception:
                    pass

            # Update statistics
            self.db_set({
                "total_sent": (self.total_sent or 0) + 1,
                "sent_today": (self.sent_today or 0) + 1,
                "last_triggered": now_datetime()
            })

            return results
# Module-level helper functions

def get_active_rules(event_type=None, target_doctype=None, category=None):
    """Get all active notification rules

    Args:
        event_type: Optional filter by event type
        target_doctype: Optional filter by target DocType
        category: Optional filter by category

    Returns:
        List of PIM Notification Rule documents
    """
    import frappe

    filters = {"is_enabled": 1}

    if event_type:
        filters["event_type"] = event_type

    if target_doctype:
        filters["target_doctype"] = target_doctype

    if category:
        filters["category"] = category

    rule_names = frappe.get_all(
        "PIM Notification Rule",
        filters=filters,
        pluck="name"
    )

    return [frappe.get_doc("PIM Notification Rule", name) for name in rule_names]

def trigger_notifications_for_event(doctype, doc_name, event, changed_fields=None):
    """Trigger all applicable notification rules for an event

    Args:
        doctype: The DocType of the document
        doc_name: The document name
        event: Event type (create, update, delete)
        changed_fields: List of changed fields for update events

    Returns:
        dict with count of triggered rules
    """
    import frappe

    event_map = {
        "create": "Document Created",
        "update": "Document Updated",
        "delete": "Document Deleted"
    }

    event_type = event_map.get(event)
    if not event_type:
        return {"triggered": 0}

    # Get matching rules
    rules = get_active_rules(event_type=event_type, target_doctype=doctype)

    # Also get Field Changed rules if this is an update
    if event == "update" and changed_fields:
        rules.extend(get_active_rules(event_type="Field Changed", target_doctype=doctype))

    # Get document
    try:
        doc = frappe.get_doc(doctype, doc_name)
    except Exception:
        return {"triggered": 0, "error": "Document not found"}

    triggered = 0
    for rule in rules:
        try:
            if rule.should_trigger(doc, event, changed_fields):
                frappe.enqueue(
                    "frappe_pim.pim.doctype.pim_notification_rule.pim_notification_rule.send_rule_notification",
                    queue="short",
                    job_id=f"notification_{rule.name}_{doc_name}",
                    rule_name=rule.name,
                    doctype=doctype,
                    doc_name=doc_name
                )
                triggered += 1
        except Exception:
            pass

    return {"triggered": triggered}

def send_rule_notification(rule_name, doctype, doc_name):
    """Send notification for a rule (called from background job)

    Args:
        rule_name: PIM Notification Rule name
        doctype: Document type
        doc_name: Document name
    """
    import frappe

    try:
        rule = frappe.get_doc("PIM Notification Rule", rule_name)
        doc = frappe.get_doc(doctype, doc_name)
        rule.send_notification(doc)
        frappe.db.commit()
    except Exception as e:
        frappe.log_error(
            f"Notification Rule Error: {rule_name}",
            str(e)
        )

def get_notification_stats():
    """Get notification statistics

    Returns:
        dict with notification stats
    """
    import frappe
    from frappe.utils import today

    stats = {
        "total_rules": 0,
        "active_rules": 0,
        "notifications_today": 0,
        "rules_by_category": {},
        "rules_by_event_type": {}
    }

    stats["total_rules"] = frappe.db.count("PIM Notification Rule")
    stats["active_rules"] = frappe.db.count("PIM Notification Rule", {"is_enabled": 1})

    # Notifications sent today
    notifications_today = frappe.db.sql("""
        SELECT SUM(sent_today) as total
        FROM `tabPIM Notification Rule`
        WHERE last_reset_date = %s
    """, today())

    if notifications_today and notifications_today[0][0]:
        stats["notifications_today"] = int(notifications_today[0][0])

    # Rules by category
    categories = frappe.db.sql("""
        SELECT category, COUNT(*) as count
        FROM `tabPIM Notification Rule`
        WHERE is_enabled = 1 AND category IS NOT NULL AND category != ''
        GROUP BY category
    """, as_dict=True)

    for cat in categories:
        stats["rules_by_category"][cat.category] = cat.count

    # Rules by event type
    event_types = frappe.db.sql("""
        SELECT event_type, COUNT(*) as count
        FROM `tabPIM Notification Rule`
        WHERE is_enabled = 1
        GROUP BY event_type
    """, as_dict=True)

    for et in event_types:
        stats["rules_by_event_type"][et.event_type] = et.count

    return stats
