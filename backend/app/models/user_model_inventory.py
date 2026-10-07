"""Explicitly migrated account-owned inventory and account-lifetime binding."""
from sqlalchemy import BigInteger, Column, ForeignKey, String
from app.core.database import Base


class UserModelInventory(Base):
    __tablename__ = 'user_model_inventories'
    __table_args__ = {
        'info': {'explicit_migration_only': True},
        'mysql_engine': 'InnoDB',
        'mysql_charset': 'utf8mb4',
        'mysql_collate': 'utf8mb4_bin'
    }
    user_id = Column(String(255), ForeignKey('user_accounts.username', ondelete='CASCADE'), primary_key=True)
    account_instance_id = Column(String(64), nullable=False)
    inventory_revision = Column(BigInteger, nullable=False, default=0)
