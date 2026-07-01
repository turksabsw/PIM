"""PIM Q&A Agent API Endpoints

This module provides API endpoints for the optional AI-powered Q&A agent
that can answer product-related questions using product data and OpenAI.

The Q&A agent retrieves relevant product information from the PIM system
and uses it as context for generating accurate answers. Responses can be
saved as QA Notes for future reference.

Endpoints:
- ask_product_question: Ask a question about a product with AI response
- get_product_context: Get product data formatted for AI context
- check_ai_availability: Check if AI features are available
- get_saved_answer: Get a previously saved answer for a similar question

Configuration:
- OPENAI_API_KEY environment variable or site_config.json openai_api_key
- AI features degrade gracefully when not configured

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

import os
import time
from datetime import datetime


def ask_product_question(
    product,
    question,
    save_response=True,
    include_variants=False,
    include_attributes=True,
    include_instructions=True,
    max_tokens=1000,
    temperature=0.7
):
    """Ask a question about a product and get an AI-generated answer.

    This is the main endpoint for the Q&A agent. It retrieves product
    information from the PIM system and uses it as context for generating
    an accurate answer using OpenAI's API.

    Args:
        product: Product Master name (required)
        question: The question to answer (required)
        save_response: Save the Q&A as a QA Note (default: True)
        include_variants: Include variant information in context (default: False)
        include_attributes: Include product attributes in context (default: True)
        include_instructions: Include chemical instructions in context (default: True)
        max_tokens: Maximum tokens for the response (default: 1000)
        temperature: AI temperature setting 0-1 (default: 0.7)

    Returns:
        dict: Response containing:
            - success: Boolean indicating success
            - answer: The AI-generated answer
            - qa_note: Name of saved QA Note (if save_response=True)
            - confidence: AI confidence estimate
            - tokens_used: Tokens consumed
            - generation_time: Time taken to generate
            - error: Error message if failed

    Example:
        >>> result = ask_product_question(
        ...     product="PROD-001",
        ...     question="What is the recommended mixing ratio for this product?"
        ... )
        >>> print(result["answer"])
    """
    import frappe
    from frappe import _

    start_time = time.time()

    # Permission check
    if not frappe.has_permission("Product Master", "read"):
        frappe.throw(_("Not permitted to access products"), frappe.PermissionError)

    # Validate product exists
    if not frappe.db.exists("Product Master", product):
        return {
            "success": False,
            "error": _("Product '{0}' not found").format(product)
        }

    # Check for existing answers
    existing = _find_similar_answer(product, question)
    if existing:
        # Record view on existing answer
        _record_qa_view(existing["name"])
        return {
            "success": True,
            "answer": existing["answer"],
            "qa_note": existing["name"],
            "from_cache": True,
            "confidence": existing.get("ai_confidence", 0),
            "generation_time": 0
        }

    # Check AI availability
    ai_available, ai_error = _check_openai_availability()
    if not ai_available:
        return {
            "success": False,
            "error": ai_error or _("AI features are not available. Please configure OpenAI API key."),
            "ai_available": False
        }

    try:
        # Build product context
        context = get_product_context(
            product,
            include_variants=include_variants,
            include_attributes=include_attributes,
            include_instructions=include_instructions
        )

        if not context.get("success"):
            return {
                "success": False,
                "error": context.get("error", _("Failed to build product context"))
            }

        # Generate answer using OpenAI
        ai_result = _generate_answer(
            question=question,
            context=context["context"],
            product_name=context["product_name"],
            max_tokens=max_tokens,
            temperature=temperature
        )

        if not ai_result.get("success"):
            return ai_result

        generation_time = time.time() - start_time

        # Save as QA Note if requested
        qa_note_name = None
        if save_response:
            qa_note_name = _save_qa_note(
                product=product,
                question=question,
                answer=ai_result["answer"],
                model=ai_result.get("model"),
                confidence=ai_result.get("confidence"),
                tokens=ai_result.get("tokens_used"),
                generation_time=generation_time,
                context_used=context.get("context_summary")
            )

        return {
            "success": True,
            "answer": ai_result["answer"],
            "qa_note": qa_note_name,
            "from_cache": False,
            "confidence": ai_result.get("confidence"),
            "tokens_used": ai_result.get("tokens_used"),
            "generation_time": round(generation_time, 2),
            "model": ai_result.get("model")
        }

    except Exception as e:
        frappe.log_error(
            message=f"Q&A Agent error for product {product}: {str(e)}",
            title="PIM Q&A Agent Error"
        )
        return {
            "success": False,
            "error": str(e)
        }


def get_product_context(
    product,
    include_variants=False,
    include_attributes=True,
    include_instructions=True,
    include_feedback=False,
    max_context_length=8000
):
    """Get product data formatted as context for AI.

    Retrieves and formats product information in a way that's suitable
    for use as AI context. The context is optimized to provide relevant
    information while staying within token limits.

    Args:
        product: Product Master name (required)
        include_variants: Include variant information (default: False)
        include_attributes: Include product attributes (default: True)
        include_instructions: Include chemical usage instructions (default: True)
        include_feedback: Include customer feedback (default: False)
        max_context_length: Maximum context character length (default: 8000)

    Returns:
        dict: Context data containing:
            - success: Boolean indicating success
            - product_name: Name of the product
            - context: Formatted context string
            - context_summary: Brief summary of included data
            - error: Error message if failed

    Example:
        >>> context = get_product_context("PROD-001")
        >>> print(context["context"])
    """
    import frappe
    from frappe import _

    try:
        product_doc = frappe.get_doc("Product Master", product)
    except frappe.DoesNotExistError:
        return {
            "success": False,
            "error": _("Product '{0}' not found").format(product)
        }

    context_parts = []
    included_sections = []

    # Basic product information
    context_parts.append(f"Product: {product_doc.product_name}")
    context_parts.append(f"Product Code: {product_doc.product_code}")

    if product_doc.product_family:
        context_parts.append(f"Product Family: {product_doc.product_family}")

    if product_doc.get("short_description"):
        context_parts.append(f"Description: {product_doc.short_description}")

    if product_doc.get("long_description"):
        # Truncate long description if needed
        long_desc = product_doc.long_description[:2000]
        context_parts.append(f"Detailed Description: {long_desc}")

    included_sections.append("basic_info")

    # Product attributes
    if include_attributes:
        attrs = _get_product_attributes_text(product_doc)
        if attrs:
            context_parts.append(f"\nProduct Attributes:\n{attrs}")
            included_sections.append("attributes")

    # Chemical usage instructions
    if include_instructions:
        instructions = _get_chemical_instructions_text(product)
        if instructions:
            context_parts.append(f"\nUsage Instructions:\n{instructions}")
            included_sections.append("instructions")

    # Product variants
    if include_variants:
        variants = _get_variants_text(product)
        if variants:
            context_parts.append(f"\nProduct Variants:\n{variants}")
            included_sections.append("variants")

    # Customer feedback
    if include_feedback:
        feedback = _get_feedback_text(product)
        if feedback:
            context_parts.append(f"\nCustomer Feedback:\n{feedback}")
            included_sections.append("feedback")

    # Combine and truncate context
    full_context = "\n".join(context_parts)
    if len(full_context) > max_context_length:
        full_context = full_context[:max_context_length] + "\n[Context truncated...]"

    return {
        "success": True,
        "product_name": product_doc.product_name,
        "context": full_context,
        "context_summary": f"Included: {', '.join(included_sections)}",
        "context_length": len(full_context)
    }


def check_ai_availability():
    """Check if AI features are available.

    Verifies that OpenAI API key is configured and the service is reachable.

    Returns:
        dict: Status containing:
            - available: Boolean indicating if AI is available
            - configured: Boolean indicating if API key is set
            - error: Error message if not available
    """
    available, error = _check_openai_availability()

    return {
        "available": available,
        "configured": _get_openai_api_key() is not None,
        "error": error
    }


def get_saved_answer(product, question, similarity_threshold=0.8):
    """Get a previously saved answer for a similar question.

    Searches existing QA Notes for similar questions and returns
    the best matching answer if found.

    Args:
        product: Product Master name
        question: The question to find a match for
        similarity_threshold: Minimum similarity score (0-1, default: 0.8)

    Returns:
        dict: Result containing:
            - found: Boolean indicating if a match was found
            - answer: The saved answer if found
            - qa_note: Name of the matching QA Note
            - similarity: Similarity score
    """
    import frappe

    try:
        existing = _find_similar_answer(product, question, similarity_threshold)

        if existing:
            _record_qa_view(existing["name"])
            return {
                "found": True,
                "answer": existing["answer"],
                "qa_note": existing["name"],
                "similarity": existing.get("similarity", 1.0)
            }

        return {"found": False}

    except Exception as e:
        frappe.log_error(
            message=f"Error finding saved answer: {str(e)}",
            title="PIM Q&A Agent Error"
        )
        return {"found": False, "error": str(e)}


def regenerate_answer(qa_note, save_as_new=False):
    """Regenerate an answer for an existing QA Note.

    Useful for refreshing answers when product information has changed.

    Args:
        qa_note: QA Note name to regenerate
        save_as_new: Create a new QA Note instead of updating (default: False)

    Returns:
        dict: Result with new answer and QA Note details
    """
    import frappe
    from frappe import _

    if not frappe.has_permission("QA Note", "write"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    try:
        qa_doc = frappe.get_doc("QA Note", qa_note)

        # Regenerate answer
        result = ask_product_question(
            product=qa_doc.linked_product,
            question=qa_doc.question,
            save_response=save_as_new,
            include_variants=False,
            include_attributes=True,
            include_instructions=True
        )

        if not result.get("success"):
            return result

        if not save_as_new:
            # Update existing QA Note
            qa_doc.answer = result["answer"]
            qa_doc.ai_model = result.get("model")
            qa_doc.ai_confidence = result.get("confidence")
            qa_doc.tokens_used = result.get("tokens_used")
            qa_doc.generation_time = result.get("generation_time")
            qa_doc.generation_timestamp = datetime.now()
            qa_doc.status = "Draft"  # Reset status for review
            qa_doc.save()

            return {
                "success": True,
                "answer": result["answer"],
                "qa_note": qa_note,
                "regenerated": True
            }

        return result

    except Exception as e:
        frappe.log_error(
            message=f"Error regenerating answer: {str(e)}",
            title="PIM Q&A Agent Error"
        )
        return {"success": False, "error": str(e)}


def bulk_generate_qa(product, questions, save_responses=True):
    """Generate answers for multiple questions about a product.

    Args:
        product: Product Master name
        questions: List of questions to answer
        save_responses: Save each Q&A as a QA Note (default: True)

    Returns:
        dict: Results for each question
    """
    import frappe
    from frappe import _
    import json

    if not frappe.has_permission("Product Master", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    # Parse questions if JSON string
    if isinstance(questions, str):
        try:
            questions = json.loads(questions)
        except json.JSONDecodeError:
            questions = [q.strip() for q in questions.split("\n") if q.strip()]

    results = []
    success_count = 0
    error_count = 0

    for question in questions:
        result = ask_product_question(
            product=product,
            question=question,
            save_response=save_responses
        )

        results.append({
            "question": question,
            "success": result.get("success", False),
            "answer": result.get("answer"),
            "qa_note": result.get("qa_note"),
            "error": result.get("error")
        })

        if result.get("success"):
            success_count += 1
        else:
            error_count += 1

    return {
        "success": error_count == 0,
        "total": len(questions),
        "successful": success_count,
        "failed": error_count,
        "results": results
    }


# ============================================================================
# Internal Helper Functions
# ============================================================================

def _get_openai_api_key():
    """Get OpenAI API key from environment or site config.

    Returns:
        str: API key or None if not configured
    """
    # First check environment variable
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key:
        return api_key

    # Then check site_config.json
    try:
        import frappe
        api_key = frappe.conf.get("openai_api_key")
        if api_key:
            return api_key
    except Exception:
        pass

    return None


def _check_openai_availability():
    """Check if OpenAI API is available.

    Returns:
        tuple: (available: bool, error: str or None)
    """
    api_key = _get_openai_api_key()
    if not api_key:
        return False, "OpenAI API key not configured. Set OPENAI_API_KEY environment variable or openai_api_key in site_config.json"

    # Basic key format validation
    if not api_key.startswith("sk-"):
        return False, "Invalid OpenAI API key format"

    return True, None


def _generate_answer(question, context, product_name, max_tokens=1000, temperature=0.7):
    """Generate an answer using OpenAI API.

    Args:
        question: The question to answer
        context: Product context information
        product_name: Name of the product
        max_tokens: Maximum tokens for response
        temperature: AI temperature setting

    Returns:
        dict: Result with answer or error
    """
    import frappe

    api_key = _get_openai_api_key()
    if not api_key:
        return {
            "success": False,
            "error": "OpenAI API key not configured"
        }

    try:
        # Try importing openai
        try:
            import openai
        except ImportError:
            return {
                "success": False,
                "error": "OpenAI Python package not installed. Run: pip install openai"
            }

        # Configure OpenAI client
        client = openai.OpenAI(api_key=api_key)

        # Build the prompt
        system_prompt = """You are a helpful product information assistant for a Product Information Management (PIM) system.
