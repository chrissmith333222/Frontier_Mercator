"""
scripts/knowledge/relationship_graph.py

Builds a network/relationship graph of the actors active in one country --
the Palantir-Gotham-style "entities as linked nodes" view, as opposed to
just map pins. Computed live from the already-loaded merged_dataset.json
(no precomputed artifact needed, unlike the AI assessments/scorecards --
networkx and plotly are lightweight, safe to run inside the deployed
Streamlit app, unlike the anthropic/voyageai backend-only pipeline).

Usage (as a module):
    from scripts.knowledge.relationship_graph import build_country_graph, build_plotly_figure
    graph = build_country_graph(events, "Kenya")
    fig = build_plotly_figure(graph)
"""

from collections import Counter

import networkx as nx
import plotly.graph_objects as go


def build_country_graph(events: list[dict], country: str, top_n: int = 15) -> dict:
    """Returns {"country", "nodes", "edges"} describing the actor
    ecosystem for one country -- which financiers/actors are active,
    weighted by event count, restricted to the top_n most-connected
    actors to keep the visualization readable. Node layout positions are
    precomputed here (spring layout) so the plotting step is pure
    rendering, no graph-theory logic."""
    actor_counts = Counter()
    actor_categories: dict[str, set] = {}
    for event in events:
        if event.get("country") != country:
            continue
        for actor in event.get("actors") or []:
            name = actor.get("name")
            # GDELT frequently tags the country itself as one of the
            # "actors" in a political/other event (e.g. actor="Kenya" on
            # a Kenya-country event) -- without this filter, the country
            # node ends up with a meaningless self-referential edge to an
            # identically-named actor node that dominates the graph
            # (in practice, often the single highest-weighted "actor").
            if not name or name.strip().lower() == country.strip().lower():
                continue
            actor_counts[name] += 1
            actor_categories.setdefault(name, set()).add(event.get("event_category"))

    top_actors = actor_counts.most_common(top_n)

    graph = nx.Graph()
    graph.add_node(country, node_type="country")
    for name, count in top_actors:
        graph.add_node(name, node_type="actor")
        graph.add_edge(country, name, weight=count)

    if len(graph.nodes) <= 1:
        return {"country": country, "nodes": [], "edges": []}

    # 3D layout (Chris: keep the relationship graph "3D, movable, zoomable
    # ... across 3 dimensions, not just 2") -- networkx's spring_layout
    # supports an arbitrary dim, so this is the same force-directed physics
    # as before, just solved in one more axis. Plotly's Scatter3d gives
    # free mouse-driven rotate/pan/zoom natively, no extra code needed.
    positions = nx.spring_layout(graph, seed=42, k=0.9, dim=3)

    nodes = [
        {
            "id": node_id,
            "node_type": graph.nodes[node_id]["node_type"],
            "x": float(positions[node_id][0]),
            "y": float(positions[node_id][1]),
            "z": float(positions[node_id][2]),
            "categories": sorted(actor_categories.get(node_id, set())) if node_id != country else [],
            "event_count": actor_counts.get(node_id, 0) if node_id != country else sum(actor_counts.values()),
        }
        for node_id in graph.nodes
    ]
    edges = [
        {"source": u, "target": v, "weight": graph.edges[u, v]["weight"]}
        for u, v in graph.edges
    ]
    return {"country": country, "nodes": nodes, "edges": edges}


def build_plotly_figure(graph: dict) -> go.Figure:
    """Renders a country actor-relationship graph as a 3D Plotly figure --
    edge lines first (so they sit behind), then nodes as a Scatter3d trace
    sized/colored by node type and connection weight. Mouse drag rotates,
    scroll/pinch zooms, and drag-to-pan all work natively via Plotly's 3D
    scene -- no custom interaction code needed."""
    fig = go.Figure()

    node_lookup = {n["id"]: n for n in graph["nodes"]}
    for edge in graph["edges"]:
        src, tgt = node_lookup[edge["source"]], node_lookup[edge["target"]]
        fig.add_trace(go.Scatter3d(
            x=[src["x"], tgt["x"]], y=[src["y"], tgt["y"]], z=[src["z"], tgt["z"]],
            mode="lines",
            line=dict(width=min(1 + edge["weight"] / 5, 8), color="rgba(154, 165, 180, 0.35)"),
            hoverinfo="none", showlegend=False,
        ))

    country_nodes = [n for n in graph["nodes"] if n["node_type"] == "country"]
    actor_nodes = [n for n in graph["nodes"] if n["node_type"] == "actor"]

    if actor_nodes:
        fig.add_trace(go.Scatter3d(
            x=[n["x"] for n in actor_nodes], y=[n["y"] for n in actor_nodes], z=[n["z"] for n in actor_nodes],
            mode="markers+text",
            marker=dict(
                size=[8 + min(n["event_count"], 30) for n in actor_nodes],
                color="#FFB03B", line=dict(width=1, color="#060B14"),
            ),
            text=[n["id"] for n in actor_nodes], textposition="top center",
            textfont=dict(size=9, color="#EDEFF4"),
            hovertext=[f"{n['id']}<br>{n['event_count']} events<br>{', '.join(n['categories'])}" for n in actor_nodes],
            hoverinfo="text", showlegend=False,
        ))

    if country_nodes:
        fig.add_trace(go.Scatter3d(
            x=[n["x"] for n in country_nodes], y=[n["y"] for n in country_nodes], z=[n["z"] for n in country_nodes],
            mode="markers+text",
            marker=dict(size=14, color="#6E8FC7", line=dict(width=2, color="#EDEFF4"), symbol="diamond"),
            text=[n["id"] for n in country_nodes], textposition="bottom center",
            textfont=dict(size=12, color="#EDEFF4"),
            hoverinfo="text", showlegend=False,
        ))

    axis_style = dict(visible=False, showbackground=False)
    fig.update_layout(
        template="plotly_dark", paper_bgcolor="#060B14",
        scene=dict(
            xaxis=axis_style, yaxis=axis_style, zaxis=axis_style,
            bgcolor="#060B14",
        ),
        height=600, margin=dict(l=10, r=10, t=10, b=10),
    )
    return fig
