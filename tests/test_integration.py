"""Integration tests for drawio-cli against a real Confluence instance.

These tests require a running Confluence server configured in .drawio-cli/config.yaml.
They are skipped if Confluence is not available.

Run with: pytest tests/test_integration.py -v
"""

import pytest
from pathlib import Path

from drawio_cli.config import load_config, find_workspace_root
from drawio_cli.confluence import ConfluenceClient, ConfluenceError
from drawio_cli.state import load_state
from drawio_cli.publisher import publish_diagram
from drawio_cli.diagram import create_empty_diagram


def get_test_client():
    """Get a Confluence client for testing, or None if not configured."""
    root = find_workspace_root()
    if root is None:
        return None, None

    config = load_config(root)
    if not config.confluence.is_configured():
        return None, None

    try:
        client = ConfluenceClient(config.confluence)
        if not client.test_connection():
            return None, None
        return client, config
    except Exception:
        return None, None


def get_first_space(client):
    """Get the first available space key."""
    response = client._request('GET', 'space', params={'limit': 1})
    spaces = response.json().get('results', [])
    if spaces:
        return spaces[0]['key']
    return None


@pytest.fixture(scope="module")
def confluence_setup():
    """Set up Confluence client and test page."""
    client, config = get_test_client()
    if client is None:
        pytest.skip("Confluence not configured or not available")

    space_key = get_first_space(client)
    if space_key is None:
        pytest.skip("No Confluence spaces available")

    # Create a test page
    data = {
        'type': 'page',
        'title': 'DrawIO CLI Integration Test Page',
        'space': {'key': space_key},
        'body': {
            'storage': {
                'value': '<p>Test page for drawio-cli integration tests</p>',
                'representation': 'storage'
            }
        }
    }

    try:
        response = client._request('POST', 'content', json=data)
        page = response.json()
        page_id = page['id']
        page_url = f"{config.confluence.base_url}{page['_links']['webui']}"
    except ConfluenceError as e:
        # Page might already exist
        if "already exists" in str(e).lower():
            page = client.get_page_by_title(space_key, 'DrawIO CLI Integration Test Page')
            page_id = page.id
            page_url = page.url
        else:
            raise

    yield {
        'client': client,
        'config': config,
        'page_id': page_id,
        'page_url': page_url,
        'space_key': space_key,
    }

    # Cleanup: delete the test page
    try:
        client._request('DELETE', f'content/{page_id}')
    except Exception:
        pass  # Ignore cleanup errors


class TestConfluenceConnection:
    """Test basic Confluence connectivity."""

    def test_connection(self, confluence_setup):
        """Test that we can connect to Confluence."""
        client = confluence_setup['client']
        assert client.test_connection()

    def test_list_spaces(self, confluence_setup):
        """Test that we can list spaces."""
        client = confluence_setup['client']
        response = client._request('GET', 'space', params={'limit': 5})
        spaces = response.json().get('results', [])
        assert len(spaces) > 0
        for space in spaces:
            print(f"  {space['key']}: {space['name']}")


class TestExportFormats:
    """Test different export formats."""

    @pytest.fixture
    def test_diagram(self, tmp_path):
        """Create a test diagram file."""
        diagram_path = tmp_path / "test-diagram.drawio"
        content = create_empty_diagram("test-diagram")
        diagram_path.write_text(content)
        return diagram_path

    def test_publish_png_format(self, confluence_setup, test_diagram, tmp_path):
        """Test publishing with PNG format (default)."""
        from drawio_cli.export import export_diagram, ExportError

        config = confluence_setup['config']

        # Try to export - may fail if desktop app not available
        try:
            result = export_diagram(
                source=test_diagram,
                format="png",
                export_config=config.export,
                editor_config=config.editor,
                force=True,
            )
            assert result.output_file.exists()
            assert result.format == "png"
            print(f"  Exported: {result.output_file}")
        except ExportError as e:
            pytest.skip(f"Export not available: {e}")

    def test_publish_svg_format(self, confluence_setup, test_diagram, tmp_path):
        """Test publishing with SVG format (with embedded diagram)."""
        from drawio_cli.export import export_diagram, ExportError

        config = confluence_setup['config']

        try:
            result = export_diagram(
                source=test_diagram,
                format="svg",
                export_config=config.export,
                editor_config=config.editor,
                force=True,
            )
            assert result.output_file.exists()
            assert result.format == "svg"

            # Check that SVG was created
            svg_content = result.output_file.read_text()
            assert "<svg" in svg_content
            print(f"  Exported: {result.output_file}")
        except ExportError as e:
            pytest.skip(f"Export not available: {e}")

    def test_publish_html_format(self, confluence_setup, test_diagram, tmp_path):
        """Test publishing with HTML format."""
        from drawio_cli.export import export_diagram, ExportError

        config = confluence_setup['config']

        try:
            result = export_diagram(
                source=test_diagram,
                format="html",
                export_config=config.export,
                editor_config=config.editor,
                force=True,
            )
            assert result.output_file.exists()
            assert result.format == "html"
            print(f"  Exported: {result.output_file}")
        except ExportError as e:
            pytest.skip(f"Export not available: {e}")


