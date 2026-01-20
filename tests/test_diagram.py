"""Tests for diagram parsing and link extraction."""

from pathlib import Path

import pytest

from drawio_cli.diagram import (
    parse_drawio_file,
    parse_drawio_content,
    extract_label_from_value,
    extract_links_from_html,
    create_empty_diagram,
    validate_drawio_file,
    DiagramParseError,
)


FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestParseDiagram:
    """Tests for parse_drawio_file and parse_drawio_content."""

    def test_parse_sample_file(self):
        """Test parsing the sample.drawio fixture."""
        info = parse_drawio_file(FIXTURES_DIR / "sample.drawio")

        assert info.name == "sample"
        assert len(info.pages) == 2
        assert "Architecture" in info.pages
        assert "Data Flow" in info.pages

    def test_parse_extracts_links(self):
        """Test that links are extracted from diagrams."""
        info = parse_drawio_file(FIXTURES_DIR / "sample.drawio")

        # Should find links from various cell types
        urls = [link.url for link in info.links]

        assert "https://api.example.com/docs" in urls
        assert "https://wiki.example.com/db-docs" in urls
        assert "https://external-api.example.com" in urls
        assert "https://docs.example.com/process" in urls

    def test_parse_extracts_labels(self):
        """Test that link labels are extracted."""
        info = parse_drawio_file(FIXTURES_DIR / "sample.drawio")

        labels = {link.label for link in info.links}

        assert "API Gateway" in labels
        assert "Database" in labels
        assert "External API" in labels

    def test_parse_deduplicates_links(self):
        """Test that duplicate links are removed."""
        # Create content with duplicate links
        content = '''<?xml version="1.0" encoding="UTF-8"?>
        <mxfile>
          <diagram name="Test">
            <mxGraphModel>
              <root>
                <mxCell id="0" />
                <mxCell id="1" parent="0" />
                <mxCell id="2" value="Link 1" style="link=https://example.com" />
                <mxCell id="3" value="Link 1" style="link=https://example.com" />
              </root>
            </mxGraphModel>
          </diagram>
        </mxfile>'''

        info = parse_drawio_content(content, "test")

        # Should deduplicate
        assert len(info.links) == 1
        assert info.links[0].url == "https://example.com"

    def test_parse_nonexistent_file(self):
        """Test parsing a nonexistent file raises error."""
        with pytest.raises(DiagramParseError, match="not found"):
            parse_drawio_file(Path("/nonexistent/file.drawio"))

    def test_parse_invalid_xml(self):
        """Test parsing invalid XML raises error."""
        with pytest.raises(DiagramParseError, match="Invalid XML"):
            parse_drawio_content("not valid xml <>>", "test")


class TestExtractLabel:
    """Tests for extract_label_from_value."""

    def test_plain_text(self):
        """Test extracting plain text."""
        assert extract_label_from_value("Hello World") == "Hello World"

    def test_html_content(self):
        """Test extracting text from HTML."""
        assert extract_label_from_value("<b>Bold</b> text") == "Bold text"

    def test_html_entities(self):
        """Test decoding HTML entities."""
        assert extract_label_from_value("A &amp; B") == "A & B"
        assert extract_label_from_value("&lt;tag&gt;") == "<tag>"

    def test_whitespace_normalization(self):
        """Test whitespace is normalized."""
        assert extract_label_from_value("  multiple   spaces  ") == "multiple spaces"

    def test_empty_value(self):
        """Test empty value returns empty string."""
        assert extract_label_from_value("") == ""
        assert extract_label_from_value(None) == ""


class TestExtractLinksFromHtml:
    """Tests for extract_links_from_html."""

    def test_single_link(self):
        """Test extracting a single link."""
        html = '<a href="https://example.com">Example</a>'
        links = extract_links_from_html(html)

        assert len(links) == 1
        assert links[0] == ("Example", "https://example.com")

    def test_multiple_links(self):
        """Test extracting multiple links."""
        html = '''
        <div>
            <a href="https://a.com">A</a>
            <a href="https://b.com">B</a>
        </div>
        '''
        links = extract_links_from_html(html)

        assert len(links) == 2
        assert ("A", "https://a.com") in links
        assert ("B", "https://b.com") in links

    def test_link_with_attributes(self):
        """Test link with extra attributes."""
        html = '<a class="link" href="https://example.com" target="_blank">Click</a>'
        links = extract_links_from_html(html)

        assert len(links) == 1
        assert links[0] == ("Click", "https://example.com")

    def test_empty_link_text(self):
        """Test link with no text uses URL as label."""
        html = '<a href="https://example.com"></a>'
        links = extract_links_from_html(html)

        assert len(links) == 1
        assert links[0][0] == "https://example.com"


class TestCreateEmptyDiagram:
    """Tests for create_empty_diagram."""

    def test_creates_valid_xml(self):
        """Test created diagram is valid XML."""
        content = create_empty_diagram("Test Diagram")

        # Should be parseable
        info = parse_drawio_content(content, "test")

        assert info.name == "test"
        assert len(info.pages) == 1

    def test_uses_provided_name(self):
        """Test diagram uses provided name."""
        content = create_empty_diagram("My Custom Name")

        assert "My Custom Name" in content


class TestValidateDrawioFile:
    """Tests for validate_drawio_file."""

    def test_valid_file(self):
        """Test validating a valid .drawio file."""
        assert validate_drawio_file(FIXTURES_DIR / "sample.drawio") is True

    def test_nonexistent_file(self):
        """Test validating nonexistent file returns False."""
        assert validate_drawio_file(Path("/nonexistent/file.drawio")) is False

    def test_wrong_extension(self, tmp_path):
        """Test validating file with wrong extension returns False."""
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("not a diagram")
        assert validate_drawio_file(txt_file) is False

    def test_invalid_xml(self, tmp_path):
        """Test validating file with invalid XML returns False."""
        bad_file = tmp_path / "bad.drawio"
        bad_file.write_text("not valid xml")
        assert validate_drawio_file(bad_file) is False

    def test_wrong_root_element(self, tmp_path):
        """Test validating XML with wrong root element returns False."""
        wrong_root = tmp_path / "wrong.drawio"
        wrong_root.write_text('<?xml version="1.0"?><html></html>')
        assert validate_drawio_file(wrong_root) is False
