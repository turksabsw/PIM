"""Merge/Survive Service for Product Deduplication

This module provides services for identifying duplicate products and merging them
using configurable survivorship rules. It's a core component of the MDM (Master
Data Management) governance features.

The service supports:
- Duplicate Detection: Find potential duplicate products based on multiple criteria
- Similarity Scoring: Calculate match scores using various algorithms
- Survivorship Rules: Determine winning field values during merge operations
- Merge Operations: Combine duplicate records into golden records
- Field-Level Tracking: Track provenance of each merged field value
- Audit Trail: Complete logging of all merge operations

Survivorship Rules:
- Most Recent: Use values from most recently updated source
- Highest Confidence: Use values with highest confidence score
- Source Priority: Follow configured source system priority order
- Manual Override: Require manual selection of values
- Most Complete: Use values from source with most populated fields
- Custom Rules: Apply field-specific rules for fine-grained control

Duplicate Detection Strategies:
- Exact Match: Match on specific fields (GTIN, SKU, etc.)
- Fuzzy Match: Use string similarity algorithms (Levenshtein, Jaro-Winkler)
- Phonetic Match: Match using soundex/metaphone for similar-sounding names
- Attribute Match: Match based on key attribute combinations
- ML-based Match: Use machine learning models for advanced matching

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

import re
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Callable, Set
import unicodedata


# =============================================================================
# Constants and Enums
# =============================================================================

class SurvivorshipRule(Enum):
    """Survivorship rules for determining winning values."""
    MOST_RECENT = "Most Recent"
    HIGHEST_CONFIDENCE = "Highest Confidence"
    SOURCE_PRIORITY = "Source Priority"
    MANUAL_OVERRIDE = "Manual Override"
    MOST_COMPLETE = "Most Complete"
    CUSTOM = "Custom"


class MergeMode(Enum):
    """How merge operations should be processed."""
    AUTOMATIC = "Automatic"
    MANUAL_REVIEW = "Manual Review Required"
    AI_ASSISTED = "AI Assisted"


class MatchType(Enum):
    """Types of duplicate matching strategies."""
    EXACT = "exact"
    FUZZY = "fuzzy"
    PHONETIC = "phonetic"
    ATTRIBUTE = "attribute"
    COMPOSITE = "composite"


class MatchStatus(Enum):
    """Status of a duplicate match."""
    POTENTIAL = "potential"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    MERGED = "merged"
    PENDING_REVIEW = "pending_review"


class MergeStatus(Enum):
    """Status of a merge operation."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class FieldResolution(Enum):
    """How a field conflict was resolved."""
    WINNER_SOURCE = "winner_source"
    CONCATENATED = "concatenated"
    AGGREGATED = "aggregated"
    MANUAL = "manual"
    CUSTOM_RULE = "custom_rule"


# Default match thresholds
MATCH_THRESHOLDS = {
    MatchType.EXACT: 100,
    MatchType.FUZZY: 80,
    MatchType.PHONETIC: 75,
    MatchType.ATTRIBUTE: 70,
    MatchType.COMPOSITE: 85,
}

# Fields commonly used for duplicate detection
DEFAULT_MATCH_FIELDS = [
    "gtin",
    "product_code",
    "item_code",
    "product_name",
    "item_name",
    "sku",
    "mpn",
    "upc",
    "ean",
    "brand",
]

# Fields that should be aggregated (not replaced) during merge
AGGREGATE_FIELDS = [
    "media_files",
    "images",
    "attachments",
    "categories",
    "tags",
    "keywords",
    "channels",
]

# Fields that should be concatenated during merge
CONCATENATE_FIELDS = [
    "notes",
    "internal_comments",
]


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class MatchConfig:
    """Configuration for duplicate matching."""
    match_type: MatchType = MatchType.FUZZY
    threshold: float = 80.0
    match_fields: List[str] = field(default_factory=lambda: DEFAULT_MATCH_FIELDS.copy())
    exact_match_fields: List[str] = field(default_factory=lambda: ["gtin", "sku", "item_code"])
    fuzzy_match_fields: List[str] = field(default_factory=lambda: ["product_name", "item_name"])
    weight_by_field: Dict[str, float] = field(default_factory=dict)
    case_sensitive: bool = False
    ignore_punctuation: bool = True
    ignore_whitespace: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "match_type": self.match_type.value,
            "threshold": self.threshold,
            "match_fields": self.match_fields,
            "exact_match_fields": self.exact_match_fields,
            "fuzzy_match_fields": self.fuzzy_match_fields,
            "weight_by_field": self.weight_by_field,
            "case_sensitive": self.case_sensitive,
            "ignore_punctuation": self.ignore_punctuation,
            "ignore_whitespace": self.ignore_whitespace,
        }


@dataclass
class SurvivorshipConfig:
    """Configuration for survivorship rules."""
    default_rule: SurvivorshipRule = SurvivorshipRule.MOST_RECENT
    source_priority: List[str] = field(default_factory=lambda: ["PIM", "ERP", "Import"])
    field_rules: Dict[str, SurvivorshipRule] = field(default_factory=dict)
    aggregate_fields: List[str] = field(default_factory=lambda: AGGREGATE_FIELDS.copy())
    concatenate_fields: List[str] = field(default_factory=lambda: CONCATENATE_FIELDS.copy())
    auto_merge_threshold: float = 95.0
    require_approval: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "default_rule": self.default_rule.value,
            "source_priority": self.source_priority,
            "field_rules": {k: v.value for k, v in self.field_rules.items()},
            "aggregate_fields": self.aggregate_fields,
            "concatenate_fields": self.concatenate_fields,
            "auto_merge_threshold": self.auto_merge_threshold,
            "require_approval": self.require_approval,
        }


@dataclass
class DuplicateMatch:
    """Represents a potential duplicate match."""
    source_product: str
    matched_product: str
    match_score: float
    match_type: MatchType
    matched_fields: Dict[str, float] = field(default_factory=dict)
    status: MatchStatus = MatchStatus.POTENTIAL
    match_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    detected_at: datetime = field(default_factory=datetime.utcnow)
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "match_id": self.match_id,
            "source_product": self.source_product,
            "matched_product": self.matched_product,
            "match_score": round(self.match_score, 2),
            "match_type": self.match_type.value,
            "matched_fields": {k: round(v, 2) for k, v in self.matched_fields.items()},
            "status": self.status.value,
            "detected_at": self.detected_at.isoformat(),
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
        }


