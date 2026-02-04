#!/usr/bin/env python
"""End-to-end manual test script for drawio-cli.

This script performs a full workflow test:
1. Creates test pages in Confluence (one per format)
2. Creates diagrams with different export formats (PNG, SVG, HTML)
3. Publishes them to Confluence
4. Verifies the results via API
5. Takes screenshots for visual verification
6. Cleans up

Run with: python tests/test_e2e_manual.py

Requires a configured workspace with Confluence credentials.
"""

import subprocess
import sys
import platform
import time
from pathlib import Path

# Add src to path for development
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from drawio_cli.config import load_config, find_workspace_root
from drawio_cli.confluence import ConfluenceClient, ConfluenceError
from drawio_cli.diagram import create_empty_diagram
from drawio_cli.export import export_diagram, ExportError
from drawio_cli.publisher import publish_diagram
from drawio_cli.state import load_state


def take_screenshot(url, output_path, auth=None, base_url=None):
    """Take a screenshot of a URL using Playwright.

    Args:
        url: URL to screenshot
        output_path: Path to save the screenshot
        auth: Optional tuple of (username, password) for form-based login
        base_url: Base URL for login page

    Returns:
        True if successful, False otherwise
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  Warning: Playwright not installed, skipping screenshot")
        return False

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1280, "height": 900},
            )
            page = context.new_page()

            # Navigate to URL - this may redirect to login
            page.goto(url, wait_until="networkidle", timeout=30000)

            # Check if we're on a login page and need to authenticate
            if auth and "login" in page.url.lower():
                print("  Logging in to Confluence...")

                # Wait for login form to be ready
                page.wait_for_selector('input[type="text"], input[type="password"]', timeout=10000)

                # Try different login form field names (varies by Confluence version)
                username_filled = False
                password_filled = False

                # Fill username - try by ID first (Confluence 9.x uses id="username")
                for selector in ['#username', 'input[name="os_username"]', 'input[name="username"]']:
                    try:
                        locator = page.locator(selector)
                        if locator.count() > 0 and locator.is_visible():
                            locator.fill(auth[0])
                            username_filled = True
                            break
                    except Exception:
                        continue

                # Fill password
                for selector in ['#password', 'input[name="os_password"]', 'input[name="password"]', 'input[type="password"]']:
                    try:
                        locator = page.locator(selector)
                        if locator.count() > 0 and locator.is_visible():
                            locator.fill(auth[1])
                            password_filled = True
                            break
                    except Exception:
                        continue

                if not username_filled or not password_filled:
                    print(f"  Warning: Could not fill login form (username={username_filled}, password={password_filled})")

                # Click login button
                for selector in ['#loginButton', 'button:has-text("Log in")', 'input[type="submit"]', 'button[type="submit"]']:
                    try:
                        locator = page.locator(selector)
                        if locator.count() > 0 and locator.is_visible():
                            locator.click()
                            break
                    except Exception:
                        continue

                # Wait for navigation after login - wait for URL to change from login page
                try:
                    page.wait_for_url(lambda u: "login" not in u.lower(), timeout=15000)
                except Exception:
                    pass

                # Wait for page to settle
                page.wait_for_load_state("networkidle", timeout=30000)

                # If still on login page, navigate again
                if "login" not in page.url.lower():
                    # We're logged in, go to target page
                    page.goto(url, wait_until="networkidle", timeout=30000)

            # Wait a bit for any dynamic content to render
            time.sleep(2)

            # Take screenshot
            page.screenshot(path=str(output_path), full_page=False)
            browser.close()

            print(f"  Screenshot saved: {output_path}")
            return True
    except Exception as e:
        print(f"  Screenshot failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def create_test_page(client, config, title="DrawIO CLI E2E Test"):
    """Create a test page in Confluence."""
    # Get first available space
    response = client._request('GET', 'space', params={'limit': 1})
    spaces = response.json().get('results', [])
    if not spaces:
        raise RuntimeError("No Confluence spaces available")

    space_key = spaces[0]['key']
    print(f"Using space: {space_key} ({spaces[0]['name']})")

    # Create page
    data = {
        'type': 'page',
        'title': title,
        'space': {'key': space_key},
        'body': {
            'storage': {
                'value': '<p>Test page for drawio-cli E2E testing</p>',
                'representation': 'storage'
            }
        }
    }

    try:
        response = client._request('POST', 'content', json=data)
        page = response.json()
        page_id = page['id']
        # Use simple page ID URL format
        page_url = f"{config.confluence.base_url}/pages/viewpage.action?pageId={page_id}"
        print(f"Created page: {page_id}")
        print(f"URL: {page_url}")
        return page_id, page_url, space_key
    except ConfluenceError as e:
        if "already exists" in str(e).lower():
            # Page exists, get it
            page = client.get_page_by_title(space_key, title)
            print(f"Using existing page: {page.id}")
            return page.id, page.url, space_key
        raise


def delete_test_page(client, page_id):
    """Delete the test page."""
    try:
        client._request('DELETE', f'content/{page_id}')
        print(f"Deleted page: {page_id}")
    except Exception as e:
        print(f"Warning: Could not delete page: {e}")


def create_diagram_with_format(workspace_root, state, format_type):
    """Create a test diagram with specified format."""
    name = f"test-{format_type}-diagram"
    diagram_path = workspace_root / f"{name}.drawio"

    # Create diagram with visible sample content so exports show something
    content = create_empty_diagram(name, with_sample_content=True)
    diagram_path.write_text(content)
    print(f"Created: {diagram_path}")

    # Add to state with format
    diagram_state = state.add_diagram(str(diagram_path.relative_to(workspace_root)))
    diagram_state.export_format = format_type
    state.save()
    print(f"  State saved with export_format: {format_type}")

    return diagram_path


def do_export_diagram(diagram_path, config, format_type):
    """Test exporting a diagram."""
    try:
        result = export_diagram(
            source=diagram_path,
            format=format_type,
            export_config=config.export,
            editor_config=config.editor,
            force=True,
        )
        print(f"Exported: {result.output_file} (method: {result.method})")
        return result.output_file
    except ExportError as e:
        print(f"Export failed: {e}")
        return None


def do_publish_diagram(diagram_path, config, state, client, page_id, format_type):
    """Test publishing a diagram to Confluence."""
    try:
        result = publish_diagram(
            diagram_path=diagram_path,
            config=config,
            state=state,
            client=client,
            page_id=page_id,
            export_format=format_type,
        )
        print(f"Published: {result.page_url}")
        print(f"  .drawio attachment: v{result.drawio_attachment.version}")
        if result.image_attachment:
            print(f"  Export attachment: {result.image_attachment.filename}")
        if result.page_updated:
            print(f"  Page content updated")
        return result
    except Exception as e:
        print(f"Publish failed: {e}")
        return None


def verify_page_content(client, page_id, format_type, diagram_name):
    """Verify the page content after publishing."""
    page = client.get_page_by_id(page_id, expand=["body.storage"])
    body = page.body_storage or ""

    # Check for diagram attachment reference
    export_filename = f"{diagram_name}.{format_type}"
    drawio_filename = f"{diagram_name}.drawio"

    checks = []

    if drawio_filename in body:
        checks.append(f"✓ Source file link: {drawio_filename}")
    else:
        checks.append(f"✗ Missing source file link: {drawio_filename}")

    if export_filename in body:
        checks.append(f"✓ Export file reference: {export_filename}")
    else:
        checks.append(f"✗ Missing export file reference: {export_filename}")

    if format_type == "html":
        if "Interactive diagram" in body:
            checks.append("✓ HTML has 'Interactive diagram' text")
        else:
            checks.append("✗ Missing 'Interactive diagram' text for HTML")
    else:
        if "<ac:image" in body:
            checks.append("✓ Image macro present")
        else:
            checks.append("✗ Missing image macro")

    for check in checks:
        print(f"  {check}")

    return all("✓" in c for c in checks)


def cleanup_files(workspace_root, diagram_names):
    """Clean up test diagram files."""
    for name in diagram_names:
        for ext in [".drawio", ".png", ".svg", ".html", ".pdf"]:
            path = workspace_root / f"{name}{ext}"
            if path.exists():
                path.unlink()
                print(f"Deleted: {path.name}")


def open_browser(url):
    """Open URL in default browser."""
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run(["open", url], check=True)
        elif system == "Windows":
            subprocess.run(["start", url], shell=True, check=True)
        else:
            # Linux - check if we're in WSL
            if "microsoft" in platform.uname().release.lower():
                # WSL - use cmd.exe to open browser
                subprocess.run(["cmd.exe", "/c", "start", url], check=True)
            else:
                subprocess.run(["xdg-open", url], check=True)
        return True
    except Exception as e:
        print(f"Could not open browser: {e}")
        return False


def main():
    print("=" * 60)
    print("DrawIO CLI End-to-End Test")
    print("=" * 60)

    # Setup
    print("\n[1] Setup")
    root = find_workspace_root()
    if root is None:
        print("Error: No workspace found. Run 'drawio-cli init' first.")
        return 1

    config = load_config(root)
    if not config.confluence.is_configured():
        print("Error: Confluence not configured.")
        return 1

    client = ConfluenceClient(config.confluence)
    if not client.test_connection():
        print("Error: Cannot connect to Confluence.")
        return 1

    print(f"Workspace: {root}")
    print(f"Confluence: {config.confluence.base_url}")

    state = load_state(config.state_file)

    test_formats = ["png", "svg", "html"]
    diagram_names = []
    results = {}
    page_urls = {}  # Track page URLs for each format
    page_ids = []   # Track page IDs for cleanup

    try:
        for format_type in test_formats:
            print(f"\n[{test_formats.index(format_type)+2}] Test {format_type.upper()} Format")
            print("-" * 40)

            # Create a separate page for each format
            page_title = f"DrawIO CLI Test - {format_type.upper()} Export"
            print(f"Creating test page: {page_title}")
            page_id, page_url, space_key = create_test_page(client, config, title=page_title)
            page_ids.append(page_id)
            page_urls[format_type] = page_url

            name = f"test-{format_type}-diagram"
            diagram_names.append(name)

            # Create diagram
            print(f"Creating diagram with format: {format_type}")
            diagram_path = create_diagram_with_format(root, state, format_type)

            # Export
            print(f"Exporting to {format_type}...")
            export_path = do_export_diagram(diagram_path, config, format_type)

            # Publish
            print(f"Publishing to Confluence...")
            result = do_publish_diagram(
                diagram_path, config, state, client, page_id, format_type
            )

            # Verify
            if result:
                print(f"Verifying page content...")
                success = verify_page_content(client, page_id, format_type, name)
                results[format_type] = success
            else:
                results[format_type] = False

        # Take screenshots for visual verification
        print("\n" + "=" * 60)
        print("Taking Screenshots for Visual Verification")
        print("=" * 60)

        screenshot_dir = root / "test-screenshots"
        screenshot_dir.mkdir(exist_ok=True)
        screenshots = {}

        # Get auth credentials for Playwright
        auth = None
        if config.confluence.username and config.confluence.password:
            auth = (config.confluence.username, config.confluence.password)

        for format_type in test_formats:
            url = page_urls[format_type]
            screenshot_path = screenshot_dir / f"confluence-{format_type}.png"
            print(f"Screenshotting {format_type.upper()} page...")
            if take_screenshot(url, screenshot_path, auth=auth):
                screenshots[format_type] = screenshot_path

        # Summary
        print("\n" + "=" * 60)
        print("Test Results Summary")
        print("=" * 60)

        for format_type, success in results.items():
            status = "PASS" if success else "FAIL"
            print(f"  {format_type.upper()}: {status}")
            print(f"    URL: {page_urls[format_type]}")
            if format_type in screenshots:
                print(f"    Screenshot: {screenshots[format_type]}")

        all_passed = all(results.values())
        print(f"\nOverall: {'ALL TESTS PASSED' if all_passed else 'SOME TESTS FAILED'}")

        if screenshots:
            print(f"\nScreenshots saved to: {screenshot_dir}")
            print("Review screenshots to verify diagrams are visible on pages.")

        # Cleanup
        print("\n" + "=" * 60)
        print("Cleanup")
        print("=" * 60)

        # Always cleanup in non-interactive mode
        for page_id in page_ids:
            delete_test_page(client, page_id)
        cleanup_files(root, diagram_names)
        print("Test pages deleted.")
        print(f"Screenshots preserved in: {screenshot_dir}")

        return 0 if all_passed else 1

    except KeyboardInterrupt:
        print("\n\nInterrupted. Cleaning up...")
        for page_id in page_ids:
            delete_test_page(client, page_id)
        cleanup_files(root, diagram_names)
        return 1
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()

        print("\nAttempting cleanup...")
        try:
            for page_id in page_ids:
                delete_test_page(client, page_id)
            cleanup_files(root, diagram_names)
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