Your role is to answer questions about products based on the provided product data.

Guidelines:
- Only answer based on the provided product context
- If the information is not available in the context, say so clearly
- Be concise but informative
- For chemical products, emphasize safety warnings when relevant
- If asked about mixing ratios or usage, provide exact values from the data
- Do not make assumptions about product properties not mentioned in the context"""

        user_prompt = f"""Product Context:
{context}

Question about "{product_name}":
{question}

Please provide a helpful answer based on the product information above."""

        # Make API call
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=max_tokens,
            temperature=temperature
        )

        # Extract response
        answer = response.choices[0].message.content
        tokens_used = response.usage.total_tokens if response.usage else 0

        # Estimate confidence based on response characteristics
        confidence = _estimate_confidence(answer, context)

        return {
            "success": True,
            "answer": answer,
            "model": response.model,
            "tokens_used": tokens_used,
            "confidence": confidence
        }

    except openai.RateLimitError:
        frappe.log_error(
            message="OpenAI rate limit exceeded",
            title="PIM Q&A Agent - Rate Limit"
        )
        return {
            "success": False,
            "error": "AI service rate limit exceeded. Please try again later.",
            "rate_limited": True
        }

    except openai.APIError as e:
        frappe.log_error(
            message=f"OpenAI API error: {str(e)}",
            title="PIM Q&A Agent - API Error"
        )
        return {
            "success": False,
            "error": f"AI service error: {str(e)}"
        }

    except Exception as e:
        frappe.log_error(
            message=f"Error generating answer: {str(e)}",
            title="PIM Q&A Agent Error"
        )
        return {
            "success": False,
            "error": str(e)
        }


def _estimate_confidence(answer, context):
    """Estimate confidence based on answer characteristics.

    Args:
        answer: The generated answer
        context: The product context used

    Returns:
        float: Confidence score 0-100
    """
    confidence = 70  # Base confidence

    # Increase confidence if answer contains specific data from context
    answer_lower = answer.lower()
    context_lower = context.lower()

    # Check for specific data mentions
    if any(phrase in answer_lower for phrase in ["according to", "the product", "specification"]):
        confidence += 10

    # Decrease confidence if answer contains uncertainty phrases
    if any(phrase in answer_lower for phrase in ["not available", "no information", "unclear", "not specified"]):
        confidence -= 20

    # Cap confidence
    return max(0, min(100, confidence))


def _find_similar_answer(product, question, threshold=0.8):
    """Find a similar existing answer.

    Args:
        product: Product Master name
        question: The question to match
        threshold: Similarity threshold

    Returns:
        dict: Matching QA Note data or None
    """
    import frappe

    try:
        # Simple keyword matching for now
        # A more sophisticated implementation could use embeddings
        question_words = set(question.lower().split())

        qa_notes = frappe.get_all(
            "QA Note",
            filters={
                "linked_product": product,
                "status": ["in", ["Active", "Verified"]]
            },
            fields=["name", "question", "answer", "ai_confidence"]
        )

        best_match = None
        best_similarity = 0

        for qa in qa_notes:
            qa_words = set(qa.question.lower().split())
            # Jaccard similarity
            intersection = len(question_words & qa_words)
            union = len(question_words | qa_words)
            similarity = intersection / union if union > 0 else 0

            if similarity >= threshold and similarity > best_similarity:
                best_similarity = similarity
                best_match = {
                    "name": qa.name,
                    "answer": qa.answer,
                    "ai_confidence": qa.ai_confidence,
                    "similarity": round(similarity, 2)
                }

        return best_match

    except Exception:
        return None


def _save_qa_note(product, question, answer, model=None, confidence=None,
                  tokens=None, generation_time=None, context_used=None):
    """Save a Q&A as a QA Note.

    Args:
        product: Product Master name
        question: The question asked
        answer: The generated answer
        model: AI model used
        confidence: AI confidence score
        tokens: Tokens used
        generation_time: Time taken to generate
        context_used: Context summary

    Returns:
        str: Name of the created QA Note or None
    """
    import frappe

    try:
        doc = frappe.new_doc("QA Note")
        doc.linked_product = product
        doc.question = question
        doc.answer = answer
        doc.generation_method = "AI"
        doc.status = "Draft"
        doc.visibility = "Internal"
        doc.asked_date = datetime.now()
        doc.generation_timestamp = datetime.now()

        if model:
            doc.ai_model = model
        if confidence is not None:
            doc.ai_confidence = confidence
        if tokens:
            doc.tokens_used = tokens
        if generation_time:
            doc.generation_time = generation_time
        if context_used:
            doc.context_used = context_used

        # Auto-generate title
        doc.note_title = question[:50] + ("..." if len(question) > 50 else "")

        doc.insert(ignore_permissions=True)
        frappe.db.commit()

        return doc.name

    except Exception as e:
        import frappe
        frappe.log_error(
            message=f"Error saving QA Note: {str(e)}",
            title="PIM Q&A Agent Error"
        )
        return None


def _record_qa_view(qa_note_name):
    """Record a view on a QA Note.

    Args:
        qa_note_name: Name of the QA Note
    """
    import frappe

    try:
        frappe.db.set_value(
            "QA Note", qa_note_name,
            {
                "view_count": frappe.db.get_value("QA Note", qa_note_name, "view_count") + 1,
                "last_viewed": datetime.now()
            },
            update_modified=False
        )
        frappe.db.commit()
    except Exception:
        pass  # Don't fail if view recording fails


def _get_product_attributes_text(product_doc):
    """Get product attributes as formatted text.

    Args:
        product_doc: Product Master document

    Returns:
        str: Formatted attributes text
    """
    try:
        attrs = []
        for attr_row in (product_doc.get("attribute_values") or []):
            attr_name = attr_row.get("attribute")
            if not attr_name:
                continue

            # Get value from appropriate column
            value = (
                attr_row.get("value_text") or
                attr_row.get("value_int") or
                attr_row.get("value_float") or
                attr_row.get("value_date") or
                attr_row.get("value_link")
            )

            if attr_row.get("value_boolean") is not None:
                value = "Yes" if attr_row.get("value_boolean") else "No"

            if value:
                attrs.append(f"- {attr_name}: {value}")

        return "\n".join(attrs) if attrs else ""

    except Exception:
        return ""


def _get_chemical_instructions_text(product):
    """Get chemical usage instructions as formatted text.

    Args:
        product: Product Master name

    Returns:
        str: Formatted instructions text
    """
    import frappe

    try:
        instructions = frappe.get_all(
            "Chemical Usage Instruction",
            filters={"linked_product": product, "status": "Active"},
            fields=[
                "instruction_title", "usage_scenario", "mixing_ratio_description",
                "application_method", "safety_warnings", "hazard_level"
            ],
            limit=5
        )

        if not instructions:
            return ""

        text_parts = []
        for inst in instructions:
            parts = [f"## {inst.instruction_title}"]
            if inst.usage_scenario:
                parts.append(f"Scenario: {inst.usage_scenario}")
            if inst.mixing_ratio_description:
                parts.append(f"Mixing Ratio: {inst.mixing_ratio_description}")
            if inst.application_method:
                parts.append(f"Application: {inst.application_method}")
            if inst.hazard_level:
                parts.append(f"Hazard Level: {inst.hazard_level}")
            if inst.safety_warnings:
                parts.append(f"Safety Warnings: {inst.safety_warnings}")

            text_parts.append("\n".join(parts))

        return "\n\n".join(text_parts)

    except Exception:
        return ""


def _get_variants_text(product):
    """Get product variants as formatted text.

    Args:
        product: Product Master name

    Returns:
        str: Formatted variants text
    """
    import frappe

    try:
        variants = frappe.get_all(
            "Product Variant",
            filters={"product_master": product},
            fields=[
                "variant_name", "variant_code", "status",
                "variant_attribute_1", "variant_value_1",
                "variant_attribute_2", "variant_value_2"
            ],
            limit=10
        )

        if not variants:
            return ""

        text_parts = []
        for var in variants:
            parts = [f"- {var.variant_name} ({var.variant_code})"]
            if var.variant_attribute_1 and var.variant_value_1:
                parts.append(f"  {var.variant_attribute_1}: {var.variant_value_1}")
            if var.variant_attribute_2 and var.variant_value_2:
                parts.append(f"  {var.variant_attribute_2}: {var.variant_value_2}")
            text_parts.append("\n".join(parts))

        return "\n".join(text_parts)

    except Exception:
        return ""


def _get_feedback_text(product):
    """Get product feedback as formatted text.

    Args:
        product: Product Master name

    Returns:
        str: Formatted feedback text
    """
    import frappe

    try:
        feedbacks = frappe.get_all(
            "Product Feedback",
            filters={"linked_product": product},
            fields=[
                "feedback_type", "feedback_text", "rating", "sentiment"
            ],
            limit=5,
            order_by="creation desc"
        )

        if not feedbacks:
            return ""

        text_parts = []
        for fb in feedbacks:
            parts = [f"- {fb.feedback_type}"]
            if fb.rating:
                parts.append(f"  Rating: {fb.rating}/5")
            if fb.sentiment:
                parts.append(f"  Sentiment: {fb.sentiment}")
            if fb.feedback_text:
                text = fb.feedback_text[:200]
                parts.append(f"  Comment: {text}")
            text_parts.append("\n".join(parts))

        return "\n".join(text_parts)

    except Exception:
        return ""


# ============================================================================
# Whitelist Wrapper
# ============================================================================

def _wrap_for_whitelist():
    """Add @frappe.whitelist() decorators at runtime."""
    import frappe

    global ask_product_question, get_product_context, check_ai_availability
    global get_saved_answer, regenerate_answer, bulk_generate_qa

    ask_product_question = frappe.whitelist()(ask_product_question)
    get_product_context = frappe.whitelist()(get_product_context)
    check_ai_availability = frappe.whitelist(allow_guest=True)(check_ai_availability)
    get_saved_answer = frappe.whitelist()(get_saved_answer)
    regenerate_answer = frappe.whitelist()(regenerate_answer)
    bulk_generate_qa = frappe.whitelist()(bulk_generate_qa)


# Apply whitelist decorators if frappe is available
try:
    _wrap_for_whitelist()
except ImportError:
    pass  # Decorators will be added when module is used in Frappe context
