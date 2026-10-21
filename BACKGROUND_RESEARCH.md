# Background research and forecast preparation

The Background research and preset forecasts workflow runs hourly. GitHub schedules may be delayed. It refreshes free ESPN schedules, current rosters, injury reports, and prior/current-season player histories, then saves projection-only research. NFL preparation uses nflverse season priors; NBA preparation uses the existing minutes-rate season prior. Those projections are research, not picks or win probabilities.

On NFL Sunday/Monday/Thursday and NBA game days, an optional price collector selects the first uniquely matched upcoming event within three hours that fits the shared eight-credit Pacific-date automated budget. NFL's full preset costs at most five market/region credits; NBA's costs six. This usually means one full preset game per day, not a whole slate. Selection is chronological, not a claim of strongest betting value.

## Private setup
In this repository go to Settings → Secrets and variables → Actions → New repository secret.
Name: ODDS_API_KEY
Value: the Odds API key, entered privately.
The existing Streamlit secret does not automatically appear in GitHub Actions. No additional GitHub token is needed: the workflow uses GitHub's built-in token. Without ODDS_API_KEY, free research and grading continue and the app displays missing background-price setup.

## Budget and safety
Reservations are committed to main before any odds request. Workflow concurrency is shared with the grader. A re-run clears its pending plan and cannot reuse a previous reservation. Reservations are retained after errors or partial requests; ambiguous network failures are not retried automatically. The cap covers this background job only. Explicit app add-ons spend extra. App session autoload is disabled in favor of the durable runner.

No betting transactions are performed. Qualifying recommendations use existing model gates, source timing, actual quotes, and availability screens. Usable passes are frozen in analyzed_forecasts.json; recommendations are saved separately in published_picks.json. Unsupported anytime-TD, total, and PRA forecasts remain market quotes, not invented model picks. Moneylines retain the existing Elo limitations, including no numerical replacement/injury adjustment.

## Measurement
background_projection_history.json preserves earliest projection-only research per player/game/category/version. Final official boxscores measure projection error; missing data stays pending. Projection research has no official pick win rate.
background_validation.json reports the existing paired base-versus-issued comparisons, game weighted. Existing per-game experimental learning and rollback guards continue. This job does not automatically promote a newly fitted model; further chronological and prospective validation remains required.

## Operations
The dashboard's Background research expander reports last refresh, preparation issues, budget and projection results. Raw data/model downloads are cached in Actions for faster future runs. Current season caches expire after 30 minutes, completed seasons after one day. Cache content never contains the API key. Failed sources do not generate substitute statistics. Research and public quote snapshots are saved to this public repository; no private key is saved.
