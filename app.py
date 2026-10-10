import streamlit as st

st.set_page_config(
page_title="EdgeLab Sports AI",
page_icon="🏈",
layout="centered"
)

st.title("🏈 EdgeLab Sports AI")
st.write("Your personal NFL and NBA game analysis dashboard.")

sport = st.sidebar.selectbox(
"Choose a sport",
["NFL", "NBA"]
)

st.header(f"{sport} Game Analyzer")

team = st.text_input("Enter the team you want to analyze", "Home Team")

win_probability = st.slider(
"Your estimated chance of winning (%)",
min_value=1,
max_value=99,
value=55
)

odds = st.number_input(
"Sportsbook American odds",
value=-110,
step=5
)

if st.button("Analyze Game"):
if odds == 0:
st.error("American odds cannot be zero. Enter odds such as -110 or +150.")
else:
probability = win_probability / 100

if odds < 0:
implied_probability = abs(odds) / (abs(odds) + 100)
potential_profit = 10000 / abs(odds)
else:
implied_probability = 100 / (odds + 100)
potential_profit = odds

expected_value = (
probability * potential_profit
- (1 - probability) * 100
)

st.subheader(f"Results for {team}")

st.metric(
"Your estimated win probability",
f"{win_probability}%"
)

st.metric(
"Sportsbook implied probability",
f"{implied_probability * 100:.1f}%"
)

st.metric(
"Estimated value per $100 risked",
f"${expected_value:.2f}"
)

if probability > implied_probability:
st.success(
"Your estimate is above the sportsbook's implied probability."
)
else:
st.warning(
"Your estimate is not above the sportsbook's implied probability."
)

st.caption(
"This is a basic calculator, not a predictive AI model. "
"Probabilities are entered manually, and betting involves risk."
)


