# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.0.28] - 2026-03-04

### Added
- `--description` / `-d` flag on `game init` for broadcast description
- `--thumbnail` flag on `game init` for thumbnail image path
- `GameInfo.description` and `GameInfo.thumbnail` fields
- Interactive prompts for description and thumbnail (both optional)

## [0.0.27] - 2026-03-04

### Fixed
- PyPI logo: restore absolute URL for README image (lost during merge)

## [0.0.26] - 2026-03-04

### Added
- `HookContext.shared` dict for plugins to pass data back (e.g. livestream URLs)
- `GameState.livestreams` field — persists livestream URLs written by hook plugins
- `resolve_config_path()` — extracted config path resolution for reuse

### Fixed
- Plugin install now uses `git+{homepage}` for GitHub/GitLab plugins instead of PyPI lookup
- Post-install verification catches silent `uv pip install` no-ops
- `save_config()` now respects `REELN_CONFIG` / `REELN_PROFILE` env vars (previously always wrote to default path)
- `detect_installer()` passes `--python sys.executable` to uv so plugins install into the correct environment
- Hardcoded version strings removed from tests (use `__version__` dynamically)

## [0.0.25] - 2026-03-04

### Fixed
- Logo image on PyPI (use absolute URL for `assets/logo.jpg`)
- Add project URLs to PyPI sidebar (Homepage, Docs, Repo, Changelog, Issues)

## [0.0.24] - 2026-03-04

### Fixed
- Registry URL casing — `raw.githubusercontent.com` is case-sensitive (`StreamnDad` not `streamn-dad`)
- mypy errors in `prompts.py` (renamed shadowed variables)
- CI workflows use `uv sync` instead of `uv pip install --system` (PEP 668)
- Plugin registry: correct homepage URL and metadata for `streamn-scoreboard`

## [0.0.23] - 2026-03-03

First feature-complete release of reeln — platform-agnostic CLI toolkit for livestreamers.

### Added

#### CLI Commands
- `reeln --version` — show version, ffmpeg info, and installed plugin versions
- `reeln doctor` — comprehensive health check: ffmpeg, codecs, hardware acceleration, config, permissions
- `reeln config show` — display current configuration as JSON
- `reeln config doctor` — validate config, warn on issues
- `reeln game init` — initialize game workspace with sport-specific segment subdirectories
- `reeln game segment <N>` — merge replays in a segment directory into a highlight video
- `reeln game highlights` — merge all segment highlights into a full-game highlight reel
- `reeln game finish` — mark a game as finished with summary
- `reeln game prune` — remove generated artifacts from a finished game directory
- `reeln game event list` — list events with filters (`--segment`, `--type`, `--untagged`)
- `reeln game event tag` — tag an event with type, player, and metadata
- `reeln game event tag-all` — bulk-tag all events in a segment
- `reeln game compile` — compile raw event clips into a single video by criteria
- `reeln render short` — render a 9:16 short from a clip
- `reeln render preview` — fast low-res preview render
- `reeln render apply` — apply a named render profile to a clip (full-frame, no crop/scale)
- `reeln render reel` — assemble rendered shorts into a concatenated reel
- `reeln media prune` — scan and prune all finished game directories
- `reeln plugins list` — list installed plugins with version info
- `reeln plugins search` — search the plugin registry
- `reeln plugins info <name>` — show detailed plugin information
- `reeln plugins install <name>` — install a plugin from the registry with auto-enable
- `reeln plugins update [name]` — update a plugin or all installed plugins
- `reeln plugins enable <name>` / `reeln plugins disable <name>` — enable/disable plugins

