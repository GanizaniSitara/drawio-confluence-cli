"""Export handling for draw.io diagrams."""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import ExportConfig
from .editor import get_desktop_path, EditorConfig


class ExportError(Exception):
    """Error exporting diagram."""

    pass


@dataclass
class ExportResult:
    """Result of an export operation."""

    source_file: Path
    output_file: Path
    format: str
    method: str  # "cli" or "manual"
    all_pages: bool = False


def get_export_filename(source: Path, format: str, page: Optional[int] = None) -> str:
    """Generate export filename from source file."""
    base = source.stem
    if page is not None:
        return f"{base}-{page}.{format}"
    return f"{base}.{format}"


def export_with_cli(
    source: Path,
    output: Optional[Path] = None,
    format: str = "png",
    scale: int = 2,
    page: Optional[int] = None,
    all_pages: bool = False,
    editor_config: Optional[EditorConfig] = None,
) -> ExportResult:
    """Export diagram using the draw.io desktop CLI.

    The desktop app supports command-line export:
    drawio -x -f png -o output.png input.drawio

    Args:
        source: Source .drawio file
        output: Output file path (optional, defaults to same directory)
        format: Export format (png, svg, pdf, etc.)
        scale: Scale factor for PNG export
        page: Specific page to export (0-indexed, None for first page)
        all_pages: Export all pages (creates multiple files)
        editor_config: Editor configuration with desktop path

    Returns:
        ExportResult with export details
    """
    app_path = get_desktop_path(editor_config)
    if app_path is None:
        raise ExportError(
            "Draw.io desktop app required for CLI export. "
            "Install from https://www.drawio.com/ or export manually from the web app."
        )

    source = source.resolve()
    if not source.exists():
        raise ExportError(f"Source file not found: {source}")

    # Determine output path
    if output is None:
        output = source.parent / get_export_filename(source, format)
    output = output.resolve()

    # Build command
    cmd = [
        str(app_path),
        "-x",  # Export mode
        "-f", format,
        "-o", str(output),
    ]

    # Add scale for PNG
    if format == "png" and scale != 1:
        cmd.extend(["-s", str(scale)])

    # Add page selection
    if page is not None:
        cmd.extend(["-p", str(page)])
    elif all_pages:
        cmd.append("-a")

    # Add source file
    cmd.append(str(source))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or "Unknown error"
            raise ExportError(f"Export failed: {error_msg}")

        # Verify output was created
        if not output.exists():
            raise ExportError(f"Export completed but output file not found: {output}")

        return ExportResult(
            source_file=source,
            output_file=output,
            format=format,
            method="cli",
            all_pages=all_pages,
        )

    except subprocess.TimeoutExpired:
        raise ExportError("Export timed out after 60 seconds")
    except FileNotFoundError:
        raise ExportError(f"Could not execute draw.io app: {app_path}")


def find_exported_file(
    source: Path,
    format: str = "png",
    search_dir: Optional[Path] = None,
) -> Optional[Path]:
    """Find an exported file that matches the source diagram.

    For manual export workflow - looks for exported files in the same
    directory or specified search directory.
    """
    if search_dir is None:
        search_dir = source.parent

    # Expected filename patterns
    base = source.stem
    patterns = [
        f"{base}.{format}",
        f"{base}-0.{format}",  # Page 0
        f"{base} ({format}).{format}",  # Some export tools add format
    ]

    for pattern in patterns:
        candidate = search_dir / pattern
        if candidate.exists():
            # Check if export is newer than source
            if candidate.stat().st_mtime >= source.stat().st_mtime:
                return candidate

    # Look for any file matching base name with right extension
    for file in search_dir.glob(f"{base}*.{format}"):
        if file.stat().st_mtime >= source.stat().st_mtime:
            return file

    return None


def check_export_available(
    source: Path,
    format: str = "png",
    search_dir: Optional[Path] = None,
) -> Optional[Path]:
    """Check if an up-to-date export exists for a diagram.

    Returns the path to the export if found and up-to-date, None otherwise.
    """
    return find_exported_file(source, format, search_dir)


def export_diagram(
    source: Path,
    output: Optional[Path] = None,
    format: Optional[str] = None,
    export_config: Optional[ExportConfig] = None,
    editor_config: Optional[EditorConfig] = None,
    force: bool = False,
) -> ExportResult:
    """Export a diagram to an image format.

    Attempts CLI export if desktop app is available, otherwise
    returns instructions for manual export.

    Args:
        source: Source .drawio file
        output: Output file path (optional)
        format: Export format (uses config default if not specified)
        export_config: Export configuration
        editor_config: Editor configuration
        force: Force re-export even if up-to-date export exists

    Returns:
        ExportResult with export details
    """
    if format is None:
        format = export_config.default_format if export_config else "png"

    source = source.resolve()
    if not source.exists():
        raise ExportError(f"Source file not found: {source}")

    # Check for existing up-to-date export
    if not force:
        existing = find_exported_file(source, format)
        if existing:
            return ExportResult(
                source_file=source,
                output_file=existing,
                format=format,
                method="cached",
            )

    # Determine output path
    if output is None:
        output = source.parent / get_export_filename(source, format)

    # Get scale from config
    scale = export_config.png_scale if export_config else 2

    # Try CLI export
    app_path = get_desktop_path(editor_config)
    if app_path:
        return export_with_cli(
            source=source,
            output=output,
            format=format,
            scale=scale,
            editor_config=editor_config,
        )

    # No desktop app - manual export required
    raise ExportError(
        f"Desktop app not available for CLI export.\n"
        f"Please export manually:\n"
        f"  1. Open {source.name} in app.diagrams.net\n"
        f"  2. File → Export as → {format.upper()}\n"
        f"  3. Save as: {output}\n"
        f"Then run this command again."
    )


def get_supported_formats() -> list[str]:
    """Get list of supported export formats."""
    return ["png", "svg", "pdf", "jpg", "gif", "webp"]
