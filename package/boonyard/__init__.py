"""boonyard — an append-only, queryable, threaded memory substrate.

Entry + tags = memory. The rest is plumbing.

The public API is assembled here as each milestone lands. Import surface is kept
flat and small on purpose (CHARTER); everything below is stdlib-only (ADR-0001).
"""

from .aggregator import Aggregator, aggregator
from .constants import SCHEMA_VERSION
from .db import connect, init_db, schema_version
from .log import log_entry, log_skill_revision, validate_entry
from .profile import (
    Profile,
    default_profile,
    load_profile,
    resolve_db_path,
    resolve_profile_path,
)
from .query import (
    audit_doctor,
    by_id,
    get_thread,
    latest_skill,
    list_agents,
    list_entry_types,
    list_skills,
    list_tags,
    node_info,
    recent,
    search_by_tag,
    search_by_tag_exact,
    search_text,
)
from .retag import retag_entry

__version__ = "3.0.0"

__all__ = [
    "SCHEMA_VERSION",
    "Aggregator",
    "Profile",
    "__version__",
    "aggregator",
    "audit_doctor",
    "by_id",
    "connect",
    "default_profile",
    "get_thread",
    "init_db",
    "latest_skill",
    "list_agents",
    "list_entry_types",
    "list_skills",
    "list_tags",
    "load_profile",
    "log_entry",
    "log_skill_revision",
    "node_info",
    "recent",
    "resolve_db_path",
    "resolve_profile_path",
    "retag_entry",
    "schema_version",
    "search_by_tag",
    "search_by_tag_exact",
    "search_text",
    "validate_entry",
]
