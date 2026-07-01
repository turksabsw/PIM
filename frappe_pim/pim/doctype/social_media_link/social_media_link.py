"""
Social Media Link Controller
Manages social media channel links for products and categories
"""

import frappe
from frappe import _
from frappe.model.document import Document
import re


class SocialMediaLink(Document):
    def validate(self):
        self.validate_link_code()
        self.validate_url()
        self.validate_product_association()

    def validate_link_code(self):
        """Ensure link_code is URL-safe slug"""
        if not self.link_code:
            # Auto-generate from link_name and platform
            base = f"{self.platform}-{self.link_name}" if self.platform else self.link_name
            self.link_code = frappe.scrub(base)

        # Must be lowercase, no spaces, alphanumeric with underscores/hyphens
        if not re.match(r'^[a-z][a-z0-9_-]*$', self.link_code):
            frappe.throw(
                _("Link Code must start with a letter and contain only lowercase letters, numbers, underscores, and hyphens"),
                title=_("Invalid Link Code")
            )

    def validate_url(self):
        """Validate URL format"""
        if self.url:
            # Basic URL validation
            if not self.url.startswith(('http://', 'https://')):
                frappe.throw(
                    _("URL must start with http:// or https://"),
                    title=_("Invalid URL")
                )

            # Validate platform-specific URL patterns
            self.validate_platform_url()

    def validate_platform_url(self):
        """Validate that URL matches the selected platform"""
        platform_domains = {
            "Facebook": ["facebook.com", "fb.com", "fb.me"],
            "Instagram": ["instagram.com", "instagr.am"],
            "Twitter/X": ["twitter.com", "x.com", "t.co"],
            "LinkedIn": ["linkedin.com", "lnkd.in"],
            "YouTube": ["youtube.com", "youtu.be"],
            "TikTok": ["tiktok.com"],
            "Pinterest": ["pinterest.com", "pin.it"],
            "Snapchat": ["snapchat.com"],
            "WhatsApp": ["whatsapp.com", "wa.me"],
            "Telegram": ["telegram.org", "t.me"],
            "WeChat": ["wechat.com", "weixin.qq.com"],
            "Line": ["line.me"],
            "Reddit": ["reddit.com"],
            "Discord": ["discord.gg", "discord.com"]
        }

        if self.platform in platform_domains:
            expected_domains = platform_domains[self.platform]
            url_lower = self.url.lower()
            if not any(domain in url_lower for domain in expected_domains):
                frappe.msgprint(
                    _("Warning: URL does not match the expected domain for {0}. "
                      "Expected domains: {1}").format(
                        self.platform, ", ".join(expected_domains)
                    ),
                    indicator="orange",
                    title=_("URL Mismatch")
                )

    def validate_product_association(self):
        """Ensure at least one association if not a company account"""
        if not self.is_company_account:
            has_association = (
                self.linked_product or
                self.linked_product_family or
                self.linked_category
            )
            if not has_association:
                frappe.msgprint(
                    _("Consider linking this social media account to a Product, "
                      "Product Family, or Category, or mark it as a Company Account."),
                    indicator="blue",
                    title=_("No Product Association")
                )

    def before_save(self):
        """Prepare data before saving"""
        # Ensure sort_order is set
        if self.sort_order is None:
            self.sort_order = self.get_next_sort_order()

        # Extract profile handle from URL if not set
        if not self.profile_handle and self.url:
            self.extract_profile_handle()

    def get_next_sort_order(self):
        """Get next available sort order"""
        max_order = frappe.db.sql("""
            SELECT MAX(sort_order) FROM `tabSocial Media Link`
        """)
        if max_order and max_order[0][0] is not None:
            return max_order[0][0] + 10
        return 10

    def extract_profile_handle(self):
        """Try to extract profile handle from URL"""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(self.url)
            path = parsed.path.strip("/")

            # Simple extraction - get last path segment
            if path:
                segments = path.split("/")
                # Filter out common path segments
                filtered = [s for s in segments if s and s not in [
                    "pages", "p", "user", "channel", "c", "@"
                ]]
                if filtered:
                    handle = filtered[-1]
                    # Remove @ prefix if present
                    self.profile_handle = handle.lstrip("@")
        except Exception:
            pass

    def on_update(self):
        """Handle post-update actions"""
        self.invalidate_cache()

    def on_trash(self):
        """Cleanup before deletion"""
        self.invalidate_cache()

    def invalidate_cache(self):
        """Clear relevant caches"""
        try:
            frappe.cache().delete_key(f"pim:social_media_link:{self.name}")
            frappe.cache().delete_key("pim:all_social_media_links")
            if self.linked_product:
                frappe.cache().delete_key(f"pim:product_social_links:{self.linked_product}")
        except Exception:
            pass

    @frappe.whitelist()
    def verify_link(self):
        """Verify that the social media link is valid and accessible"""
        import requests
        from frappe.utils import today

        if not self.url:
            frappe.throw(_("URL is not configured"))

        try:
            # Simple HEAD request to check if URL is accessible
            response = requests.head(
                self.url,
                timeout=10,
                allow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; PIM LinkVerifier/1.0)"
                }
            )

            self.last_verified_date = today()

            if response.status_code == 200:
                self.verification_status = "Verified"
                self.error_message = None
            elif response.status_code in [301, 302, 303, 307, 308]:
                self.verification_status = "Verified"
                self.error_message = _("URL redirects to: {0}").format(
                    response.headers.get("Location", "Unknown")
                )
            elif response.status_code == 404:
                self.verification_status = "Verification Failed"
                self.error_message = _("Page not found (404)")
            else:
                self.verification_status = "Verification Failed"
                self.error_message = _("HTTP {0}: {1}").format(
                    response.status_code, response.reason
                )

            self.save()
            return {
                "status": self.verification_status,
                "message": self.error_message or _("Link verified successfully")
            }

        except requests.exceptions.Timeout:
            self.verification_status = "Verification Failed"
            self.error_message = _("Connection timed out")
            self.last_verified_date = today()
            self.save()
            return {"status": "Verification Failed", "message": self.error_message}

        except requests.exceptions.RequestException as e:
            self.verification_status = "Verification Failed"
            self.error_message = str(e)[:500]  # Limit error message length
            self.last_verified_date = today()
            self.save()
            return {"status": "Verification Failed", "message": self.error_message}


