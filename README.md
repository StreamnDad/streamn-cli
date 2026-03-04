<p align="center">
  <img src="https://raw.githubusercontent.com/StreamnDad/reeln-cli/main/assets/logo.jpg" alt="reeln" width="200">
</p>

# reeln

[![CI](https://github.com/StreamnDad/reeln-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/StreamnDad/reeln-cli/actions/workflows/ci.yml)
[![Docs](https://readthedocs.org/projects/reeln-cli/badge/?version=latest)](https://reeln-cli.readthedocs.io/)
[![PyPI](https://img.shields.io/pypi/v/reeln)](https://pypi.org/project/reeln/)

**Platform-agnostic CLI toolkit for livestreamers.**

reeln handles video manipulation, segment/highlight management, and media lifecycle — generic by default, sport-specific through configuration. Built by [Streamn Dad](https://streamn.dad).

## Features

- **Game lifecycle management** — init, segment, highlights, finish
- **FFmpeg-powered video merging** — concat segments into highlight reels, no re-encoding
- **Sport-agnostic segment model** — hockey periods, basketball quarters, soccer halves, and more
- **Flexible configuration** — JSON config with XDG-compliant paths, env var overrides, named profiles
- **Pipeline debugging** — `--debug` flag captures ffmpeg commands, filter chains, and metadata for troubleshooting
- **Plugin-ready architecture** — lifecycle hooks, typed capability interfaces, and config schema declarations
- **Cross-platform** — macOS, Linux, Windows

## Quick start

```bash
# Install
pip install reeln

# Verify it works
reeln --version

# View your configuration
reeln config show

# Initialize a hockey game
reeln game init roseville mahtomedi --sport hockey
```

More commands are being built — rendering and media management are on the roadmap. See the [CLI reference](#cli-reference) below for what's available and what's coming.

## Supported sports

reeln adapts its directory structure and terminology to your sport:

| Sport | Segment name | Count | Example directories |
|---|---|---|---|
| hockey | period | 3 | `period-1/`, `period-2/`, `period-3/` |
| basketball | quarter | 4 | `quarter-1/` through `quarter-4/` |
| soccer | half | 2 | `half-1/`, `half-2/` |
| football | half | 2 | `half-1/`, `half-2/` |
| baseball | inning | 9 | `inning-1/` through `inning-9/` |
| lacrosse | quarter | 4 | `quarter-1/` through `quarter-4/` |
| generic | segment | 1 | `segment-1/` |

Custom sports can be registered in your config file.

## CLI reference

**Available now:**

| Command | Description |
|---|---|
| `reeln --version` | Show version |
| `reeln --help` | Show help and available commands |
| `reeln config show` | Display current configuration |
| `reeln config doctor` | Validate config, warn on issues |
| `reeln game init` | Set up game directory with sport-specific segments |

| `reeln plugins search` | Search the plugin registry |
| `reeln plugins info <name>` | Show detailed plugin information |
| `reeln plugins install <name>` | Install a plugin from the registry |
| `reeln plugins update [name]` | Update a plugin or all installed plugins |
| `reeln plugins list` | List installed plugins with version info |
| `reeln plugins enable <name>` | Enable a plugin |
| `reeln plugins disable <name>` | Disable a plugin |

**Coming soon** (command groups are registered, implementation in progress):

| Command | Description |
|---|---|
| `reeln game segment <N>` | Move replays and merge segment highlights |
| `reeln game highlights` | Merge all segments into full-game highlight reel |
| `reeln game finish` | Finalize game, cleanup temp files |
| `reeln render short` | Render 9:16 short from clip |
| `reeln render preview` | Fast low-res preview render |
| `reeln media prune` | Artifact cleanup (supports `--dry-run`) |
| `reeln doctor` | Health check: ffmpeg, config, permissions |

## Configuration

reeln uses a layered JSON config system:

1. **Bundled defaults** — shipped with the package
2. **User config** — `config.json` in your XDG config directory
3. **Game overrides** — `game.json` in the game directory
4. **Environment variables** — `REELN_<SECTION>_<KEY>`

```bash
# Override any config value via env var
export REELN_VIDEO_FFMPEG_PATH=/opt/ffmpeg/bin/ffmpeg
export REELN_PATHS_OUTPUT_DIR=~/custom-output

# View the resolved config
reeln config show
```

## Requirements

- Python 3.11+
- [ffmpeg 5.0+](https://ffmpeg.org/)

## Installation

```bash
# With pip
pip install reeln

# With uv
uv tool install reeln

# Development
git clone https://github.com/StreamnDad/reeln-cli.git
cd reeln-cli
make dev-install
```

## Documentation

Full documentation is available at [reeln-cli.readthedocs.io](https://reeln-cli.readthedocs.io).

## License

[GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0)

## Links

- [streamn.dad](https://streamn.dad) — project home
- [Documentation](https://reeln-cli.readthedocs.io) — full docs
- [@streamn_dad](https://www.instagram.com/streamn_dad/) — highlights on Instagram
- [YouTube](https://www.youtube.com/@streamn-dad) — livestreams and highlights
