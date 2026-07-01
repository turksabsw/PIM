"""Quality Scorer Service

Provides a cohesive quality scoring service that wraps the existing
completeness and scoring utility modules into a unified API.

Key Capabilities:
- ``calculate_score()``: Calculates composite quality scores combining
  completeness (required-field fill-rate) and multi-dimension scoring
  (content, media, SEO, translations, attributes, market).
- ``get_missing_fields()``: Identifies missing required fields for a product,
  optionally scoped to a specific channel's requirements.
- ``get_quality_report()``: Generates a comprehensive quality report with
  dimension breakdowns, channel readiness, gap analysis, and remediation
  recommendations.

The service delegates to:
- ``frappe_pim.pim.utils.completeness`` for field-level completeness,
  channel-specific scoring, and gap analysis.
- ``frappe_pim.pim.utils.scoring`` for multi-dimension quality scoring
  (content, media, SEO, translations, attributes, market).

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# =============================================================================
# Constants
# =============================================================================

class QualityLevel(str, Enum):
    """Quality classification based on overall score."""
    EXCELLENT = "excellent"     # 90-100
    GOOD = "good"              # 70-89
    FAIR = "fair"              # 50-69
    POOR = "poor"              # 25-49
    CRITICAL = "critical"      # 0-24


# Score thresholds for quality levels
QUALITY_THRESHOLDS = {
    QualityLevel.EXCELLENT: 90,
    QualityLevel.GOOD: 70,
    QualityLevel.FAIR: 50,
    QualityLevel.POOR: 25,
    QualityLevel.CRITICAL: 0,
}

# Default dimension weights (mirrors scoring.py DEFAULT_WEIGHTS)
DEFAULT_DIMENSION_WEIGHTS = {
    "completeness": 25,
    "content": 20,
    "media": 15,
    "seo": 10,
    "attributes": 20,
    "translation": 10,
}


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class MissingField:
    """A single missing field with context."""
    field_name: str
    importance: str = "required"
    source: str = "core"  # "core", "family", "channel"
    remediation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field_name": self.field_name,
            "importance": self.importance,
            "source": self.source,
            "remediation": self.remediation,
        }


@dataclass
class DimensionScore:
    """Score for a single quality dimension."""
    dimension: str
    score: float = 0.0
    weight: int = 0
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dimension": self.dimension,
            "score": self.score,
            "weight": self.weight,
            "details": self.details,
        }


@dataclass
class QualityScore:
    """Composite quality score result."""
    product_name: str
    overall_score: float = 0.0
    completeness_score: float = 0.0
    quality_level: str = QualityLevel.CRITICAL.value
    dimensions: List[DimensionScore] = field(default_factory=list)
    channel_scores: Dict[str, float] = field(default_factory=dict)
    missing_field_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "product_name": self.product_name,
            "overall_score": self.overall_score,
            "completeness_score": self.completeness_score,
            "quality_level": self.quality_level,
            "dimensions": [d.to_dict() for d in self.dimensions],
            "channel_scores": self.channel_scores,
            "missing_field_count": self.missing_field_count,
        }


@dataclass
class QualityReport:
    """Comprehensive quality report for a product."""
    product_name: str
    overall_score: float = 0.0
    quality_level: str = QualityLevel.CRITICAL.value
    completeness_score: float = 0.0
    dimensions: List[DimensionScore] = field(default_factory=list)
    missing_fields: List[MissingField] = field(default_factory=list)
    channel_readiness: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    remediation_steps: List[Dict[str, Any]] = field(default_factory=list)
    generated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "product_name": self.product_name,
            "overall_score": self.overall_score,
            "quality_level": self.quality_level,
            "completeness_score": self.completeness_score,
            "dimensions": [d.to_dict() for d in self.dimensions],
            "missing_fields": [f.to_dict() for f in self.missing_fields],
            "channel_readiness": self.channel_readiness,
            "remediation_steps": self.remediation_steps,
            "generated_at": self.generated_at,
        }


# =============================================================================
# Quality Scorer Service
# =============================================================================

class QualityScorer:
    """Unified quality scoring service for PIM products.

    Wraps the completeness and scoring utility modules into a single
    cohesive API that provides:

    - Composite quality scores (completeness + multi-dimension)
    - Missing field identification with remediation guidance
    - Comprehensive quality reports with channel readiness

    Usage::

        scorer = QualityScorer()

        # Quick score
        score = QualityScorer.calculate_score("PROD-001")

        # Missing fields
        missing = QualityScorer.get_missing_fields("PROD-001")

        # Full report
        report = QualityScorer.get_quality_report("PROD-001")

        # Channel-specific
        score = QualityScorer.calculate_score("PROD-001", channel_code="amazon")
    """

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    @staticmethod
    def calculate_score(
        product: Any,
        channel_code: Optional[str] = None,
        use_cache: bool = True,
    ) -> QualityScore:
        """Calculate composite quality score for a product.

        Combines the completeness score (required-field fill-rate) with
        the multi-dimension scoring (content, media, SEO, translations,
        attributes) into a single weighted score.

        If *channel_code* is provided, also includes the channel-specific
        completeness score in the result.

        Args:
            product: Product Master name (str) or document object.
            channel_code: Optional channel code for channel-specific scoring
                (e.g., ``"amazon"``, ``"shopify"``).
            use_cache: Whether to use cached scores when available.

        Returns:
            :class:`QualityScore` with overall and per-dimension scores.

        Example::

            score = QualityScorer.calculate_score("PROD-001")
            print(score.overall_score)  # 72.5
            print(score.quality_level)  # "good"
        """
        from frappe_pim.pim.utils.completeness import (
            calculate_score as calc_completeness,
            calculate_channel_specific_score,
            get_completeness_summary,
        )
        from frappe_pim.pim.utils.scoring import (
            calculate_product_score,
            get_score_for_product,
        )

        product_name = _resolve_product_name(product)
        result = QualityScore(product_name=product_name)

        try:
            # 1. Get multi-dimension scores from scoring.py
            dimension_scores = None
            if use_cache:
                dimension_scores = get_score_for_product(product_name, use_cache=True)

            if not dimension_scores:
                dimension_scores = calculate_product_score(product)

            # 2. Get completeness score from completeness.py
            completeness_summary = get_completeness_summary(product_name)
            completeness_pct = completeness_summary.get("score", 0.0)
            result.completeness_score = completeness_pct
            result.missing_field_count = (
                len(completeness_summary.get("missing_core", []))
                + len(completeness_summary.get("missing_attributes", []))
            )

            # 3. Build dimension breakdown
            dimensions = _build_dimensions(dimension_scores, completeness_pct)
            result.dimensions = dimensions

            # 4. Calculate weighted overall score
            result.overall_score = _calculate_weighted_overall(dimensions)

            # 5. Determine quality level
            result.quality_level = _score_to_quality_level(result.overall_score).value

            # 6. Channel-specific scoring (optional)
            if channel_code:
                ch_result = calculate_channel_specific_score(product_name, channel_code)
                result.channel_scores[channel_code] = ch_result.get("score", 0.0)

        except Exception as exc:
            _log_error(
                f"Error calculating quality score for {product_name}: {exc}",
                "PIM Quality Score Error",
            )
            result.quality_level = QualityLevel.CRITICAL.value

        return result

    @staticmethod
    def get_missing_fields(
        product_name: str,
        channel_code: Optional[str] = None,
    ) -> List[MissingField]:
        """Get all missing required fields for a product.

        Returns a flat list of :class:`MissingField` objects representing
        fields that are required but not yet filled. Fields are sourced
        from:

        1. **Core fields** — mandatory product fields (name, code, description).
        2. **Family attributes** — required attributes defined by the
           product's family template.
        3. **Channel requirements** — additional fields required by a
           specific sales channel (when *channel_code* is given).

        Args:
            product_name: Name of the Product Master document.
            channel_code: Optional channel code to include channel-specific
                requirements (e.g., ``"amazon"``).

        Returns:
            List of :class:`MissingField` objects, sorted by importance
            (critical first, then required, then recommended).

        Example::

            missing = QualityScorer.get_missing_fields("PROD-001", "amazon")
            for field in missing:
                print(f"{field.field_name} ({field.importance}): {field.remediation}")
        """
        from frappe_pim.pim.utils.completeness import (
            get_completeness_summary,
            gap_analysis,
            list_supported_channels,
        )

        missing: List[MissingField] = []

        try:
            # 1. Core and family-level missing fields
            summary = get_completeness_summary(product_name)

            for field_name in summary.get("missing_core", []):
                missing.append(MissingField(
                    field_name=field_name,
                    importance="required",
                    source="core",
                    remediation=f"Fill in the {field_name} field",
                ))

            for attr_code in summary.get("missing_attributes", []):
                missing.append(MissingField(
                    field_name=attr_code,
                    importance="required",
                    source="family",
                    remediation=f"Set value for required attribute '{attr_code}'",
                ))

            # 2. Channel-specific missing fields
            if channel_code:
                analysis = gap_analysis(product_name, channel_code)
                seen = {f.field_name for f in missing}

                for gap in analysis.critical_gaps:
                    if gap.field_name not in seen:
                        missing.append(MissingField(
                            field_name=gap.field_name,
                            importance="critical",
                            source="channel",
                            remediation=gap.remediation or f"Required for {channel_code}",
                        ))
                        seen.add(gap.field_name)

                for gap in analysis.required_gaps:
                    if gap.field_name not in seen:
                        missing.append(MissingField(
                            field_name=gap.field_name,
                            importance="required",
                            source="channel",
                            remediation=gap.remediation or f"Required for {channel_code}",
                        ))
                        seen.add(gap.field_name)

                for gap in analysis.recommended_gaps:
                    if gap.field_name not in seen:
                        missing.append(MissingField(
                            field_name=gap.field_name,
                            importance="recommended",
                            source="channel",
                            remediation=gap.remediation or f"Recommended for {channel_code}",
                        ))
                        seen.add(gap.field_name)

        except Exception as exc:
            _log_error(
                f"Error getting missing fields for {product_name}: {exc}",
                "PIM Missing Fields Error",
            )

        # Sort: critical → required → recommended
        importance_order = {"critical": 0, "required": 1, "recommended": 2, "optional": 3}
        missing.sort(key=lambda f: importance_order.get(f.importance, 99))

        return missing

    @staticmethod
    def get_quality_report(
        product_name: str,
        channel_codes: Optional[List[str]] = None,
    ) -> QualityReport:
        """Generate a comprehensive quality report for a product.

        Combines completeness, multi-dimension scoring, missing-field
        analysis, channel readiness, and remediation recommendations
        into a single report.

        Args:
            product_name: Name of the Product Master document.
            channel_codes: Optional list of channel codes to evaluate.
                If *None*, evaluates all supported channels.

        Returns:
            :class:`QualityReport` with full quality breakdown.

        Example::

            report = QualityScorer.get_quality_report("PROD-001", ["amazon", "shopify"])
            print(report.overall_score)
            for dim in report.dimensions:
                print(f"  {dim.dimension}: {dim.score}")
            for step in report.remediation_steps:
                print(f"  [{step['priority']}] {step['action']}")
        """
        from frappe_pim.pim.utils.completeness import (
            calculate_multi_channel_scores,
            get_remediation_plan,
            list_supported_channels,
        )
        from datetime import datetime

        report = QualityReport(
            product_name=product_name,
            generated_at=datetime.now().isoformat(),
        )

        try:
            # 1. Calculate composite score
            score = QualityScorer.calculate_score(product_name, use_cache=False)
            report.overall_score = score.overall_score
            report.quality_level = score.quality_level
            report.completeness_score = score.completeness_score
            report.dimensions = score.dimensions

            # 2. Get missing fields (without channel scope for base report)
            report.missing_fields = QualityScorer.get_missing_fields(product_name)

            # 3. Channel readiness analysis
            if channel_codes is None:
                try:
                    channel_codes = list_supported_channels()
                except Exception:
                    channel_codes = []

            if channel_codes:
                try:
                    multi_scores = calculate_multi_channel_scores(
                        product_name, channel_codes
                    )
                    for ch_code, ch_data in multi_scores.get("channels", {}).items():
                        report.channel_readiness[ch_code] = {
                            "score": ch_data.get("score", 0.0),
                            "is_ready": ch_data.get("is_channel_ready", False),
                            "channel_name": ch_data.get("channel_name", ch_code),
                            "missing_fields": ch_data.get("missing_fields", []),
                        }
                except Exception:
                    pass  # Channel scoring is supplementary

            # 4. Remediation plan
            try:
                plan = get_remediation_plan(product_name)
                report.remediation_steps = plan.get("steps", [])
            except Exception:
                pass  # Remediation is supplementary

        except Exception as exc:
            _log_error(
                f"Error generating quality report for {product_name}: {exc}",
                "PIM Quality Report Error",
            )
            report.quality_level = QualityLevel.CRITICAL.value

        return report

    # -----------------------------------------------------------------
    # Convenience / Batch Methods
    # -----------------------------------------------------------------

    @staticmethod
    def calculate_scores_batch(
        product_names: List[str],
        background: bool = False,
    ) -> Dict[str, Any]:
        """Calculate quality scores for multiple products.

        Args:
            product_names: List of Product Master names.
            background: If *True*, enqueue as a background job.

        Returns:
            Dict with per-product scores or enqueue confirmation.
        """
        from frappe_pim.pim.utils.scoring import recalculate_scores_for_products

        if background:
            return recalculate_scores_for_products(product_names, background=True)

        results: Dict[str, Any] = {
            "success_count": 0,
            "error_count": 0,
            "scores": {},
            "errors": [],
        }

        for name in product_names:
            try:
                score = QualityScorer.calculate_score(name, use_cache=False)
                results["scores"][name] = score.to_dict()
                results["success_count"] += 1
            except Exception as exc:
                results["errors"].append({"product": name, "error": str(exc)})
                results["error_count"] += 1

        return results

    @staticmethod
    def get_scoring_config() -> Dict[str, Any]:
        """Get the current scoring configuration.

        Returns dimension weights, thresholds, and quality level
        definitions.

        Returns:
            Dict with weights, thresholds, and quality levels.
        """
        from frappe_pim.pim.utils.scoring import get_scoring_config

        config = get_scoring_config()
        config["quality_levels"] = {
            level.value: threshold
            for level, threshold in QUALITY_THRESHOLDS.items()
        }
        config["dimension_weights"] = DEFAULT_DIMENSION_WEIGHTS.copy()
        return config


# =============================================================================
# Private Module-Level Helpers
# =============================================================================

def _resolve_product_name(product: Any) -> str:
    """Extract the product name string from a product argument.

    Args:
        product: Product Master name (str) or document object.

    Returns:
        Product name string.
    """
    if isinstance(product, str):
        return product
    return getattr(product, "name", str(product))


def _build_dimensions(
    scoring_data: Dict[str, Any],
    completeness_pct: float,
) -> List[DimensionScore]:
    """Build dimension score objects from raw scoring data.

    Args:
        scoring_data: Dict from ``calculate_product_score()`` or cached scores.
        completeness_pct: Completeness percentage from completeness module.

    Returns:
        List of :class:`DimensionScore` objects.
    """
    from frappe.utils import flt

    dimensions = []

    # Completeness dimension
    dimensions.append(DimensionScore(
        dimension="completeness",
        score=flt(completeness_pct, 2),
        weight=DEFAULT_DIMENSION_WEIGHTS.get("completeness", 25),
        details={"type": "field_fill_rate"},
    ))

    # Content dimension (average of completeness + quality)
    content_completeness = flt(scoring_data.get("content_completeness_score", 0))
    content_quality = flt(scoring_data.get("content_quality_score", 0))
    content_avg = flt((content_completeness + content_quality) / 2, 2)
    dimensions.append(DimensionScore(
        dimension="content",
        score=content_avg,
        weight=DEFAULT_DIMENSION_WEIGHTS.get("content", 20),
        details={
            "completeness": content_completeness,
            "quality": content_quality,
        },
    ))

    # Media dimension
    media_completeness = flt(scoring_data.get("media_completeness_score", 0))
    media_quality = flt(scoring_data.get("media_quality_score", 0))
    media_avg = flt((media_completeness + media_quality) / 2, 2)
    dimensions.append(DimensionScore(
        dimension="media",
        score=media_avg,
        weight=DEFAULT_DIMENSION_WEIGHTS.get("media", 15),
        details={
            "completeness": media_completeness,
            "quality": media_quality,
        },
    ))

    # SEO dimension
    seo_overall = flt(scoring_data.get("seo_score", 0))
    seo_title = flt(scoring_data.get("seo_meta_title_score", 0))
    seo_avg = flt((seo_overall + seo_title) / 2, 2)
    dimensions.append(DimensionScore(
        dimension="seo",
        score=seo_avg,
        weight=DEFAULT_DIMENSION_WEIGHTS.get("seo", 10),
        details={
            "overall": seo_overall,
            "meta_title": seo_title,
        },
    ))

    # Attributes dimension
    attr_completeness = flt(scoring_data.get("attribute_completeness_score", 0))
    attr_quality = flt(scoring_data.get("attribute_quality_score", 0))
    attr_accuracy = flt(scoring_data.get("data_accuracy_score", 0))
    attr_consistency = flt(scoring_data.get("data_consistency_score", 0))
    attr_avg = flt(
        (attr_completeness + attr_quality + attr_accuracy + attr_consistency) / 4,
        2,
    )
    dimensions.append(DimensionScore(
        dimension="attributes",
        score=attr_avg,
        weight=DEFAULT_DIMENSION_WEIGHTS.get("attributes", 20),
        details={
            "completeness": attr_completeness,
            "quality": attr_quality,
            "accuracy": attr_accuracy,
            "consistency": attr_consistency,
        },
    ))

    # Translation dimension
    trans_coverage = flt(scoring_data.get("translation_coverage_score", 0))
    trans_quality = flt(scoring_data.get("translation_quality_score", 0))
    trans_avg = flt((trans_coverage + trans_quality) / 2, 2)
    dimensions.append(DimensionScore(
        dimension="translation",
        score=trans_avg,
        weight=DEFAULT_DIMENSION_WEIGHTS.get("translation", 10),
        details={
            "coverage": trans_coverage,
            "quality": trans_quality,
        },
    ))

    return dimensions


def _calculate_weighted_overall(dimensions: List[DimensionScore]) -> float:
    """Calculate the weighted overall score from dimension scores.

    Args:
        dimensions: List of :class:`DimensionScore` objects.

    Returns:
        Weighted average score (0-100).
    """
    from frappe.utils import flt

    total_weight = sum(d.weight for d in dimensions)
    if total_weight == 0:
        return 0.0

    weighted_sum = sum(d.score * d.weight for d in dimensions)
    return flt(min(max(weighted_sum / total_weight, 0), 100), 2)


def _score_to_quality_level(score: float) -> QualityLevel:
    """Map a numeric score to a quality level.

    Args:
        score: Numeric score (0-100).

    Returns:
        :class:`QualityLevel` enum value.
    """
    if score >= QUALITY_THRESHOLDS[QualityLevel.EXCELLENT]:
        return QualityLevel.EXCELLENT
    elif score >= QUALITY_THRESHOLDS[QualityLevel.GOOD]:
        return QualityLevel.GOOD
    elif score >= QUALITY_THRESHOLDS[QualityLevel.FAIR]:
        return QualityLevel.FAIR
    elif score >= QUALITY_THRESHOLDS[QualityLevel.POOR]:
        return QualityLevel.POOR
    else:
        return QualityLevel.CRITICAL


def _log_error(message: str, title: str) -> None:
    """Log an error to the Frappe error log if available.

    Args:
        message: Error message.
        title: Error title.
    """
    try:
        import frappe
        frappe.log_error(message=message, title=title)
    except Exception:
        pass


# =============================================================================
# Convenience Functions (module-level API)
# =============================================================================

def calculate_score(
    product: Any,
    channel_code: Optional[str] = None,
    use_cache: bool = True,
) -> QualityScore:
    """Convenience wrapper for :meth:`QualityScorer.calculate_score`."""
    return QualityScorer.calculate_score(
        product=product,
        channel_code=channel_code,
        use_cache=use_cache,
    )


def get_missing_fields(
    product_name: str,
    channel_code: Optional[str] = None,
) -> List[MissingField]:
    """Convenience wrapper for :meth:`QualityScorer.get_missing_fields`."""
    return QualityScorer.get_missing_fields(
        product_name=product_name,
        channel_code=channel_code,
    )


def get_quality_report(
    product_name: str,
    channel_codes: Optional[List[str]] = None,
) -> QualityReport:
    """Convenience wrapper for :meth:`QualityScorer.get_quality_report`."""
    return QualityScorer.get_quality_report(
        product_name=product_name,
        channel_codes=channel_codes,
    )
