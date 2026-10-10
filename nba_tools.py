"""NBA statistics and research tools for EdgeLab Sports AI."""
import math
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
import requests
import streamlit as st

ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
NBA_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.nba.com/"}
HEADERS = {"User-Agent": "EdgeLabSportsAI/1.0"}


def season_name(end_year):
    return f"{end_year - 1}-{str(end_year)[-2:]}"


def current_season_end():
    today = datetime.now(timezone.utc).date()
    return today.year + 1 if today.month >= 7 else today.year


def stats_params(end_year, season_type):
    return {
        "LeagueID": "00", "Season": season_name(end_year),
        "SeasonType": season_type, "MeasureType": "Base", "PerMode": "PerGame",
        "PaceAdjust": "N", "PlusMinus": "N", "Rank": "N", "LastNGames": 0,
        "Month": 0, "OpponentTeamID": 0, "PORound": 0, "Period": 0, "TeamID": 0,
        "DateFrom": "", "DateTo": "", "Conference": "", "Division": "",
        "GameScope": "", "GameSegment": "", "Location": "", "Outcome": "",
        "SeasonSegment": "", "VsConference": "", "VsDivision": "",
        "PlayerExperience": "", "PlayerPosition": "", "StarterBench": "",
        "College": "", "Height": "", "Weight": "", "ShotClockRange": "",
    }


def nba_request(endpoint, params):
    response = requests.get(
        f"https://stats.nba.com/stats/{endpoint}", params=params,
        headers=NBA_HEADERS, timeout=25,
    )
    response.raise_for_status()
    data = response.json()
    returned = data.get("parameters", {})
    for key in ("Season", "SeasonType"):
        if key in returned and returned[key] != params[key]:
            raise ValueError(f"NBA.com returned a different {key}.")
    return data


def result_set(data):
    results = data.get("resultSets")
    if isinstance(results, list):
        if not results:
            raise ValueError("No NBA result set returned.")
        results = results[0]
    if not isinstance(results, dict):
        raise ValueError("Unrecognized NBA statistics response.")
    return results


def flat_rows(data):
    result = result_set(data)
    headers = result.get("headers", [])
    if not all(isinstance(name, str) for name in headers):
        raise ValueError("Expected flat statistics headers.")
    rows = []
    for values in result.get("rowSet", []):
        if len(values) != len(headers):
            raise ValueError("Statistics row length does not match its headers.")
        rows.append(dict(zip(headers, values)))
    return rows


def percentage(made, attempted):
    if not isinstance(attempted, (int, float)) or attempted <= 0:
        return None
    if not isinstance(made, (int, float)):
        return None
    return round(100 * made / attempted, 2)


def parse_shooting_zones(data):
    result = result_set(data)
    zone_header = next(
        header for header in result["headers"]
        if header.get("name") == "SHOT_CATEGORY"
    )
    column_header = next(
        header for header in result["headers"]
        if header.get("name") == "columns"
    )
    zones = zone_header["columnNames"]
    if "Mid-Range" not in zones:
        raise ValueError("NBA.com did not return the Mid-Range category.")
    offset = zone_header["columnsToSkip"]
    span = zone_header["columnSpan"]
    if span != 3:
        raise ValueError("Unexpected shooting-zone column format.")
    identities = column_header["columnNames"][:offset]
    rows = []
    for values in result.get("rowSet", []):
        if len(values) != offset + span * len(zones):
            raise ValueError("Unexpected shooting-zone row length.")
        row = dict(zip(identities, values[:offset]))
        index = offset + span * zones.index("Mid-Range")
        made, attempts = values[index:index + 2]
        row.update({
            "Mid-range made": made, "Mid-range attempts": attempts,
            "Mid-range FG %": percentage(made, attempts),
        })
        rows.append(row)
    return rows


