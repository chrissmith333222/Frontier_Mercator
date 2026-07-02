"""
tests/test_relationship_graph.py

Tests the relationship graph builder's data logic (top-N selection,
node/edge structure) and confirms the Plotly figure builder runs without
error on real graph output -- no dashboard or live data needed.

Usage:
    python -m pytest tests/test_relationship_graph.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.knowledge.relationship_graph import build_country_graph, build_plotly_figure

FIXTURE_EVENTS = [
    {"country": "Kenya", "event_category": "investment", "actors": [{"name": "China Eximbank", "type": "chinese_financier"}]},
    {"country": "Kenya", "event_category": "investment", "actors": [{"name": "China Eximbank", "type": "chinese_financier"}]},
    {"country": "Kenya", "event_category": "conflict", "actors": [{"name": "Government of Kenya", "type": "state_forces"}]},
    {"country": "Kenya", "event_category": "investment", "actors": [{"name": "U.S. International Development Finance Corporation", "type": "us_financier"}]},
    {"country": "Mozambique", "event_category": "conflict", "actors": [{"name": "Government of Mozambique", "type": "state_forces"}]},
    {"country": "Kenya", "event_category": "investment", "actors": []},  # no actors, should be skipped without crashing
]


def test_build_country_graph_filters_by_country():
    graph = build_country_graph(FIXTURE_EVENTS, "Kenya")
    actor_ids = {n["id"] for n in graph["nodes"] if n["node_type"] == "actor"}
    assert "China Eximbank" in actor_ids
    assert "Government of Kenya" in actor_ids
    assert "Government of Mozambique" not in actor_ids  # different country
    print("✓ test_build_country_graph_filters_by_country passed")


def test_build_country_graph_weights_by_event_count():
    graph = build_country_graph(FIXTURE_EVENTS, "Kenya")
    eximbank_node = next(n for n in graph["nodes"] if n["id"] == "China Eximbank")
    assert eximbank_node["event_count"] == 2  # appeared in 2 events
    print("✓ test_build_country_graph_weights_by_event_count passed")


def test_build_country_graph_respects_top_n():
    events = [
        {"country": "Kenya", "event_category": "investment", "actors": [{"name": f"Actor {i}"}]}
        for i in range(20)
    ]
    graph = build_country_graph(events, "Kenya", top_n=5)
    actor_nodes = [n for n in graph["nodes"] if n["node_type"] == "actor"]
    assert len(actor_nodes) == 5
    print("✓ test_build_country_graph_respects_top_n passed")


def test_build_country_graph_empty_when_no_actors():
    graph = build_country_graph([{"country": "Kenya", "event_category": "investment", "actors": []}], "Kenya")
    assert graph["nodes"] == []
    assert graph["edges"] == []
    print("✓ test_build_country_graph_empty_when_no_actors passed")


def test_build_country_graph_excludes_country_named_as_its_own_actor():
    """GDELT frequently tags the country itself as an "actor" on its own
    events (e.g. actor name "Kenya" on a Kenya-country event) -- this
    should be filtered out, not create a meaningless self-referential
    country<->actor edge with an identically-named node."""
    events = [
        {"country": "Kenya", "event_category": "other", "actors": [{"name": "Kenya"}]},
        {"country": "Kenya", "event_category": "other", "actors": [{"name": "kenya"}]},  # case-insensitive
        {"country": "Kenya", "event_category": "investment", "actors": [{"name": "China Eximbank"}]},
    ]
    graph = build_country_graph(events, "Kenya")
    actor_ids = {n["id"] for n in graph["nodes"] if n["node_type"] == "actor"}
    assert "Kenya" not in actor_ids
    assert "kenya" not in actor_ids
    assert "China Eximbank" in actor_ids
    print("✓ test_build_country_graph_excludes_country_named_as_its_own_actor passed")


def test_build_country_graph_country_with_no_events():
    graph = build_country_graph(FIXTURE_EVENTS, "Nowhereland")
    assert graph["nodes"] == []
    print("✓ test_build_country_graph_country_with_no_events passed")


def test_build_plotly_figure_runs_without_error():
    graph = build_country_graph(FIXTURE_EVENTS, "Kenya")
    fig = build_plotly_figure(graph)
    assert fig is not None
    assert len(fig.data) > 0
    print("✓ test_build_plotly_figure_runs_without_error passed")


def test_build_plotly_figure_handles_empty_graph():
    fig = build_plotly_figure({"country": "Nowhereland", "nodes": [], "edges": []})
    assert fig is not None
    print("✓ test_build_plotly_figure_handles_empty_graph passed")


if __name__ == "__main__":
    test_functions = [v for k, v in list(globals().items()) if k.startswith("test_")]
    print(f"Running {len(test_functions)} tests...\n")
    failures = 0
    for test_fn in test_functions:
        try:
            test_fn()
        except AssertionError as e:
            failures += 1
            print(f"✗ {test_fn.__name__} FAILED: {e}")
    print(f"\n{len(test_functions) - failures}/{len(test_functions)} tests passed.")
    if failures:
        sys.exit(1)
