"""boonyard — an append-only, queryable, threaded memory substrate.

Entry + tags = memory. The rest is plumbing.

The public API is assembled here as each milestone lands. Import surface is kept
flat and small on purpose (CHARTER); everything below is stdlib-only (ADR-0001).
"""

from .constants import SCHEMA_VERSION
from .db import connect, init_db, schema_version

__version__ = "3.0.0"

__all__ = [
    "SCHEMA_VERSION",
    "__version__",
    "connect",
    "init_db",
    "schema_version",
]
