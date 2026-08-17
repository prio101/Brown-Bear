"""The memory graph: stored memory as nodes and edges (BB-301).

The dashboard's other pages answer "how much" — counts, rates, cost over time. None
of them answer "what is in there, and what is it connected to", which is the
question the stack exists to serve: Brown Bear is a memory shared by models on
separate machines, and a memory you cannot inspect is one you cannot trust.

Two kinds of edge, and the distinction matters more than it first looks:

  structural   Recorded fact. This exchange belongs to that project; this chunk
               came from that document. Read straight out of Chroma metadata,
               exact, and free.
  semantic     Computed relation. These two memories are near each other in vector
               space. Derived on demand from the stored embeddings, approximate,
               and the only edge type that costs a query.

Only structural edges are drawn up front. Semantic edges appear when a node is
expanded, because each one costs a nearest-neighbour query against the collection
and drawing them for every node at load would mean a query per document.

Deliberately excluded: logs. `query_logs`, `token_events`, `system_snapshots` and
`cache_samples` run to tens of thousands of rows against a few dozen memories, so
as nodes they would bury the thing being looked at roughly a thousand to one. They
stream instead — see `routers/logs.py`.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from brownbear.config import get_settings
from brownbear.connectors import chroma
from brownbear.gateway import similarity

logger = logging.getLogger(__name__)

#: Hard ceiling on nodes returned by the overview. The graph is unreadable long
#: before a browser struggles, so this is a legibility limit, not a performance
#: one — and it is reported in the response rather than silently applied.
MAX_NODES = 600

#: Documents read per collection when building the overview.
PAGE_SIZE = 500

#: Semantic neighbours returned when a node is expanded.
SIMILAR_LIMIT = 6

#: Default floor for drawing a similarity edge, overridable per request.
#:
#: Deliberately far below the cache's 0.95 cutoff: that threshold decides whether
#: an answer may be *served*, which is a far stronger claim than whether two
#: memories are worth drawing a line between.
#:
#: 0.60 rather than a rounder number because it was measured, not guessed. On this
#: corpus with nomic-embed-text, a memory's nearest genuine neighbour scores around
#: 0.66–0.69; an earlier 0.70 drew no edges at all and made the graph look
#: unconnected when it was not. The right value is corpus- and model-dependent,
#: which is exactly why the caller can override it rather than being held to a
#: constant chosen here.
SIMILARITY_EDGE_MIN = 0.60

#: Label lengths. Long enough to recognise a memory, short enough that a node does
#: not become a paragraph.
LABEL_CHARS = 90
PREVIEW_CHARS = 400


@dataclass
class Node:
    id: str
    kind: str  # collection | project | model | source | exchange | chunk
    label: str
    #: Structural degree, filled in once edges are known. Drives node size, so a
    #: hub is visible before anything is clicked.
    degree: int = 0
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Edge:
    source: str
    target: str
    #: contains | belongs_to | answered_by | derived_from | similar_to
    kind: str
    #: Only ever set on `similar_to`; None means the edge is a recorded fact.
    weight: float | None = None


def _truncate(text: str | None, limit: int) -> str:
    if not text:
        return ""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def node_id(kind: str, value: str) -> str:
    """Typed, stable node identity.

    Typed because a project and a model can share a name, and an untyped id would
    silently merge them into one node — which would then appear to connect two
    unrelated halves of the graph.
    """
    return f"{kind}:{value}"


class GraphBuilder:
    """Accumulates nodes and edges, de-duplicating both.

    A project appears on every exchange that belongs to it; without de-duplication
    the graph would carry one project node per exchange and no shared structure —
    which is precisely the structure worth seeing.
    """

    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.edges: dict[tuple[str, str, str], Edge] = {}
        self.truncated = False

    def add_node(self, node: Node) -> str:
        existing = self.nodes.get(node.id)
        if existing is None:
            if len(self.nodes) >= MAX_NODES:
                self.truncated = True
                return node.id
            self.nodes[node.id] = node
        elif not existing.meta and node.meta:
            existing.meta = node.meta
        return node.id

    def add_edge(self, source: str, target: str, kind: str, weight: float | None = None) -> None:
        # An edge to a node dropped by the cap would render as a line to nowhere.
        if source not in self.nodes or target not in self.nodes:
            return
        if source == target:
            return
        # Similarity is symmetric; store one orientation so A–B and B–A are one
        # edge rather than two overlapping lines.
        key = (
            (kind, *sorted((source, target)))
            if kind == "similar_to"
            else (kind, source, target)
        )
        if key in self.edges:
            return
        self.edges[key] = Edge(source=source, target=target, kind=kind, weight=weight)

    def result(self) -> dict[str, Any]:
        for edge in self.edges.values():
            for endpoint in (edge.source, edge.target):
                if endpoint in self.nodes:
                    self.nodes[endpoint].degree += 1
        return {
            "nodes": [asdict(n) for n in self.nodes.values()],
            "edges": [asdict(e) for e in self.edges.values()],
            "truncated": self.truncated,
            "limits": {"max_nodes": MAX_NODES, "page_size": PAGE_SIZE},
        }


def _add_exchange(builder: GraphBuilder, doc: dict[str, Any], collection_node: str) -> None:
    """One conversation: the memory, plus the project and model that scope it."""
    meta = doc.get("metadata") or {}
    prompt = meta.get("prompt") or ""
    identifier = node_id("exchange", str(doc.get("id")))

    builder.add_node(
        Node(
            id=identifier,
            kind="exchange",
            label=_truncate(prompt, LABEL_CHARS) or "(no prompt recorded)",
            meta={
                "project": meta.get("project"),
                "model": meta.get("model"),
                "created_at": meta.get("created_at"),
                # False here is why a hit was refused despite a high score, so it
                # belongs on the node rather than only in the detail panel.
                "cacheable": meta.get("cacheable", True),
                "stale_after": meta.get("stale_after"),
                "answer_preview": _truncate(doc.get("document"), PREVIEW_CHARS),
            },
        )
    )
    builder.add_edge(collection_node, identifier, "contains")

    if project := meta.get("project"):
        pid = builder.add_node(Node(id=node_id("project", str(project)), kind="project", label=str(project)))
        builder.add_edge(identifier, pid, "belongs_to")
    if model := meta.get("model"):
        mid = builder.add_node(Node(id=node_id("model", str(model)), kind="model", label=str(model)))
        builder.add_edge(identifier, mid, "answered_by")


def _add_chunk(builder: GraphBuilder, doc: dict[str, Any], collection_node: str) -> None:
    """One knowledge chunk, under the document it was split from."""
    meta = doc.get("metadata") or {}
    identifier = node_id("chunk", str(doc.get("id")))
    source = meta.get("source")
    project = meta.get("project")

    builder.add_node(
        Node(
            id=identifier,
            kind="chunk",
            label=_truncate(doc.get("document"), LABEL_CHARS) or "(empty chunk)",
            meta={
                "project": project,
                "source": source,
                "chunk_index": meta.get("chunk_index"),
                "chunk_count": meta.get("chunk_count"),
                "created_at": meta.get("created_at"),
                "text_preview": _truncate(doc.get("document"), PREVIEW_CHARS),
            },
        )
    )
    builder.add_edge(collection_node, identifier, "contains")

    if source:
        # Scoped by project: two repositories may both hold a README.md, and
        # merging them would invent a relationship that does not exist.
        sid = builder.add_node(
            Node(
                id=node_id("source", f"{project or 'default'}/{source}"),
                kind="source",
                label=str(source),
                meta={"project": project, "chunk_count": meta.get("chunk_count")},
            )
        )
        builder.add_edge(identifier, sid, "derived_from")
        if project:
            pid = builder.add_node(
                Node(id=node_id("project", str(project)), kind="project", label=str(project))
            )
            builder.add_edge(sid, pid, "belongs_to")


async def build_overview() -> dict[str, Any]:
    """The whole memory as a structural graph.

    No semantic edges: one nearest-neighbour query per document would turn opening
    a page into hundreds of vector searches. They are added per node on expand.
    """
    settings = get_settings()
    builder = GraphBuilder()

    for name, adder in (
        (settings.conversations_collection, _add_exchange),
        (settings.knowledge_collection, _add_chunk),
    ):
        collection = await chroma.get_collection(name)
        if not collection:
            continue
        cid = str(collection.get("id"))
        collection_node = builder.add_node(
            Node(
                id=node_id("collection", name),
                kind="collection",
                label=name,
                meta={"chroma_id": cid, "role": (collection.get("metadata") or {}).get("role")},
            )
        )
        try:
            documents = await chroma.get_documents(cid, limit=PAGE_SIZE)
        except Exception:  # noqa: BLE001
            # One unreadable collection must not blank the whole graph; the other
            # collection is still worth showing.
            logger.exception("could not read collection %s for the graph", name)
            continue
        if len(documents) >= PAGE_SIZE:
            builder.truncated = True
        for doc in documents:
            adder(builder, doc, collection_node)

    return builder.result()


def _parse(identifier: str) -> tuple[str, str]:
    kind, _, value = identifier.partition(":")
    return kind, value


async def _semantic_neighbours(
    builder: GraphBuilder,
    identifier: str,
    kind: str,
    value: str,
    min_similarity: float = SIMILARITY_EDGE_MIN,
) -> list[dict[str, Any]]:
    """Nearest stored memories to this one, as `similar_to` edges.

    Fetches the node's own vector rather than re-embedding its text: the stored
    embedding is what every other score in the system was computed against, and
    re-deriving it would compare against a subtly different point.
    """
    settings = get_settings()
    name = settings.conversations_collection if kind == "exchange" else settings.knowledge_collection
    collection = await chroma.get_collection(name)
    if not collection:
        return []
    cid = str(collection.get("id"))
    space = chroma.collection_space(collection)

    rows = await chroma.get_documents(cid, ids=[value], with_embeddings=True, limit=1)
    if not rows or not rows[0].get("embedding"):
        return []

    hits = await chroma.query(cid, embedding=rows[0]["embedding"], n_results=SIMILAR_LIMIT + 1)
    found: list[dict[str, Any]] = []
    for hit in hits:
        if hit.get("id") == value:
            continue  # itself, always the nearest
        score = similarity(hit.get("distance"), space)
        if score is None or score < min_similarity:
            continue
        add = _add_exchange if kind == "exchange" else _add_chunk
        collection_node = builder.add_node(
            Node(id=node_id("collection", name), kind="collection", label=name)
        )
        add(builder, hit, collection_node)
        neighbour = node_id(kind, str(hit.get("id")))
        builder.add_edge(identifier, neighbour, "similar_to", weight=score)
        found.append({"id": neighbour, "score": score})
    return found


async def expand(
    identifier: str, min_similarity: float = SIMILARITY_EDGE_MIN
) -> dict[str, Any]:
    """One node with its immediate neighbourhood.

    Structural neighbours for every kind; semantic ones as well for the two kinds
    that have a vector. A node with no neighbours returns itself and an empty edge
    list rather than 404 — an isolated memory is a real and interesting state, not
    a missing one.
    """
    settings = get_settings()
    kind, value = _parse(identifier)
    builder = GraphBuilder()
    semantic: list[dict[str, Any]] = []

    if kind in {"exchange", "chunk"}:
        name = (
            settings.conversations_collection
            if kind == "exchange"
            else settings.knowledge_collection
        )
        collection = await chroma.get_collection(name)
        if not collection:
            return {"node": None, **builder.result(), "similar": []}
        cid = str(collection.get("id"))
        rows = await chroma.get_documents(cid, ids=[value], limit=1)
        if not rows:
            return {"node": None, **builder.result(), "similar": []}

        collection_node = builder.add_node(
            Node(id=node_id("collection", name), kind="collection", label=name)
        )
        (_add_exchange if kind == "exchange" else _add_chunk)(builder, rows[0], collection_node)
        try:
            semantic = await _semantic_neighbours(
                builder, identifier, kind, value, min_similarity
            )
        except Exception:  # noqa: BLE001
            # Structural neighbours are still worth returning; the caller sees an
            # empty `similar` rather than an error page.
            logger.exception("similarity expansion failed for %s", identifier)

    elif kind in {"project", "model", "source", "collection"}:
        # Grouping nodes: re-read the collections filtered to this node's members.
        # A whole Chroma `where` clause, not a bare operator — `{"$eq": x}` without
        # its field name filters nothing and quietly returns the entire collection.
        if kind == "project":
            where: dict[str, Any] | None = {"project": {"$eq": value}}
        elif kind == "model":
            where = {"model": {"$eq": value}}
        elif kind == "source":
            # A source id is `project/filename`; the stored metadata holds only the
            # filename, so strip the scope back off before matching.
            where = {"source": {"$eq": value.split("/", 1)[-1]}}
        else:
            where = None

        for name, adder in (
            (settings.conversations_collection, _add_exchange),
            (settings.knowledge_collection, _add_chunk),
        ):
            if kind == "model" and name == settings.knowledge_collection:
                continue  # documents carry no model; a model has no chunks
            if kind == "source" and name == settings.conversations_collection:
                continue
            if kind == "collection" and name != value:
                continue
            collection = await chroma.get_collection(name)
            if not collection:
                continue
            cid = str(collection.get("id"))
            collection_node = builder.add_node(
                Node(id=node_id("collection", name), kind="collection", label=name)
            )
            try:
                documents = await chroma.get_documents(cid, limit=PAGE_SIZE, where=where)
            except Exception:  # noqa: BLE001
                logger.exception("could not expand %s in %s", identifier, name)
                continue
            for doc in documents:
                adder(builder, doc, collection_node)

    payload = builder.result()
    node = next((n for n in payload["nodes"] if n["id"] == identifier), None)
    return {"node": node, **payload, "similar": semantic}
