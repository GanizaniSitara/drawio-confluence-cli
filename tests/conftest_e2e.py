"""Shared utilities for end-to-end Confluence tests."""

import sys
from pathlib import Path
from typing import Optional

# Add src and tests to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from test_config import (
    CONFLUENCE_BASE_URL,
    CONFLUENCE_USERNAME,
    CONFLUENCE_PASSWORD,
    TEST_SPACE_KEY,
    TEST_PAGE_PREFIX,
)

from drawio_cli.config import ConfluenceConfig, ExportConfig, EditorConfig, Config
from drawio_cli.confluence import ConfluenceClient


def get_test_output_dir() -> Path:
    """Get the test output directory, creating it if needed."""
    output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(exist_ok=True)
    return output_dir


def get_fixtures_dir() -> Path:
    """Get the fixtures directory."""
    return Path(__file__).parent / "fixtures"


def get_confluence_config() -> ConfluenceConfig:
    """Create a ConfluenceConfig for testing."""
    return ConfluenceConfig(
        base_url=CONFLUENCE_BASE_URL,
        auth_type="basic",
        ssl_verify=False,
        _username=CONFLUENCE_USERNAME,
        _password=CONFLUENCE_PASSWORD,
    )


def get_test_config() -> Config:
    """Create a full Config for testing."""
    workspace = Path(__file__).parent.parent
    return Config(
        confluence=get_confluence_config(),
        export=ExportConfig(),
        editor=EditorConfig(),
        _workspace_root=workspace,
    )


def get_confluence_client() -> ConfluenceClient:
    """Create a ConfluenceClient for testing."""
    return ConfluenceClient(get_confluence_config())


def get_test_space_key(client: ConfluenceClient) -> str:
    """Get the space key for tests.

    Uses TEST_SPACE_KEY from config if set, otherwise first available space.
    """
    if TEST_SPACE_KEY:
        return TEST_SPACE_KEY
    response = client._request('GET', 'space', params={'limit': 1})
    spaces = response.json().get('results', [])
    if not spaces:
        raise RuntimeError("No spaces available in Confluence")
    return spaces[0]['key']


def get_test_page_title(suffix: str) -> str:
    """Get a test page title with the configured prefix."""
    return f"{TEST_PAGE_PREFIX} - {suffix}"


def create_test_page(client: ConfluenceClient, title: str, space_key: Optional[str] = None) -> str:
    """Create a test page in Confluence.

    Args:
        client: The Confluence client
        title: Page title
        space_key: Optional space key (uses TEST_SPACE_KEY or first available)

    Returns:
        The page ID
    """
    if space_key is None:
        space_key = get_test_space_key(client)

    data = {
        'type': 'page',
        'title': title,
        'space': {'key': space_key},
        'body': {
            'storage': {
                'value': f'<p>Test page: {title}</p>',
                'representation': 'storage'
            }
        }
    }

    try:
        response = client._request('POST', 'content', json=data)
        page = response.json()
        return page['id']
    except Exception as e:
        if "already exists" in str(e).lower():
            page = client.get_page_by_title(space_key, title)
            return page.id
        raise


def delete_test_page(client: ConfluenceClient, page_id: str) -> bool:
    """Delete a test page from Confluence.

    Args:
        client: The Confluence client
        page_id: The page ID to delete

    Returns:
        True if deleted successfully, False otherwise
    """
    try:
        client._request('DELETE', f'content/{page_id}')
        return True
    except Exception as e:
        print(f"Warning: Could not delete page {page_id}: {e}")
        return False


def get_page_url(page_id: str) -> str:
    """Get the URL to view a page."""
    return f"{CONFLUENCE_BASE_URL}/pages/viewpage.action?pageId={page_id}"
