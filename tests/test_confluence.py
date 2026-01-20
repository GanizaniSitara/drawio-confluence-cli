"""Tests for Confluence API client."""

import json
from unittest.mock import patch, MagicMock

import pytest
import responses

from drawio_cli.config import ConfluenceConfig
from drawio_cli.confluence import (
    ConfluenceClient,
    ConfluenceError,
    AuthenticationError,
    NotFoundError,
    ConflictError,
    Page,
    Attachment,
)


@pytest.fixture
def confluence_config():
    """Create a test Confluence configuration."""
    config = ConfluenceConfig(
        base_url="https://wiki.example.com",
        auth_type="pat",
    )
    return config


@pytest.fixture
def mock_pat(monkeypatch):
    """Mock the PAT environment variable."""
    monkeypatch.setenv("CONFLUENCE_PAT", "test-token-123")


@pytest.fixture
def client(confluence_config, mock_pat):
    """Create a test Confluence client."""
    return ConfluenceClient(confluence_config)


class TestConfluenceConfig:
    """Tests for ConfluenceConfig."""

    def test_pat_from_env(self, monkeypatch):
        """Test PAT is read from environment."""
        monkeypatch.setenv("CONFLUENCE_PAT", "my-token")
        config = ConfluenceConfig(base_url="https://test.com", auth_type="pat")

        assert config.pat == "my-token"
        assert config.get_auth() == "my-token"

    def test_basic_auth_from_env(self, monkeypatch):
        """Test basic auth credentials from environment."""
        monkeypatch.setenv("CONFLUENCE_USER", "myuser")
        monkeypatch.setenv("CONFLUENCE_PASS", "mypass")
        config = ConfluenceConfig(base_url="https://test.com", auth_type="basic")

        assert config.username == "myuser"
        assert config.password == "mypass"
        assert config.get_auth() == ("myuser", "mypass")

    def test_is_configured_with_pat(self, monkeypatch):
        """Test is_configured with PAT."""
        monkeypatch.setenv("CONFLUENCE_PAT", "token")
        config = ConfluenceConfig(base_url="https://test.com", auth_type="pat")

        assert config.is_configured() is True

    def test_is_configured_without_credentials(self, monkeypatch):
        """Test is_configured without credentials."""
        monkeypatch.delenv("CONFLUENCE_PAT", raising=False)
        config = ConfluenceConfig(base_url="https://test.com", auth_type="pat")

        assert config.is_configured() is False

    def test_is_configured_without_base_url(self, monkeypatch):
        """Test is_configured without base URL."""
        monkeypatch.setenv("CONFLUENCE_PAT", "token")
        config = ConfluenceConfig(base_url="", auth_type="pat")

        assert config.is_configured() is False