class TestStateExportFormat:
    """Test that export format is stored in state."""

    def test_state_stores_export_format(self, tmp_path):
        """Test that DiagramState stores export_format correctly."""
        from drawio_cli.state import DiagramState, State

        # Create state with export format
        state = State()
        state._state_file = tmp_path / "state.json"

        diagram = state.add_diagram("test.drawio", "12345", "http://example.com/page")
        diagram.export_format = "svg"
        state.save()

        # Reload and verify
        state2 = load_state(tmp_path / "state.json")
        diagram2 = state2.get_diagram("test.drawio")

        assert diagram2 is not None
        assert diagram2.export_format == "svg"

    def test_state_format_in_json(self, tmp_path):
        """Test that export_format appears in state.json."""
        import json
        from drawio_cli.state import State

        state = State()
        state._state_file = tmp_path / "state.json"

        diagram = state.add_diagram("test.drawio")
        diagram.export_format = "html"
        state.save()

        # Read raw JSON
        with open(tmp_path / "state.json") as f:
            data = json.load(f)

        assert "export_format" in data["diagrams"]["test.drawio"]
        assert data["diagrams"]["test.drawio"]["export_format"] == "html"


class TestPublishWithFormat:
    """Test full publish workflow with different formats."""

    def test_publish_to_confluence_svg(self, confluence_setup):
        """Test publishing a diagram to Confluence as SVG."""
        from drawio_cli.export import ExportError

        client = confluence_setup['client']
        config = confluence_setup['config']
        page_id = confluence_setup['page_id']

        # Create test diagram in workspace directory
        workspace_root = config.config_dir.parent
        diagram_path = workspace_root / "test-architecture.drawio"
        content = create_empty_diagram("test-architecture")
        diagram_path.write_text(content)

        try:
            # Load state from workspace
            state = load_state(config.state_file)

            # Publish with SVG format
            try:
                result = publish_diagram(
                    diagram_path=diagram_path,
                    config=config,
                    state=state,
                    client=client,
                    page_id=page_id,
                    export_format="svg",
                )

                print(f"  Published to: {result.page_url}")
                print(f"  .drawio attachment: v{result.drawio_attachment.version}")
                if result.image_attachment:
                    print(f"  Image attachment: {result.image_attachment.filename}")

                # Verify attachments
                attachments = client.get_attachments(page_id)
                filenames = [a.filename for a in attachments]

                assert "test-architecture.drawio" in filenames
                # SVG should be attached if export succeeded
                if result.image_attachment:
                    assert "test-architecture.svg" in filenames

            except ExportError as e:
                pytest.skip(f"Export not available: {e}")
        finally:
            # Cleanup test diagram
            if diagram_path.exists():
                diagram_path.unlink()
            svg_path = diagram_path.with_suffix(".svg")
            if svg_path.exists():
                svg_path.unlink()

    def test_publish_to_confluence_html(self, confluence_setup):
        """Test publishing a diagram to Confluence as HTML."""
        from drawio_cli.export import ExportError

        client = confluence_setup['client']
        config = confluence_setup['config']
        page_id = confluence_setup['page_id']

        # Create test diagram in workspace directory
        workspace_root = config.config_dir.parent
        diagram_path = workspace_root / "test-flowchart.drawio"
        content = create_empty_diagram("test-flowchart")
        diagram_path.write_text(content)

        try:
            # Load state from workspace
            state = load_state(config.state_file)

            # Publish with HTML format
            try:
                result = publish_diagram(
                    diagram_path=diagram_path,
                    config=config,
                    state=state,
                    client=client,
                    page_id=page_id,
                    export_format="html",
                )

                print(f"  Published to: {result.page_url}")

                # Verify page content has download link for HTML
                page = client.get_page_by_id(page_id, expand=["body.storage"])
                if result.image_attachment:
                    assert "test-flowchart.html" in page.body_storage
                    assert "Interactive diagram" in page.body_storage

            except ExportError as e:
                pytest.skip(f"Export not available: {e}")
        finally:
            # Cleanup test diagram
            if diagram_path.exists():
                diagram_path.unlink()
            html_path = diagram_path.with_suffix(".html")
            if html_path.exists():
                html_path.unlink()


class TestGenerateDiagramSection:
    """Test Confluence content generation for different formats."""

    def test_svg_generates_image_macro(self):
        """Test that SVG format generates ac:image macro."""
        from drawio_cli.publisher import generate_diagram_section

        section = generate_diagram_section(
            diagram_name="test",
            image_filename="test.svg",
            drawio_filename="test.drawio",
            links=[],
        )

        assert "<ac:image" in section
        assert 'ri:filename="test.svg"' in section
        assert "Interactive diagram" not in section

    def test_html_generates_download_link(self):
        """Test that HTML format generates download link instead of image."""
        from drawio_cli.publisher import generate_diagram_section

        section = generate_diagram_section(
            diagram_name="test",
            image_filename="test.html",
            drawio_filename="test.drawio",
            links=[],
        )

        assert "<ac:image" not in section
        assert "Interactive diagram" in section
        assert 'ri:filename="test.html"' in section
        assert "Open test.html" in section

    def test_png_generates_image_macro(self):
        """Test that PNG format generates ac:image macro."""
        from drawio_cli.publisher import generate_diagram_section

        section = generate_diagram_section(
            diagram_name="test",
            image_filename="test.png",
            drawio_filename="test.drawio",
            links=[],
        )

        assert "<ac:image" in section
        assert 'ri:filename="test.png"' in section


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
