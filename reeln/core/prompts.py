"""Interactive prompt helpers for game initialization.

All prompt functions follow a preset-first pattern: if a value is provided
via CLI argument, it is returned immediately without triggering a prompt.
When no preset is given, ``questionary`` is lazy-imported and the user is
prompted interactively.
"""

from __future__ import annotations

import sys
import types
from datetime import date
from typing import Any

from reeln.core.errors import PromptAborted, ReelnError
from reeln.core.segment import list_sports
from reeln.models.team import TeamProfile


def _require_questionary() -> types.ModuleType:
    """Lazy-import ``questionary``, raising a helpful error if missing.

    Also verifies that stdin is a TTY — interactive prompts cannot work
    when input is piped or redirected.
    """
    if not sys.stdin.isatty():
        raise ReelnError(
            "Interactive prompts require a terminal. Provide HOME and AWAY arguments for non-interactive use."
        )
    try:
        import questionary
    except ImportError:
        raise ReelnError(
            "Interactive prompts require the 'questionary' package. Install it with: pip install reeln[interactive]"
        ) from None
    return questionary


# ---------------------------------------------------------------------------
# Individual prompt functions
# ---------------------------------------------------------------------------


def prompt_home_team(preset: str | None = None) -> str:
    """Prompt for the home team name, or return *preset* immediately."""
    if preset is not None:
        return preset
    questionary = _require_questionary()
    answer: str | None = questionary.text("Home team name:").ask()
    if not answer:
        raise PromptAborted("Home team prompt cancelled")
    return answer


def prompt_away_team(preset: str | None = None) -> str:
    """Prompt for the away team name, or return *preset* immediately."""
    if preset is not None:
        return preset
    questionary = _require_questionary()
    answer: str | None = questionary.text("Away team name:").ask()
    if not answer:
        raise PromptAborted("Away team prompt cancelled")
    return answer


def prompt_sport(preset: str | None = None) -> str:
    """Prompt for the sport type via a selection list, or return *preset*."""
    if preset is not None:
        return preset
    questionary = _require_questionary()
    choices = [alias.sport for alias in list_sports()]
    answer: str | None = questionary.select("Sport:", choices=choices, default="hockey").ask()
    if not answer:
        raise PromptAborted("Sport prompt cancelled")
    return answer


def prompt_date(preset: str | None = None) -> str:
    """Prompt for the game date, or return *preset*."""
    if preset is not None:
        return preset
    questionary = _require_questionary()
    today = date.today().isoformat()
    answer: str | None = questionary.text("Game date (YYYY-MM-DD):", default=today).ask()
    if not answer:
        raise PromptAborted("Date prompt cancelled")
    return answer


def prompt_venue(preset: str | None = None) -> str:
    """Prompt for the venue name, or return *preset*.

    Venue is optional — an empty answer is accepted (returns ``""``).
    """
    if preset is not None:
        return preset
    questionary = _require_questionary()
    answer: str | None = questionary.text("Venue (optional):").ask()
    if answer is None:
        return ""
    return answer


def prompt_game_time(preset: str | None = None) -> str:
    """Prompt for the game time, or return *preset*.

    Game time is optional — an empty answer is accepted (returns ``""``).
    """
    if preset is not None:
        return preset
    questionary = _require_questionary()
    answer: str | None = questionary.text("Game start time (e.g. 7:00 PM, optional):").ask()
    if answer is None:
        return ""
    return answer


def prompt_level(preset: str | None = None) -> str:
    """Prompt for the team level via a selection list, or return *preset*.

    Auto-selects if only one level exists.  Raises ``PromptAborted`` if
    no levels are configured or the user cancels.
    """
    if preset is not None:
        return preset

    from reeln.core.teams import list_levels

    levels = list_levels()
    if not levels:
        questionary = _require_questionary()
        answer = questionary.text("Team level (e.g. bantam, varsity, jv):").ask()
        if not answer:
            raise PromptAborted("Level prompt cancelled")
        return str(answer).strip().lower()
    if len(levels) == 1:
        return levels[0]

    questionary = _require_questionary()
    selected: str | None = questionary.select("Team level:", choices=levels).ask()
    if not selected:
        raise PromptAborted("Level prompt cancelled")
    return str(selected)