@st.cache_data(ttl=3600)
def load_nba_team_stats(end_year, season_type):
    params = stats_params(end_year, season_type)

    def fetch(measure):
        query = dict(params, MeasureType=measure)
        return flat_rows(nba_request("leaguedashteamstats", query))

    with ThreadPoolExecutor(max_workers=2) as pool:
        own, opponent = list(pool.map(fetch, ("Base", "Opponent")))
    opponent_by_id = {row["TEAM_ID"]: row for row in opponent}
    for row in own:
        row.update({
            key: value for key, value in opponent_by_id.get(row["TEAM_ID"], {}).items()
            if key.startswith("OPP_")
        })
    return {
        "rows": own,
        "retrieved": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }


@st.cache_data(ttl=3600)
def load_nba_player_stats(end_year, season_type):
    return flat_rows(nba_request(
        "leaguedashplayerstats", stats_params(end_year, season_type),
    ))


@st.cache_data(ttl=3600)
def load_nba_shooting(end_year, season_type, scope):
    params = dict(
        stats_params(end_year, season_type),
        DistanceRange="By Zone", PerMode="Totals",
    )
    endpoint = (
        "leaguedashteamshotlocations" if scope == "teams"
        else "leaguedashplayershotlocations"
    )
    return parse_shooting_zones(nba_request(endpoint, params))


TEAM_METRICS = [
    ("Offense: points per game", "PTS", True, False),
    ("Offense: field goal %", "FG_PCT", True, True),
    ("Offense: three-point %", "FG3_PCT", True, True),
    ("Offense: assists per game", "AST", True, False),
    ("Offense: turnovers per game", "TOV", False, False),
    ("Rebounds per game", "REB", True, False),
    ("Defense: points allowed per game", "OPP_PTS", False, False),
    ("Defense: opponent field goal %", "OPP_FG_PCT", False, True),
    ("Defense: opponent three-point %", "OPP_FG3_PCT", False, True),
    ("Defense: steals per game", "STL", True, False),
    ("Defense: blocks per game", "BLK", True, False),
]


def metric_value(row, key, is_percent):
    value = row.get(key)
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    if is_percent:
        attempt_key = {
            "FG_PCT": "FGA", "FG3_PCT": "FG3A",
            "OPP_FG_PCT": "OPP_FGA", "OPP_FG3_PCT": "OPP_FG3A",
        }.get(key)
        if attempt_key and (row.get(attempt_key) or 0) <= 0:
            return None
        value *= 100
    return value


def team_comparison(selected, league):
    output = []
    for label, key, higher_better, is_percent in TEAM_METRICS:
        value = metric_value(selected, key, is_percent)
        available = [
            candidate for row in league
            if (row.get("GP") or 0) > 0
            and (candidate := metric_value(row, key, is_percent)) is not None
        ]
        if value is None or not available:
            output.append({"Statistic": label, "Team value": None,
                           "League average": None, "Rank": None,
                           "Teams compared": len(available), "Assessment": "Unavailable"})
            continue
        average = sum(available) / len(available)
        rank = 1 + sum(
            other > value if higher_better else other < value for other in available
        )
        better = value > average if higher_better else value < average
        output.append({
            "Statistic": label, "Team value": round(value, 2),
            "League average": round(average, 2), "Rank": rank,
            "Teams compared": len(available),
            "Assessment": "At league average" if value == average else
                          "Above league average" if better else "Below league average",
        })
    return output


def shooting_lookup(rows, identity):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row[identity]].append(row)
    # Ambiguous identities are left unavailable instead of silently picking one.
    return {key: values[0] for key, values in grouped.items() if len(values) == 1}


