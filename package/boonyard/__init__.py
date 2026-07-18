"""boonyard — an append-only, queryable, threaded memory substrate.

Entry + tags = memory. The rest is plumbing.

The public API is assembled here as each milestone lands. Import surface is kept
flat and small on purpose (CHARTER); everything below is stdlib-only (ADR-0001).
"""

from .constants import SCHEMA_VERSION
from .db import connect, init_db, schema_version
from .log import log_entry, log_skill_revision, validate_entry
from .retag import retag_entry

__version__ = "3.0.0"

__all__ = [
    "SCHEMA_VERSION",
    "__version__",
    "connect",
    "init_db",
    "log_entry",
    "log_skill_revision",
    "retag_entry",
    "schema_version",
    "validate_entry",
]
