import frappe
import unittest
from frappe.utils.password import update_password
from frappe_pim.pim.api import auth


class TestAuthAPI(unittest.TestCase):
    test_email = "pim_auth_test@example.com"
    test_pwd = "Secret@12345"

    @classmethod
    def setUpClass(cls):
        if not frappe.db.exists("User", cls.test_email):
            user = frappe.get_doc({
                "doctype": "User",
                "email": cls.test_email,
                "first_name": "Auth",
                "last_name": "Test",
                "send_welcome_email": 0,
                "enabled": 1,
            })
            user.insert(ignore_permissions=True)
        update_password(cls.test_email, cls.test_pwd)
        frappe.db.commit()

    def test_login_success_returns_token(self):
        result = auth.login(self.test_email, self.test_pwd)
        self.assertTrue(result["api_key"])
        self.assertTrue(result["api_secret"])
        self.assertEqual(result["user"], self.test_email)

    def test_login_token_is_stable_across_calls(self):
        first = auth.login(self.test_email, self.test_pwd)
        second = auth.login(self.test_email, self.test_pwd)
        self.assertEqual(first["api_key"], second["api_key"])
        self.assertEqual(first["api_secret"], second["api_secret"])

    def test_login_wrong_password_raises(self):
        with self.assertRaises(frappe.AuthenticationError):
            auth.login(self.test_email, "wrong-password")

    def test_login_unknown_user_raises(self):
        with self.assertRaises(frappe.AuthenticationError):
            auth.login("nobody@nowhere.invalid", "whatever")

    def test_register_creates_user_when_signup_enabled(self):
        ws = frappe.get_single("Website Settings")
        ws.disable_signup = 0
        ws.save(ignore_permissions=True)
        frappe.db.commit()

        new_email = "pim_signup_test@example.com"
        if frappe.db.exists("User", new_email):
            frappe.delete_doc("User", new_email, ignore_permissions=True, force=True)
            frappe.db.commit()

        result = auth.register(new_email, "Signup Test")
        self.assertIn("status", result)
        self.assertTrue(frappe.db.exists("User", new_email))

    def test_me_returns_current_user(self):
        original = frappe.session.user
        try:
            frappe.set_user(self.test_email)
            result = auth.me()
            self.assertTrue(result["authenticated"])
            self.assertEqual(result["user"], self.test_email)
        finally:
            frappe.set_user(original)

    def test_me_guest_is_not_authenticated(self):
        original = frappe.session.user
        try:
            frappe.set_user("Guest")
            result = auth.me()
            self.assertFalse(result["authenticated"])
        finally:
            frappe.set_user(original)
