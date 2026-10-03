"""Explicit-only B1 infrastructure ledger, not a relationship model."""
from sqlalchemy import Column, Integer, String

from app.core.database import Base
from app.models.teaching import UTC_DATETIME, _ck, _pk, explicit_table_options


class TeachingSchemaVersion(Base):
    __tablename__ = "teaching_schema_versions"
    component = Column(String(64), nullable=False)
    version = Column(Integer, nullable=False)
    contract_hash = Column(String(64), nullable=False)
    completed_at = Column(UTC_DATETIME, nullable=False)
    __table_args__ = (_pk(__tablename__, "component"), _ck(__tablename__, "version_positive", "version >= 1"), explicit_table_options())
