import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.transcript import TranscriptEntry


class TranscriptRepository:
    """All database access for transcripts: replace and list per application."""

    def __init__(self, db: Session):
        self.db = db

    def replace_for_application(
        self, application_id: uuid.UUID, entries: list[tuple[str, str]]
    ) -> None:
        self.db.execute(
            delete(TranscriptEntry).where(TranscriptEntry.application_id == application_id)
        )
        self.db.add_all(
            TranscriptEntry(application_id=application_id, seq=i, role=role, text=text)
            for i, (role, text) in enumerate(entries)
        )
        self.db.commit()

    def list_by_application(self, application_id: uuid.UUID) -> list[TranscriptEntry]:
        stmt = (
            select(TranscriptEntry)
            .where(TranscriptEntry.application_id == application_id)
            .order_by(TranscriptEntry.seq)
        )
        return list(self.db.scalars(stmt))