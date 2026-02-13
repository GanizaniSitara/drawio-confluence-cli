"""Command-line interface for drawio-cli."""

import re
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from . import __version__
from .config import (
    Config,
    find_workspace_root,
    init_workspace,
    load_config,
)
from .confluence import ConfluenceClient, ConfluenceError, AuthenticationError, NotFoundError
from .diagram import (
    parse_drawio_file,
    create_empty_diagram,
    validate_drawio_file,
    DiagramParseError,
)
from .editor import open_diagram, get_editor_info, EditorError
from .export import export_diagram, ExportError, get_supported_formats
from .publisher import publish_diagram, checkout_diagram, PublishError
from .state import load_state, State

console = Console()


def _extract_space_key_from_url(page_url: str) -> Optional[str]:
    """Extract space key from a Confluence page URL.

    Supports:
    - /display/SPACE/Title
    - /spaces/SPACE/pages/...
    """
    parsed = urlparse(page_url)
    path = parsed.path

    # Format: /display/SPACE/Title
    match = re.match(r".*/display/([^/]+)/", path)
    if match:
        return match.group(1)

    # Format: /spaces/SPACE/pages/...
    match = re.match(r".*/spaces/([^/]+)/", path)
    if match:
        return match.group(1)

    return None


def _extract_title_from_url(page_url: str) -> Optional[str]:
    """Extract page title from a Confluence page URL.

    Supports:
    - /display/SPACE/Title
    """
    parsed = urlparse(page_url)
    path = parsed.path

    # Format: /display/SPACE/Title
    match = re.match(r".*/display/[^/]+/(.+)$", path)
    if match:
        title = match.group(1)
        # URL decode: replace + and %20 with spaces
        return title.replace("+", " ").replace("%20", " ")

    return None


class CliContext:
    """CLI context holding configuration and state."""

    def __init__(self):
        self.workspace_root: Optional[Path] = None
        self.config: Optional[Config] = None
        self.state: Optional[State] = None
        self._client: Optional[ConfluenceClient] = None

    def load(self, require_workspace: bool = True) -> None:
        """Load workspace configuration and state."""
        self.workspace_root = find_workspace_root()

        if self.workspace_root is None:
            if require_workspace:
                console.print(
                    "[red]Error:[/red] Not in a drawio-cli workspace. "
                    "Run 'drawio-cli init' first."
                )
                sys.exit(1)
            return

        self.config = load_config(self.workspace_root)
        self.state = load_state(self.config.state_file)

    @property
    def client(self) -> ConfluenceClient:
        """Get Confluence client, creating if needed."""
        if self._client is None:
            if self.config is None:
                raise RuntimeError("Config not loaded")
            if not self.config.confluence.is_configured():
                auth_type = self.config.confluence.auth_type
                if auth_type == "pat":
                    console.print(
                        "[red]Error:[/red] Confluence not configured. "
                        "auth_type is 'pat' - set CONFLUENCE_PAT environment variable."
                    )
                elif auth_type == "basic":
                    console.print(
                        "[red]Error:[/red] Confluence not configured. "
                        "auth_type is 'basic' - set CONFLUENCE_USER and CONFLUENCE_PASS environment variables."
                    )
                else:
                    console.print(
                        f"[red]Error:[/red] Invalid auth_type '{auth_type}' in config. "
                        "Must be 'pat' or 'basic'."
                    )
                sys.exit(1)
            self._client = ConfluenceClient(self.config.confluence)
        return self._client


pass_context = click.make_pass_decorator(CliContext, ensure=True)


@click.group()
@click.version_option(version=__version__, prog_name="drawio-cli")
@click.pass_context
def main(ctx: click.Context) -> None:
    """Draw.io Confluence CLI - Manage draw.io diagrams with Confluence integration."""
    ctx.ensure_object(CliContext)


