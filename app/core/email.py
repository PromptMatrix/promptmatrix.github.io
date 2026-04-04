"""
Email module — DISABLED in local-first standalone mode.

All functions are no-ops. No external email service. No Resend. No SMTP.
Notification happens entirely within the dashboard UI.

If you build a cloud/SaaS fork, replace this module with your email provider.
"""

import logging

log = logging.getLogger(__name__)


async def send_welcome(*args, **kwargs):
    log.debug("[EMAIL NOOP] send_welcome — local mode, email disabled")


async def send_approval_needed(*args, **kwargs):
    log.debug("[EMAIL NOOP] send_approval_needed — local mode, email disabled")


async def send_version_approved(*args, **kwargs):
    log.debug("[EMAIL NOOP] send_version_approved — local mode, email disabled")


async def send_version_rejected(*args, **kwargs):
    log.debug("[EMAIL NOOP] send_version_rejected — local mode, email disabled")


async def send_eval_failed(*args, **kwargs):
    log.debug("[EMAIL NOOP] send_eval_failed — local mode, email disabled")


async def send_invite(*args, **kwargs):
    log.debug("[EMAIL NOOP] send_invite — local mode, email disabled")
