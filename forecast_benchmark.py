"""Chronological synthetic-line probability tests; never simulated sportsbook profit."""
import math
import statistics
from collections import defaultdict


def probability(projected, line, residuals, temperature=1.):
    if len(residuals) < 20:
        return None
    threshold = (line-projected)/max(1., math.sqrt(max(0., projected)))
    empirical = (1+sum(e > threshold for e in residuals))/(len(residuals)+2)
    p = max(.05, min(.95, empirical))
    return 1/(1+math.exp(-temperature*math.log(p/(1-p))))


def score(samples, candidate_errors, base_errors, baseline_errors, temperature=1.):
    games = defaultdict(list)
    for r in samples:
        # Fixed lines centered on the simple historical baseline, not the outcome.
        center = r['baseline']
        lines = sorted({max(.5, math.floor(center+offset*max(1., math.sqrt(center)))+.5)
                        for offset in (-1, 0, 1)})
        for line in lines:
            y = int(r['actual'] > line)
            candidate = probability(r['candidate'], line, candidate_errors, temperature)
            base_threshold=(line-r['base'])/max(1.,math.sqrt(max(0.,r['base'])))/r.get('base_uncertainty',1.)
            base_p=(1+sum(error>base_threshold for error in base_errors))/(len(base_errors)+2)if len(base_errors)>=20 else None
            baseline = probability(r['baseline'], line, baseline_errors)
            if None in (candidate, base_p, baseline):
                continue
            # Shrink the empirical frequency BEFORE clipping, as production
            # NBA/NFL season-prior forecasts do. Use the same earlier window.
            base = max(.05,min(.95,.5+.8*(base_p-.5)))
            games[r['game']].append(((candidate-y)**2, (base-y)**2, (baseline-y)**2,
                                    -y*math.log(candidate)-(1-y)*math.log(1-candidate),
                                    candidate, y,
                                    -y*math.log(base)-(1-y)*math.log(1-base),
                                    -y*math.log(baseline)-(1-y)*math.log(1-baseline)))
    def average(index):
        return statistics.mean(statistics.mean(v[index] for v in values) for values in games.values()) if games else None
    return {'synthetic_probability_games':len(games), 'synthetic_probability_cases':sum(map(len,games.values())),
            'candidate_brier':average(0), 'incumbent_brier':average(1), 'simple_baseline_brier':average(2),
            'candidate_log_loss':average(3), 'mean_over_probability':average(4), 'observed_over_rate':average(5),
            'incumbent_log_loss':average(6),'simple_baseline_log_loss':average(7)}


def residuals(samples, field):
    return [(r['actual']-r[field])/max(1.,math.sqrt(max(0.,r[field])))/(r.get('base_uncertainty',1.)if field=='base'else 1.) for r in samples]


