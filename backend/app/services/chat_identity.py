"""Exact canonical owner SQL predicates without changing database collations."""
from sqlalchemy import LargeBinary, and_
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement


class _OwnerBytes(FunctionElement):
    type = LargeBinary()
    inherit_cache = True


@compiles(_OwnerBytes)
@compiles(_OwnerBytes, 'sqlite')
def _sqlite_owner_bytes(element, compiler, **kwargs):
    value = compiler.process(list(element.clauses)[0], **kwargs)
    return f'CAST({value} AS BLOB)'


@compiles(_OwnerBytes, 'mysql')
def _mysql_owner_bytes(element, compiler, **kwargs):
    value = compiler.process(list(element.clauses)[0], **kwargs)
    # Convert character data to a known Unicode encoding before byte comparison;
    # do not rely on the column's text collation, padding or connection charset.
    return f'CAST(CONVERT({value} USING utf8mb4) AS BINARY)'


def exact_owner_predicate(column, owner):
    if type(owner) is not str or not owner or len(owner) > 255:
        raise ValueError('exact canonical owner required')
    encoded = owner.encode('utf-8', errors='strict')
    if len(encoded) > 1020:
        raise ValueError('owner exceeds exact UTF-8 bound')
    return and_(column == owner, _OwnerBytes(column) == encoded)
