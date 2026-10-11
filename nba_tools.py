"""NBA statistics and research tools for EdgeLab Sports AI."""
import math
import json
from pathlib import Path
from collections import defaultdict, deque
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



@st.cache_data(ttl=3600)
def nba_saved_snapshot():
    path = Path(__file__).with_name("nba_stats_snapshot.json")
    if not path.exists():
        raise ValueError("Saved NBA.com data has not been installed yet.")
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    if snapshot.get("schema_version") != 1 or snapshot.get("source") != "NBA.com":
        raise ValueError("Unrecognized saved NBA statistics format.")
    datetime.fromisoformat(snapshot["retrieved_at"])
    return snapshot


def nba_stats_response(endpoint, params, saved=False):
    if not saved:
        return nba_request(endpoint, params)
    snapshot = nba_saved_snapshot()
    matches = [entry for entry in snapshot["entries"]
               if entry["endpoint"] == endpoint
               and entry["season"] == params["Season"]
               and entry["season_type"] == params["SeasonType"]
               and entry["measure"] == params["MeasureType"]
               and entry["per_mode"] == params["PerMode"]
               and entry.get("distance_range") == params.get("DistanceRange")]
    if len(matches) != 1:
        raise ValueError("No saved NBA.com data for this season/type. Try 2025–26 regular season or 2026–27 preseason, or use ESPN.")
    data = matches[0]["data"]
    for key in ("Season", "SeasonType"):
        returned = data.get("parameters", {})
        if key in returned and returned[key] != params[key]:
            raise ValueError("Saved NBA.com statistics season/type mismatch.")
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
def load_nba_team_stats(end_year, season_type, saved=False):
    params = stats_params(end_year, season_type)

    def fetch(measure):
        query = dict(params, MeasureType=measure)
        return flat_rows(nba_stats_response("leaguedashteamstats", query, saved))

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
        "retrieved": nba_saved_snapshot()["retrieved_at"] if saved else datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }


@st.cache_data(ttl=3600)
def load_nba_player_stats(end_year, season_type, saved=False):
    return flat_rows(nba_stats_response(
        "leaguedashplayerstats", stats_params(end_year, season_type), saved,
    ))


@st.cache_data(ttl=3600)
def load_nba_shooting(end_year, season_type, scope, saved=False):
    params = dict(
        stats_params(end_year, season_type),
        DistanceRange="By Zone", PerMode="Totals",
    )
    endpoint = (
        "leaguedashteamshotlocations" if scope == "teams"
        else "leaguedashplayershotlocations"
    )
    return parse_shooting_zones(nba_stats_response(endpoint, params, saved))



# ESPN uses the season ending year. Keep season/type refs explicit so a
# historical request can never silently return the current season.
ESPN_CORE = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba"
ESPN_TYPES = {"Pre Season": 1, "Regular Season": 2, "Playoffs": 3}


def espn_json(url, params=None):
    response = requests.get(url, params=params, headers=HEADERS, timeout=15)
    response.raise_for_status()
    return response.json()


def espn_stats_row(data, end_year, type_name):
    type_id = ESPN_TYPES[type_name]
    expected = f"/seasons/{end_year}/types/{type_id}/"
    if expected not in data.get("$ref", ""):
        raise ValueError("ESPN returned statistics for a different season/type.")
    values = {
        stat["name"]: stat.get("value")
        for category in data.get("splits", {}).get("categories", [])
        for stat in category.get("stats", [])
    }
    games = values.get("gamesPlayed")
    if not isinstance(games, (int, float)) or games <= 0:
        raise ValueError("No played games in this ESPN statistics response.")
    row = {"GP": games}
    for key, total in {
        "PTS": "points", "MIN": "minutes", "REB": "rebounds",
        "AST": "assists", "STL": "steals", "BLK": "blocks",
        "TOV": "turnovers", "FGM": "fieldGoalsMade", "FGA": "fieldGoalsAttempted",
        "FG3M": "threePointFieldGoalsMade", "FG3A": "threePointFieldGoalsAttempted",
        "FTM": "freeThrowsMade", "FTA": "freeThrowsAttempted",
    }.items():
        value = values.get(total)
        row[key] = value / games if isinstance(value, (int, float)) else None
    for key, made, attempts in (("FG_PCT", "FGM", "FGA"),
                                ("FG3_PCT", "FG3M", "FG3A"),
                                ("FT_PCT", "FTM", "FTA")):
        row[key] = (row[made] / row[attempts]
                    if row.get(attempts) and row.get(made) is not None else None)
    return row


