"""State management for tracking diagram-to-Confluence mappings."""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class DiagramLink:
    """A hyperlink found in a diagram."""

    label: str
    url: str

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {"label": self.label, "url": self.url}

    @classmethod
    def from_dict(cls, data: dict) -> "DiagramLink":
        """Create from dictionary."""
        return cls(label=data["label"], url=data["url"])


@dataclass
class DiagramState:
    """State of a tracked diagram."""

    local_path: str
    confluence_page_id: Optional[str] = None
    confluence_page_url: Optional[str] = None
    last_sync: Optional[str] = None
    last_attachment_version: Optional[int] = None
    last_local_modified: Optional[str] = None
    links_in_diagram: list[DiagramLink] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "confluence_page_id": self.confluence_page_id,
            "confluence_page_url": self.confluence_page_url,
            "last_sync": self.last_sync,
            "last_attachment_version": self.last_attachment_version,
            "last_local_modified": self.last_local_modified,
            "links_in_diagram": [link.to_dict() for link in self.links_in_diagram],
        }

    @classmethod
    def from_dict(cls, local_path: str, data: dict) -> "DiagramState":
        """Create from dictionary."""
        links = [
            DiagramLink.from_dict(link) for link in data.get("links_in_diagram", [])
        ]
        return cls(
            local_path=local_path,
            confluence_page_id=data.get("confluence_page_id"),
            confluence_page_url=data.get("confluence_page_url"),
            last_sync=data.get("last_sync"),
            last_attachment_version=data.get("last_attachment_version"),
            last_local_modified=data.get("last_local_modified"),
            links_in_diagram=links,
        )

    def update_sync_time(self) -> None:
        """Update last sync time to now."""
        self.last_sync = datetime.utcnow().isoformat() + "Z"

    def update_local_modified(self, mtime: Optional[float] = None) -> None:
        """Update last local modified time."""
        if mtime is not None:
            self.last_local_modified = datetime.utcfromtimestamp(mtime).isoformat() + "Z"
        else:
            self.last_local_modified = datetime.utcnow().isoformat() + "Z"

    def is_linked(self) -> bool:
        """Check if diagram is linked to a Confluence page."""
        return bool(self.confluence_page_id)


@dataclass
class State:
    """Overall state tracking all diagrams."""

    diagrams: dict[str, DiagramState] = field(default_factory=dict)
    _state_file: Optional[Path] = field(default=None, repr=False)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "diagrams": {
                path: state.to_dict() for path, state in self.diagrams.items()
            }
        }

    @classmethod
    def from_dict(cls, data: dict, state_file: Optional[Path] = None) -> "State":
        """Create from dictionary."""
        diagrams = {}
        for path, state_data in data.get("diagrams", {}).items():
            diagrams[path] = DiagramState.from_dict(path, state_data)
        state = cls(diagrams=diagrams)
        state._state_file = state_file
        return state

    def save(self) -> None:
        """Save state to state.json."""
        if self._state_file is None:
            raise ValueError("State file path not set")
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._state_file, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    def get_diagram(self, local_path: str) -> Optional[DiagramState]:
        """Get diagram state by local path."""
        # Normalize path
        normalized = str(Path(local_path))
        return self.diagrams.get(normalized)

    def add_diagram(
        self,
        local_path: str,
        page_id: Optional[str] = None,
        page_url: Optional[str] = None,
    ) -> DiagramState:
        """Add or update a diagram in state."""
        normalized = str(Path(local_path))
        if normalized in self.diagrams:
            diagram = self.diagrams[normalized]
            if page_id:
                diagram.confluence_page_id = page_id
            if page_url:
                diagram.confluence_page_url = page_url
        else:
            diagram = DiagramState(
                local_path=normalized,
                confluence_page_id=page_id,
                confluence_page_url=page_url,
            )
            self.diagrams[normalized] = diagram
        return diagram

    def remove_diagram(self, local_path: str) -> bool:
        """Remove a diagram from state."""
        normalized = str(Path(local_path))
        if normalized in self.diagrams:
            del self.diagrams[normalized]
            return True
        return False

    def list_diagrams(self) -> list[DiagramState]:
        """List all tracked diagrams."""
        return list(self.diagrams.values())

    def list_linked_diagrams(self) -> list[DiagramState]:
        """List diagrams linked to Confluence pages."""
        return [d for d in self.diagrams.values() if d.is_linked()]

    def list_unlinked_diagrams(self) -> list[DiagramState]:
        """List diagrams not linked to Confluence pages."""
        return [d for d in self.diagrams.values() if not d.is_linked()]


def load_state(state_file: Path) -> State:
    """Load state from state.json file."""
    if not state_file.exists():
        state = State()
        state._state_file = state_file
        return state

    with open(state_file) as f:
        data = json.load(f)

    return State.from_dict(data, state_file)
