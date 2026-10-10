
import streamlit as st
import requests
import csv
import io
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

st.set_page_config(
    page_title="EdgeLab Sports AI",
    page_icon="🏈",
    layout="wide",
)

st.title("🏈 EdgeLab Sports AI")
st.write("Scores, standings, betting value, and NFL predictions")

SPORTS = {
    "NFL": "football/nfl",
    "NBA": "basketball/nba",
}

BASE_URL = "https://site.api.espn.com/apis"
HEADERS = {"User-Agent": "EdgeLabSportsAI/1.0"}

NFL_HISTORY_URL = (
    "https://raw.githubusercontent.com/nflverse/"
    "nfldata/master/data/games.csv"
)


# -------------------------
# ESPN SCORES AND STANDINGS
# -------------------------

@st.cache_data(ttl=300)
def get_scoreboard(sport_path, game_date):
    url = f"{BASE_URL}/site/v2/sports/{sport_path}/scoreboard"
    response = requests.get(
        url,
        params={"dates": game_date.strftime("%Y%m%d")},
        timeout=15,
        headers=HEADERS,
    )
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=900)
def get_standings(sport_path):
    url = f"{BASE_URL}/v2/sports/{sport_path}/standings"
    response = requests.get(
        url,
        timeout=15,
        headers=HEADERS,
    )
    response.raise_for_status()
    return response.json()


def show_games(data):
    events = data.get("events", [])

    if not events:
        st.info("No games were listed for this date. Try another date.")
        return

    for event in events:
        competition = event.get("competitions", [{}])[0]
        competitors = competition.get("competitors", [])

        home = next(
            (team for team in competitors
             if team.get("homeAway") == "home"),
            {},
        )
        away = next(
            (team for team in competitors
             if team.get("homeAway") == "away"),
            {},
        )

        home_team = home.get("team", {}).get("displayName", "Home")
        away_team = away.get("team", {}).get("displayName", "Away")
        home_score = home.get("score", "—")
        away_score = away.get("score", "—")

        status = (
            event.get("status", {})
            .get("type", {})
            .get("description", "Status unavailable")
        )

        start_time = event.get("date", "")
        if start_time:
            try:
                start_time = format_game_time(start_time)
            except (ValueError, TypeError, ZoneInfoNotFoundError):
                start_time = event.get("date", "") + " (source time)"

        with st.container(border=True):
            st.subheader(f"{away_team} at {home_team}")
            col1, col2, col3 = st.columns(3)
            col1.metric(away_team, away_score)
            col2.metric(home_team, home_score)
            col3.write("**Status**")
            col3.write(status)

            if start_time:
                st.caption(f"Scheduled time: {start_time}")


def stat_value(stats, possible_names):
    for stat in stats:
        if stat.get("name") in possible_names:
            return stat.get("displayValue", stat.get("value", "—"))
    return "—"


def parse_standings(data):
    rows = []
    seen_teams = set()

    def walk(node, group_name="League"):
        if not isinstance(node, dict):
            return

        current_group = node.get("name", group_name)
        entries = node.get("standings", {}).get("entries", [])

        for entry in entries:
            team_name = entry.get("team", {}).get(
                "displayName", "Unknown team"
            )

            if team_name in seen_teams:
                continue

            seen_teams.add(team_name)
            stats = entry.get("stats", [])

            rows.append({
                "Team": team_name,
                "Conference / Division": current_group,
                "Wins": stat_value(stats, ["wins"]),
                "Losses": stat_value(stats, ["losses"]),
                "Win %": stat_value(
                    stats,
                    ["winPercent", "winPct", "winningPercentage"],
                ),
                "Points For": stat_value(
                    stats, ["pointsFor", "pointsScored"]
                ),
                "Points Against": stat_value(
                    stats, ["pointsAgainst", "pointsAllowed"]
                ),
            })

        for child in node.get("children", []):
            walk(child, current_group)

    walk(data)
    return rows


# -------------------------
# BETTING ODDS CALCULATOR
# -------------------------

def american_to_decimal(odds):
    if odds > 0:
        return 1 + odds / 100
    return 1 + 100 / abs(odds)


def implied_probability(odds):
    if odds > 0:
        return 100 / (odds + 100)
    return abs(odds) / (abs(odds) + 100)


def format_money(amount):
    return f"${amount:,.2f}"


# -------------------------
# HISTORICAL NFL DATA
# -------------------------

@st.cache_data(ttl=3600)
def load_nfl_history():
    response = requests.get(
        NFL_HISTORY_URL,
        timeout=45,
        headers=HEADERS,
    )
    response.raise_for_status()

    reader = csv.DictReader(io.StringIO(response.text))
    games = []

    for row in reader:
        try:
            if row.get("game_type", "").upper() != "REG":
                continue

            home_score = float(row["home_score"])
            away_score = float(row["away_score"])
            season = int(row["season"])
            home_team = row["home_team"].strip()
            away_team = row["away_team"].strip()
            game_day = row["gameday"]

            if not home_team or not away_team:
                continue

            if not math.isfinite(home_score) or not math.isfinite(away_score):
                continue

            if home_score < 0 or away_score < 0:
                continue

            if not game_day:
                continue

            parsed_date = datetime.strptime(game_day, "%Y-%m-%d").date()

            # Ignore games dated in the future.
            if parsed_date > date.today():
                continue

            games.append({
                "date": parsed_date,
                "season": season,
                "home_team": home_team,
                "away_team": away_team,
                "home_score": home_score,
                "away_score": away_score,
            })

        except (ValueError, TypeError, KeyError):
            continue

    games.sort(key=lambda game: game["date"])

    if len(games) < 100:
        raise ValueError(
            "Too few completed historical NFL games were found."
        )

    return games


# -------------------------

# ELO MODEL AND BACKTEST
# -------------------------

def expected_home_win(home_rating, away_rating, home_advantage=55):
    rating_difference = home_rating + home_advantage - away_rating
    return 1 / (1 + 10 ** (-rating_difference / 400))