def player_display_rows(players, team_id, zones):
    zone_lookup = shooting_lookup(zones, "PLAYER_ID")
    output = []
    for player in players:
        if player.get("TEAM_ID") != team_id:
            continue
        row = {
            "Player": player["PLAYER_NAME"], "Games": player.get("GP"),
            "Minutes/game": player.get("MIN"), "Points/game": player.get("PTS"),
            "Rebounds/game": player.get("REB"), "Assists/game": player.get("AST"),
            "Steals/game": player.get("STL"), "Blocks/game": player.get("BLK"),
            "Turnovers/game": player.get("TOV"),
            "FG %": round(player["FG_PCT"] * 100, 2) if (player.get("FGA") or 0) > 0 and player.get("FG_PCT") is not None else None,
            "3-point %": round(player["FG3_PCT"] * 100, 2) if (player.get("FG3A") or 0) > 0 and player.get("FG3_PCT") is not None else None,
            "3-point made/game": player.get("FG3M"),
            "3-point attempts/game": player.get("FG3A"),
            "Free throw %": round(player["FT_PCT"] * 100, 2) if (player.get("FTA") or 0) > 0 and player.get("FT_PCT") is not None else None,
        }
        zone = zone_lookup.get(player["PLAYER_ID"])
        # Validate team association before joining separate shooting data.
        if zone and zone.get("TEAM_ID") != team_id:
            zone = None
        for key in ("Mid-range FG %", "Mid-range made", "Mid-range attempts"):
            row[key] = zone.get(key) if zone else None
        output.append(row)
    return sorted(output, key=lambda row: row.get("Points/game") or 0, reverse=True)


@st.cache_data(ttl=300)
def load_nba_injuries():
    response = requests.get(f"{ESPN}/injuries", headers=HEADERS, timeout=20)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data.get("injuries"), list):
        raise ValueError("Unrecognized NBA injury report.")
    rows, teams = [], []
    for group in data["injuries"]:
        team = group.get("displayName", "Unknown team")
        teams.append(team)
        for injury in group.get("injuries", []):
            athlete = injury.get("athlete", {})
            details = injury.get("details") or {}
            rows.append({
                "Team": team, "Player": athlete.get("displayName", "Unknown"),
                "Position": athlete.get("position", {}).get("abbreviation", "Unknown"),
                "Status": injury.get("status") or "Unknown",
                "Injury": details.get("type") or "Not provided",
                "Report updated (UTC)": injury.get("date") or "Not provided",
            })
    return {
        "rows": rows, "teams": sorted(set(teams)),
        "source_timestamp": data.get("timestamp", "Not provided"),
        "retrieved": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }


@st.cache_data(ttl=300)
def load_nba_game_details(event_id):
    response = requests.get(
        f"{ESPN}/summary", params={"event": event_id},
        headers=HEADERS, timeout=20,
    )
    response.raise_for_status()
    data = response.json()
    if str(data.get("header", {}).get("id")) != str(event_id):
        raise ValueError("ESPN returned a different game.")
    return data.get("gameInfo") or {}


def parse_nba_game_logs(season_logs):
    games = {}
    for end_year, rows in season_logs:
        grouped = defaultdict(list)
        for row in rows:
            if str(row.get("SEASON_ID")) != "2" + str(end_year - 1):
                raise ValueError("NBA game log contains a different season or game type.")
            if row.get("WL") not in ("W", "L"):
                continue
            grouped[str(row["GAME_ID"])].append(row)
        for game_id, entries in grouped.items():
            if len(entries) != 2:
                raise ValueError(f"Game {game_id} does not have exactly two completed team records.")
            home = next((row for row in entries if " vs. " in row.get("MATCHUP", "")), None)
            away = next((row for row in entries if " @ " in row.get("MATCHUP", "")), None)
            if home is None and all(" @ " in row.get("MATCHUP", "") for row in entries):
                # Neutral-venue logs can mark both teams as away. Do not invent a home side.
                continue
            if home is None or away is None:
                raise ValueError("Cannot identify NBA home and away teams.")
            game_date = datetime.strptime(home["GAME_DATE"][:10], "%Y-%m-%d").date()
            if game_date != datetime.strptime(away["GAME_DATE"][:10], "%Y-%m-%d").date():
                raise ValueError("Team game dates disagree.")
            if game_date > datetime.now(timezone.utc).date():
                continue
            scores = (home.get("PTS"), away.get("PTS"))
            if not all(isinstance(score, (int, float)) and math.isfinite(score) and score >= 0 for score in scores):
                raise ValueError("Invalid completed NBA scores.")
            games[game_id] = {
                "date": game_date, "season": end_year,
                "home_team": home["TEAM_ABBREVIATION"],
                "away_team": away["TEAM_ABBREVIATION"],
                "home_score": float(scores[0]), "away_score": float(scores[1]),
            }
    return sorted(games.values(), key=lambda game: (game["date"], game["home_team"]))


