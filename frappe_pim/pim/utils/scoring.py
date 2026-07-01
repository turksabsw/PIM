"""
Product Scoring Utility Module

This module provides functions for calculating product scores across multiple dimensions:
- Content completeness and quality
- Media completeness and quality
- SEO optimization
- Translation coverage and quality
- Attribute completeness and quality
- Market performance metrics

All scores are normalized to 0-100 scale.
"""


# Default weights for score calculation
DEFAULT_WEIGHTS = {
    "content_weight": 20,
    "media_weight": 15,
    "seo_weight": 15,
    "translation_weight": 15,
    "attribute_weight": 20,
    "market_weight": 15,
}

# Required fields for completeness calculations
REQUIRED_CONTENT_FIELDS = [
    "product_name",
    "short_description",
    "long_description",
]

REQUIRED_SEO_FIELDS = [
    "seo_meta_title",
    "seo_meta_description",
    "seo_meta_keywords",
]

# Threshold values
SEO_META_TITLE_MAX_LENGTH = 60
SEO_META_TITLE_MIN_LENGTH = 30
SEO_META_DESCRIPTION_MAX_LENGTH = 160
SEO_META_DESCRIPTION_MIN_LENGTH = 120


def calculate_product_score(product, method=None):
    """Calculate comprehensive product score across all dimensions.

    This is the main entry point for product scoring. It calculates scores
    for content, media, SEO, translations, attributes, and market metrics,
    then returns a dictionary with all component scores.

    Args:
        product: Product Master name (str) or Product Master document
        method: Calculation method identifier (optional)

    Returns:
        dict: Dictionary containing all calculated scores:
            - overall_score: Weighted average of all components
            - content_completeness_score: Score for content field completion
            - content_quality_score: Score for content quality
            - media_completeness_score: Score for media presence
            - media_quality_score: Score for media quality
            - seo_score: Overall SEO score
            - seo_meta_title_score: Score for meta title optimization
            - translation_coverage_score: Score for translation completeness
            - translation_quality_score: Score for translation quality
            - attribute_completeness_score: Score for attribute field completion
            - attribute_quality_score: Score for attribute data quality
            - data_accuracy_score: Score for data accuracy
            - data_consistency_score: Score for data consistency
            - market_performance_score: Market performance metric
            - customer_satisfaction_score: Customer satisfaction metric
            - competitive_position_score: Competitive positioning metric
            - feedback_sentiment_score: Customer feedback sentiment
            - weights: Default weight configuration used

    Raises:
        Exception: If product doesn't exist or calculation fails

    Example:
        >>> scores = calculate_product_score("PROD-001")
        >>> print(scores["overall_score"])
        75.5
    """
    import frappe
    from frappe.utils import flt

    try:
        # Get product document
        if isinstance(product, str):
            product_name = product
            if not frappe.db.exists("Product Master", product_name):
                frappe.throw(f"Product {product_name} does not exist")
            product_doc = frappe.get_doc("Product Master", product_name)
        else:
            product_doc = product
            product_name = product_doc.name

        # Calculate all component scores
        content_scores = calculate_content_score(product_doc)
        media_scores = calculate_media_score(product_doc)
        seo_scores = calculate_seo_score(product_doc)
        translation_scores = calculate_translation_score(product_doc)
        attribute_scores = calculate_attribute_score(product_doc)
        market_scores = calculate_market_score(product_doc)

        # Compile all scores
        scores = {
            # Content scores
            "content_completeness_score": content_scores.get("completeness", 0),
            "content_quality_score": content_scores.get("quality", 0),
            # Media scores
            "media_completeness_score": media_scores.get("completeness", 0),
            "media_quality_score": media_scores.get("quality", 0),
            # SEO scores
            "seo_score": seo_scores.get("overall", 0),
            "seo_meta_title_score": seo_scores.get("meta_title", 0),
            # Translation scores
            "translation_coverage_score": translation_scores.get("coverage", 0),
            "translation_quality_score": translation_scores.get("quality", 0),
            # Attribute scores
            "attribute_completeness_score": attribute_scores.get("completeness", 0),
            "attribute_quality_score": attribute_scores.get("quality", 0),
            "data_accuracy_score": attribute_scores.get("accuracy", 0),
            "data_consistency_score": attribute_scores.get("consistency", 0),
            # Market scores
            "market_performance_score": market_scores.get("performance", 0),
            "customer_satisfaction_score": market_scores.get("satisfaction", 0),
            "competitive_position_score": market_scores.get("competitive", 0),
            "feedback_sentiment_score": market_scores.get("sentiment", 0),
            # Weights
            "content_weight": DEFAULT_WEIGHTS["content_weight"],
            "media_weight": DEFAULT_WEIGHTS["media_weight"],
            "seo_weight": DEFAULT_WEIGHTS["seo_weight"],
            "translation_weight": DEFAULT_WEIGHTS["translation_weight"],
            "attribute_weight": DEFAULT_WEIGHTS["attribute_weight"],
            "market_weight": DEFAULT_WEIGHTS["market_weight"],
        }

        # Calculate overall weighted score
        scores["overall_score"] = calculate_weighted_score(scores)

        return scores

    except Exception as e:
        import frappe
        frappe.log_error(
            message=f"Error calculating product score for {product}: {str(e)}",
            title="PIM Scoring Error"
        )
        # Return default scores on error
        return get_default_scores()