@st.cache_data(ttl=3600)
def load_espn_nba_teams(end_year, type_name):
    directory = espn_json(f"{ESPN}/teams", {"limit": 100})
    teams = [entry["team"] for sport in directory.get("sports", [])
             for league in sport.get("leagues", []) for entry in league.get("teams", [])
             if not entry["team"].get("isAllStar")]
    def fetch(team):
        try:
            url = f"{ESPN_CORE}/seasons/{end_year}/types/{ESPN_TYPES[type_name]}/teams/{team['id']}/statistics"
            row = espn_stats_row(espn_json(url), end_year, type_name)
            row.update(TEAM_ID=int(team["id"]), TEAM_NAME=team["displayName"])
            return row, None
        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError) as exc:
            return None, f"{team['displayName']}: {exc}"
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(fetch, teams))
    return {"rows": [row for row, error in results if row],
            "errors": [error for row, error in results if error],
            "source": "ESPN", "retrieved": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}


@st.cache_data(ttl=3600)
def load_espn_nba_players(end_year, type_name, team_id):
    url = f"{ESPN_CORE}/seasons/{end_year}/teams/{team_id}/athletes"
    directory = espn_json(url, {"limit": 100})
    if directory.get("pageCount", 1) > 1:
        raise ValueError("ESPN roster is incomplete; more than one page returned.")
    def fetch(item):
        try:
            ref = item["$ref"].replace("http://", "https://", 1)
            if f"/seasons/{end_year}/athletes/" not in ref:
                raise ValueError("ESPN roster season mismatch.")
            athlete = espn_json(ref)
            athlete_id = str(athlete["id"])
            stats = espn_json(f"{ESPN_CORE}/seasons/{end_year}/types/{ESPN_TYPES[type_name]}/athletes/{athlete_id}/statistics")
            row = espn_stats_row(stats, end_year, type_name)
            row.update(PLAYER_ID=int(athlete_id), PLAYER_NAME=athlete["displayName"], TEAM_ID=team_id)
            return row, None
        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError) as exc:
            return None, str(exc)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(fetch, directory.get("items", [])))
    return {"rows": [row for row, error in results if row],
            "unavailable": sum(bool(error) for row, error in results),
            "roster_count": len(results)}


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



@st.cache_data(ttl=3600)
def load_nba_saved_history(end_year):
    snapshot = json.loads(Path(__file__).with_name("nba_history_snapshot.json").read_text(encoding="utf-8"))
    if (snapshot.get("schema_version") != 1
            or snapshot.get("source") != "NBA.com leaguegamelog"
            or snapshot.get("season_type") != "Regular Season"):
        raise ValueError("Invalid saved NBA history metadata.")
    datetime.fromisoformat(snapshot["retrieved_at"])
    years = set(range(end_year - 4, end_year + 1))
    if not years.issubset(set(snapshot["seasons_requested"])):
        raise ValueError("Saved NBA history does not cover the requested seasons.")
    games, seen = [], set()
    for row in snapshot["games"]:
        game = dict(row)
        game["date"] = date.fromisoformat(game["date"])
        if game["season"] not in years:
            continue
        if game["date"] > datetime.now(timezone.utc).date():
            continue
        if not game["home_team"] or not game["away_team"] or game["home_team"] == game["away_team"]:
            raise ValueError("Invalid saved NBA teams.")
        if not all(isinstance(game[key], (int, float)) and math.isfinite(game[key]) and game[key] >= 0 for key in ("home_score", "away_score")):
            raise ValueError("Invalid saved NBA score.")
        if game["home_score"] == game["away_score"]:
            raise ValueError("Completed NBA games cannot be tied.")
        identity = (game["date"], game["home_team"], game["away_team"])
        if identity in seen:
            raise ValueError("Duplicate saved NBA game.")
        seen.add(identity)
        games.append(game)
    if len(games) < 100:
        raise ValueError("Too few saved NBA games for a backtest.")
    return {"games": sorted(games, key=lambda game: (game["date"], game["home_team"])),
            "retrieved_at": snapshot["retrieved_at"],
            "extra_schedule_dates": snapshot.get("extra_schedule_dates", [])}

