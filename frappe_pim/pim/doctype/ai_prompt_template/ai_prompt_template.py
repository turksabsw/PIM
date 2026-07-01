"""
AI Prompt Template Controller
Manages prompt templates with Jinja2 templating for AI enrichment jobs
"""

import frappe
from frappe import _
from frappe.model.document import Document
from typing import Optional, List, Dict, Any
from frappe.utils import now_datetime, cint, flt
import json
import re


class AIPromptTemplate(Document):
    def validate(self):
        self.validate_template_code()
        self.validate_prompts()
        self.validate_output_config()
        self.validate_examples()
        self.validate_default_settings()
        self.set_defaults()

    def validate_template_code(self):
        """Validate template code format"""
        if self.template_code:
            # Allow alphanumeric, hyphens, and underscores
            if not re.match(r'^[a-zA-Z0-9_-]+$', self.template_code):
                frappe.throw(
                    _("Template Code can only contain letters, numbers, hyphens, and underscores"),
                    title=_("Invalid Template Code")
                )

    def validate_prompts(self):
        """Validate prompt templates are valid Jinja2"""
        # Validate system prompt if provided
        if self.system_prompt:
            self._validate_jinja_template(self.system_prompt, "System Prompt")

        # Validate user prompt template (required)
        if self.user_prompt_template:
            self._validate_jinja_template(self.user_prompt_template, "User Prompt Template")

    def _validate_jinja_template(self, template: str, field_name: str):
        """Validate a Jinja2 template string"""
        try:
            from jinja2 import Template, TemplateSyntaxError, UndefinedError
            # Try to compile the template
            Template(template)
        except TemplateSyntaxError as e:
            frappe.throw(
                _("{0} has invalid Jinja2 syntax: {1}").format(field_name, str(e)),
                title=_("Template Syntax Error")
            )
        except Exception as e:
            frappe.throw(
                _("{0} validation failed: {1}").format(field_name, str(e)),
                title=_("Template Validation Error")
            )

    def validate_output_config(self):
        """Validate output configuration"""
        # Validate output schema if JSON output is required
        if self.output_format == "JSON" and self.output_schema:
            try:
                schema = json.loads(self.output_schema)
                if not isinstance(schema, dict):
                    frappe.throw(
                        _("Output Schema must be a JSON object"),
                        title=_("Invalid Schema")
                    )
            except json.JSONDecodeError as e:
                frappe.throw(
                    _("Output Schema is not valid JSON: {0}").format(str(e)),
                    title=_("Invalid JSON")
                )

        # Validate post-processing script if custom
        if self.post_processing == "Custom" and self.post_processing_script:
            self._validate_python_script(self.post_processing_script)

        # Validate output length constraints
        if self.min_output_length and self.max_output_length:
            if self.min_output_length > self.max_output_length:
                frappe.throw(
                    _("Min output length cannot be greater than max output length"),
                    title=_("Invalid Length Constraints")
                )

    def _validate_python_script(self, script: str):
        """Validate Python script syntax"""
        try:
            compile(script, '<string>', 'exec')
        except SyntaxError as e:
            frappe.throw(
                _("Post Processing Script has syntax error: {0}").format(str(e)),
                title=_("Script Syntax Error")
            )

    def validate_examples(self):
        """Validate few-shot examples"""
        if self.examples:
            try:
                examples = json.loads(self.examples)
                if not isinstance(examples, list):
                    frappe.throw(
                        _("Examples must be a JSON array"),
                        title=_("Invalid Examples")
                    )

                for i, example in enumerate(examples):
                    if not isinstance(example, dict):
                        frappe.throw(
                            _("Example {0} must be a JSON object").format(i + 1),
                            title=_("Invalid Example")
                        )
                    if "input" not in example or "output" not in example:
                        frappe.throw(
                            _("Example {0} must have 'input' and 'output' fields").format(i + 1),
                            title=_("Invalid Example")
                        )
            except json.JSONDecodeError as e:
                frappe.throw(
                    _("Examples is not valid JSON: {0}").format(str(e)),
                    title=_("Invalid JSON")
                )

        # Validate validation rules
        if self.enable_output_validation and self.validation_rules:
            try:
                rules = json.loads(self.validation_rules)
                if not isinstance(rules, list):
                    frappe.throw(
                        _("Validation Rules must be a JSON array"),
                        title=_("Invalid Validation Rules")
                    )
            except json.JSONDecodeError as e:
                frappe.throw(
                    _("Validation Rules is not valid JSON: {0}").format(str(e)),
                    title=_("Invalid JSON")
                )

    def validate_default_settings(self):
        """Validate AI default settings"""
        # Validate temperature
        if self.default_temperature is not None:
            if self.default_temperature < 0 or self.default_temperature > 1:
                frappe.throw(
                    _("Default Temperature must be between 0.0 and 1.0"),
                    title=_("Invalid Temperature")
                )

        # Validate max_tokens
        if self.default_max_tokens is not None and self.default_max_tokens < 1:
            frappe.throw(
                _("Default Max Tokens must be at least 1"),
                title=_("Invalid Max Tokens")
            )

        # Ensure only one default per job type
        if self.is_default and self.is_active:
            existing_default = frappe.db.exists(
                "AI Prompt Template",
                {
                    "job_type": self.job_type,
                    "is_default": 1,
                    "is_active": 1,
                    "name": ["!=", self.name]
                }
            )
            if existing_default:
                frappe.throw(
                    _("There is already a default template for job type '{0}'. "
                      "Please deactivate it first or uncheck 'Is Default'.").format(self.job_type),
                    title=_("Default Already Exists")
                )

    def set_defaults(self):
        """Set default values"""
        if not self.created_by:
            self.created_by = frappe.session.user

        # Auto-generate template code if not provided
        if not self.template_code and self.template_name:
            # Convert name to code format
            code = self.template_name.lower()
            code = re.sub(r'[^a-z0-9]+', '-', code)
            code = code.strip('-')
            self.template_code = code[:50]  # Limit length

        # Set default variable definitions if not provided
        if not self.variable_definitions:
            self.variable_definitions = json.dumps(self._get_default_variable_definitions())

    def _get_default_variable_definitions(self) -> Dict[str, Any]:
        """Get default variable definitions based on job type"""
        base_vars = {
            "product": {
                "type": "object",
                "description": "Product Master document",
                "properties": {
                    "name": "Document name",
                    "sku": "Product SKU",
                    "product_name": "Product name",
                    "short_description": "Short description",
                    "long_description": "Long description",
                    "product_type": "Product type (Simple/Configurable/Bundle/Virtual)",
                    "product_family": "Product family",
                    "brand": "Brand name",
                    "manufacturer": "Manufacturer name"
                }
            },
            "attributes": {
                "type": "object",
                "description": "Product attributes as key-value pairs"
            },
            "channel": {
                "type": "object",
                "description": "Target channel (if specified)",
                "properties": {
                    "name": "Channel name",
                    "channel_code": "Channel code"
                }
            },
            "locale": {
                "type": "object",
                "description": "Target locale (if specified)",
                "properties": {
                    "locale_code": "Locale code (e.g., en_US)",
                    "locale_name": "Locale name"
                }
            },
            "category": {
                "type": "string",
                "description": "Product category name"
            },
            "family": {
                "type": "object",
                "description": "Product family document"
            },
            "existing_values": {
                "type": "object",
                "description": "Existing attribute values for the product"
            }
        }

        # Add job-type specific variables
        if self.job_type == "Translation":
            base_vars["source_locale"] = {
                "type": "object",
                "description": "Source locale for translation"
            }
            base_vars["source_content"] = {
                "type": "string",
                "description": "Content to translate"
            }

        elif self.job_type == "Classification Suggestion":
            base_vars["taxonomy"] = {
                "type": "object",
                "description": "Target taxonomy for classification"
            }
            base_vars["available_nodes"] = {
                "type": "array",
                "description": "List of available taxonomy nodes"
            }

        elif self.job_type == "Image Analysis":
            base_vars["images"] = {
                "type": "array",
                "description": "List of product image URLs"
            }

        return base_vars

    def render_prompt(
        self,
        product: Optional[Dict] = None,
        attributes: Optional[Dict] = None,
        channel: Optional[Dict] = None,
        locale: Optional[Dict] = None,
        extra_context: Optional[Dict] = None
    ) -> Dict[str, str]:
        """
        Render the prompt templates with the provided context

        Args:
            product: Product data dictionary
            attributes: Product attributes dictionary
            channel: Channel data dictionary
            locale: Locale data dictionary
            extra_context: Additional context variables

        Returns:
            Dict with 'system_prompt' and 'user_prompt' keys
        """
        from jinja2 import Template, Environment, StrictUndefined

        # Build context
        context = {
            "product": product or {},
            "attributes": attributes or {},
            "channel": channel or {},
            "locale": locale or {},
            "existing_values": attributes or {},
            "category": product.get("product_category") if product else None,
            "family": product.get("product_family") if product else None,
        }

        # Add custom variables
        if self.custom_variables:
            try:
                custom = json.loads(self.custom_variables)
                context.update(custom)
            except (json.JSONDecodeError, TypeError):
                pass

        # Add extra context
        if extra_context:
            context.update(extra_context)

        # Create Jinja environment
        env = Environment(undefined=StrictUndefined)

        result = {
            "system_prompt": "",
            "user_prompt": ""
        }

        # Render system prompt
        if self.system_prompt:
            try:
                template = env.from_string(self.system_prompt)
                result["system_prompt"] = template.render(**context)
            except Exception as e:
                frappe.log_error(f"Error rendering system prompt: {str(e)}")
                result["system_prompt"] = self.system_prompt  # Use raw if rendering fails

        # Render user prompt
        try:
            template = env.from_string(self.user_prompt_template)
            result["user_prompt"] = template.render(**context)
        except Exception as e:
            frappe.throw(
                _("Error rendering user prompt: {0}").format(str(e)),
                title=_("Template Rendering Error")
            )

        # Add examples if configured
        if self.include_examples and self.examples:
            examples_text = self._format_examples()
            if examples_text:
                result["user_prompt"] = examples_text + "\n\n" + result["user_prompt"]

        return result

    def _format_examples(self) -> str:
        """Format few-shot examples for the prompt"""
        try:
            examples = json.loads(self.examples)
            if not examples:
                return ""

            # Limit to max_examples
            max_ex = self.max_examples or 3
            examples = examples[:max_ex]

            formatted = ["Here are some examples:"]
            for i, ex in enumerate(examples, 1):
                formatted.append(f"\nExample {i}:")
                formatted.append(f"Input: {ex.get('input', '')}")
                formatted.append(f"Output: {ex.get('output', '')}")

            return "\n".join(formatted)
        except (json.JSONDecodeError, TypeError):
            return ""

    def validate_output(self, output: str) -> Dict[str, Any]:
        """
        Validate AI output against configured rules

        Args:
            output: The AI-generated output

        Returns:
            Dict with 'valid' boolean and 'errors' list
        """
        errors = []

        # Check minimum length
        if self.min_output_length and len(output) < self.min_output_length:
            errors.append(
                _("Output is too short. Minimum length: {0}, Actual: {1}").format(
                    self.min_output_length, len(output)
                )
            )

        # Check maximum length
        if self.max_output_length and len(output) > self.max_output_length:
            errors.append(
                _("Output is too long. Maximum length: {0}, Actual: {1}").format(
                    self.max_output_length, len(output)
                )
            )

        # Check forbidden patterns
        if self.forbidden_patterns:
            patterns = self.forbidden_patterns.strip().split('\n')
            for pattern in patterns:
                pattern = pattern.strip()
                if pattern:
                    try:
                        if re.search(pattern, output, re.IGNORECASE):
                            errors.append(
                                _("Output contains forbidden pattern: {0}").format(pattern)
                            )
                    except re.error:
                        pass  # Skip invalid regex patterns

        # Validate JSON output
        if self.output_format == "JSON":
            try:
                parsed = json.loads(output)
                # Validate against schema if provided
                if self.output_schema:
                    schema_errors = self._validate_against_schema(parsed)
                    errors.extend(schema_errors)
            except json.JSONDecodeError as e:
                errors.append(_("Output is not valid JSON: {0}").format(str(e)))

        # Apply custom validation rules
        if self.enable_output_validation and self.validation_rules:
            try:
                rules = json.loads(self.validation_rules)
                for rule in rules:
                    rule_errors = self._apply_validation_rule(output, rule)
                    errors.extend(rule_errors)
            except (json.JSONDecodeError, TypeError):
                pass

        return {
            "valid": len(errors) == 0,
            "errors": errors
        }

    def _validate_against_schema(self, data: Any) -> List[str]:
        """Validate data against JSON schema"""
        errors = []
        try:
            schema = json.loads(self.output_schema)
            # Basic schema validation (field presence and types)
            if "required" in schema:
                for field in schema["required"]:
                    if field not in data:
                        errors.append(_("Missing required field: {0}").format(field))
        except Exception:
            pass
        return errors

    def _apply_validation_rule(self, output: str, rule: Dict) -> List[str]:
        """Apply a single validation rule"""
        errors = []
        rule_type = rule.get("rule", "")
        message = rule.get("message", "Validation failed")

        if rule_type == "contains":
            if rule.get("value") not in output:
                errors.append(message)
        elif rule_type == "not_contains":
            if rule.get("value") in output:
                errors.append(message)
        elif rule_type == "regex_match":
            pattern = rule.get("pattern", "")
            if pattern and not re.search(pattern, output):
                errors.append(message)
        elif rule_type == "min_words":
            word_count = len(output.split())
            if word_count < rule.get("value", 0):
                errors.append(message)

        return errors

    def post_process_output(self, output: str) -> str:
        """
        Apply post-processing to AI output

        Args:
            output: Raw AI output

        Returns:
            Processed output string
        """
        if self.post_processing == "None" or not self.post_processing:
            return output

        if self.post_processing == "Trim Whitespace":
            return output.strip()

        if self.post_processing == "Extract JSON":
            return self._extract_json(output)

        if self.post_processing == "Parse Key-Value":
            return self._parse_key_value(output)

        if self.post_processing == "Custom" and self.post_processing_script:
            return self._run_custom_post_processing(output)

        return output

    def _extract_json(self, output: str) -> str:
        """Extract JSON from output that may contain surrounding text"""
        # Try to find JSON object or array
        patterns = [
            r'\{[^{}]*\}',  # Simple object
            r'\{.*\}',      # Complex object (greedy)
            r'\[.*\]'       # Array
        ]

        for pattern in patterns:
            match = re.search(pattern, output, re.DOTALL)
            if match:
                try:
                    json.loads(match.group())
                    return match.group()
                except json.JSONDecodeError:
                    continue

        return output

    def _parse_key_value(self, output: str) -> str:
        """Parse key-value pairs from output"""
        result = {}
        lines = output.strip().split('\n')

        for line in lines:
            if ':' in line:
                key, value = line.split(':', 1)
                result[key.strip()] = value.strip()

        return json.dumps(result)

    def _run_custom_post_processing(self, output: str) -> str:
        """Run custom post-processing script"""
        try:
            local_vars = {"response": output}
            exec(self.post_processing_script, {}, local_vars)
            return local_vars.get("result", output)
        except Exception as e:
            frappe.log_error(f"Custom post-processing error: {str(e)}")
            return output

    def update_usage_stats(
        self,
        successful: bool = True,
        confidence: float = 0.0,
        tokens_used: int = 0
    ):
        """
        Update usage statistics for this template

        Args:
            successful: Whether the use was successful
            confidence: Confidence score of the result
            tokens_used: Number of tokens consumed
        """
        total = self.total_uses + 1
        successful_count = self.successful_uses + (1 if successful else 0)

        # Calculate running average for confidence
        avg_confidence = (
            (self.average_confidence * self.total_uses + confidence) / total
            if total > 0 else 0
        )

        # Calculate running average for tokens
        avg_tokens = (
            (self.average_tokens * self.total_uses + tokens_used) / total
            if total > 0 else 0
        )

        self.db_set({
            "total_uses": total,
            "successful_uses": successful_count,
            "average_confidence": flt(avg_confidence, 2),
            "average_tokens": cint(avg_tokens),
            "last_used_at": now_datetime()
        })


