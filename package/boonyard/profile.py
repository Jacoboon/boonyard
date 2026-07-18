"""The schema profile — ``boonyard.toml`` parsing + config precedence (ADR-0002 §Layer 4).

A profile is the per-node contract: the advisory seat registry, allowed
entry_types, declared tag namespaces, and extras configuration. It is *advisory*
— it informs soft-validation warnings, never rejections (ADR-0002). A malformed
or missing profile warns and falls back to built-in defaults; it never crashes.

The ``[agents]`` section is an advisory seat *registry*, not an allowlist (wall
entry 97): seats are roles (``code``, ``cowork``, ``chat``, ``professor``,
``system``), each with a one-line lane description. A recurring unknown seat is a
signal to register it, not to reject it. Model identity rides on a ``model:`` tag,
not on this list.

Stdlib-only: ``tomllib`` (Python 3.11+), per ADR-0001.
"""

import logging
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .constants import (
    DEFAULT_AGENTS,
    DEFAULT_DB_FILENAME,
    DEFAULT_ENTRY_TYPES,
    DEFAULT_NODE_DIRNAME,
    DEFAULT_TAG_NAMESPACES,
)

_log = logging.getLogger("boonyard")


@dataclass(frozen=True)
class Profile:
    """A parsed ``boonyard.toml`` (or the built-in defaults).

    ``allowed_agents`` / ``allowed_entry_types`` / ``namespaces`` are the sets the
    write path and ``audit_doctor`` soft-validate against. ``agent_lanes`` and
    ``namespace_docs`` carry the human-readable descriptions for discovery tools.
    """

    node_name: str | None = None
    allowed_agents: frozenset[str] = DEFAULT_AGENTS
    allowed_entry_types: frozenset[str] = DEFAULT_ENTRY_TYPES
    namespaces: frozenset[str] = DEFAULT_TAG_NAMESPACES
    agent_lanes: dict[str, str] = field(default_factory=dict)
    namespace_docs: dict[str, str] = field(default_factory=dict)
    extras_enabled: bool = False
    extras_fields: tuple[str, ...] = ()
    extras_indexes: tuple[str, ...] = ()

    def validation_kwargs(self) -> dict:
        """The soft-validation keyword args to splat into ``log_entry`` / ``validate_entry``."""
        return {
            "known_agents": self.allowed_agents,
            "known_entry_types": self.allowed_entry_types,
            "known_namespaces": self.namespaces,
        }


def default_profile() -> Profile:
    """The built-in profile used when no ``boonyard.toml`` is present."""
    return Profile()


def _safe_load_toml(path: Path) -> dict | None:
    """Parse a TOML file, returning None (with a warning) on any error."""
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        _log.warning("could not read profile %s: %s — using defaults", path, exc)
        return None


def profile_from_dict(data: dict) -> Profile:
    """Build a :class:`Profile` from an already-parsed TOML mapping.

    Accepts the ``[agents] allowed = [...]`` form (arch 02) and the
    lane-description table form (``[agents]\\ncode = "the implementing seat"``,
    wall entry 97) — with the lane form, the seat keys are the registry.
    """
    node = data.get("node", {})
    agents = data.get("agents", {})
    entry_types = data.get("entry_types", {})
    namespaces_tbl = data.get("tags", {}).get("namespaces", {})
    extras = data.get("extras", {})

    allowed = agents.get("allowed")
    lanes = {k: v for k, v in agents.items() if k != "allowed" and isinstance(v, str)}
    if allowed is None:
        allowed = list(lanes) if lanes else list(DEFAULT_AGENTS)
    allowed_agents = frozenset(allowed) if allowed else DEFAULT_AGENTS

    et_allowed = entry_types.get("allowed")
    allowed_entry_types = frozenset(et_allowed) if et_allowed else DEFAULT_ENTRY_TYPES

    ns_docs = {k: v for k, v in namespaces_tbl.items() if isinstance(v, str)}
    namespaces = frozenset(ns_docs) | DEFAULT_TAG_NAMESPACES

    return Profile(
        node_name=node.get("name"),
        allowed_agents=allowed_agents,
        allowed_entry_types=allowed_entry_types,
        namespaces=namespaces,
        agent_lanes=lanes,
        namespace_docs=ns_docs,
        extras_enabled=bool(extras.get("enabled", False)),
        extras_fields=tuple(extras.get("fields", [])),
        extras_indexes=tuple(extras.get("indexes", [])),
    )


def load_profile(path: str | Path | None) -> Profile:
    """Load a profile from ``path``, or return defaults if missing/unreadable.

    Never raises: a malformed ``boonyard.toml`` warns and yields the default
    profile (the substrate captures; validators only advise).

    Example:
        profile = load_profile("node/boonyard.toml")
        log_entry("code", "note", "x", db_path="node/journal.db",
                  **profile.validation_kwargs())
    """
    if path is None:
        return default_profile()
    p = Path(path)
    if not p.exists():
        return default_profile()
    data = _safe_load_toml(p)
    if data is None:
        return default_profile()
    return profile_from_dict(data)


# --------------------------------------------------------------------------
# Config precedence (arch 04 §Configuration)
# --------------------------------------------------------------------------
def _user_config_dir() -> Path:
    """The user-level config directory (``~/.config/boonyard``)."""
    return Path.home() / ".config" / "boonyard"


def resolve_profile_path(
    explicit: str | Path | None = None,
    *,
    env: dict[str, str] | None = None,
    cwd: str | Path | None = None,
) -> Path | None:
    """Resolve which ``boonyard.toml`` to use, highest precedence first (arch 04).

    Order: explicit argument > ``BOONYARD_PROFILE_PATH`` env var > a
    ``boonyard.toml`` beside the node (cwd, then ``<cwd>/node/``) > None
    (built-in defaults). Returns a path or None; callers pass the result to
    :func:`load_profile`.
    """
    env = os.environ if env is None else env
    if explicit is not None:
        return Path(explicit)
    if env.get("BOONYARD_PROFILE_PATH"):
        return Path(env["BOONYARD_PROFILE_PATH"])
    base = Path(cwd) if cwd is not None else Path.cwd()
    for candidate in (base / "boonyard.toml", base / DEFAULT_NODE_DIRNAME / "boonyard.toml"):
        if candidate.exists():
            return candidate
    return None


def resolve_db_path(
    explicit: str | Path | None = None,
    *,
    env: dict[str, str] | None = None,
    cwd: str | Path | None = None,
) -> Path:
    """Resolve which node file to use, highest precedence first (arch 04).

    Order: explicit argument > ``BOONYARD_DB_PATH`` env var > an existing
    ``<cwd>/node/journal.db`` or ``<cwd>/journal.db`` > the default
    ``<cwd>/node/journal.db``. The default's parent is created by ``init_db`` at
    init time, not here.
    """
    env = os.environ if env is None else env
    if explicit is not None:
        return Path(explicit)
    if env.get("BOONYARD_DB_PATH"):
        return Path(env["BOONYARD_DB_PATH"])
    base = Path(cwd) if cwd is not None else Path.cwd()
    node_default = base / DEFAULT_NODE_DIRNAME / DEFAULT_DB_FILENAME
    for candidate in (node_default, base / DEFAULT_DB_FILENAME):
        if candidate.exists():
            return candidate
    return node_default
