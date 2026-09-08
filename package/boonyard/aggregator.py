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

A node that cannot serve a v3 read is **skipped, not raised** (ADR-0003, dated
clarification 2026-08-24): one v2-schema straggler in the registry used to take
down reads across every node in the union (boonyard #76 Finding 2). Capture,
don't crash — the skip comes back as a warning instead.
"""

import logging
import re
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

from .meter import collect_rows, default_meter_path, summarize
from .profile import _safe_load_toml
from .query import (
    _ENTRY_COLS,
    _coerce_today,
    _dated_entry_rows,
    _dates_envelope,
    _row_to_entry,
    node_info,
)
from .query import search_text as _node_search_text

_log = logging.getLogger("boonyard")

# Safe margin below SQLite's default SQLITE_MAX_ATTACHED (10).
_MAX_ATTACH = 8
# Node names become SQL identifiers (ATTACH ... AS "<name>"); constrain them.
#
# ⚠ HYPHENS ARE ALLOWED (2026-09-07, ADR-0014). They have to be: ADR-0008 slugs are
# `[a-z0-9-]+`, so every hosted node — `test-0`, and every wall after the migration
# (`mycelium-sky`, `tea-guru`) — carries one, and the account door builds an
# Aggregator over exactly those slugs. Rejecting them made the account door raise a
# ValueError on any real account, which is how this was found: the tests used
# hyphen-free fixture names and hid it.
#
# It is safe because every interpolation of a name in this module is already quoted —
# `ATTACH DATABASE ? AS "{name}"`, `FROM "{name}".entry`, `SELECT '{name}' AS source`
# — and this charset still admits no quote, backslash, space, dot or semicolon, so
# there is nothing to break out of. The `[nodes]` table in an umbrella.toml keeps
# using underscore keys by its own convention; that convention is now a preference,
# not a constraint.
_IDENT = re.compile(r"^[A-Za-z0-9_-]+$")

# scope may be None / 'all' / 'current' / a name / a list of names.
Scope = str | Sequence[str] | None


class AggregatorConfigError(ValueError):
    """The configuration names a node that cannot be served — a wrong config, not a sick node.

    Subclasses ``ValueError`` deliberately: the MCP layer already turns a
    ``ValueError`` into a validation error carrying the message verbatim, so this
    reaches a model as the sentence below rather than as "internal error".

    Example:
        AggregatorConfigError("node 'umbrella' is configured at a path that does not exist")
    """


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
                raise ValueError(f"invalid node name {name!r}: use [A-Za-z0-9_-] only")
        self._nodes = dict(nodes)

    # -- scope + connection plumbing ---------------------------------------
    def nodes(self) -> dict[str, str]:
        """The configured ``{name: path}`` map (a copy)."""
        return dict(self._nodes)

    def _resolve_scope(self, scope: Scope) -> list[str]:
        """Scope -> node names. An unknown NAME still raises: that is a caller
        error, not an environment failure (a broken node is the latter, _probe)."""
        if scope is None or scope in ("all", "current"):
            return list(self._nodes)
        names = [scope] if isinstance(scope, str) else list(scope)
        for name in names:
            if name not in self._nodes:
                raise ValueError(f"unknown node in scope: {name!r}")
        return names

    def _probe(self, name: str) -> str | None:
        """Why this node can't be read, or None if it can (ADR-0003 clarification).

        Cheap and per-call: one open, one ``sqlite_master`` lookup. Per-call so a
        node that comes back healthy is picked up without restarting a standing
        MCP service. Only opens files that already exist, so probing never
        creates a stray node file.

        Deliberately NOT ``db.connect()``: that applies ``PRAGMA journal_mode =
        WAL`` before ``query_only``, which would try to *modify* a file we have
        just decided we may not understand. A probe must never write to the thing
        it is probing.
        """
        path = self._nodes[name]
        if not Path(path).exists():
            return f"node file not found: {path}"
        try:
            conn = sqlite3.connect(path)
            try:
                conn.execute("PRAGMA query_only = ON")
                row = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') "
                    "AND name = 'entry'"
                ).fetchone()
            finally:
                conn.close()
        except sqlite3.Error as exc:  # not a database, locked, corrupt...
            return f"unreadable: {exc}"
        if row is None:
            return "no v3 'entry' table (pre-v3 schema or not a boonyard node)"
        return None

    def _healthy_scope(self, scope: Scope) -> tuple[list[str], list[dict]]:
        """Resolve scope, then drop the nodes that can't serve a read.

        Returns ``(healthy_names, warnings)``. A node that is PRESENT but cannot be
        read degrades the union; it never kills it (boonyard #76 Finding 2 — one v2
        node crashed reads across all six). The warning names the node and the
        reason, so the failure stays loud somewhere: a reader that silently returns
        nothing is the ``visit_watch`` failure (jrhood #174), not a fix.

        ⚠ **A PATH THAT DOES NOT EXIST RAISES** (2026-09-08, migration order §1.5d).
        The two are different faults and only one of them is the node's. A missing
        file is the *configuration* lying about what this door serves, and eleven of
        the thirteen readers return a bare list with nowhere to put a warning — so a
        stale path made a whole wall vanish from every spanning read with **no marker
        at all**, and a seat obeying the read law ("search before you assert")
        concluded the topic was never recorded and appended a contradicting entry to
        an append-only store. That damage cannot be undone, only corrected. #76's law
        is preserved exactly where #76 lived — a v2/corrupt node still degrades — and
        tightened only for the case #76 never covered.
        """
        healthy: list[str] = []
        warnings: list[dict] = []
        for name in self._resolve_scope(scope):
            path = self._nodes[name]
            if not Path(path).exists():
                raise AggregatorConfigError(
                    f"node {name!r} is configured at a path that does not exist: {path}. "
                    "A union that silently drops a wall is a wrong answer, not a slower "
                    "one — fix the registry entry or remove the node."
                )
            reason = self._probe(name)
            if reason is None:
                healthy.append(name)
                continue
            warnings.append({"kind": "node_skipped", "node": name, "detail": reason})
            _log.warning("node %r skipped: %s", name, reason)
        return healthy, warnings

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
        names, _ = self._healthy_scope(scope)
        where = "WHERE (? IS NULL OR agent = ?) AND (? IS NULL OR entry_type = ?)"
        rows = self._collect_entries(names, where, [agent, agent, entry_type, entry_type], "", [])
        rows.sort(key=lambda r: (r["timestamp"], r["id"]), reverse=True)
        return [_row_to_entry(r, source=r["source"]) for r in rows[:limit]]

    def by_id(self, entry_id: int, *, scope: Scope = None) -> dict | None:
        """The first entry with this (node-local) id in scope order, or None."""
        for name in self._healthy_scope(scope)[0]:
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
        names, _ = self._healthy_scope(scope)
        rows = self._collect_entries(
            names, "WHERE id = ? OR related_id = ?", [root_id, root_id], "", []
        )
        rows.sort(key=lambda r: (r["source"], r["id"]))
        return [_row_to_entry(r, source=r["source"]) for r in rows]

    def search_by_tag(self, tag: str, limit: int = 20, *, scope: Scope = None) -> list[dict]:
        """Substring tag match across scope, newest-first."""
        names, _ = self._healthy_scope(scope)
        rows = self._collect_entries(names, "WHERE tags LIKE ?", [f"%{tag}%"], "", [])
        rows.sort(key=lambda r: (r["timestamp"], r["id"]), reverse=True)
        return [_row_to_entry(r, source=r["source"]) for r in rows[:limit]]

    def search_by_tag_exact(self, tag: str, limit: int = 20, *, scope: Scope = None) -> list[dict]:
        """Exact tag equality (via ``entry_tag``) across scope, newest-first."""
        names, _ = self._healthy_scope(scope)
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
        for name in self._healthy_scope(scope)[0]:
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
        names, _ = self._healthy_scope(scope)
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
        names, _ = self._healthy_scope(scope)
        totals = self._aggregate_counts(
            names, 'SELECT agent, COUNT(*) AS n FROM "{node}".entry GROUP BY agent', []
        )
        return sorted(
            ({"agent": a, "count": n} for a, n in totals.items()),
            key=lambda x: (-x["count"], x["agent"]),
        )

    def list_entry_types(self, *, scope: Scope = None) -> list[dict]:
        """Unioned entry_type counts across scope."""
        names, _ = self._healthy_scope(scope)
        totals = self._aggregate_counts(
            names, 'SELECT entry_type, COUNT(*) AS n FROM "{node}".entry GROUP BY entry_type', []
        )
        return sorted(
            ({"entry_type": e, "count": n} for e, n in totals.items()),
            key=lambda x: (-x["count"], x["entry_type"]),
        )

    def list_nodes(self) -> list[dict]:
        """Metadata for each configured node (name, slug, counts, timestamps).

        Also the health surface: a node that fails :meth:`_probe` is listed with
        ``healthy=False`` and the reason in ``warning`` rather than taking the
        whole listing down with it. This is how a cloud seat sees a bad node.
        """
        out = []
        for slug, path in self._nodes.items():
            reason = self._probe(slug)
            if reason is not None:
                out.append(
                    {
                        "name": slug,
                        "slug": slug,
                        "created_at": None,
                        "entry_count": None,
                        "last_write_at": None,
                        "healthy": False,
                        "warning": reason,
                    }
                )
                continue
            info = node_info(db_path=path)
            out.append(
                {
                    "name": info["name"] or slug,
                    "slug": slug,
                    "created_at": info["created_at"],
                    "entry_count": info["entry_count"],
                    "last_write_at": info["last_write_at"],
                    "healthy": True,
                    "warning": None,
                }
            )
        return out

    def read_stats(
        self,
        within_days: int = 7,
        *,
        today: date | str | None = None,
        scope: Scope = None,
    ) -> dict:
        """Read-vs-write traffic across scope, unioned from each node's meter sidecar.

        Same envelope as :func:`boonyard.meter.read_stats`. Each node meters itself
        into its own ``meter.db``; this merges them. A node that cannot be read, or
        that has no meter yet, contributes a warning instead of an exception —
        the ADR-0003 degrade-don't-crash path, applied to telemetry.

        Example:
            agg.read_stats(7, scope="all")["totals"]["ratio"]
        """
        day = _coerce_today(today)
        since = day - timedelta(days=max(within_days, 1) - 1)
        names, warnings = self._healthy_scope(scope)
        rows: list[dict] = []
        for name in names:
            node_rows, warning = collect_rows(
                default_meter_path(self._nodes[name]), since, day, source=name
            )
            rows.extend(node_rows)
            if warning is not None:
                warnings.append(warning)
        return summarize(rows, within_days, since, day, warnings)

    def upcoming_dates(
        self,
        within_days: int = 45,
        *,
        prefix: str = "killdate",
        today: date | str | None = None,
        scope: Scope = None,
    ) -> dict:
        """The kill-date register across scope, merged and re-sorted by date.

        Same envelope as :func:`boonyard.query.upcoming_dates`, with ``node`` set
        to each row's registry slug and with any skipped node reported in
        ``warnings`` alongside malformed tags. Overdue dates sort to the top and
        never drop out.

        Example:
            agg.upcoming_dates(45, scope="all")["dates"]
        """
        day = _coerce_today(today)
        names, warnings = self._healthy_scope(scope)
        # tags is the CSV column; the LIKE is a prefilter and _dated_entry_rows is
        # the authority. Goes through _collect_entries — no second ATTACH path.
        rows = self._collect_entries(names, "WHERE tags LIKE ?", [f"%{prefix}:%"], "", [])
        dates: list[dict] = []
        for row in rows:
            entry_rows, entry_warnings = _dated_entry_rows(
                _row_to_entry(row, source=row["source"]),
                prefix,
                day,
                within_days,
                row["source"],
            )
            dates.extend(entry_rows)
            warnings.extend(entry_warnings)
        return _dates_envelope(day, within_days, prefix, dates, warnings)


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
    # ⚠ AN UNREADABLE REGISTRY IS AN ENVIRONMENT ERROR, NOT AN EMPTY ONE (2026-09-08,
    # migration order §1.5c). `_safe_load_toml(...) or {}` turned a missing or renamed
    # umbrella.toml into a zero-node Aggregator that CONSTRUCTS SUCCESSFULLY, and every
    # reader then returned clean empty success at exit 0 — including `upcoming_dates`,
    # which would report "no dates" for every overdue kill-date on all six walls,
    # indefinitely, from the exact reader built so a past date can never drop out. With
    # zero nodes `_healthy_scope` never probes, so even the two readers that do carry
    # warnings return `warnings: []`. An empty [nodes] table raises for the same reason:
    # it produces the identical zero-node door, and nobody writes one on purpose.
    path = Path(config_path)
    if not path.exists():
        raise AggregatorConfigError(f"aggregator config not found: {path}")
    data = _safe_load_toml(path)
    if data is None:
        raise AggregatorConfigError(f"aggregator config is not readable TOML: {path}")
    table = data.get("nodes")
    if table is None:
        raise AggregatorConfigError(f"aggregator config has no [nodes] table: {path}")
    if not table:
        raise AggregatorConfigError(f"aggregator config's [nodes] table is empty: {path}")
    node_map = {k: str(v) for k, v in table.items()}
    return Aggregator(node_map)