@frappe.whitelist()
def get_social_media_links(product=None, product_family=None, category=None, enabled_only=True):
    """Get social media links with optional filtering

    Args:
        product: Filter by linked product
        product_family: Filter by linked product family
        category: Filter by linked category
        enabled_only: If True, return only enabled links
    """
    filters = {}
    if enabled_only:
        filters["enabled"] = 1
    if product:
        filters["linked_product"] = product
    if product_family:
        filters["linked_product_family"] = product_family
    if category:
        filters["linked_category"] = category

    return frappe.get_all(
        "Social Media Link",
        filters=filters,
        fields=[
            "name", "link_name", "link_code", "platform", "url",
            "profile_handle", "enabled", "verification_status", "sort_order",
            "linked_product", "linked_product_family", "linked_category",
            "is_company_account"
        ],
        order_by="sort_order asc"
    )


@frappe.whitelist()
def get_platform_options():
    """Get available social media platforms"""
    return [
        {"value": "Facebook", "label": _("Facebook")},
        {"value": "Instagram", "label": _("Instagram")},
        {"value": "Twitter/X", "label": _("Twitter/X")},
        {"value": "LinkedIn", "label": _("LinkedIn")},
        {"value": "YouTube", "label": _("YouTube")},
        {"value": "TikTok", "label": _("TikTok")},
        {"value": "Pinterest", "label": _("Pinterest")},
        {"value": "Snapchat", "label": _("Snapchat")},
        {"value": "WhatsApp", "label": _("WhatsApp")},
        {"value": "Telegram", "label": _("Telegram")},
        {"value": "WeChat", "label": _("WeChat")},
        {"value": "Line", "label": _("Line")},
        {"value": "Reddit", "label": _("Reddit")},
        {"value": "Discord", "label": _("Discord")},
        {"value": "Other", "label": _("Other")}
    ]


@frappe.whitelist()
def bulk_verify_links(links=None):
    """Verify multiple social media links

    Args:
        links: JSON string of list of link names (if None, verify all)
    """
    import json

    if links:
        if isinstance(links, str):
            links = json.loads(links)
    else:
        links = frappe.get_all(
            "Social Media Link",
            filters={"enabled": 1},
            pluck="name"
        )

    results = []
    for link_name in links:
        try:
            doc = frappe.get_doc("Social Media Link", link_name)
            result = doc.verify_link()
            results.append({
                "name": link_name,
                "status": result.get("status"),
                "message": result.get("message")
            })
        except Exception as e:
            results.append({
                "name": link_name,
                "status": "Error",
                "message": str(e)
            })

    return results
