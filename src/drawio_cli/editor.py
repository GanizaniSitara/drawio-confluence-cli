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


def _is_wsl() -> bool:
    """Check if running in Windows Subsystem for Linux."""
    try:
        with open("/proc/version", "r") as f:
            return "microsoft" in f.read().lower()
    except (FileNotFoundError, PermissionError):
        return False


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

    elif system == "Linux":
        # Check for WSL environment first - can use Windows draw.io
        if _is_wsl():
            wsl_candidates = [
                Path("/mnt/c/Program Files/draw.io/draw.io.exe"),
                Path("/mnt/c/Users") / os.environ.get("USER", "") / "AppData/Local/Programs/draw.io/draw.io.exe",
            ]
            for path in wsl_candidates:
                if path.exists():
                    return path

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

    elif system == "Darwin":
        # macOS
        candidates = [
            Path("/Applications/draw.io.app/Contents/MacOS/draw.io"),
            Path.home() / "Applications" / "draw.io.app" / "Contents" / "MacOS" / "draw.io",
        ]
        for path in candidates:
            if path.exists():
                return path

    return None


def is_desktop_available(config: Optional[EditorConfig] = None) -> bool:
    """Check if desktop app is available."""
    if config and config.desktop_path:
        return _path_exists(config.desktop_path)
    return find_desktop_app() is not None


def get_desktop_path(config: Optional[EditorConfig] = None) -> Optional[Path]:
    """Get the desktop app path."""
    if config and config.desktop_path:
        if _path_exists(config.desktop_path):
            return _resolve_path(config.desktop_path)
    return find_desktop_app()


def _windows_to_wsl_path(path_str: str) -> Optional[Path]:
    """Convert a Windows path to a WSL path."""
    # Handle C:\... -> /mnt/c/...
    if len(path_str) >= 3 and path_str[1] == ":" and path_str[2] == "\\":
        drive = path_str[0].lower()
        rest = path_str[3:].replace("\\", "/")
        return Path(f"/mnt/{drive}/{rest}")
    # Also handle C:/... style
    if len(path_str) >= 3 and path_str[1] == ":" and path_str[2] == "/":
        drive = path_str[0].lower()
        rest = path_str[3:]
        return Path(f"/mnt/{drive}/{rest}")
    return None


def _wsl_to_windows_path(path: Path) -> str:
    """Convert a WSL path to a Windows path."""
    path_str = str(path)
    # Handle /mnt/c/... -> C:\...
    if path_str.startswith("/mnt/") and len(path_str) > 6:
        drive = path_str[5].upper()
        rest = path_str[6:].replace("/", "\\")
        return f"{drive}:{rest}"
    # For other paths, use wslpath if available
    try:
        result = subprocess.run(
            ["wslpath", "-w", str(path)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return path_str


def _path_exists(path_str: str) -> bool:
    """Check if a path exists, handling Windows paths in WSL."""
    path = Path(path_str)
    if path.exists():
        return True
    # In WSL, try converting Windows path
    if _is_wsl():
        wsl_path = _windows_to_wsl_path(path_str)
        if wsl_path and wsl_path.exists():
            return True
    return False


def _resolve_path(path_str: str) -> Path:
    """Resolve a path, converting Windows paths in WSL if needed."""
    path = Path(path_str)
    if path.exists():
        return path
    # In WSL, try converting Windows path
    if _is_wsl():
        wsl_path = _windows_to_wsl_path(path_str)
        if wsl_path and wsl_path.exists():
            return wsl_path
    return path


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
        elif _is_wsl() and str(app_path).endswith(".exe"):
            # In WSL with Windows app - convert paths and use cmd.exe
            win_app_path = _wsl_to_windows_path(app_path)
            win_file_path = _wsl_to_windows_path(file_path)
            subprocess.Popen(
                ["cmd.exe", "/c", "start", "", win_app_path, win_file_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
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
        if _is_wsl():
            # In WSL, use cmd.exe to open the browser
            subprocess.Popen(
                ["cmd.exe", "/c", "start", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
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
