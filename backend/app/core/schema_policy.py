"""Pure startup exclusion shared with future explicitly migrated stages."""
from sqlalchemy import Table


def startup_table_allowed(table: Table) -> bool:
    return not table.info.get("explicit_migration_only", False) and not table.name.startswith("teaching_")