def clear_nba_caches():
    for function in (
        nba_saved_snapshot, load_espn_nba_teams, load_espn_nba_players,
        load_nba_team_stats, load_nba_player_stats, load_nba_shooting,
        load_nba_injuries, load_nba_game_details, load_nba_history, load_nba_saved_history,
    ):
        function.clear()



def nba_season_validation(predictions, current_end_year):
    """Evaluate each completed season after the first warm-up season.

    Elo and baseline predictions already use only earlier game dates. Freeze
    each season's shrinkage strength using the preceding season, then score
    the entire next season without retuning on its outcomes.
    """
    by_season = defaultdict(list)
    for prediction in sorted(predictions, key=lambda row: row["Date"]):
        by_season[prediction["Season"]].append(prediction)
    results = []
    for season in sorted(by_season):
        if season >= current_end_year or season - 1 not in by_season:
            continue
        calibration = by_season[season - 1]
        evaluation = by_season[season]
        if len(calibration) < 100 or len(evaluation) < 100:
            continue
        if calibration[-1]["Date"] >= evaluation[0]["Date"]:
            raise ValueError("Season calibration overlaps its evaluation dates.")
        def result(row):
            return 1.0 if row["Actual Result"] == "Home win" else 0.0 if row["Actual Result"] == "Away win" else 0.5
        def score(rows, strength):
            return sum((0.5 + strength * (row["Home Win Probability"] - 0.5) - result(row)) ** 2 for row in rows) / len(rows)
        strength = min((step / 100 for step in range(100, 4, -1)),
                       key=lambda candidate: score(calibration, candidate))
        non_ties = [row for row in evaluation if row["Actual Result"] != "Tie"]
        if not non_ties:
            continue
        original = score(evaluation, 1.0)
        adjusted = score(evaluation, strength)
        results.append({
            "season": season, "games": len(evaluation),
            "accuracy": sum(row["Correct"] for row in non_ties) / len(non_ties),
            "baseline_accuracy": sum(row["Baseline Correct"] for row in non_ties) / len(non_ties),
            "brier": original,
            "baseline_brier": sum(row["Baseline Brier Score"] for row in evaluation) / len(evaluation),
            "adjusted_brier": adjusted, "adjustment_gain": original - adjusted,
            "strength": strength, "calibration_games": len(calibration),
            "calibration_first": calibration[0]["Date"], "calibration_last": calibration[-1]["Date"],
            "first_date": evaluation[0]["Date"], "last_date": evaluation[-1]["Date"],
        })
    return results