def build_elo_model(games, k_factor=20, home_advantage=55):
    ratings = {}
    predictions = []

    # Sort games chronologically, then process each date as a group.
    sorted_games = sorted(games, key=lambda game: game["date"])
    games_by_date = {}

    for game in sorted_games:
        game_date = game["date"]
        games_by_date.setdefault(game_date, []).append(game)

    # Historical home-result average for the baseline.
    # A home win = 1, away win = 0, tie = 0.5.
    prior_result_total = 0.0
    prior_game_count = 0

    for game_date in sorted(games_by_date):
        daily_updates = {}
        daily_results = []
        daily_predictions = []

        # All games on this date use ratings from BEFORE this date.
        baseline_probability = (
            prior_result_total / prior_game_count
            if prior_game_count > 0
            else 0.5
        )

        for game in games_by_date[game_date]:
            home = game["home_team"]
            away = game["away_team"]

            home_rating = ratings.get(home, 1500.0)
            away_rating = ratings.get(away, 1500.0)

            probability = expected_home_win(
                home_rating,
                away_rating,
                home_advantage,
            )

            if game["home_score"] > game["away_score"]:
                actual = 1.0
            elif game["home_score"] < game["away_score"]:
                actual = 0.0
            else:
                actual = 0.5

            baseline_correct = (
                (baseline_probability >= 0.5 and actual == 1.0)
                or (baseline_probability < 0.5 and actual == 0.0)
                or actual == 0.5
            )

            daily_predictions.append({
                "Date": game_date.isoformat(),
                "Season": game["season"],
                "Home Team": home,
                "Away Team": away,
                "Home Win Probability": probability,
                "Predicted Home Win %": round(probability * 100, 1),
                "Baseline Home Probability": round(
                    baseline_probability * 100, 1
                ),
                "Actual Result": (
                    "Home win" if actual == 1.0
                    else "Away win" if actual == 0.0
                    else "Tie"
                ),
                "Correct": (
                    (probability >= 0.5 and actual == 1.0)
                    or (probability < 0.5 and actual == 0.0)
                    or actual == 0.5
                ),
                "Baseline Correct": baseline_correct,
                "Brier Score": (probability - actual) ** 2,
                "Baseline Brier Score": (
                    baseline_probability - actual
                ) ** 2,
            })

            # Calculate rating changes, but do not apply them yet.
            change = k_factor * (actual - probability)
            daily_updates[home] = (
                daily_updates.get(home, 0.0) + change
            )
            daily_updates[away] = (
                daily_updates.get(away, 0.0) - change
            )

            daily_results.append(actual)

        # Only after every game on this date has been predicted
        # do we apply Elo changes and update the baseline history.
        for team, change in daily_updates.items():
            ratings[team] = ratings.get(team, 1500.0) + change

        predictions.extend(daily_predictions)
        prior_result_total += sum(daily_results)
        prior_game_count += len(daily_results)

    return ratings, predictions


def get_backtest_summary(predictions):
    # Use the final 20% of predictions as the test period.
    split_index = int(len(predictions) * 0.80)
    test_games = predictions[split_index:]

    if not test_games:
        return None, []

    non_tie_games = [
        game for game in test_games
        if game["Actual Result"] != "Tie"
    ]

    if non_tie_games:
        accuracy = (
            sum(game["Correct"] for game in non_tie_games)
            / len(non_tie_games)
        )
        baseline_accuracy = (
            sum(game["Baseline Correct"] for game in non_tie_games)
            / len(non_tie_games)
        )
    else:
        accuracy = 0.0
        baseline_accuracy = 0.0

    brier = sum(
        game["Brier Score"] for game in test_games
    ) / len(test_games)

    baseline_brier = sum(
        game["Baseline Brier Score"] for game in test_games
    ) / len(test_games)

    return {
        "test_games": len(test_games),
        "accuracy": accuracy,
        "brier": brier,
        "baseline_accuracy": baseline_accuracy,
        "baseline_brier": baseline_brier,
        "first_date": test_games[0]["Date"],
        "last_date": test_games[-1]["Date"],
    }, test_games



def get_season_backtest_rows(test_games):
    games_by_season = {}
    for game in test_games:
        games_by_season.setdefault(game["Season"], []).append(game)

    rows = []
    for season, games in sorted(games_by_season.items()):
        non_ties = [
            game for game in games if game["Actual Result"] != "Tie"
        ]
        accuracy = (
            sum(game["Correct"] for game in non_ties) / len(non_ties)
            if non_ties else None
        )
        baseline_accuracy = (
            sum(game["Baseline Correct"] for game in non_ties) / len(non_ties)
            if non_ties else None
        )
        brier = sum(game["Brier Score"] for game in games) / len(games)
        baseline_brier = (
            sum(game["Baseline Brier Score"] for game in games) / len(games)
        )
        rows.append({
            "Season": season,
            "Test games": len(games),
            "Non-tied games": len(non_ties),
            "Winner accuracy": (
                f"{accuracy * 100:.1f}%" if accuracy is not None else "N/A"
            ),
            "Baseline accuracy": (
                f"{baseline_accuracy * 100:.1f}%"
                if baseline_accuracy is not None else "N/A"
            ),
            "Accuracy gain (pp)": (
                round((accuracy - baseline_accuracy) * 100, 1)
                if accuracy is not None else None
            ),
            "Brier score": round(brier, 4),
            "Baseline Brier": round(baseline_brier, 4),
            "Brier improvement": round(baseline_brier - brier, 4),
            "First test date": min(game["Date"] for game in games),
            "Last test date": max(game["Date"] for game in games),
        })
    return rows


def get_calibration_rows(test_games):
    buckets = {}
    for game in test_games:
        # Exclude ties so observed frequencies are actual home win rates.
        if game["Actual Result"] == "Tie":
            continue
        probability = game["Home Win Probability"]
        bucket = min(int(probability * 10), 9)
        buckets.setdefault(bucket, []).append(game)

    rows = []
    for bucket, games in sorted(buckets.items()):
        mean_probability = (
            sum(game["Home Win Probability"] for game in games) / len(games)
        )
        actual_rate = (
            sum(game["Actual Result"] == "Home win" for game in games)
            / len(games)
        )
        rows.append({
            "Predicted home win range": (
                f"{bucket * 10}–{(bucket + 1) * 10}%"
                + (" (includes 100%)" if bucket == 9 else "")
            ),
            "Games": len(games),
            "Average predicted home win %": round(mean_probability * 100, 1),
            "Actual home win %": round(actual_rate * 100, 1),
            "Actual minus predicted (pp)": round(
                (actual_rate - mean_probability) * 100, 1
            ),
            "Sample size": "Small sample" if len(games) < 50 else "50+ games",
        })
    return rows


def shrink_probability(probability, strength):
    return 0.5 + strength * (probability - 0.5)


def test_probability_adjustment(predictions):
    ordered = sorted(predictions, key=lambda game: game["Date"])
    if len(ordered) < 100:
        return None
    calibration_start = ordered[int(len(ordered) * 0.60)]["Date"]
    evaluation_start = ordered[int(len(ordered) * 0.80)]["Date"]
    calibration = [
        game for game in ordered
        if calibration_start <= game["Date"] < evaluation_start
    ]
    evaluation = [
        game for game in ordered if game["Date"] >= evaluation_start
    ]
    if not calibration or not evaluation:
        return None

    def actual_result(game):
        return (
            1.0 if game["Actual Result"] == "Home win"
            else 0.0 if game["Actual Result"] == "Away win"
            else 0.5
        )

    def score(games, strength):
        return sum(
            (shrink_probability(game["Home Win Probability"], strength)
             - actual_result(game)) ** 2
            for game in games
        ) / len(games)

    # Prefer the unchanged model if calibration scores are equal.
    strengths = [step / 100 for step in range(100, 4, -1)]
    strength = min(strengths, key=lambda value: score(calibration, value))
    original_brier = score(evaluation, 1.0)
    adjusted_brier = score(evaluation, strength)
    return {
        "strength": strength,
        "calibration_games": len(calibration),
        "calibration_first": calibration[0]["Date"],
        "calibration_last": calibration[-1]["Date"],
        "evaluation_games": len(evaluation),
        "evaluation_first": evaluation[0]["Date"],
        "evaluation_last": evaluation[-1]["Date"],
        "original_brier": original_brier,
        "adjusted_brier": adjusted_brier,
        "improvement": original_brier - adjusted_brier,
    }


