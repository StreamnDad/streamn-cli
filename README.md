<p align="center">
  <img src="assets/logo.jpg" alt="Streamn Dad" width="200">
</p>

# streamn-cli

A command-line toolkit for livestreaming youth hockey games — game setup, replay management, period highlights, and story-of-the-game merging.

> **Work in progress** — source code and install instructions coming soon.

Built by [Streamn Dad](https://streamn.dad) to automate the repetitive parts of running a one-person livestream operation so you can focus on the game.

## What It Does

**Pre-game setup** (`streamn-cli game init`)
- Select teams from saved profiles (with fuzzy autocomplete)
- Generate game overrides (scoreboard, logos, rosters, platform config)
- Initialize scoreboard text files for OBS overlays
- Create YouTube livestream via API (optional)
- Create game-aware directory for replay organization

**Period highlights** (`streamn-cli game period <N>`)
- Automatically find new replay files from OBS replay buffer
- Move them into organized period directories
- Merge period replays into a single intermission highlight video (ffmpeg concat, no re-encode)

**Story of the game** (`streamn-cli game highlights`)
- Merge all period highlight videos into one full-game highlight reel
- Double-header support with automatic game numbering

**Replay organization**
- Game-aware directories solve the double-header problem (all replays in one flat folder)
- Structure: `~/Movies/{date}_{Home}_vs_{Away}/period-{1,2,3}/`
- `--dry-run` on all commands to preview before acting

## Quick Start

```bash
# 1. Pre-game: set up teams, scoreboard, and game directory
streamn-cli game init --level squirts --home roseville --away mahtomedi

# 2. End of period 1: move replays + merge
streamn-cli game period 1

# 3. End of period 2
streamn-cli game period 2

# 4. End of period 3
streamn-cli game period 3

# 5. Post-game: merge all periods into story of the game
streamn-cli game highlights
```

### Double-headers

```bash
# Game 1 — normal
streamn-cli game init --level squirts --home roseville --away mahtomedi

# Game 2 — auto-detects _g2 directory
streamn-cli game init --level squirts --home roseville --away stillwater

# Or specify explicitly
streamn-cli game period 1 -g 2
streamn-cli game highlights -g 2
```

## Requirements

- Python 3.11+
- [ffmpeg](https://ffmpeg.org/) (for highlight merging)
- [OBS Studio](https://obsproject.com/) (for livestreaming and replay buffer)

## Status

This project is under active development. The core game workflow (`init` / `period` / `highlights`) is functional and used on game days. Additional features (multi-platform publishing, cloud workers, smart zoom shorts) exist in the codebase but are not yet documented for public use.

## License

This project is licensed under the [GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0).

## Links

- [streamn.dad](https://streamn.dad) — project home
- [@streamn_dad](https://www.instagram.com/streamn_dad/) — highlights on Instagram
- [YouTube](https://www.youtube.com/@streamn-dad) — livestreams and highlights
