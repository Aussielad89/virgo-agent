"""End-to-end tests for the blackboard shared message space."""

from __future__ import annotations

import json
import threading

from blackboard import Blackboard, BoardEntry


def test_post_returns_monotonic_id():
    bb = Blackboard()
    a = bb.post("t/a", 1)
    b = bb.post("t/a", 2)
    assert b == a + 1


def test_get_latest_and_all():
    bb = Blackboard()
    bb.post("topic", "first")
    bb.post("topic", "second")
    assert bb.get("topic") == "second"
    assert bb.get("topic", latest=False) == ["first", "second"]
    assert bb.get("missing") is None


def test_get_entry_returns_full_object():
    bb = Blackboard()
    eid = bb.post("topic", {"x": 1}, source="agent1", phase="discover")
    entry = bb.get_entry("topic")
    assert isinstance(entry, BoardEntry)
    assert entry.entry_id == eid
    assert entry.source == "agent1"
    assert entry.phase == "discover"


def test_search_by_regex():
    bb = Blackboard()
    bb.post("network/hosts", ["10.0.0.1"], source="scanner")
    bb.post("network/ports", [22, 80], source="scanner")
    hits = bb.search(r"hosts")
    assert len(hits) == 1
    assert hits[0].topic == "network/hosts"
    # content match
    assert len(bb.search(r"10\.0\.0\.1")) == 1


def test_wait_for_unblocks_and_times_out():
    bb = Blackboard()
    result = bb.wait_for("never", timeout=0.1)
    assert result is None

    evt = threading.Event()

    def producer():
        evt.wait(0.2)
        bb.post("ready", "go")

    t = threading.Thread(target=producer)
    t.start()
    evt.set()
    out = bb.wait_for("ready", timeout=2.0)
    t.join()
    assert out == "go"


def test_clear_topic_and_all():
    bb = Blackboard()
    bb.post("a", 1)
    bb.post("b", 2)
    bb.clear("a")
    assert bb.get("a") is None
    assert bb.get("b") == 2
    bb.clear()
    assert bb.topics() == []


def test_serialization_round_trip():
    bb = Blackboard()
    bb.post("x", {"k": "v"}, source="s")
    data = json.loads(bb.to_json())
    assert "x" in data["topics"]
    assert data["topics"]["x"][0]["content"] == {"k": "v"}

    # Replaying from a dict is supported via to_dict -> reconstruct manually.
    restored = Blackboard()
    restored._topics = {
        t: [BoardEntry(**e) for e in entries] for t, entries in data["topics"].items()
    }
    assert restored.get("x") == {"k": "v"}


def test_thread_safety_under_contention():
    bb = Blackboard()
    errors = []

    def worker(i):
        try:
            for j in range(50):
                bb.post(f"t/{i}", j)
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(bb.entries("t/0")) == 50
