"""AI Translation Service

This module provides AI-powered translation services for multi-language product content:
- Product description translation with context awareness
- SEO content localization
- Attribute value translation
- Glossary-enforced terminology consistency
- Translation memory for reuse and cost optimization
- Quality scoring for translations

The service supports multiple AI providers:
- OpenAI (GPT-4, GPT-3.5-turbo)
- Anthropic Claude (Claude 3 Opus, Sonnet, Haiku)
- Google Gemini
- Google Translate API (for basic translations)
- DeepL API (for high-quality translations)

Key Concepts:
- Glossary: Domain-specific terminology mappings for consistent translations
- Translation Memory: Cache of previous translations for reuse
- Translation Request: A request to translate product content
- Translation Result: Translated content with quality scores
- Language Pair: Source and target language combination

Human-in-the-Loop Workflow:
1. User requests translation for product content
2. System checks translation memory for existing translations
3. Glossary terms are applied during translation
4. AI generates translation with quality score
5. Results are queued for human review (if required)
6. Approved translations are applied and stored in translation memory

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Union


# =============================================================================
# Constants and Enums
# =============================================================================

class TranslationProvider(Enum):
    """Supported translation providers."""
    OPENAI = "OpenAI"
    ANTHROPIC = "Anthropic"
    GOOGLE_GEMINI = "Google Gemini"
    GOOGLE_TRANSLATE = "Google Translate"
    DEEPL = "DeepL"


class TranslationStatus(Enum):
    """Status of a translation request."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"


class TranslationQuality(Enum):
    """Translation quality levels."""
    EXCELLENT = "excellent"  # >= 0.9
    GOOD = "good"           # >= 0.75
    ACCEPTABLE = "acceptable"  # >= 0.6
    NEEDS_REVIEW = "needs_review"  # >= 0.4
    POOR = "poor"           # < 0.4


class ContentType(Enum):
    """Types of content that can be translated."""
    PRODUCT_TITLE = "product_title"
    SHORT_DESCRIPTION = "short_description"
    LONG_DESCRIPTION = "long_description"
    BULLET_POINTS = "bullet_points"
    KEYWORDS = "keywords"
    META_DESCRIPTION = "meta_description"
    SEO_TITLE = "seo_title"
    ATTRIBUTE_VALUE = "attribute_value"
    CATEGORY_NAME = "category_name"
    BRAND_DESCRIPTION = "brand_description"


class GlossaryMatchType(Enum):
    """How to match glossary terms."""
    EXACT = "exact"           # Exact string match
    CASE_INSENSITIVE = "case_insensitive"  # Case-insensitive match
    WHOLE_WORD = "whole_word"  # Match whole words only
    REGEX = "regex"           # Regular expression match


# Supported languages with ISO 639-1 codes
SUPPORTED_LANGUAGES = {
    "en": "English",
    "tr": "Turkish",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "pl": "Polish",
    "ru": "Russian",
    "zh": "Chinese (Simplified)",
    "zh-TW": "Chinese (Traditional)",
    "ja": "Japanese",
    "ko": "Korean",
    "ar": "Arabic",
    "he": "Hebrew",
    "sv": "Swedish",
    "da": "Danish",
    "fi": "Finnish",
    "no": "Norwegian",
    "cs": "Czech",
    "sk": "Slovak",
    "hu": "Hungarian",
    "ro": "Romanian",
    "bg": "Bulgarian",
    "uk": "Ukrainian",
    "el": "Greek",
    "th": "Thai",
    "vi": "Vietnamese",
    "id": "Indonesian",
    "ms": "Malay",
    "hi": "Hindi",
}

# Provider-specific API endpoints
API_ENDPOINTS = {
    TranslationProvider.OPENAI: "https://api.openai.com/v1/chat/completions",
    TranslationProvider.ANTHROPIC: "https://api.anthropic.com/v1/messages",
    TranslationProvider.GOOGLE_GEMINI: "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
    TranslationProvider.GOOGLE_TRANSLATE: "https://translation.googleapis.com/language/translate/v2",
    TranslationProvider.DEEPL: "https://api.deepl.com/v2/translate",
}

# Default models per provider
DEFAULT_MODELS = {
    TranslationProvider.OPENAI: "gpt-4-turbo-preview",
    TranslationProvider.ANTHROPIC: "claude-3-sonnet-20240229",
    TranslationProvider.GOOGLE_GEMINI: "gemini-pro",
}

# Maximum characters for different content types
MAX_CHARS = {
    ContentType.PRODUCT_TITLE: 200,
    ContentType.SHORT_DESCRIPTION: 500,
    ContentType.LONG_DESCRIPTION: 5000,
    ContentType.BULLET_POINTS: 2000,
    ContentType.KEYWORDS: 500,
    ContentType.META_DESCRIPTION: 320,
    ContentType.SEO_TITLE: 70,
    ContentType.ATTRIBUTE_VALUE: 200,
    ContentType.CATEGORY_NAME: 100,
    ContentType.BRAND_DESCRIPTION: 2000,
}

# Rate limits per provider (requests per minute)
RATE_LIMITS = {
    TranslationProvider.OPENAI: 60,
    TranslationProvider.ANTHROPIC: 50,
    TranslationProvider.GOOGLE_GEMINI: 60,
    TranslationProvider.GOOGLE_TRANSLATE: 100,
    TranslationProvider.DEEPL: 100,
}


# =============================================================================
# Prompt Templates
# =============================================================================

TRANSLATION_PROMPT_TEMPLATE = """You are a professional translator specializing in e-commerce product content.
Translate the following {content_type} from {source_language} to {target_language}.

IMPORTANT RULES:
1. Maintain the original meaning, tone, and style
2. Adapt cultural references and idioms appropriately for the target market
3. Keep product specifications, measurements, and technical terms accurate
4. Preserve any HTML tags, markdown formatting, or special characters
5. Do not translate brand names, product codes, or model numbers
6. Ensure SEO optimization for the target language market

{glossary_section}

Source Text:
{source_text}

{additional_context}

Respond with ONLY the translated text, no explanations or notes."""

GLOSSARY_SECTION_TEMPLATE = """GLOSSARY - Use these exact translations for the following terms:
{glossary_entries}

You MUST use these exact translations when these terms appear in the source text."""

