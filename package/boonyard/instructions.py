"""The package's readme for a model — served at ``initialize`` and by the ``instructions`` tool.

Professor's idea (boonyard #125): *"an 'instructions' command that every node will
serve the same … like a help or readme … one static command away."* The MCP spec's
``InitializeResult`` carries an optional ``instructions`` string for exactly this, and
a client that honours it hands the text to the model on every connect — a boot doc
that cannot be skipped because it arrives with the tool list (umbrella #228: rules
0-for-8, machinery 2-for-2).

Two rules hold this file together, and ``tests/test_instructions.py`` enforces both:

* **Every tool name in ``TOOL_DEFS`` appears verbatim in the text.** A tool added
  without a readme line fails CI. The tool lines are assembled from ``TOOL_DEFS``
  at import, so the only way to break the rule is to write a description that
  reads as nothing.
* **The whole text is at most ``MAX_BYTES``.** It is injected into a model's
  context on every connect; a readme that costs more than a few hundred tokens
  is a tax on every session.

The static half lives here; the node half (a per-node ``readme`` skill) is read
by the ``instructions`` tool in ``mcp.py``.
"""

MAX_BYTES = 3_500

_BODY = """\
BOONYARD NODE — how to use this memory (boonyard {version}).
A node is one append-only SQLite file of ENTRIES: timestamped text by a named agent, \
optionally threaded to an earlier entry (related_id) and tagged. Nothing is ever edited \
or deleted. A correction is a new entry that points at the old one.

THE READ LAW — search before you assert. search_text the nouns (full-text), \
search_by_tag or search_by_tag_exact for a tag, recent for the newest, get_thread for a \
root and its replies, by_id for one entry. Then cite the id you found, or say you \
searched and found nothing.

WRITING — log_entry(agent, entry_type, content, related_id?, tags?). tags is a \
comma-separated string ("decision, project-x"), lowercase-hyphen, never JSON. Put \
model:<your exact model name> in tags. related_id threads a reply or a correction to \
the entry it answers — thread whenever you are answering something. One entry per \
event, not a transcript. entry_type is one of the node's profile types{types}; unknown \
values warn and still insert.

REGISTERS — a tag killdate:YYYY-MM-DD or open:YYYY-MM-DD makes a dated row; \
upcoming_dates(prefix) reads them, overdue first, and never drops a past date. A \
retired row is retagged open-retired:YYYY-MM-DD (CLI only; retag is not a tool).

SKILLS — {skills}

READ HEAT — every read records the ids it returned (never the query); {heat}\
read_stats is the read/write meter.

IDS ARE NODE-LOCAL — #412 means nothing without its node: another node has its own \
#412. {nodearg}Cite an entry as #412@umbrella, and pass that slug back as node.

TOOLS (name — purpose):
{tools}

Call instructions for this node's own readme, if its people wrote one.
"""


def _clause(description: str) -> str:
    """The first clause of a tool description: up to the first period, ≤ 72 chars."""
    first = description.split(". ")[0].rstrip(".")
    return first if len(first) <= 72 else first[:69].rstrip() + "…"


def _requires_node(tool: dict) -> bool:
    """Does this door mark ``node`` as a REQUIRED argument on this tool?

    Example:
        _requires_node({"inputSchema": {"required": ["node"]}})  # -> True
    """
    return "node" in (tool.get("inputSchema") or {}).get("required", [])


def build(tool_defs: list[dict], version: str) -> str:
    """Assemble the readme from the tool definitions and the hand-written body.

    ⚠ EVERY SENTENCE THAT NAMES A TOOL IS DERIVED FROM ``tool_defs``, never hand-typed
    (2026-09-08). Three were prose and all three were wrong at some door: the SKILLS line
    named ``latest_skill`` and ``list_skills`` at the aggregate door, which serves neither;
    READ HEAT named ``ghosts`` the same way; and the node-local paragraph hand-listed four
    tools when the account door marks **nine**. A readme that names a tool the door refuses
    sends a model straight to an error — the defect ADR-0014 §11 removed from ``tools/list``,
    surviving in the text the model actually reads on every connect.

    Example:
        build(TOOL_DEFS, "3.5.0").startswith("BOONYARD NODE")
    """
    names = {t["name"] for t in tool_defs}
    lines = [f"  {t['name']} — {_clause(t['description'])}" for t in tool_defs]

    if "log_skill_revision" in names:
        skills = "log_skill_revision(slug, content, agent) appends a revision of a named skill"
        if "latest_skill" in names:
            skills += "; latest_skill(slug) returns the newest"
        if "list_skills" in names:
            skills += "; list_skills is the catalog"
        skills += (
            '. The slug "readme" is reserved for this node\'s own readme '
            "(tags: readme, instructions, agents)."
        )
    else:
        skills = "address a specific node to reach the skill tools; this door does not serve them."

    heat = "ghosts lists root entries nobody threaded to or read; " if "ghosts" in names else ""

    needs = sorted(t["name"] for t in tool_defs if _requires_node(t))
    nodearg = (
        'Every row names its node in "source", and this door requires node=<slug> on '
        f"{', '.join(needs)} (list_nodes gives the slugs). "
        if needs
        else "This door serves one node, so nothing here takes a node argument. "
    )
    types = " (node_info lists them)" if "node_info" in names else ""
    return _BODY.format(
        version=version,
        tools="\n".join(lines),
        skills=skills,
        heat=heat,
        nodearg=nodearg,
        types=types,
    )


def instructions_text(tool_defs: list[dict] | None = None) -> str:
    """The package readme for ONE door — the module default when none is given.

    ⚠ THE README IS PER DOOR, for the same reason ``tools/list`` is (ADR-0014 §11: a
    door advertises only what it can serve). The aggregate door serves 15 of the 20
    tools; a readme built from the module default would have taught a model about
    ``ghosts`` and ``node_info`` at a door that refuses them — a listing that sends the
    model to an error, which is the thing §11 removed from ``tools/list`` and would
    have left standing in the text the model actually reads.

    The default is assembled once and cached, because it is the common case and it is
    injected on every connect.
    """
    from . import __version__

    if tool_defs is not None:
        return build(tool_defs, __version__)
    global _CACHED
    if _CACHED is None:
        from .mcp import TOOL_DEFS

        _CACHED = build(TOOL_DEFS, __version__)
    return _CACHED


_CACHED: str | None = None


def __getattr__(name: str):
    # ``from boonyard.instructions import INSTRUCTIONS`` — assembled on first access so
    # this module never imports ``mcp`` at import time (mcp imports it lazily too).
    if name == "INSTRUCTIONS":
        return instructions_text()
    raise AttributeError(name)