@st.cache_data(ttl=3600)
def load_nba_history(end_year):
    years = list(range(end_year - 4, end_year + 1))

    def fetch(year):
        params = {
            "LeagueID": "00", "Season": season_name(year),
            "SeasonType": "Regular Season", "PlayerOrTeam": "T",
            "Direction": "ASC", "Sorter": "DATE", "Counter": 1000,
            "DateFrom": "", "DateTo": "",
        }
        return year, flat_rows(nba_request("leaguegamelog", params))

    with ThreadPoolExecutor(max_workers=5) as pool:
        season_logs = list(pool.map(fetch, years))
    games = parse_nba_game_logs(season_logs)
    if len(games) < 100:
        raise ValueError("Too few completed regular-season NBA games for a backtest.")
    return games


def clear_nba_caches():
    for function in (
        load_nba_team_stats, load_nba_player_stats, load_nba_shooting,
        load_nba_injuries, load_nba_game_details, load_nba_history,
    ):
        function.clear()


def show_nba_model(shared, end_year):
    st.header("🏀 NBA Historical Prediction Model")
    st.caption(
        "Basic regular-season Elo research model. Preseason games and neutral-venue games without an identifiable home side are excluded. "
        "It does not account for current injuries, player stats, rest, travel, "
        "or sportsbook prices. K=20 and home advantage=55 are starting "
        "settings, not tuned NBA parameters."
    )
    if st.button("Load NBA model & backtest", key="nba_load_model"):
        st.session_state["nba_model_loaded"] = True
    if not st.session_state.get("nba_model_loaded"):
        st.info("Click Load NBA model & backtest to retrieve historical NBA results.")
        return
    try:
        with st.spinner("Loading completed NBA games and building ratings..."):
            games = load_nba_history(end_year)
            ratings, predictions = shared["build_elo_model"](games)
            summary, test_games = shared["get_backtest_summary"](predictions)
        st.success(f"Loaded {len(games):,} completed NBA regular-season games.")
        st.subheader("NBA Historical Backtest")
        if not summary:
            st.info("No test games available.")
            return
        columns = st.columns(5)
        for column, label, value in zip(columns, (
            "Test games", "Winner accuracy", "Brier score",
            "Baseline Brier", "Baseline winner accuracy",
        ), (
            f"{summary['test_games']:,}", f"{summary['accuracy'] * 100:.1f}%",
            f"{summary['brier']:.4f}", f"{summary['baseline_brier']:.4f}",
            f"{summary['baseline_accuracy'] * 100:.1f}%",
        )):
            column.metric(label, value)
        st.caption(
            f"Test period: {summary['first_date']} to {summary['last_date']}. "
            "Final 20% of games; predictions use ratings and baseline history "
            "from before each game date. The baseline uses the historical "
            "home-result average. Lower Brier is better."
        )
        st.subheader("NBA Backtest Results by Season")
        st.dataframe(
            shared["get_season_backtest_rows"](test_games),
            hide_index=True, use_container_width=True,
        )
        st.caption("Season numbers are ending years. First/current seasons may be partial.")
        st.subheader("NBA Probability Calibration")
        st.dataframe(
            shared["get_calibration_rows"](test_games),
            hide_index=True, use_container_width=True,
        )
        st.caption(
            "Compare average predicted home win % with actual home win %. "
            "Closer is better; small groups may fluctuate by chance."
        )
        adjustment = shared["test_probability_adjustment"](predictions)
        st.subheader("NBA Probability Adjustment Test")
        if adjustment:
            cols = st.columns(3)
            cols[0].metric("Original Brier (same games)", f"{adjustment['original_brier']:.4f}")
            cols[1].metric("Adjusted Brier", f"{adjustment['adjusted_brier']:.4f}")
            cols[2].metric("Brier improvement", f"{adjustment['improvement']:+.4f}")
            st.caption(
                f"Strength {adjustment['strength']:.2f}; learned from "
                f"{adjustment['calibration_first']} to {adjustment['calibration_last']}. "
                f"Evaluated on {adjustment['evaluation_games']:,} games from "
                f"{adjustment['evaluation_first']} to {adjustment['evaluation_last']}. "
                "Whole dates stay together. Positive improvement is better. "
                "The adjustment is experimental and may not improve later games; "
                "it preserves the favorite and winner accuracy."
            )
        st.subheader("Predict an NBA Matchup")
        teams = sorted(ratings)
        home = st.selectbox("NBA home team", teams, key="nba_home")
        away = st.selectbox(
            "NBA away team", [team for team in teams if team != home], key="nba_away",
        )
        probability = shared["expected_home_win"](ratings[home], ratings[away])
        matchup = [
            {"Team": home, "Original Elo win %": round(probability * 100, 1)},
            {"Team": away, "Original Elo win %": round((1 - probability) * 100, 1)},
        ]
        if adjustment:
            adjusted = shared["shrink_probability"](probability, adjustment["strength"])
            matchup[0]["Adjusted win %"] = round(adjusted * 100, 1)
            matchup[1]["Adjusted win %"] = round((1 - adjusted) * 100, 1)
        st.dataframe(matchup, hide_index=True, use_container_width=True)
        st.caption(
            "These estimates are for regular-season-style matchups, not a "
            "validated preseason model. Current injuries and stats below "
            "do not affect these percentages."
        )
        st.subheader("Current NBA Model Team Ratings")
        st.dataframe(
            [{"Team": team, "Elo rating": round(rating, 1)}
             for team, rating in sorted(ratings.items(), key=lambda item: item[1], reverse=True)],
            hide_index=True, use_container_width=True,
        )
        with st.expander("View recent NBA historical test predictions"):
            st.dataframe(test_games[-50:], hide_index=True, use_container_width=True)
    except (requests.exceptions.RequestException, ValueError, KeyError, TypeError, AttributeError) as exc:
        st.warning(f"NBA historical model could not be loaded: {exc}")