QUALITY_CHECK_PROMPT = """Rate the quality of the following translation on a scale of 0 to 1.
Consider:
1. Accuracy - Does it convey the original meaning?
2. Fluency - Does it sound natural in the target language?
3. Terminology - Are technical terms translated correctly?
4. Style - Is the tone appropriate for e-commerce?
5. Completeness - Is all content translated?

Source ({source_language}):
{source_text}

Translation ({target_language}):
{translated_text}

Respond in JSON format:
{{"score": 0.85, "issues": ["list of any issues found"], "suggestions": ["improvement suggestions"]}}"""


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class GlossaryTerm:
    """A term in the translation glossary."""
    source_term: str
    target_term: str
    source_language: str
    target_language: str
    match_type: GlossaryMatchType = GlossaryMatchType.CASE_INSENSITIVE
    context: Optional[str] = None  # Category/domain context
    notes: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    def matches(self, text: str) -> List[Tuple[int, int]]:
        """Find all matches of this term in text.

        Returns:
            List of (start, end) tuples for each match
        """
        matches = []

        if self.match_type == GlossaryMatchType.EXACT:
            start = 0
            while True:
                pos = text.find(self.source_term, start)
                if pos == -1:
                    break
                matches.append((pos, pos + len(self.source_term)))
                start = pos + 1

        elif self.match_type == GlossaryMatchType.CASE_INSENSITIVE:
            text_lower = text.lower()
            term_lower = self.source_term.lower()
            start = 0
            while True:
                pos = text_lower.find(term_lower, start)
                if pos == -1:
                    break
                matches.append((pos, pos + len(self.source_term)))
                start = pos + 1

        elif self.match_type == GlossaryMatchType.WHOLE_WORD:
            pattern = r'\b' + re.escape(self.source_term) + r'\b'
            for match in re.finditer(pattern, text, re.IGNORECASE):
                matches.append((match.start(), match.end()))

        elif self.match_type == GlossaryMatchType.REGEX:
            try:
                for match in re.finditer(self.source_term, text):
                    matches.append((match.start(), match.end()))
            except re.error:
                pass

        return matches

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "source_term": self.source_term,
            "target_term": self.target_term,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "match_type": self.match_type.value,
            "context": self.context,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class Glossary:
    """A collection of glossary terms."""
    name: str
    source_language: str
    target_language: str
    terms: List[GlossaryTerm] = field(default_factory=list)
    description: Optional[str] = None
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)

    def add_term(self, source: str, target: str,
                 match_type: GlossaryMatchType = GlossaryMatchType.CASE_INSENSITIVE,
                 context: Optional[str] = None,
                 notes: Optional[str] = None) -> GlossaryTerm:
        """Add a term to the glossary."""
        term = GlossaryTerm(
            source_term=source,
            target_term=target,
            source_language=self.source_language,
            target_language=self.target_language,
            match_type=match_type,
            context=context,
            notes=notes,
        )
        self.terms.append(term)
        return term

    def get_matching_terms(self, text: str, context: Optional[str] = None) -> List[GlossaryTerm]:
        """Get all glossary terms that match in the text."""
        matching = []
        for term in self.terms:
            # Skip if context specified and doesn't match
            if context and term.context and term.context != context:
                continue
            if term.matches(text):
                matching.append(term)
        return matching

    def format_for_prompt(self, matching_terms: List[GlossaryTerm]) -> str:
        """Format matching terms for the translation prompt."""
        if not matching_terms:
            return ""

        entries = []
        for term in matching_terms:
            entry = f'"{term.source_term}" -> "{term.target_term}"'
            if term.notes:
                entry += f" ({term.notes})"
            entries.append(entry)

        return GLOSSARY_SECTION_TEMPLATE.format(
            glossary_entries="\n".join(f"- {e}" for e in entries)
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "terms": [t.to_dict() for t in self.terms],
            "description": self.description,
            "is_active": self.is_active,
            "term_count": len(self.terms),
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class TranslationMemoryEntry:
    """An entry in the translation memory."""
    source_text: str
    translated_text: str
    source_language: str
    target_language: str
    content_type: ContentType
    hash_key: str = ""
    quality_score: float = 0.0
    use_count: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_used: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self):
        if not self.hash_key:
            self.hash_key = self._generate_hash()

    def _generate_hash(self) -> str:
        """Generate a unique hash for this translation pair."""
        key_string = f"{self.source_language}:{self.target_language}:{self.source_text}"
        return hashlib.sha256(key_string.encode()).hexdigest()[:32]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "source_text": self.source_text,
            "translated_text": self.translated_text,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "content_type": self.content_type.value,
            "hash_key": self.hash_key,
            "quality_score": round(self.quality_score, 3),
            "use_count": self.use_count,
            "created_at": self.created_at.isoformat(),
            "last_used": self.last_used.isoformat(),
        }


@dataclass
class TranslationRequest:
    """Request for content translation."""
    source_text: str
    source_language: str
    target_language: str
    content_type: ContentType
    product: Optional[str] = None
    field_name: Optional[str] = None
    glossary_name: Optional[str] = None
    additional_context: Optional[str] = None
    use_translation_memory: bool = True
    require_review: bool = False
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "source_text": self.source_text,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "content_type": self.content_type.value,
            "product": self.product,
            "field_name": self.field_name,
            "glossary_name": self.glossary_name,
            "additional_context": self.additional_context,
            "use_translation_memory": self.use_translation_memory,
            "require_review": self.require_review,
            "request_id": self.request_id,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class TranslationResult:
    """Result of a translation request."""
    request_id: str
    source_text: str
    translated_text: str
    source_language: str
    target_language: str
    content_type: ContentType
    status: TranslationStatus
    quality_score: float = 0.0
    from_memory: bool = False
    glossary_terms_used: List[str] = field(default_factory=list)
    provider: Optional[TranslationProvider] = None
    model: Optional[str] = None
    processing_time_ms: int = 0
    tokens_used: int = 0
    error_message: Optional[str] = None
    quality_issues: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def quality_level(self) -> TranslationQuality:
        """Get quality level from score."""
        if self.quality_score >= 0.9:
            return TranslationQuality.EXCELLENT
        elif self.quality_score >= 0.75:
            return TranslationQuality.GOOD
        elif self.quality_score >= 0.6:
            return TranslationQuality.ACCEPTABLE
        elif self.quality_score >= 0.4:
            return TranslationQuality.NEEDS_REVIEW
        else:
            return TranslationQuality.POOR

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "request_id": self.request_id,
            "source_text": self.source_text,
            "translated_text": self.translated_text,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "content_type": self.content_type.value,
            "status": self.status.value,
            "quality_score": round(self.quality_score, 3),
            "quality_level": self.quality_level.value,
            "from_memory": self.from_memory,
            "glossary_terms_used": self.glossary_terms_used,
            "provider": self.provider.value if self.provider else None,
            "model": self.model,
            "processing_time_ms": self.processing_time_ms,
            "tokens_used": self.tokens_used,
            "error_message": self.error_message,
            "quality_issues": self.quality_issues,
            "suggestions": self.suggestions,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class BulkTranslationResult:
    """Result of bulk translation operation."""
    total_items: int
    successful: int = 0
    failed: int = 0
    from_memory: int = 0
    results: List[TranslationResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    processing_time_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_items": self.total_items,
            "successful": self.successful,
            "failed": self.failed,
            "from_memory": self.from_memory,
            "success_rate": round(self.successful / max(self.total_items, 1) * 100, 1),
            "memory_hit_rate": round(self.from_memory / max(self.successful, 1) * 100, 1),
            "results": [r.to_dict() for r in self.results],
            "errors": self.errors,
            "processing_time_ms": self.processing_time_ms,
        }


@dataclass
class ProductTranslation:
    """Complete translation of a product's content."""
    product: str
    source_language: str
    target_language: str
    translations: Dict[str, TranslationResult] = field(default_factory=dict)
    overall_quality: float = 0.0
    status: TranslationStatus = TranslationStatus.PENDING
    created_at: datetime = field(default_factory=datetime.utcnow)

    def add_translation(self, field_name: str, result: TranslationResult):
        """Add a field translation."""
        self.translations[field_name] = result
        self._recalculate_quality()

    def _recalculate_quality(self):
        """Recalculate overall quality score."""
        if not self.translations:
            self.overall_quality = 0.0
            return

        scores = [t.quality_score for t in self.translations.values()]
        self.overall_quality = sum(scores) / len(scores)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "product": self.product,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "translations": {k: v.to_dict() for k, v in self.translations.items()},
            "field_count": len(self.translations),
            "overall_quality": round(self.overall_quality, 3),
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
        }


# =============================================================================
# Translation Memory Manager
# =============================================================================

