"""
Data Steward Controller
Manages data ownership responsibilities for MDM governance

Data stewardship assigns users to be responsible for specific data domains
within the PIM system. This enables:
- Clear data ownership and accountability
- Approval workflows for data changes
- Quality monitoring and notifications
- Escalation paths for issues

Stewardship Roles:
- Data Owner: Ultimate authority for data in domain
- Data Custodian: Day-to-day management of data
- Data Quality Analyst: Monitors and improves data quality
- Domain Expert: Subject matter expert for validation
- Approver: Can approve changes in workflow
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, nowdate, now_datetime


# Domain type to DocType mapping
DOMAIN_DOCTYPE_MAP = {
    "Product Family": "Product Family",
    "Brand": "Brand",
    "Channel": "Channel",
    "Attribute Group": "PIM Attribute Group",
    "All Products": None,
}


class DataSteward(Document):
    """Controller for Data Steward DocType.

    Handles validation, domain resolution, and stewardship queries.
    """

    def validate(self):
        """Validate stewardship assignment."""
        self.validate_domain()
        self.validate_dates()
        self.validate_permissions()
        self.set_domain_doctype()

    def before_save(self):
        """Set computed fields before saving."""
        self.set_domain_doctype()
        self.update_metrics()

    def on_update(self):
        """Actions after save."""
        self.check_expiry_status()

    def validate_domain(self):
        """Validate domain configuration."""
        if self.domain != "All Products" and not self.domain_value:
            frappe.throw(
                _("Domain Value is required when Domain Type is not 'All Products'"),
                title=_("Missing Domain Value")
            )

        # Validate domain value exists
        if self.domain_value and self.domain in DOMAIN_DOCTYPE_MAP:
            doctype = DOMAIN_DOCTYPE_MAP.get(self.domain)
            if doctype and not frappe.db.exists(doctype, self.domain_value):
                frappe.throw(
                    _("{0} '{1}' does not exist").format(self.domain, self.domain_value),
                    title=_("Invalid Domain Value")
                )

    def validate_dates(self):
        """Validate date range."""
        if self.valid_from and self.valid_until:
            if getdate(self.valid_from) > getdate(self.valid_until):
                frappe.throw(
                    _("Valid From date cannot be after Valid Until date"),
                    title=_("Invalid Date Range")
                )

    def validate_permissions(self):
        """Validate permission assignments based on role."""
        # Data Quality Analyst shouldn't have delete permission
        if self.role == "Data Quality Analyst" and self.can_delete:
            frappe.msgprint(
                _("Data Quality Analyst typically doesn't need delete permissions. "
                  "Consider if this is intentional."),
                indicator="orange"
            )

        # Only Data Owner should be able to assign stewards
        if self.role not in ("Data Owner", "Data Custodian") and self.can_assign_stewards:
            frappe.msgprint(
                _("Steward assignment is typically reserved for Data Owners. "
                  "Consider if this is intentional."),
                indicator="orange"
            )

    def set_domain_doctype(self):
        """Set the domain_doctype field for Dynamic Link."""
        if self.domain and self.domain in DOMAIN_DOCTYPE_MAP:
            self.domain_doctype = DOMAIN_DOCTYPE_MAP.get(self.domain)
        else:
            self.domain_doctype = None

    def update_metrics(self):
        """Update performance metrics for the stewardship domain."""
        if not self.name:
            return

        try:
            self.products_in_domain = self.get_product_count()
            self.pending_approvals = self.get_pending_approval_count()
            self.avg_quality_score = self.get_average_quality_score()
        except Exception:
            # Metrics are non-critical, don't fail save
            pass

    def check_expiry_status(self):
        """Update status if assignment has expired."""
        if self.valid_until and getdate(self.valid_until) < getdate(nowdate()):
            if self.status != "Expired":
                frappe.db.set_value(
                    "Data Steward", self.name,
                    "status", "Expired",
                    update_modified=False
                )

    def get_product_count(self):
        """Get count of products in this stewardship domain."""
        if self.domain == "All Products":
            return frappe.db.count("Item", {"custom_pim_status": ["is", "set"]})

        if not self.domain_value:
            return 0

        filters = {"custom_pim_status": ["is", "set"]}

        if self.domain == "Product Family":
            # Count products in this family (and children if include_children)
            families = [self.domain_value]
            if self.include_children:
                families.extend(get_child_families(self.domain_value))
            filters["item_group"] = ["in", families]

        elif self.domain == "Brand":
            filters["brand"] = self.domain_value

        return frappe.db.count("Item", filters)

    def get_pending_approval_count(self):
        """Get count of pending approvals in domain."""
        # Check for pending workflow states
        try:
            return frappe.db.count(
                "Item",
                {
                    "custom_pim_status": ["is", "set"],
                    "workflow_state": ["in", ["Pending Approval", "Pending Review"]]
                }
            )
        except Exception:
            return 0

    def get_average_quality_score(self):
        """Get average data quality score for products in domain."""
        try:
            result = frappe.db.sql("""
                SELECT AVG(custom_pim_completeness) as avg_score
                FROM `tabItem`
                WHERE custom_pim_status IS NOT NULL
                AND custom_pim_completeness > 0
            """, as_dict=True)

            if result and result[0].avg_score:
                return float(result[0].avg_score)
        except Exception:
            pass
        return 0

    def is_active(self):
        """Check if stewardship is currently active."""
        if self.status != "Active":
            return False

        today = getdate(nowdate())

        if self.valid_from and getdate(self.valid_from) > today:
            return False

        if self.valid_until and getdate(self.valid_until) < today:
            return False

        return True

    def has_permission(self, permission_type):
        """Check if steward has specific permission.

        Args:
            permission_type: One of 'approve', 'publish', 'merge', 'delete', 'assign'

        Returns:
            bool: Whether steward has the permission
        """
        if not self.is_active():
            return False

        permission_map = {
            "approve": self.can_approve,
            "publish": self.can_publish,
            "merge": self.can_merge,
            "delete": self.can_delete,
            "assign": self.can_assign_stewards,
        }

        return bool(permission_map.get(permission_type, False))


def get_child_families(parent_family):
    """Get all descendant families for hierarchy traversal.

    Args:
        parent_family: Name of parent Product Family

    Returns:
        list: Names of all descendant families
    """
    children = []

    def collect_children(family_name):
        direct_children = frappe.get_all(
            "Product Family",
            filters={"parent_family": family_name},
            pluck="name"
        )
        for child in direct_children:
            children.append(child)
            collect_children(child)

    collect_children(parent_family)
    return children


@frappe.whitelist()
def get_steward_for_product(product_name, permission_type=None):
    """Get the responsible steward(s) for a product.

    Finds stewards based on product's family, brand, etc. with priority handling.

    Args:
        product_name: Name of Product Master or Item
        permission_type: Optional filter by permission (approve, publish, etc.)

    Returns:
        list: List of steward dictionaries with user and role info
    """
    # Get product info
    try:
        product = frappe.db.get_value(
            "Item",
            product_name,
            ["item_group", "brand"],
            as_dict=True
        )
    except Exception:
        return []

    if not product:
        return []

    stewards = []
    today = nowdate()

    # Build filters for active stewards
    base_filters = {
        "status": "Active",
        "valid_from": ["<=", today],
    }

    # Get stewards by different domain types
    domains_to_check = [
        ("All Products", None),
        ("Brand", product.get("brand")),
        ("Product Family", product.get("item_group")),
    ]

    for domain_type, domain_value in domains_to_check:
        filters = base_filters.copy()
        filters["domain"] = domain_type

        if domain_value:
            filters["domain_value"] = domain_value

        domain_stewards = frappe.get_all(
            "Data Steward",
            filters=filters,
            fields=[
                "name", "steward", "steward_name", "role",
                "priority", "can_approve", "can_publish",
                "can_merge", "can_delete"
            ],
            order_by="priority asc"
        )

        # Filter by permission if specified
        if permission_type and domain_stewards:
            perm_field = f"can_{permission_type}"
            domain_stewards = [
                s for s in domain_stewards
                if s.get(perm_field)
            ]

        stewards.extend(domain_stewards)

    # Sort by priority and deduplicate by user
    stewards.sort(key=lambda x: x.get("priority", 999))

    seen_users = set()
    unique_stewards = []
    for steward in stewards:
        if steward["steward"] not in seen_users:
            seen_users.add(steward["steward"])
            unique_stewards.append(steward)

    return unique_stewards


@frappe.whitelist()
def get_steward_domains(user=None):
    """Get all domains a user has stewardship over.

    Args:
        user: User ID (defaults to current user)

    Returns:
        list: List of stewardship domain dictionaries
    """
    user = user or frappe.session.user
    today = nowdate()

    return frappe.get_all(
        "Data Steward",
        filters={
            "steward": user,
            "status": "Active",
            "valid_from": ["<=", today],
        },
        fields=[
            "name", "domain", "domain_value", "role",
            "can_approve", "can_publish", "can_merge",
            "can_delete", "can_assign_stewards",
            "products_in_domain", "avg_quality_score"
        ],
        order_by="domain asc, domain_value asc"
    )


@frappe.whitelist()
def check_stewardship_permission(product_name, permission_type, user=None):
    """Check if user has stewardship permission for a product.

    Args:
        product_name: Name of Product Master or Item
        permission_type: Permission to check (approve, publish, merge, delete)
        user: User ID (defaults to current user)

    Returns:
        dict: {allowed: bool, stewardship: dict or None}
    """
    user = user or frappe.session.user

    # System Manager always has permission
    if "System Manager" in frappe.get_roles(user):
        return {"allowed": True, "stewardship": None}

    stewards = get_steward_for_product(product_name, permission_type)

    for steward in stewards:
        if steward.get("steward") == user:
            return {"allowed": True, "stewardship": steward}

    return {"allowed": False, "stewardship": None}


@frappe.whitelist()
def assign_steward(domain_type, domain_value, steward_user, role="Data Custodian"):
    """Create a new stewardship assignment.

    Args:
        domain_type: Type of domain (Product Family, Brand, etc.)
        domain_value: Value of the domain
        steward_user: User to assign as steward
        role: Stewardship role

    Returns:
        str: Name of created Data Steward document
    """
    frappe.has_permission("Data Steward", "create", throw=True)

    doc = frappe.new_doc("Data Steward")
    doc.steward = steward_user
    doc.domain = domain_type
    doc.domain_value = domain_value
    doc.role = role
    doc.insert()

    return doc.name


@frappe.whitelist()
def record_steward_activity(steward_name):
    """Record steward activity timestamp.

    Called when steward performs an action in their domain.

    Args:
        steward_name: Name of Data Steward document
    """
    if frappe.db.exists("Data Steward", steward_name):
        frappe.db.set_value(
            "Data Steward", steward_name,
            "last_activity", now_datetime(),
            update_modified=False
        )


@frappe.whitelist()
def get_stewardship_summary():
    """Get summary statistics for stewardship dashboard.

    Returns:
        dict: Summary statistics
    """
    today = nowdate()

    total = frappe.db.count("Data Steward")
    active = frappe.db.count(
        "Data Steward",
        {"status": "Active", "valid_from": ["<=", today]}
    )
    expiring_soon = frappe.db.count(
        "Data Steward",
        {
            "status": "Active",
            "valid_until": ["between", [today, frappe.utils.add_days(today, 30)]]
        }
    )

    # Get role distribution
    role_distribution = frappe.get_all(
        "Data Steward",
        filters={"status": "Active"},
        fields=["role", "count(*) as count"],
        group_by="role"
    )

    return {
        "total": total,
        "active": active,
        "expiring_soon": expiring_soon,
        "inactive": total - active,
        "role_distribution": {r["role"]: r["count"] for r in role_distribution}
    }
