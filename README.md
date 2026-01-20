# drawio-confluence-cli

A CLI tool to manage draw.io diagrams with Confluence Server/Data Center integration.

## Features

- **Confluence as source of truth**: Store `.drawio` files as page attachments
- **Local editing**: Download diagrams, edit locally, publish back
- **Link extraction**: Automatically extract hyperlinks from diagrams and list them on the page
- **Image export**: Export diagrams to PNG/SVG for embedding in Confluence pages
- **Git-friendly**: `.drawio` files are XML and work well with version control

## Installation

```bash
# From source
git clone https://github.com/yourusername/drawio-confluence-cli.git
cd drawio-confluence-cli
pip install -e .

# Or with dev dependencies
pip install -e ".[dev]"
```

## Quick Start

### 1. Initialize a workspace

```bash
cd my-diagrams
drawio-cli init --base-url https://wiki.company.com
```

### 2. Set up authentication

```bash
# Using Personal Access Token (recommended)
export CONFLUENCE_PAT="your-token-here"

# Or using basic auth
export CONFLUENCE_USER="your-username"
export CONFLUENCE_PASS="your-password"
```

### 3. Download an existing diagram

```bash
drawio-cli checkout https://wiki.company.com/display/SPACE/PageName
```

### 4. Edit the diagram

```bash
# Opens in desktop app (if installed) or opens app.diagrams.net
drawio-cli edit diagram.drawio
```

### 5. Publish changes

```bash
drawio-cli publish diagram.drawio
```

## Commands

### Setup & Configuration

| Command | Description |
|---------|-------------|
| `drawio-cli init` | Initialize a workspace and configure Confluence connection |
| `drawio-cli config` | View current configuration and test connection |

### Diagram Management

| Command | Description |
|---------|-------------|
| `drawio-cli list` | List tracked diagrams and their sync status |
| `drawio-cli checkout <page-url>` | Download `.drawio` file from a Confluence page |
| `drawio-cli new <name> [--page <url>]` | Create a new diagram, optionally linked to a page |
| `drawio-cli status` | Show detailed status of all tracked diagrams |
| `drawio-cli links <diagram>` | Show hyperlinks found in a diagram |

### Editing

| Command | Description |
|---------|-------------|
| `drawio-cli edit <diagram>` | Open diagram in editor (desktop app or web) |
| `drawio-cli edit <diagram> --desktop` | Force desktop app |
| `drawio-cli edit <diagram> --web` | Force web editor |

### Export

| Command | Description |
|---------|-------------|
| `drawio-cli export <diagram>` | Export to image (requires desktop app) |
| `drawio-cli export <diagram> -f svg` | Export as SVG |
| `drawio-cli export <diagram> --force` | Re-export even if cached |

### Publishing

| Command | Description |
|---------|-------------|
| `drawio-cli publish <diagram>` | Upload diagram and image to Confluence |
| `drawio-cli publish <diagram> --page <url>` | Publish to a specific page |
| `drawio-cli publish-all` | Publish all linked diagrams |

## Configuration

Configuration is stored in `.drawio-cli/config.yaml`:

```yaml
confluence:
  base_url: "https://wiki.company.com"
  auth_type: "pat"  # or "basic"

editor:
  prefer: "web"  # or "desktop"
  desktop_path: null  # auto-detected, or set manually

export:
  default_format: "png"
  png_scale: 2  # 2x for retina displays
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `CONFLUENCE_PAT` | Personal Access Token for Confluence |
| `CONFLUENCE_USER` | Username for basic authentication |
| `CONFLUENCE_PASS` | Password for basic authentication |

## Workflow

### Typical workflow

1. **Checkout** an existing diagram or **create** a new one
2. **Edit** the diagram locally
3. **Export** to PNG/SVG (automatic with desktop app, manual otherwise)
4. **Publish** to update Confluence

### What happens when you publish

1. The `.drawio` source file is uploaded as an attachment
2. The exported image (PNG/SVG) is uploaded as an attachment
3. The page content is updated to show:
   - The embedded image
   - A link to download the `.drawio` source
   - A list of all hyperlinks found in the diagram

### Example page content after publish

```
[Embedded diagram image]

Source: architecture.drawio

Links in this diagram:
• API Documentation → https://api.company.com/docs
• Service B → https://wiki.company.com/display/ARCH/ServiceB
```

## Link Extraction

The tool automatically extracts hyperlinks from your diagrams. Links can be added in draw.io by:

1. Select a shape
2. Right-click → Edit Link
3. Enter the URL

These links are preserved in the `.drawio` file and listed on the Confluence page when published.

## Desktop App vs Web

**Desktop app** (recommended):
- Automatic export via CLI
- Direct file editing
- Install from https://www.drawio.com/

**Web only**:
- Works everywhere
- Manual export required (File → Export)
- Open with `drawio-cli edit --web`

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run tests with coverage
pytest --cov=drawio_cli
```

## Project Structure

```
drawio-confluence-cli/
├── src/drawio_cli/
│   ├── __init__.py
│   ├── __main__.py      # Entry point
│   ├── cli.py           # CLI commands (Click)
│   ├── config.py        # Configuration management
│   ├── confluence.py    # Confluence REST API client
│   ├── diagram.py       # .drawio parsing, link extraction
│   ├── editor.py        # Editor launching
│   ├── export.py        # Export handling
│   ├── publisher.py     # Publish workflow
│   └── state.py         # State tracking
└── tests/
    ├── test_confluence.py
    ├── test_diagram.py
    ├── test_state.py
    └── fixtures/
        └── sample.drawio
```

## Troubleshooting

### "Not in a drawio-cli workspace"

Run `drawio-cli init` in your working directory first.

### "Authentication failed"

Check that your `CONFLUENCE_PAT` (or `CONFLUENCE_USER`/`CONFLUENCE_PASS`) environment variables are set correctly.

### "Desktop app not found"

The desktop app is optional. You can:
- Install it from https://www.drawio.com/
- Or use `--web` flag to use the web editor
- Or export manually from app.diagrams.net

### Export fails

Without the desktop app, exports must be done manually:
1. Open your diagram at app.diagrams.net
2. File → Export as → PNG (or SVG)
3. Save the file next to your `.drawio` file
4. Run `drawio-cli publish` again

## License

MIT
