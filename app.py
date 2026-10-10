
import streamlit as st
import requests
from datetime import date, timedelta

st.set_page_config(
    page_title="EdgeLab Sports AI",
    page_icon="🏈",
    layout="wide",
)

st.title("🏈 EdgeLab Sports AI")
st.write("Live schedules, scores, standings, and team records")

SPORTS = {
    "NFL": "football/nfl",
    "NBA": "basketball/nba",
}

BASE_URL = "https://site.api.espn.com/apis"

HEADERS = {"User-Agent": "EdgeLabSportsAI/1.0"}


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
    # Standings use /apis/v2/, not /apis/site/v2/.
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
        standings = node.get("standings", {})
        entries = standings.get("entries", [])

        for entry in entries:
            team = entry.get("team", {})
            team_name = team.get("displayName", "Unknown team")

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
                    stats, ["winPercent", "winPct", "winningPercentage"]
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

st.caption(
    "Schedules and scores come from ESPN's public scoreboard interface. "
    "Data availability and coverage may vary."
)

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
    st.error(f"Could not read the scoreboard data: {exc}")

st.divider()
st.subheader(f"{sport} Team Statistics & Standings")
st.caption(
    "Standings show the latest data returned by ESPN, "
    "not necessarily standings as of the selected game date."
)

try:
    with st.spinner(f"Loading {sport} team standings..."):
        standings_data = get_standings(SPORTS[sport])
        teams = parse_standings(standings_data)

    if not teams:
        st.warning(
            "ESPN did not return recognizable standings for this sport. "
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
            team_record = filtered_teams[0]
            st.markdown(f"### {selected_team}")

            col1, col2, col3 = st.columns(3)
            col1.metric("Wins", team_record["Wins"])
            col2.metric("Losses", team_record["Losses"])
            col3.metric("Win %", team_record["Win %"])

except requests.exceptions.Timeout:
    st.error("The standings data took too long to respond. Try again.")
except requests.exceptions.RequestException as exc:
    st.error(f"Could not retrieve standings: {exc}")
except (ValueError, TypeError, KeyError, AttributeError) as exc:
    st.error(f"Could not read the standings data: {exc}")

st.divider()
st.caption(
    "EdgeLab Sports AI — live schedules, scores, and standings. "
    "Betting predictions and advanced team statistics are not included yet."
)
