"""Draw.io diagram file parsing and link extraction."""

import base64
import re
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import unquote
import xml.etree.ElementTree as ET


@dataclass
class DiagramLink:
    """A hyperlink found in a diagram."""

    label: str
    url: str
    cell_id: Optional[str] = None

    def __hash__(self):
        return hash((self.label, self.url))

    def __eq__(self, other):
        if not isinstance(other, DiagramLink):
            return False
        return self.label == other.label and self.url == other.url


@dataclass
class DiagramInfo:
    """Information about a draw.io diagram."""

    name: str
    pages: list[str]
    links: list[DiagramLink]


class DiagramParseError(Exception):
    """Error parsing a .drawio file."""

    pass


def decode_diagram_content(encoded: str) -> str:
    """Decode compressed diagram content.

    Draw.io compresses diagram content using:
    1. URL encoding
    2. Base64 encoding
    3. Deflate compression
    """
    try:
        # URL decode
        decoded = unquote(encoded)
        # Base64 decode
        decoded_bytes = base64.b64decode(decoded)
        # Decompress (raw deflate, negative wbits)
        decompressed = zlib.decompress(decoded_bytes, -zlib.MAX_WBITS)
        # URL decode the result
        return unquote(decompressed.decode("utf-8"))
    except Exception:
        # If decoding fails, content might not be compressed
        return encoded


def parse_drawio_file(file_path: Path) -> DiagramInfo:
    """Parse a .drawio file and extract information."""
    if not file_path.exists():
        raise DiagramParseError(f"File not found: {file_path}")

    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
    except ET.ParseError as e:
        raise DiagramParseError(f"Invalid XML: {e}")

    return parse_drawio_xml(root, file_path.stem)


def parse_drawio_content(content: str, name: str = "diagram") -> DiagramInfo:
    """Parse .drawio content from a string."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        raise DiagramParseError(f"Invalid XML: {e}")

    return parse_drawio_xml(root, name)


def parse_drawio_xml(root: ET.Element, name: str) -> DiagramInfo:
    """Parse draw.io XML structure."""
    pages = []
    links = []

    # Draw.io files have <mxfile> root with <diagram> children
    if root.tag == "mxfile":
        for diagram in root.findall(".//diagram"):
            page_name = diagram.get("name", "Page")
            pages.append(page_name)

            # Get diagram content - may be compressed in text or as mxGraphModel child
            content = diagram.text
            mx_model = diagram.find("mxGraphModel")

            if mx_model is not None:
                # Direct XML content
                links.extend(extract_links_from_graph_model(mx_model))
            elif content:
                # Compressed content
                try:
                    decoded = decode_diagram_content(content.strip())
                    decoded_root = ET.fromstring(decoded)
                    links.extend(extract_links_from_graph_model(decoded_root))
                except Exception:
                    # Skip pages that can't be decoded
                    pass

    elif root.tag == "mxGraphModel":
        # Standalone mxGraphModel (older format or exported)
        pages.append(name)
        links.extend(extract_links_from_graph_model(root))

    # Deduplicate links
    unique_links = list(dict.fromkeys(links))

    return DiagramInfo(name=name, pages=pages, links=unique_links)


def extract_links_from_graph_model(model: ET.Element) -> list[DiagramLink]:
    """Extract all hyperlinks from an mxGraphModel element."""
    links = []

    # Find all mxCell elements
    for cell in model.findall(".//mxCell"):
        cell_id = cell.get("id")
        value = cell.get("value", "")
        style = cell.get("style", "")

        # Check for link in style attribute
        link_match = re.search(r'link=([^;]+)', style)
        if link_match:
            url = unquote(link_match.group(1))
            label = extract_label_from_value(value) or f"Link {cell_id}"
            links.append(DiagramLink(label=label, url=url, cell_id=cell_id))

        # Check for links in HTML value (cells can contain HTML with <a> tags)
        if value and "<a " in value.lower():
            html_links = extract_links_from_html(value)
            for label, url in html_links:
                links.append(DiagramLink(label=label, url=url, cell_id=cell_id))

    # Also check UserObject elements (alternative cell representation)
    for obj in model.findall(".//UserObject"):
        cell_id = obj.get("id")
        label = obj.get("label", "")
        link = obj.get("link", "")

        if link:
            label_text = extract_label_from_value(label) or f"Link {cell_id}"
            links.append(DiagramLink(label=label_text, url=link, cell_id=cell_id))

    # Check for object elements (another variation)
    for obj in model.findall(".//object"):
        cell_id = obj.get("id")
        label = obj.get("label", "")
        link = obj.get("link", "")

        if link:
            label_text = extract_label_from_value(label) or f"Link {cell_id}"
            links.append(DiagramLink(label=label_text, url=link, cell_id=cell_id))

    return links


def extract_label_from_value(value: str) -> str:
    """Extract plain text label from a cell value (may contain HTML)."""
    if not value:
        return ""

    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', value)
    # Decode HTML entities
    text = text.replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&amp;", "&").replace("&quot;", '"')
    text = text.replace("&nbsp;", " ")
    # Clean up whitespace
    text = " ".join(text.split())

    return text.strip()


def extract_links_from_html(html: str) -> list[tuple[str, str]]:
    """Extract links from HTML content."""
    links = []

    # Find all <a href="...">text</a> patterns
    pattern = r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>([^<]*)</a>'
    matches = re.findall(pattern, html, re.IGNORECASE)

    for url, text in matches:
        label = text.strip() if text.strip() else url
        links.append((label, url))

    return links


def create_empty_diagram(name: str = "Untitled Diagram") -> str:
    """Create an empty .drawio diagram XML."""
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<mxfile host="app.diagrams.net" modified="{_current_timestamp()}" type="device">
  <diagram id="diagram-1" name="{name}">
    <mxGraphModel dx="1434" dy="836" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="827" pageHeight="1169" math="0" shadow="0">
      <root>
        <mxCell id="0" />
        <mxCell id="1" parent="0" />
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>'''


def _current_timestamp() -> str:
    """Get current timestamp in draw.io format."""
    from datetime import datetime

    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")


def get_diagram_modified_time(file_path: Path) -> Optional[float]:
    """Get the modification time of a diagram file."""
    if file_path.exists():
        return file_path.stat().st_mtime
    return None


def validate_drawio_file(file_path: Path) -> bool:
    """Validate that a file is a valid .drawio file."""
    if not file_path.exists():
        return False

    if file_path.suffix.lower() not in [".drawio", ".xml"]:
        return False

    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
        # Valid draw.io files have mxfile or mxGraphModel as root
        return root.tag in ["mxfile", "mxGraphModel"]
    except ET.ParseError:
        return False