def calculate_content_score(product_doc):
    """Calculate content completeness and quality scores.

    Evaluates the presence and quality of text content fields like
    product name, descriptions, and other text-based information.

    Args:
        product_doc: Product Master document

    Returns:
        dict: Dictionary with 'completeness' and 'quality' scores (0-100)
    """
    import frappe
    from frappe.utils import flt

    try:
        completeness_score = 0
        quality_score = 0
        total_fields = 0
        filled_fields = 0
        quality_points = 0

        # Check required content fields
        for field in REQUIRED_CONTENT_FIELDS:
            total_fields += 1
            value = getattr(product_doc, field, None)
            if value and str(value).strip():
                filled_fields += 1
                # Evaluate quality based on length
                quality_points += evaluate_content_quality(field, value)

        # Calculate completeness percentage
        if total_fields > 0:
            completeness_score = flt((filled_fields / total_fields) * 100, 2)

        # Check for additional content fields if they exist
        additional_content_fields = [
            "marketing_text", "technical_specifications",
            "usage_instructions", "warnings"
        ]

        additional_total = 0
        additional_filled = 0
        for field in additional_content_fields:
            if hasattr(product_doc, field):
                additional_total += 1
                value = getattr(product_doc, field, None)
                if value and str(value).strip():
                    additional_filled += 1
                    quality_points += evaluate_content_quality(field, value)

        # Combine required and additional for final completeness
        total_all = total_fields + additional_total
        filled_all = filled_fields + additional_filled
        if total_all > 0:
            completeness_score = flt((filled_all / total_all) * 100, 2)

        # Calculate quality score from quality points
        max_quality_points = (total_fields + additional_total) * 100
        if max_quality_points > 0:
            quality_score = flt((quality_points / max_quality_points) * 100, 2)

        return {
            "completeness": min(completeness_score, 100),
            "quality": min(quality_score, 100)
        }

    except Exception as e:
        import frappe
        frappe.log_error(
            message=f"Error calculating content score: {str(e)}",
            title="PIM Content Score Error"
        )
        return {"completeness": 0, "quality": 0}