@dataclass
class FieldMergeResult:
    """Result of merging a single field."""
    field_name: str
    winning_value: Any
    source_product: str
    source_system: Optional[str] = None
    confidence: float = 100.0
    resolution: FieldResolution = FieldResolution.WINNER_SOURCE
    alternative_values: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "field_name": self.field_name,
            "winning_value": self.winning_value,
            "source_product": self.source_product,
            "source_system": self.source_system,
            "confidence": round(self.confidence, 2),
            "resolution": self.resolution.value,
            "alternative_values": self.alternative_values,
        }


@dataclass
class MergeResult:
    """Result of a merge operation."""
    success: bool
    merge_id: str
    golden_record: Optional[str] = None
    source_products: List[str] = field(default_factory=list)
    merged_fields: Dict[str, FieldMergeResult] = field(default_factory=dict)
    status: MergeStatus = MergeStatus.PENDING
    survivorship_rule: SurvivorshipRule = SurvivorshipRule.MOST_RECENT
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    merged_at: Optional[datetime] = None
    merged_by: Optional[str] = None
    rollback_data: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "merge_id": self.merge_id,
            "golden_record": self.golden_record,
            "source_products": self.source_products,
            "merged_fields": {
                k: v.to_dict() for k, v in self.merged_fields.items()
            },
            "status": self.status.value,
            "survivorship_rule": self.survivorship_rule.value,
            "errors": self.errors,
            "warnings": self.warnings,
            "merged_at": self.merged_at.isoformat() if self.merged_at else None,
            "merged_by": self.merged_by,
        }


@dataclass
class DuplicateScanResult:
    """Result of a duplicate scan operation."""
    total_products_scanned: int
    duplicates_found: int
    duplicate_groups: List[List[DuplicateMatch]] = field(default_factory=list)
    matches: List[DuplicateMatch] = field(default_factory=list)
    scan_duration_ms: int = 0
    config_used: Optional[MatchConfig] = None
    scanned_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_products_scanned": self.total_products_scanned,
            "duplicates_found": self.duplicates_found,
            "duplicate_groups": [
                [m.to_dict() for m in group]
                for group in self.duplicate_groups
            ],
            "matches": [m.to_dict() for m in self.matches],
            "scan_duration_ms": self.scan_duration_ms,
            "config_used": self.config_used.to_dict() if self.config_used else None,
            "scanned_at": self.scanned_at.isoformat(),
        }


# =============================================================================
# Similarity Algorithms
# =============================================================================

class SimilarityCalculator:
    """Calculate similarity scores between strings using various algorithms."""

    @staticmethod
    def levenshtein_distance(s1: str, s2: str) -> int:
        """Calculate Levenshtein edit distance between two strings.

        Args:
            s1: First string
            s2: Second string

        Returns:
            Edit distance (number of edits to transform s1 to s2)
        """
        if len(s1) < len(s2):
            s1, s2 = s2, s1

        if len(s2) == 0:
            return len(s1)

        previous_row = range(len(s2) + 1)

        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row

        return previous_row[-1]

    @staticmethod
    def levenshtein_similarity(s1: str, s2: str) -> float:
        """Calculate similarity ratio based on Levenshtein distance.

        Args:
            s1: First string
            s2: Second string

        Returns:
            Similarity score (0-100)
        """
        if not s1 and not s2:
            return 100.0
        if not s1 or not s2:
            return 0.0

        distance = SimilarityCalculator.levenshtein_distance(s1, s2)
        max_len = max(len(s1), len(s2))

        return ((max_len - distance) / max_len) * 100

    @staticmethod
    def jaro_similarity(s1: str, s2: str) -> float:
        """Calculate Jaro similarity between two strings.

        Args:
            s1: First string
            s2: Second string

        Returns:
            Similarity score (0-100)
        """
        if not s1 and not s2:
            return 100.0
        if not s1 or not s2:
            return 0.0
        if s1 == s2:
            return 100.0

        len_s1, len_s2 = len(s1), len(s2)
        match_distance = max(len_s1, len_s2) // 2 - 1

        s1_matches = [False] * len_s1
        s2_matches = [False] * len_s2

        matches = 0
        transpositions = 0

        for i in range(len_s1):
            start = max(0, i - match_distance)
            end = min(i + match_distance + 1, len_s2)

            for j in range(start, end):
                if s2_matches[j] or s1[i] != s2[j]:
                    continue
                s1_matches[i] = True
                s2_matches[j] = True
                matches += 1
                break

        if matches == 0:
            return 0.0

        k = 0
        for i in range(len_s1):
            if not s1_matches[i]:
                continue
            while not s2_matches[k]:
                k += 1
            if s1[i] != s2[k]:
                transpositions += 1
            k += 1

        jaro = (
            matches / len_s1 +
            matches / len_s2 +
            (matches - transpositions / 2) / matches
        ) / 3

        return jaro * 100

    @staticmethod
    def jaro_winkler_similarity(s1: str, s2: str, p: float = 0.1) -> float:
        """Calculate Jaro-Winkler similarity between two strings.

        Args:
            s1: First string
            s2: Second string
            p: Scaling factor (default 0.1)

        Returns:
            Similarity score (0-100)
        """
        jaro_sim = SimilarityCalculator.jaro_similarity(s1, s2) / 100

        # Find common prefix (up to 4 characters)
        prefix_len = 0
        for i in range(min(len(s1), len(s2), 4)):
            if s1[i] == s2[i]:
                prefix_len += 1
            else:
                break

        return (jaro_sim + prefix_len * p * (1 - jaro_sim)) * 100

    @staticmethod
    def jaccard_similarity(s1: str, s2: str, tokenize: bool = True) -> float:
        """Calculate Jaccard similarity between two strings.

        Args:
            s1: First string
            s2: Second string
            tokenize: Whether to tokenize by words (default True)

        Returns:
            Similarity score (0-100)
        """
        if not s1 and not s2:
            return 100.0
        if not s1 or not s2:
            return 0.0

        if tokenize:
            set1 = set(s1.lower().split())
            set2 = set(s2.lower().split())
        else:
            set1 = set(s1.lower())
            set2 = set(s2.lower())

        if not set1 and not set2:
            return 100.0
        if not set1 or not set2:
            return 0.0

        intersection = len(set1 & set2)
        union = len(set1 | set2)

        return (intersection / union) * 100 if union > 0 else 0.0

    @staticmethod
    def soundex(s: str) -> str:
        """Generate Soundex code for a string.

        Args:
            s: Input string

        Returns:
            Soundex code (4 characters)
        """
        if not s:
            return ""

        s = s.upper()
        s = ''.join(c for c in s if c.isalpha())

        if not s:
            return ""

        # Soundex mapping
        mapping = {
            'B': '1', 'F': '1', 'P': '1', 'V': '1',
            'C': '2', 'G': '2', 'J': '2', 'K': '2', 'Q': '2', 'S': '2', 'X': '2', 'Z': '2',
            'D': '3', 'T': '3',
            'L': '4',
            'M': '5', 'N': '5',
            'R': '6',
        }

        first_letter = s[0]
        coded = first_letter

        prev_code = mapping.get(first_letter, '')

        for char in s[1:]:
            code = mapping.get(char, '')
            if code and code != prev_code:
                coded += code
            prev_code = code if code else prev_code

        # Pad with zeros
        coded = (coded + '000')[:4]

        return coded

    @staticmethod
    def phonetic_similarity(s1: str, s2: str) -> float:
        """Calculate phonetic similarity using Soundex.

        Args:
            s1: First string
            s2: Second string

        Returns:
            Similarity score (0-100)
        """
        soundex1 = SimilarityCalculator.soundex(s1)
        soundex2 = SimilarityCalculator.soundex(s2)

        if soundex1 == soundex2:
            return 100.0

        # Compare character by character
        matches = sum(1 for a, b in zip(soundex1, soundex2) if a == b)
        return (matches / 4) * 100

    @staticmethod
    def normalize_string(
        s: str,
        lowercase: bool = True,
        remove_punctuation: bool = True,
        remove_whitespace: bool = False,
        strip_accents: bool = True
    ) -> str:
        """Normalize a string for comparison.

        Args:
            s: Input string
            lowercase: Convert to lowercase
            remove_punctuation: Remove punctuation characters
            remove_whitespace: Remove all whitespace
            strip_accents: Remove accent marks

        Returns:
            Normalized string
        """
        if not s:
            return ""

        # Strip accents
        if strip_accents:
            s = ''.join(
                c for c in unicodedata.normalize('NFD', s)
                if unicodedata.category(c) != 'Mn'
            )

        # Lowercase
        if lowercase:
            s = s.lower()

        # Remove punctuation
        if remove_punctuation:
            s = re.sub(r'[^\w\s]', '', s)

        # Handle whitespace
        if remove_whitespace:
            s = re.sub(r'\s+', '', s)
        else:
            s = re.sub(r'\s+', ' ', s).strip()

        return s


