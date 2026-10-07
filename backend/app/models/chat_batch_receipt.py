"""Metadata-only paper receipt declarations; explicit migration, never startup DDL."""
from sqlalchemy import CheckConstraint, Column, Integer, LargeBinary, String
from sqlalchemy.dialects.mysql import VARBINARY
from sqlalchemy.orm import declarative_base

ReceiptBase = declarative_base()


class ChatBatchReceipt(ReceiptBase):
    __tablename__ = 'chat_batch_receipts'
    # Preserve Unicode normalization variants, casing and trailing key spaces.
    owner_key = Column(LargeBinary(1020).with_variant(VARBINARY(1020), 'mysql'), primary_key=True)
    request_key = Column(LargeBinary(512).with_variant(VARBINARY(512), 'mysql'), primary_key=True)
    request_digest = Column(String(64), nullable=False)
    agent_mode = Column(String(32), nullable=False)
    conversation_id = Column(String(64), nullable=True)
    project_id = Column(String(64), nullable=True)
    state = Column(String(16), nullable=False)
    # No FK: deleting transcript rows must leave the minimal retry tombstone.
    user_message_id = Column(Integer, nullable=True)
    assistant_message_id = Column(Integer, nullable=True)
    __table_args__ = (
        CheckConstraint("state IN ('reserved','committed','deleted')", name='ck_chat_batch_state'),
        CheckConstraint("(state = 'reserved' AND user_message_id IS NULL AND assistant_message_id IS NULL) OR "
            "(state IN ('committed','deleted') AND user_message_id IS NOT NULL AND assistant_message_id IS NOT NULL "
            "AND user_message_id > 0 AND assistant_message_id > 0 "
            "AND user_message_id != assistant_message_id)", name='ck_chat_batch_pair'),
        {'mysql_engine':'InnoDB', 'mysql_charset':'utf8mb4', 'mysql_collate':'utf8mb4_bin',
         'info':{'explicit_migration_only':True}},
    )