def show_nba_season_validation(predictions, end_year):
    st.subheader("NBA Validation Across Completed Seasons")
    st.caption(
        "The first available season is warm-up history. Each later completed "
        "season is evaluated in full. Predictions update only after earlier "
        "game dates; each season's adjustment strength is fixed using the "
        "preceding season. K=20 and home advantage=55 stay unchanged. "
        "This comparison uses a different test period from the final-20% backtest above."
    )
    results = nba_season_validation(predictions, end_year)
    if not results:
        st.info("At least two completed seasons are needed for this comparison.")
        return
    st.dataframe([{
        "Season": season_name(row["season"]), "Test games": row["games"],
        "Winner accuracy": f"{row['accuracy'] * 100:.1f}%",
        "Baseline accuracy": f"{row['baseline_accuracy'] * 100:.1f}%",
        "Original Brier": round(row["brier"], 4),
        "Baseline Brier": round(row["baseline_brier"], 4),
        "Adjusted Brier": round(row["adjusted_brier"], 4),
        "Adjustment improvement": f"{row['adjustment_gain']:+.6f}",
        "Adjustment strength": row["strength"],
        "Calibration season": season_name(row["season"] - 1),
    } for row in results], hide_index=True, use_container_width=True)
    beats_baseline = sum(row["brier"] < row["baseline_brier"] for row in results)
    helped = sum(row["adjustment_gain"] > 1e-12 for row in results)
    hurt = sum(row["adjustment_gain"] < -1e-12 for row in results)
    total = sum(row["games"] for row in results)
    gain = sum(row["adjustment_gain"] * row["games"] for row in results) / total
    st.write(f"**Original model beat baseline Brier in {beats_baseline}/{len(results)} seasons. Adjustment helped in {helped}, worsened in {hurt}.**")
    st.caption(
        f"Across {total:,} evaluation games, weighted adjustment improvement "
        f"was {gain:+.6f}. Positive means lower Brier; negative means worse. "
        "Adjustment keeps the same favorites and winner accuracy. Later "
        "seasons reuse earlier seasons as calibration, so these are chronological "
        "checks, not independent trials. Historical consistency does not "
        "establish future accuracy or betting profit."
    )
    with st.expander("View season calibration and evaluation dates"):
        st.dataframe([{
            "Season": season_name(row["season"]),
            "Calibration games": row["calibration_games"],
            "Calibration start": row["calibration_first"], "Calibration end": row["calibration_last"],
            "Evaluation start": row["first_date"], "Evaluation end": row["last_date"],
        } for row in results], hide_index=True, use_container_width=True)


def nba_recent_form_features(predictions):
    """Recent surprises versus Elo, reset each season and delayed by date."""
    history = defaultdict(lambda: deque(maxlen=10))
    days = defaultdict(list)
    for row in sorted(predictions, key=lambda row: row["Date"]):
        days[row["Date"]].append(row)
    output = []
    for day in sorted(days):
        updates = []
        for row in days[day]:
            item = dict(row)
            home = list(history[(row["Season"], row["Home Team"])])
            away = list(history[(row["Season"], row["Away Team"])])
            for window in (5, 10):
                # Use unchanged Elo until both teams have enough current-season games.
                item[f"Form {window}"] = (sum(home[-window:]) / window - sum(away[-window:]) / window
                                          if len(home) >= window and len(away) >= window else 0.0)
                item[f"Form available {window}"] = len(home) >= window and len(away) >= window
            output.append(item)
            actual = 1.0 if row["Actual Result"] == "Home win" else 0.0 if row["Actual Result"] == "Away win" else 0.5
            surprise = actual - row["Home Win Probability"]
            updates.extend(((row["Season"], row["Home Team"], surprise),
                            (row["Season"], row["Away Team"], -surprise)))
        for season, team, surprise in updates:
            history[(season, team)].append(surprise)
    return output


def nba_form_probability(probability, feature, weight):
    if weight == 0 or feature == 0:
        return probability
    probability = max(1e-9, min(1 - 1e-9, probability))
    log_odds = math.log(probability / (1 - probability)) + weight * feature
    return 1 / (1 + math.exp(-log_odds))


