"""Publishing workflow for uploading diagrams to Confluence."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import Config
from .confluence import ConfluenceClient, Page, Attachment, ConflictError
from .diagram import parse_drawio_file, DiagramLink
from .export import export_diagram, ExportResult, check_export_available
from .state import State, DiagramState


class PublishError(Exception):
    """Error during publish operation."""

    pass


@dataclass
class PublishResult:
    """Result of a publish operation."""

    diagram_path: Path
    page_id: str
    page_url: str
    drawio_attachment: Attachment
    image_attachment: Optional[Attachment]
    links_added: int
    page_updated: bool


def generate_links_section(links: list[DiagramLink]) -> str:
    """Generate Confluence storage format XHTML for links section.

    Creates a formatted list of links found in the diagram.
    """
    if not links:
        return ""

    lines = ["<h3>Links in this diagram</h3>", "<ul>"]
    for link in links:
        # Escape HTML in label
        label = (
            link.label
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        lines.append(f'  <li><a href="{link.url}">{label}</a></li>')
    lines.append("</ul>")

    return "\n".join(lines)


def generate_diagram_section(
    diagram_name: str,
    image_filename: str,
    drawio_filename: str,
    links: list[DiagramLink],
) -> str:
    """Generate complete Confluence storage format section for a diagram.

    Includes:
    - Embedded image (ac:image macro)
    - Download link for .drawio source
    - List of links found in diagram
    """
    sections = []

    # Image macro
    sections.append(
        f'<ac:image ac:align="center" ac:layout="center">'
        f'<ri:attachment ri:filename="{image_filename}" />'
        f'</ac:image>'
    )

    # Source file link
    sections.append(
        f'<p><em>Source: '
        f'<ac:link><ri:attachment ri:filename="{drawio_filename}" />'
        f'<ac:plain-text-link-body><![CDATA[{drawio_filename}]]></ac:plain-text-link-body>'
        f'</ac:link></em></p>'
    )

    # Links section
    if links:
        sections.append(generate_links_section(links))

    return "\n".join(sections)


def find_diagram_section(body: str, diagram_name: str) -> tuple[int, int]:
    """Find the start and end positions of an existing diagram section.

    Returns (start, end) positions, or (-1, -1) if not found.
    """
    # Look for markers we can use to identify the section
    # Pattern: ac:image with our filename, followed by source link, followed by links

    # Simple approach: find ac:image with our attachment
    patterns = [
        f'ri:filename="{diagram_name}.png"',
        f'ri:filename="{diagram_name}.svg"',
    ]

    for pattern in patterns:
        match = re.search(re.escape(pattern), body)
        if match:
            # Found the image - now find the section boundaries
            # Walk backwards to find ac:image start
            start = body.rfind("<ac:image", 0, match.start())
            if start == -1:
                continue

            # Walk forwards to find the end of the links section
            # Look for next ac:image, next h2/h3 heading, or end of content
            pos = match.end()

            # Find end of links section (</ul> after "Links in this diagram")
            links_end = body.find("</ul>", pos)
            if links_end != -1 and "Links in this diagram" in body[pos:links_end]:
                end = links_end + len("</ul>")
            else:
                # No links section, end after source link paragraph
                p_end = body.find("</p>", pos)
                if p_end != -1:
                    end = p_end + len("</p>")
                else:
                    end = match.end()

            return (start, end)

    return (-1, -1)


def update_page_body(
    body: str,
    diagram_name: str,
    image_filename: str,
    drawio_filename: str,
    links: list[DiagramLink],
) -> str:
    """Update page body with diagram section.

    If a section for this diagram exists, replace it.
    Otherwise, append to the end of the body.
    """
    new_section = generate_diagram_section(
        diagram_name, image_filename, drawio_filename, links
    )

    # Check if section exists
    start, end = find_diagram_section(body, diagram_name)

    if start >= 0:
        # Replace existing section
        return body[:start] + new_section + body[end:]
    else:
        # Append to end
        if body.strip():
            return body.rstrip() + "\n\n" + new_section
        else:
            return new_section


def publish_diagram(
    diagram_path: Path,
    config: Config,
    state: State,
    client: ConfluenceClient,
    page_id: Optional[str] = None,
    page_url: Optional[str] = None,
    update_page_content: bool = True,
    force_export: bool = False,
) -> PublishResult:
    """Publish a diagram to Confluence.

    Steps:
    1. Parse diagram and extract links
    2. Export to image format (PNG/SVG)
    3. Upload .drawio source as attachment
    4. Upload image as attachment
    5. Update page body with image macro and links

    Args:
        diagram_path: Path to .drawio file
        config: Application configuration
        state: State tracking
        client: Confluence API client
        page_id: Target page ID (overrides state)
        page_url: Target page URL (alternative to page_id)
        update_page_content: Whether to update page body
        force_export: Force re-export even if cached

    Returns:
        PublishResult with publish details
    """
    diagram_path = diagram_path.resolve()
    if not diagram_path.exists():
        raise PublishError(f"Diagram file not found: {diagram_path}")

    # Get diagram state
    rel_path = str(diagram_path.relative_to(config.config_dir.parent))
    diagram_state = state.get_diagram(rel_path)

    # Determine target page
    if page_id is None and page_url:
        page = client.get_page_by_url(page_url)
        page_id = page.id
    elif page_id is None and diagram_state and diagram_state.confluence_page_id:
        page_id = diagram_state.confluence_page_id
    elif page_id is None:
        raise PublishError(
            f"No Confluence page specified for {diagram_path.name}. "
            "Use --page option or link the diagram first."
        )

    # Get page info
    page = client.get_page_by_id(page_id, expand=["version", "space", "body.storage"])

    # Parse diagram
    diagram_info = parse_drawio_file(diagram_path)
    links = [DiagramLink(label=l.label, url=l.url) for l in diagram_info.links]

    # Export diagram
    export_format = config.export.default_format
    export_result: Optional[ExportResult] = None
    image_attachment: Optional[Attachment] = None

    try:
        export_result = export_diagram(
            source=diagram_path,
            format=export_format,
            export_config=config.export,
            editor_config=config.editor,
            force=force_export,
        )
    except Exception as e:
        # Export failed - check if we have a cached export
        existing = check_export_available(diagram_path, export_format)
        if existing:
            from dataclasses import dataclass as dc

            @dc
            class CachedResult:
                output_file: Path
                format: str

            export_result = CachedResult(output_file=existing, format=export_format)  # type: ignore
        else:
            # No export available - continue without image
            pass

    # Upload .drawio source
    drawio_attachment = client.upload_attachment_from_file(
        page_id=page_id,
        file_path=diagram_path,
        comment="Updated diagram source",
    )

    # Upload image if available
    if export_result and hasattr(export_result, 'output_file'):
        image_attachment = client.upload_attachment_from_file(
            page_id=page_id,
            file_path=export_result.output_file,
            comment="Updated diagram image",
        )

    # Update page content
    page_updated = False
    if update_page_content and image_attachment:
        diagram_name = diagram_path.stem
        image_filename = image_attachment.filename
        drawio_filename = drawio_attachment.filename

        # Convert links to the format expected by update_page_body
        link_objs = [
            DiagramLink(label=l.label, url=l.url) for l in diagram_info.links
        ]

        new_body = update_page_body(
            body=page.body_storage or "",
            diagram_name=diagram_name,
            image_filename=image_filename,
            drawio_filename=drawio_filename,
            links=link_objs,
        )

        if new_body != page.body_storage:
            try:
                client.update_page_content(
                    page_id=page_id,
                    title=page.title,
                    body=new_body,
                    version=page.version,
                )
                page_updated = True
            except ConflictError:
                raise PublishError(
                    "Page was modified since reading. Please try again."
                )

    # Update state
    if diagram_state is None:
        diagram_state = state.add_diagram(rel_path, page_id, page.url)
    else:
        diagram_state.confluence_page_id = page_id
        diagram_state.confluence_page_url = page.url

    diagram_state.last_attachment_version = drawio_attachment.version
    diagram_state.update_sync_time()
    diagram_state.links_in_diagram = [
        __import__("drawio_cli.state", fromlist=["DiagramLink"]).DiagramLink(
            label=l.label, url=l.url
        )
        for l in diagram_info.links
    ]
    state.save()

    return PublishResult(
        diagram_path=diagram_path,
        page_id=page_id,
        page_url=page.url,
        drawio_attachment=drawio_attachment,
        image_attachment=image_attachment,
        links_added=len(diagram_info.links),
        page_updated=page_updated,
    )


def checkout_diagram(
    page_url: str,
    output_dir: Path,
    config: Config,
    state: State,
    client: ConfluenceClient,
    filename: Optional[str] = None,
) -> Path:
    """Download a .drawio diagram from Confluence.

    Args:
        page_url: URL of the Confluence page
        output_dir: Directory to save the diagram
        config: Application configuration
        state: State tracking
        client: Confluence API client
        filename: Optional filename override

    Returns:
        Path to the downloaded file
    """
    # Get page info
    page = client.get_page_by_url(page_url)

    # Find .drawio attachment
    attachments = client.get_attachments(page.id)
    drawio_attachments = [a for a in attachments if a.filename.endswith(".drawio")]

    if not drawio_attachments:
        raise PublishError(f"No .drawio attachments found on page: {page.title}")

    if len(drawio_attachments) > 1 and filename is None:
        names = ", ".join(a.filename for a in drawio_attachments)
        raise PublishError(
            f"Multiple .drawio files found: {names}. "
            "Specify which one with --filename."
        )

    # Select attachment
    if filename:
        attachment = next(
            (a for a in drawio_attachments if a.filename == filename), None
        )
        if attachment is None:
            raise PublishError(f"Attachment not found: {filename}")
    else:
        attachment = drawio_attachments[0]

    # Download content
    content = client.download_attachment(page.id, attachment.filename)

    # Save to file
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / attachment.filename
    output_path.write_bytes(content)

    # Update state
    rel_path = str(output_path.relative_to(config.config_dir.parent))
    diagram_state = state.add_diagram(rel_path, page.id, page.url)
    diagram_state.last_attachment_version = attachment.version
    diagram_state.update_sync_time()
    diagram_state.update_local_modified(output_path.stat().st_mtime)
    state.save()

    return output_path
