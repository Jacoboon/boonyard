"""The over-many reader — Umbrella mode (ADR-0003, arch 03).

An aggregator opens N node files **read-only** and unions their entries, tagging
each row with a ``source`` field naming the originating node. It never writes:
there are no write methods, and every connection sets ``PRAGMA query_only = ON``.

Implementation follows arch 03: a ``:memory:`` primary connection with each node
``ATTACH``-ed, then a ``UNION ALL`` across the attached ``entry`` tables. SQLite's
default ``SQLITE_MAX_ATTACHED`` is 10, so scopes larger than that are chunked and
merged in Python (arch 03 §Attached-DB limit).

Cross-node writes, threads, foreign keys, and transactions are out of scope by
design (arch 03 §What scope does NOT do): scope unions reads, nothing more.
"""

import re
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from .profile import _safe_load_toml
from .query import _ENTRY_COLS, _row_to_entry, node_info
from .query import search_text as _node_search_text

# Safe margin below SQLite's default SQLITE_MAX_ATTACHED (10).
_MAX_ATTACH = 8
# Node names become SQL identifiers (ATTACH ... AS "<name>"); constrain them.
_IDENT = re.compile(r"^[A-Za-z0-9_]+$")

# scope may be None / 'all' / 'current' / a name / a list of names.
Scope = str | Sequence[str] | None


