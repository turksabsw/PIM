# Copyright (c) 2024, Your Company and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class BrandPortalUserBrand(Document):
    """Child table for Brand Portal User brand assignments.

    Stores the brands assigned to a portal user with their
    specific access level for each brand.

    Access Levels:
    - View Only: Can view product data, no editing
    - Contributor: Can submit data, subject to approval
    - Editor: Can edit product data directly
    - Brand Admin: Full access within the brand scope
    """

    pass