@main.command()
@click.option(
    "--path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Path to initialize workspace (defaults to current directory)",
)
@click.option(
    "--base-url",
    prompt="Confluence base URL",
    help="Confluence server base URL (e.g., https://wiki.company.com)",
)
@click.option(
    "--auth-type",
    type=click.Choice(["pat", "basic"]),
    default="pat",
    help="Authentication type",
)
@pass_context
def init(
    ctx: CliContext,
    path: Optional[Path],
    base_url: str,
    auth_type: str,
) -> None:
    """Initialize a new drawio-cli workspace."""
    if path is None:
        path = Path.cwd()

    # Check if already initialized
    existing = find_workspace_root(path)
    if existing and existing == path.resolve():
        console.print(f"[yellow]Workspace already initialized at {path}[/yellow]")
        ctx.config = load_config(path)
    else:
        ctx.config = init_workspace(path)
        console.print(f"[green]Initialized workspace at {path}[/green]")

    # Update configuration
    ctx.config.confluence.base_url = base_url.rstrip("/")
    ctx.config.confluence.auth_type = auth_type
    ctx.config.save()

    console.print(f"\nConfiguration saved to {ctx.config.config_file}")

    # Show draw.io desktop status
    if ctx.config.editor.desktop_path:
        console.print(f"[green]✓ Draw.io desktop app detected:[/green] {ctx.config.editor.desktop_path}")
    else:
        console.print("[dim]Draw.io desktop app not found - will use web editor[/dim]")

    console.print("\n[bold]Next steps:[/bold]")

    if auth_type == "pat":
        console.print("  1. Set CONFLUENCE_PAT environment variable with your Personal Access Token")
    else:
        console.print("  1. Set CONFLUENCE_USER and CONFLUENCE_PASS environment variables")

    console.print("  2. Run 'drawio-cli config' to verify settings")
    console.print("  3. Run 'drawio-cli checkout <page-url>' to download a diagram")


@main.command()
@pass_context
def config(ctx: CliContext) -> None:
    """View current configuration."""
    ctx.load(require_workspace=False)

    if ctx.config is None:
        console.print("[yellow]No workspace found. Run 'drawio-cli init' first.[/yellow]")
        return

    console.print(Panel("[bold]Configuration[/bold]"))

    table = Table(show_header=False, box=None)
    table.add_column("Setting", style="cyan")
    table.add_column("Value")

    table.add_row("Workspace", str(ctx.workspace_root))
    table.add_row("Config file", str(ctx.config.config_file))
    table.add_row("", "")
    table.add_row("[bold]Confluence[/bold]", "")
    table.add_row("  Base URL", ctx.config.confluence.base_url or "[dim]not set[/dim]")
    table.add_row("  Auth type", ctx.config.confluence.auth_type)
    table.add_row(
        "  Credentials",
        "[green]configured[/green]" if ctx.config.confluence.is_configured() else "[red]not set[/red]",
    )
    table.add_row("", "")
    table.add_row("[bold]Editor[/bold]", "")
    table.add_row("  Prefer", ctx.config.editor.prefer)

    editor_info = get_editor_info(ctx.config.editor)
    if editor_info["desktop_available"]:
        table.add_row("  Desktop app", f"[green]found[/green] ({editor_info['desktop_path']})")
    else:
        table.add_row("  Desktop app", "[dim]not found[/dim]")

    table.add_row("", "")
    table.add_row("[bold]Export[/bold]", "")
    table.add_row("  Default format", ctx.config.export.default_format)
    table.add_row("  PNG scale", str(ctx.config.export.png_scale))

    console.print(table)

    # Test connection if configured
    if ctx.config.confluence.is_configured():
        console.print("\n[bold]Testing Confluence connection...[/bold]")
        try:
            client = ConfluenceClient(ctx.config.confluence)
            if client.test_connection():
                console.print("[green]✓ Connection successful[/green]")
            else:
                console.print("[red]✗ Connection failed[/red]")
        except AuthenticationError as e:
            console.print(f"[red]✗ Authentication failed: {e}[/red]")
        except ConfluenceError as e:
            console.print(f"[red]✗ Connection error: {e}[/red]")


@main.command("list")
@pass_context
def list_diagrams(ctx: CliContext) -> None:
    """List tracked diagrams and their status."""
    ctx.load()

    if not ctx.state.diagrams:
        console.print("[dim]No diagrams tracked yet.[/dim]")
        console.print("Use 'drawio-cli checkout <page-url>' to download a diagram")
        console.print("or 'drawio-cli new <name>' to create one.")
        return

    table = Table(title="Tracked Diagrams")
    table.add_column("Diagram", style="cyan")
    table.add_column("Confluence Page")
    table.add_column("Last Sync")
    table.add_column("Status")

    for path, diagram in ctx.state.diagrams.items():
        # Check if local file exists
        local_path = ctx.workspace_root / path
        if local_path.exists():
            status = "[green]local[/green]"
        else:
            status = "[red]missing[/red]"

        page_info = ""
        if diagram.confluence_page_id:
            page_info = diagram.confluence_page_url or f"ID: {diagram.confluence_page_id}"
            if len(page_info) > 50:
                page_info = "..." + page_info[-47:]

        sync_time = diagram.last_sync or "[dim]never[/dim]"
        if sync_time and sync_time != "[dim]never[/dim]":
            # Format timestamp
            sync_time = sync_time.replace("T", " ").replace("Z", "")[:16]

        table.add_row(path, page_info, sync_time, status)

    console.print(table)


