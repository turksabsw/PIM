"""PIM Background Tasks Module

This module contains scheduled and background task functions for the
PIM application. These tasks run asynchronously via Frappe's job queue
and scheduler.

Task Categories:
    - Scheduled tasks: Run periodically (hourly, daily, weekly)
    - Background jobs: Run on-demand via frappe.enqueue()

Scheduled tasks are configured in hooks.py under scheduler_events.
"""

from frappe_pim.pim.tasks.scheduled import (
    recalculate_stale_scores,
    generate_scheduled_feeds,
    cleanup_orphan_media,
    optimize_eav_indexes,
)

__all__ = [
    "recalculate_stale_scores",
    "generate_scheduled_feeds",
    "cleanup_orphan_media",
    "optimize_eav_indexes",
]