def _chunks(items: list[str], size: int) -> Iterator[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


class Aggregator:
    """Reads across many nodes read-only, unioning results with a ``source`` field.

    Construct via :func:`aggregator` (from an umbrella.toml) or directly with a
    ``{name: path}`` mapping. Every reader accepts a ``scope`` (None/'all' = every
    configured node; a name; or a list of names).
    """

    def __init__(self, nodes: dict[str, str]):
        for name in nodes:
            if not _IDENT.match(name):
                raise ValueError(f"invalid node name {name!r}: use [A-Za-z0-9_] only")
        self._nodes = dict(nodes)

    # -- scope + connection plumbing ---------------------------------------
    def nodes(self) -> dict[str, str]:
        """The configured ``{name: path}`` map (a copy)."""
        return dict(self._nodes)

    def _resolve_scope(self, scope: Scope) -> list[str]:
        if scope is None or scope in ("all", "current"):
            return list(self._nodes)
        names = [scope] if isinstance(scope, str) else list(scope)
        for name in names:
            if name not in self._nodes:
                raise ValueError(f"unknown node in scope: {name!r}")
        return names

    @contextmanager
    def _attach(self, names: list[str]) -> Iterator[sqlite3.Connection]:
        """A read-only ``:memory:`` connection with each named node attached."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            for name in names:
                conn.execute(f'ATTACH DATABASE ? AS "{name}"', (self._nodes[name],))
            conn.execute("PRAGMA query_only = ON")  # writes physically impossible
            yield conn
        finally:
            conn.close()

    def _union_entries(self, names: list[str], where: str, per_node_params: list) -> str:
        """Build a ``UNION ALL`` of ``SELECT source, <cols> FROM "<n>".entry`` legs."""
        legs = [
            f"SELECT '{name}' AS source, {_ENTRY_COLS} FROM \"{name}\".entry {where}"
            for name in names
        ]
        return " UNION ALL ".join(legs)

    def _collect_entries(
        self, names: list[str], where: str, node_params: list, tail: str, tail_params: list
    ) -> list[sqlite3.Row]:
        """Run an entry UNION per attach-chunk and concatenate the rows."""
        rows: list[sqlite3.Row] = []
        for chunk in _chunks(names, _MAX_ATTACH):
            params: list = []
            for _ in chunk:
                params.extend(node_params)
            sql = self._union_entries(chunk, where, node_params) + " " + tail
            with self._attach(chunk) as conn:
                rows.extend(conn.execute(sql, params + tail_params).fetchall())
        return rows

    # -- readers -----------------------------------------------------------
    def recent(
        self,
        limit: int = 20,
        agent: str | None = None,
        entry_type: str | None = None,
        *,
        scope: Scope = None,
    ) -> list[dict]:
        """Newest-first across scope, optionally filtered by agent / entry_type."""
        names = self._resolve_scope(scope)
        where = "WHERE (? IS NULL OR agent = ?) AND (? IS NULL OR entry_type = ?)"
        rows = self._collect_entries(names, where, [agent, agent, entry_type, entry_type], "", [])
        rows.sort(key=lambda r: (r["timestamp"], r["id"]), reverse=True)
        return [_row_to_entry(r, source=r["source"]) for r in rows[:limit]]

    def by_id(self, entry_id: int, *, scope: Scope = None) -> dict | None:
        """The first entry with this (node-local) id in scope order, or None."""
        for name in self._resolve_scope(scope):
            with self._attach([name]) as conn:
                row = conn.execute(
                    f"SELECT '{name}' AS source, {_ENTRY_COLS} FROM \"{name}\".entry WHERE id = ?",
                    (entry_id,),
                ).fetchone()
                if row is not None:
                    return _row_to_entry(row, source=name)
        return None

    def get_thread(self, root_id: int, *, scope: Scope = None) -> list[dict]:
        """Root + direct children across scope (threads are node-local; ADR-0004)."""
        names = self._resolve_scope(scope)
        rows = self._collect_entries(
            names, "WHERE id = ? OR related_id = ?", [root_id, root_id], "", []
        )
        rows.sort(key=lambda r: (r["source"], r["id"]))
        return [_row_to_entry(r, source=r["source"]) for r in rows]

    def search_by_tag(self, tag: str, limit: int = 20, *, scope: Scope = None) -> list[dict]:
        """Substring tag match across scope, newest-first."""
        names = self._resolve_scope(scope)
        rows = self._collect_entries(names, "WHERE tags LIKE ?", [f"%{tag}%"], "", [])
        rows.sort(key=lambda r: (r["timestamp"], r["id"]), reverse=True)
        return [_row_to_entry(r, source=r["source"]) for r in rows[:limit]]

    def search_by_tag_exact(self, tag: str, limit: int = 20, *, scope: Scope = None) -> list[dict]:
        """Exact tag equality (via ``entry_tag``) across scope, newest-first."""
        names = self._resolve_scope(scope)
        rows: list[sqlite3.Row] = []
        for chunk in _chunks(names, _MAX_ATTACH):
            legs, params = [], []
            for name in chunk:
                legs.append(
                    f"SELECT '{name}' AS source, e.{', e.'.join(_ENTRY_COLS.split(', '))} "
                    f'FROM "{name}".entry e JOIN "{name}".entry_tag t ON t.entry_id = e.id '
                    "WHERE t.tag = ?"
                )
                params.append(tag)
            sql = " UNION ALL ".join(legs)
            with self._attach(chunk) as conn:
                rows.extend(conn.execute(sql, params).fetchall())
        rows.sort(key=lambda r: (r["timestamp"], r["id"]), reverse=True)
        return [_row_to_entry(r, source=r["source"]) for r in rows[:limit]]

    def search_text(self, query: str, limit: int = 20, *, scope: Scope = None) -> list[dict]:
        """FTS5 search across scope. Raises ``ValueError`` on malformed FTS syntax.

        FTS5 ``MATCH`` doesn't compose cleanly across ATTACH (schema-qualified
        virtual tables don't parse), so this dogfoods the per-node reader and
        merges — each node opened read-only, results tagged with ``source``.
        """
        entries: list[dict] = []
        for name in self._resolve_scope(scope):
            for entry in _node_search_text(query, limit, db_path=self._nodes[name]):
                entry["source"] = name
                entries.append(entry)
        entries.sort(key=lambda e: (e["timestamp"], e["id"]), reverse=True)
        return entries[:limit]

    def _aggregate_counts(self, names: list[str], select_sql: str, params_per_node: list) -> dict:
        """Sum ``(key, count)`` rows of ``select_sql`` across attach-chunks."""
        totals: dict[str, int] = {}
        for chunk in _chunks(names, _MAX_ATTACH):
            legs, params = [], []
            for name in chunk:
                legs.append(select_sql.format(node=name))
                params.extend(params_per_node)
            sql = " UNION ALL ".join(legs)
            with self._attach(chunk) as conn:
                for row in conn.execute(sql, params):
                    totals[row[0]] = totals.get(row[0], 0) + row[1]
        return totals

    def list_tags(
        self, prefix: str | None = None, tree: bool = False, *, scope: Scope = None
    ) -> list[dict] | dict[str, list[dict]]:
        """The unioned tag menu across scope, counts summed, most-used first."""
        names = self._resolve_scope(scope)
        totals = self._aggregate_counts(
            names,
            'SELECT tag, COUNT(*) AS n FROM "{node}".entry_tag '
            "WHERE (? IS NULL OR tag LIKE ? || '%') GROUP BY tag",
            [prefix, prefix],
        )
        flat = sorted(
            ({"tag": t, "count": n} for t, n in totals.items()),
            key=lambda x: (-x["count"], x["tag"]),
        )
        if not tree:
            return flat
        grouped: dict[str, list[dict]] = {}
        for item in flat:
            grouped.setdefault(item["tag"].split("-", 1)[0], []).append(item)
        return grouped

    def list_agents(self, *, scope: Scope = None) -> list[dict]:
        """Unioned agent counts across scope."""
        names = self._resolve_scope(scope)
        totals = self._aggregate_counts(
            names, 'SELECT agent, COUNT(*) AS n FROM "{node}".entry GROUP BY agent', []
        )
        return sorted(
            ({"agent": a, "count": n} for a, n in totals.items()),
            key=lambda x: (-x["count"], x["agent"]),
        )

    def list_entry_types(self, *, scope: Scope = None) -> list[dict]:
        """Unioned entry_type counts across scope."""
        names = self._resolve_scope(scope)
        totals = self._aggregate_counts(
            names, 'SELECT entry_type, COUNT(*) AS n FROM "{node}".entry GROUP BY entry_type', []
        )
        return sorted(
            ({"entry_type": e, "count": n} for e, n in totals.items()),
            key=lambda x: (-x["count"], x["entry_type"]),
        )

    def list_nodes(self) -> list[dict]:
        """Metadata for each configured node (name, slug, counts, timestamps)."""
        out = []
        for slug, path in self._nodes.items():
            info = node_info(db_path=path)
            out.append(
                {
                    "name": info["name"] or slug,
                    "slug": slug,
                    "created_at": info["created_at"],
                    "entry_count": info["entry_count"],
                    "last_write_at": info["last_write_at"],
                }
            )
        return out


def aggregator(
    config_path: str | Path | None = None,
    *,
    nodes: dict[str, str] | None = None,
) -> Aggregator:
    """Build an :class:`Aggregator` from an umbrella.toml ``[nodes]`` table or a map.

    Example:
        agg = aggregator("~/.config/boonyard/umbrella.toml")
        for e in agg.recent(20):
            print(e["source"], e["content"])
    """
    if nodes is not None:
        return Aggregator(nodes)
    if config_path is None:
        raise ValueError("aggregator requires a config_path or a nodes mapping")
    data = _safe_load_toml(Path(config_path)) or {}
    node_map = {k: str(v) for k, v in data.get("nodes", {}).items()}
    return Aggregator(node_map)
