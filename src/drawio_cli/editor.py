"""Editor launching for draw.io diagrams."""

import os
import platform
import shutil
import subprocess
import webbrowser
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from .config import EditorConfig


class EditorError(Exception):
    """Error launching editor."""

    pass


def find_desktop_app() -> Optional[Path]:
    """Find the draw.io desktop application."""
    system = platform.system()

    if system == "Windows":
        # Common Windows install locations
        candidates = [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "draw.io" / "draw.io.exe",
            Path(os.environ.get("PROGRAMFILES", "")) / "draw.io" / "draw.io.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", "")) / "draw.io" / "draw.io.exe",
            Path("C:/Program Files/draw.io/draw.io.exe"),
        ]
        for path in candidates:
            if path.exists():
                return path

    elif system == "Darwin":
        # macOS
        candidates = [
            Path("/Applications/draw.io.app/Contents/MacOS/draw.io"),
            Path.home() / "Applications" / "draw.io.app" / "Contents" / "MacOS" / "draw.io",
        ]
        for path in candidates:
            if path.exists():
                return path

    elif system == "Linux":
        # Linux - check if drawio is in PATH
        drawio_path = shutil.which("drawio")
        if drawio_path:
            return Path(drawio_path)

        # Common Linux install locations
        candidates = [
            Path("/usr/bin/drawio"),
            Path("/usr/local/bin/drawio"),
            Path("/opt/drawio/drawio"),
            Path.home() / ".local" / "bin" / "drawio",
        ]
        for path in candidates:
            if path.exists():
                return path

    return None


def is_desktop_available(config: Optional[EditorConfig] = None) -> bool:
    """Check if desktop app is available."""
    if config and config.desktop_path:
        return Path(config.desktop_path).exists()
    return find_desktop_app() is not None


def get_desktop_path(config: Optional[EditorConfig] = None) -> Optional[Path]:
    """Get the desktop app path."""
    if config and config.desktop_path:
        path = Path(config.desktop_path)
        if path.exists():
            return path
    return find_desktop_app()


def open_in_desktop(file_path: Path, config: Optional[EditorConfig] = None) -> bool:
    """Open a diagram in the desktop app."""
    app_path = get_desktop_path(config)
    if app_path is None:
        raise EditorError(
            "Draw.io desktop app not found. Install from https://www.drawio.com/ "
            "or configure the path in config.yaml"
        )

    file_path = file_path.resolve()
    if not file_path.exists():
        raise EditorError(f"File not found: {file_path}")

    try:
        # Launch the app with the file
        if platform.system() == "Windows":
            subprocess.Popen([str(app_path), str(file_path)], shell=False)
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", "-a", str(app_path), str(file_path)])
        else:
            subprocess.Popen([str(app_path), str(file_path)])
        return True
    except Exception as e:
        raise EditorError(f"Failed to launch desktop app: {e}")


def open_in_web(file_path: Path) -> bool:
    """Open a diagram in the web browser using app.diagrams.net.

    Note: The web app can't directly access local files for security reasons.
    This opens the web app where the user can use File > Open to load the file.
    """
    file_path = file_path.resolve()
    if not file_path.exists():
        raise EditorError(f"File not found: {file_path}")

    # Open diagrams.net - user will need to use File > Open from Device
    # We can't pass the file directly due to browser security restrictions
    url = "https://app.diagrams.net/"

    try:
        webbrowser.open(url)
        return True
    except Exception as e:
        raise EditorError(f"Failed to open web browser: {e}")


def open_diagram(
    file_path: Path,
    config: Optional[EditorConfig] = None,
    prefer: Optional[str] = None,
) -> str:
    """Open a diagram for editing.

    Args:
        file_path: Path to the .drawio file
        config: Editor configuration
        prefer: Override for editor preference ("web" or "desktop")

    Returns:
        String indicating how the file was opened ("desktop" or "web")
    """
    file_path = file_path.resolve()

    # Determine preference
    if prefer is None and config:
        prefer = config.prefer

    if prefer == "desktop" or (prefer is None and is_desktop_available(config)):
        # Try desktop first
        try:
            open_in_desktop(file_path, config)
            return "desktop"
        except EditorError:
            # Fall back to web
            if prefer == "desktop":
                raise
            open_in_web(file_path)
            return "web"
    else:
        # Use web
        open_in_web(file_path)
        return "web"


def get_editor_info(config: Optional[EditorConfig] = None) -> dict:
    """Get information about available editors."""
    desktop_path = get_desktop_path(config)
    return {
        "desktop_available": desktop_path is not None,
        "desktop_path": str(desktop_path) if desktop_path else None,
        "web_url": "https://app.diagrams.net/",
        "preferred": config.prefer if config else "web",
    }
