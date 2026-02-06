#!/usr/bin/env python
"""Test that SVG images are embedded in Confluence page content."""

import argparse
import shutil
import sys
from pathlib import Path

# Add src and tests to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from conftest_e2e import (
    get_confluence_client,
    get_test_config,
    get_fixtures_dir,
    get_test_output_dir,
    get_first_space_key,
    create_test_page,
    delete_test_page,
    get_page_url,
)
from drawio_cli.export import export_diagram
from drawio_cli.publisher import publish_diagram
from drawio_cli.state import State


def main():
    parser = argparse.ArgumentParser(description="Test SVG embedding in Confluence")
    parser.add_argument("--keep", action="store_true", help="Keep test page for inspection")
    args = parser.parse_args()

    print("Testing SVG embedding in Confluence...")

    # Setup
    config = get_test_config()
    client = get_confluence_client()
    output_dir = get_test_output_dir()

    # Connect
    if not client.test_connection():
        print("ERROR: Cannot connect to Confluence")
        return 1
    print(f"Connected to {config.confluence.base_url}")

    # Get space
    space_key = get_first_space_key(client)
    print(f"Using space: {space_key}")

    # Copy fixture with links to output dir for testing
    fixture_path = get_fixtures_dir() / "sample_with_links.drawio"
    diagram_path = output_dir / "test-embed-svg.drawio"
    shutil.copy(fixture_path, diagram_path)
    print(f"Using diagram: {diagram_path}")

    # Create test page
    page_title = "Embed Test - SVG"
    page_id = create_test_page(client, page_title, space_key)
    print(f"Using page: {page_id}")

    try:
        # Export to SVG
        print("Exporting to SVG...")
        export_result = export_diagram(
            source=diagram_path,
            format="svg",
            export_config=config.export,
            editor_config=config.editor,
            force=True,
        )
        print(f"Exported: {export_result.output_file}")

        # Move exported file to output dir if not already there
        exported_file = Path(export_result.output_file)
        if exported_file.parent != output_dir:
            target = output_dir / exported_file.name
            shutil.move(str(exported_file), str(target))
            print(f"Moved export to: {target}")

        # Create state
        state = State(_state_file=config.state_file)

        # Publish
        print("Publishing...")
        publish_diagram(
            diagram_path=diagram_path,
            config=config,
            state=state,
            client=client,
            page_id=page_id,
            export_format="svg",
            log=lambda msg: print(f"  {msg}"),
        )

        # Check page content
        print("\nVerifying page content...")
        page = client.get_page_by_id(page_id, expand=["body.storage"])
        body = page.body_storage or ""

        print(f"Body length: {len(body)} chars")

        success = False
        if "<ac:image" in body and 'ri:filename="test-embed-svg.svg"' in body:
            print("SUCCESS: ac:image macro references the SVG attachment")
            success = True
        else:
            print("FAIL: No image reference found in body")

        # Show body preview
        print("\nPage body preview:")
        print("-" * 40)
        print(body[:500])
        print("-" * 40)

        print(f"\nPage URL: {get_page_url(page_id)}")
        print("Check the page in your browser to verify clickable links in SVG work.")

        if args.keep:
            print("\nPage preserved for inspection (--keep flag set)")
        else:
            print("\nCleaning up test page...")
            if delete_test_page(client, page_id):
                print("Page deleted.")
            else:
                print("Could not delete page - delete manually if needed.")

        return 0 if success else 1

    except Exception as e:
        print(f"ERROR: {e}")
        if not args.keep:
            print("Cleaning up test page...")
            delete_test_page(client, page_id)
        raise


if __name__ == "__main__":
    sys.exit(main())