def evaluate_content_quality(field, value):
    """Evaluate quality of a content field value.

    Quality is based on:
    - Length (not too short, not excessively long)
    - Presence of meaningful content (not just placeholders)
    - Proper formatting

    Args:
        field: Field name
        value: Field value

    Returns:
        int: Quality points (0-100)
    """
    if not value:
        return 0

    value = str(value).strip()
    points = 0

    # Check for placeholder text
    placeholders = ["lorem ipsum", "test", "placeholder", "tbd", "n/a", "xxx"]
    lower_value = value.lower()
    for placeholder in placeholders:
        if placeholder in lower_value:
            return 20  # Low quality for placeholder text

    # Length-based scoring
    length = len(value)

    if field == "product_name":
        if 5 <= length <= 100:
            points = 100
        elif 3 <= length < 5:
            points = 60
        elif length > 100:
            points = 80
        else:
            points = 40

    elif field == "short_description":
        if 50 <= length <= 300:
            points = 100
        elif 20 <= length < 50:
            points = 70
        elif length > 300:
            points = 80
        else:
            points = 40

    elif field == "long_description":
        if length >= 200:
            points = 100
        elif 100 <= length < 200:
            points = 80
        elif 50 <= length < 100:
            points = 60
        else:
            points = 40

    else:
        # Generic quality scoring for other fields
        if length >= 50:
            points = 100
        elif length >= 20:
            points = 70
        else:
            points = 50

    return points


def calculate_media_score(product_doc):
    """Calculate media completeness and quality scores.

    Evaluates the presence and quality of media assets like
    images, videos, and documents attached to the product.

    Args:
        product_doc: Product Master document

    Returns:
        dict: Dictionary with 'completeness' and 'quality' scores (0-100)
    """
    import frappe
    from frappe.utils import flt

    try:
        completeness_score = 0
        quality_score = 0

        # Check for media table
        media_count = 0
        has_primary_image = False

        # Check product_media child table if exists
        if hasattr(product_doc, "product_media") and product_doc.product_media:
            media_count = len(product_doc.product_media)
            for media in product_doc.product_media:
                if getattr(media, "is_primary", False):
                    has_primary_image = True
                    break

        # Check main image field
        if hasattr(product_doc, "image") and product_doc.image:
            has_primary_image = True
            if media_count == 0:
                media_count = 1

        # Completeness based on media presence
        if media_count >= 5:
            completeness_score = 100
        elif media_count >= 3:
            completeness_score = 80
        elif media_count >= 1:
            completeness_score = 60
        else:
            completeness_score = 0

        # Quality based on having primary image and multiple views
        if has_primary_image:
            quality_score = 50
            if media_count >= 3:
                quality_score = 80
            if media_count >= 5:
                quality_score = 100
        elif media_count > 0:
            quality_score = 30

        return {
            "completeness": min(completeness_score, 100),
            "quality": min(quality_score, 100)
        }

    except Exception as e:
        import frappe
        frappe.log_error(
            message=f"Error calculating media score: {str(e)}",
            title="PIM Media Score Error"
        )
        return {"completeness": 0, "quality": 0}


def calculate_seo_score(product_doc):
    """Calculate SEO optimization scores.

    Evaluates SEO metadata fields for completeness and optimization
    including meta title, meta description, and meta keywords.

    Args:
        product_doc: Product Master document

    Returns:
        dict: Dictionary with 'overall' and 'meta_title' scores (0-100)
    """
    import frappe
    from frappe.utils import flt

    try:
        overall_score = 0
        meta_title_score = 0
        scores_count = 0
        total_score = 0

        # Check meta title
        meta_title = getattr(product_doc, "seo_meta_title", None)
        if meta_title:
            meta_title_score = evaluate_meta_title(meta_title)
            total_score += meta_title_score
            scores_count += 1
        else:
            scores_count += 1

        # Check meta description
        meta_desc = getattr(product_doc, "seo_meta_description", None)
        if meta_desc:
            desc_score = evaluate_meta_description(meta_desc)
            total_score += desc_score
            scores_count += 1
        else:
            scores_count += 1

        # Check meta keywords
        meta_keywords = getattr(product_doc, "seo_meta_keywords", None)
        if meta_keywords:
            keywords_score = evaluate_meta_keywords(meta_keywords)
            total_score += keywords_score
            scores_count += 1
        else:
            scores_count += 1

        # Check canonical URL if exists
        canonical = getattr(product_doc, "seo_canonical_url", None)
        if hasattr(product_doc, "seo_canonical_url"):
            if canonical:
                total_score += 100
            scores_count += 1

        # Calculate overall SEO score
        if scores_count > 0:
            overall_score = flt(total_score / scores_count, 2)

        return {
            "overall": min(overall_score, 100),
            "meta_title": min(meta_title_score, 100)
        }

    except Exception as e:
        import frappe
        frappe.log_error(
            message=f"Error calculating SEO score: {str(e)}",
            title="PIM SEO Score Error"
        )
        return {"overall": 0, "meta_title": 0}


