"""Install a whole school from one JSON file filled in by the onboarding team. See
docs/school-onboarding.md for the file format.

The curriculum tree (competencias, capacidades, estándares, desempeños) is not typed in the file:
each área names a catalog area by codigo and the loader copies the tree from the CNEB catalog
(curriculum). What the school decides is which áreas, grados and transversales it uses.
"""

import hashlib
from uuid import UUID


def derive_id(kind: str, modular_code: str, key: str) -> UUID:
    """A row's primary key from what the row is, so loading the same file into an empty database
    always yields the same ids. It is exactly Postgres' md5('<kind>:<modular>:<key>')::uuid, which
    is what lets seed/seed_demo.sql refer to these rows in plain SQL without a lookup. The modular
    code is in the input so two schools never collide on MAT-C1."""
    return UUID(bytes=hashlib.md5(f"{kind}:{modular_code}:{key}".encode()).digest())