def show_nba_statistics(end_year):
    st.header("🏀 NBA Team Strengths, Weaknesses & Player Stats")
    season = st.selectbox(
        "NBA statistics season", list(range(end_year, end_year - 5, -1)),
        format_func=season_name, key="nba_stats_season",
    )
    type_label = st.selectbox(
        "NBA statistics season type", ["Preseason", "Regular season", "Playoffs"],
        index=0 if datetime.now(timezone.utc).month == 10 and season == end_year else 1,
        key="nba_stats_type",
    )
    type_name = {"Preseason": "Pre Season", "Regular season": "Regular Season", "Playoffs": "Playoffs"}[type_label]
    st.caption(
        "Preseason, regular season, and playoffs are kept separate. "
        "Current preseason samples are small. Statistics are current season "
        "aggregates, not snapshots for the sidebar date."
    )
    selection = (season, type_name)
    if st.button("Load NBA team & player browser", key="nba_load_stats"):
        st.session_state["nba_stats_loaded"] = selection
    if st.session_state.get("nba_stats_loaded") != selection:
        st.info("Choose a season and type, then load the NBA browser.")
        return
    try:
        with st.spinner("Loading NBA league team statistics..."):
            data = load_nba_team_stats(season, type_name)
        teams = [row for row in data["rows"] if (row.get("GP") or 0) > 0]
        if not teams:
            st.info("No completed team statistics for this season/type yet. Try the previous regular season.")
            return
        teams.sort(key=lambda team: team["TEAM_NAME"])
        selected_id = st.selectbox(
            "Choose any NBA team", [team["TEAM_ID"] for team in teams],
            format_func=lambda value: next(team["TEAM_NAME"] for team in teams if team["TEAM_ID"] == value),
            key="nba_selected_stats_team",
        )
        selected = next(team for team in teams if team["TEAM_ID"] == selected_id)
        st.caption(
            f"Source: NBA.com. Retrieved {data['retrieved']}. "
            f"Teams with played games: {len(teams)}/30. Cached up to one hour."
        )
        st.write(f"**{selected['TEAM_NAME']}: {selected['GP']} games — {season_name(season)} {type_label}**")
        st.subheader("NBA Team Strengths & Weaknesses")
        comparisons = team_comparison(selected, teams)
        st.dataframe(comparisons, hide_index=True, use_container_width=True)
        strengths = [row["Statistic"] for row in comparisons if row["Assessment"] == "Above league average"]
        weaknesses = [row["Statistic"] for row in comparisons if row["Assessment"] == "Below league average"]
        st.write("**Above-average areas:** " + (", ".join(strengths) or "None in available metrics."))
        st.write("**Below-average areas:** " + (", ".join(weaknesses) or "None in available metrics."))
        st.caption(
            "Rank 1 is best. Lower points/shooting allowed and turnovers are "
            "better. League averages are unweighted team averages. These "
            "comparisons do not adjust for pace, opponent strength, or lineups. "
            "Above average may reflect only a small difference."
        )
        if st.checkbox("Show NBA team mid-range shooting", key="nba_team_midrange"):
            try:
                zones = load_nba_shooting(season, type_name, "teams")
                zone = shooting_lookup(zones, "TEAM_ID").get(selected_id)
                if zone:
                    st.dataframe([{key: zone[key] for key in (
                        "TEAM_NAME", "Mid-range made", "Mid-range attempts", "Mid-range FG %",
                    )}], hide_index=True, use_container_width=True)
                else:
                    st.info("No mid-range team shooting data available.")
            except (requests.exceptions.RequestException, ValueError, KeyError, TypeError) as exc:
                st.info(f"Mid-range team data unavailable: {exc}")
        if st.checkbox("Compare all NBA teams", key="nba_all_teams"):
            rows = []
            for team in teams:
                row = {"Team": team["TEAM_NAME"], "Games": team["GP"]}
                for label, key, higher, is_percent in TEAM_METRICS:
                    value = metric_value(team, key, is_percent)
                    row[label] = round(value, 2) if value is not None else None
                rows.append(row)
            st.dataframe(rows, hide_index=True, use_container_width=True)
        st.subheader("NBA Player Statistics & Shooting")
        if st.checkbox("Load players for selected NBA team", key="nba_players_open"):
            with st.spinner("Loading player production and shooting zones..."):
                players = load_nba_player_stats(season, type_name)
                try:
                    player_zones = load_nba_shooting(season, type_name, "players")
                except (requests.exceptions.RequestException, ValueError, KeyError, TypeError) as exc:
                    player_zones = []
                    st.info(f"Mid-range data unavailable; other player stats remain available: {exc}")
            display = player_display_rows(players, selected_id, player_zones)
            if display:
                st.dataframe(display, hide_index=True, use_container_width=True)
            else:
                st.info("No player stats available for this team and season type.")
            st.caption(
                "Production and 3-point makes/attempts are per game. Mid-range "
                "makes/attempts are season totals from NBA.com's Mid-Range zone. "
                "Mid-range FG % is makes divided by attempts; it does not "
                "include all two-point shots. A blank percentage means no "
                "attempts or missing data. Players with no played games may "
                "be absent. Multi-team season totals are identified by the "
                "source's current team and may include previous-team games. "
                "This is not a confirmed starting lineup."
            )
        st.markdown("[Official NBA statistics](https://www.nba.com/stats/) · [NBA shooting zones](https://www.nba.com/stats/players/shooting)")
    except (requests.exceptions.RequestException, ValueError, KeyError, TypeError, AttributeError) as exc:
        st.warning(f"NBA statistics could not be loaded: {exc}")