def prompt_team(level: str, role: str, preset: str | None = None) -> TeamProfile:
    """Prompt for a team selection within a level, or load *preset* by slug.

    *role* is a display label like ``"home"`` or ``"away"``.
    Offers existing profiles plus a ``[Create new team]`` option.

    Raises ``PromptAborted`` if the user cancels.
    """
    from reeln.core.teams import list_team_profiles, load_team_profile

    if preset is not None:
        return load_team_profile(level, preset)

    slugs = list_team_profiles(level)
    create_label = "[Create new team]"
    choices = [*slugs, create_label]

    questionary = _require_questionary()
    answer: str | None = questionary.select(
        f"Select {role} team:",
        choices=choices,
    ).ask()
    if not answer:
        raise PromptAborted(f"{role.title()} team prompt cancelled")

    if answer == create_label:
        return create_team_interactive(level, role)

    return load_team_profile(level, answer)


def create_team_interactive(level: str, role: str) -> TeamProfile:
    """Interactively create and save a new team profile.

    Prompts for team name and short name, saves to disk, and returns the
    profile.
    """
    from reeln.core.teams import save_team_profile, slugify

    questionary = _require_questionary()

    name: str | None = questionary.text(f"New {role} team name:").ask()
    if not name:
        raise PromptAborted(f"New {role} team creation cancelled")

    short_name: str | None = questionary.text(
        "Short name (abbreviation):",
        default=name[:3].upper(),
    ).ask()
    if not short_name:
        raise PromptAborted(f"New {role} team creation cancelled")

    profile = TeamProfile(team_name=name, short_name=short_name, level=level)
    slug = slugify(name)
    save_team_profile(profile, slug)
    return profile


def prompt_description(preset: str | None = None) -> str:
    """Prompt for a broadcast description, or return *preset*.

    Description is optional — an empty answer is accepted (returns ``""``).
    """
    if preset is not None:
        return preset
    questionary = _require_questionary()
    answer: str | None = questionary.text("Broadcast description (optional):").ask()
    if answer is None:
        return ""
    return answer


def prompt_thumbnail(preset: str | None = None) -> str:
    """Prompt for a thumbnail file path, or return *preset*.

    Thumbnail is optional — an empty answer is accepted (returns ``""``).
    """
    if preset is not None:
        return preset
    questionary = _require_questionary()
    answer: str | None = questionary.text("Thumbnail image path (optional):").ask()
    if answer is None:
        return ""
    return answer


def prompt_period_length(preset: int | None = None) -> int:
    """Prompt for the period/segment length in minutes, or return *preset*.

    Defaults to ``15`` when the user enters a non-numeric value.
    Raises ``PromptAborted`` if the user cancels.
    """
    if preset is not None:
        return preset
    questionary = _require_questionary()
    answer: str | None = questionary.text(
        "Period/segment length in minutes:",
        default="15",
    ).ask()
    if answer is None:
        raise PromptAborted("Period length prompt cancelled")
    try:
        return int(answer)
    except ValueError:
        return 15


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def collect_game_info_interactive(
    *,
    home: str | None = None,
    away: str | None = None,
    sport: str | None = None,
    game_date: str | None = None,
    venue: str | None = None,
    game_time: str | None = None,
    period_length: int | None = None,
    description: str | None = None,
    thumbnail: str | None = None,
) -> dict[str, Any]:
    """Collect all game info fields, prompting only for missing values.

    Returns a dict with keys: ``home``, ``away``, ``sport``, ``game_date``,
    ``venue``, ``game_time``, ``period_length``, ``home_profile``,
    ``away_profile``.

    When either team is missing (``None``), prompts for a team level and
    uses :func:`prompt_team` to select or create team profiles.  Preset
    teams bypass profile selection entirely.
    """
    result: dict[str, Any] = {}

    # Sport first — needed before level/team prompting
    result["sport"] = prompt_sport(preset=sport)

    # If either team needs prompting, go through level + profile selection
    home_profile: TeamProfile | None = None
    away_profile: TeamProfile | None = None

    if home is None or away is None:
        level = prompt_level()
        if home is None:
            home_profile = prompt_team(level, "home")
            result["home"] = home_profile.team_name
        else:
            result["home"] = home
        if away is None:
            away_profile = prompt_team(level, "away")
            result["away"] = away_profile.team_name
        else:
            result["away"] = away
    else:
        result["home"] = home
        result["away"] = away

    result["home_profile"] = home_profile
    result["away_profile"] = away_profile

    result["game_date"] = prompt_date(preset=game_date)
    result["venue"] = prompt_venue(preset=venue)
    result["game_time"] = prompt_game_time(preset=game_time)
    result["period_length"] = prompt_period_length(preset=period_length)
    result["description"] = prompt_description(preset=description)
    result["thumbnail"] = prompt_thumbnail(preset=thumbnail)

    return result