#### Core Features
- Package skeleton: `pyproject.toml`, Makefile, `.coveragerc`, `pytest.ini`, `python -m reeln` support
- Structured logging module with JSON and human formatters
- Error hierarchy: `ReelnError` base with typed subclasses
- FFmpeg discovery with cross-platform support (PATH, brew, apt, choco), version checking (5.0+ minimum)
- Media probe helpers: duration, fps, resolution via ffprobe
- Deterministic ffmpeg command builders (concat, render) with golden test assertions
- `FFmpegRenderer` implementation with `render()` and `preview()` methods
- Config system: JSON loading, schema validation, `config_version`, XDG-compliant paths, env var overrides (`REELN_<SECTION>_<KEY>`), deep merge, atomic writes, named profiles
- Segment model: generic time division abstraction with sport alias registry (hockey, basketball, soccer, football, baseball, lacrosse, generic) and custom sport registration
- Game lifecycle: `GameInfo`, `GameState`, `GameEvent` models with JSON serialization, double-header auto-detection, `game.json` state tracking
- `GameEvent` model for first-class event tracking with UUID-based IDs, prefix matching, extensible metadata, and idempotent creation
- Render state tracking in `game.json` via `RenderEntry` with event auto-linking
- ShortConfig model with crop modes (pad, crop), output formats (vertical, square), anchor positions
- Filter graph builders: scale, pad, crop, speed, LUT, subtitle — composable and golden-tested
- Render profiles: named configuration sets for reusable rendering parameter overrides (speed, LUT, subtitle template, encoding)
- Multi-iteration rendering: run a clip through N render profiles sequentially and concatenate results
- Template engine: `{{key}}` placeholder substitution for `.ass` subtitle files
- `TemplateContext`, `TemplateProvider` protocol, `build_base_context()` for game/event context
- ASS subtitle helpers: `rgb_to_ass()`, `format_ass_time()`
- Bundled `goal_overlay` ASS subtitle template with dynamic font sizing and team-colored background
- `builtin:` prefix for `subtitle_template` in render profiles (e.g. `"builtin:goal_overlay"`)
- `build_overlay_context()` for computing overlay-specific template variables from event metadata
- `--player` and `--assists` CLI flags on `render short`, `render preview`, and `render apply` — populate overlay template variables without game event tagging; override event data when both are present
- Default `player-overlay` render profile and `goal` iteration mapping in bundled config
- `TeamProfile` model with metadata (logo, roster, colors, jersey colors, period length)
- Team profile management: load, save, list, delete with atomic writes
- Interactive team selection and game time prompting in `game init`
- `--game-time`, `--level`, `--period-length`, `--venue` options on `game init`
- `--debug` flag on game and render commands — writes pipeline debug artifacts with ffmpeg commands, filter chains, and metadata
- HTML debug index (`debug/index.html`) with summary table and per-operation sections
- `--dry-run` support across all destructive and render commands
- `PruneResult` model, `format_bytes()`, `find_game_dirs()` helpers
- `CompilationResult` model for compilation output tracking
- `questionary` as optional dependency (`pip install reeln[interactive]`)

#### Plugin System
- Plugin system foundation: lifecycle hooks, capability protocols, hook registry
- `Hook` enum with 11 lifecycle hooks: `PRE_RENDER`, `POST_RENDER`, `ON_CLIP_AVAILABLE`, `ON_EVENT_CREATED`, `ON_EVENT_TAGGED`, `ON_GAME_INIT`, `ON_GAME_FINISH`, `ON_HIGHLIGHTS_MERGED`, `ON_ERROR`, `ON_SEGMENT_START`, `ON_SEGMENT_COMPLETE`
- `HookRegistry` with safe emission — handler exceptions are caught and logged
- Capability protocols: `Uploader`, `MetadataEnricher`, `Notifier`, `Generator`
- Plugin orchestrator: sequential pipeline (Generator -> MetadataEnricher -> Uploader -> Notifier)
- Plugin loader: `discover_plugins()`, `load_plugin()`, `load_enabled_plugins()`, `activate_plugins()`
- Plugin config schema declaration with `ConfigField` and `PluginConfigSchema`
- Remote plugin registry with cache, search, install, update, and auto-enable
- `author` and `license` fields on plugin registry entries
- `ThrottledReader` for upload throughput limiting, `upload_lock()` for serialization
- `filelock>=3.0` dependency

#### CI/CD & Docs
- GitHub Actions CI workflow (Python 3.11/3.12/3.13 matrix, lint, type check, tests, docs build)
- GitHub Actions release workflow (tag-based PyPI publish via trusted publisher)
- CI and docs badges in README
- Documentation infrastructure: Sphinx + MyST, Furo theme, Read the Docs config
- Full docs site: install guide, quickstart tutorial, CLI reference, configuration guide, sports guide

### Fixed
- `render short --render-profile` now correctly resolves `subtitle_template` from the profile — previously the template was silently dropped in the single-profile path

### Changed
- `--rink` CLI flag renamed to `--venue` for sport-agnostic terminology
- Segment merge and highlights merge output written to `paths.output_dir` for discoverability
- `period_length` moved from `TeamProfile` to `GameInfo`
- Full test suite with 100% line + branch coverage