def nba_recent_form_validation(predictions, current_end_year):
    by_season = defaultdict(list)
    for row in nba_recent_form_features(predictions):
        by_season[row["Season"]].append(row)
    # Small fixed candidate set. Zero weight preserves Elo exactly.
    candidates = [(window, weight) for weight in (0.0, 0.25, 0.5, 1.0, 2.0) for window in (5, 10)]
    def actual(row):
        return 1.0 if row["Actual Result"] == "Home win" else 0.0 if row["Actual Result"] == "Away win" else 0.5
    def score(rows, window, weight):
        return sum((nba_form_probability(row["Home Win Probability"], row[f"Form {window}"], weight) - actual(row)) ** 2 for row in rows) / len(rows)
    results = []
    for season in sorted(by_season):
        if season >= current_end_year or season - 1 not in by_season:
            continue
        training, evaluation = by_season[season - 1], by_season[season]
        if len(training) < 100 or len(evaluation) < 100:
            continue
        if training[-1]["Date"] >= evaluation[0]["Date"]:
            raise ValueError("Recent-form training overlaps evaluation dates.")
        window, weight = min(candidates, key=lambda candidate: score(training, *candidate))
        non_ties = [row for row in evaluation if row["Actual Result"] != "Tie"]
        if not non_ties:
            continue
        original = score(evaluation, window, 0.0)
        form_brier = score(evaluation, window, weight)
        correct = sum((nba_form_probability(row["Home Win Probability"], row[f"Form {window}"], weight) >= 0.5) == (actual(row) == 1.0) for row in non_ties)
        results.append({
            "season": season, "games": len(evaluation), "window": window, "weight": weight,
            "original_accuracy": sum(row["Correct"] for row in non_ties) / len(non_ties),
            "form_accuracy": correct / len(non_ties), "original_brier": original,
            "form_brier": form_brier, "gain": original - form_brier,
            "games_with_form": sum(row[f"Form available {window}"] for row in evaluation),
            "training_first": training[0]["Date"], "training_last": training[-1]["Date"],
            "evaluation_first": evaluation[0]["Date"], "evaluation_last": evaluation[-1]["Date"],
        })
    return results


def show_nba_recent_form_validation(predictions, end_year):
    st.subheader("NBA Recent Form Experiment")
    st.caption(
        "Tests the last 5 or 10 games: did each team win more often than Elo "
        "expected? Each season's window and weight are chosen using only the "
        "preceding season, including the option to keep Elo unchanged. Recent "
        "form resets each season, uses only earlier dates, and starts after "
        "both teams have enough games. This is compared with original Elo, "
        "without the separate confidence adjustment."
    )
    results = nba_recent_form_validation(predictions, end_year)
    if not results:
        st.info("At least two completed seasons are needed for the recent-form experiment.")
        return
    st.dataframe([{
        "Season": season_name(row["season"]), "Test games": row["games"],
        "Original accuracy": f"{row['original_accuracy'] * 100:.1f}%",
        "With form accuracy": f"{row['form_accuracy'] * 100:.1f}%",
        "Original Brier": round(row["original_brier"], 4),
        "With form Brier": round(row["form_brier"], 4),
        "Brier improvement": f"{row['gain']:+.6f}",
        "Recent games": row["window"] if row["weight"] else "Unchanged Elo",
        "Form weight": row["weight"],
        "Games with enough history": row["games_with_form"],
        "Training season": season_name(row["season"] - 1),
    } for row in results], hide_index=True, use_container_width=True)
    helped = sum(row["gain"] > 1e-12 for row in results)
    hurt = sum(row["gain"] < -1e-12 for row in results)
    games = sum(row["games"] for row in results)
    gain = sum(row["gain"] * row["games"] for row in results) / games
    st.write(f"**Recent-form test: improved Brier in {helped}/{len(results)} seasons; worsened in {hurt}. Weighted improvement: {gain:+.6f}.**")
    st.info("Recent form remains an experiment. The matchup calculator continues to use the existing Elo probabilities and confidence adjustment.")
    st.caption(
        "Positive Brier improvement is better. A zero form weight means "
        "the preceding-season test selected unchanged Elo. Within a test "
        "season, earlier results update team form before later predictions, "
        "while the chosen window/weight stay fixed. This does not account "
        "for injuries, player statistics, rest, trades, or shooting margins. "
        "These historical checks are not an untouched future test."
    )


