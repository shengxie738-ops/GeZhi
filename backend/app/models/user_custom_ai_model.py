"""Versioned BYOK storage. Legacy ciphertext is never decrypted or serialized."""
import uuid
from sqlalchemy import BigInteger, Boolean, Column, ForeignKey, Index, JSON, String, Text, TIMESTAMP, text
from sqlalchemy.sql import func
from app.core.database import Base
from app.services.byok.errors import ByokError


class UserCustomAIModel(Base):
    __tablename__ = 'user_custom_ai_models'
    __table_args__ = (
        Index('ix_byok_owner_config_version', 'user_id', 'id', 'config_version'),
        {'info': {'explicit_migration_only': True}, 'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_bin'}
    )
    id = Column(String(64), primary_key=True, default=lambda: uuid.uuid4().hex, index=True)
    user_id = Column(
        String(255),
        ForeignKey('user_accounts.username', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    owner_binding_token = Column(String(64), nullable=True)
    name = Column(String(64), nullable=False, default='Custom model')
    provider = Column(String(64), nullable=False, default='OpenAI Compatible')
    # Retained display-only historical column, never interpreted as an adapter.
    api_type = Column(String(64), nullable=False, default='Chat Completions API')
    adapter_id = Column(String(64), nullable=True)
    base_url = Column(String(512), nullable=False)
    encrypted_api_key = Column(Text, nullable=False, default='')
    credential_envelope = Column(JSON, nullable=True)
    credential_state = Column(String(32), nullable=False, default='legacy_reentry_required')
    config_version = Column(BigInteger, nullable=False, default=1)
    credential_version = Column(BigInteger, nullable=False, default=0)
    consent_version = Column(BigInteger, nullable=False, default=0)
    destination_digest = Column(String(64), nullable=True)
    capability_evidence = Column(JSON, nullable=False, default=list)
    probe_generations = Column(JSON, nullable=False, default=dict)
    response_model_aliases = Column(JSON, nullable=False, default=dict)
    model_ids = Column(JSON, nullable=False, default=list)
    is_active = Column(Boolean, nullable=False, default=False)
    created_at = Column(TIMESTAMP, server_default=text('CURRENT_TIMESTAMP'))
    updated_at = Column(TIMESTAMP, server_default=text('CURRENT_TIMESTAMP'), onupdate=func.now())

    def get_decrypted_api_key(self):
        raise ByokError('CREDENTIAL_REENTRY_REQUIRED')

    def to_dict(self, mask_key=True):
        # All public output must pass through an account-bound repository snapshot.
        raise ByokError('UNSUPPORTED_ADAPTER')
