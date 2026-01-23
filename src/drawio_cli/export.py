"""Export handling for draw.io diagrams."""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import requests

from .config import ExportConfig
from .editor import get_desktop_path, EditorConfig

# draw.io public export API endpoint
DRAWIO_EXPORT_API = "https://convert.diagrams.net/node/export"


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


def export_with_api(
    source: Path,
    output: Optional[Path] = None,
    format: str = "png",
    scale: int = 2,
    page: int = 0,
) -> ExportResult:
    """Export diagram using the draw.io public export API.

    Uses https://convert.diagrams.net/node/export to render diagrams
    server-side without requiring the desktop app.

    Args:
        source: Source .drawio file
        output: Output file path (optional, defaults to same directory)
        format: Export format (png, svg, pdf)
        scale: Scale factor for export
        page: Page index to export (0-indexed)

    Returns:
        ExportResult with export details
    """
    source = source.resolve()
    if not source.exists():
        raise ExportError(f"Source file not found: {source}")

    # Determine output path
    if output is None:
        output = source.parent / get_export_filename(source, format)
    output = output.resolve()

    # Read the diagram XML
    xml_content = source.read_text(encoding="utf-8")

    # Prepare the POST data
    data = {
        "format": format,
        "xml": xml_content,
        "scale": str(scale),
        "pageIndex": str(page),
    }

    # Add format-specific options
    if format == "png":
        data["transparent"] = "false"
    elif format == "pdf":
        data["allPages"] = "false"

    try:
        response = requests.post(
            DRAWIO_EXPORT_API,
            data=data,
            timeout=60,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )

        if response.status_code != 200:
            raise ExportError(
                f"Export API returned status {response.status_code}: {response.text[:200]}"
            )

        # Check we got binary content back
        content_type = response.headers.get("content-type", "")
        if "image" not in content_type and "pdf" not in content_type:
            raise ExportError(f"Unexpected response type: {content_type}")

        # Write the exported file
        output.write_bytes(response.content)

        return ExportResult(
            source_file=source,
            output_file=output,
            format=format,
            method="api",
        )

    except requests.exceptions.Timeout:
        raise ExportError("Export API timed out after 60 seconds")
    except requests.exceptions.ConnectionError as e:
        raise ExportError(f"Could not connect to export API: {e}")
    except requests.exceptions.RequestException as e:
        raise ExportError(f"Export API request failed: {e}")


def export_with_playwright(
    source: Path,
    output: Optional[Path] = None,
    format: str = "png",
    scale: int = 2,
) -> ExportResult:
    """Export diagram using Playwright with headless browser.

    Uses the draw.io viewer (viewer.diagrams.net) to render diagrams
    in a headless browser and export them without requiring the desktop app.

    Args:
        source: Source .drawio file
        output: Output file path (optional, defaults to same directory)
        format: Export format (png, svg, pdf)
        scale: Scale factor for export

    Returns:
        ExportResult with export details
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise ExportError(
            "Playwright not installed. Install with: pip install playwright && playwright install chromium"
        )

    source = source.resolve()
    if not source.exists():
        raise ExportError(f"Source file not found: {source}")

    # Determine output path
    if output is None:
        output = source.parent / get_export_filename(source, format)
    output = output.resolve()

    # Read diagram XML and URL-encode it for the viewer URL
    xml_content = source.read_text(encoding="utf-8")
    encoded_xml = quote(xml_content, safe="")

    # Build viewer URL - viewer.diagrams.net renders diagrams from URL-encoded XML
    viewer_url = f"https://viewer.diagrams.net/?highlight=0000ff&nav=0&page=0#R{encoded_xml}"

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as e:
            raise ExportError(
                f"Failed to launch browser. Run 'playwright install chromium' first. Error: {e}"
            )

        # Create page with appropriate viewport (scaled for high-res export)
        viewport_width = 1920 * scale // 2
        viewport_height = 1080 * scale // 2
        page = browser.new_page(
            viewport={"width": viewport_width, "height": viewport_height},
            device_scale_factor=scale,
        )

        try:
            # Navigate to the viewer
            page.goto(viewer_url, timeout=30000, wait_until="networkidle")

            # Wait for diagram to render (the viewer creates an SVG)
            page.wait_for_selector("svg", timeout=15000)

            # Give extra time for complex diagrams to fully render
            page.wait_for_timeout(1000)

            if format == "svg":
                # Extract SVG content from the rendered diagram
                svg_content = page.evaluate("""
                    () => {
                        const svg = document.querySelector('svg');
                        return svg ? svg.outerHTML : null;
                    }
                """)
                if svg_content:
                    output.write_text(svg_content, encoding="utf-8")
                else:
                    raise ExportError("Failed to extract SVG content")

            elif format == "pdf":
                # Get diagram dimensions for PDF sizing
                dims = page.evaluate("""
                    () => {
                        const svg = document.querySelector('svg');
                        if (!svg) return null;
                        const rect = svg.getBoundingClientRect();
                        return {width: rect.width, height: rect.height};
                    }
                """)
                if dims and dims.get("width") > 0:
                    page.pdf(
                        path=str(output),
                        width=f"{int(dims['width'] + 40)}px",
                        height=f"{int(dims['height'] + 40)}px",
                        print_background=True,
                    )
                else:
                    page.pdf(path=str(output), print_background=True)

            else:  # png, jpg
                # Get the bounding box of the SVG diagram
                clip_box = page.evaluate("""
                    () => {
                        const svg = document.querySelector('svg');
                        if (!svg) return null;
                        const rect = svg.getBoundingClientRect();
                        // Add some padding
                        return {
                            x: Math.max(0, rect.x - 10),
                            y: Math.max(0, rect.y - 10),
                            width: rect.width + 20,
                            height: rect.height + 20
                        };
                    }
                """)

                if clip_box and clip_box.get("width", 0) > 0:
                    page.screenshot(
                        path=str(output),
                        clip=clip_box,
                        type="png" if format == "png" else "jpeg",
                    )
                else:
                    # Fall back to full page screenshot
                    page.screenshot(path=str(output), full_page=True)

        finally:
            browser.close()

    if not output.exists():
        raise ExportError(f"Export completed but output file not found: {output}")

    return ExportResult(
        source_file=source,
        output_file=output,
        format=format,
        method="playwright",
    )


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

    Attempts export in order of preference:
    1. Desktop CLI (if available) - fastest, most reliable
    2. draw.io public API - no local install required
    3. Playwright headless browser - requires playwright package

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

    errors = []

    # Method 1: Try CLI export (desktop app)
    app_path = get_desktop_path(editor_config)
    if app_path:
        try:
            return export_with_cli(
                source=source,
                output=output,
                format=format,
                scale=scale,
                editor_config=editor_config,
            )
        except ExportError as e:
            errors.append(f"Desktop CLI: {e}")

    # Method 2: Try draw.io public API
    try:
        return export_with_api(
            source=source,
            output=output,
            format=format,
            scale=scale,
        )
    except ExportError as e:
        errors.append(f"API: {e}")

    # Method 3: Try Playwright-based export (headless browser)
    try:
        return export_with_playwright(
            source=source,
            output=output,
            format=format,
            scale=scale,
        )
    except ExportError as e:
        errors.append(f"Playwright: {e}")

    # All methods failed
    raise ExportError(
        f"All export methods failed for {source.name}:\n"
        + "\n".join(f"  - {err}" for err in errors)
    )


def get_supported_formats() -> list[str]:
    """Get list of supported export formats."""
    return ["png", "svg", "pdf", "jpg", "gif", "webp"]
