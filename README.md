# drawio-confluence-cli

A CLI tool to manage draw.io diagrams with Confluence Server/Data Center integration.

> **Note:** If you have the official [draw.io Confluence plugin](https://marketplace.atlassian.com/apps/1210933/draw-io-diagrams-for-confluence) installed, use that instead - it provides native integration with live editing directly in Confluence.
>
> This tool is for situations where you **don't have the plugin installed, or can't install it** (e.g., restricted marketplace access, cost constraints, self-hosted instances without plugin support). It provides a workaround by storing `.drawio` files as attachments and publishing exported images to pages.

## Features

- **Confluence as source of truth**: Store `.drawio` files as page attachments
- **Local editing**: Download diagrams, edit locally, publish back
- **Link extraction**: Automatically extract hyperlinks from diagrams and list them on the page
- **Image export**: Export diagrams to PNG/SVG for embedding in Confluence pages
- **Git-friendly**: `.drawio` files are XML and work well with version control

## Installation

```bash
# From source
git clone https://github.com/GanizaniSitara/drawio-confluence-cli.git
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

**Option A: Personal Access Token (recommended)**
```bash
export CONFLUENCE_PAT="your-token-here"
```

**Option B: Username/Password**
```bash
# First, edit .drawio-cli/config.yaml and change auth_type to "basic":
#   auth_type: "basic"
# Then set the environment variables:
export CONFLUENCE_USER="your-username"
export CONFLUENCE_PASS="your-password"
```

### 3. Choose your workflow

**Workflow A: Download an existing diagram from Confluence**

If you already have a `.drawio` file attached to a Confluence page:

```bash
# Download the diagram
drawio-cli checkout https://wiki.company.com/display/SPACE/PageName

# Edit it
drawio-cli edit diagram.drawio

# Publish changes back
drawio-cli publish diagram.drawio
```

**Workflow B: Create a new diagram and publish to Confluence**

If you're starting from scratch:

```bash
# Create a new diagram linked to an existing Confluence page
drawio-cli new architecture --page https://wiki.company.com/display/SPACE/PageName

# Edit the diagram
drawio-cli edit architecture.drawio

# Export to PNG (automatic with desktop app, or export manually from web)
drawio-cli export architecture.drawio

# Publish to Confluence (uploads .drawio + image, updates page content)
drawio-cli publish architecture.drawio
```

The Confluence page must already exist - this tool attaches diagrams to existing pages, it doesn't create new pages.

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
  auth_type: "pat"  # "pat" for Personal Access Token, "basic" for username/password

editor:
  prefer: "web"  # or "desktop"
  desktop_path: null  # auto-detected, or set manually

export:
  default_format: "png"
  png_scale: 2  # 2x for retina displays
```

### Authentication

The `auth_type` setting determines which environment variables are used:

| `auth_type` | Environment Variables | Description |
|-------------|----------------------|-------------|
| `pat` (default) | `CONFLUENCE_PAT` | Personal Access Token - recommended for Confluence Server/DC 7.9+ |
| `basic` | `CONFLUENCE_USER` + `CONFLUENCE_PASS` | Username and password - use if PAT not available |

**Important:** If using username/password, you must edit `config.yaml` and change `auth_type: "basic"` before setting the environment variables.

## Workflow

### Working with existing diagrams

If a `.drawio` file is already attached to a Confluence page:

1. `checkout` - download the diagram from Confluence
2. `edit` - make changes locally
3. `publish` - upload changes back to Confluence

### Creating new diagrams

To add a new diagram to an existing Confluence page:

1. `new --page <url>` - create a new `.drawio` file linked to the page
2. `edit` - design your diagram
3. `export` - export to PNG/SVG (automatic with desktop app)
4. `publish` - upload diagram and image to Confluence

**Note:** The Confluence page must already exist. This tool doesn't create pages - it only attaches diagrams to existing pages.

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
