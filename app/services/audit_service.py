"""
Records who did what, for the admin portal's Users & Audit view. This is
deliberately a plain insert with no transaction of its own - it's meant to
be called right before the caller's own db.commit(), so the audit row and
the change it describes are committed together atomically. If the calling
endpoint rolls back, the audit row rolls back with it, which is correct:
we only want a record of changes that actually happened.
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.models.user import AuditLog


def record_audit(
    db: Session,
    actor_user_id: Optional[str],
    action: str,
    entity_type: str,
    entity_id: Optional[str] = None,
    details: Optional[str] = None,
) -> AuditLog:
    """
    `action` should read like "member.update", "loan.approve", "user.role_change" -
    dot-separated module.verb, so the audit log is filterable/greppable.
    """
    entry = AuditLog(
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
    )
    db.add(entry)
    return entry
