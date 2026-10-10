
import streamlit as st
import requests
import csv
import io
import math
from datetime import date, timedelta, datetime

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
            start_time = start_time.replace("T", " ")[:16] + " UTC"

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


# -------------------------
# SCHEDULE AND SCORES
# -------------------------

st.subheader(f"{sport} Schedule & Scores")

try:
    with st.spinner(f"Loading {sport} games..."):
        scoreboard = get_scoreboard(SPORTS[sport], selected_date)
    show_games(scoreboard)

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
        col1, col2, col3 = st.columns(3)

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

        st.caption(
            f"Test period: {summary['first_date']} to "
            f"{summary['last_date']}. Accuracy is based on "
            "non-tied games. Historical performance does not "
            "guarantee future performance."
        )

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

        col1, col2 = st.columns(2)
        col1.metric(f"{home_team} Elo rating", f"{home_rating:.0f}")
        col2.metric(f"{away_team} Elo rating", f"{away_rating:.0f}")

        st.caption(
            "Probabilities include a fixed home-field advantage. "
            "They are model estimates, not live odds or guarantees."
        )

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
