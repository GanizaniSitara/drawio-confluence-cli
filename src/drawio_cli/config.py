"""Configuration management for drawio-cli."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


CONFIG_DIR = ".drawio-cli"
CONFIG_FILE = "config.yaml"
STATE_FILE = "state.json"


@dataclass
class ConfluenceConfig:
    """Confluence server configuration."""

    base_url: str = ""
    auth_type: str = "pat"  # "pat" or "basic"
    ssl_verify: bool = True  # Set to False for self-signed certs / no SSL

    @property
    def pat(self) -> Optional[str]:
        """Get Personal Access Token from environment."""
        return os.environ.get("CONFLUENCE_PAT")

    @property
    def username(self) -> Optional[str]:
        """Get username from environment."""
        return os.environ.get("CONFLUENCE_USER")

    @property
    def password(self) -> Optional[str]:
        """Get password from environment."""
        return os.environ.get("CONFLUENCE_PASS")

    def get_auth(self) -> tuple[Optional[str], Optional[str]] | str | None:
        """Get authentication credentials based on auth_type."""
        if self.auth_type == "pat":
            return self.pat
        elif self.auth_type == "basic":
            if self.username and self.password:
                return (self.username, self.password)
        return None

    def is_configured(self) -> bool:
        """Check if Confluence is properly configured."""
        if not self.base_url:
            return False
        if self.auth_type == "pat":
            return bool(self.pat)
        elif self.auth_type == "basic":
            return bool(self.username and self.password)
        return False


@dataclass
class EditorConfig:
    """Editor configuration."""

    prefer: str = "web"  # "web" or "desktop"
    desktop_path: Optional[str] = None


@dataclass
class ExportConfig:
    """Export configuration."""

    default_format: str = "png"
    svg_with_html_macro: bool = False
    png_scale: int = 2


@dataclass
class WorkspaceConfig:
    """Workspace configuration."""

    root: str = "."


@dataclass
class Config:
    """Main configuration container."""

    confluence: ConfluenceConfig = field(default_factory=ConfluenceConfig)
    editor: EditorConfig = field(default_factory=EditorConfig)
    export: ExportConfig = field(default_factory=ExportConfig)
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)

    _workspace_root: Optional[Path] = field(default=None, repr=False)

    @property
    def config_dir(self) -> Path:
        """Get the .drawio-cli config directory path."""
        if self._workspace_root:
            return self._workspace_root / CONFIG_DIR
        return Path(self.workspace.root) / CONFIG_DIR

    @property
    def config_file(self) -> Path:
        """Get the config.yaml file path."""
        return self.config_dir / CONFIG_FILE

    @property
    def state_file(self) -> Path:
        """Get the state.json file path."""
        return self.config_dir / STATE_FILE

    def to_dict(self) -> dict:
        """Convert config to dictionary for YAML serialization."""
        return {
            "confluence": {
                "base_url": self.confluence.base_url,
                "auth_type": self.confluence.auth_type,
                "ssl_verify": self.confluence.ssl_verify,
            },
            "editor": {
                "prefer": self.editor.prefer,
                "desktop_path": self.editor.desktop_path,
            },
            "export": {
                "default_format": self.export.default_format,
                "svg_with_html_macro": self.export.svg_with_html_macro,
                "png_scale": self.export.png_scale,
            },
            "workspace": {
                "root": self.workspace.root,
            },
        }

    @classmethod
    def from_dict(cls, data: dict, workspace_root: Optional[Path] = None) -> "Config":
        """Create config from dictionary."""
        config = cls()
        config._workspace_root = workspace_root

        if "confluence" in data:
            conf = data["confluence"]
            config.confluence = ConfluenceConfig(
                base_url=conf.get("base_url", ""),
                auth_type=conf.get("auth_type", "pat"),
                ssl_verify=conf.get("ssl_verify", True),
            )

        if "editor" in data:
            ed = data["editor"]
            config.editor = EditorConfig(
                prefer=ed.get("prefer", "web"),
                desktop_path=ed.get("desktop_path"),
            )

        if "export" in data:
            exp = data["export"]
            config.export = ExportConfig(
                default_format=exp.get("default_format", "png"),
                svg_with_html_macro=exp.get("svg_with_html_macro", False),
                png_scale=exp.get("png_scale", 2),
            )

        if "workspace" in data:
            ws = data["workspace"]
            config.workspace = WorkspaceConfig(
                root=ws.get("root", "."),
            )

        return config

    def save(self) -> None:
        """Save configuration to config.yaml."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, "w") as f:
            yaml.safe_dump(self.to_dict(), f, default_flow_style=False)


def find_workspace_root(start_path: Optional[Path] = None) -> Optional[Path]:
    """Find the workspace root by looking for .drawio-cli directory."""
    if start_path is None:
        start_path = Path.cwd()

    current = start_path.resolve()

    while current != current.parent:
        if (current / CONFIG_DIR).is_dir():
            return current
        current = current.parent

    # Check root directory
    if (current / CONFIG_DIR).is_dir():
        return current

    return None


def load_config(workspace_root: Optional[Path] = None) -> Config:
    """Load configuration from workspace.

    If workspace_root is not provided, searches for it starting from cwd.
    """
    if workspace_root is None:
        workspace_root = find_workspace_root()

    if workspace_root is None:
        # Return default config if no workspace found
        return Config()

    config_file = workspace_root / CONFIG_DIR / CONFIG_FILE

    if not config_file.exists():
        config = Config()
        config._workspace_root = workspace_root
        return config

    with open(config_file) as f:
        data = yaml.safe_load(f) or {}

    return Config.from_dict(data, workspace_root)


def init_workspace(path: Optional[Path] = None) -> Config:
    """Initialize a new workspace at the given path."""
    # Import here to avoid circular imports
    from .editor import find_desktop_app

    if path is None:
        path = Path.cwd()

    path = path.resolve()
    config_dir = path / CONFIG_DIR

    if config_dir.exists():
        # Load existing config
        return load_config(path)

    # Create new config
    config = Config()
    config._workspace_root = path

    # Auto-detect draw.io desktop app and save to config if found
    desktop_app = find_desktop_app()
    if desktop_app:
        config.editor.desktop_path = str(desktop_app)
        config.editor.prefer = "desktop"

    config.save()

    # Create empty state file
    state_file = config.state_file
    state_file.write_text("{}")

    return config
