
import streamlit as st
import requests
from datetime import date, timedelta

st.set_page_config(
    page_title="EdgeLab Sports AI",
    page_icon="🏈",
    layout="wide",
)

st.title("🏈 EdgeLab Sports AI")
st.write("Live scores, standings, and betting value analysis")

SPORTS = {
    "NFL": "football/nfl",
    "NBA": "basketball/nba",
}

BASE_URL = "https://site.api.espn.com/apis"
HEADERS = {"User-Agent": "EdgeLabSportsAI/1.0"}


# -------------------------
# ESPN DATA
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
        st.info(
            "No games were listed for this date. "
            "Try another date."
        )
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

        home_team = home.get("team", {}).get(
            "displayName", "Home"
        )
        away_team = away.get("team", {}).get(
            "displayName", "Away"
        )
        home_score = home.get("score", "—")
        away_score = away.get("score", "—")

        status = (
            event.get("status", {})
            .get("type", {})
            .get("description", "Status unavailable")
        )

        start_time = event.get("date", "")
        if start_time:
            start_time = (
                start_time.replace("T", " ")[:16] + " UTC"
            )

        with st.container(border=True):
            st.subheader(f"{away_team} at {home_team}")
            col1, col2, col3 = st.columns(3)

            col1.metric(away_team, home_score)
            col2.metric(home_team, home_score)
            col3.write("**Status**")
            col3.write(status)

            if start_time:
                st.caption(f"Scheduled time: {start_time}")


def stat_value(stats, possible_names):
    for stat in stats:
        if stat.get("name") in possible_names:
            return stat.get(
                "displayValue",
                stat.get("value", "—"),
            )
    return "—"


def parse_standings(data):
    rows = []
    seen_teams = set()

    def walk(node, group_name="League"):
        if not isinstance(node, dict):
            return

        current_group = node.get("name", group_name)
        standings = node.get("standings", {})
        entries = standings.get("entries", [])

        for entry in entries:
            team = entry.get("team", {})
            team_name = team.get(
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
                    ["winPercent", "winPct",
                     "winningPercentage"],
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
# BETTING CALCULATOR
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
# SIDEBAR
# -------------------------

sport = st.sidebar.selectbox(
    "Choose a sport",
    list(SPORTS),
)

selected_date = st.sidebar.date_input(
    "Choose game date",
    value=date.today(),
    min_value=date.today() - timedelta(days=365),
    max_value=date.today() + timedelta(days=365),
)

if st.sidebar.button("Refresh live data"):
    get_scoreboard.clear()
    get_standings.clear()


# -------------------------
# SCHEDULE AND SCORES
# -------------------------

st.subheader(f"{sport} Schedule & Scores")

try:
    with st.spinner(f"Loading {sport} games..."):
        scoreboard = get_scoreboard(
            SPORTS[sport],
            selected_date,
        )
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
            "ESPN did not return recognizable standings. "
            "Try refreshing later."
        )
    else:
        team_names = ["All teams"] + sorted(
            row["Team"] for row in teams
        )

        selected_team = st.selectbox(
            "Find a team's record",
            team_names,
        )

        if selected_team == "All teams":
            filtered_teams = teams
        else:
            filtered_teams = [
                row for row in teams
                if row["Team"] == selected_team
            ]

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
    "Enter the sportsbook's American odds and your estimated "
    "probability of winning to evaluate a hypothetical bet."
)

st.info(
    "This tool does not create predictions or retrieve sportsbook "
    "odds. Your probability estimate is an input, not a verified forecast."
)

with st.form("bet_calculator"):
    col1, col2 = st.columns(2)

    with col1:
        bet_sport = st.selectbox(
            "Sport",
            ["NFL", "NBA"],
        )

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
            help="Examples: -110, +150, -200",
        )

    with col2:
        estimated_probability = st.slider(
            "Your estimated chance of winning (%)",
            min_value=1,
            max_value=99,
            value=60,
            step=1,
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
        st.error(
            "American odds cannot be zero. Use odds such as -110 or +150."
        )
    else:
        market_probability = implied_probability(odds)
        decimal_odds = american_to_decimal(odds)
        estimated_probability_decimal = (
            estimated_probability / 100
        )

        potential_profit = stake * (decimal_odds - 1)
        potential_payout = stake + potential_profit

        expected_profit = (
            estimated_probability_decimal * potential_profit
            - (1 - estimated_probability_decimal) * stake
        )

        probability_difference = (
            estimated_probability_decimal - market_probability
        ) * 100

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
            f"{probability_difference:+.2f} percentage points",
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

        st.caption(
            "Expected profit is a mathematical estimate based on "
            "your input probability and the entered odds. It is not "
            "a guarantee and excludes any additional fees."
        )

        if probability_difference > 0:
            st.success(
                "Your estimated probability is above the sportsbook's "
                "implied probability. The bet has positive estimated "
                "value under your assumptions."
            )
        elif probability_difference < 0:
            st.warning(
                "Your estimated probability is below the sportsbook's "
                "implied probability. The bet has negative estimated "
                "value under your assumptions."
            )
        else:
            st.info(
                "Your estimated probability matches the sportsbook's "
                "implied probability before considering other factors."
            )

        st.write(
            f"**Break-even win rate:** "
            f"{market_probability * 100:.2f}%"
        )

        st.write(
            f"**Decimal odds:** {decimal_odds:.3f}"
        )

st.divider()
st.caption(
    "EdgeLab Sports AI — schedules, scores, standings, and a "
    "user-input betting calculator. Estimates are not guarantees "
    "of outcomes or profit."
)
