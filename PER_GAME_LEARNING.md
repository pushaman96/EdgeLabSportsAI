# Learning from each tracked game

The old calibration gate waited for 100 prospective picks and 30 games within
each model/category/direction/strategy. That research validation still exists.
A new experimental layer updates future forecasts after the first eligible
tracked game, without claiming that the update has already improved accuracy.

## What changes

- NFL prop projections and expected opportunities receive separate relative
  error adjustments. Each game contributes one averaged update per model/category.
- NFL and NBA moneylines, and supported NFL props, receive a bounded probability
  strength adjustment. Opposite-side probabilities remain complementary.
- Sport, model and category stay separate. Original and adjusted projections,
  workload, probability and update version are frozen with new picks.
- The scheduled grader runs at minutes 2, 17, 32 and 47. GitHub scheduling and
  upstream statistics can be delayed. The saved state becomes usable when the
  deployed app picks up the new commit; this is not instantaneous online service.
- Only prospective, graded original recommendations train this layer. Historical
  imports, manual selections, cushions, pending/unverified results and preseason
  games do not. Untracked games and NBA manual prop quotes cannot train a model.

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
