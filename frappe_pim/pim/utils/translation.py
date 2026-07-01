"""
Translation Gap Detection Utility Module

This module provides functions for detecting and tracking translation gaps
in product content. It helps identify which products are missing translations
for required languages and fields.

Key functionality:
- Detect missing translations for a product
- Get translation coverage statistics
- Identify products with incomplete translations
- Track translation status by language and field
- Generate translation gap reports

The translation gap detection uses the Product Translation Item child table
which tracks translations for various product fields across different languages.

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""


# Default required fields that should be translated
DEFAULT_TRANSLATABLE_FIELDS = [
    "Product Name",
    "Short Description",
    "Long Description",
    "Meta Title",
    "Meta Description",
]

# Field name mapping for display
FIELD_DISPLAY_NAMES = {
    "Product Name": "Product Name",
    "Short Description": "Short Description",
    "Long Description": "Long Description",
    "Meta Title": "SEO Meta Title",
    "Meta Description": "SEO Meta Description",
    "Meta Keywords": "SEO Meta Keywords",
    "Marketing Text": "Marketing Text",
    "Technical Specifications": "Technical Specifications",
    "Usage Instructions": "Usage Instructions",
    "Warnings": "Warnings",
    "Other": "Other Content",
}


def get_missing_translations(product, required_languages=None, required_fields=None):
    """Get missing translations for a product.

    Analyzes the product's translation items and identifies which
    language/field combinations are missing.

    Args:
        product: Product Master name (str) or Product Master document
        required_languages: List of required language codes. If None,
            uses all enabled languages from the Language DocType.
        required_fields: List of required field names to check.
            If None, uses DEFAULT_TRANSLATABLE_FIELDS.

    Returns:
        dict: Dictionary containing:
            - missing: List of dicts with {language, field, display_name}
            - total_required: Total number of translations required
            - total_present: Number of translations present
            - coverage_percentage: Percentage of translations complete
            - by_language: Dict of missing counts per language
            - by_field: Dict of missing counts per field

    Example:
        >>> missing = get_missing_translations("PROD-001")
        >>> print(missing["coverage_percentage"])
        75.0
        >>> print(missing["missing"])
        [{"language": "de", "field": "Short Description", "display_name": "Short Description"}]
    """
    import frappe

    try:
        # Get product document
        if isinstance(product, str):
            product_name = product
            if not frappe.db.exists("Product Master", product_name):
                return _empty_missing_result()
            product_doc = frappe.get_doc("Product Master", product_name)
        else:
            product_doc = product
            product_name = product_doc.name

        # Get required languages
        if required_languages is None:
            required_languages = _get_enabled_languages()

        if not required_languages:
            # No languages configured - return complete
            return {
                "missing": [],
                "total_required": 0,
                "total_present": 0,
                "coverage_percentage": 100.0,
                "by_language": {},
                "by_field": {},
            }

        # Get required fields
        if required_fields is None:
            required_fields = DEFAULT_TRANSLATABLE_FIELDS.copy()

        # Get existing translations
        translations = product_doc.get("product_translations") or []
        existing = _build_existing_translations_map(translations)

        # Find missing translations
        missing = []
        by_language = {}
        by_field = {}

        for lang in required_languages:
            for field in required_fields:
                key = f"{lang}|{field}"
                if key not in existing:
                    missing.append({
                        "language": lang,
                        "field": field,
                        "display_name": FIELD_DISPLAY_NAMES.get(field, field),
                    })

                    # Track by language
                    if lang not in by_language:
                        by_language[lang] = 0
                    by_language[lang] += 1

                    # Track by field
                    if field not in by_field:
                        by_field[field] = 0
                    by_field[field] += 1

        # Calculate coverage
        total_required = len(required_languages) * len(required_fields)
        total_present = total_required - len(missing)
        coverage = 100.0 if total_required == 0 else round(
            (total_present / total_required) * 100, 2
        )

        return {
            "product": product_name,
            "missing": missing,
            "total_required": total_required,
            "total_present": total_present,
            "coverage_percentage": coverage,
            "by_language": by_language,
            "by_field": by_field,
        }

    except Exception as e:
        import frappe
        frappe.log_error(
            message=f"Error getting missing translations for {product}: {str(e)}",
            title="PIM Translation Gap Error"
        )
        return _empty_missing_result()


def get_translation_coverage(product, required_languages=None):
    """Get translation coverage percentage for a product.

    A convenience function that returns just the coverage percentage
    for a product's translations.

    Args:
        product: Product Master name (str) or Product Master document
        required_languages: List of required language codes (optional)

    Returns:
        float: Coverage percentage from 0.0 to 100.0

    Example:
        >>> coverage = get_translation_coverage("PROD-001")
        >>> print(f"Product is {coverage}% translated")
    """
    result = get_missing_translations(product, required_languages)
    return result.get("coverage_percentage", 0.0)


def get_products_with_missing_translations(
    required_languages=None,
    required_fields=None,
    min_missing=1,
    limit=100,
    product_family=None,
    category=None,
):
    """Get products that have missing translations.

    Scans products and identifies those with incomplete translations
    based on the required languages and fields.

    Args:
        required_languages: List of required language codes. If None,
            uses all enabled languages.
        required_fields: List of required field names. If None,
            uses DEFAULT_TRANSLATABLE_FIELDS.
        min_missing: Minimum number of missing translations to include
            a product in results (default: 1).
        limit: Maximum number of products to return (default: 100).
        product_family: Filter by product family (optional).
        category: Filter by category (optional).

    Returns:
        list: List of dicts containing:
            - product: Product Master name
            - product_name: Display name
            - missing_count: Number of missing translations
            - coverage_percentage: Translation coverage
            - missing_languages: List of languages with gaps
            - missing_fields: List of fields with gaps

    Example:
        >>> incomplete = get_products_with_missing_translations(min_missing=3)
        >>> for p in incomplete:
        ...     print(f"{p['product']}: {p['missing_count']} missing")
    """
    import frappe

    try:
        # Build product filters
        filters = {"docstatus": 0}
        if product_family:
            filters["product_family"] = product_family
        if category:
            filters["category"] = category

        # Get products
        products = frappe.get_all(
            "Product Master",
            filters=filters,
            fields=["name", "product_name", "product_family", "category"],
            limit=limit * 2,  # Get extra since we'll filter
        )

        if not products:
            return []

        # Get required languages if not specified
        if required_languages is None:
            required_languages = _get_enabled_languages()

        if not required_languages:
            return []

        # Check each product
        results = []
        for product in products:
            try:
                gaps = get_missing_translations(
                    product["name"],
                    required_languages,
                    required_fields,
                )

                if len(gaps.get("missing", [])) >= min_missing:
                    results.append({
                        "product": product["name"],
                        "product_name": product.get("product_name", product["name"]),
                        "product_family": product.get("product_family"),
                        "category": product.get("category"),
                        "missing_count": len(gaps.get("missing", [])),
                        "coverage_percentage": gaps.get("coverage_percentage", 0),
                        "missing_languages": list(gaps.get("by_language", {}).keys()),
                        "missing_fields": list(gaps.get("by_field", {}).keys()),
                    })

                    if len(results) >= limit:
                        break

            except Exception:
                continue

        # Sort by missing count (most incomplete first)
        results.sort(key=lambda x: x["missing_count"], reverse=True)

        return results

    except Exception as e:
        import frappe
        frappe.log_error(
            message=f"Error getting products with missing translations: {str(e)}",
            title="PIM Translation Scan Error"
        )
        return []


def get_translation_statistics(product_family=None, category=None):
    """Get translation statistics across products.

    Calculates aggregate translation coverage statistics for
    products, optionally filtered by family or category.

    Args:
        product_family: Filter by product family (optional)
        category: Filter by category (optional)

    Returns:
        dict: Dictionary containing:
            - total_products: Number of products analyzed
            - fully_translated: Number of products with 100% coverage
            - partially_translated: Products with 1-99% coverage
            - not_translated: Products with 0% coverage
            - average_coverage: Average coverage across all products
            - by_language: Dict with coverage stats per language
            - by_field: Dict with coverage stats per field

    Example:
        >>> stats = get_translation_statistics(product_family="Electronics")
        >>> print(f"Average coverage: {stats['average_coverage']}%")
    """
    import frappe
    from frappe.utils import flt

    try:
        # Build filters
        filters = {"docstatus": 0}
        if product_family:
            filters["product_family"] = product_family
        if category:
            filters["category"] = category

        # Get products
        products = frappe.get_all(
            "Product Master",
            filters=filters,
            pluck="name",
            limit=500,  # Reasonable limit for statistics
        )

        if not products:
            return _empty_statistics()

        # Get required languages
        required_languages = _get_enabled_languages()
        if not required_languages:
            return _empty_statistics()

        # Calculate statistics
        total_products = len(products)
        fully_translated = 0
        partially_translated = 0
        not_translated = 0
        coverage_sum = 0

        language_stats = {lang: {"total": 0, "complete": 0} for lang in required_languages}
        field_stats = {field: {"total": 0, "complete": 0} for field in DEFAULT_TRANSLATABLE_FIELDS}

        for product in products:
            try:
                gaps = get_missing_translations(product, required_languages)
                coverage = gaps.get("coverage_percentage", 0)
                coverage_sum += coverage

                if coverage >= 100:
                    fully_translated += 1
                elif coverage > 0:
                    partially_translated += 1
                else:
                    not_translated += 1

                # Track by language
                by_language = gaps.get("by_language", {})
                for lang in required_languages:
                    language_stats[lang]["total"] += 1
                    if lang not in by_language:
                        language_stats[lang]["complete"] += 1

                # Track by field
                by_field = gaps.get("by_field", {})
                for field in DEFAULT_TRANSLATABLE_FIELDS:
                    field_stats[field]["total"] += 1
                    if field not in by_field:
                        field_stats[field]["complete"] += 1

            except Exception:
                continue

        # Calculate averages
        average_coverage = flt(coverage_sum / total_products, 2) if total_products > 0 else 0

        # Calculate language coverage percentages
        language_coverage = {}
        for lang, stats in language_stats.items():
            if stats["total"] > 0:
                language_coverage[lang] = flt(
                    (stats["complete"] / stats["total"]) * 100, 2
                )
            else:
                language_coverage[lang] = 100.0

        # Calculate field coverage percentages
        field_coverage = {}
        for field, stats in field_stats.items():
            if stats["total"] > 0:
                field_coverage[field] = flt(
                    (stats["complete"] / stats["total"]) * 100, 2
                )
            else:
                field_coverage[field] = 100.0

        return {
            "total_products": total_products,
            "fully_translated": fully_translated,
            "partially_translated": partially_translated,
            "not_translated": not_translated,
            "average_coverage": average_coverage,
            "by_language": language_coverage,
            "by_field": field_coverage,
            "required_languages": required_languages,
            "required_fields": DEFAULT_TRANSLATABLE_FIELDS,
        }

    except Exception as e:
        import frappe
        frappe.log_error(
            message=f"Error calculating translation statistics: {str(e)}",
            title="PIM Translation Statistics Error"
        )
        return _empty_statistics()


def get_translation_status(product, language):
    """Get translation status for a specific language.

    Returns detailed status of translations for a product
    in a specific language.

    Args:
        product: Product Master name
        language: Language code to check

    Returns:
        dict: Dictionary containing:
            - language: Language code
            - is_complete: Whether all required fields are translated
            - translated_fields: List of fields that are translated
            - missing_fields: List of fields that need translation
            - verified_fields: List of fields with verified translations
            - coverage_percentage: Coverage for this language

    Example:
        >>> status = get_translation_status("PROD-001", "de")
        >>> if status["is_complete"]:
        ...     print("German translation is complete!")
    """
    import frappe

    try:
        if not frappe.db.exists("Product Master", product):
            return _empty_language_status(language)

        product_doc = frappe.get_doc("Product Master", product)
        translations = product_doc.get("product_translations") or []

        translated_fields = []
        verified_fields = []

        for trans in translations:
            if trans.get("language") == language:
                field = trans.get("field_name")
                if field:
                    translated_fields.append(field)
                    if trans.get("is_verified"):
                        verified_fields.append(field)

        missing_fields = [
            f for f in DEFAULT_TRANSLATABLE_FIELDS
            if f not in translated_fields
        ]

        total = len(DEFAULT_TRANSLATABLE_FIELDS)
        present = len([f for f in translated_fields if f in DEFAULT_TRANSLATABLE_FIELDS])
        coverage = 100.0 if total == 0 else round((present / total) * 100, 2)

        return {
            "language": language,
            "is_complete": len(missing_fields) == 0,
            "translated_fields": translated_fields,
            "missing_fields": missing_fields,
            "verified_fields": verified_fields,
            "coverage_percentage": coverage,
            "verified_percentage": round(
                (len(verified_fields) / present) * 100, 2
            ) if present > 0 else 0.0,
        }

    except Exception as e:
        import frappe
        frappe.log_error(
            message=f"Error getting translation status for {product}/{language}: {str(e)}",
            title="PIM Translation Status Error"
        )
        return _empty_language_status(language)


def check_translation_completeness(doc, method=None):
    """Check translation completeness for a product on save.

    This function is designed to be used as a doc_event hook.
    It updates the product's translation coverage score.

    Args:
        doc: The Product Master document being saved
        method: The hook method name (unused, for Frappe hook signature)

    Returns:
        float: Translation coverage percentage

    Example:
        # In hooks.py:
        # doc_events = {
        #     "Product Master": {
        #         "before_save": "frappe_pim.pim.utils.translation.check_translation_completeness"
        #     }
        # }
    """
    import frappe

    try:
        coverage = get_translation_coverage(doc)

        # Update translation score if field exists
        if hasattr(doc, "translation_coverage"):
            doc.translation_coverage = coverage

        # Set a flag if product has translation gaps
        if hasattr(doc, "has_translation_gaps"):
            doc.has_translation_gaps = coverage < 100

        return coverage

    except Exception as e:
        frappe.log_error(
            message=f"Error checking translation completeness for {doc.name}: {str(e)}",
            title="PIM Translation Check Error"
        )
        return 0.0


def generate_translation_report(
    products=None,
    product_family=None,
    category=None,
    language=None,
    output_format="dict",
):
    """Generate a translation gap report.

    Creates a comprehensive report of translation gaps for
    specified products or product filters.

    Args:
        products: List of product names to include (optional)
        product_family: Filter by product family (optional)
        category: Filter by category (optional)
        language: Filter by specific language (optional)
        output_format: Report format - "dict" or "csv" (default: "dict")

    Returns:
        dict or str: Report data as dictionary or CSV string

    Example:
        >>> report = generate_translation_report(language="de")
        >>> for row in report["rows"]:
        ...     print(f"{row['product']}: {row['missing_fields']}")
    """
    import frappe
    from frappe.utils import now_datetime

    try:
        # Get products to analyze
        if products:
            product_list = products
        else:
            filters = {"docstatus": 0}
            if product_family:
                filters["product_family"] = product_family
            if category:
                filters["category"] = category

            product_list = frappe.get_all(
                "Product Master",
                filters=filters,
                pluck="name",
                limit=500,
            )

        if not product_list:
            return _empty_report()

        # Get languages to check
        if language:
            required_languages = [language]
        else:
            required_languages = _get_enabled_languages()

        # Generate report rows
        rows = []
        for product in product_list:
            try:
                gaps = get_missing_translations(product, required_languages)

                if gaps.get("missing"):
                    product_doc = frappe.get_doc("Product Master", product)
                    row = {
                        "product": product,
                        "product_name": product_doc.product_name or product,
                        "product_family": product_doc.get("product_family", ""),
                        "category": product_doc.get("category", ""),
                        "missing_count": len(gaps["missing"]),
                        "coverage_percentage": gaps["coverage_percentage"],
                        "missing_languages": ", ".join(gaps.get("by_language", {}).keys()),
                        "missing_fields": ", ".join(gaps.get("by_field", {}).keys()),
                    }
                    rows.append(row)

            except Exception:
                continue

        # Sort by missing count
        rows.sort(key=lambda x: x["missing_count"], reverse=True)

        report = {
            "generated_at": str(now_datetime()),
            "filters": {
                "product_family": product_family,
                "category": category,
                "language": language,
            },
            "summary": {
                "total_products": len(product_list),
                "products_with_gaps": len(rows),
                "total_missing_translations": sum(r["missing_count"] for r in rows),
            },
            "rows": rows,
        }

        if output_format == "csv":
            return _convert_report_to_csv(report)

        return report

    except Exception as e:
        import frappe
        frappe.log_error(
            message=f"Error generating translation report: {str(e)}",
            title="PIM Translation Report Error"
        )
        return _empty_report()


def get_unverified_translations(product=None, language=None, limit=100):
    """Get translations that are not yet verified.

    Returns translation items that have not been marked as verified,
    useful for translation review workflows.

    Args:
        product: Filter by product (optional)
        language: Filter by language (optional)
        limit: Maximum number of results (default: 100)

    Returns:
        list: List of unverified translation records

    Example:
        >>> unverified = get_unverified_translations(language="fr")
        >>> print(f"{len(unverified)} translations need verification")
    """
    import frappe

    try:
        # Query Product Translation Item child table
        # We need to join through the parent product
        filters = {"is_verified": 0}

        if language:
            filters["language"] = language

        # Get from child table with parent info
        translations = frappe.db.sql("""
            SELECT
                pti.name as translation_id,
                pti.language,
                pti.field_name,
                pti.translated_value,
                pti.translation_source,
                pti.translated_by,
                pti.parent as product,
                pm.product_name
            FROM `tabProduct Translation Item` pti
            INNER JOIN `tabProduct Master` pm ON pti.parent = pm.name
            WHERE pti.is_verified = 0
            {product_filter}
            {language_filter}
            ORDER BY pti.modified DESC
            LIMIT %s
        """.format(
            product_filter="AND pti.parent = %s" if product else "",
            language_filter="AND pti.language = %s" if language else "",
        ), tuple(
            [v for v in [product, language] if v] + [limit]
        ), as_dict=True)

        return translations or []

    except Exception as e:
        import frappe
        frappe.log_error(
            message=f"Error getting unverified translations: {str(e)}",
            title="PIM Unverified Translations Error"
        )
        return []


def bulk_update_translation_status(translations, is_verified=True, verified_by=None):
    """Bulk update verification status for translations.

    Args:
        translations: List of translation record names or dicts with
            {parent, language, field_name}
        is_verified: Whether to mark as verified (default: True)
        verified_by: User who verified (optional, defaults to current user)

    Returns:
        dict: Result with success_count and errors

    Example:
        >>> result = bulk_update_translation_status(
        ...     [{"parent": "PROD-001", "language": "de", "field_name": "Product Name"}],
        ...     is_verified=True
        ... )
    """
    import frappe
    from frappe.utils import today

    try:
        if verified_by is None:
            verified_by = frappe.session.user

        success_count = 0
        errors = []

        for trans in translations:
            try:
                if isinstance(trans, str):
                    # Direct translation name
                    frappe.db.set_value(
                        "Product Translation Item",
                        trans,
                        {
                            "is_verified": 1 if is_verified else 0,
                            "verified_by": verified_by if is_verified else None,
                            "verified_date": today() if is_verified else None,
                        },
                        update_modified=True,
                    )
                else:
                    # Dict with parent, language, field_name
                    parent = trans.get("parent")
                    language = trans.get("language")
                    field_name = trans.get("field_name")

                    if parent and language and field_name:
                        # Find the translation item
                        name = frappe.db.get_value(
                            "Product Translation Item",
                            {
                                "parent": parent,
                                "language": language,
                                "field_name": field_name,
                            },
                            "name",
                        )
                        if name:
                            frappe.db.set_value(
                                "Product Translation Item",
                                name,
                                {
                                    "is_verified": 1 if is_verified else 0,
                                    "verified_by": verified_by if is_verified else None,
                                    "verified_date": today() if is_verified else None,
                                },
                                update_modified=True,
                            )
                            success_count += 1
                        else:
                            errors.append({"item": trans, "error": "Translation not found"})

                success_count += 1

            except Exception as e:
                errors.append({"item": trans, "error": str(e)})

        frappe.db.commit()

        return {
            "success_count": success_count,
            "error_count": len(errors),
            "errors": errors,
        }

    except Exception as e:
        import frappe
        frappe.log_error(
            message=f"Error in bulk translation status update: {str(e)}",
            title="PIM Bulk Translation Update Error"
        )
        return {
            "success_count": 0,
            "error_count": 1,
            "errors": [{"error": str(e)}],
        }


# Private helper functions


def _get_enabled_languages():
    """Get list of enabled language codes from Language DocType.

    Returns:
        list: List of enabled language codes
    """
    import frappe

    try:
        languages = frappe.get_all(
            "Language",
            filters={"enabled": 1},
            pluck="name",
        )
        return languages or []
    except Exception:
        # Fallback to common languages if Language DocType doesn't exist
        return ["en"]


def _build_existing_translations_map(translations):
    """Build a map of existing translations by language|field key.

    Args:
        translations: List of Product Translation Item rows

    Returns:
        set: Set of "language|field" keys for existing translations
    """
    existing = set()
    for trans in translations:
        language = trans.get("language")
        field = trans.get("field_name")
        value = trans.get("translated_value")

        # Only count as translated if there's actual content
        if language and field and value and str(value).strip():
            existing.add(f"{language}|{field}")

    return existing


def _empty_missing_result():
    """Return empty missing translations result structure.

    Returns:
        dict: Empty result dictionary
    """
    return {
        "missing": [],
        "total_required": 0,
        "total_present": 0,
        "coverage_percentage": 100.0,
        "by_language": {},
        "by_field": {},
    }


def _empty_statistics():
    """Return empty statistics result structure.

    Returns:
        dict: Empty statistics dictionary
    """
    return {
        "total_products": 0,
        "fully_translated": 0,
        "partially_translated": 0,
        "not_translated": 0,
        "average_coverage": 0.0,
        "by_language": {},
        "by_field": {},
        "required_languages": [],
        "required_fields": [],
    }


def _empty_language_status(language):
    """Return empty language status result structure.

    Args:
        language: Language code

    Returns:
        dict: Empty status dictionary
    """
    return {
        "language": language,
        "is_complete": False,
        "translated_fields": [],
        "missing_fields": DEFAULT_TRANSLATABLE_FIELDS.copy(),
        "verified_fields": [],
        "coverage_percentage": 0.0,
        "verified_percentage": 0.0,
    }


def _empty_report():
    """Return empty report result structure.

    Returns:
        dict: Empty report dictionary
    """
    return {
        "generated_at": None,
        "filters": {},
        "summary": {
            "total_products": 0,
            "products_with_gaps": 0,
            "total_missing_translations": 0,
        },
        "rows": [],
    }


def _convert_report_to_csv(report):
    """Convert report dictionary to CSV string.

    Args:
        report: Report dictionary

    Returns:
        str: CSV formatted string
    """
    import csv
    from io import StringIO

    output = StringIO()
    writer = csv.writer(output)

    # Write header
    if report.get("rows"):
        headers = list(report["rows"][0].keys())
        writer.writerow(headers)

        # Write data
        for row in report["rows"]:
            writer.writerow([row.get(h, "") for h in headers])

    return output.getvalue()
