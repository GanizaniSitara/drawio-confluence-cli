# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.3] - 2026-02-13

### Added
- Automatic version bumping via pre-push git hook
- Version bump script for manual major/minor/patch bumping
- .gitattributes for consistent line endings across platforms

### Changed
- Dynamic version management in pyproject.toml (reads from __init__.py)

## [0.2.0] - 2026-02-13

### Added
- `remove` command to delete diagrams from Confluence pages
- Support for page ID in addition to URL in `publish` command
- C4 model shape support in link extraction (c4Name, c4Type properties)
- Placeholder resolution (%property%) in diagram labels
- Delete attachment methods in ConfluenceClient

### Changed
- `publish` command now takes page as positional argument (no more --page flag)
- Link extraction prioritizes c4Name > name > title > placeholder resolution > HTML stripping
- README updated with new syntax and workflow examples

### Fixed
- Link labels now show meaningful text for C4 shapes instead of HTML placeholders

## [0.1.0] - 2025-02-13

### Added
- Initial release
- Confluence Server/Data Center integration
- Local diagram editing with draw.io desktop or web
- Checkout diagrams from Confluence pages
- Publish diagrams to Confluence with automatic export
- Link extraction from diagrams
- Support for PNG, SVG, PDF export formats
- Configuration management via .drawio-cli/config.yaml
- State tracking for linked diagrams
- Auto-create Confluence pages if they don't exist
- SSL verification configuration for self-signed certificates
- Multiple export methods: desktop CLI, headless browser, public API
