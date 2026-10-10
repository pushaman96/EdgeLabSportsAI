
import streamlit as st
import requests
from datetime import date, timedelta

st.set_page_config(
    page_title="EdgeLab Sports AI",
    page_icon="🏈",
    layout="wide",
)

st.title("🏈 EdgeLab Sports AI")
st.write("Live game schedules, scores, and results")

SPORTS = {
    "NFL": "football/nfl",
    "NBA": "basketball/nba",
}

BASE_URL = "https://site.api.espn.com/apis/site/v2/sports"


@st.cache_data(ttl=300)
def get_scoreboard(sport_path, game_date):
    url = f"{BASE_URL}/{sport_path}/scoreboard"
    response = requests.get(
        url,
        params={"dates": game_date.strftime("%Y%m%d")},
        timeout=15,
        headers={"User-Agent": "EdgeLabSportsAI/1.0"},
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


sport = st.sidebar.selectbox("Choose a sport", list(SPORTS))
selected_date = st.sidebar.date_input(
    "Choose game date",
    value=date.today(),
    min_value=date.today() - timedelta(days=365),
    max_value=date.today() + timedelta(days=365),
)

if st.sidebar.button("Refresh live data"):
    get_scoreboard.clear()

st.caption(
    "Scores and schedules are retrieved from ESPN's public scoreboard interface. "
    "Data availability and coverage may vary."
)

try:
    with st.spinner(f"Loading {sport} games..."):
        scoreboard = get_scoreboard(
            SPORTS[sport],
            selected_date,
        )
    show_games(scoreboard)

except requests.exceptions.Timeout:
    st.error("The data source took too long to respond. Try again.")
except requests.exceptions.RequestException as exc:
    st.error(f"Could not retrieve game data: {exc}")
except (ValueError, TypeError, KeyError) as exc:
    st.error(f"Could not read the returned game data: {exc}")

st.divider()
st.caption(
    "EdgeLab Sports AI — schedules and scores only for now. "
    "Prediction models and team statistics will be added in later steps."
)