@main.command()
@click.argument("page_url")
@click.option(
    "--output",
    "-o",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Output directory (defaults to current directory)",
)
@click.option(
    "--filename",
    "-f",
    default=None,
    help="Specific .drawio filename to download (if page has multiple)",
)
@pass_context
def checkout(
    ctx: CliContext,
    page_url: str,
    output: Optional[Path],
    filename: Optional[str],
) -> None:
    """Download a .drawio diagram from a Confluence page."""
    ctx.load()

    if output is None:
        output = Path.cwd()

    console.print(f"[bold]Downloading diagram from Confluence...[/bold]")

    try:
        result_path = checkout_diagram(
            page_url=page_url,
            output_dir=output,
            config=ctx.config,
            state=ctx.state,
            client=ctx.client,
            filename=filename,
        )
        console.print(f"[green]✓ Downloaded:[/green] {result_path}")
        console.print(f"\nEdit with: drawio-cli edit {result_path.name}")
    except PublishError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    except ConfluenceError as e:
        console.print(f"[red]Confluence error:[/red] {e}")
        sys.exit(1)


@main.command()
@click.argument("name")
@click.argument("page_url", required=False, default=None)
@click.option(
    "--output",
    "-o",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Output directory (defaults to current directory)",
)
@click.option(
    "--format",
    "-f",
    "fmt",
    type=click.Choice(get_supported_formats()),
    default=None,
    help="Export format for publishing (default: from config)",
)
@click.option(
    "--no-edit",
    is_flag=True,
    help="Don't open editor after creation",
)
@click.option(
    "--no-publish",
    is_flag=True,
    help="Don't publish after editing (just create and open)",
)
@pass_context
def new(
    ctx: CliContext,
    name: str,
    page_url: Optional[str],
    output: Optional[Path],
    fmt: Optional[str],
    no_edit: bool,
    no_publish: bool,
) -> None:
    """Create a new .drawio diagram.

    NAME is the diagram filename (with or without .drawio extension).
    PAGE_URL is an optional Confluence page URL to link the diagram to.
    If the page doesn't exist, it will be created automatically.

    When PAGE_URL is provided, the editor will wait for you to save and close,
    then automatically export and publish to Confluence.
    """
    ctx.load()

    if output is None:
        output = Path.cwd()

    # Ensure name has .drawio extension
    if not name.endswith(".drawio"):
        name = f"{name}.drawio"

    output_path = output / name

    if output_path.exists():
        if not click.confirm(f"File already exists: {output_path}\nOverwrite and update Confluence link?"):
            console.print("[yellow]Cancelled[/yellow]")
            sys.exit(0)

    # Publish by default if page_url is provided (unless --no-publish)
    should_publish = page_url is not None and not no_publish
    should_edit = not no_edit
    page_id = None
    page = None

    # Validate/create Confluence page BEFORE creating local file
    if page_url:
        try:
            page = ctx.client.get_page_by_url(page_url)
            page_id = page.id
            console.print(f"Linked to existing page: {page.title}")
        except NotFoundError:
            # Page doesn't exist - try to create it
            space_key = _extract_space_key_from_url(page_url)
            title = _extract_title_from_url(page_url)

            if not space_key:
                console.print(f"[red]Error:[/red] Could not extract space key from URL: {page_url}")
                console.print("URL format should be: /display/SPACEKEY/Page+Title")
                sys.exit(1)

            if not title:
                # Use diagram name as title if not in URL
                title = Path(name).stem.replace("-", " ").replace("_", " ").title()

            console.print(f"Page not found. Creating: {title} in space {space_key}...")
            try:
                page = ctx.client.create_page(space_key, title)
                page_id = page.id
                console.print(f"[green]✓ Created Confluence page:[/green] {page.title}")
            except ConfluenceError as e:
                console.print(f"[red]Error:[/red] Failed to create page: {e}")
                console.print("Check your permissions for this space.")
                sys.exit(1)
        except AuthenticationError as e:
            console.print(f"[red]Authentication error:[/red] {e}")
            sys.exit(1)
        except ConfluenceError as e:
            console.print(f"[red]Confluence error:[/red] {e}")
            if should_publish:
                console.print("Cannot proceed without valid page link.")
                sys.exit(1)
            should_publish = False

    # Now create the local diagram file
    content = create_empty_diagram(Path(name).stem)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content)

    # Add to state
    rel_path = str(output_path.relative_to(ctx.workspace_root))
    diagram_state = ctx.state.add_diagram(rel_path, page_id, page.url if page else page_url)
    if fmt:
        diagram_state.export_format = fmt
    ctx.state.save()

    console.print(f"[green]✓ Created:[/green] {output_path}")
    if fmt:
        console.print(f"  Export format: {fmt}")

    # Open in editor
    if should_edit:
        try:
            wait_for_close = should_publish  # Wait if we need to publish after
            if wait_for_close:
                console.print("[bold]Opening editor - will publish after you save and close...[/bold]")
            method = open_diagram(output_path, ctx.config.editor, wait=wait_for_close)
            if method == "desktop":
                if not wait_for_close:
                    console.print(f"[green]Opened in desktop app[/green]")
            else:
                console.print(f"[green]Opened app.diagrams.net[/green] - use File → Open from → Device to load {output_path.name}")
                if should_publish:
                    console.print("[yellow]Note:[/yellow] Cannot auto-publish with web editor. Run 'drawio-cli publish' manually after editing.")
                    should_publish = False

            # Publish after editor closes
            if should_publish and method == "desktop":
                console.print("\n[bold]Editor closed. Publishing to Confluence...[/bold]")

                def log(msg: str) -> None:
                    console.print(f"  [dim]{msg}[/dim]")

                try:
                    result = publish_diagram(
                        diagram_path=output_path,
                        config=ctx.config,
                        state=ctx.state,
                        client=ctx.client,
                        export_format=fmt,
                        log=log,
                    )
                    console.print(f"[green]✓ Published successfully[/green]")
                    console.print(f"  Page: {result.page_url}")
                    console.print(f"  .drawio attachment: v{result.drawio_attachment.version}")
                    if result.image_attachment:
                        console.print(f"  Image attachment: {result.image_attachment.filename}")
                    else:
                        console.print("  [yellow]No image attachment (export may have failed)[/yellow]")
                    if result.page_updated:
                        console.print("  Page content updated")
                except (PublishError, ConfluenceError, ExportError) as e:
                    console.print(f"[red]Publish error:[/red] {e}")
                    sys.exit(1)

        except EditorError as e:
            console.print(f"[yellow]Could not open editor:[/yellow] {e}")
            console.print(f"\nEdit manually with: drawio-cli edit {name}")
    else:
        console.print(f"\nEdit with: drawio-cli edit {name}")