# API Functions

@frappe.whitelist()
def get_prompt_templates(
    job_type: Optional[str] = None,
    is_active: bool = True,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """
    Get list of prompt templates

    Args:
        job_type: Filter by job type
        is_active: Filter by active status
        limit: Maximum results to return

    Returns:
        List of template summaries
    """
    filters = {}

    if job_type:
        filters["job_type"] = job_type
    if is_active:
        filters["is_active"] = 1

    return frappe.get_all(
        "AI Prompt Template",
        filters=filters,
        fields=[
            "name", "template_name", "template_code", "job_type",
            "is_active", "is_default", "version", "description",
            "default_ai_provider", "total_uses", "successful_uses",
            "average_confidence", "last_used_at"
        ],
        order_by="is_default desc, total_uses desc",
        limit_page_length=limit
    )


@frappe.whitelist()
def get_default_template(job_type: str) -> Optional[Dict[str, Any]]:
    """
    Get the default template for a job type

    Args:
        job_type: The AI job type

    Returns:
        Template document or None
    """
    template_name = frappe.db.get_value(
        "AI Prompt Template",
        {
            "job_type": job_type,
            "is_default": 1,
            "is_active": 1
        },
        "name"
    )

    if template_name:
        return frappe.get_doc("AI Prompt Template", template_name).as_dict()

    return None


@frappe.whitelist()
def render_template(
    template: str,
    product: Optional[str] = None,
    channel: Optional[str] = None,
    locale: Optional[str] = None,
    extra_context: Optional[str] = None
) -> Dict[str, str]:
    """
    Render a prompt template with product data

    Args:
        template: Template name
        product: Product name (optional)
        channel: Channel name (optional)
        locale: Locale code (optional)
        extra_context: Additional context as JSON string

    Returns:
        Dict with rendered prompts
    """
    doc = frappe.get_doc("AI Prompt Template", template)

    # Load product data if provided
    product_data = None
    attributes_data = None
    if product:
        product_doc = frappe.get_doc("Product Master", product)
        product_data = product_doc.as_dict()

        # Load attributes
        attributes_data = {}
        try:
            from frappe_pim.pim.utils.attribute_resolver import get_all_scoped_attributes
            attributes_data = get_all_scoped_attributes(
                product=product,
                locale=locale,
                channel=channel
            )
        except ImportError:
            pass

    # Load channel data if provided
    channel_data = None
    if channel:
        channel_data = frappe.get_doc("Channel", channel).as_dict()

    # Load locale data if provided
    locale_data = None
    if locale:
        locale_data = frappe.get_doc("PIM Locale", locale).as_dict()

    # Parse extra context
    extra = None
    if extra_context:
        try:
            extra = json.loads(extra_context)
        except (json.JSONDecodeError, TypeError):
            pass

    return doc.render_prompt(
        product=product_data,
        attributes=attributes_data,
        channel=channel_data,
        locale=locale_data,
        extra_context=extra
    )


@frappe.whitelist()
def validate_template_output(template: str, output: str) -> Dict[str, Any]:
    """
    Validate AI output against template rules

    Args:
        template: Template name
        output: AI output to validate

    Returns:
        Validation result with 'valid' and 'errors'
    """
    doc = frappe.get_doc("AI Prompt Template", template)
    return doc.validate_output(output)


@frappe.whitelist()
def preview_template(
    template_name: str,
    system_prompt: Optional[str] = None,
    user_prompt_template: Optional[str] = None,
    sample_product: Optional[str] = None
) -> Dict[str, Any]:
    """
    Preview a template with sample data before saving

    Args:
        template_name: Name for reference
        system_prompt: System prompt template
        user_prompt_template: User prompt template
        sample_product: Product to use as sample data

    Returns:
        Dict with rendered preview and validation status
    """
    from jinja2 import Template, Environment, TemplateSyntaxError

    result = {
        "valid": True,
        "errors": [],
        "system_prompt": "",
        "user_prompt": ""
    }

    # Validate templates
    env = Environment()

    if system_prompt:
        try:
            env.from_string(system_prompt)
        except TemplateSyntaxError as e:
            result["valid"] = False
            result["errors"].append(f"System Prompt: {str(e)}")

    if user_prompt_template:
        try:
            env.from_string(user_prompt_template)
        except TemplateSyntaxError as e:
            result["valid"] = False
            result["errors"].append(f"User Prompt: {str(e)}")

    # If valid and sample product provided, render preview
    if result["valid"] and sample_product:
        try:
            product_doc = frappe.get_doc("Product Master", sample_product)
            context = {
                "product": product_doc.as_dict(),
                "attributes": {},
                "channel": {},
                "locale": {},
                "existing_values": {},
                "category": product_doc.product_category,
                "family": product_doc.product_family
            }

            if system_prompt:
                template = env.from_string(system_prompt)
                result["system_prompt"] = template.render(**context)

            if user_prompt_template:
                template = env.from_string(user_prompt_template)
                result["user_prompt"] = template.render(**context)

        except Exception as e:
            result["errors"].append(f"Render Error: {str(e)}")

    return result


@frappe.whitelist()
def duplicate_template(template: str, new_name: str) -> str:
    """
    Duplicate an existing template

    Args:
        template: Source template name
        new_name: Name for the new template

    Returns:
        Name of the new template
    """
    source = frappe.get_doc("AI Prompt Template", template)
    new_doc = frappe.copy_doc(source)

    new_doc.template_name = new_name
    new_doc.template_code = None  # Will be auto-generated
    new_doc.is_default = 0  # Don't duplicate default status
    new_doc.total_uses = 0
    new_doc.successful_uses = 0
    new_doc.average_confidence = 0
    new_doc.average_tokens = 0
    new_doc.last_used_at = None
    new_doc.created_by = frappe.session.user

    # Update version
    if new_doc.version:
        try:
            parts = new_doc.version.split('.')
            parts[-1] = str(int(parts[-1]) + 1)
            new_doc.version = '.'.join(parts)
        except (ValueError, IndexError):
            new_doc.version = "1.0"

    new_doc.insert()

    return new_doc.name


@frappe.whitelist()
def get_template_statistics() -> Dict[str, Any]:
    """
    Get overall template usage statistics

    Returns:
        Dict with statistics
    """
    stats = {
        "total_templates": frappe.db.count("AI Prompt Template"),
        "active_templates": frappe.db.count("AI Prompt Template", {"is_active": 1}),
        "templates_by_job_type": {},
        "total_uses": 0,
        "overall_success_rate": 0,
        "average_confidence": 0
    }

    # Get templates by job type
    job_types = frappe.get_all(
        "AI Prompt Template",
        filters={"is_active": 1},
        fields=["job_type", "count(*) as count"],
        group_by="job_type"
    )
    for jt in job_types:
        stats["templates_by_job_type"][jt.job_type] = jt.count

    # Aggregate usage stats
    result = frappe.db.sql("""
        SELECT
            SUM(total_uses) as total_uses,
            SUM(successful_uses) as successful_uses,
            AVG(average_confidence) as avg_confidence
        FROM `tabAI Prompt Template`
        WHERE is_active = 1
    """, as_dict=True)

    if result and result[0]:
        stats["total_uses"] = cint(result[0].get("total_uses", 0))
        total_uses = stats["total_uses"]
        successful = cint(result[0].get("successful_uses", 0))
        stats["overall_success_rate"] = (
            round(successful / total_uses * 100, 2) if total_uses > 0 else 0
        )
        stats["average_confidence"] = flt(result[0].get("avg_confidence", 0), 2)

    return stats
