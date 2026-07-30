"""Persisted settings overrides (spec 001 §1.6).

Only *overrides* live here. Anything never changed from the dashboard stays
absent, so the environment remains the source of truth for the default and the
database says only what an operator deliberately changed.
"""

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from brownbear.db import Base


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Stored as text and parsed against the setting's declared type, so a bad
    # historical value can never crash startup — it fails validation on read.
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