@main.command()
@click.argument("diagram", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--desktop/--web",
    default=None,
    help="Force desktop or web editor",
)
@click.option(
    "--no-publish",
    is_flag=True,
    help="Don't publish after editing (just open editor)",
)
@pass_context
def edit(ctx: CliContext, diagram: Path, desktop: Optional[bool], no_publish: bool) -> None:
    """Open a diagram for editing.

    If the diagram is linked to a Confluence page, it will automatically
    publish after you save and close the editor.
    """
    ctx.load()

    # Validate file
    if not validate_drawio_file(diagram):
        console.print(f"[red]Error:[/red] Not a valid .drawio file: {diagram}")
        sys.exit(1)

    prefer = None
    if desktop is True:
        prefer = "desktop"
    elif desktop is False:
        prefer = "web"

    # Check if diagram is linked to Confluence
    rel_path = str(diagram.resolve().relative_to(ctx.workspace_root))
    diagram_state = ctx.state.get_diagram(rel_path)
    is_linked = diagram_state and diagram_state.confluence_page_id
    should_publish = is_linked and not no_publish

    try:
        wait_for_close = should_publish
        if wait_for_close:
            console.print("[bold]Opening editor - will publish after you save and close...[/bold]")

        method = open_diagram(diagram, ctx.config.editor, prefer, wait=wait_for_close)
        if method == "desktop":
            if not wait_for_close:
                console.print(f"[green]Opened in desktop app:[/green] {diagram}")
        else:
            console.print(f"[green]Opened app.diagrams.net[/green] - use File → Open from → Device to load {diagram.name}")
            if should_publish:
                console.print("[yellow]Note:[/yellow] Cannot auto-publish with web editor. Run 'drawio-cli publish' manually after editing.")
                should_publish = False

        # Publish after editor closes
        if should_publish and method == "desktop":
            console.print("\n[bold]Editor closed. Publishing to Confluence...[/bold]")

            def log(msg: str) -> None:
                console.print(f"  [dim]{msg}[/dim]")

            try:
                result = publish_diagram(
                    diagram_path=diagram,
                    config=ctx.config,
                    state=ctx.state,
                    client=ctx.client,
                    log=log,
                )
                console.print(f"[green]✓ Published successfully[/green]")
                console.print(f"  Page: {result.page_url}")
                console.print(f"  .drawio attachment: v{result.drawio_attachment.version}")
                if result.image_attachment:
                    console.print(f"  Image attachment: {result.image_attachment.filename}")
                else:
                    console.print("  [yellow]No image attachment (export may have failed)[/yellow]")
                if result.page_updated:
                    console.print("  Page content updated")
            except (PublishError, ConfluenceError, ExportError) as e:
                console.print(f"[red]Publish error:[/red] {e}")
                sys.exit(1)

    except EditorError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@main.command()