def validate(samples, allow_date_split=False):
    """Use earlier residual fitting, then temperature selection, then untouched later tests."""
    samples = sorted(samples, key=lambda r:(r['date'],str(r['game'])))
    years = sorted({r['season'] for r in samples})
    if len(years) < 2 and not allow_date_split:
        return {'passed':False,'status':'Insufficient separate calibration and validation seasons','residuals':[]}
    if not samples:return {'passed':False,'status':'No comparable historical samples','residuals':[]}
    test_year = years[-1]
    if len(years)>=2:
        earlier = [r for r in samples if r['season'] < test_year]
        testing = [r for r in samples if r['season'] == test_year]
        validation_mode='Complete later observed season'
    else:
        all_dates=sorted({r['date']for r in samples})
        test_start=all_dates[int(.7*len(all_dates))]
        earlier=[r for r in samples if r['date']<test_start]
        testing=[r for r in samples if r['date']>=test_start]
        validation_mode='Later dates within limited verified context history'
    dates = sorted({r['date'] for r in earlier})
    split = dates[int(.7*len(dates))] if dates else ''
    fitting = [r for r in earlier if r['date'] < split]
    calibration = [r for r in earlier if r['date'] >= split]
    ce,be,se = (residuals(fitting,field) for field in ('candidate','base','baseline'))
    options = []
    for strength in (.25,.5,.75,1.,1.25):
        fitted = score(calibration,ce,be,se,strength)
        if fitted['candidate_brier'] is not None:
            options.append((fitted['candidate_brier'],strength))
    temperature = min(options)[1] if options else 1.
    tested = score(testing,ce,be,se,temperature)
    games = defaultdict(list)
    for r in testing:
        games[r['game']].append((abs(r['candidate']-r['actual']),abs(r['base']-r['actual']),
                                 abs(r['baseline']-r['actual']),abs(r['workload']-r['actual_workload']),
                                 abs(r['base_workload']-r['actual_workload'])))
    def average(index):
        return statistics.mean(statistics.mean(v[index] for v in values) for values in games.values()) if games else None
    cm,bm,sm,wm,bwm = (average(i) for i in range(5))
    enough = len(fitting)>=50 and len({r['game']for r in calibration})>=10 and len(games)>=20
    stat_passed = enough and cm < min(bm,sm) and wm <= bwm
    probability_passed = enough and tested['candidate_brier'] is not None and tested['candidate_brier'] < min(tested['incumbent_brier'],tested['simple_baseline_brier']) and tested['candidate_log_loss'] <= min(tested['incumbent_log_loss'],tested['simple_baseline_log_loss'])
    return dict(tested,passed=bool(stat_passed and probability_passed),forecast_passed=bool(stat_passed),
                probability_passed=bool(probability_passed),candidate_mae=cm,incumbent_mae=bm,simple_baseline_mae=sm,
                candidate_workload_mae=wm,incumbent_workload_mae=bwm,validation_games=len(games),
                calibration_examples=len(fitting),temperature_games=len({r['game']for r in calibration}),
                temperature=temperature,residuals=ce,validation_season=test_year,validation_mode=validation_mode,calibration_split=split,
                calibration_through=max((r['date']for r in earlier),default=None),
                validation_from=min((r['date']for r in testing),default=None),
                status='Historical stat/workload and synthetic-probability checks passed' if stat_passed and probability_passed else 'Candidate retained for research; incumbent retained',
                scope='Game-weighted synthetic half-unit lines; reference distributions fit on the same earlier window. No historical sportsbook lines, prices, ROI or independent future-performance proof')


def validate_variants(variants):
    """Select structure on the earliest fitting window, never the later test outcomes."""
    available={name:rows for name,rows in variants.items()if rows}
    if not available:return {'passed':False,'status':'No comparable variants','residuals':[]}
    rows=next(iter(available.values()));test_year=max(r['season']for r in rows)
    earlier_dates=sorted({r['date']for r in rows if r['season']<test_year})
    split=earlier_dates[int(.7*len(earlier_dates))]if earlier_dates else ''
    scored=[]
    for name,values in available.items():
        games=defaultdict(list)
        for r in values:
            if r['season']<test_year and r['date']<split:
                games[r['game']].append((abs(r['candidate']-r['actual']),abs(r['workload']-r['actual_workload']),abs(r['base_workload']-r['actual_workload'])))
        if games:
            avg=lambda i:statistics.mean(statistics.mean(v[i]for v in group)for group in games.values())
            scored.append((avg(1)>avg(2)+1e-12,avg(0),name,len(games)))
    chosen=min(scored)[2]if scored else sorted(available)[0]
    report=validate(available[chosen])
    report.update(selected_variant=chosen,variant_selection_through=max((r['date']for r in available[chosen]if r['season']<test_year and r['date']<split),default=None),
                  variants_tested_on_earlier_window=len(scored),selection_rule='Prefer no worse earlier workload error, then lower earlier stat MAE; later outcomes never select the variant')
    return report
