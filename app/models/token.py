from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.models.campaign import utcnow


def _uuid() -> str:
    return str(uuid.uuid4())


class PlatformToken(Base):
    """Encrypted platform access token.

    Only ciphertext + IV are ever persisted. The plaintext token never touches
    the database or the logs.
    """

    __tablename__ = "platform_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    platform: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    encrypted_token: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    iv: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    def __repr__(self) -> str:  # never leak ciphertext/plaintext in reprs
        return f"<PlatformToken platform={self.platform!r} id={self.id!r}>"