@pass_context
def status(ctx: CliContext) -> None:
    """Show status of tracked diagrams compared to Confluence."""
    ctx.load()

    if not ctx.state.diagrams:
        console.print("[dim]No diagrams tracked.[/dim]")
        return

    console.print("[bold]Diagram Status[/bold]\n")

    for path, diagram in ctx.state.diagrams.items():
        local_path = ctx.workspace_root / path

        console.print(f"[cyan]{path}[/cyan]")

        if not local_path.exists():
            console.print("  [red]Local file missing[/red]")
            continue

        # Parse local diagram
        try:
            info = parse_drawio_file(local_path)
            console.print(f"  Pages: {len(info.pages)}")
            console.print(f"  Links: {len(info.links)}")
        except DiagramParseError as e:
            console.print(f"  [red]Parse error: {e}[/red]")
            continue

        if diagram.confluence_page_id:
            console.print(f"  Linked to: {diagram.confluence_page_url or diagram.confluence_page_id}")
            if diagram.last_sync:
                console.print(f"  Last sync: {diagram.last_sync}")
        else:
            console.print("  [yellow]Not linked to Confluence[/yellow]")

        console.print()


@main.command("export")
@click.argument("diagram", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--format",
    "-f",
    "fmt",
    type=click.Choice(get_supported_formats()),
    default=None,
    help="Export format (default: from config)",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="Output file path",
)
@click.option(
    "--force",
    is_flag=True,
    help="Force export even if up-to-date export exists",
)
@pass_context
def export_cmd(
    ctx: CliContext,
    diagram: Path,
    fmt: Optional[str],
    output: Optional[Path],
    force: bool,
) -> None:
    """Export a diagram to an image format (requires desktop app)."""
    ctx.load()

    try:
        result = export_diagram(
            source=diagram,
            output=output,
            format=fmt,
            export_config=ctx.config.export,
            editor_config=ctx.config.editor,
            force=force,
        )

        if result.method == "cached":
            console.print(f"[green]Using cached export:[/green] {result.output_file}")
        else:
            console.print(f"[green]✓ Exported:[/green] {result.output_file}")

    except ExportError as e:
        console.print(f"[red]Export error:[/red]\n{e}")
        sys.exit(1)


