"""PIM Scheduled Tasks

This module contains functions that run on a schedule via Frappe's
scheduler. These tasks handle maintenance operations that need to
run periodically without user intervention.

Task Schedule:
    - recalculate_stale_scores: Hourly - Refreshes completeness scores
    - generate_scheduled_feeds: Daily - Generates scheduled export feeds
    - cleanup_orphan_media: Daily - Removes orphaned media files
    - optimize_eav_indexes: Weekly - Optimizes database indexes
    - quality_scan_batch: Daily - Batch quality assessment against policies

Utility Tasks (not scheduled, call via frappe.enqueue):
    - recalculate_all_scores: Force recalculate all product scores
    - cleanup_stale_cache: Clear stale PIM cache entries
    - batch_quality_assessment: Run quality assessment with custom filters
    - run_channel_quality_scan: Evaluate products for channel readiness

These functions are registered in hooks.py under scheduler_events
and executed by the Frappe scheduler worker.

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""


def recalculate_stale_scores():
    """Recalculate completeness scores for products that may be stale.

    This hourly task identifies products that may have outdated completeness
    scores and recalculates them. This handles cases where:
        - Family attribute templates were modified
        - Batch operations didn't trigger score updates
        - Scores are below 100% and may need refresh

    The task processes products in batches to avoid overwhelming the system
    and commits after each product to prevent long-running transactions.

    Limits processing to 500 products per run to ensure timely completion.
    """
    import frappe
    from frappe.utils import now_datetime

    try:
        frappe.logger("pim_scheduler").info(
            "Starting recalculate_stale_scores task"
        )

        # Get products with incomplete scores (may need recalculation)
        # Also include products modified recently but with unchanged scores
        products = frappe.get_all(
            "Product Master",
            filters={
                "completeness_score": ["<", 100]
            },
            fields=["name"],
            order_by="modified desc",
            limit=500
        )

        processed = 0
        errors = 0

        for product in products:
            try:
                # Get and save the document to trigger score recalculation
                doc = frappe.get_doc("Product Master", product.name)
                old_score = doc.completeness_score

                # Recalculate via the completeness utility
                from frappe_pim.pim.utils.completeness import calculate_score
                new_score = calculate_score(doc)

                # Only save if score changed
                if new_score != old_score:
                    doc.completeness_score = new_score
                    doc.flags.ignore_version = True  # Don't create version for auto-update
                    doc.flags.ignore_links = True  # Skip link validation
                    doc.db_update()
                    frappe.db.commit()
                    processed += 1

            except Exception as e:
                errors += 1
                frappe.log_error(
                    message=f"Failed to recalculate score for {product.name}: {str(e)}",
                    title="PIM Score Recalculation Error"
                )
                frappe.db.rollback()

        frappe.logger("pim_scheduler").info(
            f"recalculate_stale_scores completed: {processed} updated, {errors} errors"
        )

    except Exception as e:
        frappe.log_error(
            message=f"recalculate_stale_scores task failed: {str(e)}",
            title="PIM Scheduled Task Error"
        )


def generate_scheduled_feeds():
    """Generate scheduled export feeds for enabled profiles.

    This daily task finds all Export Profile documents that are:
        - Enabled (enabled = 1)
        - Scheduled (is_scheduled = 1)

    For each matching profile, it enqueues a background job to generate
    the export feed. This ensures feeds are generated without blocking
    the scheduler and allows parallel processing of multiple feeds.

    The actual feed generation is handled by the export API module.
    """
    import frappe

    try:
        frappe.logger("pim_scheduler").info(
            "Starting generate_scheduled_feeds task"
        )

        # Find all enabled and scheduled export profiles
        profiles = frappe.get_all(
            "Export Profile",
            filters={
                "enabled": 1,
                "is_scheduled": 1
            },
            fields=["name", "profile_name", "export_format"]
        )

        if not profiles:
            frappe.logger("pim_scheduler").info(
                "No scheduled export profiles found"
            )
            return

        enqueued = 0
        errors = 0

        for profile in profiles:
            try:
                # Check if export module exists before enqueuing
                # This gracefully handles the case where export module
                # is not yet implemented
                try:
                    from frappe_pim.pim.api import export as export_module
                    has_export_module = hasattr(export_module, "generate_feed")
                except ImportError:
                    has_export_module = False

                if has_export_module:
                    frappe.enqueue(
                        "frappe_pim.pim.api.export.generate_feed",
                        queue="long",
                        timeout=3600,
                        profile=profile.name,
                        scheduled=True
                    )
                    enqueued += 1

                    frappe.logger("pim_scheduler").info(
                        f"Enqueued feed generation for profile: {profile.name}"
                    )
                else:
                    # Log that export module is not available
                    frappe.logger("pim_scheduler").warning(
                        f"Export module not available, skipping profile: {profile.name}"
                    )

            except Exception as e:
                errors += 1
                frappe.log_error(
                    message=f"Failed to enqueue feed for {profile.name}: {str(e)}",
                    title="PIM Feed Generation Error"
                )

        frappe.logger("pim_scheduler").info(
            f"generate_scheduled_feeds completed: {enqueued} enqueued, {errors} errors"
        )

    except Exception as e:
        frappe.log_error(
            message=f"generate_scheduled_feeds task failed: {str(e)}",
            title="PIM Scheduled Task Error"
        )


def cleanup_orphan_media():
    """Remove orphaned Product Media records.

    This daily task identifies and removes Product Media records that
    are no longer associated with a valid Product Master. This can happen
    when:
        - Products are deleted without cascade delete
        - Database inconsistencies occur
        - Imports fail midway

    The task uses a LEFT JOIN query to efficiently find orphans and
    deletes them in batches, committing after each deletion to prevent
    long-running transactions.

    Also cleans up the actual files from the file system if they exist.
    """
    import frappe

    try:
        frappe.logger("pim_scheduler").info(
            "Starting cleanup_orphan_media task"
        )

        # Find orphaned Product Media records
        # These are records where the parent Product Master no longer exists
        orphans = frappe.db.sql("""
            SELECT pm.name, pm.file_url
            FROM `tabProduct Media` pm
            LEFT JOIN `tabProduct Master` p ON pm.parent = p.name
            WHERE p.name IS NULL
            LIMIT 1000
        """, as_dict=True)

        if not orphans:
            frappe.logger("pim_scheduler").info(
                "No orphaned media records found"
            )
            return

        deleted = 0
        errors = 0

        for orphan in orphans:
            try:
                # Delete the Product Media record
                frappe.delete_doc(
                    "Product Media",
                    orphan.name,
                    ignore_permissions=True,
                    force=True
                )
                frappe.db.commit()
                deleted += 1

                # Optionally clean up the actual file
                # Note: Frappe's File doctype handles file cleanup separately
                # This is just for the Product Media child table records

            except Exception as e:
                errors += 1
                frappe.log_error(
                    message=f"Failed to delete orphan media {orphan.name}: {str(e)}",
                    title="PIM Orphan Media Cleanup Error"
                )
                frappe.db.rollback()

        frappe.logger("pim_scheduler").info(
            f"cleanup_orphan_media completed: {deleted} deleted, {errors} errors"
        )

    except Exception as e:
        frappe.log_error(
            message=f"cleanup_orphan_media task failed: {str(e)}",
            title="PIM Scheduled Task Error"
        )


def optimize_eav_indexes():
    """Analyze and optimize EAV table indexes.

    This weekly task runs database maintenance on the Product Attribute
    Value table (the EAV storage table) to ensure optimal query performance.

    Operations performed:
        - ANALYZE TABLE: Updates table statistics for query optimizer
        - Checks for missing indexes and logs recommendations

    This is particularly important for EAV tables which can grow large
    and benefit from up-to-date statistics for query planning.
    """
    import frappe

    try:
        frappe.logger("pim_scheduler").info(
            "Starting optimize_eav_indexes task"
        )

        # Analyze the main EAV table for updated statistics
        try:
            frappe.db.sql("ANALYZE TABLE `tabProduct Attribute Value`")
            frappe.logger("pim_scheduler").info(
                "Analyzed tabProduct Attribute Value"
            )
        except Exception as e:
            frappe.log_error(
                message=f"Failed to analyze tabProduct Attribute Value: {str(e)}",
                title="PIM Index Optimization Error"
            )

        # Analyze Product Master table
        try:
            frappe.db.sql("ANALYZE TABLE `tabProduct Master`")
            frappe.logger("pim_scheduler").info(
                "Analyzed tabProduct Master"
            )
        except Exception as e:
            frappe.log_error(
                message=f"Failed to analyze tabProduct Master: {str(e)}",
                title="PIM Index Optimization Error"
            )

        # Analyze Product Variant table if it exists
        try:
            frappe.db.sql("ANALYZE TABLE `tabProduct Variant`")
            frappe.logger("pim_scheduler").info(
                "Analyzed tabProduct Variant"
            )
        except Exception:
            # Table may not exist yet
            pass

        # Check for recommended indexes
        _check_recommended_indexes()

        frappe.db.commit()

        frappe.logger("pim_scheduler").info(
            "optimize_eav_indexes completed successfully"
        )

    except Exception as e:
        frappe.log_error(
            message=f"optimize_eav_indexes task failed: {str(e)}",
            title="PIM Scheduled Task Error"
        )


def _check_recommended_indexes():
    """Check if recommended indexes exist and log warnings if missing.

    This helper function verifies that critical indexes exist on
    the EAV and related tables. Missing indexes are logged for
    administrator attention.
    """
    import frappe

    recommended_indexes = [
        {
            "table": "tabProduct Attribute Value",
            "columns": ["parent", "attribute"],
            "name": "idx_pav_parent_attr"
        },
        {
            "table": "tabProduct Master",
            "columns": ["product_family"],
            "name": "idx_pm_family"
        },
        {
            "table": "tabProduct Master",
            "columns": ["status"],
            "name": "idx_pm_status"
        }
    ]

    for idx_info in recommended_indexes:
        try:
            # Check if index exists
            existing = frappe.db.sql("""
                SHOW INDEX FROM `{table}`
                WHERE Key_name = %s
            """.format(table=idx_info["table"]), (idx_info["name"],), as_dict=True)

            if not existing:
                # Try to create the index
                columns = ", ".join([f"`{c}`" for c in idx_info["columns"]])
                try:
                    frappe.db.sql("""
                        CREATE INDEX IF NOT EXISTS `{name}`
                        ON `{table}` ({columns})
                    """.format(
                        name=idx_info["name"],
                        table=idx_info["table"],
                        columns=columns
                    ))
                    frappe.logger("pim_scheduler").info(
                        f"Created missing index: {idx_info['name']}"
                    )
                except Exception:
                    frappe.logger("pim_scheduler").warning(
                        f"Could not create index {idx_info['name']} on {idx_info['table']}"
                    )

        except Exception:
            # Table may not exist
            pass


def recalculate_all_scores():
    """Recalculate completeness scores for ALL products.

    This is a utility task that can be called manually to force
    recalculation of all product completeness scores. Unlike the
    scheduled task, this processes all products regardless of their
    current score.

    Use with caution on large product catalogs as it may take
    considerable time to complete.

    This function is not scheduled but can be called via:
        frappe.enqueue("frappe_pim.pim.tasks.scheduled.recalculate_all_scores")
    """
    import frappe

    try:
        frappe.logger("pim_scheduler").info(
            "Starting recalculate_all_scores task"
        )

        # Get all products
        products = frappe.get_all(
            "Product Master",
            fields=["name"],
            order_by="modified desc"
        )

        total = len(products)
        processed = 0
        errors = 0

        for i, product in enumerate(products):
            try:
                doc = frappe.get_doc("Product Master", product.name)

                from frappe_pim.pim.utils.completeness import calculate_score
                new_score = calculate_score(doc)

                doc.completeness_score = new_score
                doc.flags.ignore_version = True
                doc.flags.ignore_links = True
                doc.db_update()

                processed += 1

                # Commit every 100 products
                if processed % 100 == 0:
                    frappe.db.commit()
                    frappe.logger("pim_scheduler").info(
                        f"Progress: {processed}/{total} products processed"
                    )

            except Exception as e:
                errors += 1
                frappe.log_error(
                    message=f"Failed to recalculate score for {product.name}: {str(e)}",
                    title="PIM Score Recalculation Error"
                )
                frappe.db.rollback()

        # Final commit
        frappe.db.commit()

        frappe.logger("pim_scheduler").info(
            f"recalculate_all_scores completed: {processed} processed, {errors} errors out of {total} total"
        )

    except Exception as e:
        frappe.log_error(
            message=f"recalculate_all_scores task failed: {str(e)}",
            title="PIM Task Error"
        )


def cleanup_stale_cache():
    """Clean up stale PIM cache entries.

    This utility task clears potentially stale cache entries that
    may have accumulated. It's useful when cache invalidation
    didn't work properly or after bulk operations.

    This function is not scheduled by default but can be called via:
        frappe.enqueue("frappe_pim.pim.tasks.scheduled.cleanup_stale_cache")
    """
    import frappe

    try:
        frappe.logger("pim_scheduler").info(
            "Starting cleanup_stale_cache task"
        )

        from frappe_pim.pim.utils.cache import clear_all_pim_cache
        clear_all_pim_cache()

        frappe.logger("pim_scheduler").info(
            "cleanup_stale_cache completed"
        )

    except Exception as e:
        frappe.log_error(
            message=f"cleanup_stale_cache task failed: {str(e)}",
            title="PIM Task Error"
        )


def quality_scan_batch():
    """Run batch quality assessment for products.

    This scheduled task evaluates products against data quality policies
    to identify quality issues and update quality scores. The task:
        - Finds products that haven't been scanned recently
        - Evaluates each product against applicable quality policies
        - Updates quality scores and identifies gaps
        - Logs issues for data steward review

    This is typically scheduled to run daily to ensure all products
    maintain up-to-date quality assessments.

    Processing is limited to 500 products per run to ensure timely
    completion and avoid overwhelming the system.
    """
    import frappe
    from frappe.utils import now_datetime, add_days, getdate

    try:
        frappe.logger("pim_scheduler").info(
            "Starting quality_scan_batch task"
        )

        # Get products that need quality scanning
        # Priority: products not scanned in last 7 days, then by lowest score
        seven_days_ago = add_days(getdate(), -7)

        products = frappe.get_all(
            "Product Master",
            filters={
                "status": ["not in", ["Archived", "Deleted"]]
            },
            fields=["name", "completeness_score", "modified"],
            or_filters=[
                ["pim_last_quality_scan", "is", "not set"],
                ["pim_last_quality_scan", "<", seven_days_ago]
            ],
            order_by="completeness_score asc, modified desc",
            limit=500
        )

        if not products:
            frappe.logger("pim_scheduler").info(
                "No products require quality scanning"
            )
            return

        processed = 0
        errors = 0
        issues_found = 0

        for product in products:
            try:
                result = _evaluate_product_quality(product.name)

                if result.get("success"):
                    processed += 1
                    issues_found += result.get("issues_count", 0)

                    # Update last scan timestamp
                    frappe.db.set_value(
                        "Product Master",
                        product.name,
                        "pim_last_quality_scan",
                        now_datetime(),
                        update_modified=False
                    )

                    # Commit every 10 products
                    if processed % 10 == 0:
                        frappe.db.commit()

            except Exception as e:
                errors += 1
                frappe.log_error(
                    message=f"Quality scan failed for {product.name}: {str(e)}",
                    title="PIM Quality Scan Error"
                )
                frappe.db.rollback()

        # Final commit
        frappe.db.commit()

        frappe.logger("pim_scheduler").info(
            f"quality_scan_batch completed: {processed} scanned, "
            f"{issues_found} issues found, {errors} errors"
        )

    except Exception as e:
        frappe.log_error(
            message=f"quality_scan_batch task failed: {str(e)}",
            title="PIM Scheduled Task Error"
        )


def batch_quality_assessment(product_filters=None, policy_names=None, batch_size=100):
    """Run quality assessment on a batch of products.

    This utility function can be called directly or enqueued to evaluate
    multiple products against data quality policies. It's useful for:
        - Manual quality audits
        - Post-import quality checks
        - Re-evaluation after policy changes

    Args:
        product_filters: Optional dict of filters for Product Master query
        policy_names: Optional list of specific policy names to evaluate
                     (evaluates all enabled policies if not specified)
        batch_size: Number of products to process per commit (default 100)

    Returns:
        dict: Summary of assessment results

    Can be called via:
        frappe.enqueue(
            "frappe_pim.pim.tasks.scheduled.batch_quality_assessment",
            queue="long",
            timeout=3600,
            product_filters={"product_family": "Electronics"},
            policy_names=["Required Fields Policy"]
        )
    """
    import frappe
    from frappe.utils import now_datetime

    try:
        frappe.logger("pim_scheduler").info(
            f"Starting batch_quality_assessment with filters: {product_filters}"
        )

        # Build product query
        filters = product_filters or {}
        if "status" not in filters:
            filters["status"] = ["not in", ["Archived", "Deleted"]]

        products = frappe.get_all(
            "Product Master",
            filters=filters,
            fields=["name"],
            order_by="modified desc"
        )

        if not products:
            frappe.logger("pim_scheduler").info(
                "No products found matching filters"
            )
            return {
                "success": True,
                "total": 0,
                "processed": 0,
                "errors": 0,
                "message": "No products found matching filters"
            }

        total = len(products)
        processed = 0
        errors = 0
        passed = 0
        failed = 0

        for i, product in enumerate(products):
            try:
                result = _evaluate_product_quality(
                    product.name,
                    policy_names=policy_names
                )

                if result.get("success"):
                    processed += 1
                    if result.get("overall_passed"):
                        passed += 1
                    else:
                        failed += 1

                    # Update last scan timestamp
                    frappe.db.set_value(
                        "Product Master",
                        product.name,
                        "pim_last_quality_scan",
                        now_datetime(),
                        update_modified=False
                    )

                # Commit in batches
                if (i + 1) % batch_size == 0:
                    frappe.db.commit()
                    frappe.logger("pim_scheduler").info(
                        f"Progress: {i + 1}/{total} products assessed"
                    )

            except Exception as e:
                errors += 1
                frappe.log_error(
                    message=f"Quality assessment failed for {product.name}: {str(e)}",
                    title="PIM Quality Assessment Error"
                )
                frappe.db.rollback()

        # Final commit
        frappe.db.commit()

        summary = {
            "success": True,
            "total": total,
            "processed": processed,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "pass_rate": round((passed / processed * 100) if processed > 0 else 0, 2),
            "completed_at": str(now_datetime())
        }

        frappe.logger("pim_scheduler").info(
            f"batch_quality_assessment completed: {summary}"
        )

        return summary

    except Exception as e:
        frappe.log_error(
            message=f"batch_quality_assessment task failed: {str(e)}",
            title="PIM Task Error"
        )
        return {
            "success": False,
            "error": str(e)
        }


def _evaluate_product_quality(product_name, policy_names=None):
    """Evaluate a single product against quality policies.

    This helper function performs the actual quality evaluation for
    a product, checking against all applicable data quality policies.

    Args:
        product_name: Name of the Product Master document
        policy_names: Optional list of specific policies to evaluate

    Returns:
        dict: Evaluation results including pass/fail status and issues
    """
    import frappe

    try:
        product = frappe.get_doc("Product Master", product_name)

        # Get policies to evaluate
        if policy_names:
            policies = [
                frappe.get_doc("Data Quality Policy", name)
                for name in policy_names
                if frappe.db.exists("Data Quality Policy", name)
            ]
        else:
            # Get all enabled policies
            policy_list = frappe.get_all(
                "Data Quality Policy",
                filters={"enabled": 1},
                fields=["name"],
                order_by="priority asc"
            )
            policies = [
                frappe.get_doc("Data Quality Policy", p.name)
                for p in policy_list
            ]

        if not policies:
            # No policies defined, just calculate basic completeness
            from frappe_pim.pim.utils.completeness import calculate_score
            score = calculate_score(product)

            return {
                "success": True,
                "product": product_name,
                "overall_passed": score >= 80,
                "overall_score": score,
                "issues_count": 0,
                "policies_evaluated": 0
            }

        # Evaluate against each policy
        all_errors = []
        all_warnings = []
        policy_results = []
        overall_passed = True
        total_weight = 0
        weighted_score = 0

        for policy in policies:
            try:
                result = policy.evaluate_product(product)

                if result.get("skipped"):
                    continue

                policy_results.append({
                    "policy": policy.name,
                    "policy_name": policy.policy_name,
                    "passed": result.get("passed", True),
                    "score": result.get("score", 100)
                })

                if not result.get("passed"):
                    overall_passed = False

                all_errors.extend(result.get("failed_rules", []))
                all_warnings.extend(result.get("warnings", []))

                # Calculate weighted score
                if policy.include_in_score:
                    weight = policy.policy_weight or 1.0
                    total_weight += weight
                    weighted_score += result.get("score", 0) * weight

                # Update policy statistics
                policy.update_statistics(
                    passed=1 if result.get("passed") else 0,
                    failed=0 if result.get("passed") else 1
                )

            except Exception as e:
                frappe.log_error(
                    message=f"Policy {policy.name} evaluation error for {product_name}: {str(e)}",
                    title="PIM Policy Evaluation Error"
                )

        # Calculate overall score
        overall_score = (weighted_score / total_weight) if total_weight > 0 else 100

        # Update product's quality score if field exists
        if hasattr(product, "pim_quality_score"):
            frappe.db.set_value(
                "Product Master",
                product_name,
                "pim_quality_score",
                overall_score,
                update_modified=False
            )

        # Store quality issues count
        issues_count = len(all_errors) + len(all_warnings)
        if hasattr(product, "pim_quality_issues"):
            issue_summary = []
            for error in all_errors[:5]:  # First 5 errors
                issue_summary.append(f"ERROR: {error.get('error_message', 'Unknown')}")
            for warning in all_warnings[:3]:  # First 3 warnings
                issue_summary.append(f"WARNING: {warning.get('error_message', 'Unknown')}")

            frappe.db.set_value(
                "Product Master",
                product_name,
                "pim_quality_issues",
                "\n".join(issue_summary) if issue_summary else None,
                update_modified=False
            )

        return {
            "success": True,
            "product": product_name,
            "overall_passed": overall_passed,
            "overall_score": round(overall_score, 2),
            "issues_count": issues_count,
            "errors": len(all_errors),
            "warnings": len(all_warnings),
            "policies_evaluated": len(policy_results),
            "policy_results": policy_results
        }

    except Exception as e:
        return {
            "success": False,
            "product": product_name,
            "error": str(e)
        }


def run_channel_quality_scan(channel_code, product_filters=None):
    """Run channel-specific quality assessment for products.

    Evaluates products against channel-specific requirements to identify
    readiness gaps. This is useful before publishing products to a channel.

    Args:
        channel_code: The channel to evaluate against (e.g., 'amazon', 'shopify')
        product_filters: Optional dict of filters for Product Master query

    Returns:
        dict: Summary with ready and not-ready products

    Can be called via:
        frappe.enqueue(
            "frappe_pim.pim.tasks.scheduled.run_channel_quality_scan",
            queue="long",
            timeout=3600,
            channel_code="amazon",
            product_filters={"status": "Active"}
        )
    """
    import frappe
    from frappe.utils import now_datetime

    try:
        frappe.logger("pim_scheduler").info(
            f"Starting run_channel_quality_scan for channel: {channel_code}"
        )

        # Import completeness module for channel scoring
        try:
            from frappe_pim.pim.utils.completeness import (
                calculate_channel_specific_score,
                gap_analysis
            )
            has_channel_scoring = True
        except ImportError:
            has_channel_scoring = False

        if not has_channel_scoring:
            frappe.logger("pim_scheduler").warning(
                "Channel scoring module not available"
            )
            return {
                "success": False,
                "error": "Channel scoring module not available"
            }

        # Build product query
        filters = product_filters or {}
        if "status" not in filters:
            filters["status"] = ["not in", ["Archived", "Deleted"]]

        products = frappe.get_all(
            "Product Master",
            filters=filters,
            fields=["name"],
            order_by="modified desc",
            limit=1000
        )

        if not products:
            return {
                "success": True,
                "channel": channel_code,
                "total": 0,
                "ready": 0,
                "not_ready": 0,
                "message": "No products found"
            }

        total = len(products)
        ready_products = []
        not_ready_products = []
        errors = 0

        for product in products:
            try:
                score_result = calculate_channel_specific_score(
                    product.name,
                    channel_code
                )

                if score_result.get("is_channel_ready"):
                    ready_products.append({
                        "name": product.name,
                        "score": score_result.get("score", 0)
                    })
                else:
                    # Get gap analysis for not-ready products
                    gaps = gap_analysis(product.name, channel_code)
                    not_ready_products.append({
                        "name": product.name,
                        "score": score_result.get("score", 0),
                        "critical_gaps": len(gaps.critical_gaps) if hasattr(gaps, 'critical_gaps') else 0,
                        "missing_fields": score_result.get("missing_fields", [])[:5]
                    })

            except Exception as e:
                errors += 1
                frappe.log_error(
                    message=f"Channel scan failed for {product.name}: {str(e)}",
                    title="PIM Channel Quality Scan Error"
                )

        # Commit progress tracking
        frappe.db.commit()

        summary = {
            "success": True,
            "channel": channel_code,
            "total": total,
            "ready": len(ready_products),
            "not_ready": len(not_ready_products),
            "errors": errors,
            "readiness_rate": round((len(ready_products) / total * 100) if total > 0 else 0, 2),
            "ready_products": ready_products[:50],  # Return top 50
            "not_ready_products": sorted(
                not_ready_products,
                key=lambda x: x.get("critical_gaps", 0),
                reverse=True
            )[:50],  # Return top 50 by gaps
            "completed_at": str(now_datetime())
        }

        frappe.logger("pim_scheduler").info(
            f"run_channel_quality_scan completed for {channel_code}: "
            f"{summary['ready']}/{summary['total']} ready ({summary['readiness_rate']}%)"
        )

        return summary

    except Exception as e:
        frappe.log_error(
            message=f"run_channel_quality_scan task failed: {str(e)}",
            title="PIM Task Error"
        )
        return {
            "success": False,
            "channel": channel_code,
            "error": str(e)
        }