TEAM_STAT_METRICS = [
    ("Offense: points per game", "stats", "scoring", "totalPointsPerGame", True),
    ("Offense: net passing yards per game", "stats", "passing", "netPassingYardsPerGame", True),
    ("Offense: rushing yards per game", "stats", "rushing", "rushingYardsPerGame", True),
    ("Offense: yards per rush", "stats", "rushing", "yardsPerRushAttempt", True),
    ("Offense: third-down conversion %", "stats", "miscellaneous", "thirdDownConvPct", True),
    ("Defense: points allowed per game", "opponent", "scoring", "totalPointsPerGame", False),
    ("Defense: net passing yards allowed per game", "opponent", "passing", "netPassingYardsPerGame", False),
    ("Defense: rushing yards allowed per game", "opponent", "rushing", "rushingYardsPerGame", False),
    ("Defense: sacks per game", "stats", "defensive", "sacks", True),
    ("Defense: takeaways per game", "stats", "miscellaneous", "totalTakeaways", True),
]


def parse_team_statistics(data, season):
    returned_season = data.get("season", {})
    if returned_season.get("year") != season or returned_season.get("type") != 2:
        raise ValueError("ESPN returned a different season or season type.")
    results = data.get("results", {})

    def values(section):
        node = results.get(section, {})
        categories = node if isinstance(node, list) else node.get("categories", [])
        parsed = {}
        for category in categories:
            for stat in category.get("stats", []):
                value = stat.get("value")
                if isinstance(value, (int, float)) and math.isfinite(value):
                    parsed[(category.get("name"), stat.get("name"))] = float(value)
        return parsed

    own, opponent = values("stats"), values("opponent")
    games = own.get(("general", "gamesPlayed"),
                    own.get(("passing", "teamGamesPlayed"), 0))
    if games <= 0:
        raise ValueError("No completed games with team statistics.")
    team = data.get("team", {})
    row = {
        "Team": team.get("displayName", team.get("abbreviation", "Unknown")),
        "Code": team.get("abbreviation", ""),
        "Games": int(games),
    }
    for label, section, category, name, higher_better in TEAM_STAT_METRICS:
        value = (own if section == "stats" else opponent).get((category, name))
        if value is not None and name in ("sacks", "totalTakeaways"):
            value /= games
        row[label] = value
    return row


