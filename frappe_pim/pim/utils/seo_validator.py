"""
SEO Completeness Validation Utility Module

This module provides functions for validating SEO field completeness and quality
for products. It helps ensure products have proper SEO metadata before publishing
and integrates with the overall completeness scoring system.

Key functionality:
- Validate SEO field presence and quality
- Calculate SEO completeness scores
- Identify SEO issues and provide recommendations
- Check optimal length constraints for meta fields
- Generate SEO validation reports

The SEO validation checks the following fields on Product Master:
- seo_meta_title: Optimal 30-60 characters
- seo_meta_description: Optimal 120-160 characters
- seo_meta_keywords: Optimal 3-10 comma-separated keywords
- seo_canonical_url: Valid URL format

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""


# SEO field configurations with optimal lengths and requirements
SEO_FIELDS = {
    "seo_meta_title": {
        "label": "Meta Title",
        "required": True,
        "min_length": 30,
        "max_length": 60,
        "optimal_message": "30-60 characters recommended",
    },
    "seo_meta_description": {
        "label": "Meta Description",
        "required": True,
        "min_length": 120,
        "max_length": 160,
        "optimal_message": "120-160 characters recommended",
    },
    "seo_meta_keywords": {
        "label": "Meta Keywords",
        "required": True,
        "min_keywords": 3,
        "max_keywords": 10,
        "optimal_message": "3-10 keywords recommended",
    },
    "seo_canonical_url": {
        "label": "Canonical URL",
        "required": False,
        "optimal_message": "Set if product has multiple URLs",
    },
}

# Required SEO fields for completeness calculation
REQUIRED_SEO_FIELDS = ["seo_meta_title", "seo_meta_description", "seo_meta_keywords"]

# Issue severity levels
SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"


def validate_seo_fields(doc, method=None):
    """Validate SEO fields for a Product Master on save.

    This function is designed to be used as a doc_event hook.
    It checks SEO field presence and quality, updating the
    document's SEO-related scores if fields exist.

    Args:
        doc: The Product Master document being saved
        method: The hook method name (unused, for Frappe hook signature)

    Returns:
        dict: Validation result with:
            - is_valid: Boolean indicating all required fields are present
            - score: SEO completeness score (0-100)
            - issues: List of validation issues found

    Example:
        # In hooks.py:
        # doc_events = {
        #     "Product Master": {
        #         "before_save": "frappe_pim.pim.utils.seo_validator.validate_seo_fields"
        #     }
        # }
    """
    import frappe

    try:
        result = get_seo_validation_result(doc)

        # Update SEO score on document if field exists
        if hasattr(doc, "seo_score"):
            doc.seo_score = result.get("score", 0)

        # Set SEO completeness flag if field exists
        if hasattr(doc, "is_seo_complete"):
            doc.is_seo_complete = result.get("is_valid", False)

        # Set a flag if product has SEO issues
        if hasattr(doc, "has_seo_issues"):
            doc.has_seo_issues = len(result.get("issues", [])) > 0

        return result

    except Exception as e:
        frappe.log_error(
            message=f"Error validating SEO fields for {doc.name}: {str(e)}",
            title="PIM SEO Validation Error"
        )
        return {
            "is_valid": False,
            "score": 0,
            "issues": [{"field": "general", "severity": SEVERITY_ERROR, "message": str(e)}],
        }


def get_seo_completeness(product):
    """Get SEO completeness percentage for a product.

    A convenience function that returns just the SEO completeness score
    for a product's SEO metadata fields.

    Args:
        product: Product Master name (str) or Product Master document

    Returns:
        float: SEO completeness score from 0.0 to 100.0

    Example:
        >>> score = get_seo_completeness("PROD-001")
        >>> print(f"Product SEO is {score}% complete")
    """
    result = get_seo_validation_result(product)
    return result.get("score", 0.0)


def get_seo_validation_result(product):
    """Get comprehensive SEO validation result for a product.

    Performs a full SEO validation including completeness check,
    quality assessment, and issue identification.

    Args:
        product: Product Master name (str) or Product Master document

    Returns:
        dict: Validation result containing:
            - product: Product name
            - is_valid: Whether all required SEO fields are properly filled
            - score: Overall SEO score (0-100)
            - completeness_score: Score for field presence (0-100)
            - quality_score: Score for field quality (0-100)
            - fields: Dict of individual field statuses
            - issues: List of validation issues with severity
            - recommendations: List of improvement suggestions

    Example:
        >>> result = get_seo_validation_result("PROD-001")
        >>> if not result["is_valid"]:
        ...     for issue in result["issues"]:
        ...         print(f"{issue['severity']}: {issue['message']}")
    """
    import frappe

    try:
        # Get product document
        if isinstance(product, str):
            product_name = product
            if not frappe.db.exists("Product Master", product_name):
                return _empty_validation_result(product_name)
            product_doc = frappe.get_doc("Product Master", product_name)
        else:
            product_doc = product
            product_name = product_doc.name

        # Validate each SEO field
        fields = {}
        issues = []
        recommendations = []
        completeness_points = 0
        quality_points = 0
        total_required = len(REQUIRED_SEO_FIELDS)

        for field_name, config in SEO_FIELDS.items():
            field_result = _validate_single_field(product_doc, field_name, config)
            fields[field_name] = field_result

            # Add issues from this field
            issues.extend(field_result.get("issues", []))

            # Add recommendations from this field
            if field_result.get("recommendation"):
                recommendations.append(field_result["recommendation"])

            # Calculate completeness (only for required fields)
            if config.get("required", False):
                if field_result.get("is_present"):
                    completeness_points += 1
                if field_result.get("quality_score", 0) > 0:
                    quality_points += field_result["quality_score"]

        # Calculate scores
        completeness_score = round((completeness_points / total_required) * 100, 2) if total_required > 0 else 100.0
        quality_score = round(quality_points / total_required, 2) if total_required > 0 else 100.0

        # Overall score is weighted average (60% completeness, 40% quality)
        overall_score = round((completeness_score * 0.6) + (quality_score * 0.4), 2)

        # Determine if valid (all required fields present with acceptable quality)
        is_valid = completeness_score >= 100 and quality_score >= 50

        return {
            "product": product_name,
            "is_valid": is_valid,
            "score": overall_score,
            "completeness_score": completeness_score,
            "quality_score": quality_score,
            "fields": fields,
            "issues": issues,
            "recommendations": recommendations,
        }

    except Exception as e:
        import frappe
        frappe.log_error(
            message=f"Error getting SEO validation result for {product}: {str(e)}",
            title="PIM SEO Validation Error"
        )
        return _empty_validation_result(str(product))


def get_seo_issues(product):
    """Get list of SEO issues for a product.

    Returns a detailed list of SEO issues including severity,
    field, and recommended action.

    Args:
        product: Product Master name (str) or Product Master document

    Returns:
        list: List of issue dicts containing:
            - field: Field name with the issue
            - severity: error, warning, or info
            - message: Description of the issue
            - current_value: Current value (if applicable)
            - recommendation: Suggested fix

    Example:
        >>> issues = get_seo_issues("PROD-001")
        >>> errors = [i for i in issues if i["severity"] == "error"]
        >>> print(f"Found {len(errors)} critical SEO issues")
    """
    result = get_seo_validation_result(product)
    return result.get("issues", [])


def get_seo_recommendations(product):
    """Get SEO improvement recommendations for a product.

    Returns actionable recommendations for improving the product's
    SEO metadata quality.

    Args:
        product: Product Master name (str) or Product Master document

    Returns:
        list: List of recommendation strings

    Example:
        >>> recommendations = get_seo_recommendations("PROD-001")
        >>> for rec in recommendations:
        ...     print(f"- {rec}")
    """
    result = get_seo_validation_result(product)
    return result.get("recommendations", [])


def check_seo_quality(product):
    """Check SEO quality and return a quality grade.

    Evaluates the overall quality of SEO metadata and returns
    a letter grade (A-F) along with the score.

    Args:
        product: Product Master name (str) or Product Master document

    Returns:
        dict: Quality assessment containing:
            - grade: Letter grade (A, B, C, D, F)
            - score: Numeric score (0-100)
            - summary: Brief quality summary
            - breakdown: Dict of component scores

    Example:
        >>> quality = check_seo_quality("PROD-001")
        >>> print(f"SEO Grade: {quality['grade']} ({quality['score']})")
    """
    result = get_seo_validation_result(product)
    score = result.get("score", 0)

    # Determine grade
    if score >= 90:
        grade = "A"
        summary = "Excellent SEO metadata"
    elif score >= 80:
        grade = "B"
        summary = "Good SEO metadata with minor improvements possible"
    elif score >= 70:
        grade = "C"
        summary = "Average SEO metadata, improvements recommended"
    elif score >= 60:
        grade = "D"
        summary = "Below average SEO, significant improvements needed"
    else:
        grade = "F"
        summary = "Poor SEO metadata, immediate attention required"

    return {
        "grade": grade,
        "score": score,
        "summary": summary,
        "breakdown": {
            "completeness_score": result.get("completeness_score", 0),
            "quality_score": result.get("quality_score", 0),
        },
        "issues_count": len(result.get("issues", [])),
        "recommendations_count": len(result.get("recommendations", [])),
    }


def get_products_with_seo_issues(
    min_issues=1,
    severity=None,
    product_family=None,
    category=None,
    limit=100,
):
    """Get products that have SEO issues.

    Scans products and identifies those with incomplete or
    poor quality SEO metadata.

    Args:
        min_issues: Minimum number of issues to include a product (default: 1)
        severity: Filter by issue severity (error, warning, info)
        product_family: Filter by product family (optional)
        category: Filter by category (optional)
        limit: Maximum number of products to return (default: 100)

    Returns:
        list: List of dicts containing:
            - product: Product Master name
            - product_name: Display name
            - score: SEO score
            - grade: Letter grade
            - issues_count: Number of issues
            - errors_count: Number of error-level issues
            - warnings_count: Number of warning-level issues

    Example:
        >>> products = get_products_with_seo_issues(severity="error")
        >>> for p in products:
        ...     print(f"{p['product']}: {p['errors_count']} errors")
    """
    import frappe

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
            fields=["name", "product_name", "product_family", "category"],
            limit=limit * 2,  # Get extra since we'll filter
        )

        if not products:
            return []

        # Check each product
        results = []
        for product in products:
            try:
                validation = get_seo_validation_result(product["name"])
                issues = validation.get("issues", [])

                # Filter by severity if specified
                if severity:
                    issues = [i for i in issues if i.get("severity") == severity]

                if len(issues) >= min_issues:
                    quality = check_seo_quality(product["name"])
                    all_issues = validation.get("issues", [])

                    results.append({
                        "product": product["name"],
                        "product_name": product.get("product_name", product["name"]),
                        "product_family": product.get("product_family"),
                        "category": product.get("category"),
                        "score": validation.get("score", 0),
                        "grade": quality.get("grade", "F"),
                        "issues_count": len(all_issues),
                        "errors_count": len([i for i in all_issues if i.get("severity") == SEVERITY_ERROR]),
                        "warnings_count": len([i for i in all_issues if i.get("severity") == SEVERITY_WARNING]),
                    })

                    if len(results) >= limit:
                        break

            except Exception:
                continue

        # Sort by score (lowest first - most issues)
        results.sort(key=lambda x: x["score"])

        return results

    except Exception as e:
        import frappe
        frappe.log_error(
            message=f"Error getting products with SEO issues: {str(e)}",
            title="PIM SEO Scan Error"
        )
        return []


def get_seo_statistics(product_family=None, category=None):
    """Get SEO statistics across products.

    Calculates aggregate SEO metrics for products,
    optionally filtered by family or category.

    Args:
        product_family: Filter by product family (optional)
        category: Filter by category (optional)

    Returns:
        dict: Dictionary containing:
            - total_products: Number of products analyzed
            - fully_optimized: Products with score >= 90
            - needs_improvement: Products with score 60-89
            - critical: Products with score < 60
            - average_score: Average SEO score
            - by_field: Dict with completion rates per field
            - grade_distribution: Dict with count per grade

    Example:
        >>> stats = get_seo_statistics(product_family="Electronics")
        >>> print(f"Average SEO score: {stats['average_score']}%")
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
            limit=500,
        )

        if not products:
            return _empty_statistics()

        # Calculate statistics
        total_products = len(products)
        fully_optimized = 0
        needs_improvement = 0
        critical = 0
        score_sum = 0

        grade_distribution = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
        field_completion = {field: 0 for field in SEO_FIELDS.keys()}

        for product in products:
            try:
                validation = get_seo_validation_result(product)
                score = validation.get("score", 0)
                score_sum += score

                # Track categories
                if score >= 90:
                    fully_optimized += 1
                elif score >= 60:
                    needs_improvement += 1
                else:
                    critical += 1

                # Track grade distribution
                quality = check_seo_quality(product)
                grade = quality.get("grade", "F")
                grade_distribution[grade] += 1

                # Track field completion
                fields = validation.get("fields", {})
                for field_name, field_status in fields.items():
                    if field_status.get("is_present"):
                        field_completion[field_name] += 1

            except Exception:
                continue

        # Calculate averages
        average_score = flt(score_sum / total_products, 2) if total_products > 0 else 0

        # Calculate field completion rates
        field_rates = {}
        for field_name, count in field_completion.items():
            field_rates[field_name] = flt((count / total_products) * 100, 2) if total_products > 0 else 0

        return {
            "total_products": total_products,
            "fully_optimized": fully_optimized,
            "needs_improvement": needs_improvement,
            "critical": critical,
            "average_score": average_score,
            "by_field": field_rates,
            "grade_distribution": grade_distribution,
        }

    except Exception as e:
        import frappe
        frappe.log_error(
            message=f"Error calculating SEO statistics: {str(e)}",
            title="PIM SEO Statistics Error"
        )
        return _empty_statistics()