class TranslationMemoryManager:
    """Manages translation memory for reuse and cost optimization."""

    def __init__(self, max_entries: int = 10000):
        """Initialize the translation memory manager.

        Args:
            max_entries: Maximum entries to keep in memory
        """
        self.max_entries = max_entries
        self._memory: Dict[str, TranslationMemoryEntry] = {}
        self._loaded = False

    def _ensure_loaded(self):
        """Load translation memory from database if available."""
        if self._loaded:
            return

        try:
            import frappe

            if not frappe.db.exists("DocType", "Translation Memory"):
                self._loaded = True
                return

            entries = frappe.get_all(
                "Translation Memory",
                filters={"is_active": 1},
                fields=[
                    "name", "source_text", "translated_text",
                    "source_language", "target_language", "content_type",
                    "hash_key", "quality_score", "use_count"
                ],
                limit=self.max_entries,
                order_by="use_count desc"
            )

            for entry in entries:
                content_type = ContentType(entry.get("content_type", "product_title"))
                tm_entry = TranslationMemoryEntry(
                    source_text=entry["source_text"],
                    translated_text=entry["translated_text"],
                    source_language=entry["source_language"],
                    target_language=entry["target_language"],
                    content_type=content_type,
                    hash_key=entry.get("hash_key", ""),
                    quality_score=entry.get("quality_score", 0.0),
                    use_count=entry.get("use_count", 0),
                )
                self._memory[tm_entry.hash_key] = tm_entry

            self._loaded = True

        except Exception:
            self._loaded = True

    def lookup(self, source_text: str, source_language: str,
               target_language: str) -> Optional[TranslationMemoryEntry]:
        """Look up a translation in memory.

        Args:
            source_text: Text to translate
            source_language: Source language code
            target_language: Target language code

        Returns:
            Translation memory entry if found
        """
        self._ensure_loaded()

        key_string = f"{source_language}:{target_language}:{source_text}"
        hash_key = hashlib.sha256(key_string.encode()).hexdigest()[:32]

        entry = self._memory.get(hash_key)
        if entry:
            entry.use_count += 1
            entry.last_used = datetime.utcnow()
            self._update_use_count(entry)

        return entry

    def store(self, result: TranslationResult) -> TranslationMemoryEntry:
        """Store a translation result in memory.

        Args:
            result: Translation result to store

        Returns:
            Created translation memory entry
        """
        self._ensure_loaded()

        entry = TranslationMemoryEntry(
            source_text=result.source_text,
            translated_text=result.translated_text,
            source_language=result.source_language,
            target_language=result.target_language,
            content_type=result.content_type,
            quality_score=result.quality_score,
            use_count=1,
        )

        # Store in local memory
        self._memory[entry.hash_key] = entry

        # Store in database
        self._save_to_database(entry)

        # Cleanup old entries if needed
        if len(self._memory) > self.max_entries:
            self._cleanup_old_entries()

        return entry

    def _update_use_count(self, entry: TranslationMemoryEntry):
        """Update use count in database."""
        try:
            import frappe

            if not frappe.db.exists("DocType", "Translation Memory"):
                return

            if frappe.db.exists("Translation Memory", {"hash_key": entry.hash_key}):
                frappe.db.set_value(
                    "Translation Memory",
                    {"hash_key": entry.hash_key},
                    {
                        "use_count": entry.use_count,
                        "last_used": entry.last_used
                    },
                    update_modified=False
                )
        except Exception:
            pass

    def _save_to_database(self, entry: TranslationMemoryEntry):
        """Save entry to database."""
        try:
            import frappe

            if not frappe.db.exists("DocType", "Translation Memory"):
                return

            if frappe.db.exists("Translation Memory", {"hash_key": entry.hash_key}):
                return  # Already exists

            doc = frappe.get_doc({
                "doctype": "Translation Memory",
                "source_text": entry.source_text[:65535],  # Limit for Text field
                "translated_text": entry.translated_text[:65535],
                "source_language": entry.source_language,
                "target_language": entry.target_language,
                "content_type": entry.content_type.value,
                "hash_key": entry.hash_key,
                "quality_score": entry.quality_score,
                "use_count": entry.use_count,
                "is_active": 1,
            })
            doc.insert(ignore_permissions=True)
            frappe.db.commit()

        except Exception:
            pass

    def _cleanup_old_entries(self):
        """Remove least-used entries to stay under limit."""
        if len(self._memory) <= self.max_entries:
            return

        # Sort by use count (ascending) and remove bottom 10%
        sorted_keys = sorted(
            self._memory.keys(),
            key=lambda k: self._memory[k].use_count
        )

        remove_count = len(self._memory) - int(self.max_entries * 0.9)
        for key in sorted_keys[:remove_count]:
            del self._memory[key]

    def get_stats(self) -> Dict[str, Any]:
        """Get translation memory statistics."""
        self._ensure_loaded()

        total_uses = sum(e.use_count for e in self._memory.values())

        # Group by language pair
        lang_pairs = {}
        for entry in self._memory.values():
            pair = f"{entry.source_language}->{entry.target_language}"
            lang_pairs[pair] = lang_pairs.get(pair, 0) + 1

        return {
            "total_entries": len(self._memory),
            "total_uses": total_uses,
            "language_pairs": lang_pairs,
            "average_quality": sum(e.quality_score for e in self._memory.values()) / max(len(self._memory), 1),
        }


# =============================================================================
# Glossary Manager
# =============================================================================

class GlossaryManager:
    """Manages glossaries for consistent terminology."""

    def __init__(self):
        """Initialize the glossary manager."""
        self._glossaries: Dict[str, Glossary] = {}
        self._loaded = False

    def _ensure_loaded(self):
        """Load glossaries from database if available."""
        if self._loaded:
            return

        try:
            import frappe

            if not frappe.db.exists("DocType", "Translation Glossary"):
                self._loaded = True
                return

            # Load glossaries
            glossaries = frappe.get_all(
                "Translation Glossary",
                filters={"is_active": 1},
                fields=["name", "source_language", "target_language", "description"]
            )

            for g in glossaries:
                glossary = Glossary(
                    name=g["name"],
                    source_language=g["source_language"],
                    target_language=g["target_language"],
                    description=g.get("description"),
                )

                # Load terms for this glossary
                if frappe.db.exists("DocType", "Glossary Term"):
                    terms = frappe.get_all(
                        "Glossary Term",
                        filters={"parent": g["name"]},
                        fields=[
                            "source_term", "target_term", "match_type",
                            "context", "notes"
                        ]
                    )

                    for t in terms:
                        match_type = GlossaryMatchType(
                            t.get("match_type", "case_insensitive")
                        )
                        glossary.add_term(
                            source=t["source_term"],
                            target=t["target_term"],
                            match_type=match_type,
                            context=t.get("context"),
                            notes=t.get("notes"),
                        )

                self._glossaries[g["name"]] = glossary

            self._loaded = True

        except Exception:
            self._loaded = True

    def get_glossary(self, name: str) -> Optional[Glossary]:
        """Get a glossary by name."""
        self._ensure_loaded()
        return self._glossaries.get(name)

    def get_glossary_for_language_pair(
        self,
        source_language: str,
        target_language: str
    ) -> Optional[Glossary]:
        """Get glossary for a language pair."""
        self._ensure_loaded()

        for glossary in self._glossaries.values():
            if (glossary.source_language == source_language and
                glossary.target_language == target_language):
                return glossary

        return None

    def list_glossaries(self) -> List[Dict[str, Any]]:
        """List all available glossaries."""
        self._ensure_loaded()
        return [g.to_dict() for g in self._glossaries.values()]

    def create_glossary(
        self,
        name: str,
        source_language: str,
        target_language: str,
        description: Optional[str] = None
    ) -> Glossary:
        """Create a new glossary."""
        glossary = Glossary(
            name=name,
            source_language=source_language,
            target_language=target_language,
            description=description,
        )

        self._glossaries[name] = glossary
        self._save_glossary_to_database(glossary)

        return glossary

    def add_term_to_glossary(
        self,
        glossary_name: str,
        source_term: str,
        target_term: str,
        match_type: str = "case_insensitive",
        context: Optional[str] = None,
        notes: Optional[str] = None
    ) -> Optional[GlossaryTerm]:
        """Add a term to a glossary."""
        self._ensure_loaded()

        glossary = self._glossaries.get(glossary_name)
        if not glossary:
            return None

        term = glossary.add_term(
            source=source_term,
            target=target_term,
            match_type=GlossaryMatchType(match_type),
            context=context,
            notes=notes,
        )

        self._save_term_to_database(glossary_name, term)

        return term

    def _save_glossary_to_database(self, glossary: Glossary):
        """Save glossary to database."""
        try:
            import frappe

            if not frappe.db.exists("DocType", "Translation Glossary"):
                return

            if frappe.db.exists("Translation Glossary", glossary.name):
                return

            doc = frappe.get_doc({
                "doctype": "Translation Glossary",
                "glossary_name": glossary.name,
                "source_language": glossary.source_language,
                "target_language": glossary.target_language,
                "description": glossary.description,
                "is_active": 1,
            })
            doc.insert(ignore_permissions=True)
            frappe.db.commit()

        except Exception:
            pass

    def _save_term_to_database(self, glossary_name: str, term: GlossaryTerm):
        """Save term to database."""
        try:
            import frappe

            if not frappe.db.exists("DocType", "Glossary Term"):
                return

            doc = frappe.get_doc({
                "doctype": "Glossary Term",
                "parent": glossary_name,
                "parenttype": "Translation Glossary",
                "parentfield": "terms",
                "source_term": term.source_term,
                "target_term": term.target_term,
                "match_type": term.match_type.value,
                "context": term.context,
                "notes": term.notes,
            })
            doc.insert(ignore_permissions=True)
            frappe.db.commit()

        except Exception:
            pass


