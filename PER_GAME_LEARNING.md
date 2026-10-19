# Learning from each tracked game

The old calibration gate waited for 100 prospective picks and 30 games within
each model/category/direction/strategy. That research validation still exists.
A new experimental layer updates future forecasts after the first eligible
tracked game, without claiming that the update has already improved accuracy.

## What changes

- NFL and supported NBA prop projections and expected opportunities receive separate relative
  error adjustments. Each game contributes one averaged update per model/category.
- NFL and NBA moneylines, and supported NFL props, receive a bounded probability
  strength adjustment. Opposite-side probabilities remain complementary.
- Sport, model and category stay separate. Original and adjusted projections,
  workload, probability and update version are frozen with new picks.
- The scheduled grader runs at minutes 2, 17, 32 and 47. GitHub scheduling and
  upstream statistics can be delayed. The saved state becomes usable when the
  deployed app picks up the new commit; this is not instantaneous online service.
- Prospective, graded original recommendations and the separate analyzed-forecast log train this layer. Historical
  imports, manual selections, cushions, pending/unverified results and preseason
  games do not. Unanalyzed games and NBA manual prop quotes cannot train a model. Supported NBA analyzed props can train the new minutes-rate model.

## How large is an update?

Forecast and workload errors are normalized by the saved base forecast and clipped
to +/-50%. An exponential update uses rate 1/13 (12 games of neutral initial
weight). The resulting multiplicative forecast adjustments are capped at +/-15%.
Probability strength uses a clipped log-loss gradient with step .1, bounded to
[.5, 1.5]. These are engineering defaults, not tuned or validated optimal values.
A rebuild replays the frozen ledger in grading-time order: refreshing the app or
rerunning the grader cannot count the same evidence again. Duplicate books,
lines and directions for one player/game do not multiply its influence.

Older prospective records with the original projections can initialize the layer.
New records save base projections explicitly, so an adjusted forecast does not
become its own training target. Corrections use only records available before
prediction time. Missing, stale, malformed or future state falls back to the base
forecast. Existing forecast baseline and price-edge gates remain in place.

## Explaining misses

The review reports central forecast versus actual and workload versus actual.
When a yardage/reception forecast and positive workload totals exist, the total
forecast error is split exactly into:

- Workload contribution = (actual opportunities - expected opportunities) x
  forecast output per expected opportunity.
- Efficiency contribution = actual output - actual opportunities x that same
  forecast output per opportunity.

These describe the measured discrepancy. They do not prove that an injury,
coaching decision or weather caused it. Moneylines report the selected team's
score margin; without a saved scoring/possession forecast, cause stays unknown.

## Measuring whether it helps

The learning panel compares original and issued Brier scores on newly frozen
adjusted picks after those games finish. It never grades a newly fitted estimate
against the result that just trained it. Earlier records cannot retroactively
prove this layer works. Same-game selections are correlated; these comparisons
are descriptive and do not establish statistical significance or profitability.
No automatic win-rate or profit improvement is promised. Full tree retraining,
player-specific effects and numerical injury/weather features remain separate.

Run checks with `python -m unittest discover -s tests -p 'test_*.py'`.


## Forecast learning expansion

Every usable analyzed NFL/NBA prop quote and moneyline is frozen before kickoff
in `analyzed_forecasts.json`, including forecasts rejected for insufficient edge
or a failed baseline gate. Missing forecasts, late quotes and unverified matchups
cannot be recorded. This ledger is separate from `published_picks.json`; analysis
records never enter the official pick win/loss record. Same player/game/model
forecasts train once, regardless of quote/direction/threshold count. Publication
requires the same private permanent-storage token as pick saving. Viewing an
unanalyzed game does not create a prediction. NBA preseason is excluded.

### Automatic comparison and rollback

For each model/category, compare baseline versus candidate predictions saved
before outcomes, with each game's mean loss difference counted once. The guard
uses up to 20 recent comparison games. It halves the adjustment after 5 games
with mean candidate degradation above .01; it rolls back to the base forecast
after 10 games when mean degradation exceeds .01 and its approximate 95% lower
bound is positive. Probability comparisons use Brier differences, while count/
yardage comparisons use normalized squared-error differences, clipped to +/-1.
This is an engineering heuristic, not a statistical guarantee. Frozen shadow
candidates continue to be scored during rollback; later recovery can restore
weight. Base/candidate Brier scores, game count, status and applied weight appear
in the learning panel on the main dashboard.

### Numerical NFL context adjustments

Confirmed absent offensive teammates' recent carries/targets are partially
redistributed across active players in proportion to their observed usage.
Half the missing workload is available for redistribution, with a 15% per-player
cap. Questionable/Doubtful teammates are not presumed absent. Where a confirmed
absent primary QB and one active replacement each have 30 recent prior attempts,
the observed yards-per-attempt ratio produces an efficiency adjustment bounded
to .85–1.10 for passing/receiving yards. Missing replacement evidence stays neutral.
These coefficients are conservative engineering defaults, not fitted causal effects.

Predicted final-margin scenarios use strictly older team point margins, empirical
margin variation and smoothed scenario frequencies. Prior team attempts/carries
by final-margin context yield shrunk workload adjustments capped at +/-10%.
The model distinguishes win by 8+, within 7 and lose by 8+. Those are final-margin
scenarios, not estimates of time spent leading/trailing. Missing history stays
neutral. The existing descriptive live score-state review remains separate.
Each new NFL forecast saves its original projection and numerical context factors.
The underlying historical baseline test does not validate these added context
adjustments; they require prospective evaluation. Moneylines still have no
numerical injury/line/defense effect, and weather remains unquantified.