@main.command()
@click.argument("diagram", type=click.Path(exists=True, path_type=Path))
@click.argument("page", required=False, default=None)
@click.option(
    "--format",
    "-f",
    "fmt",
    type=click.Choice(get_supported_formats()),
    default=None,
    help="Export format (overrides stored format)",
)
@click.option(
    "--no-content-update",
    is_flag=True,
    help="Only upload attachments, don't update page content",
)
@click.option(
    "--force-export",
    is_flag=True,
    help="Force re-export even if cached export exists",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    help="Show detailed progress",
)
@pass_context
def publish(
    ctx: CliContext,
    diagram: Path,
    page: Optional[str],
    fmt: Optional[str],
    no_content_update: bool,
    force_export: bool,
    verbose: bool,
) -> None:
    """Publish a diagram to Confluence.

    DIAGRAM is the path to the .drawio file.
    PAGE is an optional Confluence page URL or page ID (overrides stored link).
    """
    ctx.load()

    # Resolve page URL from ID if numeric
    page_url = None
    if page:
        if page.isdigit():
            # It's a page ID - resolve to URL
            try:
                page_info = ctx.client.get_page_by_id(page)
                page_url = page_info.url
                console.print(f"[dim]Resolved page ID {page} → {page_info.title}[/dim]")
            except NotFoundError:
                console.print(f"[red]Error:[/red] Page ID {page} not found")
                sys.exit(1)
            except ConfluenceError as e:
                console.print(f"[red]Confluence error:[/red] {e}")
                sys.exit(1)
        else:
            page_url = page

    console.print(f"[bold]Publishing {diagram.name}...[/bold]")

    def log(msg: str) -> None:
        if verbose:
            console.print(f"  [dim]{msg}[/dim]")

    try:
        result = publish_diagram(
            diagram_path=diagram,
            config=ctx.config,
            state=ctx.state,
            client=ctx.client,
            page_url=page_url,
            export_format=fmt,
            update_page_content=not no_content_update,
            force_export=force_export,
            log=log,
        )

        console.print(f"\n[green]✓ Published successfully[/green]")
        console.print(f"  Page: {result.page_url}")
        console.print(f"  .drawio attachment: v{result.drawio_attachment.version}")
        if result.image_attachment:
            console.print(f"  Image attachment: {result.image_attachment.filename}")
        else:
            console.print("  [yellow]No image attachment (export may have failed)[/yellow]")
        if result.links_added > 0:
            console.print(f"  Links in diagram: {result.links_added}")
        if result.page_updated:
            console.print("  Page content updated")

    except PublishError as e:
        console.print(f"[red]Publish error:[/red] {e}")
        sys.exit(1)
    except ConfluenceError as e:
        console.print(f"[red]Confluence error:[/red] {e}")
        sys.exit(1)
    except ExportError as e:
        console.print(f"[red]Export error:[/red] {e}")
        sys.exit(1)


@main.command("publish-all")
@click.option(
    "--force-export",
    is_flag=True,
    help="Force re-export even if cached exports exist",
)
@pass_context
def publish_all(ctx: CliContext, force_export: bool) -> None:
    """Publish all tracked diagrams that are linked to Confluence pages."""
    ctx.load()

    linked = ctx.state.list_linked_diagrams()
    if not linked:
        console.print("[dim]No diagrams linked to Confluence pages.[/dim]")
        return

    console.print(f"[bold]Publishing {len(linked)} diagram(s)...[/bold]\n")

    success = 0
    failed = 0

    for diagram in linked:
        local_path = ctx.workspace_root / diagram.local_path
        console.print(f"[cyan]{diagram.local_path}[/cyan]")

        if not local_path.exists():
            console.print("  [red]✗ Local file missing[/red]")
            failed += 1
            continue

        try:
            result = publish_diagram(
                diagram_path=local_path,
                config=ctx.config,
                state=ctx.state,
                client=ctx.client,
                force_export=force_export,
            )
            console.print(f"  [green]✓ Published[/green]")
            success += 1
        except (PublishError, ConfluenceError, ExportError) as e:
            console.print(f"  [red]✗ {e}[/red]")
            failed += 1

    console.print(f"\n[bold]Results:[/bold] {success} succeeded, {failed} failed")