def show_nba_injuries():
    st.header("NBA Injury & Availability Updates")
    with st.expander("View NBA injury reports"):
        if st.button("Load / refresh NBA injuries", key="nba_load_injuries"):
            load_nba_injuries.clear()
            st.session_state["nba_injuries_open"] = True
        if not st.session_state.get("nba_injuries_open"):
            st.info("Load the latest NBA injury reports.")
            return
        try:
            report = load_nba_injuries()
            team = st.selectbox("NBA injury team", ["All teams"] + report["teams"], key="nba_injury_team")
            include_active = st.checkbox("Include Active NBA updates", key="nba_injury_active")
            rows = [
                row for row in report["rows"]
                if (team == "All teams" or row["Team"] == team)
                and (include_active or row["Status"].lower() != "active")
            ]
            statuses = sorted(
                {"Probable", "Questionable", "Doubtful", "Out", "Injured Reserve", "Day-To-Day"}
                | {row["Status"] for row in rows}
            )
            status = st.multiselect(
                "NBA injury status", statuses, key="nba_injury_status",
                help="Leave empty for all reported statuses. Statuses are not inferred or converted.",
            )
            if status:
                rows = [row for row in rows if row["Status"] in status]
            position = st.selectbox(
                "NBA injury position", ["All positions"] + sorted({row["Position"] for row in rows}),
                key="nba_injury_position",
            )
            if position != "All positions":
                rows = [row for row in rows if row["Position"] == position]
            st.caption(
                f"Source: ESPN. Retrieved {report['retrieved']}. "
                f"Source timestamp: {report['source_timestamp']}. Cached five minutes."
            )
            if rows:
                st.dataframe(rows, hide_index=True, use_container_width=True)
            else:
                st.info("No matching updates. This does not confirm that all players are healthy.")
            st.caption(
                "Latest reports, not historical snapshots for the sidebar "
                "date. Active reports are hidden by default. NBA.com/ESPN "
                "availability categories may differ from NFL categories; "
                "only explicitly reported statuses appear in results. "
                "This is not a confirmed game-day active lineup."
            )
        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError, AttributeError) as exc:
            st.warning(f"NBA injury updates unavailable: {exc}")