@st.cache_data(ttl=3600)
def load_all_nfl_team_statistics(season):
    response = requests.get(
        f"{BASE_URL}/site/v2/sports/football/nfl/teams",
        params={"limit": 100}, headers=HEADERS, timeout=20,
    )
    response.raise_for_status()
    entries = response.json()["sports"][0]["leagues"][0]["teams"]

    def fetch(entry):
        team = entry["team"]
        try:
            response = requests.get(
                f"{BASE_URL}/site/v2/sports/football/nfl/teams/{team['id']}/statistics",
                params={"season": season, "seasontype": 2},
                headers=HEADERS, timeout=20,
            )
            response.raise_for_status()
            return parse_team_statistics(response.json(), season), None
        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError, AttributeError) as exc:
            return None, f"{team.get('displayName', 'Team')}: {exc}"

    with ThreadPoolExecutor(max_workers=8) as pool:
        fetched = list(pool.map(fetch, entries))
    rows = sorted([row for row, error in fetched if row], key=lambda row: row["Team"])
    errors = [error for row, error in fetched if error]
    return {
        "rows": rows,
        "errors": errors,
        "expected": len(entries),
        "fetched_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    }


def get_team_comparison_rows(selected, league_rows):
    comparisons = []
    for label, section, category, name, higher_better in TEAM_STAT_METRICS:
        value = selected.get(label)
        available = [row[label] for row in league_rows if row.get(label) is not None]
        if value is None or not available:
            comparisons.append({"Statistic": label, "Team value": None,
                                "League average": None, "Rank": None,
                                "Teams compared": len(available), "Assessment": "Unavailable"})
            continue
        rank = 1 + sum(
            other > value if higher_better else other < value
            for other in available
        )
        average = sum(available) / len(available)
        assessment = (
            "Above league average" if (value > average if higher_better else value < average)
            else "Below league average" if value != average else "At league average"
        )
        comparisons.append({
            "Statistic": label, "Team value": round(value, 2),
            "League average": round(average, 2), "Rank": rank,
            "Teams compared": len(available), "Assessment": assessment,
        })
    return comparisons


PLAYER_STAT_FIELDS = {
    "QB": [
        ("Pass attempts", "passing", "passingAttempts"),
        ("Completions", "passing", "completions"),
        ("Completion %", "passing", "completionPct"),
        ("Passing yards", "passing", "passingYards"),
        ("Yards per attempt", "passing", "yardsPerPassAttempt"),
        ("Pass TD", "passing", "passingTouchdowns"),
        ("Interceptions", "passing", "interceptions"),
        ("Sacks taken", "passing", "sacks"),
        ("Passer rating", "passing", "QBRating"),
        ("Rushing yards", "rushing", "rushingYards"),
        ("Rush TD", "rushing", "rushingTouchdowns"),
    ],
    "RB": [
        ("Carries", "rushing", "rushingAttempts"),
        ("Rushing yards", "rushing", "rushingYards"),
        ("Yards per carry", "rushing", "yardsPerRushAttempt"),
        ("Rush TD", "rushing", "rushingTouchdowns"),
        ("Targets", "receiving", "receivingTargets"),
        ("Receptions", "receiving", "receptions"),
        ("Receiving yards", "receiving", "receivingYards"),
        ("Receiving TD", "receiving", "receivingTouchdowns"),
    ],
    "WR": [
        ("Targets", "receiving", "receivingTargets"),
        ("Receptions", "receiving", "receptions"),
        ("Receiving yards", "receiving", "receivingYards"),
        ("Yards per catch", "receiving", "yardsPerReception"),
        ("Receiving TD", "receiving", "receivingTouchdowns"),
    ],
}


@st.cache_data(ttl=3600)
def load_nfl_player_team_directory():
    response = requests.get(
        f"{BASE_URL}/site/v2/sports/football/nfl/teams",
        params={"limit": 100}, headers=HEADERS, timeout=20,
    )
    response.raise_for_status()
    entries = response.json()["sports"][0]["leagues"][0]["teams"]
    return sorted(
        [{"id": entry["team"]["id"], "name": entry["team"]["displayName"]}
         for entry in entries],
        key=lambda team: team["name"],
    )


def parse_player_roster(data, season):
    if data.get("season", {}).get("year") != season:
        raise ValueError("Roster season does not match the requested season.")
    players, seen = [], set()
    for group in data.get("athletes", []):
        for athlete in group.get("items", []):
            position = athlete.get("position", {}).get("abbreviation")
            athlete_id = athlete.get("id")
            if position not in PLAYER_STAT_FIELDS or not athlete_id or athlete_id in seen:
                continue
            seen.add(athlete_id)
            players.append({
                "id": athlete_id,
                "name": athlete.get("displayName", "Unknown player"),
                "position": position,
            })
    return players


def parse_player_statistics(data, player, season):
    season_ref = data.get("season", {}).get("$ref", "")
    type_ref = data.get("seasonType", {}).get("$ref", "")
    athlete_ref = data.get("athlete", {}).get("$ref", "")
    if (
        f"/seasons/{season}" not in season_ref
        or f"/types/2" not in type_ref
        or f"/athletes/{player['id']}" not in athlete_ref
    ):
        raise ValueError("Player or season metadata does not match the request.")
    values = {}
    for category in data.get("splits", {}).get("categories", []):
        for stat in category.get("stats", []):
            value = stat.get("value")
            if isinstance(value, (int, float)) and math.isfinite(value):
                values[(category.get("name"), stat.get("name"))] = value
    if not values:
        raise ValueError("No player statistics returned.")
    row = {
        "Player": player["name"],
        "Position": player["position"],
        "Games": values.get(("general", "gamesPlayed")),
    }
    for label, category, name in PLAYER_STAT_FIELDS[player["position"]]:
        value = values.get((category, name))
        row[label] = round(value, 2) if value is not None else None
    return row


@st.cache_data(ttl=3600)
def load_nfl_team_player_statistics(team_id, season):
    response = requests.get(
        f"{BASE_URL}/site/v2/sports/football/nfl/teams/{team_id}/roster",
        params={"season": season}, headers=HEADERS, timeout=20,
    )
    response.raise_for_status()
    players = parse_player_roster(response.json(), season)

    def fetch(player):
        try:
            response = requests.get(
                "https://sports.core.api.espn.com/v2/sports/football/"
                f"leagues/nfl/seasons/{season}/types/2/"
                f"athletes/{player['id']}/statistics/0",
                headers=HEADERS, timeout=20,
            )
            response.raise_for_status()
            return parse_player_statistics(response.json(), player, season), None
        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError, AttributeError) as exc:
            return None, f"{player['name']}: {exc}"

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(fetch, players))
    return {
        "rows": [row for row, error in results if row],
        "errors": [error for row, error in results if error],
        "roster_count": len(players),
        "fetched_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    }


def parse_nfl_injuries(data):
    groups = data.get("injuries")
    if not isinstance(groups, list):
        raise ValueError("ESPN did not return a recognizable injury report.")
    rows = []
    team_names = []
    for group in groups:
        team_name = group.get("displayName", "Unknown team")
        team_names.append(team_name)
        for injury in group.get("injuries", []):
            athlete = injury.get("athlete", {})
            details = injury.get("details") or {}
            player_url = next(
                (link.get("href") for link in athlete.get("links", [])
                 if "playercard" in link.get("rel", [])
                 and str(link.get("href", "")).startswith("https://www.espn.com/")),
                None,
            )
            rows.append({
                "Team": team_name,
                "Player": athlete.get("displayName", "Unknown player"),
                "Position": athlete.get("position", {}).get("abbreviation", "Unknown"),
                "Status": injury.get("status") or "Unknown",
                "Injury": details.get("type") or "Not provided",
                "Report updated (UTC)": injury.get("date") or "Not provided",
                "Player page": player_url,
            })
    rows.sort(key=lambda row: (row["Team"], row["Player"]))
    return {
        "rows": rows,
        "teams": sorted(set(team_names)),
        "source_timestamp": data.get("timestamp") or "Not provided",
        "season": data.get("season", {}).get("displayName", "Not provided"),
    }


@st.cache_data(ttl=300)
def load_nfl_injury_updates():
    response = requests.get(
        f"{BASE_URL}/site/v2/sports/football/nfl/injuries",
        headers=HEADERS, timeout=20,
    )
    response.raise_for_status()
    report = parse_nfl_injuries(response.json())
    report["fetched_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    return report


def format_game_time(game_time):
    if not game_time:
        return "Not provided"
    kickoff = datetime.fromisoformat(game_time.replace("Z", "+00:00"))
    if kickoff.tzinfo is None:
        raise ValueError("Game time has no timezone.")
    return kickoff.astimezone(
        ZoneInfo("America/Los_Angeles")
    ).strftime("%a, %b %d, %Y at %I:%M %p %Z")


@st.cache_data(ttl=300)
def load_espn_game_weather(event_id):
    response = requests.get(
        f"{BASE_URL}/site/v2/sports/football/nfl/summary",
        params={"event": event_id}, headers=HEADERS, timeout=20,
    )
    response.raise_for_status()
    data = response.json()
    if str(data.get("header", {}).get("id", "")) != str(event_id):
        raise ValueError("ESPN returned a different game.")
    return {
        "weather": data.get("gameInfo", {}).get("weather") or {},
        "venue": data.get("gameInfo", {}).get("venue") or {},
        "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }


def get_espn_weather_rows(event_weather, summary_weather):
    weather = dict(event_weather or {})
    weather.update({
        key: value for key, value in (summary_weather or {}).items()
        if value is not None
    })
    fields = [
        ("Conditions", "displayValue"),
        ("Temperature", "temperature"),
        ("High temperature", "highTemperature"),
        ("Low temperature", "lowTemperature"),
        ("Wind speed", "windSpeed"),
        ("Wind gust", "gust"),
        ("Precipitation", "precipitation"),
    ]
    return [
        {"Weather field": label,
         "ESPN reported value": str(weather[key]) if weather.get(key) is not None else "Not provided"}
        for label, key in fields
    ]


def show_espn_nfl_weather(scoreboard_data, game_date):
    st.subheader("NFL Game Weather — ESPN")
    st.caption(
        "ESPN's game weather report and kickoff time. "
        "Weather information does not change model probabilities."
    )
    with st.expander("View ESPN weather and game time"):
        events = [
            event for event in scoreboard_data.get("events", [])
            if event.get("id")
        ]
        if not events:
            st.info("No NFL games are listed for the selected date.")
            return
        labels = {
            event["id"]: event.get("name", "NFL game") for event in events
        }
        event_id = st.selectbox(
            "Select a game for weather", list(labels),
            format_func=lambda value: labels[value], key="espn_weather_event",
        )
        event = next(game for game in events if game["id"] == event_id)
        competition = event.get("competitions", [{}])[0]
        venue = competition.get("venue") or {}
        try:
            st.write("**Game time (Pacific):** " + format_game_time(event.get("date")))
            st.write(f"**Venue:** {venue.get('fullName', 'Not provided')}")
            indoor = venue.get("indoor")
            st.write(
                "**ESPN indoor flag:** "
                + ("Yes" if indoor is True else "No" if indoor is False else "Not provided")
            )
            st.caption(
                "The indoor flag does not confirm roof type or whether a "
                "retractable roof will be open for this game."
            )
            if st.button("Load / refresh ESPN weather", key="load_espn_weather"):
                load_espn_game_weather.clear()
                st.session_state["espn_weather_loaded_event"] = (str(game_date), event_id)
            if st.session_state.get("espn_weather_loaded_event") != (str(game_date), event_id):
                st.info("Click Load / refresh ESPN weather to view the game report.")
                return
            with st.spinner("Loading ESPN game weather..."):
                report = load_espn_game_weather(event_id)
            event_weather = event.get("weather") or competition.get("weather") or {}
            rows = get_espn_weather_rows(event_weather, report["weather"])
            if any(row["ESPN reported value"] != "Not provided" for row in rows):
                st.dataframe(rows, hide_index=True, use_container_width=True)
            else:
                st.info("ESPN has not supplied weather for this game.")
            st.caption(
                f"Source: ESPN. Retrieved {report['retrieved_at']}. "
                "Cached for up to five minutes. This is retrieval time; ESPN "
                "does not supply a forecast issuance time in this feed. "
                "Values are shown as ESPN reports them. The feed does not "
                "explicitly label temperature, wind, or precipitation units; "
                "precipitation is not assumed to be a percentage or an amount. "
                "Missing values mean unavailable, not zero."
            )
            if indoor is True:
                st.info(
                    "This venue is marked indoor. The reported outdoor weather "
                    "should not be treated as conditions on the field."
                )
            st.markdown(
                f"[View this game on ESPN](https://www.espn.com/nfl/game/_/gameId/{event_id})"
            )
        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError, AttributeError, ZoneInfoNotFoundError) as exc:
            st.warning(f"ESPN weather could not be loaded: {exc}")


# -------------------------
# SIDEBAR
# -------------------------

sport = st.sidebar.selectbox("Choose a sport", list(SPORTS))

selected_date = st.sidebar.date_input(
    "Choose game date",
    value=date.today(),
    min_value=date.today() - timedelta(days=365),
    max_value=date.today() + timedelta(days=365),
)

if st.sidebar.button("Refresh live data"):
    get_scoreboard.clear()
    get_standings.clear()
    load_nfl_history.clear()
    load_all_nfl_team_statistics.clear()
    load_nfl_player_team_directory.clear()
    load_nfl_team_player_statistics.clear()
    load_nfl_injury_updates.clear()
    load_espn_game_weather.clear()


# -------------------------
# SCHEDULE AND SCORES
# -------------------------

st.subheader(f"{sport} Schedule & Scores")

try:
    with st.spinner(f"Loading {sport} games..."):
        scoreboard = get_scoreboard(SPORTS[sport], selected_date)
    show_games(scoreboard)
    if sport == "NFL":
        show_espn_nfl_weather(scoreboard, selected_date)

except requests.exceptions.Timeout:
    st.error("The scoreboard took too long to respond. Try again.")
except requests.exceptions.RequestException as exc:
    st.error(f"Could not retrieve game data: {exc}")
except (ValueError, TypeError, KeyError) as exc:
    st.error(f"Could not read scoreboard data: {exc}")


# -------------------------
# TEAM STANDINGS
# -------------------------

st.divider()
st.subheader(f"{sport} Team Statistics & Standings")
st.caption(
    "Latest standings returned by ESPN, not necessarily standings "
    "as of the selected game date."
)

try:
    with st.spinner(f"Loading {sport} standings..."):
        standings_data = get_standings(SPORTS[sport])
        teams = parse_standings(standings_data)

    if not teams:
        st.warning(
            "ESPN did not return recognizable standings. Try refreshing."
        )
    else:
        team_names = ["All teams"] + sorted(
            row["Team"] for row in teams
        )
        selected_team = st.selectbox(
            "Find a team's record",
            team_names,
        )

        filtered_teams = (
            teams if selected_team == "All teams"
            else [row for row in teams if row["Team"] == selected_team]
        )

        st.dataframe(
            filtered_teams,
            hide_index=True,
            use_container_width=True,
        )

        if selected_team != "All teams":
            record = filtered_teams[0]
            col1, col2, col3 = st.columns(3)
            col1.metric("Wins", record["Wins"])
            col2.metric("Losses", record["Losses"])
            col3.metric("Win %", record["Win %"])

except requests.exceptions.Timeout:
    st.error("Standings took too long to respond. Try again.")
except requests.exceptions.RequestException as exc:
    st.error(f"Could not retrieve standings: {exc}")
except (ValueError, TypeError, KeyError, AttributeError) as exc:
    st.error(f"Could not read standings: {exc}")


# -------------------------
# BETTING ODDS AND VALUE
# -------------------------

st.divider()
st.header("🎯 Betting Odds & Value Calculator")

st.write(
    "Enter sportsbook odds and your estimated chance of winning "
    "to evaluate a hypothetical bet."
)

st.info(
    "This calculator uses the probability you enter. It does not "
    "retrieve live sportsbook odds or independently predict outcomes."
)

with st.form("bet_calculator"):
    col1, col2 = st.columns(2)

    with col1:
        bet_sport = st.selectbox("Bet sport", ["NFL", "NBA"])
        team_name = st.text_input(
            "Team or bet selection",
            placeholder="Example: Kansas City Chiefs",
        )
        odds = st.number_input(
            "American odds",
            min_value=-100000,
            max_value=100000,
            value=-110,
            step=5,
        )

    with col2:
        estimated_probability = st.slider(
            "Your estimated chance of winning (%)",
            min_value=1,
            max_value=99,
            value=60,
        )
        stake = st.number_input(
            "Amount risked ($)",
            min_value=1.0,
            max_value=100000.0,
            value=100.0,
            step=10.0,
        )

    submitted = st.form_submit_button(
        "Calculate Betting Value",
        type="primary",
        use_container_width=True,
    )

if submitted:
    if odds == 0:
        st.error("American odds cannot be zero. Use -110 or +150.")
    else:
        market_probability = implied_probability(odds)
        decimal_odds = american_to_decimal(odds)
        estimated = estimated_probability / 100
        potential_profit = stake * (decimal_odds - 1)
        potential_payout = stake + potential_profit
        expected_profit = (
            estimated * potential_profit
            - (1 - estimated) * stake
        )
        difference = (estimated - market_probability) * 100

        st.subheader(
            f"Results: {team_name.strip() or 'Your selected bet'}"
        )

        col1, col2, col3 = st.columns(3)
        col1.metric(
            "Sportsbook implied probability",
            f"{market_probability * 100:.2f}%",
        )
        col2.metric(
            "Your estimated probability",
            f"{estimated_probability:.1f}%",
        )
        col3.metric(
            "Probability difference",
            f"{difference:+.2f} percentage points",
        )

        col1, col2, col3 = st.columns(3)
        col1.metric(
            "Potential profit if you win",
            format_money(potential_profit),
        )
        col2.metric(
            "Total payout if you win",
            format_money(potential_payout),
        )
        col3.metric(
            "Estimated expected profit",
            format_money(expected_profit),
        )

        st.write(
            f"**Break-even win rate:** "
            f"{market_probability * 100:.2f}%"
        )
        st.write(f"**Decimal odds:** {decimal_odds:.3f}")

        if difference > 0:
            st.success(
                "Your estimate is above the sportsbook's implied "
                "probability. Estimated value is positive under "
                "your assumptions."
            )
        elif difference < 0:
            st.warning(
                "Your estimate is below the sportsbook's implied "
                "probability. Estimated value is negative under "
                "your assumptions."
            )
        else:
            st.info(
                "Your estimate matches the sportsbook's implied "
                "probability before other factors."
            )

        st.caption(
            "Expected profit is a mathematical estimate, not a "
            "guarantee. It depends on your probability estimate "
            "being realistic."
        )


# -------------------------
# NFL HISTORICAL PREDICTION MODEL
# -------------------------

st.divider()
st.header("🏈 NFL Historical Prediction Model")

st.write(
    "This model uses historical regular-season results to maintain "
    "Elo ratings for each team. Ratings are updated after games, "
    "then used to estimate future matchup probabilities."
)

st.info(
    "This is a basic research model, not a guaranteed betting edge. "
    "It does not currently account for injuries, starting quarterbacks, "
    "weather, or current sportsbook prices."
)

try:
    with st.spinner("Loading historical NFL games and building Elo ratings..."):
        history = load_nfl_history()
        elo_ratings, historical_predictions = build_elo_model(history)
        summary, test_games = get_backtest_summary(
            historical_predictions
        )

    st.success(
        f"Loaded {len(history):,} completed NFL regular-season games."
    )

    st.subheader("Historical Backtest")

    st.write(
        "The model predicts each game before updating its ratings "
        "with that game's result. The final 20% of games are used "
        "for a chronological test."
    )

    if summary:
        col1, col2, col3, col4, col5 = st.columns(5)

        col1.metric(
            "Test games",
            f"{summary['test_games']:,}",
        )
        col2.metric(
            "Winner accuracy",
            f"{summary['accuracy'] * 100:.1f}%",
        )
        col3.metric(
            "Brier score",
            f"{summary['brier']:.3f}",
            help="Lower is better. A perfect probability forecast scores 0.",
        )
        col4.metric(
            "Baseline Brier Score",
            f'{summary["baseline_brier"]:.4f}',
        )

        col5.metric(
            "Baseline winner accuracy",
            f"{summary['baseline_accuracy'] * 100:.1f}%",
            help="Predicts the side favored by the historical home-result average, using only earlier dates. Tied games are excluded from accuracy.",
        )

        st.caption(
            f"Test period: {summary['first_date']} to "
            f"{summary['last_date']}. Accuracy is based on "
            "non-tied games. Historical performance does not "
            "guarantee future performance."
        )

        st.subheader("Backtest Results by Season")
        st.caption(
            "Uses only games in the same final-20% test period shown above. "
            "The first and current seasons may be partial. Accuracy excludes "
            "ties; Brier scores include them. Positive accuracy gain and "
            "positive Brier improvement mean Elo beat the baseline. "
            "pp means percentage points."
        )
        st.dataframe(
            get_season_backtest_rows(test_games),
            hide_index=True,
            use_container_width=True,
        )

        st.subheader("Probability Calibration")
        st.write(
            "When the model assigns the home team around a 60% chance, "
            "does the home team win around 60% of the time?"
        )
        st.caption(
            "Uses the same test period, with ties excluded. Each row groups "
            "home-team predictions into a 10-percentage-point range; upper "
            "bounds are excluded except 100%. Compare the average prediction "
            "with the actual home win rate. A gap near zero is better. "
            "A positive gap means home teams won more often than predicted; "
            "a negative gap means they won less often. Small samples can "
            "produce large gaps by chance. This is a diagnostic, not an "
            "adjustment to the model's probabilities."
        )
        calibration_rows = get_calibration_rows(test_games)
        if calibration_rows:
            st.dataframe(
                calibration_rows,
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.info("No non-tied test games are available for calibration.")

        st.subheader("Probability Adjustment Test")
        st.write(
            "This experiment moves probabilities toward 50% to test "
            "whether softer confidence improves forecasts."
        )
        adjustment = test_probability_adjustment(historical_predictions)
        if adjustment:
            st.caption(
                f"Adjustment learned from {adjustment['calibration_games']:,} "
                f"games dated {adjustment['calibration_first']} to "
                f"{adjustment['calibration_last']}. Compared on "
                f"{adjustment['evaluation_games']:,} later games dated "
                f"{adjustment['evaluation_first']} to "
                f"{adjustment['evaluation_last']}. Whole dates stay together, "
                "so the comparison may include slightly more games than "
                "the summary above. Elo still updates after each completed "
                "date; the adjustment is fixed before evaluation begins."
            )
            original_col, adjusted_col, improvement_col = st.columns(3)
            original_col.metric(
                "Original Brier (comparison games)",
                f"{adjustment['original_brier']:.4f}",
            )
            adjusted_col.metric(
                "Adjusted Brier (same games)",
                f"{adjustment['adjusted_brier']:.4f}",
            )
            improvement_col.metric(
                "Brier improvement",
                f"{adjustment['improvement']:+.4f}",
                help="Positive means the adjustment improved the Brier score.",
            )
            example = shrink_probability(0.80, adjustment["strength"])
            st.write(
                f"**Adjustment strength:** {adjustment['strength']:.2f} "
                f"(1.00 keeps the original probability). "
                f"An 80% prediction becomes **{example * 100:.1f}%**."
            )
            if adjustment["improvement"] > 0:
                st.success(
                    "The adjusted probabilities scored better on these "
                    "later comparison games."
                )
            elif adjustment["improvement"] < 0:
                st.warning(
                    "The adjustment did not improve these later games. "
                    "The original model scored better."
                )
            else:
                st.info("The original and adjusted scores are equal.")
            st.caption(
                "Ties count as 0.5 for Brier scoring. This adjustment keeps "
                "the same favorite, so winner accuracy does not change. "
                "This is an exploratory comparison: we already inspected "
                "this test period's results. Future unseen games are needed "
                "for independent confirmation. Matchup predictions below "
                "continue to use the original Elo probabilities."
            )
        else:
            st.info("Not enough historical games for an adjustment test.")

        with st.expander("View recent historical test predictions"):
            st.dataframe(
                [
                    {
                        "Date": game["Date"],
                        "Season": game["Season"],
                        "Home Team": game["Home Team"],
                        "Away Team": game["Away Team"],
                        "Predicted Home Win %": (
                            game["Predicted Home Win %"]
                        ),
                        "Actual Result": game["Actual Result"],
                    }
                    for game in test_games[-50:]
                ],
                hide_index=True,
                use_container_width=True,
    )

    st.subheader("Predict an NFL Matchup")

    team_codes = sorted(elo_ratings.keys())

    if len(team_codes) >= 2:
        home_team = st.selectbox(
            "Select the home team",
            team_codes,
            index=team_codes.index("KC") if "KC" in team_codes else 0,
            key="elo_home",
        )

        away_options = [
            team for team in team_codes if team != home_team
        ]

        default_away_index = (
            away_options.index("BUF")
            if "BUF" in away_options
            else 0
        )

        away_team = st.selectbox(
            "Select the away team",
            away_options,
            index=default_away_index,
            key="elo_away",
        )

        home_rating = elo_ratings[home_team]
        away_rating = elo_ratings[away_team]

        home_probability = expected_home_win(
            home_rating,
            away_rating,
        )
        away_probability = 1 - home_probability

        col1, col2 = st.columns(2)

        col1.metric(
            f"{home_team} estimated win probability",
            f"{home_probability * 100:.1f}%",
        )
        col2.metric(
            f"{away_team} estimated win probability",
            f"{away_probability * 100:.1f}%",
        )

        matchup_adjustment = test_probability_adjustment(
            historical_predictions
        )
        if matchup_adjustment:
            strength = matchup_adjustment["strength"]
            adjusted_home = shrink_probability(home_probability, strength)
            adjusted_away = 1 - adjusted_home
            st.write("**Original and adjusted matchup probabilities**")
            st.dataframe(
                [
                    {
                        "Team": home_team,
                        "Original Elo win %": round(home_probability * 100, 1),
                        "Adjusted win %": round(adjusted_home * 100, 1),
                    },
                    {
                        "Team": away_team,
                        "Original Elo win %": round(away_probability * 100, 1),
                        "Adjusted win %": round(adjusted_away * 100, 1),
                    },
                ],
                hide_index=True,
                use_container_width=True,
            )
            st.caption(
                f"Adjusted probabilities use strength {strength:.2f}, "
                "learned from the earlier calibration period shown above. "
                "Both teams' adjusted probabilities add to 100%; the "
                "favorite stays the same. These are experimental estimates. "
                "The adjustment is recalculated when historical data updates "
                "and does not account for injuries or weather."
            )

        col1, col2 = st.columns(2)
        col1.metric(f"{home_team} Elo rating", f"{home_rating:.0f}")
        col2.metric(f"{away_team} Elo rating", f"{away_rating:.0f}")

        st.caption(
            "Probabilities include a fixed home-field advantage. "
            "They are model estimates, not live odds or guarantees."
        )

    st.divider()
    st.subheader("NFL Team Strengths & Weaknesses")
    st.caption(
        "Season-to-date regular-season statistics for all 32 NFL teams. "
        "These provide matchup context and do not change Elo probabilities. "
        "Season totals are current, not historical snapshots for the sidebar date."
    )
    available_seasons = sorted({game["season"] for game in history}, reverse=True)
    stats_season = st.selectbox(
        "Team statistics season", available_seasons[:5], key="team_stats_season",
    )
    with st.expander("View offense, defense, and league comparisons"):
        if st.button("Load team statistics", key="load_team_stats"):
            st.session_state["team_stats_loaded_season"] = stats_season
        if st.session_state.get("team_stats_loaded_season") == stats_season:
            try:
                with st.spinner("Loading all NFL teams..."):
                    team_stats = load_all_nfl_team_statistics(stats_season)
                league_rows = team_stats["rows"]
                st.caption(
                    f"Source: ESPN. Retrieved {team_stats['fetched_at']}. "
                    f"Available teams: {len(league_rows)}/{team_stats['expected']}. "
                    "Cached for up to one hour; Refresh live data clears the cache."
                )
                if len(league_rows) < 32:
                    st.warning(
                        "Some team data is unavailable. Averages and ranks "
                        "compare only available teams."
                    )
                if league_rows:
                    names = [row["Team"] for row in league_rows]
                    selected_name = st.selectbox(
                        "Choose any NFL team", names, key="team_strength_selection",
                    )
                    selected_stats = next(
                        row for row in league_rows if row["Team"] == selected_name
                    )
                    st.write(
                        f"**{selected_name}: {selected_stats['Games']} games**"
                    )
                    comparisons = get_team_comparison_rows(selected_stats, league_rows)
                    st.dataframe(comparisons, hide_index=True, use_container_width=True)
                    strengths = [
                        row["Statistic"] for row in comparisons
                        if row["Assessment"] == "Above league average"
                    ]
                    weaknesses = [
                        row["Statistic"] for row in comparisons
                        if row["Assessment"] == "Below league average"
                    ]
                    st.write("**Above-average areas:** " + (", ".join(strengths) or "None in available metrics."))
                    st.write("**Below-average areas:** " + (", ".join(weaknesses) or "None in available metrics."))
                    st.caption(
                        "Rank 1 is best for the listed metric. Lower yards and "
                        "points allowed are better on defense. League averages "
                        "are unweighted averages of available team values. "
                        "These comparisons do not adjust for opponent strength "
                        "or game situation; yards alone do not establish quality. "
                        "Points include all team scoring, including defense and "
                        "special teams. Early-season samples may be small."
                    )
                    if st.checkbox("Compare all NFL teams", key="show_all_team_stats"):
                        st.dataframe(
                            league_rows, hide_index=True, use_container_width=True,
                        )
                else:
                    st.info("No team statistics are available for this season.")
                if team_stats["errors"]:
                    if st.checkbox("Show unavailable team data", key="show_team_stats_errors"):
                        for error in team_stats["errors"]:
                            st.write(error)
            except (requests.exceptions.RequestException, ValueError, KeyError, TypeError, AttributeError) as exc:
                st.warning(f"Team statistics could not be loaded: {exc}")
        else:
            st.info("Click Load team statistics to retrieve the selected season.")

    st.divider()
    st.subheader("NFL Player Statistics: QB, RB & WR")
    st.caption(
        "Browse any NFL team. Regular-season player totals provide context "
        "and do not change matchup probabilities."
    )
    with st.expander("View quarterback, running back, and wide receiver stats"):
        if st.checkbox("Open player statistics", key="open_player_stats"):
            try:
                player_teams = load_nfl_player_team_directory()
                team_names = [team["name"] for team in player_teams]
                player_team_name = st.selectbox(
                    "Player statistics team", team_names, key="player_stats_team",
                )
                player_team_id = next(
                    team["id"] for team in player_teams
                    if team["name"] == player_team_name
                )
                player_season = st.selectbox(
                    "Player statistics season", available_seasons[:5],
                    key="player_stats_season",
                )
                selection = (player_team_id, player_season)
                if st.button("Load QB, RB & WR stats", key="load_player_stats"):
                    st.session_state["loaded_player_stats_selection"] = selection
                if st.session_state.get("loaded_player_stats_selection") == selection:
                    with st.spinner("Loading roster and player season statistics..."):
                        player_data = load_nfl_team_player_statistics(
                            player_team_id, player_season,
                        )
                    st.caption(
                        f"Source: ESPN. {player_season} regular season. "
                        f"Retrieved {player_data['fetched_at']}. "
                        f"Statistics available for {len(player_data['rows'])}/"
                        f"{player_data['roster_count']} roster players at these "
                        "positions. Cached up to one hour."
                    )
                    qb_tab, rb_tab, wr_tab = st.tabs(
                        ["Quarterbacks", "Running backs", "Wide receivers"]
                    )
                    for position, tab in zip(("QB", "RB", "WR"), (qb_tab, rb_tab, wr_tab)):
                        with tab:
                            position_rows = [
                                row for row in player_data["rows"]
                                if row["Position"] == position
                            ]
                            sort_field = {
                                "QB": "Pass attempts", "RB": "Carries", "WR": "Targets"
                            }[position]
                            position_rows.sort(
                                key=lambda row: row.get(sort_field) or 0, reverse=True,
                            )
                            if position_rows:
                                st.dataframe(
                                    position_rows, hide_index=True,
                                    use_container_width=True,
                                )
                            else:
                                st.info("No statistics available for this position.")
                    st.caption(
                        "Players come from ESPN's roster for the selected season, "
                        "including reserves when returned. This is not a confirmed "
                        "starting lineup. Player totals can include games for other "
                        "teams after a trade; they are not necessarily totals for "
                        "the selected team alone. Blank values mean unavailable, "
                        "not zero. Passer rating is not ESPN Total QBR. "
                        "Stats are season totals, not snapshots as of the sidebar "
                        "date. Injuries and recent-game splits will be added separately."
                    )
                    if player_data["errors"] and st.checkbox(
                        "Show players with unavailable stats", key="player_stat_errors",
                    ):
                        for error in player_data["errors"]:
                            st.write(error)
                else:
                    st.info("Click Load QB, RB & WR stats for the selected team and season.")
            except (requests.exceptions.RequestException, ValueError, KeyError, TypeError, AttributeError) as exc:
                st.warning(f"Player statistics could not be loaded: {exc}")

    st.divider()
    st.subheader("NFL Injury & Availability Updates")
    st.caption(
        "Latest ESPN player statuses for all NFL teams. These are current "
        "updates, not reports as of the sidebar date or selected statistics "
        "season. They do not change model probabilities."
    )
    with st.expander("View current injury and availability reports"):
        if st.button("Load / refresh injury updates", key="refresh_injury_updates"):
            load_nfl_injury_updates.clear()
            st.session_state["show_injury_updates"] = True
        if st.session_state.get("show_injury_updates"):
            try:
                with st.spinner("Loading NFL injury updates..."):
                    injury_report = load_nfl_injury_updates()
                    injury_teams = load_nfl_player_team_directory()
                st.caption(
                    f"Source: ESPN. Retrieved {injury_report['fetched_at']}. "
                    f"Source timestamp: {injury_report['source_timestamp']}. "
                    f"Source season: {injury_report['season']}. "
                    "Data is cached for up to five minutes."
                )
                injury_team_options = sorted(
                    {team["name"] for team in injury_teams}
                    | set(injury_report["teams"])
                )
                injury_team = st.selectbox(
                    "Injury report team", ["All teams"] + injury_team_options,
                    key="injury_team_selection",
                )
                include_active = st.checkbox(
                    "Include Active status updates", key="include_active_injury_updates",
                    help="The source can list cleared players and other availability news with Active status.",
                )
                injury_rows = [
                    row for row in injury_report["rows"]
                    if (injury_team == "All teams" or row["Team"] == injury_team)
                    and (include_active or row["Status"].lower() != "active")
                ]
                status_options = sorted(
                    {"Probable", "Questionable", "Doubtful", "Out", "Injured Reserve"}
                    | {row["Status"] for row in injury_rows}
                )
                status_filter = st.multiselect(
                    "Filter injury status",
                    status_options,
                    key="injury_status_selection",
                    help="Leave empty to show all available statuses. Probable appears only when explicitly reported by ESPN; no status is inferred.",
                )
                if status_filter:
                    injury_rows = [
                        row for row in injury_rows if row["Status"] in status_filter
                    ]
                positions = sorted({row["Position"] for row in injury_rows})
                position_filter = st.selectbox(
                    "Injury report position", ["All positions"] + positions,
                    key="injury_position_selection",
                )
                if position_filter != "All positions":
                    injury_rows = [
                        row for row in injury_rows if row["Position"] == position_filter
                    ]
                st.write(f"**{len(injury_rows)} listed updates match your filters.**")
                if injury_rows:
                    st.dataframe(
                        injury_rows, hide_index=True, use_container_width=True,
                        column_config={
                            "Player page": st.column_config.LinkColumn(
                                "ESPN player page", display_text="View player",
                            ),
                        },
                    )
                else:
                    st.info(
                        "No reports match these filters. This does not confirm "
                        "that every player is healthy or available."
                    )
                st.caption(
                    "Questionable does not mean ruled out. Out and Injured "
                    "Reserve are different statuses. Active updates are hidden "
                    "unless selected. Report times are shown as supplied by "
                    "ESPN in UTC. This feed may include older reports and "
                    "availability news; it is not a confirmed game-day inactive "
                    "list. Use the player links to review the latest details."
                )
            except (requests.exceptions.RequestException, ValueError, KeyError, TypeError, AttributeError) as exc:
                st.warning(f"Injury updates could not be loaded: {exc}")
        else:
            st.info("Click Load / refresh injury updates to view the latest reports.")

    st.subheader("Current Model Team Ratings")

    rating_table = [
        {"Team": team, "Elo Rating": round(rating, 1)}
        for team, rating in sorted(
            elo_ratings.items(),
            key=lambda item: item[1],
            reverse=True,
        )
    ]

    st.dataframe(
        rating_table,
        hide_index=True,
        use_container_width=True,
    )

except requests.exceptions.Timeout:
    st.error(
        "The historical NFL dataset took too long to download. "
        "Refresh the app and try again."
    )
except requests.exceptions.RequestException as exc:
    st.error(
        f"Could not download the historical NFL dataset: {exc}"
    )
except (ValueError, TypeError, KeyError, csv.Error) as exc:
    st.error(
        f"Could not process the historical NFL data: {exc}"
    )

st.divider()
st.caption(
    "EdgeLab Sports AI — historical Elo estimates and betting "
    "calculations are for research and educational purposes. "
    "No prediction guarantees a result or profit."
)