def nba_rest_features(predictions, extra_schedule_dates=()):
    last_played, days, extra_days = {}, defaultdict(list), defaultdict(list)
    for row in sorted(predictions, key=lambda row: row["Date"]):
        days[row["Date"]].append(row)
    for item in extra_schedule_dates:
        day = date.fromisoformat(item["date"]).isoformat()
        teams = item["teams"]
        if len(teams) != 2 or teams[0] == teams[1]:
            raise ValueError("Invalid extra NBA schedule teams.")
        for team in teams:
            extra_days[day].append((item["season"], team))
    output = []
    for day in sorted(set(days) | set(extra_days)):
        current_date = date.fromisoformat(day)
        updates = list(extra_days[day])
        for row in days[day]:
            item = dict(row)
            gaps = []
            for team in (row["Home Team"], row["Away Team"]):
                previous = last_played.get((row["Season"], team))
                gap = (current_date - previous).days if previous else None
                if gap is not None and gap <= 0:
                    raise ValueError("Invalid NBA rest-date order.")
                gaps.append(gap)
                updates.append((row["Season"], team))
            home, away = gaps
            available = home is not None and away is not None
            item.update({
                "Rest available": available,
                "Home rest days": home - 1 if home is not None else None,
                "Away rest days": away - 1 if away is not None else None,
                "Rest advantage": min(home - 1, 3) - min(away - 1, 3) if available else 0,
                "Back-to-back advantage": int(away == 1) - int(home == 1) if available else 0,
            })
            output.append(item)
        # Every game dated today sees only earlier dates, including neutral games.
        for season, team in updates:
            last_played[(season, team)] = current_date
    return output


def nba_rest_probability(row, back_weight, rest_weight):
    feature = back_weight * row["Back-to-back advantage"] + rest_weight * row["Rest advantage"]
    return nba_form_probability(row["Home Win Probability"], feature, 1.0)


def nba_rest_validation(predictions, current_end_year, extra_schedule_dates=()):
    grouped = defaultdict(list)
    for row in nba_rest_features(predictions, extra_schedule_dates):
        grouped[row["Season"]].append(row)
    # Fixed modest coefficients in log odds. Zero/zero retains original Elo.
    candidates = [(back, rest) for back in (0.0, 0.1, 0.2, 0.3, 0.4)
                  for rest in (0.0, 0.05, 0.1)]
    def actual(row):
        return 1.0 if row["Actual Result"] == "Home win" else 0.0 if row["Actual Result"] == "Away win" else 0.5
    def score(rows, back, rest):
        return sum((nba_rest_probability(row, back, rest) - actual(row)) ** 2 for row in rows) / len(rows)
    results = []
    for season in sorted(grouped):
        if season >= current_end_year or season - 1 not in grouped:
            continue
        training, evaluation = grouped[season - 1], grouped[season]
        if len(training) < 100 or len(evaluation) < 100:
            continue
        if training[-1]["Date"] >= evaluation[0]["Date"]:
            raise ValueError("NBA rest training overlaps evaluation dates.")
        back, rest = min(candidates, key=lambda candidate: score(training, *candidate))
        non_ties = [row for row in evaluation if row["Actual Result"] != "Tie"]
        if not non_ties:
            continue
        original, adjusted = score(evaluation, 0.0, 0.0), score(evaluation, back, rest)
        accuracy = sum((nba_rest_probability(row, back, rest) >= 0.5) == (actual(row) == 1.0) for row in non_ties) / len(non_ties)
        results.append({
            "season": season, "games": len(evaluation), "back_weight": back, "rest_weight": rest,
            "original_accuracy": sum(row["Correct"] for row in non_ties) / len(non_ties),
            "rest_accuracy": accuracy, "original_brier": original, "rest_brier": adjusted,
            "gain": original - adjusted,
            "rest_games": sum(row["Rest available"] for row in evaluation),
            "back_advantage_games": sum(row["Back-to-back advantage"] != 0 for row in evaluation),
            "training_last": training[-1]["Date"], "evaluation_first": evaluation[0]["Date"],
        })
    return results