### NBA prop model

Supports points, rebounds, assists and made threes. Uses verified NBA.com
regular-season player game logs from the prior and current seasons, current ESPN
rosters, a unique team/name mapping between providers, and fresh injury coverage.
Player/team IDs are never joined across provider namespaces. Requires at least
8 prior current-team appearances within 240 days. Expected minutes blend the last
5 and 12 appearances, capped at 40. Production per minute is estimated from the
last 12 appearances; expected output equals minutes times that rate.
Confirmed absent teammates' observed minutes are partially redistributed by active
minute share, capped at a 10% increment and 40 total minutes. If recent team
history is missing (including the offseason), the absence adjustment stays neutral.
Rookies, trades with insufficient current-team history, uncertain player status,
missing source data and preseason stay on Pass with a reason.

Calibration errors come from the older 65% of historical game dates. A later
35% date window compares the minutes-rate forecast with an 8-game mean baseline,
using game-weighted mean absolute error. No same-day or future player rows enter
an earlier forecast. A category needs 20 later games, 50 calibration examples and
a lower validation error before it can recommend a paper selection. This is a
stat-forecast gate, not a historical odds profitability test. Empirical forecast
errors yield experimental Over/Under probabilities; a recommendation additionally
needs a fresh valid quote and at least a five-percentage-point price edge.

A live-source smoke test retrieved 26,568 player logs and tested 456 later games
(split date 2026-02-07). Mean absolute errors, candidate versus baseline:
points 4.832 vs 4.888; rebounds 1.961 vs 1.995; assists 1.431 vs 1.444;
threes 0.921 vs 0.935. These are small historical gains in the base forecast,
not evidence that the new injury adjustment, probabilities or bets are profitable.
The source endpoints may be unavailable; the UI then reports the issue and
creates no substitute picks. No new paid service or dependency is required.


## NFL passing counts and clearer explanations

Passing completions and passing touchdowns now have separate experimental count
forecasts. Required nflverse columns are retained as optional numeric inputs;
missing completions/TDs are never treated as zero. Each forecast needs 8 prior
QB starts, coverage of the latest 4 current-team games, current-season league
conversion coverage and at least 4 opponent games, plus the existing unique
roster, fresh injury, schedule, kickoff, quote and source-coverage checks.

Expected attempts blend the last 2 and 4 current-team starts. Historical attempt
variation produces a discrete mixture of attempt counts. QB completion/TD rates
shrink toward the prior-week league rate with 100 attempt-equivalents of prior
weight. Opponent conversion rates use 150 attempt-equivalents and a factor bounded
to .8–1.2. Each attempt count has a beta-binomial conversion distribution, with
fixed concentration 80 for completions and 40 for TDs. These are engineering
defaults, not proven optimal parameters. Counts stay physically bounded by attempts.
The 10th–90th percentile range describes this count distribution, not a guarantee.

The probability blends the conversion-distribution tail with a smoothed prior-game
threshold frequency. Blend weights are selected using 2024 data only and frozen
for the 2025 check. Live estimates are capped to 5%–95%. Benchmarks use fixed
pregame half-count thresholds computed from prior statistics; no past sportsbook
odds are reconstructed. The recommendation gate needs at least 100 forecasts and
50 distinct games, improved game-weighted MAE, and Brier below both .25 and the
historical-frequency benchmark, followed by a five-percentage-point quoted price
edge. Failing categories remain visible research forecasts and usable analysis
records, without entering recommended-pick results.

Live-source checks of 12,043 offensive player rows and 1,088 team rows produced
253 eligible 2025 forecasts across 179 games per category. The weight selected
from 174 eligible 2024 examples was .75 on prior threshold frequency:

| Category | Count MAE | Recent-average MAE | Benchmark Brier | Frequency Brier | Gate |
| --- | ---: | ---: | ---: | ---: | --- |
| Completions | 4.767 | 4.791 | .22509 | .22777 | Passed |
| Passing TDs | 1.036 | 1.048 | .23244 | .23204 | Research only |

These small development gains do not establish future hit rate or profitability.
The TD gate was not weakened to force a recommendation. Additional probability
work or prospective evidence is required. Per-game learning saves base/candidate
count forecasts and probabilities; new categories use the existing comparison
and rollback system. Final/live ESPN passing stats read completions from the
numerator of C/ATT, attempts from the denominator and passing TDs from TD.

Receiver targets now have an explicit supporting chain: prior team attempts
and opponent passing volume -> player target share -> targets -> shrunk catch
rate -> receptions -> historical yards per catch. At least 4 matched recent
current-team player/team games are required. This supports explanations of
receiving/reception forecasts; it does not replace an existing validated selected
model or invent a target betting market. Supporting QB completion/TD forecasts
also appear alongside already analyzed passing-yard/attempt quotes, without an
extra odds request. To compare actual completion/TD quotes, explicitly select
those existing provider market categories; the default market preset is unchanged.

The current-analysis and frozen-pick explanation panels now show equations,
forecast-versus-line distance, uncertainty ranges, numerical adjustments when
saved, validation scope and Take/Pass reasons. Missing inputs stay missing.
Target forecasts and count conversion inputs are frozen with new records for
postgame review. These deterministic explanations require no paid AI service and
make no additional odds call. Opening an old pick does not fabricate new inputs.
