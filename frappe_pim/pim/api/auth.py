"""PIM Token-based Authentication API.

Guest-accessible endpoints for a decoupled SPA frontend hosted on a different
origin. Uses Frappe's api_key:api_secret token auth so the frontend never
depends on cross-site cookies.
"""

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils.password import check_password, get_decrypted_password


def _resolve_user(usr):
    """Resolve a login identifier (email or username) to a User name."""
    if not usr:
        return None
    if frappe.db.exists("User", usr):
        return usr
    return frappe.db.get_value("User", {"username": usr}, "name")


def _get_or_create_api_credentials(user):
    """Return a stable (api_key, api_secret) pair for the user, creating if absent."""
    user_doc = frappe.get_doc("User", user)
    changed = False

    if not user_doc.api_key:
        user_doc.api_key = frappe.generate_hash(length=15)
        changed = True

    api_secret = None
    if user_doc.api_secret:
        api_secret = get_decrypted_password("User", user, "api_secret")

    if not api_secret:
        api_secret = frappe.generate_hash(length=15)
        user_doc.api_secret = api_secret
        changed = True

    if changed:
        user_doc.save(ignore_permissions=True)
        frappe.db.commit()

    return user_doc.api_key, api_secret


@frappe.whitelist(allow_guest=True)
@rate_limit(key="usr", limit=5, seconds=60)
def login(usr, pwd):
    """Authenticate and return an API token (api_key:api_secret)."""
    user = _resolve_user(usr)
    if not user:
        frappe.throw(_("Invalid login credentials"), frappe.AuthenticationError)

    # Raises frappe.AuthenticationError on mismatch.
    check_password(user, pwd)

    if not frappe.db.get_value("User", user, "enabled"):
        frappe.throw(_("User account is disabled"), frappe.AuthenticationError)

    api_key, api_secret = _get_or_create_api_credentials(user)

    return {
        "api_key": api_key,
        "api_secret": api_secret,
        "user": user,
        "full_name": frappe.db.get_value("User", user, "full_name"),
    }


@frappe.whitelist(allow_guest=True)
@rate_limit(key="email", limit=5, seconds=60)
def register(email, full_name):
    """Public self-signup: create a Website User and send a verification email.

    Requires Website Settings signup to be enabled (disable_signup = 0).
    Frappe's sign_up throws if signup is disabled; that error propagates to the
    frontend which surfaces the server message.
    """
    from frappe.core.doctype.user.user import sign_up

    status, message = sign_up(email, full_name, redirect_to="")
    return {"status": status, "message": message}


@frappe.whitelist(allow_guest=True)
def me():
    """Return the current user resolved from the Authorization token header."""
    user = frappe.session.user
    if not user or user == "Guest":
        return {"authenticated": False}
    return {
        "authenticated": True,
        "user": user,
        "full_name": frappe.db.get_value("User", user, "full_name"),
    }