def show_nba_rest_validation(predictions, end_year, extra_schedule_dates=()):
    st.subheader("NBA Rest Days & Back-to-Back Experiment")
    st.caption(
        "A game the next calendar day is a back-to-back (zero full rest days). "
        "Tests a back-to-back advantage and a difference in full rest days, "
        "capped at three per team. Each season's weights are selected using "
        "only the preceding season. Zero weights keep original Elo. First "
        "games with unknown rest use unchanged Elo; history resets each season. "
        "This test does not combine rest with recent form or confidence adjustment."
    )
    results = nba_rest_validation(predictions, end_year, extra_schedule_dates)
    if not results:
        st.info("At least two completed seasons are needed for the rest-days test.")
        return
    st.dataframe([{
        "Season": season_name(row["season"]), "Test games": row["games"],
        "Original accuracy": f"{row['original_accuracy'] * 100:.1f}%",
        "With rest accuracy": f"{row['rest_accuracy'] * 100:.1f}%",
        "Original Brier": round(row["original_brier"], 4),
        "With rest Brier": round(row["rest_brier"], 4),
        "Brier improvement": f"{row['gain']:+.6f}",
        "Back-to-back weight": row["back_weight"], "Rest-days weight": row["rest_weight"],
        "Known rest games": row["rest_games"],
        "One team on back-to-back": row["back_advantage_games"],
        "Training season": season_name(row["season"] - 1),
    } for row in results], hide_index=True, use_container_width=True)
    helped = sum(row["gain"] > 1e-12 for row in results)
    hurt = sum(row["gain"] < -1e-12 for row in results)
    total = sum(row["games"] for row in results)
    gain = sum(row["gain"] * row["games"] for row in results) / total
    st.write(f"**Rest test improved Brier in {helped}/{len(results)} seasons; worsened in {hurt}. Weighted improvement: {gain:+.6f}.**")
    st.info("Rest remains an experiment. The matchup calculator does not yet use rest-day adjustments.")
    st.caption(
        "Rest is inferred from recorded regular-season dates, including "
        "saved neutral games excluded from Elo. Games outside this feed, "
        "such as NBA Cup finals, may be missing, so this is a schedule-based "
        "proxy. It does not measure travel, time zones, tip-off intervals, "
        "or individual player rest. Positive Brier improvement is better. "
        "Saved history ends at the displayed last-game date and cannot "
        "establish current rest for a future matchup."
    )