def generate_seo_report(
    products=None,
    product_family=None,
    category=None,
    include_details=True,
    output_format="dict",
):
    """Generate an SEO audit report.

    Creates a comprehensive report of SEO status and issues for
    specified products or product filters.

    Args:
        products: List of product names to include (optional)
        product_family: Filter by product family (optional)
        category: Filter by category (optional)
        include_details: Include detailed field-level info (default: True)
        output_format: Report format - "dict" or "csv" (default: "dict")

    Returns:
        dict or str: Report data as dictionary or CSV string

    Example:
        >>> report = generate_seo_report(product_family="Electronics")
        >>> for row in report["rows"]:
        ...     print(f"{row['product']}: Grade {row['grade']}")
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

        # Generate report rows
        rows = []
        for product in product_list:
            try:
                validation = get_seo_validation_result(product)
                quality = check_seo_quality(product)
                product_doc = frappe.get_doc("Product Master", product)

                row = {
                    "product": product,
                    "product_name": product_doc.product_name or product,
                    "product_family": product_doc.get("product_family", ""),
                    "category": product_doc.get("category", ""),
                    "score": validation.get("score", 0),
                    "grade": quality.get("grade", "F"),
                    "completeness_score": validation.get("completeness_score", 0),
                    "quality_score": validation.get("quality_score", 0),
                    "issues_count": len(validation.get("issues", [])),
                    "is_valid": validation.get("is_valid", False),
                }

                if include_details:
                    fields = validation.get("fields", {})
                    for field_name in SEO_FIELDS.keys():
                        field_status = fields.get(field_name, {})
                        row[f"{field_name}_present"] = field_status.get("is_present", False)
                        row[f"{field_name}_score"] = field_status.get("quality_score", 0)

                rows.append(row)

            except Exception:
                continue

        # Sort by score (lowest first)
        rows.sort(key=lambda x: x["score"])

        # Calculate summary statistics
        total = len(rows)
        stats = get_seo_statistics(product_family, category) if total > 0 else _empty_statistics()

        report = {
            "generated_at": str(now_datetime()),
            "filters": {
                "product_family": product_family,
                "category": category,
                "products": products,
            },
            "summary": {
                "total_products": total,
                "average_score": stats.get("average_score", 0),
                "fully_optimized": stats.get("fully_optimized", 0),
                "needs_improvement": stats.get("needs_improvement", 0),
                "critical": stats.get("critical", 0),
                "grade_distribution": stats.get("grade_distribution", {}),
            },
            "rows": rows,
        }

        if output_format == "csv":
            return _convert_report_to_csv(report)

        return report

    except Exception as e:
        import frappe
        frappe.log_error(
            message=f"Error generating SEO report: {str(e)}",
            title="PIM SEO Report Error"
        )
        return _empty_report()


def bulk_check_seo(products):
    """Check SEO for multiple products at once.

    Efficiently validates SEO for a list of products and returns
    aggregated results.

    Args:
        products: List of Product Master names

    Returns:
        dict: Results containing:
            - valid_count: Number of products with valid SEO
            - invalid_count: Number of products with invalid SEO
            - average_score: Average SEO score
            - products: Dict mapping product name to validation result

    Example:
        >>> results = bulk_check_seo(["PROD-001", "PROD-002", "PROD-003"])
        >>> print(f"{results['valid_count']} products have valid SEO")
    """
    import frappe
    from frappe.utils import flt

    try:
        valid_count = 0
        invalid_count = 0
        score_sum = 0
        product_results = {}

        for product in products:
            try:
                validation = get_seo_validation_result(product)
                product_results[product] = {
                    "is_valid": validation.get("is_valid", False),
                    "score": validation.get("score", 0),
                    "issues_count": len(validation.get("issues", [])),
                }

                if validation.get("is_valid"):
                    valid_count += 1
                else:
                    invalid_count += 1

                score_sum += validation.get("score", 0)

            except Exception:
                invalid_count += 1
                product_results[product] = {
                    "is_valid": False,
                    "score": 0,
                    "error": "Validation failed",
                }

        total = len(products)
        average_score = flt(score_sum / total, 2) if total > 0 else 0

        return {
            "total_count": total,
            "valid_count": valid_count,
            "invalid_count": invalid_count,
            "average_score": average_score,
            "products": product_results,
        }

    except Exception as e:
        import frappe
        frappe.log_error(
            message=f"Error in bulk SEO check: {str(e)}",
            title="PIM Bulk SEO Check Error"
        )
        return {
            "total_count": len(products),
            "valid_count": 0,
            "invalid_count": len(products),
            "average_score": 0,
            "products": {},
            "error": str(e),
        }


# Private helper functions


def _validate_single_field(product_doc, field_name, config):
    """Validate a single SEO field.

    Args:
        product_doc: Product Master document
        field_name: Name of the field to validate
        config: Field configuration from SEO_FIELDS

    Returns:
        dict: Field validation result
    """
    value = getattr(product_doc, field_name, None)
    is_present = bool(value and str(value).strip())
    issues = []
    recommendation = None
    quality_score = 0

    if not is_present:
        if config.get("required"):
            issues.append({
                "field": field_name,
                "severity": SEVERITY_ERROR,
                "message": f"{config['label']} is required but missing",
                "current_value": None,
                "recommendation": f"Add {config['label']} - {config.get('optimal_message', '')}",
            })
            recommendation = f"Add {config['label']}"
        else:
            issues.append({
                "field": field_name,
                "severity": SEVERITY_INFO,
                "message": f"{config['label']} is not set",
                "current_value": None,
                "recommendation": config.get("optimal_message"),
            })
    else:
        # Validate based on field type
        if field_name == "seo_meta_keywords":
            quality_score, field_issues = _validate_keywords(value, config)
        elif field_name == "seo_canonical_url":
            quality_score, field_issues = _validate_url(value, config)
        else:
            quality_score, field_issues = _validate_text_length(value, config)

        issues.extend(field_issues)

        # Add recommendation if quality is not optimal
        if quality_score < 80:
            recommendation = config.get("optimal_message")

    return {
        "field_name": field_name,
        "label": config.get("label"),
        "is_present": is_present,
        "value": value if is_present else None,
        "quality_score": quality_score,
        "issues": issues,
        "recommendation": recommendation,
    }


def _validate_text_length(value, config):
    """Validate text field length against optimal range.

    Args:
        value: Field value
        config: Field configuration

    Returns:
        tuple: (quality_score, issues_list)
    """
    issues = []
    value_str = str(value).strip()
    length = len(value_str)

    min_length = config.get("min_length", 0)
    max_length = config.get("max_length", 999)

    if min_length <= length <= max_length:
        quality_score = 100
    elif length < min_length:
        # Too short
        ratio = length / min_length if min_length > 0 else 0
        quality_score = max(30, int(ratio * 100))
        issues.append({
            "field": config.get("label"),
            "severity": SEVERITY_WARNING,
            "message": f"{config['label']} is too short ({length} characters). Minimum recommended: {min_length}",
            "current_value": length,
            "recommendation": f"Expand to at least {min_length} characters",
        })
    else:
        # Too long
        overage = length - max_length
        penalty = min(50, overage // 5)
        quality_score = max(50, 100 - penalty)
        issues.append({
            "field": config.get("label"),
            "severity": SEVERITY_WARNING,
            "message": f"{config['label']} is too long ({length} characters). Maximum recommended: {max_length}",
            "current_value": length,
            "recommendation": f"Shorten to {max_length} characters or less",
        })

    # Check for placeholder text
    placeholders = ["lorem ipsum", "test", "placeholder", "tbd", "n/a", "xxx", "todo"]
    lower_value = value_str.lower()
    for placeholder in placeholders:
        if placeholder in lower_value:
            quality_score = min(quality_score, 20)
            issues.append({
                "field": config.get("label"),
                "severity": SEVERITY_ERROR,
                "message": f"{config['label']} contains placeholder text",
                "current_value": value_str[:50],
                "recommendation": "Replace placeholder with actual content",
            })
            break

    return quality_score, issues


def _validate_keywords(value, config):
    """Validate meta keywords field.

    Args:
        value: Keywords string (comma-separated)
        config: Field configuration

    Returns:
        tuple: (quality_score, issues_list)
    """
    issues = []
    keywords = [k.strip() for k in str(value).split(",") if k.strip()]
    keyword_count = len(keywords)

    min_keywords = config.get("min_keywords", 3)
    max_keywords = config.get("max_keywords", 10)

    if min_keywords <= keyword_count <= max_keywords:
        quality_score = 100
    elif keyword_count < min_keywords:
        ratio = keyword_count / min_keywords if min_keywords > 0 else 0
        quality_score = max(30, int(ratio * 100))
        issues.append({
            "field": config.get("label"),
            "severity": SEVERITY_WARNING,
            "message": f"Too few keywords ({keyword_count}). Minimum recommended: {min_keywords}",
            "current_value": keyword_count,
            "recommendation": f"Add more keywords (target: {min_keywords}-{max_keywords})",
        })
    else:
        # Too many keywords
        overage = keyword_count - max_keywords
        penalty = min(40, overage * 5)
        quality_score = max(60, 100 - penalty)
        issues.append({
            "field": config.get("label"),
            "severity": SEVERITY_WARNING,
            "message": f"Too many keywords ({keyword_count}). Maximum recommended: {max_keywords}",
            "current_value": keyword_count,
            "recommendation": f"Reduce to {max_keywords} most relevant keywords",
        })

    # Check for duplicate keywords
    unique_keywords = set(k.lower() for k in keywords)
    if len(unique_keywords) < len(keywords):
        quality_score = min(quality_score, 70)
        issues.append({
            "field": config.get("label"),
            "severity": SEVERITY_WARNING,
            "message": "Contains duplicate keywords",
            "current_value": keyword_count - len(unique_keywords),
            "recommendation": "Remove duplicate keywords",
        })

    # Check for very short keywords
    short_keywords = [k for k in keywords if len(k) < 3]
    if short_keywords:
        quality_score = min(quality_score, 80)
        issues.append({
            "field": config.get("label"),
            "severity": SEVERITY_INFO,
            "message": f"Contains very short keywords: {', '.join(short_keywords)}",
            "current_value": len(short_keywords),
            "recommendation": "Consider using more descriptive keywords",
        })

    return quality_score, issues


def _validate_url(value, config):
    """Validate URL field.

    Args:
        value: URL string
        config: Field configuration

    Returns:
        tuple: (quality_score, issues_list)
    """
    import re

    issues = []
    value_str = str(value).strip()

    # Basic URL pattern validation
    url_pattern = re.compile(
        r'^https?://'  # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain
        r'localhost|'  # localhost
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # or ip
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE
    )

    if url_pattern.match(value_str):
        quality_score = 100

        # Check for HTTPS preference
        if not value_str.startswith("https://"):
            quality_score = 90
            issues.append({
                "field": config.get("label"),
                "severity": SEVERITY_INFO,
                "message": "URL uses HTTP instead of HTTPS",
                "current_value": value_str,
                "recommendation": "Consider using HTTPS for better security",
            })
    else:
        quality_score = 30
        issues.append({
            "field": config.get("label"),
            "severity": SEVERITY_ERROR,
            "message": "Invalid URL format",
            "current_value": value_str,
            "recommendation": "Use a valid URL starting with http:// or https://",
        })

    return quality_score, issues


def _empty_validation_result(product_name=None):
    """Return empty validation result structure.

    Args:
        product_name: Product name for the result

    Returns:
        dict: Empty validation result dictionary
    """
    return {
        "product": product_name,
        "is_valid": False,
        "score": 0,
        "completeness_score": 0,
        "quality_score": 0,
        "fields": {},
        "issues": [],
        "recommendations": [],
    }


def _empty_statistics():
    """Return empty statistics result structure.

    Returns:
        dict: Empty statistics dictionary
    """
    return {
        "total_products": 0,
        "fully_optimized": 0,
        "needs_improvement": 0,
        "critical": 0,
        "average_score": 0.0,
        "by_field": {},
        "grade_distribution": {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0},
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
            "average_score": 0,
            "fully_optimized": 0,
            "needs_improvement": 0,
            "critical": 0,
            "grade_distribution": {},
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
