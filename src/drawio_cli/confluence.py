"""Confluence REST API client for Server/Data Center."""

import re
import urllib3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse, parse_qs

import requests

from .config import ConfluenceConfig


class ConfluenceError(Exception):
    """Base exception for Confluence API errors."""

    pass


class AuthenticationError(ConfluenceError):
    """Authentication failed."""

    pass


class NotFoundError(ConfluenceError):
    """Resource not found."""

    pass


class ConflictError(ConfluenceError):
    """Version conflict detected."""

    pass


@dataclass
class Page:
    """Confluence page information."""

    id: str
    title: str
    space_key: str
    version: int
    url: str
    body_storage: Optional[str] = None


@dataclass
class Attachment:
    """Confluence attachment information."""

    id: str
    title: str
    filename: str
    media_type: str
    version: int
    download_url: str


class ConfluenceClient:
    """Client for Confluence Server/Data Center REST API."""

    def __init__(self, config: ConfluenceConfig):
        """Initialize client with configuration."""
        self.config = config
        self.base_url = config.base_url.rstrip("/")
        self.api_url = f"{self.base_url}/rest/api"
        self.session = requests.Session()

        # Configure SSL verification
        self.session.verify = config.ssl_verify
        if not config.ssl_verify:
            # Suppress InsecureRequestWarning when SSL verification is disabled
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        self._setup_auth()

    def _setup_auth(self) -> None:
        """Set up authentication for the session."""
        auth = self.config.get_auth()
        if auth is None:
            raise AuthenticationError(
                "No authentication configured. Set CONFLUENCE_PAT or "
                "CONFLUENCE_USER/CONFLUENCE_PASS environment variables."
            )

        if isinstance(auth, str):
            # PAT authentication
            self.session.headers["Authorization"] = f"Bearer {auth}"
        else:
            # Basic authentication
            self.session.auth = auth

    def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs,
    ) -> requests.Response:
        """Make an API request."""
        url = f"{self.api_url}/{endpoint.lstrip('/')}"
        response = self.session.request(method, url, **kwargs)

        if response.status_code == 401:
            raise AuthenticationError("Authentication failed. Check your credentials.")
        elif response.status_code == 404:
            raise NotFoundError(f"Resource not found: {endpoint}")
        elif response.status_code == 409:
            raise ConflictError("Version conflict detected. Page may have been modified.")
        elif not response.ok:
            raise ConfluenceError(
                f"API request failed: {response.status_code} - {response.text}"
            )

        return response

    def get_page_by_id(self, page_id: str, expand: Optional[list[str]] = None) -> Page:
        """Get page by ID."""
        params = {}
        if expand:
            params["expand"] = ",".join(expand)

        response = self._request("GET", f"content/{page_id}", params=params)
        data = response.json()

        return self._parse_page(data)

    def get_page_by_url(self, page_url: str) -> Page:
        """Get page by its URL.

        Supports various Confluence URL formats:
        - /display/SPACE/Title
        - /pages/viewpage.action?pageId=123456
        - /spaces/SPACE/pages/123456/Title
        """
        parsed = urlparse(page_url)
        path = parsed.path

        # Try to extract page ID from URL
        page_id = None

        # Format: /pages/viewpage.action?pageId=123456
        if "viewpage.action" in path:
            query = parse_qs(parsed.query)
            if "pageId" in query:
                page_id = query["pageId"][0]

        # Format: /spaces/SPACE/pages/123456/Title
        match = re.search(r"/pages/(\d+)", path)
        if match:
            page_id = match.group(1)

        if page_id:
            return self.get_page_by_id(page_id, expand=["version", "space", "body.storage"])

        # Format: /display/SPACE/Title
        match = re.match(r".*/display/([^/]+)/(.+)$", path)
        if match:
            space_key = match.group(1)
            title = match.group(2).replace("+", " ").replace("%20", " ")
            return self.get_page_by_title(space_key, title)

        raise ValueError(f"Could not parse page URL: {page_url}")

    def get_page_by_title(self, space_key: str, title: str) -> Page:
        """Get page by space key and title."""
        params = {
            "spaceKey": space_key,
            "title": title,
            "expand": "version,space,body.storage",
        }
        response = self._request("GET", "content", params=params)
        data = response.json()

        results = data.get("results", [])
        if not results:
            raise NotFoundError(f"Page not found: {space_key}/{title}")

        return self._parse_page(results[0])

    def _parse_page(self, data: dict) -> Page:
        """Parse page data from API response."""
        space = data.get("space", {})
        version = data.get("version", {})
        body = data.get("body", {}).get("storage", {})

        # Build URL
        base = self.base_url
        links = data.get("_links", {})
        webui = links.get("webui", "")
        url = f"{base}{webui}" if webui else ""

        return Page(
            id=data["id"],
            title=data["title"],
            space_key=space.get("key", ""),
            version=version.get("number", 1),
            url=url,
            body_storage=body.get("value"),
        )

    def update_page_content(
        self,
        page_id: str,
        title: str,
        body: str,
        version: int,
    ) -> Page:
        """Update page content."""
        data = {
            "id": page_id,
            "type": "page",
            "title": title,
            "body": {
                "storage": {
                    "value": body,
                    "representation": "storage",
                }
            },
            "version": {
                "number": version + 1,
            },
        }

        response = self._request("PUT", f"content/{page_id}", json=data)
        return self._parse_page(response.json())

    def get_attachments(self, page_id: str) -> list[Attachment]:
        """Get all attachments for a page."""
        response = self._request(
            "GET",
            f"content/{page_id}/child/attachment",
            params={"expand": "version"},
        )
        data = response.json()

        attachments = []
        for item in data.get("results", []):
            attachments.append(self._parse_attachment(item))

        return attachments

    def get_attachment_by_filename(
        self, page_id: str, filename: str
    ) -> Optional[Attachment]:
        """Get a specific attachment by filename."""
        response = self._request(
            "GET",
            f"content/{page_id}/child/attachment",
            params={"filename": filename, "expand": "version"},
        )
        data = response.json()

        results = data.get("results", [])
        if not results:
            return None

        return self._parse_attachment(results[0])

    def _parse_attachment(self, data: dict) -> Attachment:
        """Parse attachment data from API response."""
        version = data.get("version", {})
        links = data.get("_links", {})
        extensions = data.get("extensions", {})

        return Attachment(
            id=data["id"],
            title=data["title"],
            filename=data["title"],
            media_type=extensions.get("mediaType", "application/octet-stream"),
            version=version.get("number", 1),
            download_url=links.get("download", ""),
        )

    def download_attachment(self, page_id: str, filename: str) -> bytes:
        """Download attachment content."""
        attachment = self.get_attachment_by_filename(page_id, filename)
        if attachment is None:
            raise NotFoundError(f"Attachment not found: {filename}")

        download_url = f"{self.base_url}{attachment.download_url}"
        response = self.session.get(download_url)

        if not response.ok:
            raise ConfluenceError(
                f"Failed to download attachment: {response.status_code}"
            )

        return response.content

    def upload_attachment(
        self,
        page_id: str,
        filename: str,
        content: bytes,
        media_type: str = "application/octet-stream",
        comment: str = "",
    ) -> Attachment:
        """Upload or update an attachment."""
        # Check if attachment exists
        existing = self.get_attachment_by_filename(page_id, filename)

        files = {
            "file": (filename, content, media_type),
        }

        data = {}
        if comment:
            data["comment"] = comment

        headers = {"X-Atlassian-Token": "nocheck"}

        if existing:
            # Update existing attachment
            response = self._request(
                "POST",
                f"content/{page_id}/child/attachment/{existing.id}/data",
                files=files,
                data=data,
                headers=headers,
            )
        else:
            # Create new attachment
            response = self._request(
                "POST",
                f"content/{page_id}/child/attachment",
                files=files,
                data=data,
                headers=headers,
            )

        result = response.json()

        # Response may be a single attachment or a list
        if "results" in result:
            return self._parse_attachment(result["results"][0])
        return self._parse_attachment(result)

    def upload_attachment_from_file(
        self,
        page_id: str,
        file_path: Path,
        comment: str = "",
    ) -> Attachment:
        """Upload attachment from a local file."""
        content = file_path.read_bytes()
        filename = file_path.name

        # Determine media type
        media_type = self._get_media_type(filename)

        return self.upload_attachment(
            page_id=page_id,
            filename=filename,
            content=content,
            media_type=media_type,
            comment=comment,
        )

    def _get_media_type(self, filename: str) -> str:
        """Get media type for a filename."""
        ext = Path(filename).suffix.lower()
        media_types = {
            ".drawio": "application/vnd.jgraph.mxfile",
            ".png": "image/png",
            ".svg": "image/svg+xml",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".pdf": "application/pdf",
            ".xml": "application/xml",
        }
        return media_types.get(ext, "application/octet-stream")

    def test_connection(self) -> bool:
        """Test if the connection to Confluence works."""
        try:
            self._request("GET", "space", params={"limit": 1})
            return True
        except ConfluenceError:
            return False
