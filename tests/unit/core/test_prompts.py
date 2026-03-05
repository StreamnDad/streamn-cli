"""Tests for interactive prompt helpers."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from reeln.core.errors import PromptAborted, ReelnError
from reeln.core.prompts import (
    _require_questionary,
    collect_game_info_interactive,
    create_team_interactive,
    prompt_away_team,
    prompt_date,
    prompt_description,
    prompt_game_time,
    prompt_home_team,
    prompt_level,
    prompt_period_length,
    prompt_sport,
    prompt_team,
    prompt_thumbnail,
    prompt_venue,
)
from reeln.models.team import TeamProfile

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_questionary() -> MagicMock:
    """Return a MagicMock that replaces questionary."""
    return MagicMock()


# ---------------------------------------------------------------------------
# _require_questionary
# ---------------------------------------------------------------------------


def test_require_questionary_returns_module_when_present() -> None:
    """If questionary is installed, the real module is returned."""
    fake_mod = MagicMock()
    with (
        patch("reeln.core.prompts.sys") as mock_sys,
        patch.dict("sys.modules", {"questionary": fake_mod}),
    ):
        mock_sys.stdin.isatty.return_value = True
        result = _require_questionary()
    assert result is fake_mod


def test_require_questionary_raises_when_missing() -> None:
    """If questionary is not installed, a helpful ReelnError is raised."""
    with (
        patch("reeln.core.prompts.sys") as mock_sys,
        patch.dict("sys.modules", {"questionary": None}),
        pytest.raises(ReelnError, match="pip install reeln\\[interactive\\]"),
    ):
        mock_sys.stdin.isatty.return_value = True
        _require_questionary()


def test_require_questionary_raises_when_not_tty() -> None:
    """If stdin is not a TTY, a helpful ReelnError is raised."""
    with (
        patch("reeln.core.prompts.sys") as mock_sys,
        pytest.raises(ReelnError, match="require a terminal"),
    ):
        mock_sys.stdin.isatty.return_value = False
        _require_questionary()


# ---------------------------------------------------------------------------
# prompt_home_team
# ---------------------------------------------------------------------------


def test_prompt_home_team_preset_returns_immediately() -> None:
    assert prompt_home_team(preset="eagles") == "eagles"


def test_prompt_home_team_interactive(mock_questionary: MagicMock) -> None:
    mock_questionary.text.return_value.ask.return_value = "roseville"
    with patch("reeln.core.prompts._require_questionary", return_value=mock_questionary):
        result = prompt_home_team()
    assert result == "roseville"
    mock_questionary.text.assert_called_once_with("Home team name:")


def test_prompt_home_team_cancelled(mock_questionary: MagicMock) -> None:
    mock_questionary.text.return_value.ask.return_value = None
    with (
        patch("reeln.core.prompts._require_questionary", return_value=mock_questionary),
        pytest.raises(PromptAborted, match="Home team"),
    ):
        prompt_home_team()


def test_prompt_home_team_empty_string(mock_questionary: MagicMock) -> None:
    mock_questionary.text.return_value.ask.return_value = ""
    with (
        patch("reeln.core.prompts._require_questionary", return_value=mock_questionary),
        pytest.raises(PromptAborted, match="Home team"),
    ):
        prompt_home_team()


# ---------------------------------------------------------------------------
# prompt_away_team
# ---------------------------------------------------------------------------


def test_prompt_away_team_preset_returns_immediately() -> None:
    assert prompt_away_team(preset="bears") == "bears"


def test_prompt_away_team_interactive(mock_questionary: MagicMock) -> None:
    mock_questionary.text.return_value.ask.return_value = "mahtomedi"
    with patch("reeln.core.prompts._require_questionary", return_value=mock_questionary):
        result = prompt_away_team()
    assert result == "mahtomedi"
    mock_questionary.text.assert_called_once_with("Away team name:")


def test_prompt_away_team_cancelled(mock_questionary: MagicMock) -> None:
    mock_questionary.text.return_value.ask.return_value = None
    with (
        patch("reeln.core.prompts._require_questionary", return_value=mock_questionary),
        pytest.raises(PromptAborted, match="Away team"),
    ):
        prompt_away_team()


# ---------------------------------------------------------------------------
# prompt_sport
# ---------------------------------------------------------------------------


def test_prompt_sport_preset_returns_immediately() -> None:
    assert prompt_sport(preset="hockey") == "hockey"


def test_prompt_sport_interactive(mock_questionary: MagicMock) -> None:
    mock_questionary.select.return_value.ask.return_value = "basketball"
    with patch("reeln.core.prompts._require_questionary", return_value=mock_questionary):
        result = prompt_sport()
    assert result == "basketball"
    # Verify select was called with sport choices
    call_kwargs = mock_questionary.select.call_args
    assert "Sport:" in call_kwargs.args or call_kwargs.kwargs.get("prompt") == "Sport:"
    choices = call_kwargs.kwargs.get("choices") or call_kwargs.args[1]
    assert "hockey" in choices
    assert "basketball" in choices


def test_prompt_sport_cancelled(mock_questionary: MagicMock) -> None:
    mock_questionary.select.return_value.ask.return_value = None
    with (
        patch("reeln.core.prompts._require_questionary", return_value=mock_questionary),
        pytest.raises(PromptAborted, match="Sport"),
    ):
        prompt_sport()


# ---------------------------------------------------------------------------
# prompt_date
# ---------------------------------------------------------------------------


def test_prompt_date_preset_returns_immediately() -> None:
    assert prompt_date(preset="2026-12-25") == "2026-12-25"


def test_prompt_date_interactive(mock_questionary: MagicMock) -> None:
    mock_questionary.text.return_value.ask.return_value = "2026-03-15"
    with patch("reeln.core.prompts._require_questionary", return_value=mock_questionary):
        result = prompt_date()
    assert result == "2026-03-15"
    today = date.today().isoformat()
    mock_questionary.text.assert_called_once_with("Game date (YYYY-MM-DD):", default=today)


def test_prompt_date_cancelled(mock_questionary: MagicMock) -> None:
    mock_questionary.text.return_value.ask.return_value = None
    with (
        patch("reeln.core.prompts._require_questionary", return_value=mock_questionary),
        pytest.raises(PromptAborted, match="Date"),
    ):
        prompt_date()


# ---------------------------------------------------------------------------
# prompt_venue
# ---------------------------------------------------------------------------


def test_prompt_venue_preset_returns_immediately() -> None:
    assert prompt_venue(preset="OVAL") == "OVAL"


def test_prompt_venue_preset_empty_string_returns_immediately() -> None:
    assert prompt_venue(preset="") == ""


def test_prompt_venue_interactive(mock_questionary: MagicMock) -> None:
    mock_questionary.text.return_value.ask.return_value = "Xcel Energy Center"
    with patch("reeln.core.prompts._require_questionary", return_value=mock_questionary):
        result = prompt_venue()
    assert result == "Xcel Energy Center"


def test_prompt_venue_skipped_returns_empty(mock_questionary: MagicMock) -> None:
    """Venue is optional — empty string is accepted."""
    mock_questionary.text.return_value.ask.return_value = ""
    with patch("reeln.core.prompts._require_questionary", return_value=mock_questionary):
        result = prompt_venue()
    assert result == ""


def test_prompt_venue_cancelled_returns_empty(mock_questionary: MagicMock) -> None:
    """Venue is optional — cancellation returns empty, not PromptAborted."""
    mock_questionary.text.return_value.ask.return_value = None
    with patch("reeln.core.prompts._require_questionary", return_value=mock_questionary):
        result = prompt_venue()
    assert result == ""


# ---------------------------------------------------------------------------
# prompt_game_time
# ---------------------------------------------------------------------------


def test_prompt_game_time_preset_returns_immediately() -> None:
    assert prompt_game_time(preset="7:00 PM") == "7:00 PM"


def test_prompt_game_time_preset_empty_string_returns_immediately() -> None:
    assert prompt_game_time(preset="") == ""


def test_prompt_game_time_interactive(mock_questionary: MagicMock) -> None:
    mock_questionary.text.return_value.ask.return_value = "7:30 PM"
    with patch("reeln.core.prompts._require_questionary", return_value=mock_questionary):
        result = prompt_game_time()
    assert result == "7:30 PM"


def test_prompt_game_time_skipped_returns_empty(mock_questionary: MagicMock) -> None:
    """Game time is optional — empty string is accepted."""
    mock_questionary.text.return_value.ask.return_value = ""
    with patch("reeln.core.prompts._require_questionary", return_value=mock_questionary):
        result = prompt_game_time()
    assert result == ""


def test_prompt_game_time_cancelled_returns_empty(mock_questionary: MagicMock) -> None:
    """Game time is optional — cancellation returns empty, not PromptAborted."""
    mock_questionary.text.return_value.ask.return_value = None
    with patch("reeln.core.prompts._require_questionary", return_value=mock_questionary):
        result = prompt_game_time()
    assert result == ""


# ---------------------------------------------------------------------------
# prompt_level
# ---------------------------------------------------------------------------


def test_prompt_level_preset_returns_immediately() -> None:
    assert prompt_level(preset="bantam") == "bantam"


def test_prompt_level_no_levels_creates_level(mock_questionary: MagicMock) -> None:
    """When no levels exist, prompts for a new level name."""
    mock_questionary.text.return_value.ask.return_value = "  Bantam  "
    with (
        patch("reeln.core.teams.list_levels", return_value=[]),
        patch("reeln.core.prompts._require_questionary", return_value=mock_questionary),
    ):
        result = prompt_level()
    assert result == "bantam"
    mock_questionary.text.assert_called_once_with("Team level (e.g. bantam, varsity, jv):")


def test_prompt_level_no_levels_cancelled(mock_questionary: MagicMock) -> None:
    """When no levels exist and user cancels, raises PromptAborted."""
    mock_questionary.text.return_value.ask.return_value = None
    with (
        patch("reeln.core.teams.list_levels", return_value=[]),
        patch("reeln.core.prompts._require_questionary", return_value=mock_questionary),
        pytest.raises(PromptAborted, match="Level prompt cancelled"),
    ):
        prompt_level()


def test_prompt_level_no_levels_empty_string(mock_questionary: MagicMock) -> None:
    """When no levels exist and user enters empty string, raises PromptAborted."""
    mock_questionary.text.return_value.ask.return_value = ""
    with (
        patch("reeln.core.teams.list_levels", return_value=[]),
        patch("reeln.core.prompts._require_questionary", return_value=mock_questionary),
        pytest.raises(PromptAborted, match="Level prompt cancelled"),
    ):
        prompt_level()


def test_prompt_level_single_auto_selects() -> None:
    with patch("reeln.core.teams.list_levels", return_value=["varsity"]):
        result = prompt_level()
    assert result == "varsity"


def test_prompt_level_multiple_prompts(mock_questionary: MagicMock) -> None:
    mock_questionary.select.return_value.ask.return_value = "bantam"
    with (
        patch("reeln.core.teams.list_levels", return_value=["bantam", "varsity"]),
        patch("reeln.core.prompts._require_questionary", return_value=mock_questionary),
    ):
        result = prompt_level()
    assert result == "bantam"
    mock_questionary.select.assert_called_once_with("Team level:", choices=["bantam", "varsity"])


def test_prompt_level_cancelled_raises(mock_questionary: MagicMock) -> None:
    mock_questionary.select.return_value.ask.return_value = None
    with (
        patch("reeln.core.teams.list_levels", return_value=["bantam", "varsity"]),
        patch("reeln.core.prompts._require_questionary", return_value=mock_questionary),
        pytest.raises(PromptAborted, match="Level prompt cancelled"),
    ):
        prompt_level()


# ---------------------------------------------------------------------------
# prompt_team
# ---------------------------------------------------------------------------


def test_prompt_team_preset_loads_profile() -> None:
    profile = TeamProfile(team_name="Roseville", short_name="ROS", level="bantam")
    with patch("reeln.core.teams.load_team_profile", return_value=profile) as mock_load:
        result = prompt_team("bantam", "home", preset="roseville")
    assert result == profile
    mock_load.assert_called_once_with("bantam", "roseville")


def test_prompt_team_selects_existing(mock_questionary: MagicMock) -> None:
    profile = TeamProfile(team_name="Roseville", short_name="ROS", level="bantam")
    mock_questionary.select.return_value.ask.return_value = "roseville"
    with (
        patch("reeln.core.teams.list_team_profiles", return_value=["mahtomedi", "roseville"]),
        patch("reeln.core.teams.load_team_profile", return_value=profile) as mock_load,
        patch("reeln.core.prompts._require_questionary", return_value=mock_questionary),
    ):
        result = prompt_team("bantam", "home")
    assert result == profile
    mock_load.assert_called_once_with("bantam", "roseville")


def test_prompt_team_create_new(mock_questionary: MagicMock) -> None:
    mock_questionary.select.return_value.ask.return_value = "[Create new team]"
    new_profile = TeamProfile(team_name="NewTeam", short_name="NEW", level="bantam")
    with (
        patch("reeln.core.teams.list_team_profiles", return_value=["roseville"]),
        patch("reeln.core.prompts._require_questionary", return_value=mock_questionary),
        patch("reeln.core.prompts.create_team_interactive", return_value=new_profile) as mock_create,
    ):
        result = prompt_team("bantam", "away")
    assert result == new_profile
    mock_create.assert_called_once_with("bantam", "away")


def test_prompt_team_cancelled_raises(mock_questionary: MagicMock) -> None:
    mock_questionary.select.return_value.ask.return_value = None
    with (
        patch("reeln.core.teams.list_team_profiles", return_value=["roseville"]),
        patch("reeln.core.prompts._require_questionary", return_value=mock_questionary),
        pytest.raises(PromptAborted, match="Home team prompt cancelled"),
    ):
        prompt_team("bantam", "home")


# ---------------------------------------------------------------------------
# create_team_interactive
# ---------------------------------------------------------------------------


def test_create_team_interactive_success(mock_questionary: MagicMock) -> None:
    mock_questionary.text.return_value.ask.side_effect = ["Roseville", "ROS"]
    with (
        patch("reeln.core.prompts._require_questionary", return_value=mock_questionary),
        patch("reeln.core.teams.save_team_profile") as mock_save,
    ):
        result = create_team_interactive("bantam", "home")

    assert result.team_name == "Roseville"
    assert result.short_name == "ROS"
    assert result.level == "bantam"
    mock_save.assert_called_once()
    # Verify the slug passed to save
    call_args = mock_save.call_args
    assert call_args[0][1] == "roseville"


def test_create_team_interactive_name_cancelled(mock_questionary: MagicMock) -> None:
    mock_questionary.text.return_value.ask.return_value = None
    with (
        patch("reeln.core.prompts._require_questionary", return_value=mock_questionary),
        pytest.raises(PromptAborted, match="creation cancelled"),
    ):
        create_team_interactive("bantam", "home")


def test_create_team_interactive_name_empty(mock_questionary: MagicMock) -> None:
    mock_questionary.text.return_value.ask.return_value = ""
    with (
        patch("reeln.core.prompts._require_questionary", return_value=mock_questionary),
        pytest.raises(PromptAborted, match="creation cancelled"),
    ):
        create_team_interactive("bantam", "away")


def test_create_team_interactive_short_name_cancelled(mock_questionary: MagicMock) -> None:
    mock_questionary.text.return_value.ask.side_effect = ["Roseville", None]
    with (
        patch("reeln.core.prompts._require_questionary", return_value=mock_questionary),
        pytest.raises(PromptAborted, match="creation cancelled"),
    ):
        create_team_interactive("bantam", "home")


# ---------------------------------------------------------------------------
# prompt_period_length
# ---------------------------------------------------------------------------


def test_prompt_period_length_preset_returns_immediately() -> None:
    assert prompt_period_length(preset=12) == 12


def test_prompt_period_length_preset_zero_returns_immediately() -> None:
    assert prompt_period_length(preset=0) == 0


def test_prompt_period_length_interactive(mock_questionary: MagicMock) -> None:
    mock_questionary.text.return_value.ask.return_value = "20"
    with patch("reeln.core.prompts._require_questionary", return_value=mock_questionary):
        result = prompt_period_length()
    assert result == 20
    mock_questionary.text.assert_called_once_with(
        "Period/segment length in minutes:",
        default="15",
    )


def test_prompt_period_length_invalid_defaults_to_15(mock_questionary: MagicMock) -> None:
    """Non-numeric input falls back to 15."""
    mock_questionary.text.return_value.ask.return_value = "abc"
    with patch("reeln.core.prompts._require_questionary", return_value=mock_questionary):
        result = prompt_period_length()
    assert result == 15


def test_prompt_period_length_cancelled_raises(mock_questionary: MagicMock) -> None:
    mock_questionary.text.return_value.ask.return_value = None
    with (
        patch("reeln.core.prompts._require_questionary", return_value=mock_questionary),
        pytest.raises(PromptAborted, match="Period length"),
    ):
        prompt_period_length()


# ---------------------------------------------------------------------------
# prompt_description
# ---------------------------------------------------------------------------


def test_prompt_description_preset_returns_immediately() -> None:
    assert prompt_description(preset="Big game") == "Big game"


def test_prompt_description_preset_empty_string_returns_immediately() -> None:
    assert prompt_description(preset="") == ""


def test_prompt_description_interactive(mock_questionary: MagicMock) -> None:
    mock_questionary.text.return_value.ask.return_value = "Championship game"
    with patch("reeln.core.prompts._require_questionary", return_value=mock_questionary):
        result = prompt_description()
    assert result == "Championship game"


def test_prompt_description_skipped_returns_empty(mock_questionary: MagicMock) -> None:
    """Description is optional — empty string is accepted."""
    mock_questionary.text.return_value.ask.return_value = ""
    with patch("reeln.core.prompts._require_questionary", return_value=mock_questionary):
        result = prompt_description()
    assert result == ""


def test_prompt_description_cancelled_returns_empty(mock_questionary: MagicMock) -> None:
    """Description is optional — cancellation returns empty, not PromptAborted."""
    mock_questionary.text.return_value.ask.return_value = None
    with patch("reeln.core.prompts._require_questionary", return_value=mock_questionary):
        result = prompt_description()
    assert result == ""


# ---------------------------------------------------------------------------
# prompt_thumbnail
# ---------------------------------------------------------------------------


def test_prompt_thumbnail_preset_returns_immediately() -> None:
    assert prompt_thumbnail(preset="/tmp/thumb.jpg") == "/tmp/thumb.jpg"


def test_prompt_thumbnail_preset_empty_string_returns_immediately() -> None:
    assert prompt_thumbnail(preset="") == ""


def test_prompt_thumbnail_interactive(mock_questionary: MagicMock) -> None:
    mock_questionary.text.return_value.ask.return_value = "/img/banner.png"
    with patch("reeln.core.prompts._require_questionary", return_value=mock_questionary):
        result = prompt_thumbnail()
    assert result == "/img/banner.png"


def test_prompt_thumbnail_skipped_returns_empty(mock_questionary: MagicMock) -> None:
    """Thumbnail is optional — empty string is accepted."""
    mock_questionary.text.return_value.ask.return_value = ""
    with patch("reeln.core.prompts._require_questionary", return_value=mock_questionary):
        result = prompt_thumbnail()
    assert result == ""


def test_prompt_thumbnail_cancelled_returns_empty(mock_questionary: MagicMock) -> None:
    """Thumbnail is optional — cancellation returns empty, not PromptAborted."""
    mock_questionary.text.return_value.ask.return_value = None
    with patch("reeln.core.prompts._require_questionary", return_value=mock_questionary):
        result = prompt_thumbnail()
    assert result == ""


# ---------------------------------------------------------------------------
# collect_game_info_interactive
# ---------------------------------------------------------------------------


def test_collect_all_presets_no_import_needed() -> None:
    """When all presets are provided, questionary is never imported."""
    result = collect_game_info_interactive(
        home="eagles",
        away="bears",
        sport="hockey",
        game_date="2026-03-15",
        venue="OVAL",
        game_time="7:00 PM",
        period_length=15,
        description="Big game",
        thumbnail="/tmp/thumb.jpg",
    )
    assert result["home"] == "eagles"
    assert result["away"] == "bears"
    assert result["sport"] == "hockey"
    assert result["game_date"] == "2026-03-15"
    assert result["venue"] == "OVAL"
    assert result["game_time"] == "7:00 PM"
    assert result["period_length"] == 15
    assert result["description"] == "Big game"
    assert result["thumbnail"] == "/tmp/thumb.jpg"
    assert result["home_profile"] is None
    assert result["away_profile"] is None


def test_collect_no_profiles_when_both_preset() -> None:
    """When both teams are preset, no level prompt and no profiles."""
    result = collect_game_info_interactive(
        home="eagles",
        away="bears",
        sport="hockey",
        game_date="2026-03-15",
        venue="OVAL",
        game_time="7:00 PM",
        period_length=15,
        description="",
        thumbnail="",
    )
    assert result["home_profile"] is None
    assert result["away_profile"] is None


def test_collect_with_profiles(mock_questionary: MagicMock) -> None:
    """When both teams are missing, level + team selection returns profiles."""
    home_prof = TeamProfile(team_name="Eagles", short_name="EGL", level="bantam")
    away_prof = TeamProfile(team_name="Bears", short_name="BRS", level="bantam")

    with (
        patch("reeln.core.prompts.prompt_sport", return_value="hockey"),
        patch("reeln.core.prompts.prompt_level", return_value="bantam"),
        patch("reeln.core.prompts.prompt_team", side_effect=[home_prof, away_prof]),
        patch("reeln.core.prompts.prompt_date", return_value="2026-03-15"),
        patch("reeln.core.prompts.prompt_venue", return_value="OVAL"),
        patch("reeln.core.prompts.prompt_game_time", return_value="7:00 PM"),
        patch("reeln.core.prompts.prompt_period_length", return_value=15),
        patch("reeln.core.prompts.prompt_description", return_value="Test desc"),
        patch("reeln.core.prompts.prompt_thumbnail", return_value="/tmp/t.jpg"),
    ):
        result = collect_game_info_interactive()

    assert result["home"] == "Eagles"
    assert result["away"] == "Bears"
    assert result["home_profile"] is home_prof
    assert result["away_profile"] is away_prof
    assert result["sport"] == "hockey"
    assert result["game_date"] == "2026-03-15"
    assert result["venue"] == "OVAL"
    assert result["game_time"] == "7:00 PM"
    assert result["period_length"] == 15
    assert result["description"] == "Test desc"
    assert result["thumbnail"] == "/tmp/t.jpg"


def test_collect_with_profiles_and_presets() -> None:
    """One team preset (string), one prompted (profile) — mixed result."""
    away_prof = TeamProfile(team_name="Bears", short_name="BRS", level="bantam")

    with (
        patch("reeln.core.prompts.prompt_sport", return_value="hockey"),
        patch("reeln.core.prompts.prompt_level", return_value="bantam"),
        patch("reeln.core.prompts.prompt_team", return_value=away_prof) as mock_team,
        patch("reeln.core.prompts.prompt_date", return_value="2026-03-15"),
        patch("reeln.core.prompts.prompt_venue", return_value=""),
        patch("reeln.core.prompts.prompt_game_time", return_value=""),
        patch("reeln.core.prompts.prompt_period_length", return_value=15),
        patch("reeln.core.prompts.prompt_description", return_value=""),
        patch("reeln.core.prompts.prompt_thumbnail", return_value=""),
    ):
        result = collect_game_info_interactive(
            home="roseville",
            away=None,
            sport="hockey",
            game_date="2026-03-15",
            venue="",
            game_time="",
        )

    assert result["home"] == "roseville"
    assert result["away"] == "Bears"
    assert result["home_profile"] is None
    assert result["away_profile"] is away_prof
    # prompt_team called once for away only
    mock_team.assert_called_once_with("bantam", "away")


def test_collect_with_home_prompted_away_preset() -> None:
    """Home is None (prompted via profile), away is preset string."""
    home_prof = TeamProfile(team_name="Eagles", short_name="EGL", level="bantam")

    with (
        patch("reeln.core.prompts.prompt_sport", return_value="hockey"),
        patch("reeln.core.prompts.prompt_level", return_value="bantam"),
        patch("reeln.core.prompts.prompt_team", return_value=home_prof) as mock_team,
        patch("reeln.core.prompts.prompt_date", return_value="2026-03-15"),
        patch("reeln.core.prompts.prompt_venue", return_value=""),
        patch("reeln.core.prompts.prompt_game_time", return_value=""),
        patch("reeln.core.prompts.prompt_period_length", return_value=15),
        patch("reeln.core.prompts.prompt_description", return_value=""),
        patch("reeln.core.prompts.prompt_thumbnail", return_value=""),
    ):
        result = collect_game_info_interactive(
            home=None,
            away="bears",
            sport="hockey",
            game_date="2026-03-15",
            venue="",
            game_time="",
        )

    assert result["home"] == "Eagles"
    assert result["away"] == "bears"
    assert result["home_profile"] is home_prof
    assert result["away_profile"] is None
    # prompt_team called once for home only
    mock_team.assert_called_once_with("bantam", "home")


def test_collect_abort_propagates() -> None:
    """PromptAborted from a sub-prompt propagates up."""
    with (
        patch("reeln.core.prompts.prompt_sport", side_effect=PromptAborted("Sport prompt cancelled")),
        pytest.raises(PromptAborted),
    ):
        collect_game_info_interactive()


def test_collect_all_interactive() -> None:
    """When no presets are given, all fields are prompted via level+team."""
    home_prof = TeamProfile(team_name="Eagles", short_name="EGL", level="bantam")
    away_prof = TeamProfile(team_name="Bears", short_name="BRS", level="bantam")

    with (
        patch("reeln.core.prompts.prompt_sport", return_value="hockey"),
        patch("reeln.core.prompts.prompt_level", return_value="bantam"),
        patch("reeln.core.prompts.prompt_team", side_effect=[home_prof, away_prof]),
        patch("reeln.core.prompts.prompt_date", return_value=date.today().isoformat()),
        patch("reeln.core.prompts.prompt_venue", return_value="OVAL"),
        patch("reeln.core.prompts.prompt_game_time", return_value="7:00 PM"),
        patch("reeln.core.prompts.prompt_period_length", return_value=15),
        patch("reeln.core.prompts.prompt_description", return_value="Game day"),
        patch("reeln.core.prompts.prompt_thumbnail", return_value=""),
    ):
        result = collect_game_info_interactive()

    assert result["home"] == "Eagles"
    assert result["away"] == "Bears"
    assert result["sport"] == "hockey"
    assert result["game_date"] == date.today().isoformat()
    assert result["venue"] == "OVAL"
    assert result["game_time"] == "7:00 PM"
    assert result["period_length"] == 15
    assert result["description"] == "Game day"
    assert result["thumbnail"] == ""
    assert result["home_profile"] is home_prof
    assert result["away_profile"] is away_prof