class TestConfluenceClient:
    """Tests for ConfluenceClient."""

    def test_auth_header_set(self, client):
        """Test authorization header is set for PAT."""
        assert "Authorization" in client.session.headers
        assert client.session.headers["Authorization"] == "Bearer test-token-123"

    def test_no_credentials_raises(self, confluence_config, monkeypatch):
        """Test client creation without credentials raises error."""
        monkeypatch.delenv("CONFLUENCE_PAT", raising=False)

        with pytest.raises(AuthenticationError):
            ConfluenceClient(confluence_config)

    @responses.activate
    def test_get_page_by_id(self, client):
        """Test getting a page by ID."""
        responses.add(
            responses.GET,
            "https://wiki.example.com/rest/api/content/12345",
            json={
                "id": "12345",
                "title": "Test Page",
                "type": "page",
                "space": {"key": "TEST"},
                "version": {"number": 5},
                "body": {"storage": {"value": "<p>Content</p>"}},
                "_links": {"webui": "/display/TEST/Test+Page"},
            },
            status=200,
        )

        page = client.get_page_by_id("12345", expand=["version", "space", "body.storage"])

        assert page.id == "12345"
        assert page.title == "Test Page"
        assert page.space_key == "TEST"
        assert page.version == 5
        assert page.body_storage == "<p>Content</p>"

    @responses.activate
    def test_get_page_not_found(self, client):
        """Test getting nonexistent page raises error."""
        responses.add(
            responses.GET,
            "https://wiki.example.com/rest/api/content/99999",
            json={"message": "Not found"},
            status=404,
        )

        with pytest.raises(NotFoundError):
            client.get_page_by_id("99999")

    @responses.activate
    def test_authentication_failure(self, client):
        """Test authentication failure raises error."""
        responses.add(
            responses.GET,
            "https://wiki.example.com/rest/api/content/12345",
            json={"message": "Unauthorized"},
            status=401,
        )

        with pytest.raises(AuthenticationError):
            client.get_page_by_id("12345")

    @responses.activate
    def test_get_attachments(self, client):
        """Test getting page attachments."""
        responses.add(
            responses.GET,
            "https://wiki.example.com/rest/api/content/12345/child/attachment",
            json={
                "results": [
                    {
                        "id": "att1",
                        "title": "diagram.drawio",
                        "type": "attachment",
                        "version": {"number": 3},
                        "extensions": {"mediaType": "application/vnd.jgraph.mxfile"},
                        "_links": {"download": "/download/attachments/12345/diagram.drawio"},
                    },
                    {
                        "id": "att2",
                        "title": "diagram.png",
                        "type": "attachment",
                        "version": {"number": 2},
                        "extensions": {"mediaType": "image/png"},
                        "_links": {"download": "/download/attachments/12345/diagram.png"},
                    },
                ]
            },
            status=200,
        )

        attachments = client.get_attachments("12345")

        assert len(attachments) == 2
        assert attachments[0].filename == "diagram.drawio"
        assert attachments[0].version == 3
        assert attachments[1].filename == "diagram.png"

    @responses.activate
    def test_upload_attachment_new(self, client):
        """Test uploading a new attachment."""
        responses.add(
            responses.GET,
            "https://wiki.example.com/rest/api/content/12345/child/attachment",
            json={"results": []},
            status=200,
        )
        responses.add(
            responses.POST,
            "https://wiki.example.com/rest/api/content/12345/child/attachment",
            json={
                "results": [
                    {
                        "id": "att-new",
                        "title": "new.drawio",
                        "type": "attachment",
                        "version": {"number": 1},
                        "extensions": {"mediaType": "application/vnd.jgraph.mxfile"},
                        "_links": {"download": "/download/attachments/12345/new.drawio"},
                    }
                ]
            },
            status=200,
        )

        attachment = client.upload_attachment(
            page_id="12345",
            filename="new.drawio",
            content=b"<mxfile></mxfile>",
            media_type="application/vnd.jgraph.mxfile",
        )

        assert attachment.filename == "new.drawio"
        assert attachment.version == 1

    @responses.activate
    def test_update_page_content(self, client):
        """Test updating page content."""
        responses.add(
            responses.PUT,
            "https://wiki.example.com/rest/api/content/12345",
            json={
                "id": "12345",
                "title": "Test Page",
                "type": "page",
                "space": {"key": "TEST"},
                "version": {"number": 6},
                "_links": {"webui": "/display/TEST/Test+Page"},
            },
            status=200,
        )

        page = client.update_page_content(
            page_id="12345",
            title="Test Page",
            body="<p>New content</p>",
            version=5,
        )

        assert page.version == 6

    @responses.activate
    def test_update_page_conflict(self, client):
        """Test page update conflict raises error."""
        responses.add(
            responses.PUT,
            "https://wiki.example.com/rest/api/content/12345",
            json={"message": "Version conflict"},
            status=409,
        )

        with pytest.raises(ConflictError):
            client.update_page_content(
                page_id="12345",
                title="Test Page",
                body="<p>New content</p>",
                version=5,
            )

    @responses.activate
    def test_test_connection_success(self, client):
        """Test connection test succeeds."""
        responses.add(
            responses.GET,
            "https://wiki.example.com/rest/api/space",
            json={"results": []},
            status=200,
        )

        assert client.test_connection() is True

    @responses.activate
    def test_test_connection_failure(self, client):
        """Test connection test fails on error."""
        responses.add(
            responses.GET,
            "https://wiki.example.com/rest/api/space",
            json={"message": "Error"},
            status=500,
        )

        assert client.test_connection() is False


class TestPageUrlParsing:
    """Tests for parsing Confluence page URLs."""

    @responses.activate
    def test_parse_display_url(self, client):
        """Test parsing /display/SPACE/Title URLs."""
        responses.add(
            responses.GET,
            "https://wiki.example.com/rest/api/content",
            json={
                "results": [
                    {
                        "id": "12345",
                        "title": "My Page",
                        "space": {"key": "SPACE"},
                        "version": {"number": 1},
                        "_links": {"webui": "/display/SPACE/My+Page"},
                    }
                ]
            },
            status=200,
        )

        page = client.get_page_by_url("https://wiki.example.com/display/SPACE/My+Page")

        assert page.id == "12345"
        assert page.title == "My Page"

    @responses.activate
    def test_parse_viewpage_url(self, client):
        """Test parsing /pages/viewpage.action?pageId=X URLs."""
        responses.add(
            responses.GET,
            "https://wiki.example.com/rest/api/content/67890",
            json={
                "id": "67890",
                "title": "Another Page",
                "space": {"key": "TEST"},
                "version": {"number": 2},
                "_links": {"webui": "/pages/viewpage.action?pageId=67890"},
            },
            status=200,
        )

        page = client.get_page_by_url(
            "https://wiki.example.com/pages/viewpage.action?pageId=67890"
        )

        assert page.id == "67890"
        assert page.title == "Another Page"

    @responses.activate
    def test_parse_spaces_url(self, client):
        """Test parsing /spaces/SPACE/pages/ID/Title URLs."""
        responses.add(
            responses.GET,
            "https://wiki.example.com/rest/api/content/11111",
            json={
                "id": "11111",
                "title": "Page Title",
                "space": {"key": "MYSPACE"},
                "version": {"number": 3},
                "_links": {"webui": "/spaces/MYSPACE/pages/11111/Page+Title"},
            },
            status=200,
        )

        page = client.get_page_by_url(
            "https://wiki.example.com/spaces/MYSPACE/pages/11111/Page+Title"
        )

        assert page.id == "11111"

    def test_parse_invalid_url(self, client):
        """Test parsing invalid URL raises error."""
        with pytest.raises(ValueError, match="Could not parse"):
            client.get_page_by_url("https://wiki.example.com/invalid/path")
