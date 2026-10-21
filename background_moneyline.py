"""Same chronological Elo and shrinkage calculations as the app; no UI execution."""
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