def show_nba_model(shared, end_year):
    st.header("🏀 NBA Historical Prediction Model")
    st.caption(
        "Basic regular-season Elo research model. Preseason games and neutral-venue games without an identifiable home side are excluded. "
        "It does not account for current injuries, player stats, rest, travel, "
        "or sportsbook prices. K=20 and home advantage=55 are starting "
        "settings, not tuned NBA parameters."
    )
    history_source = st.selectbox(
        "NBA model history source", ["Saved NBA.com history", "Live NBA.com connection"],
        key="nba_history_source",
    )
    if history_source == "Saved NBA.com history":
        st.caption("Uses installed NBA.com game results without a live download. The retrieval time and last game date appear after loading. Saved history does not update automatically.")
    if st.button("Load NBA model & backtest", key="nba_load_model"):
        st.session_state["nba_model_loaded"] = True
    if not st.session_state.get("nba_model_loaded"):
        st.info("Click Load NBA model & backtest to retrieve historical NBA results.")
        return
    try:
        with st.spinner("Loading completed NBA games and building ratings..."):
            if history_source == "Saved NBA.com history":
                saved_history = load_nba_saved_history(end_year)
                games = saved_history["games"]
                st.caption(f"Source: saved NBA.com results. Retrieved {saved_history['retrieved_at']}. Last included game: {games[-1]['date'].isoformat()}.")
            else:
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
        show_nba_season_validation(predictions, end_year)
        show_nba_recent_form_validation(predictions, end_year)
        extra_dates = saved_history.get("extra_schedule_dates", []) if history_source == "Saved NBA.com history" else []
        show_nba_rest_validation(predictions, end_year, extra_dates)
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
    except (requests.exceptions.RequestException, ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
        st.warning(f"NBA historical model could not be loaded: {exc}")
        if history_source == "Live NBA.com connection":
            st.info("Choose Saved NBA.com history to run the backtest without the live connection.")


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
    source = st.selectbox(
        "NBA statistics source", ["ESPN", "NBA.com (saved data)", "NBA.com (live connection)"],
        key="nba_stats_source",
    )
    use_espn = source == "ESPN"
    use_saved = source == "NBA.com (saved data)"
    st.caption("ESPN supplies basic stats. NBA.com saved data includes mid-range and opponent shooting stats without a live connection; it reflects the displayed update time.")
    if use_saved:
        try:
            snapshot = nba_saved_snapshot()
            st.info(f"Saved NBA.com data retrieved {snapshot['retrieved_at']}. This snapshot does not update automatically. Refresh live data clears app caches but does not download a new snapshot.")
        except (ValueError, KeyError, OSError) as exc:
            st.warning(str(exc))
            return
    selection = (season, type_name, source)
    if st.button("Load NBA team & player browser", key="nba_load_stats"):
        st.session_state["nba_stats_loaded"] = selection
    if st.session_state.get("nba_stats_loaded") != selection:
        st.info("Choose a season and type, then load the NBA browser.")
        return
    try:
        with st.spinner("Loading NBA league team statistics..."):
            data = load_espn_nba_teams(season, type_name) if use_espn else load_nba_team_stats(season, type_name, use_saved)
        teams = [row for row in data["rows"] if (row.get("GP") or 0) > 0]
        if not teams:
            st.info("The selected source has no available team statistics for this season/type. For ESPN, try the previous regular season; preseason aggregates may be unavailable.")
            return
        teams.sort(key=lambda team: team["TEAM_NAME"])
        selected_id = st.selectbox(
            "Choose any NBA team", [team["TEAM_ID"] for team in teams],
            format_func=lambda value: next(team["TEAM_NAME"] for team in teams if team["TEAM_ID"] == value),
            key="nba_selected_stats_team",
        )
        selected = next(team for team in teams if team["TEAM_ID"] == selected_id)
        st.caption(
            f"Source: {source}. Retrieved {data['retrieved']}. "
            f"Teams with played games: {len(teams)}/30. Cached up to one hour."
        )
        if use_espn:
            st.info("ESPN does not supply opponent points/shooting or true mid-range zones in this feed. Those values remain unavailable. Comparisons use only teams with available data.")
            if data.get("errors"):
                with st.expander("Teams with unavailable statistics"):
                    st.write(data["errors"])
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
        if not use_espn and st.checkbox("Show NBA team mid-range shooting", key="nba_team_midrange"):
            try:
                zones = load_nba_shooting(season, type_name, "teams", use_saved)
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
                if use_espn:
                    player_data = load_espn_nba_players(season, type_name, selected_id)
                    players, player_zones = player_data["rows"], []
                    st.caption(f"ESPN statistics available for {len(players)}/{player_data['roster_count']} roster players. Players without statistics are omitted; roster association does not guarantee team-only season totals.")
                else:
                    players = load_nba_player_stats(season, type_name, use_saved)
                    player_zones = []
                    if st.checkbox("Load NBA player mid-range shooting", key="nba_player_midrange"):
                        try:
                            player_zones = load_nba_shooting(season, type_name, "players", use_saved)
                        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError):
                            st.info("Mid-range data unavailable; other player stats remain available.")
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
                "source's roster association and may include previous-team games. "
                "This is not a confirmed starting lineup."
            )
        st.markdown("[Official NBA statistics](https://www.nba.com/stats/) · [NBA shooting zones](https://www.nba.com/stats/players/shooting)")
    except (requests.exceptions.RequestException, ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
        st.warning(f"NBA statistics could not be loaded: {exc}")
        if source == "NBA.com (live connection)":
            st.info("Try NBA.com (saved data) to load the installed snapshot without contacting NBA.com, or ESPN for basic stats.")


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
