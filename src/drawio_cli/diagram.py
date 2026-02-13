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
            # Get all attributes for placeholder resolution
            props = dict(obj.attrib)
            label_text = extract_label_from_object(label, props) or f"Link {cell_id}"
            links.append(DiagramLink(label=label_text, url=link, cell_id=cell_id))

    # Check for object elements (another variation)
    for obj in model.findall(".//object"):
        cell_id = obj.get("id")
        label = obj.get("label", "")
        link = obj.get("link", "")

        if link:
            # Get all attributes for placeholder resolution
            props = dict(obj.attrib)
            label_text = extract_label_from_object(label, props) or f"Link {cell_id}"
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


def extract_label_from_object(label: str, props: dict[str, str]) -> str:
    """Extract label from an object element, resolving placeholders.

    Handles:
    - C4 model shapes (c4Name, c4Type, etc.)
    - Generic placeholders like %name%
    - Falls back to stripping HTML from label

    Args:
        label: The label attribute (may contain HTML and placeholders)
        props: All attributes from the object element
    """
    # Priority order for finding a good label:
    # 1. c4Name (C4 model shapes)
    # 2. name property
    # 3. title property
    # 4. Resolve placeholders in label
    # 5. Strip HTML from label

    # Check for C4 model properties first
    c4_name = props.get("c4Name", "").strip()
    if c4_name:
        return c4_name

    # Check for generic name/title properties
    name = props.get("name", "").strip()
    if name:
        return name

    title = props.get("title", "").strip()
    if title:
        return title

    # If label contains placeholders like %c4Name%, try to resolve them
    if label and "%" in label:
        resolved = resolve_placeholders(label, props)
        # Only use resolved if it produced meaningful text
        resolved_clean = extract_label_from_value(resolved)
        if resolved_clean and resolved_clean != label:
            return resolved_clean

    # Fall back to extracting text from label
    return extract_label_from_value(label)


def resolve_placeholders(text: str, props: dict[str, str]) -> str:
    """Resolve %placeholder% patterns using properties.

    Args:
        text: Text containing %placeholder% patterns
        props: Dictionary of property values
    """
    def replace_placeholder(match: re.Match) -> str:
        key = match.group(1)
        # Try exact match first, then case-insensitive
        if key in props:
            return props[key]
        # Case-insensitive lookup
        for prop_key, prop_val in props.items():
            if prop_key.lower() == key.lower():
                return prop_val
        # Return empty string for unresolved placeholders
        return ""

    # Replace all %placeholder% patterns
    return re.sub(r'%([^%]+)%', replace_placeholder, text)


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


def create_empty_diagram(name: str = "Untitled Diagram", with_sample_content: bool = False) -> str:
    """Create a .drawio diagram XML.

    Args:
        name: The diagram name
        with_sample_content: If True, include a sample shape for visibility in exports

    Creates a landscape A4 diagram with page view disabled for a cleaner editing experience.
    """
    # Landscape A4: 1169x827 (swapped from portrait 827x1169)
    # page="0" disables page view for cleaner infinite canvas
    if with_sample_content:
        # Include a sample rectangle with the diagram name for visible exports
        content = f'''<?xml version="1.0" encoding="UTF-8"?>
<mxfile host="app.diagrams.net" modified="{_current_timestamp()}" type="device">
  <diagram id="diagram-1" name="{name}">
    <mxGraphModel dx="1434" dy="836" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="0" pageScale="1" pageWidth="1169" pageHeight="827" math="0" shadow="0">
      <root>
        <mxCell id="0" />
        <mxCell id="1" parent="0" />
        <mxCell id="2" value="{name}" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;fontSize=14;fontStyle=1" vertex="1" parent="1">
          <mxGeometry x="100" y="100" width="200" height="80" as="geometry" />
        </mxCell>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>'''
    else:
        content = f'''<?xml version="1.0" encoding="UTF-8"?>
<mxfile host="app.diagrams.net" modified="{_current_timestamp()}" type="device">
  <diagram id="diagram-1" name="{name}">
    <mxGraphModel dx="1434" dy="836" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="0" pageScale="1" pageWidth="1169" pageHeight="827" math="0" shadow="0">
      <root>
        <mxCell id="0" />
        <mxCell id="1" parent="0" />
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>'''
    return content


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