def evaluate_meta_title(value):
    """Evaluate SEO meta title quality.

    Optimal meta title is 30-60 characters.

    Args:
        value: Meta title string

    Returns:
        int: Quality score (0-100)
    """
    if not value:
        return 0

    length = len(str(value).strip())

    if SEO_META_TITLE_MIN_LENGTH <= length <= SEO_META_TITLE_MAX_LENGTH:
        return 100
    elif length < SEO_META_TITLE_MIN_LENGTH:
        return max(30, int(length / SEO_META_TITLE_MIN_LENGTH * 100))
    else:
        # Penalize for being too long
        overage = length - SEO_META_TITLE_MAX_LENGTH
        penalty = min(50, overage)
        return max(50, 100 - penalty)


def evaluate_meta_description(value):
    """Evaluate SEO meta description quality.

    Optimal meta description is 120-160 characters.

    Args:
        value: Meta description string

    Returns:
        int: Quality score (0-100)
    """
    if not value:
        return 0

    length = len(str(value).strip())

    if SEO_META_DESCRIPTION_MIN_LENGTH <= length <= SEO_META_DESCRIPTION_MAX_LENGTH:
        return 100
    elif length < SEO_META_DESCRIPTION_MIN_LENGTH:
        return max(30, int(length / SEO_META_DESCRIPTION_MIN_LENGTH * 100))
    else:
        overage = length - SEO_META_DESCRIPTION_MAX_LENGTH
        penalty = min(50, overage // 2)
        return max(50, 100 - penalty)


def evaluate_meta_keywords(value):
    """Evaluate SEO meta keywords quality.

    Checks for presence and reasonable number of keywords.

    Args:
        value: Meta keywords string (comma-separated)

    Returns:
        int: Quality score (0-100)
    """
    if not value:
        return 0

    keywords = [k.strip() for k in str(value).split(",") if k.strip()]
    keyword_count = len(keywords)

    if 3 <= keyword_count <= 10:
        return 100
    elif keyword_count == 1:
        return 50
    elif keyword_count == 2:
        return 70
    elif keyword_count > 10:
        # Too many keywords is also not ideal
        return max(60, 100 - (keyword_count - 10) * 5)
    else:
        return 0


def calculate_translation_score(product_doc):
    """Calculate translation coverage and quality scores.

    Evaluates the completeness and quality of translations
    for multi-language product content.

    Args:
        product_doc: Product Master document

    Returns:
        dict: Dictionary with 'coverage' and 'quality' scores (0-100)
    """
    import frappe
    from frappe.utils import flt

    try:
        coverage_score = 0
        quality_score = 0

        # Check for translations child table
        if not hasattr(product_doc, "translations") or not product_doc.translations:
            # No translations - check if this is expected
            # If only one language is configured, this is OK
            return {"coverage": 100, "quality": 100}

        translations = product_doc.translations
        if not translations:
            return {"coverage": 100, "quality": 100}

        # Get configured languages (if settings exist)
        try:
            required_languages = frappe.get_all(
                "Language",
                filters={"enabled": 1},
                pluck="name"
            )
        except Exception:
            required_languages = ["en"]  # Default to English only

        if not required_languages:
            required_languages = ["en"]

        # Track which fields are translated for each language
        translated_fields_by_lang = {}
        verified_translations = 0
        total_translations = 0

        for trans in translations:
            lang = getattr(trans, "language", None)
            if lang:
                if lang not in translated_fields_by_lang:
                    translated_fields_by_lang[lang] = set()

                field = getattr(trans, "field_name", None)
                if field:
                    translated_fields_by_lang[lang].add(field)

                total_translations += 1
                if getattr(trans, "is_verified", False):
                    verified_translations += 1

        # Calculate coverage score
        languages_covered = len(translated_fields_by_lang)
        if len(required_languages) > 0:
            coverage_score = flt((languages_covered / len(required_languages)) * 100, 2)
        else:
            coverage_score = 100

        # Calculate quality score based on verified translations
        if total_translations > 0:
            quality_score = flt((verified_translations / total_translations) * 100, 2)
        else:
            quality_score = 100  # No translations needed

        return {
            "coverage": min(coverage_score, 100),
            "quality": min(quality_score, 100)
        }

    except Exception as e:
        import frappe
        frappe.log_error(
            message=f"Error calculating translation score: {str(e)}",
            title="PIM Translation Score Error"
        )
        return {"coverage": 0, "quality": 0}


def calculate_attribute_score(product_doc):
    """Calculate attribute completeness and quality scores.

    Evaluates the presence and quality of product attributes
    including completeness, accuracy, and consistency.

    Args:
        product_doc: Product Master document

    Returns:
        dict: Dictionary with 'completeness', 'quality', 'accuracy',
              and 'consistency' scores (0-100)
    """
    import frappe
    from frappe.utils import flt

    try:
        completeness_score = 0
        quality_score = 0
        accuracy_score = 80  # Default baseline
        consistency_score = 80  # Default baseline

        # Check for attributes child table
        attributes = []
        if hasattr(product_doc, "attributes") and product_doc.attributes:
            attributes = product_doc.attributes
        elif hasattr(product_doc, "product_attributes") and product_doc.product_attributes:
            attributes = product_doc.product_attributes

        if not attributes:
            # Check if product family defines required attributes
            family = getattr(product_doc, "product_family", None)
            if family:
                try:
                    family_doc = frappe.get_doc("Product Family", family)
                    required_attrs = getattr(family_doc, "required_attributes", [])
                    if required_attrs:
                        # Family has required attributes but product has none
                        return {
                            "completeness": 0,
                            "quality": 0,
                            "accuracy": 0,
                            "consistency": 0
                        }
                except Exception:
                    pass

            # No attributes defined/required
            return {
                "completeness": 100,
                "quality": 100,
                "accuracy": 100,
                "consistency": 100
            }

        # Count filled vs total attributes
        filled_attrs = 0
        total_attrs = len(attributes)
        quality_points = 0

        for attr in attributes:
            value = getattr(attr, "attribute_value", None) or getattr(attr, "value", None)
            if value and str(value).strip():
                filled_attrs += 1
                # Quality check - value is not a placeholder
                if str(value).lower() not in ["n/a", "tbd", "-", "none", "na"]:
                    quality_points += 100
                else:
                    quality_points += 30

        # Calculate completeness
        if total_attrs > 0:
            completeness_score = flt((filled_attrs / total_attrs) * 100, 2)
            quality_score = flt(quality_points / total_attrs, 2)

        # Check for data consistency (similar products should have similar attributes)
        # This is a simplified version - in production, this would compare with related products
        consistency_score = 80 if filled_attrs == total_attrs else 60

        # Accuracy is based on having valid attribute values
        accuracy_score = quality_score if quality_score > 0 else 80

        return {
            "completeness": min(completeness_score, 100),
            "quality": min(quality_score, 100),
            "accuracy": min(accuracy_score, 100),
            "consistency": min(consistency_score, 100)
        }

    except Exception as e:
        import frappe
        frappe.log_error(
            message=f"Error calculating attribute score: {str(e)}",
            title="PIM Attribute Score Error"
        )
        return {
            "completeness": 0,
            "quality": 0,
            "accuracy": 0,
            "consistency": 0
        }


def calculate_market_score(product_doc):
    """Calculate market-related scores.

    Evaluates market performance, customer satisfaction,
    competitive position, and feedback sentiment.

    These scores are typically based on external data sources
    and may require additional DocTypes to be populated.

    Args:
        product_doc: Product Master document

    Returns:
        dict: Dictionary with 'performance', 'satisfaction',
              'competitive', and 'sentiment' scores (0-100)
    """
    import frappe
    from frappe.utils import flt

    try:
        performance_score = 50  # Default baseline
        satisfaction_score = 50  # Default baseline
        competitive_score = 50  # Default baseline
        sentiment_score = 50  # Default baseline

        product_name = product_doc.name

        # Check for product feedback
        try:
            feedback_stats = frappe.db.sql("""
                SELECT
                    COUNT(*) as total_feedback,
                    AVG(CASE WHEN rating IS NOT NULL THEN rating ELSE 0 END) as avg_rating,
                    SUM(CASE WHEN sentiment = 'Positive' THEN 1 ELSE 0 END) as positive_count,
                    SUM(CASE WHEN sentiment = 'Negative' THEN 1 ELSE 0 END) as negative_count,
                    SUM(CASE WHEN status = 'Resolved' THEN 1 ELSE 0 END) as resolved_count
                FROM `tabProduct Feedback`
                WHERE linked_product = %s
            """, (product_name,), as_dict=True)

            if feedback_stats and feedback_stats[0].get("total_feedback"):
                stats = feedback_stats[0]
                total = stats.get("total_feedback", 0)

                # Calculate satisfaction from average rating
                avg_rating = flt(stats.get("avg_rating", 0))
                if avg_rating > 0:
                    satisfaction_score = flt((avg_rating / 5) * 100, 2)

                # Calculate sentiment score
                positive = stats.get("positive_count", 0) or 0
                negative = stats.get("negative_count", 0) or 0
                if total > 0:
                    sentiment_score = flt(
                        ((positive - negative + total) / (2 * total)) * 100, 2
                    )
                    sentiment_score = max(0, min(100, sentiment_score))

                # Performance from resolution rate
                resolved = stats.get("resolved_count", 0) or 0
                if total > 0:
                    performance_score = flt((resolved / total) * 100, 2)
                    # Adjust baseline - 70% is good
                    performance_score = min(100, performance_score + 30)

        except Exception:
            pass  # Table might not exist yet

        # Check for competitor analysis
        try:
            competitor_stats = frappe.db.sql("""
                SELECT
                    COUNT(*) as total_analyses,
                    AVG(our_overall_rating) as our_avg_rating,
                    AVG(competitor_overall_rating) as competitor_avg_rating,
                    AVG(CASE WHEN threat_level = 'High' THEN 3
                             WHEN threat_level = 'Medium' THEN 2
                             WHEN threat_level = 'Low' THEN 1
                             ELSE 2 END) as avg_threat
                FROM `tabCompetitor Analysis`
                WHERE linked_product = %s
            """, (product_name,), as_dict=True)

            if competitor_stats and competitor_stats[0].get("total_analyses"):
                stats = competitor_stats[0]
                our_rating = flt(stats.get("our_avg_rating", 0))
                competitor_rating = flt(stats.get("competitor_avg_rating", 0))

                if our_rating > 0 and competitor_rating > 0:
                    # Score based on how we compare to competitors
                    ratio = our_rating / competitor_rating
                    competitive_score = min(100, flt(ratio * 50, 2))
                elif our_rating > 0:
                    competitive_score = flt((our_rating / 5) * 100, 2)

        except Exception:
            pass  # Table might not exist yet

        return {
            "performance": min(max(performance_score, 0), 100),
            "satisfaction": min(max(satisfaction_score, 0), 100),
            "competitive": min(max(competitive_score, 0), 100),
            "sentiment": min(max(sentiment_score, 0), 100)
        }

    except Exception as e:
        import frappe
        frappe.log_error(
            message=f"Error calculating market score: {str(e)}",
            title="PIM Market Score Error"
        )
        return {
            "performance": 50,
            "satisfaction": 50,
            "competitive": 50,
            "sentiment": 50
        }


def calculate_weighted_score(scores):
    """Calculate weighted overall score from component scores.

    Uses the configured weights to calculate a weighted average
    of all component scores.

    Args:
        scores: Dictionary containing component scores and weights

    Returns:
        float: Weighted overall score (0-100)
    """
    from frappe.utils import flt

    try:
        # Get weights
        content_weight = flt(scores.get("content_weight", DEFAULT_WEIGHTS["content_weight"]))
        media_weight = flt(scores.get("media_weight", DEFAULT_WEIGHTS["media_weight"]))
        seo_weight = flt(scores.get("seo_weight", DEFAULT_WEIGHTS["seo_weight"]))
        translation_weight = flt(scores.get("translation_weight", DEFAULT_WEIGHTS["translation_weight"]))
        attribute_weight = flt(scores.get("attribute_weight", DEFAULT_WEIGHTS["attribute_weight"]))
        market_weight = flt(scores.get("market_weight", DEFAULT_WEIGHTS["market_weight"]))

        total_weight = (
            content_weight + media_weight + seo_weight +
            translation_weight + attribute_weight + market_weight
        )

        if total_weight == 0:
            total_weight = 100

        # Calculate component averages
        content_score = (
            flt(scores.get("content_completeness_score", 0)) +
            flt(scores.get("content_quality_score", 0))
        ) / 2

        media_score = (
            flt(scores.get("media_completeness_score", 0)) +
            flt(scores.get("media_quality_score", 0))
        ) / 2

        seo_score = (
            flt(scores.get("seo_score", 0)) +
            flt(scores.get("seo_meta_title_score", 0))
        ) / 2

        translation_score = (
            flt(scores.get("translation_coverage_score", 0)) +
            flt(scores.get("translation_quality_score", 0))
        ) / 2

        attribute_score = (
            flt(scores.get("attribute_completeness_score", 0)) +
            flt(scores.get("attribute_quality_score", 0)) +
            flt(scores.get("data_accuracy_score", 0)) +
            flt(scores.get("data_consistency_score", 0))
        ) / 4

        market_score = (
            flt(scores.get("market_performance_score", 0)) +
            flt(scores.get("customer_satisfaction_score", 0)) +
            flt(scores.get("competitive_position_score", 0)) +
            flt(scores.get("feedback_sentiment_score", 0))
        ) / 4

        # Calculate weighted sum
        weighted_sum = (
            (content_score * content_weight) +
            (media_score * media_weight) +
            (seo_score * seo_weight) +
            (translation_score * translation_weight) +
            (attribute_score * attribute_weight) +
            (market_score * market_weight)
        )

        overall_score = flt(weighted_sum / total_weight, 2)

        return min(max(overall_score, 0), 100)

    except Exception:
        return 0


def get_default_scores():
    """Get default score structure with zeros.

    Returns:
        dict: Dictionary with all score fields set to 0
    """
    return {
        "overall_score": 0,
        "content_completeness_score": 0,
        "content_quality_score": 0,
        "media_completeness_score": 0,
        "media_quality_score": 0,
        "seo_score": 0,
        "seo_meta_title_score": 0,
        "translation_coverage_score": 0,
        "translation_quality_score": 0,
        "attribute_completeness_score": 0,
        "attribute_quality_score": 0,
        "data_accuracy_score": 0,
        "data_consistency_score": 0,
        "market_performance_score": 0,
        "customer_satisfaction_score": 0,
        "competitive_position_score": 0,
        "feedback_sentiment_score": 0,
        "content_weight": DEFAULT_WEIGHTS["content_weight"],
        "media_weight": DEFAULT_WEIGHTS["media_weight"],
        "seo_weight": DEFAULT_WEIGHTS["seo_weight"],
        "translation_weight": DEFAULT_WEIGHTS["translation_weight"],
        "attribute_weight": DEFAULT_WEIGHTS["attribute_weight"],
        "market_weight": DEFAULT_WEIGHTS["market_weight"],
    }


def get_score_for_product(product, use_cache=True):
    """Get the current product score, optionally from cache.

    Args:
        product: Product Master name
        use_cache: Whether to use cached score if available

    Returns:
        dict: Current product score or None if not found
    """
    import frappe

    try:
        cache_key = f"pim:product_scores:{product}"

        if use_cache:
            cached = frappe.cache().get_value(cache_key)
            if cached:
                return cached

        score = frappe.get_all(
            "Product Score",
            filters={
                "linked_product": product,
                "is_current": 1,
                "status": "Active"
            },
            fields=["*"],
            limit=1
        )

        if score:
            result = score[0]
            frappe.cache().set_value(cache_key, result, expires_in_sec=300)
            return result

        return None

    except Exception as e:
        import frappe
        frappe.log_error(
            message=f"Error getting score for product {product}: {str(e)}",
            title="PIM Score Retrieval Error"
        )
        return None


def recalculate_scores_for_products(products, background=False):
    """Recalculate scores for multiple products.

    Args:
        products: List of Product Master names
        background: Whether to run in background (enqueue)

    Returns:
        dict: Results with success count and any errors
    """
    import frappe

    if background:
        frappe.enqueue(
            "frappe_pim.pim.utils.scoring._recalculate_scores_batch",
            products=products,
            queue="long",
            timeout=3600
        )
        return {
            "status": "enqueued",
            "message": f"Score recalculation queued for {len(products)} products"
        }

    return _recalculate_scores_batch(products)


def _recalculate_scores_batch(products):
    """Internal batch recalculation function.

    Args:
        products: List of Product Master names

    Returns:
        dict: Results with success count and errors
    """
    import frappe

    success_count = 0
    errors = []

    for product in products:
        try:
            scores = calculate_product_score(product)

            # Update or create Product Score record
            existing = frappe.get_all(
                "Product Score",
                filters={
                    "linked_product": product,
                    "is_current": 1
                },
                limit=1
            )

            if existing:
                doc = frappe.get_doc("Product Score", existing[0].name)
                for field, value in scores.items():
                    if hasattr(doc, field):
                        setattr(doc, field, value)
                doc.calculation_method = "Batch"
                doc.save()
            else:
                doc = frappe.new_doc("Product Score")
                doc.linked_product = product
                doc.score_type = "Overall"
                doc.is_current = 1
                doc.status = "Active"
                doc.calculation_method = "Batch"
                for field, value in scores.items():
                    if hasattr(doc, field):
                        setattr(doc, field, value)
                doc.insert()

            success_count += 1

            # Invalidate cache
            frappe.cache().delete_key(f"pim:product_scores:{product}")

        except Exception as e:
            errors.append({
                "product": product,
                "error": str(e)
            })
            frappe.log_error(
                message=f"Error recalculating score for {product}: {str(e)}",
                title="PIM Batch Scoring Error"
            )

    return {
        "status": "completed",
        "success_count": success_count,
        "error_count": len(errors),
        "errors": errors
    }


def get_scoring_config():
    """Get current scoring configuration.

    Returns:
        dict: Scoring configuration including weights and thresholds
    """
    return {
        "weights": DEFAULT_WEIGHTS.copy(),
        "thresholds": {
            "seo_meta_title_max_length": SEO_META_TITLE_MAX_LENGTH,
            "seo_meta_title_min_length": SEO_META_TITLE_MIN_LENGTH,
            "seo_meta_description_max_length": SEO_META_DESCRIPTION_MAX_LENGTH,
            "seo_meta_description_min_length": SEO_META_DESCRIPTION_MIN_LENGTH,
        },
        "required_content_fields": REQUIRED_CONTENT_FIELDS.copy(),
        "required_seo_fields": REQUIRED_SEO_FIELDS.copy(),
    }