@main.command()
@click.argument("diagram", type=click.Path(path_type=Path))
@click.option(
    "--delete-local",
    is_flag=True,
    help="Also delete the local .drawio file",
)
@click.option(
    "--keep-attachments",
    is_flag=True,
    help="Only unlink from state, don't delete Confluence attachments",
)
@click.option(
    "--yes", "-y",
    is_flag=True,
    help="Skip confirmation prompt",
)
@pass_context
def remove(
    ctx: CliContext,
    diagram: Path,
    delete_local: bool,
    keep_attachments: bool,
    yes: bool,
) -> None:
    """Remove a diagram from Confluence and unlink from tracking.

    This deletes the .drawio and image attachments from the Confluence page,
    removes the diagram from local state tracking, and optionally deletes
    the local file.
    """
    ctx.load()

    # Check if diagram is tracked
    rel_path = str(diagram.resolve().relative_to(ctx.workspace_root)) if diagram.exists() else str(diagram)
    diagram_state = ctx.state.get_diagram(rel_path)

    if not diagram_state:
        # Try with just the filename
        for path in ctx.state.diagrams:
            if Path(path).name == diagram.name:
                rel_path = path
                diagram_state = ctx.state.get_diagram(rel_path)
                break

    if not diagram_state:
        console.print(f"[yellow]Diagram not tracked:[/yellow] {diagram}")
        console.print("Use 'drawio-cli list' to see tracked diagrams.")
        sys.exit(1)

    page_id = diagram_state.confluence_page_id
    page_url = diagram_state.confluence_page_url

    # Confirm action
    if not yes:
        console.print(f"[bold]Will remove:[/bold] {rel_path}")
        if page_id:
            console.print(f"  Confluence page: {page_url or page_id}")
            if not keep_attachments:
                console.print("  [yellow]Will delete attachments from Confluence[/yellow]")
        if delete_local and diagram.exists():
            console.print(f"  [yellow]Will delete local file: {diagram}[/yellow]")

        if not click.confirm("\nProceed?"):
            console.print("[dim]Cancelled[/dim]")
            sys.exit(0)

    deleted_attachments = []

    # Delete Confluence attachments
    if page_id and not keep_attachments:
        console.print(f"[bold]Removing from Confluence...[/bold]")

        try:
            # Delete .drawio attachment
            drawio_filename = Path(rel_path).name
            if ctx.client.delete_attachment_by_filename(page_id, drawio_filename):
                deleted_attachments.append(drawio_filename)
                console.print(f"  [green]✓[/green] Deleted {drawio_filename}")

            # Delete image attachments (try common formats)
            base_name = Path(rel_path).stem
            for ext in [".png", ".svg", ".jpg", ".pdf"]:
                image_filename = base_name + ext
                if ctx.client.delete_attachment_by_filename(page_id, image_filename):
                    deleted_attachments.append(image_filename)
                    console.print(f"  [green]✓[/green] Deleted {image_filename}")

        except AuthenticationError as e:
            console.print(f"[red]Authentication error:[/red] {e}")
            sys.exit(1)
        except ConfluenceError as e:
            console.print(f"[red]Confluence error:[/red] {e}")
            sys.exit(1)

        if not deleted_attachments:
            console.print("  [dim]No attachments found to delete[/dim]")

    # Remove from state
    ctx.state.remove_diagram(rel_path)
    ctx.state.save()
    console.print(f"[green]✓[/green] Removed from tracking")

    # Delete local file
    if delete_local:
        local_path = ctx.workspace_root / rel_path
        if local_path.exists():
            local_path.unlink()
            console.print(f"[green]✓[/green] Deleted local file: {local_path}")

            # Also delete exported images
            for ext in [".png", ".svg", ".jpg", ".pdf"]:
                export_path = local_path.with_suffix(ext)
                if export_path.exists():
                    export_path.unlink()
                    console.print(f"[green]✓[/green] Deleted export: {export_path.name}")

    console.print(f"\n[green]Done.[/green]")
    if page_url:
        console.print(f"Page: {page_url}")


@main.command()
@click.argument("diagram", type=click.Path(exists=True, path_type=Path))
@pass_context
def links(ctx: CliContext, diagram: Path) -> None:
    """Show links found in a diagram."""
    ctx.load()

    try:
        info = parse_drawio_file(diagram)
    except DiagramParseError as e:
        console.print(f"[red]Error parsing diagram:[/red] {e}")
        sys.exit(1)

    console.print(f"[bold]{diagram.name}[/bold]")
    console.print(f"Pages: {', '.join(info.pages)}\n")

    if not info.links:
        console.print("[dim]No links found in diagram.[/dim]")
        return

    console.print(f"[bold]Links ({len(info.links)}):[/bold]")
    for link in info.links:
        console.print(f"  • {link.label}")
        console.print(f"    [dim]{link.url}[/dim]")


if __name__ == "__main__":
    main()
