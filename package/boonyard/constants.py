"""Canonical constants for the boonyard substrate.

Small on purpose. Everything here is a value the whole package agrees on:
the schema version, default filenames/ports, and the *default* soft-validation
sets. A node's ``boonyard.toml`` profile (M4) may extend the agent / entry_type
sets; per ADR-0002 those are advisory — unknown values warn but still insert.
"""

# The schema version this package writes and expects. Matches the package major
# version (arch 04: "major version = schema version"). Bumping either is an ADR.
SCHEMA_VERSION = 3

# A node is one SQLite file (ADR-0003). This is its conventional filename inside
# a node directory, and the conventional directory name for a project's own node.
DEFAULT_DB_FILENAME = "journal.db"
DEFAULT_NODE_DIRNAME = "node"

# The MCP server's default local port (arch 04 / arch 06).
DEFAULT_MCP_PORT = 8765

# Default seats (agent column = *role*, not model — wall entry 97). Model identity
# rides on a ``model:`` tag, self-reported per entry. This is the fallback registry
# when no ``boonyard.toml`` [agents] section is declared; it is advisory only.
DEFAULT_AGENTS: frozenset[str] = frozenset(
    {
        "code",  # the implementing seat (Claude Code and kin)
        "cowork",  # the design seat
        "chat",  # the consumer-chat seat
        "professor",  # the human (Jacob)
        "system",  # auto-generated entries (audits, CI, migrations)
    }
)

# Default entry types (arch 01). A profile may extend this list. Unknown types
# warn but insert — the substrate captures, it does not gatekeep.
DEFAULT_ENTRY_TYPES: frozenset[str] = frozenset(
    {
        "prompt",  # a prompt or directive given to a seat
        "implementation",  # a record of work done
        "decision",  # a choice with rationale (often paired with an ADR)
        "discussion",  # exploratory back-and-forth
        "lint_finding",  # a noted issue, code smell, observation
        "verification",  # a confirmation that something was tested or holds
        "vision",  # a future-looking direction, longer than a note
        "error",  # a recorded failure or incident
        "note",  # the catch-all
        "skill",  # a reusable how-to (ADR-0004)
        "hotfix",  # a rapid fix, often paired with a root-cause entry
    }
)

# Seats exempt from the audit_doctor "AI-seat entry missing a model: tag" check
# (wall entry 97). A human and the system don't self-report a model.
NON_MODEL_SEATS: frozenset[str] = frozenset({"professor", "system"})