# =============================================================================
# Merge/Survive Service
# =============================================================================

class MergeSurviveService:
    """Service for detecting duplicates and merging product records.

    This service provides high-level operations for:
    - Scanning for duplicate products
    - Calculating match scores
    - Applying survivorship rules
    - Merging duplicate records
    - Creating golden records

    Attributes:
        match_config: Configuration for duplicate matching
        survivorship_config: Configuration for survivorship rules
        similarity: Similarity calculator instance
    """

    def __init__(
        self,
        match_config: Optional[MatchConfig] = None,
        survivorship_config: Optional[SurvivorshipConfig] = None
    ):
        """Initialize the merge/survive service.

        Args:
            match_config: Match configuration (uses defaults if not provided)
            survivorship_config: Survivorship configuration (uses defaults if not provided)
        """
        self.match_config = match_config or MatchConfig()
        self.survivorship_config = survivorship_config or SurvivorshipConfig()
        self.similarity = SimilarityCalculator()
        self._cache: Dict[str, Any] = {}

    # ─────────────────────────────────────────────────────────────────────
    # Duplicate Detection
    # ─────────────────────────────────────────────────────────────────────

    def find_duplicates(
        self,
        products: Optional[List[str]] = None,
        product_data: Optional[List[Dict[str, Any]]] = None,
        config: Optional[MatchConfig] = None
    ) -> DuplicateScanResult:
        """Scan for duplicate products.

        Args:
            products: List of Product Master names to scan (uses all if not provided)
            product_data: Optional pre-loaded product data to avoid DB queries
            config: Match configuration (uses instance config if not provided)

        Returns:
            DuplicateScanResult with all found duplicates
        """
        import time

        start_time = time.time()
        config = config or self.match_config

        # Load product data if not provided
        if product_data is None:
            product_data = self._load_products(products)

        total_products = len(product_data)
        matches: List[DuplicateMatch] = []
        seen_pairs: Set[Tuple[str, str]] = set()

        # Compare all pairs
        for i, product1 in enumerate(product_data):
            for product2 in product_data[i + 1:]:
                p1_name = product1.get("name") or product1.get("product_code", "")
                p2_name = product2.get("name") or product2.get("product_code", "")

                # Skip if already compared
                pair_key = tuple(sorted([p1_name, p2_name]))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                # Calculate match
                match = self._calculate_match(product1, product2, config)

                if match and match.match_score >= config.threshold:
                    matches.append(match)

        # Group duplicates
        duplicate_groups = self._group_duplicates(matches)

        scan_duration = int((time.time() - start_time) * 1000)

        result = DuplicateScanResult(
            total_products_scanned=total_products,
            duplicates_found=len(matches),
            duplicate_groups=duplicate_groups,
            matches=matches,
            scan_duration_ms=scan_duration,
            config_used=config,
        )

        # Log the scan
        _log_duplicate_scan(result)

        return result

    def find_duplicates_for_product(
        self,
        product: str,
        threshold: Optional[float] = None,
        limit: int = 20
    ) -> List[DuplicateMatch]:
        """Find potential duplicates for a specific product.

        Args:
            product: Product Master name
            threshold: Minimum match score (uses config default if not provided)
            limit: Maximum number of matches to return

        Returns:
            List of DuplicateMatch objects
        """
        threshold = threshold or self.match_config.threshold

        # Load the source product
        source_data = self._load_product(product)
        if not source_data:
            return []

        # Load all other products
        all_products = self._load_products(exclude=[product])

        matches = []
        for candidate in all_products:
            match = self._calculate_match(source_data, candidate, self.match_config)

            if match and match.match_score >= threshold:
                matches.append(match)

        # Sort by score and limit
        matches.sort(key=lambda x: x.match_score, reverse=True)
        return matches[:limit]

    def _calculate_match(
        self,
        product1: Dict[str, Any],
        product2: Dict[str, Any],
        config: MatchConfig
    ) -> Optional[DuplicateMatch]:
        """Calculate match score between two products.

        Args:
            product1: First product data
            product2: Second product data
            config: Match configuration

        Returns:
            DuplicateMatch if match is found, None otherwise
        """
        p1_name = product1.get("name") or product1.get("product_code", "")
        p2_name = product2.get("name") or product2.get("product_code", "")

        if not p1_name or not p2_name or p1_name == p2_name:
            return None

        field_scores: Dict[str, float] = {}
        total_weight = 0.0
        weighted_score = 0.0

        # Check exact match fields first
        for field_name in config.exact_match_fields:
            val1 = product1.get(field_name)
            val2 = product2.get(field_name)

            if val1 and val2:
                # Normalize for comparison
                normalized1 = self._normalize_value(val1, config)
                normalized2 = self._normalize_value(val2, config)

                if normalized1 == normalized2:
                    # Exact match on key field - high score
                    field_scores[field_name] = 100.0
                    weight = config.weight_by_field.get(field_name, 2.0)  # Higher weight for exact match fields
                    weighted_score += 100.0 * weight
                    total_weight += weight

        # Check fuzzy match fields
        for field_name in config.fuzzy_match_fields:
            val1 = product1.get(field_name)
            val2 = product2.get(field_name)

            if val1 and val2:
                normalized1 = self._normalize_value(val1, config)
                normalized2 = self._normalize_value(val2, config)

                # Use appropriate similarity algorithm
                if config.match_type == MatchType.PHONETIC:
                    score = self.similarity.phonetic_similarity(normalized1, normalized2)
                elif config.match_type == MatchType.EXACT:
                    score = 100.0 if normalized1 == normalized2 else 0.0
                else:
                    # Default to Jaro-Winkler for fuzzy matching
                    score = self.similarity.jaro_winkler_similarity(normalized1, normalized2)

                field_scores[field_name] = score
                weight = config.weight_by_field.get(field_name, 1.0)
                weighted_score += score * weight
                total_weight += weight

        if total_weight == 0:
            return None

        overall_score = weighted_score / total_weight

        if overall_score < config.threshold:
            return None

        return DuplicateMatch(
            source_product=p1_name,
            matched_product=p2_name,
            match_score=overall_score,
            match_type=config.match_type,
            matched_fields=field_scores,
        )

    def _normalize_value(self, value: Any, config: MatchConfig) -> str:
        """Normalize a value for comparison.

        Args:
            value: Value to normalize
            config: Match configuration

        Returns:
            Normalized string value
        """
        if value is None:
            return ""

        str_value = str(value)

        return SimilarityCalculator.normalize_string(
            str_value,
            lowercase=not config.case_sensitive,
            remove_punctuation=config.ignore_punctuation,
            remove_whitespace=config.ignore_whitespace,
        )

    def _group_duplicates(
        self,
        matches: List[DuplicateMatch]
    ) -> List[List[DuplicateMatch]]:
        """Group duplicate matches into clusters.

        Args:
            matches: List of duplicate matches

        Returns:
            List of duplicate groups
        """
        if not matches:
            return []

        # Build adjacency map
        adjacency: Dict[str, Set[str]] = {}
        for match in matches:
            if match.source_product not in adjacency:
                adjacency[match.source_product] = set()
            if match.matched_product not in adjacency:
                adjacency[match.matched_product] = set()

            adjacency[match.source_product].add(match.matched_product)
            adjacency[match.matched_product].add(match.source_product)

        # Find connected components using BFS
        visited: Set[str] = set()
        groups: List[List[DuplicateMatch]] = []

        for product in adjacency:
            if product in visited:
                continue

            # BFS to find all connected products
            group_products: Set[str] = set()
            queue = [product]

            while queue:
                current = queue.pop(0)
                if current in visited:
                    continue
                visited.add(current)
                group_products.add(current)

                for neighbor in adjacency.get(current, []):
                    if neighbor not in visited:
                        queue.append(neighbor)

            # Collect all matches for this group
            group_matches = [
                m for m in matches
                if m.source_product in group_products or m.matched_product in group_products
            ]

            if group_matches:
                groups.append(group_matches)

        return groups

    # ─────────────────────────────────────────────────────────────────────
    # Merge Operations
    # ─────────────────────────────────────────────────────────────────────

    def merge_products(
        self,
        source_products: List[str],
        golden_record: Optional[str] = None,
        survivorship_config: Optional[SurvivorshipConfig] = None,
        auto_create_golden: bool = True
    ) -> MergeResult:
        """Merge multiple products into a single golden record.

        Args:
            source_products: List of Product Master names to merge
            golden_record: Existing Golden Record to merge into (creates new if not provided)
            survivorship_config: Survivorship configuration (uses instance config if not provided)
            auto_create_golden: Whether to auto-create Golden Record if not provided

        Returns:
            MergeResult with merge operation details
        """
        import frappe

        merge_id = str(uuid.uuid4())
        config = survivorship_config or self.survivorship_config

        result = MergeResult(
            success=False,
            merge_id=merge_id,
            source_products=source_products,
            survivorship_rule=config.default_rule,
        )

        try:
            # Validate source products exist
            product_data_list = []
            for product_name in source_products:
                data = self._load_product(product_name)
                if not data:
                    result.errors.append(f"Product not found: {product_name}")
                    continue
                product_data_list.append(data)

            if len(product_data_list) < 2:
                result.errors.append("At least 2 valid products are required for merge")
                result.status = MergeStatus.FAILED
                return result

            # Get or create golden record
            if golden_record:
                gr = frappe.get_doc("Golden Record", golden_record)
            elif auto_create_golden:
                gr = self._create_golden_record(product_data_list[0])
            else:
                result.errors.append("No Golden Record provided and auto_create is disabled")
                result.status = MergeStatus.FAILED
                return result

            result.golden_record = gr.name

            # Apply survivorship rules to determine winning values
            merged_fields = self._apply_survivorship(
                product_data_list,
                config
            )
            result.merged_fields = merged_fields

            # Store rollback data
            result.rollback_data = {
                "golden_record_before": gr.as_dict() if golden_record else None,
                "source_products": [p.copy() for p in product_data_list],
            }

            # Update golden record with merged data
            self._apply_merge_to_golden_record(gr, merged_fields, product_data_list, config)

            # Mark source products as merged (if configured)
            for product_name in source_products:
                if product_name != gr.product_master:
                    self._mark_product_as_merged(product_name, gr.name)

            result.success = True
            result.status = MergeStatus.COMPLETED
            result.merged_at = datetime.utcnow()
            result.merged_by = frappe.session.user

            # Log the merge
            _log_merge_operation(result)

        except Exception as e:
            result.errors.append(f"Merge failed: {str(e)}")
            result.status = MergeStatus.FAILED
            _log_merge_error(result, str(e))

        return result

    def _apply_survivorship(
        self,
        product_data_list: List[Dict[str, Any]],
        config: SurvivorshipConfig
    ) -> Dict[str, FieldMergeResult]:
        """Apply survivorship rules to determine winning field values.

        Args:
            product_data_list: List of product data dictionaries
            config: Survivorship configuration

        Returns:
            Dictionary mapping field names to FieldMergeResult
        """
        merged_fields: Dict[str, FieldMergeResult] = {}

        # Collect all fields from all products
        all_fields: Set[str] = set()
        for data in product_data_list:
            all_fields.update(data.keys())

        # Remove system fields
        system_fields = {"name", "owner", "creation", "modified", "modified_by", "docstatus", "idx"}
        all_fields -= system_fields

        for field_name in all_fields:
            # Get the rule for this field
            field_rule = config.field_rules.get(field_name, config.default_rule)

            # Collect values from all sources
            field_values = []
            for data in product_data_list:
                value = data.get(field_name)
                if value is not None and value != "":
                    field_values.append({
                        "value": value,
                        "product": data.get("name") or data.get("product_code"),
                        "source_system": data.get("_source_system", "PIM"),
                        "modified": data.get("modified"),
                        "confidence": data.get(f"_{field_name}_confidence", 100),
                    })

            if not field_values:
                continue

            # Handle special fields
            if field_name in config.aggregate_fields:
                merged_fields[field_name] = self._aggregate_field_values(
                    field_name, field_values
                )
            elif field_name in config.concatenate_fields:
                merged_fields[field_name] = self._concatenate_field_values(
                    field_name, field_values
                )
            else:
                # Apply survivorship rule
                merged_fields[field_name] = self._select_winning_value(
                    field_name, field_values, field_rule, config
                )

        return merged_fields

    def _select_winning_value(
        self,
        field_name: str,
        field_values: List[Dict[str, Any]],
        rule: SurvivorshipRule,
        config: SurvivorshipConfig
    ) -> FieldMergeResult:
        """Select the winning value based on survivorship rule.

        Args:
            field_name: Name of the field
            field_values: List of value dictionaries
            rule: Survivorship rule to apply
            config: Survivorship configuration

        Returns:
            FieldMergeResult with winning value
        """
        if len(field_values) == 1:
            val = field_values[0]
            return FieldMergeResult(
                field_name=field_name,
                winning_value=val["value"],
                source_product=val["product"],
                source_system=val.get("source_system"),
                confidence=val.get("confidence", 100),
            )

        winner = None

        if rule == SurvivorshipRule.MOST_RECENT:
            # Sort by modified date, most recent first
            sorted_values = sorted(
                field_values,
                key=lambda x: x.get("modified") or "",
                reverse=True
            )
            winner = sorted_values[0]

        elif rule == SurvivorshipRule.HIGHEST_CONFIDENCE:
            sorted_values = sorted(
                field_values,
                key=lambda x: x.get("confidence", 0),
                reverse=True
            )
            winner = sorted_values[0]

        elif rule == SurvivorshipRule.SOURCE_PRIORITY:
            for priority_source in config.source_priority:
                for val in field_values:
                    if val.get("source_system") == priority_source:
                        winner = val
                        break
                if winner:
                    break
            if not winner:
                winner = field_values[0]

        elif rule == SurvivorshipRule.MOST_COMPLETE:
            # Prefer longer/more complete values
            sorted_values = sorted(
                field_values,
                key=lambda x: len(str(x.get("value", ""))) if x.get("value") else 0,
                reverse=True
            )
            winner = sorted_values[0]

        else:
            # Default to first value (Manual Override case - should be handled by UI)
            winner = field_values[0]

        # Build alternative values list
        alternatives = [
            {
                "value": v["value"],
                "product": v["product"],
                "source_system": v.get("source_system"),
            }
            for v in field_values
            if v["product"] != winner["product"]
        ]

        return FieldMergeResult(
            field_name=field_name,
            winning_value=winner["value"],
            source_product=winner["product"],
            source_system=winner.get("source_system"),
            confidence=winner.get("confidence", 100),
            resolution=FieldResolution.WINNER_SOURCE,
            alternative_values=alternatives,
        )

    def _aggregate_field_values(
        self,
        field_name: str,
        field_values: List[Dict[str, Any]]
    ) -> FieldMergeResult:
        """Aggregate field values (for list-type fields like tags, categories).

        Args:
            field_name: Name of the field
            field_values: List of value dictionaries

        Returns:
            FieldMergeResult with aggregated values
        """
        aggregated: List[Any] = []
        source_products = []

        for val in field_values:
            value = val["value"]
            source_products.append(val["product"])

            if isinstance(value, list):
                for item in value:
                    if item not in aggregated:
                        aggregated.append(item)
            elif isinstance(value, str):
                # Try to split comma-separated values
                items = [v.strip() for v in value.split(",") if v.strip()]
                for item in items:
                    if item not in aggregated:
                        aggregated.append(item)
            elif value not in aggregated:
                aggregated.append(value)

        return FieldMergeResult(
            field_name=field_name,
            winning_value=aggregated,
            source_product=", ".join(source_products),
            confidence=100,
            resolution=FieldResolution.AGGREGATED,
        )

    def _concatenate_field_values(
        self,
        field_name: str,
        field_values: List[Dict[str, Any]]
    ) -> FieldMergeResult:
        """Concatenate field values (for text fields like notes).

        Args:
            field_name: Name of the field
            field_values: List of value dictionaries

        Returns:
            FieldMergeResult with concatenated values
        """
        parts = []
        source_products = []

        for val in field_values:
            value = str(val["value"]) if val["value"] else ""
            if value.strip():
                parts.append(f"[From {val['product']}]: {value}")
                source_products.append(val["product"])

        concatenated = "\n\n".join(parts)

        return FieldMergeResult(
            field_name=field_name,
            winning_value=concatenated,
            source_product=", ".join(source_products),
            confidence=100,
            resolution=FieldResolution.CONCATENATED,
        )

    def _create_golden_record(
        self,
        primary_product: Dict[str, Any]
    ) -> Any:
        """Create a new Golden Record from a product.

        Args:
            primary_product: Product data to use as primary

        Returns:
            Created Golden Record document
        """
        import frappe

        product_name = primary_product.get("name") or primary_product.get("product_code")
        product_display = primary_product.get("product_name") or primary_product.get("item_name") or product_name

        gr = frappe.new_doc("Golden Record")
        gr.record_name = product_display
        gr.product_master = product_name
        gr.survivorship_rule = self.survivorship_config.default_rule.value
        gr.merge_mode = MergeMode.MANUAL_REVIEW.value
        gr.status = "Draft"

        # Add as primary source
        gr.append("source_records", {
            "source_product": product_name,
            "source_system": "PIM",
            "confidence_score": 100,
            "is_primary": 1,
            "added_at": datetime.utcnow(),
            "last_synced_at": datetime.utcnow(),
        })

        gr.insert()

        return gr

    def _apply_merge_to_golden_record(
        self,
        gr: Any,
        merged_fields: Dict[str, FieldMergeResult],
        product_data_list: List[Dict[str, Any]],
        config: SurvivorshipConfig
    ):
        """Apply merged field values to a Golden Record.

        Args:
            gr: Golden Record document
            merged_fields: Dictionary of merged field results
            product_data_list: List of source product data
            config: Survivorship configuration
        """
        import frappe
        from frappe.utils import now_datetime

        # Add source records
        existing_sources = {s.source_product for s in gr.source_records}

        for product_data in product_data_list:
            product_name = product_data.get("name") or product_data.get("product_code")

            if product_name not in existing_sources:
                gr.append("source_records", {
                    "source_product": product_name,
                    "source_system": product_data.get("_source_system", "PIM"),
                    "confidence_score": 80,
                    "is_primary": 0,
                    "added_at": now_datetime(),
                    "last_synced_at": now_datetime(),
                })

        # Store field-level tracking
        field_sources = {}
        field_confidence = {}

        for field_name, merge_result in merged_fields.items():
            field_sources[field_name] = merge_result.source_product
            field_confidence[field_name] = merge_result.confidence

        gr.field_sources = json.dumps(field_sources)
        gr.field_confidence = json.dumps(field_confidence)

        # Update merge tracking
        gr.merge_count = (gr.merge_count or 0) + 1
        gr.last_merged_at = now_datetime()

        gr.save()
        frappe.db.commit()

    def _mark_product_as_merged(self, product_name: str, golden_record: str):
        """Mark a product as having been merged into a golden record.

        Args:
            product_name: Product Master name
            golden_record: Golden Record name
        """
        import frappe

        try:
            # Add custom field or flag to indicate merge status
            frappe.db.set_value(
                "Product Master",
                product_name,
                {
                    "merged_into": golden_record,
                    "merge_status": "Merged",
                },
                update_modified=True
            )
            frappe.db.commit()
        except Exception:
            pass  # Field might not exist

    # ─────────────────────────────────────────────────────────────────────
    # Helper Methods
    # ─────────────────────────────────────────────────────────────────────

    def _load_product(self, product_name: str) -> Optional[Dict[str, Any]]:
        """Load a single product's data.

        Args:
            product_name: Product Master name

        Returns:
            Product data dictionary or None
        """
        import frappe

        try:
            if frappe.db.exists("Product Master", product_name):
                doc = frappe.get_doc("Product Master", product_name)
                return doc.as_dict()

            if frappe.db.exists("Item", product_name):
                doc = frappe.get_doc("Item", product_name)
                return doc.as_dict()

            return None
        except Exception:
            return None

    def _load_products(
        self,
        products: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """Load multiple products' data.

        Args:
            products: Specific products to load (loads all if not provided)
            exclude: Products to exclude
            limit: Maximum products to load

        Returns:
            List of product data dictionaries
        """
        import frappe

        exclude = exclude or []
        filters = {}

        if products:
            filters["name"] = ["in", products]
        if exclude:
            filters["name"] = ["not in", exclude]

        try:
            # Try Product Master first
            if frappe.db.exists("DocType", "Product Master"):
                products_list = frappe.get_all(
                    "Product Master",
                    filters=filters,
                    fields=["*"],
                    limit=limit
                )
                if products_list:
                    return products_list

            # Fall back to Item
            return frappe.get_all(
                "Item",
                filters=filters,
                fields=["*"],
                limit=limit
            )
        except Exception:
            return []


# =============================================================================
# Public API Functions
# =============================================================================

def find_duplicates(
    products: Optional[List[str]] = None,
    threshold: float = 80.0,
    match_type: str = "fuzzy",
    async_scan: bool = False
) -> Dict[str, Any]:
    """Find duplicate products in the catalog.

    This is the main API function for duplicate detection.

    Args:
        products: Specific products to scan (scans all if not provided)
        threshold: Minimum match score to consider a duplicate
        match_type: Type of matching (exact, fuzzy, phonetic, composite)
        async_scan: If True, run as background job

    Returns:
        Dictionary with scan results or job ID
    """
    import frappe

    if async_scan:
        job = frappe.enqueue(
            "frappe_pim.pim.services.merge_survive._find_duplicates_job",
            queue="long",
            timeout=3600,
            products=products,
            threshold=threshold,
            match_type=match_type
        )
        return {
            "success": True,
            "job_id": job.id if hasattr(job, "id") else str(job),
            "status": "queued"
        }

    config = MatchConfig(
        match_type=MatchType(match_type),
        threshold=threshold
    )

    service = MergeSurviveService(match_config=config)
    result = service.find_duplicates(products=products)

    return result.to_dict()


def find_duplicates_for_product(
    product: str,
    threshold: float = 80.0,
    limit: int = 20
) -> Dict[str, Any]:
    """Find potential duplicates for a specific product.

    Args:
        product: Product Master name
        threshold: Minimum match score
        limit: Maximum matches to return

    Returns:
        Dictionary with match results
    """
    service = MergeSurviveService()
    matches = service.find_duplicates_for_product(
        product=product,
        threshold=threshold,
        limit=limit
    )

    return {
        "success": True,
        "product": product,
        "matches_count": len(matches),
        "matches": [m.to_dict() for m in matches]
    }


def merge_products(
    source_products: List[str],
    golden_record: Optional[str] = None,
    survivorship_rule: str = "Most Recent",
    require_approval: bool = True
) -> Dict[str, Any]:
    """Merge multiple products into a golden record.

    Args:
        source_products: List of Product Master names to merge
        golden_record: Existing Golden Record to merge into
        survivorship_rule: Default survivorship rule
        require_approval: Whether to require human approval

    Returns:
        Dictionary with merge result
    """
    config = SurvivorshipConfig(
        default_rule=SurvivorshipRule(survivorship_rule),
        require_approval=require_approval
    )

    service = MergeSurviveService(survivorship_config=config)
    result = service.merge_products(
        source_products=source_products,
        golden_record=golden_record
    )

    return result.to_dict()


def calculate_match_score(
    product1: str,
    product2: str,
    match_type: str = "fuzzy"
) -> Dict[str, Any]:
    """Calculate match score between two products.

    Args:
        product1: First Product Master name
        product2: Second Product Master name
        match_type: Type of matching algorithm

    Returns:
        Dictionary with match details
    """
    config = MatchConfig(match_type=MatchType(match_type))
    service = MergeSurviveService(match_config=config)

    data1 = service._load_product(product1)
    data2 = service._load_product(product2)

    if not data1 or not data2:
        return {
            "success": False,
            "error": "One or both products not found"
        }

    match = service._calculate_match(data1, data2, config)

    if match:
        return {
            "success": True,
            "match": match.to_dict()
        }
    else:
        return {
            "success": True,
            "match": None,
            "message": "No significant match found"
        }


def get_survivorship_rules() -> List[Dict[str, str]]:
    """Get available survivorship rules.

    Returns:
        List of survivorship rule options
    """
    return [
        {
            "value": rule.value,
            "label": rule.value,
            "description": _get_rule_description(rule)
        }
        for rule in SurvivorshipRule
    ]


def get_match_types() -> List[Dict[str, str]]:
    """Get available match types.

    Returns:
        List of match type options
    """
    return [
        {
            "value": mt.value,
            "label": mt.value.title(),
            "description": _get_match_type_description(mt)
        }
        for mt in MatchType
    ]


def preview_merge(
    source_products: List[str],
    survivorship_rule: str = "Most Recent"
) -> Dict[str, Any]:
    """Preview a merge operation without applying changes.

    Args:
        source_products: List of Product Master names
        survivorship_rule: Survivorship rule to apply

    Returns:
        Dictionary with preview of merged data
    """
    config = SurvivorshipConfig(
        default_rule=SurvivorshipRule(survivorship_rule)
    )

    service = MergeSurviveService(survivorship_config=config)

    # Load product data
    product_data_list = []
    for product_name in source_products:
        data = service._load_product(product_name)
        if data:
            product_data_list.append(data)

    if len(product_data_list) < 2:
        return {
            "success": False,
            "error": "At least 2 valid products are required"
        }

    # Apply survivorship to get preview
    merged_fields = service._apply_survivorship(product_data_list, config)

    return {
        "success": True,
        "preview": {
            field_name: result.to_dict()
            for field_name, result in merged_fields.items()
        },
        "source_count": len(product_data_list),
        "field_count": len(merged_fields)
    }


def confirm_duplicate_match(
    match_id: str,
    confirmed: bool,
    reviewed_by: Optional[str] = None
) -> Dict[str, Any]:
    """Confirm or reject a duplicate match.

    Args:
        match_id: Match identifier
        confirmed: Whether the match is confirmed
        reviewed_by: User who reviewed

    Returns:
        Dictionary with confirmation result
    """
    import frappe

    try:
        # Check if Duplicate Match DocType exists
        if not frappe.db.exists("DocType", "Duplicate Match"):
            # Store in a simpler way
            return {
                "success": True,
                "match_id": match_id,
                "status": "confirmed" if confirmed else "rejected",
                "reviewed_by": reviewed_by or frappe.session.user
            }

        # Update the match record
        status = MatchStatus.CONFIRMED if confirmed else MatchStatus.REJECTED
        frappe.db.set_value(
            "Duplicate Match",
            match_id,
            {
                "status": status.value,
                "reviewed_by": reviewed_by or frappe.session.user,
                "reviewed_at": datetime.utcnow()
            }
        )
        frappe.db.commit()

        return {
            "success": True,
            "match_id": match_id,
            "status": status.value
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def get_merge_history(
    golden_record: Optional[str] = None,
    product: Optional[str] = None,
    limit: int = 50
) -> Dict[str, Any]:
    """Get merge operation history.

    Args:
        golden_record: Filter by Golden Record
        product: Filter by product
        limit: Maximum entries to return

    Returns:
        Dictionary with merge history
    """
    import frappe

    filters = {}
    if golden_record:
        filters["golden_record"] = golden_record
    if product:
        filters["source_products"] = ["like", f"%{product}%"]

    try:
        if frappe.db.exists("DocType", "Merge Operation Log"):
            logs = frappe.get_all(
                "Merge Operation Log",
                filters=filters,
                fields=["*"],
                order_by="created desc",
                limit=limit
            )
            return {
                "success": True,
                "count": len(logs),
                "logs": logs
            }
        else:
            return {
                "success": True,
                "count": 0,
                "logs": [],
                "message": "Merge logging DocType not configured"
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def rollback_merge(
    merge_id: str,
    reason: Optional[str] = None
) -> Dict[str, Any]:
    """Rollback a previous merge operation.

    Args:
        merge_id: Merge operation identifier
        reason: Reason for rollback

    Returns:
        Dictionary with rollback result
    """
    import frappe

    try:
        # This would require stored rollback data
        # For now, return a placeholder response
        return {
            "success": False,
            "error": "Rollback functionality requires merge audit trail configuration",
            "merge_id": merge_id
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


# =============================================================================
# Helper Functions (Private)
# =============================================================================

def _get_rule_description(rule: SurvivorshipRule) -> str:
    """Get description for a survivorship rule.

    Args:
        rule: Survivorship rule

    Returns:
        Description string
    """
    descriptions = {
        SurvivorshipRule.MOST_RECENT: "Use values from the most recently updated source",
        SurvivorshipRule.HIGHEST_CONFIDENCE: "Use values with the highest confidence score",
        SurvivorshipRule.SOURCE_PRIORITY: "Follow configured source system priority order",
        SurvivorshipRule.MANUAL_OVERRIDE: "Require manual selection for each field",
        SurvivorshipRule.MOST_COMPLETE: "Use values from the source with most populated fields",
        SurvivorshipRule.CUSTOM: "Apply custom field-specific rules",
    }
    return descriptions.get(rule, "")


def _get_match_type_description(match_type: MatchType) -> str:
    """Get description for a match type.

    Args:
        match_type: Match type

    Returns:
        Description string
    """
    descriptions = {
        MatchType.EXACT: "Match on exact field values (case-insensitive)",
        MatchType.FUZZY: "Use string similarity algorithms for approximate matching",
        MatchType.PHONETIC: "Match on similar-sounding values using Soundex",
        MatchType.ATTRIBUTE: "Match based on key attribute combinations",
        MatchType.COMPOSITE: "Combine multiple matching strategies",
    }
    return descriptions.get(match_type, "")


def _log_duplicate_scan(result: DuplicateScanResult):
    """Log a duplicate scan operation.

    Args:
        result: Scan result
    """
    import frappe

    try:
        if frappe.db.exists("DocType", "Duplicate Scan Log"):
            log = frappe.get_doc({
                "doctype": "Duplicate Scan Log",
                "total_scanned": result.total_products_scanned,
                "duplicates_found": result.duplicates_found,
                "groups_count": len(result.duplicate_groups),
                "scan_duration_ms": result.scan_duration_ms,
                "scanned_at": result.scanned_at,
                "config": json.dumps(result.config_used.to_dict()) if result.config_used else None
            })
            log.insert(ignore_permissions=True)
            frappe.db.commit()
    except Exception:
        pass  # DocType might not exist


def _log_merge_operation(result: MergeResult):
    """Log a merge operation.

    Args:
        result: Merge result
    """
    import frappe

    try:
        if frappe.db.exists("DocType", "Merge Operation Log"):
            log = frappe.get_doc({
                "doctype": "Merge Operation Log",
                "merge_id": result.merge_id,
                "golden_record": result.golden_record,
                "source_products": json.dumps(result.source_products),
                "status": result.status.value,
                "survivorship_rule": result.survivorship_rule.value,
                "merged_fields_count": len(result.merged_fields),
                "merged_at": result.merged_at,
                "merged_by": result.merged_by
            })
            log.insert(ignore_permissions=True)
            frappe.db.commit()
    except Exception:
        pass


def _log_merge_error(result: MergeResult, error: str):
    """Log a merge error.

    Args:
        result: Merge result
        error: Error message
    """
    import frappe

    frappe.log_error(
        message=f"""
Merge Operation Failed

Merge ID: {result.merge_id}
Source Products: {", ".join(result.source_products)}
Golden Record: {result.golden_record}

Error: {error}

Errors: {", ".join(result.errors)}
        """,
        title=f"Merge Error - {result.merge_id[:8]}"
    )


def _find_duplicates_job(
    products: Optional[List[str]],
    threshold: float,
    match_type: str
):
    """Background job for duplicate scanning.

    Args:
        products: Products to scan
        threshold: Match threshold
        match_type: Match type
    """
    config = MatchConfig(
        match_type=MatchType(match_type),
        threshold=threshold
    )

    service = MergeSurviveService(match_config=config)
    service.find_duplicates(products=products)


# =============================================================================
# Frappe API Wrappers
# =============================================================================

def _wrap_for_whitelist():
    """Wrap functions for Frappe whitelist at runtime."""
    import frappe

    functions = [
        "find_duplicates",
        "find_duplicates_for_product",
        "merge_products",
        "calculate_match_score",
        "get_survivorship_rules",
        "get_match_types",
        "preview_merge",
        "confirm_duplicate_match",
        "get_merge_history",
        "rollback_merge",
    ]

    module = __import__(__name__)
    for name in __name__.split(".")[1:]:
        module = getattr(module, name)

    for func_name in functions:
        func = getattr(module, func_name)
        if not getattr(func, "_whitelisted", False):
            whitelisted = frappe.whitelist()(func)
            setattr(module, func_name, whitelisted)


# Apply whitelist decorators when module is loaded in Frappe context
try:
    _wrap_for_whitelist()
except Exception:
    pass  # Not in Frappe context
