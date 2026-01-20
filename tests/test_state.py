"""Tests for state management."""

import json
from pathlib import Path

import pytest

from drawio_cli.state import (
    State,
    DiagramState,
    DiagramLink,
    load_state,
)


@pytest.fixture
def state_file(tmp_path):
    """Create a temporary state file path."""
    return tmp_path / ".drawio-cli" / "state.json"


@pytest.fixture
def empty_state(state_file):
    """Create an empty state."""
    state = State()
    state._state_file = state_file
    return state


class TestDiagramLink:
    """Tests for DiagramLink."""

    def test_to_dict(self):
        """Test converting link to dict."""
        link = DiagramLink(label="Test", url="https://example.com")
        d = link.to_dict()

        assert d["label"] == "Test"
        assert d["url"] == "https://example.com"

    def test_from_dict(self):
        """Test creating link from dict."""
        link = DiagramLink.from_dict({"label": "Test", "url": "https://example.com"})

        assert link.label == "Test"
        assert link.url == "https://example.com"


class TestDiagramState:
    """Tests for DiagramState."""

    def test_to_dict(self):
        """Test converting diagram state to dict."""
        state = DiagramState(
            local_path="test/diagram.drawio",
            confluence_page_id="12345",
            confluence_page_url="https://wiki.example.com/page",
            last_sync="2024-01-20T10:00:00Z",
            links_in_diagram=[DiagramLink(label="Link", url="https://example.com")],
        )
        d = state.to_dict()

        assert d["confluence_page_id"] == "12345"
        assert d["confluence_page_url"] == "https://wiki.example.com/page"
        assert len(d["links_in_diagram"]) == 1

    def test_from_dict(self):
        """Test creating diagram state from dict."""
        state = DiagramState.from_dict(
            "test/diagram.drawio",
            {
                "confluence_page_id": "12345",
                "links_in_diagram": [{"label": "Link", "url": "https://example.com"}],
            },
        )

        assert state.local_path == "test/diagram.drawio"
        assert state.confluence_page_id == "12345"
        assert len(state.links_in_diagram) == 1

    def test_is_linked(self):
        """Test is_linked property."""
        linked = DiagramState(local_path="a.drawio", confluence_page_id="123")
        unlinked = DiagramState(local_path="b.drawio")

        assert linked.is_linked() is True
        assert unlinked.is_linked() is False

    def test_update_sync_time(self):
        """Test update_sync_time sets current time."""
        state = DiagramState(local_path="test.drawio")
        assert state.last_sync is None

        state.update_sync_time()

        assert state.last_sync is not None
        assert "T" in state.last_sync
        assert state.last_sync.endswith("Z")


class TestState:
    """Tests for State."""

    def test_add_diagram(self, empty_state):
        """Test adding a new diagram."""
        diagram = empty_state.add_diagram(
            "project/diagram.drawio",
            page_id="123",
            page_url="https://wiki.example.com/page",
        )

        assert diagram.local_path == "project/diagram.drawio"
        assert diagram.confluence_page_id == "123"
        assert "project/diagram.drawio" in empty_state.diagrams

    def test_add_diagram_update_existing(self, empty_state):
        """Test updating an existing diagram."""
        empty_state.add_diagram("test.drawio", page_id="123")
        empty_state.add_diagram("test.drawio", page_id="456")

        assert len(empty_state.diagrams) == 1
        assert empty_state.diagrams["test.drawio"].confluence_page_id == "456"

    def test_get_diagram(self, empty_state):
        """Test getting a diagram."""
        empty_state.add_diagram("test.drawio")

        diagram = empty_state.get_diagram("test.drawio")
        assert diagram is not None

        missing = empty_state.get_diagram("nonexistent.drawio")
        assert missing is None

    def test_remove_diagram(self, empty_state):
        """Test removing a diagram."""
        empty_state.add_diagram("test.drawio")

        result = empty_state.remove_diagram("test.drawio")
        assert result is True
        assert "test.drawio" not in empty_state.diagrams

        result = empty_state.remove_diagram("nonexistent.drawio")
        assert result is False

    def test_list_diagrams(self, empty_state):
        """Test listing all diagrams."""
        empty_state.add_diagram("a.drawio")
        empty_state.add_diagram("b.drawio")

        diagrams = empty_state.list_diagrams()
        assert len(diagrams) == 2

    def test_list_linked_diagrams(self, empty_state):
        """Test listing only linked diagrams."""
        empty_state.add_diagram("linked.drawio", page_id="123")
        empty_state.add_diagram("unlinked.drawio")

        linked = empty_state.list_linked_diagrams()
        assert len(linked) == 1
        assert linked[0].local_path == "linked.drawio"

    def test_list_unlinked_diagrams(self, empty_state):
        """Test listing only unlinked diagrams."""
        empty_state.add_diagram("linked.drawio", page_id="123")
        empty_state.add_diagram("unlinked.drawio")

        unlinked = empty_state.list_unlinked_diagrams()
        assert len(unlinked) == 1
        assert unlinked[0].local_path == "unlinked.drawio"

    def test_save_and_load(self, state_file):
        """Test saving and loading state."""
        # Create and save state
        state = State()
        state._state_file = state_file
        state.add_diagram("test.drawio", page_id="123")
        state.save()

        # Load state
        loaded = load_state(state_file)

        assert "test.drawio" in loaded.diagrams
        assert loaded.diagrams["test.drawio"].confluence_page_id == "123"

    def test_load_nonexistent_file(self, tmp_path):
        """Test loading from nonexistent file returns empty state."""
        state = load_state(tmp_path / "nonexistent.json")

        assert len(state.diagrams) == 0

    def test_to_dict(self, empty_state):
        """Test converting state to dict."""
        empty_state.add_diagram("test.drawio", page_id="123")

        d = empty_state.to_dict()

        assert "diagrams" in d
        assert "test.drawio" in d["diagrams"]

    def test_from_dict(self, state_file):
        """Test creating state from dict."""
        data = {
            "diagrams": {
                "test.drawio": {
                    "confluence_page_id": "123",
                    "confluence_page_url": "https://wiki.example.com/page",
                    "links_in_diagram": [],
                }
            }
        }

        state = State.from_dict(data, state_file)

        assert "test.drawio" in state.diagrams
        assert state.diagrams["test.drawio"].confluence_page_id == "123"
