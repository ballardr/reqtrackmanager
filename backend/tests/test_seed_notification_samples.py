"""Tests for `scripts/seed_notification_samples.py`: the seeded notifications are registered types, and between them
they cover every target kind except those the helper reports as having no record to point at, so a seeded dataset
opens every kind it claims to."""

import sys
from pathlib import Path

from sqlalchemy import select

from app.database import SessionLocal
from app.models.notification import Notification
from app.models.user import User
from app.modules.registry import get_all_notification_target_kinds, get_all_notification_targets
from tests.conftest import create_org_user, create_project

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from seed_notification_samples import seed_notification_samples  # noqa: E402


def test_the_samples_cover_every_target_kind_the_dataset_can_open(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    create_org_user(client, admin_token, org_id, "sampled@example.com", role="member")

    skipped = seed_notification_samples("sampled@example.com", org_id, project["id"])

    db = SessionLocal()
    try:
        rows = db.scalars(
            select(Notification).join(User, User.id == Notification.user_id).where(User.email == "sampled@example.com")
        ).all()
    finally:
        db.close()
    targets = get_all_notification_targets()
    assert rows and all(row.type in targets for row in rows), "a sample uses a type that declares no target"
    covered = {kind for row in rows for kind in targets[row.type]}
    # A kind is skipped only when the organisation has no policy, report run or standard to open.
    assert set(skipped) <= {"record", "delivery_status", "policy", "report_run", "standard"}
    assert get_all_notification_target_kinds() - covered <= set(skipped)