def show_nba_game_details(scoreboard, game_date, shared):
    st.header("NBA Game Time, Arena & ESPN Weather")
    events = [event for event in scoreboard.get("events", []) if event.get("id")]
    if not events:
        st.info("No NBA games listed for the sidebar date.")
        return
    labels = {event["id"]: event.get("name", "NBA game") for event in events}
    selected = st.selectbox(
        "NBA game details", list(labels), format_func=lambda key: labels[key],
        key="nba_detail_game",
    )
    event = next(event for event in events if event["id"] == selected)
    competition = event.get("competitions", [{}])[0]
    venue = competition.get("venue") or {}
    try:
        st.write("**Game time (Pacific):** " + shared["format_game_time"](event.get("date")))
        st.write("**Arena:** " + venue.get("fullName", "Not provided"))
        indoor = venue.get("indoor")
        st.write("**ESPN indoor flag:** " + ("Yes" if indoor is True else "No" if indoor is False else "Not provided"))
        st.caption(
            "Outdoor weather generally does not describe conditions inside "
            "an arena. Roof open/closed status is not supplied by this feed."
        )
        if st.button("Load / refresh NBA ESPN game report", key="nba_game_report"):
            load_nba_game_details.clear()
            st.session_state["nba_loaded_report"] = (str(game_date), selected)
        if st.session_state.get("nba_loaded_report") == (str(game_date), selected):
            info = load_nba_game_details(selected)
            weather = info.get("weather") or {}
            event_weather = event.get("weather") or competition.get("weather") or {}
            rows = shared["get_espn_weather_rows"](event_weather, weather)
            if any(row["ESPN reported value"] != "Not provided" for row in rows):
                st.dataframe(rows, hide_index=True, use_container_width=True)
                st.caption("Values are reported by ESPN; this feed does not explicitly label the weather units.")
            else:
                st.info("ESPN does not provide a weather report for this NBA game.")
        st.markdown(f"[View game on ESPN](https://www.espn.com/nba/game/_/gameId/{selected})")
    except (requests.exceptions.RequestException, ValueError, KeyError, TypeError, AttributeError) as exc:
        st.warning(f"NBA game details unavailable: {exc}")


def render_nba_tools(game_date, scoreboard, shared):
    end_year = current_season_end()
    st.divider()
    show_nba_game_details(scoreboard, game_date, shared)
    st.divider()
    show_nba_model(shared, end_year)
    st.divider()
    show_nba_statistics(end_year)
    st.divider()
    show_nba_injuries()