# =============================================================================
# AI Translation Service
# =============================================================================

class AITranslationService:
    """Service for AI-powered content translation.

    This service provides high-level operations for translating product
    content using AI providers, with glossary support and translation memory.

    Attributes:
        provider: Translation provider to use
        model: Specific model to use
        api_key: API key for the provider
        memory_manager: Translation memory manager
        glossary_manager: Glossary manager
    """

    def __init__(
        self,
        provider: Optional[TranslationProvider] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        use_memory: bool = True,
        use_glossary: bool = True
    ):
        """Initialize the AI translation service.

        Args:
            provider: Translation provider (loaded from settings if not provided)
            model: Model to use (loaded from settings if not provided)
            api_key: API key (loaded from settings if not provided)
            use_memory: Whether to use translation memory
            use_glossary: Whether to use glossaries
        """
        self._provider = provider
        self._model = model
        self._api_key = api_key
        self.use_memory = use_memory
        self.use_glossary = use_glossary
        self._initialized = False

        self.memory_manager = TranslationMemoryManager() if use_memory else None
        self.glossary_manager = GlossaryManager() if use_glossary else None

    def _ensure_initialized(self):
        """Ensure the service is initialized with settings."""
        if self._initialized:
            return

        if not self._provider or not self._api_key:
            config = _get_translation_config()
            if not config:
                raise ValueError(
                    "AI translation is not enabled. Please configure in PIM Settings."
                )

            if not self._provider:
                provider_str = config.get("provider")
                if provider_str:
                    self._provider = TranslationProvider(provider_str)
                else:
                    # Default to AI enrichment provider
                    self._provider = TranslationProvider.OPENAI

            if not self._api_key:
                self._api_key = _get_translation_api_key()
                if not self._api_key:
                    raise ValueError("Translation API key is not configured.")

            if not self._model:
                self._model = config.get("model") or DEFAULT_MODELS.get(self._provider)

        self._initialized = True

    @property
    def provider(self) -> TranslationProvider:
        """Get the translation provider."""
        self._ensure_initialized()
        return self._provider

    @property
    def model(self) -> str:
        """Get the model name."""
        self._ensure_initialized()
        return self._model

    def translate(self, request: TranslationRequest) -> TranslationResult:
        """Translate content based on the request.

        Args:
            request: Translation request

        Returns:
            TranslationResult with translated content
        """
        import time

        self._ensure_initialized()
        start_time = time.time()

        result = TranslationResult(
            request_id=request.request_id,
            source_text=request.source_text,
            translated_text="",
            source_language=request.source_language,
            target_language=request.target_language,
            content_type=request.content_type,
            status=TranslationStatus.PROCESSING,
            provider=self.provider,
            model=self.model,
        )

        try:
            # Check translation memory first
            if self.use_memory and request.use_translation_memory:
                memory_entry = self.memory_manager.lookup(
                    request.source_text,
                    request.source_language,
                    request.target_language
                )
                if memory_entry and memory_entry.quality_score >= 0.7:
                    result.translated_text = memory_entry.translated_text
                    result.quality_score = memory_entry.quality_score
                    result.from_memory = True
                    result.status = TranslationStatus.COMPLETED
                    result.processing_time_ms = int((time.time() - start_time) * 1000)
                    return result

            # Get matching glossary terms
            glossary_terms = []
            if self.use_glossary:
                glossary = None
                if request.glossary_name:
                    glossary = self.glossary_manager.get_glossary(request.glossary_name)
                else:
                    glossary = self.glossary_manager.get_glossary_for_language_pair(
                        request.source_language,
                        request.target_language
                    )

                if glossary:
                    glossary_terms = glossary.get_matching_terms(request.source_text)

            # Build prompt
            prompt = self._build_prompt(request, glossary_terms)

            # Call AI provider
            ai_response = self._call_provider(prompt, request.content_type)

            result.translated_text = ai_response.get("content", "")
            result.tokens_used = ai_response.get("total_tokens", 0)

            # Record glossary terms used
            if glossary_terms:
                result.glossary_terms_used = [t.source_term for t in glossary_terms]

            # Check quality
            quality_result = self._check_translation_quality(request, result)
            result.quality_score = quality_result.get("score", 0.8)
            result.quality_issues = quality_result.get("issues", [])
            result.suggestions = quality_result.get("suggestions", [])

            # Determine status based on quality and review requirements
            if request.require_review or result.quality_score < 0.6:
                result.status = TranslationStatus.NEEDS_REVIEW
                _create_translation_review_entry(request, result)
            else:
                result.status = TranslationStatus.COMPLETED

            # Store in translation memory
            if self.use_memory and result.quality_score >= 0.7:
                self.memory_manager.store(result)

        except Exception as e:
            result.status = TranslationStatus.FAILED
            result.error_message = str(e)
            _log_translation_error(request, str(e))

        result.processing_time_ms = int((time.time() - start_time) * 1000)

        # Log the result
        _log_translation_result(request, result)

        return result

    def translate_text(
        self,
        text: str,
        source_language: str,
        target_language: str,
        content_type: str = "product_title",
        glossary_name: Optional[str] = None
    ) -> TranslationResult:
        """Translate a text string.

        Args:
            text: Text to translate
            source_language: Source language code
            target_language: Target language code
            content_type: Type of content
            glossary_name: Optional glossary to use

        Returns:
            TranslationResult
        """
        request = TranslationRequest(
            source_text=text,
            source_language=source_language,
            target_language=target_language,
            content_type=ContentType(content_type),
            glossary_name=glossary_name,
        )

        return self.translate(request)

    def translate_product(
        self,
        product: str,
        target_language: str,
        source_language: str = "en",
        fields: Optional[List[str]] = None,
        glossary_name: Optional[str] = None
    ) -> ProductTranslation:
        """Translate all fields of a product.

        Args:
            product: Product Master name
            target_language: Target language code
            source_language: Source language code
            fields: Specific fields to translate (default: all translatable)
            glossary_name: Optional glossary to use

        Returns:
            ProductTranslation with all field translations
        """
        self._ensure_initialized()

        product_data = _get_product_data(product)
        if not product_data:
            translation = ProductTranslation(
                product=product,
                source_language=source_language,
                target_language=target_language,
                status=TranslationStatus.FAILED,
            )
            return translation

        # Default translatable fields
        if not fields:
            fields = ["item_name", "description", "pim_title", "pim_description"]

        # Field to content type mapping
        field_type_map = {
            "item_name": ContentType.PRODUCT_TITLE,
            "pim_title": ContentType.PRODUCT_TITLE,
            "description": ContentType.LONG_DESCRIPTION,
            "pim_description": ContentType.SHORT_DESCRIPTION,
            "web_short_description": ContentType.SHORT_DESCRIPTION,
            "web_long_description": ContentType.LONG_DESCRIPTION,
        }

        translation = ProductTranslation(
            product=product,
            source_language=source_language,
            target_language=target_language,
        )

        for field_name in fields:
            source_text = product_data.get(field_name)
            if not source_text:
                continue

            content_type = field_type_map.get(field_name, ContentType.PRODUCT_TITLE)

            request = TranslationRequest(
                source_text=source_text,
                source_language=source_language,
                target_language=target_language,
                content_type=content_type,
                product=product,
                field_name=field_name,
                glossary_name=glossary_name,
            )

            result = self.translate(request)
            translation.add_translation(field_name, result)

        # Set overall status
        if all(t.status == TranslationStatus.COMPLETED
               for t in translation.translations.values()):
            translation.status = TranslationStatus.COMPLETED
        elif any(t.status == TranslationStatus.FAILED
                 for t in translation.translations.values()):
            translation.status = TranslationStatus.FAILED
        else:
            translation.status = TranslationStatus.NEEDS_REVIEW

        return translation

    def bulk_translate(
        self,
        products: List[str],
        target_language: str,
        source_language: str = "en",
        fields: Optional[List[str]] = None,
        glossary_name: Optional[str] = None,
        async_process: bool = True
    ) -> BulkTranslationResult:
        """Translate multiple products.

        Args:
            products: List of Product Master names
            target_language: Target language code
            source_language: Source language code
            fields: Specific fields to translate
            glossary_name: Optional glossary to use
            async_process: If True, process in background

        Returns:
            BulkTranslationResult
        """
        import frappe
        import time

        self._ensure_initialized()
        start_time = time.time()

        bulk_result = BulkTranslationResult(
            total_items=len(products)
        )

        if async_process and len(products) > 3:
            # Enqueue as background job
            frappe.enqueue(
                "frappe_pim.pim.services.ai_translation._bulk_translate_job",
                queue="long",
                timeout=3600,
                products=products,
                target_language=target_language,
                source_language=source_language,
                fields=fields,
                glossary_name=glossary_name,
            )

            bulk_result.processing_time_ms = int((time.time() - start_time) * 1000)
            return bulk_result

        for product in products:
            try:
                product_translation = self.translate_product(
                    product=product,
                    target_language=target_language,
                    source_language=source_language,
                    fields=fields,
                    glossary_name=glossary_name,
                )

                # Track results
                for field_name, result in product_translation.translations.items():
                    bulk_result.results.append(result)

                    if result.status == TranslationStatus.COMPLETED:
                        bulk_result.successful += 1
                        if result.from_memory:
                            bulk_result.from_memory += 1
                    else:
                        bulk_result.failed += 1

            except Exception as e:
                bulk_result.failed += 1
                bulk_result.errors.append(f"{product}: {str(e)}")

        bulk_result.processing_time_ms = int((time.time() - start_time) * 1000)
        return bulk_result

    def _build_prompt(
        self,
        request: TranslationRequest,
        glossary_terms: List[GlossaryTerm]
    ) -> str:
        """Build the translation prompt.

        Args:
            request: Translation request
            glossary_terms: Matching glossary terms

        Returns:
            Formatted prompt string
        """
        # Get language names
        source_lang_name = SUPPORTED_LANGUAGES.get(
            request.source_language, request.source_language
        )
        target_lang_name = SUPPORTED_LANGUAGES.get(
            request.target_language, request.target_language
        )

        # Format glossary section
        glossary_section = ""
        if glossary_terms and self.glossary_manager:
            glossary_section = self.glossary_manager.get_glossary(
                request.glossary_name or ""
            )
            if glossary_section:
                glossary_section = glossary_section.format_for_prompt(glossary_terms)
            else:
                entries = []
                for term in glossary_terms:
                    entry = f'"{term.source_term}" -> "{term.target_term}"'
                    entries.append(entry)
                glossary_section = GLOSSARY_SECTION_TEMPLATE.format(
                    glossary_entries="\n".join(f"- {e}" for e in entries)
                )

        # Build additional context
        additional_context = ""
        if request.additional_context:
            additional_context = f"Additional context: {request.additional_context}"

        # Format content type name
        content_type_name = request.content_type.value.replace("_", " ")

        prompt = TRANSLATION_PROMPT_TEMPLATE.format(
            content_type=content_type_name,
            source_language=source_lang_name,
            target_language=target_lang_name,
            glossary_section=glossary_section,
            source_text=request.source_text,
            additional_context=additional_context,
        )

        return prompt

    def _call_provider(
        self,
        prompt: str,
        content_type: ContentType
    ) -> Dict[str, Any]:
        """Call the translation provider.

        Args:
            prompt: The prompt to send
            content_type: Type of content for token limits

        Returns:
            Dictionary with response and token usage
        """
        max_tokens = MAX_CHARS.get(content_type, 500)

        if self.provider in [TranslationProvider.OPENAI,
                            TranslationProvider.ANTHROPIC,
                            TranslationProvider.GOOGLE_GEMINI]:
            return self._call_ai_provider(prompt, max_tokens)
        elif self.provider == TranslationProvider.GOOGLE_TRANSLATE:
            return self._call_google_translate(prompt)
        elif self.provider == TranslationProvider.DEEPL:
            return self._call_deepl(prompt)
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")

    def _call_ai_provider(self, prompt: str, max_tokens: int) -> Dict[str, Any]:
        """Call AI provider (OpenAI, Anthropic, Gemini).

        Args:
            prompt: The prompt to send
            max_tokens: Maximum tokens for response

        Returns:
            Dictionary with response and token usage
        """
        import requests

        if self.provider == TranslationProvider.OPENAI:
            headers = {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            }

            data = {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a professional translator specializing in e-commerce product content. Provide accurate, natural translations."
                    },
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": max_tokens,
                "temperature": 0.3,  # Lower temp for more consistent translations
            }

            response = requests.post(
                API_ENDPOINTS[TranslationProvider.OPENAI],
                headers=headers,
                json=data,
                timeout=60
            )

            if response.status_code != 200:
                error_msg = response.json().get("error", {}).get("message", response.text)
                raise Exception(f"OpenAI API error: {error_msg}")

            result = response.json()
            usage = result.get("usage", {})

            return {
                "content": result["choices"][0]["message"]["content"],
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            }

        elif self.provider == TranslationProvider.ANTHROPIC:
            headers = {
                "x-api-key": self._api_key,
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
            }

            data = {
                "model": self.model,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "system": "You are a professional translator specializing in e-commerce product content. Provide accurate, natural translations.",
            }

            response = requests.post(
                API_ENDPOINTS[TranslationProvider.ANTHROPIC],
                headers=headers,
                json=data,
                timeout=60
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise Exception(f"Anthropic API error: {error_msg}")

            result = response.json()
            usage = result.get("usage", {})

            return {
                "content": result["content"][0]["text"],
                "prompt_tokens": usage.get("input_tokens", 0),
                "completion_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            }

        elif self.provider == TranslationProvider.GOOGLE_GEMINI:
            endpoint = API_ENDPOINTS[TranslationProvider.GOOGLE_GEMINI].format(
                model=self.model
            )
            url = f"{endpoint}?key={self._api_key}"

            data = {
                "contents": [
                    {
                        "parts": [
                            {
                                "text": f"System: You are a professional translator.\n\nUser: {prompt}"
                            }
                        ]
                    }
                ],
                "generationConfig": {
                    "maxOutputTokens": max_tokens,
                    "temperature": 0.3,
                }
            }

            response = requests.post(url, json=data, timeout=60)

            if response.status_code != 200:
                error_msg = response.json().get("error", {}).get("message", response.text)
                raise Exception(f"Gemini API error: {error_msg}")

            result = response.json()
            content = ""
            if result.get("candidates"):
                content = result["candidates"][0]["content"]["parts"][0]["text"]

            usage = result.get("usageMetadata", {})

            return {
                "content": content,
                "prompt_tokens": usage.get("promptTokenCount", 0),
                "completion_tokens": usage.get("candidatesTokenCount", 0),
                "total_tokens": usage.get("totalTokenCount", 0),
            }

        raise ValueError(f"Unsupported AI provider: {self.provider}")

    def _call_google_translate(self, text: str) -> Dict[str, Any]:
        """Call Google Translate API.

        Args:
            text: Text to translate (prompt contains source text)

        Returns:
            Dictionary with translated content
        """
        import requests

        # Extract source text from prompt (it's embedded in the prompt)
        # For Google Translate, we need to extract the actual text
        # This is a simplified version - in production, pass text directly

        url = f"{API_ENDPOINTS[TranslationProvider.GOOGLE_TRANSLATE]}?key={self._api_key}"

        data = {
            "q": text,
            "target": "en",  # Would need to extract from context
            "format": "text"
        }

        response = requests.post(url, json=data, timeout=30)

        if response.status_code != 200:
            raise Exception(f"Google Translate error: {response.text}")

        result = response.json()
        translated = result.get("data", {}).get("translations", [{}])[0].get("translatedText", "")

        return {
            "content": translated,
            "total_tokens": 0,
        }

    def _call_deepl(self, text: str) -> Dict[str, Any]:
        """Call DeepL API.

        Args:
            text: Text to translate

        Returns:
            Dictionary with translated content
        """
        import requests

        headers = {
            "Authorization": f"DeepL-Auth-Key {self._api_key}",
            "Content-Type": "application/json",
        }

        data = {
            "text": [text],
            "target_lang": "EN",  # Would need to extract from context
        }

        response = requests.post(
            API_ENDPOINTS[TranslationProvider.DEEPL],
            headers=headers,
            json=data,
            timeout=30
        )

        if response.status_code != 200:
            raise Exception(f"DeepL error: {response.text}")

        result = response.json()
        translated = result.get("translations", [{}])[0].get("text", "")

        return {
            "content": translated,
            "total_tokens": 0,
        }

    def _check_translation_quality(
        self,
        request: TranslationRequest,
        result: TranslationResult
    ) -> Dict[str, Any]:
        """Check translation quality.

        Args:
            request: Original request
            result: Translation result

        Returns:
            Dictionary with quality assessment
        """
        # Basic quality checks
        issues = []
        suggestions = []

        source_text = request.source_text
        translated_text = result.translated_text

        # Check for empty translation
        if not translated_text or not translated_text.strip():
            return {
                "score": 0.0,
                "issues": ["Empty translation"],
                "suggestions": ["Retry translation"]
            }

        # Check length ratio (translation shouldn't be drastically different in length)
        length_ratio = len(translated_text) / max(len(source_text), 1)
        if length_ratio < 0.3:
            issues.append("Translation seems too short")
            suggestions.append("Verify that all content was translated")
        elif length_ratio > 3.0:
            issues.append("Translation seems too long")
            suggestions.append("Check for unnecessary additions")

        # Check for untranslated content (source text appearing in translation)
        # This is a simple check - more sophisticated checks would use NLP
        source_words = set(source_text.lower().split())
        translated_words = set(translated_text.lower().split())

        # Common words that should be translated
        common_to_translate = source_words - {"the", "a", "an", "and", "or", "in", "on", "at"}
        overlap = common_to_translate & translated_words

        # If too many source words appear in translation, might not be fully translated
        overlap_ratio = len(overlap) / max(len(common_to_translate), 1)
        if overlap_ratio > 0.5 and len(overlap) > 3:
            issues.append("Some content may not be translated")
            suggestions.append(f"Check these terms: {', '.join(list(overlap)[:5])}")

        # Check for preserved formatting
        source_has_html = bool(re.search(r'<[^>]+>', source_text))
        translated_has_html = bool(re.search(r'<[^>]+>', translated_text))

        if source_has_html and not translated_has_html:
            issues.append("HTML formatting may have been lost")
            suggestions.append("Ensure HTML tags are preserved")

        # Calculate base score
        base_score = 0.85  # Start with a good base score

        # Adjust score based on issues
        score_adjustment = len(issues) * 0.1
        final_score = max(0.1, base_score - score_adjustment)

        # Adjust based on length ratio
        if 0.5 <= length_ratio <= 2.0:
            final_score = min(1.0, final_score + 0.05)

        return {
            "score": round(final_score, 3),
            "issues": issues,
            "suggestions": suggestions,
        }


# =============================================================================
# Public API Functions
# =============================================================================

def translate_text(
    text: str,
    source_language: str,
    target_language: str,
    content_type: str = "product_title",
    glossary_name: Optional[str] = None,
    async_translate: bool = False
) -> Dict[str, Any]:
    """Translate text using AI.

    This is the main API function for translating text.

    Args:
        text: Text to translate
        source_language: Source language code (e.g., "en")
        target_language: Target language code (e.g., "de")
        content_type: Type of content being translated
        glossary_name: Optional glossary name to use
        async_translate: If True, process in background

    Returns:
        Dictionary with translation result or job ID
    """
    import frappe

    if async_translate:
        job = frappe.enqueue(
            "frappe_pim.pim.services.ai_translation._translate_text_job",
            queue="default",
            timeout=120,
            text=text,
            source_language=source_language,
            target_language=target_language,
            content_type=content_type,
            glossary_name=glossary_name,
        )
        return {
            "success": True,
            "job_id": job.id if hasattr(job, "id") else str(job),
            "status": "queued"
        }

    service = AITranslationService()
    result = service.translate_text(
        text=text,
        source_language=source_language,
        target_language=target_language,
        content_type=content_type,
        glossary_name=glossary_name,
    )

    return result.to_dict()


def translate_product(
    product: str,
    target_language: str,
    source_language: str = "en",
    fields: Optional[List[str]] = None,
    glossary_name: Optional[str] = None,
    async_translate: bool = False
) -> Dict[str, Any]:
    """Translate all translatable fields of a product.

    Args:
        product: Product Master name
        target_language: Target language code
        source_language: Source language code
        fields: Specific fields to translate
        glossary_name: Optional glossary to use
        async_translate: If True, process in background

    Returns:
        Dictionary with product translation results
    """
    import frappe

    if async_translate:
        job = frappe.enqueue(
            "frappe_pim.pim.services.ai_translation._translate_product_job",
            queue="default",
            timeout=300,
            product=product,
            target_language=target_language,
            source_language=source_language,
            fields=fields,
            glossary_name=glossary_name,
        )
        return {
            "success": True,
            "job_id": job.id if hasattr(job, "id") else str(job),
            "status": "queued"
        }

    service = AITranslationService()
    result = service.translate_product(
        product=product,
        target_language=target_language,
        source_language=source_language,
        fields=fields,
        glossary_name=glossary_name,
    )

    return result.to_dict()


def bulk_translate_products(
    products: List[str],
    target_language: str,
    source_language: str = "en",
    fields: Optional[List[str]] = None,
    glossary_name: Optional[str] = None,
    async_process: bool = True
) -> Dict[str, Any]:
    """Translate multiple products.

    Args:
        products: List of Product Master names
        target_language: Target language code
        source_language: Source language code
        fields: Specific fields to translate
        glossary_name: Optional glossary to use
        async_process: If True, process in background

    Returns:
        Dictionary with bulk translation results
    """
    service = AITranslationService()
    result = service.bulk_translate(
        products=products,
        target_language=target_language,
        source_language=source_language,
        fields=fields,
        glossary_name=glossary_name,
        async_process=async_process,
    )

    return result.to_dict()


def get_translation_memory_stats() -> Dict[str, Any]:
    """Get translation memory statistics.

    Returns:
        Dictionary with memory statistics
    """
    manager = TranslationMemoryManager()
    return manager.get_stats()


def lookup_translation(
    text: str,
    source_language: str,
    target_language: str
) -> Optional[Dict[str, Any]]:
    """Look up existing translation in memory.

    Args:
        text: Text to look up
        source_language: Source language code
        target_language: Target language code

    Returns:
        Translation memory entry or None
    """
    manager = TranslationMemoryManager()
    entry = manager.lookup(text, source_language, target_language)

    if entry:
        return entry.to_dict()
    return None


def list_glossaries() -> List[Dict[str, Any]]:
    """List all available glossaries.

    Returns:
        List of glossary information
    """
    manager = GlossaryManager()
    return manager.list_glossaries()


def get_glossary(name: str) -> Optional[Dict[str, Any]]:
    """Get a specific glossary.

    Args:
        name: Glossary name

    Returns:
        Glossary data or None
    """
    manager = GlossaryManager()
    glossary = manager.get_glossary(name)

    if glossary:
        return glossary.to_dict()
    return None


def create_glossary(
    name: str,
    source_language: str,
    target_language: str,
    description: Optional[str] = None
) -> Dict[str, Any]:
    """Create a new glossary.

    Args:
        name: Glossary name
        source_language: Source language code
        target_language: Target language code
        description: Optional description

    Returns:
        Created glossary data
    """
    manager = GlossaryManager()
    glossary = manager.create_glossary(
        name=name,
        source_language=source_language,
        target_language=target_language,
        description=description,
    )

    return glossary.to_dict()


def add_glossary_term(
    glossary_name: str,
    source_term: str,
    target_term: str,
    match_type: str = "case_insensitive",
    context: Optional[str] = None,
    notes: Optional[str] = None
) -> Dict[str, Any]:
    """Add a term to a glossary.

    Args:
        glossary_name: Name of the glossary
        source_term: Source term
        target_term: Target translation
        match_type: How to match the term
        context: Optional category/domain context
        notes: Optional notes

    Returns:
        Result of adding the term
    """
    manager = GlossaryManager()
    term = manager.add_term_to_glossary(
        glossary_name=glossary_name,
        source_term=source_term,
        target_term=target_term,
        match_type=match_type,
        context=context,
        notes=notes,
    )

    if term:
        return {
            "success": True,
            "term": term.to_dict()
        }

    return {
        "success": False,
        "error": f"Glossary not found: {glossary_name}"
    }


def get_supported_languages() -> Dict[str, str]:
    """Get list of supported languages.

    Returns:
        Dictionary mapping language codes to names
    """
    return SUPPORTED_LANGUAGES.copy()


def get_translation_providers() -> List[Dict[str, str]]:
    """Get list of available translation providers.

    Returns:
        List of provider information
    """
    return [
        {"value": p.value, "label": p.value}
        for p in TranslationProvider
    ]


def approve_translation(
    translation_id: str,
    approved_text: Optional[str] = None
) -> Dict[str, Any]:
    """Approve a translation in the review queue.

    Args:
        translation_id: Translation review entry ID
        approved_text: Optional modified translation

    Returns:
        Result of approval
    """
    return _process_translation_review(translation_id, approved=True, text=approved_text)


def reject_translation(
    translation_id: str,
    reason: Optional[str] = None
) -> Dict[str, Any]:
    """Reject a translation in the review queue.

    Args:
        translation_id: Translation review entry ID
        reason: Rejection reason

    Returns:
        Result of rejection
    """
    return _process_translation_review(translation_id, approved=False, reason=reason)


def get_pending_translations(
    product: Optional[str] = None,
    target_language: Optional[str] = None,
    limit: int = 50
) -> Dict[str, Any]:
    """Get pending translations awaiting review.

    Args:
        product: Optional filter by product
        target_language: Optional filter by target language
        limit: Maximum entries to return

    Returns:
        Dictionary with pending translations
    """
    import frappe

    filters = {"status": "Needs Review"}

    if product:
        filters["product"] = product

    if target_language:
        filters["target_language"] = target_language

    try:
        if not frappe.db.exists("DocType", "Translation Review"):
            return {
                "success": True,
                "count": 0,
                "entries": []
            }

        entries = frappe.get_all(
            "Translation Review",
            filters=filters,
            fields=[
                "name", "product", "field_name", "source_text",
                "translated_text", "source_language", "target_language",
                "quality_score", "created_at"
            ],
            order_by="created_at desc",
            limit=limit
        )

        return {
            "success": True,
            "count": len(entries),
            "entries": entries
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "count": 0,
            "entries": []
        }


def test_translation_connection() -> Dict[str, Any]:
    """Test the translation provider connection.

    Returns:
        Dictionary with connection test result
    """
    try:
        service = AITranslationService()
        service._ensure_initialized()

        # Try a simple test translation
        result = service.translate_text(
            text="Hello",
            source_language="en",
            target_language="es",
            content_type="product_title",
        )

        return {
            "success": result.status != TranslationStatus.FAILED,
            "provider": service.provider.value,
            "model": service.model,
            "test_translation": result.translated_text,
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


# =============================================================================
# Helper Functions (Private)
# =============================================================================

def _get_translation_config() -> Optional[Dict[str, Any]]:
    """Get translation configuration from PIM Settings.

    Returns:
        Dictionary with translation config or None
    """
    import frappe

    try:
        if not frappe.db.exists("DocType", "PIM Settings"):
            return None

        settings = frappe.get_cached_doc("PIM Settings")

        # Check for dedicated translation settings or fall back to AI enrichment
        if hasattr(settings, "enable_translation") and not settings.enable_translation:
            return None

        if hasattr(settings, "enable_ai_enrichment") and not settings.enable_ai_enrichment:
            return None

        # Get translation-specific settings or fall back to AI settings
        provider = getattr(settings, "translation_provider", None)
        if not provider:
            provider = getattr(settings, "ai_provider", "OpenAI")

        model = getattr(settings, "translation_model", None)
        if not model:
            model = getattr(settings, "ai_model", None)

        return {
            "provider": provider,
            "model": model,
        }

    except Exception:
        return None


def _get_translation_api_key() -> Optional[str]:
    """Get the translation API key from PIM Settings.

    Returns:
        Decrypted API key or None
    """
    import frappe

    try:
        settings = frappe.get_cached_doc("PIM Settings")

        # Try translation-specific key first, then fall back to AI key
        key = None
        if hasattr(settings, "translation_api_key"):
            key = settings.get_password("translation_api_key")

        if not key and hasattr(settings, "ai_api_key"):
            key = settings.get_password("ai_api_key")

        return key

    except Exception:
        return None


def _get_product_data(product_name: str) -> Optional[Dict[str, Any]]:
    """Get product data for translation.

    Args:
        product_name: Product Master name

    Returns:
        Dictionary with product data or None
    """
    import frappe

    try:
        # Try Product Master first
        if frappe.db.exists("Product Master", product_name):
            doc = frappe.get_doc("Product Master", product_name)
            return doc.as_dict()

        # Try ERPNext Item
        if frappe.db.exists("Item", product_name):
            doc = frappe.get_doc("Item", product_name)
            return doc.as_dict()

        return None

    except Exception:
        return None


def _create_translation_review_entry(
    request: TranslationRequest,
    result: TranslationResult
) -> Optional[str]:
    """Create an entry in the Translation Review queue.

    Args:
        request: Original translation request
        result: Translation result

    Returns:
        Review entry name if created
    """
    import frappe

    try:
        if not frappe.db.exists("DocType", "Translation Review"):
            return None

        entry = frappe.get_doc({
            "doctype": "Translation Review",
            "product": request.product,
            "field_name": request.field_name,
            "source_text": request.source_text[:65535],
            "translated_text": result.translated_text[:65535],
            "source_language": request.source_language,
            "target_language": request.target_language,
            "content_type": request.content_type.value,
            "quality_score": result.quality_score,
            "quality_issues": json.dumps(result.quality_issues),
            "suggestions": json.dumps(result.suggestions),
            "request_id": result.request_id,
            "status": "Needs Review",
            "created_at": datetime.utcnow(),
        })
        entry.insert(ignore_permissions=True)
        frappe.db.commit()

        return entry.name

    except Exception as e:
        import frappe
        frappe.log_error(
            message=f"Failed to create translation review entry: {str(e)}",
            title="AI Translation - Review Queue Error"
        )
        return None


def _process_translation_review(
    review_id: str,
    approved: bool,
    text: Optional[str] = None,
    reason: Optional[str] = None
) -> Dict[str, Any]:
    """Process a translation review approval/rejection.

    Args:
        review_id: Translation Review entry name
        approved: Whether approved
        text: Optional content override
        reason: Rejection reason

    Returns:
        Dictionary with result
    """
    import frappe

    try:
        if not frappe.db.exists("Translation Review", review_id):
            return {
                "success": False,
                "error": f"Review entry not found: {review_id}"
            }

        entry = frappe.get_doc("Translation Review", review_id)

        if approved:
            entry.status = "Approved"
            entry.approved_text = text or entry.translated_text
            entry.approved_by = frappe.session.user
            entry.approved_at = datetime.utcnow()

            # Apply translation to product
            if entry.product and entry.field_name:
                _apply_translation_to_product(
                    entry.product,
                    entry.field_name,
                    entry.approved_text,
                    entry.target_language
                )

            # Store in translation memory
            manager = TranslationMemoryManager()
            tm_entry = TranslationMemoryEntry(
                source_text=entry.source_text,
                translated_text=entry.approved_text,
                source_language=entry.source_language,
                target_language=entry.target_language,
                content_type=ContentType(entry.content_type),
                quality_score=1.0,  # Human-approved = high quality
            )
            manager.store(TranslationResult(
                request_id=entry.request_id,
                source_text=tm_entry.source_text,
                translated_text=tm_entry.translated_text,
                source_language=tm_entry.source_language,
                target_language=tm_entry.target_language,
                content_type=tm_entry.content_type,
                status=TranslationStatus.APPROVED,
                quality_score=1.0,
            ))
        else:
            entry.status = "Rejected"
            entry.rejection_reason = reason
            entry.rejected_by = frappe.session.user
            entry.rejected_at = datetime.utcnow()

        entry.save(ignore_permissions=True)
        frappe.db.commit()

        return {
            "success": True,
            "status": entry.status,
            "review_id": review_id
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def _apply_translation_to_product(
    product: str,
    field_name: str,
    translated_text: str,
    target_language: str
) -> bool:
    """Apply translated content to product.

    Args:
        product: Product Master name
        field_name: Field to update
        translated_text: Translated content
        target_language: Target language code

    Returns:
        True if applied successfully
    """
    import frappe

    try:
        # For multi-language support, we might store translations differently
        # This is a simplified version that updates the field directly
        # In a real implementation, you'd use a Translation DocType or
        # language-specific fields

        translated_field = f"{field_name}_{target_language}"

        # Try Product Master
        if frappe.db.exists("Product Master", product):
            # Check if language-specific field exists
            meta = frappe.get_meta("Product Master")
            if meta.has_field(translated_field):
                frappe.db.set_value(
                    "Product Master",
                    product,
                    translated_field,
                    translated_text,
                    update_modified=True
                )
            else:
                # Fall back to storing in a translations child table or JSON field
                pass

            frappe.db.commit()
            return True

        # Try Item
        if frappe.db.exists("Item", product):
            meta = frappe.get_meta("Item")
            if meta.has_field(translated_field):
                frappe.db.set_value(
                    "Item",
                    product,
                    translated_field,
                    translated_text,
                    update_modified=True
                )
                frappe.db.commit()
                return True

        return False

    except Exception:
        return False


def _log_translation_result(request: TranslationRequest, result: TranslationResult):
    """Log translation result.

    Args:
        request: Original request
        result: Translation result
    """
    import frappe

    try:
        if frappe.db.exists("DocType", "Translation Log"):
            log = frappe.get_doc({
                "doctype": "Translation Log",
                "request_id": result.request_id,
                "product": request.product,
                "field_name": request.field_name,
                "source_language": request.source_language,
                "target_language": request.target_language,
                "content_type": request.content_type.value,
                "status": result.status.value,
                "quality_score": result.quality_score,
                "from_memory": result.from_memory,
                "provider": result.provider.value if result.provider else None,
                "model": result.model,
                "tokens_used": result.tokens_used,
                "processing_time_ms": result.processing_time_ms,
                "error_message": result.error_message,
                "created_at": datetime.utcnow(),
            })
            log.insert(ignore_permissions=True)
            frappe.db.commit()

    except Exception:
        pass  # Silently fail logging


def _log_translation_error(request: TranslationRequest, error: str):
    """Log translation error.

    Args:
        request: Original request
        error: Error message
    """
    import frappe

    frappe.log_error(
        message=f"""
AI Translation Error

Product: {request.product}
Field: {request.field_name}
Source Language: {request.source_language}
Target Language: {request.target_language}
Request ID: {request.request_id}

Error: {error}
        """,
        title=f"AI Translation Error - {request.product or 'text'}"
    )


def _bulk_translate_job(
    products: List[str],
    target_language: str,
    source_language: str = "en",
    fields: Optional[List[str]] = None,
    glossary_name: Optional[str] = None
):
    """Background job for bulk translation.

    Args:
        products: List of product names
        target_language: Target language code
        source_language: Source language code
        fields: Fields to translate
        glossary_name: Glossary to use
    """
    service = AITranslationService()
    service.bulk_translate(
        products=products,
        target_language=target_language,
        source_language=source_language,
        fields=fields,
        glossary_name=glossary_name,
        async_process=False,
    )


def _translate_text_job(
    text: str,
    source_language: str,
    target_language: str,
    content_type: str,
    glossary_name: Optional[str] = None
):
    """Background job for text translation.

    Args:
        text: Text to translate
        source_language: Source language code
        target_language: Target language code
        content_type: Content type
        glossary_name: Glossary to use
    """
    service = AITranslationService()
    service.translate_text(
        text=text,
        source_language=source_language,
        target_language=target_language,
        content_type=content_type,
        glossary_name=glossary_name,
    )


def _translate_product_job(
    product: str,
    target_language: str,
    source_language: str = "en",
    fields: Optional[List[str]] = None,
    glossary_name: Optional[str] = None
):
    """Background job for product translation.

    Args:
        product: Product name
        target_language: Target language code
        source_language: Source language code
        fields: Fields to translate
        glossary_name: Glossary to use
    """
    service = AITranslationService()
    service.translate_product(
        product=product,
        target_language=target_language,
        source_language=source_language,
        fields=fields,
        glossary_name=glossary_name,
    )


# =============================================================================
# Frappe API Wrappers
# =============================================================================

def _wrap_for_whitelist():
    """Wrap functions for Frappe whitelist at runtime."""
    import frappe

    functions = [
        "translate_text",
        "translate_product",
        "bulk_translate_products",
        "get_translation_memory_stats",
        "lookup_translation",
        "list_glossaries",
        "get_glossary",
        "create_glossary",
        "add_glossary_term",
        "get_supported_languages",
        "get_translation_providers",
        "approve_translation",
        "reject_translation",
        "get_pending_translations",
        "test_translation_connection",
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
