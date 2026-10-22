"""Ten completed seasons: longer versus recent-only residual calibration.
Research only. Never edits a forecast, frozen pick, model or sportsbook request.
"""
import csv,gzip,hashlib,io,json,math,statistics
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date,datetime,timezone
from pathlib import Path
import requests

VERSION='history-window-study-v1'
CACHE=Path('.research_cache/history_window')
NBA_FIELDS={'PTS':'points','REB':'rebounds','AST':'assists','FG3M':'three_point_field_goals_made','FGM':'field_goals_made','FGA':'field_goals_attempted','FG3A':'three_point_field_goals_attempted','FTM':'free_throws_made','FTA':'free_throws_attempted'}

def numeric(v):
    if isinstance(v,bool):return None
    try:v=float(v);return v if math.isfinite(v)else None
    except (ValueError,TypeError):return None

def download(url,name):
    CACHE.mkdir(parents=True,exist_ok=True);p=CACHE/name
    if p.exists():return p.read_bytes()
    r=requests.get(url,timeout=(10,45));r.raise_for_status();blob=r.content
    if not blob:raise ValueError('Empty historical archive')
    temp=p.with_suffix(p.suffix+'.tmp');temp.write_bytes(blob);temp.replace(p)
    return blob

def nba_normalize(raw,year,cutoff):
    result=[];seen=set();skipped=0
    required={'season','season_type','game_date','game_id','athlete_id','team_id','minutes','points','rebounds','assists','three_point_field_goals_made'}
    if not raw or not required.issubset(raw[0]):raise ValueError('NBA archive schema mismatch')
    for r in raw:
        if r.get('season')!=year or r.get('season_type')!=2:continue
        day=str(r.get('game_date',''))[:10]
        if not day or day>=cutoff:continue
        minutes=numeric(r.get('minutes'))
        if r.get('did_not_play')is True or minutes is None or minutes<=0:skipped+=1;continue
        fields={k:numeric(r.get(v))for k,v in NBA_FIELDS.items()}
        if any(fields[k]is None or fields[k]<0 for k in ('PTS','REB','AST','FG3M')):skipped+=1;continue
        for made,attempt in [('FGM','FGA'),('FG3M','FG3A'),('FTM','FTA')]:
            if fields[made]is None or fields[attempt]is None or not 0<=fields[made]<=fields[attempt]:fields[made]=fields[attempt]=None
        if fields['FG3M']is None:skipped+=1;continue
        if not r.get('athlete_id')or not r.get('team_id')or not r.get('game_id'):skipped+=1;continue
        key=(str(r['game_id']),str(r['athlete_id']))
        if key in seen:raise ValueError('Duplicate player/game in NBA historical archive')
        seen.add(key)
        result.append(dict(fields,player='espn:'+str(r['athlete_id']),name=r.get('athlete_display_name'),team=str(r['team_id']),game=str(r['game_id']),date=day,season=year,minutes=minutes,PRA=fields['PTS']+fields['REB']+fields['AST']))
    return result,skipped

def load_nba(year,cutoff):
    import pyarrow.parquet as pq
    url=f'https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_nba_player_boxscores/player_box_{year}.parquet'
    blob=download(url,f'nba_{year}.parquet');raw=pq.read_table(io.BytesIO(blob)).to_pylist()
    rows,skipped=nba_normalize(raw,year,cutoff)
    return rows,dict(season=year,source=url,sha256=hashlib.sha256(blob).hexdigest(),usable_rows=len(rows),excluded_dnp_missing_or_invalid=skipped,players=len({r['player']for r in rows}),games=len({r['game']for r in rows}))

def load_nfl(year):
    from nfl_prop_model import normalize_stats
    result={};sources=[]
    for kind in ('player','team'):
        url=f'https://github.com/nflverse/nflverse-data/releases/download/stats_{kind}/stats_{kind}_week_{year}.csv.gz'
        blob=download(url,f'nfl_{kind}_{year}.csv.gz')
        raw=list(csv.DictReader(io.StringIO(gzip.decompress(blob).decode('utf-8-sig'))))
        rows=normalize_stats(raw,kind)
        if not rows or any(r['season']!=year for r in rows):raise ValueError('NFL archive season mismatch')
        result[kind]=rows;sources.append(dict(kind=kind,season=year,source=url,sha256=hashlib.sha256(blob).hexdigest(),usable_rows=len(rows)))
    return result,sources

def prior_cohort(rows,identity,limit):
    ids={r[identity]for r in rows}
    return set(sorted(ids,key=lambda pid:hashlib.sha256(str(pid).encode()).hexdigest())[:limit])

def nba_samples(prior,current,year):
    from nba_season_prior import season_projection
    selected=prior_cohort(prior,'player',64);by_player=defaultdict(list);samples=defaultdict(list)
    for r in prior+current:
        if r['player']in selected:by_player[r['player']].append(r)
    for history in by_player.values():
        for r in sorted((r for r in history if r['season']==year),key=lambda r:(r['date'],r['game'])):
            for field in ('PTS','REB','AST','FG3M','PRA'):
                f=season_projection(history,field,year,r['team'],r['date'])
                if not f or f['role_uncertain']:continue
                samples[field,f['cohort']].append(dict(season=year,date=r['date'],game=r['game'],player=r['player'],projected=f['projected'],baseline=f['baseline'],actual=r[field],workload=f['minutes'],actual_workload=r['minutes'],uncertainty=f['uncertainty']))
    return samples,dict(selected_prior_season_players=len(selected),matched_players=len({r['player']for rows in samples.values()for r in rows}))

def nfl_samples(prior,current,year):
    from nfl_season_prior import estimate,indexes,SPECS
    selected=set()
    for position,limit in [('QB',24),('RB',40),('WR',40),('TE',24)]:selected.update(prior_cohort([r for r in prior['player']if r.get('position')==position],'player_id',limit))
    players=prior['player']+current['player'];idx=indexes(players,prior['team']+current['team']);cache={};samples=defaultdict(list)
    for r in current['player']:
        if r['player_id']not in selected:continue
        for market,(stat,workload,_)in SPECS.items():
            allowed=('QB',)if 'pass_'in market else ('WR','TE','RB','HB','FB')if 'reception'in market else ('RB','HB','FB')
            if r.get('position')not in allowed or numeric(r.get(stat))is None or numeric(r.get(workload))is None:continue
            f=estimate(r['player_id'],year,r['week'],r['team'],r['opponent_team'],market,idx,cache)
            if not f or f['role_uncertain']or f['coverage_gap']:continue
            samples[market,f['cohort']].append(dict(season=year,date=f'{year}-{r["week"]:02d}',game=r['game_id'],player=r['player_id'],projected=f['projected'],baseline=f['baseline'],actual=r[stat],workload=f['opportunities'],actual_workload=r[workload],uncertainty=f['uncertainty']))
    return samples,dict(selected_prior_season_players=len(selected),matched_players=len({r['player']for rows in samples.values()for r in rows}))

def deterministic_sample(rows,limit):
    # Sampling identity contains no actual outcome or retrospective rank.
    return sorted(rows,key=lambda r:hashlib.sha256((str(r['game'])+'|'+str(r['player'])).encode()).hexdigest())[:limit]

def calibration_errors(rows,target_year,first_year,recent=None):
    start=max(first_year,target_year-recent)if recent else first_year
    eligible=[r for r in rows if start<=r['season']<target_year]
    chosen=deterministic_sample(eligible,256)
    return [(r['actual']-r['projected'])/max(1.,math.sqrt(max(0.,r['projected'])))/r['uncertainty']for r in chosen],len(eligible),sorted({r['season']for r in eligible})

def evaluate(rows,target_year,first_year):
    test=[r for r in rows if r['season']==target_year]
    old,nlong,years=calibration_errors(rows,target_year,first_year)
    recent,nrecent,recent_years=calibration_errors(rows,target_year,first_year,recent=3)
    if any(r['season']>=target_year for r in rows if first_year<=r['season']<target_year):raise AssertionError('Future calibration data')
    grouped=defaultdict(list)
    for r in test:grouped[r['game']].append((abs(r['actual']-r['projected']),abs(r['actual']-r['baseline']),abs(r['actual_workload']-r['workload'])))
    avg=lambda i:statistics.mean(statistics.mean(x[i]for x in g)for g in grouped.values())if grouped else None
    outcomes=defaultdict(list)
    if len(old)>=50 and len(recent)>=50:
        for r in deterministic_sample(test,128):
            lines=sorted({max(.5,math.floor(r['baseline']+d*math.sqrt(max(0.,r['baseline'])))+.5)for d in (-1,0,1)})
            for line in lines:
                threshold=(line-r['projected'])/max(1.,math.sqrt(max(0.,r['projected'])))/r['uncertainty']
                probs=[max(.05,min(.95,.5+.8*((1+sum(e>threshold for e in residuals))/(len(residuals)+2)-.5)))for residuals in (old,recent)]
                y=int(r['actual']>line)
                outcomes[r['game']].append(tuple((p-y)**2 for p in probs)+tuple(-y*math.log(p)-(1-y)*math.log(1-p)for p in probs))
    mean=lambda i:statistics.mean(statistics.mean(v[i]for v in g)for g in outcomes.values())if outcomes else None
    lb,rb,ll,rl=[mean(i)for i in range(4)]
    enough=len(outcomes)>=20 and len(old)>=50 and len(recent)>=50 and len(years)>len(recent_years)
    return dict(validation_season=target_year,forecast_examples=len(test),stat_validation_games=len(grouped),forecast_mae=avg(0),simple_baseline_mae=avg(1),workload_mae=avg(2),longer_calibration_seasons=years,recent_calibration_seasons=recent_years,longer_calibration_examples=nlong,recent_calibration_examples=nrecent,longer_residual_sample=len(old),recent_residual_sample=len(recent),synthetic_probability_games=len(outcomes),longer_brier=lb,recent_brier=rb,longer_log_loss=ll,recent_log_loss=rl,benefit_supported=bool(enough and lb<rb and ll<=rl),scope='Identical recent-role central forecast; only earlier residual-history window differs. Game-weighted synthetic half-unit lines; bounded outcome-independent samples. No historical sportsbook lines or ROI. Retrospective development evidence, not new independent validation.')

def run(output='history_window_study.json',now=None):
    now=now or datetime.now(timezone.utc);report={'schema':1,'version':VERSION,'generated_utc':now.isoformat(),'status':'Research only; no live model, frozen pick or probability changed','sports':{}}
    # Ten completed seasons plus one warm-up season for prior-year features.
    for sport,last in [('NBA',now.year if now.month>=7 else now.year-1),('NFL',now.year-1 if now.month>=3 else now.year-2)]:
        first=last-9;data={};manifests=[];issues=[]
        with ThreadPoolExecutor(max_workers=3)as pool:
            jobs={year:pool.submit(load_nba,year,now.date().isoformat())if sport=='NBA'else pool.submit(load_nfl,year)for year in range(first-1,last+1)}
            for year,task in jobs.items():
                try:
                    data[year],source=task.result();manifests.extend(source if isinstance(source,list)else[source])
                except Exception as exc:issues.append({'season':year,'error_type':type(exc).__name__,'status':'Historical source missing or invalid; not counted as zero'})
        combined=defaultdict(list);coverage=[]
        for year in range(first,last+1):
            if year not in data or year-1 not in data:continue
            samples,cohort=(nba_samples if sport=='NBA'else nfl_samples)(data[year-1],data[year],year)
            for key,rows in samples.items():combined[key].extend(rows)
            coverage.append(dict(season=year,forecast_examples=sum(map(len,samples.values())),**cohort))
            print(sport,year,'examples',sum(map(len,samples.values())),flush=True)
        results=[]
        for (category,stage),rows in sorted(combined.items()):
            for year in range(last-2,last+1):results.append(dict(category=category,season_stage=stage,**evaluate(rows,year,first)))
        groups=[]
        for key in sorted(combined):
            folds=[r for r in results if(r['category'],r['season_stage'])==key]
            supported=len(folds)==3 and all(r['benefit_supported']for r in folds)
            groups.append(dict(category=key[0],season_stage=key[1],later_seasons=len(folds),seasons_helped=sum(r['benefit_supported']for r in folds),benefit_supported=supported,decision='Longer window warrants further prospective testing; not deployed'if supported else'Keep recent window; broader history has not consistently helped'))
        report['sports'][sport]={'first_requested_season':first,'last_completed_season':last,'warmup_season':first-1,'source_manifest':manifests,'coverage':coverage,'issues':issues,'season_results':results,'category_decisions':groups,'scope':'Ten-season study; historical participants selected deterministically from each prior-season roster, including retired players. Not a complete-league forecast evaluation. Recent workload formulas unchanged; older data is tested as an uncertainty-calibration candidate. No automatic promotion.'}
        target=Path(output);temp=target.with_suffix('.tmp');temp.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n');temp.replace(target)
    return report



def nba_team_games(year,cutoff):
    import pyarrow.parquet as pq
    blob=download(f'https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_nba_player_boxscores/player_box_{year}.parquet',f'nba_{year}.parquet')
    columns=['season','season_type','game_date','game_id','team_id','home_away','team_score','opponent_team_id','opponent_team_score']
    rows=pq.read_table(io.BytesIO(blob),columns=columns).to_pylist();grouped={}
    for r in rows:
        if r['season']!=year or r['season_type']!=2 or str(r['game_date'])>=cutoff:continue
        if r['home_away']not in ('home','away'):continue
        values=(r['team_id'],r['opponent_team_id'],numeric(r['team_score']),numeric(r['opponent_team_score']),str(r['game_date']))
        if any(v is None for v in values)or values[0]==values[1]or min(values[2:4])<0 or values[2]==values[3]:continue
        key=(r['game_id'],r['home_away'])
        if key in grouped and grouped[key]!=values:raise ValueError('Inconsistent NBA final team scores')
        grouped[key]=values
    games=[]
    for (eid,side),home in grouped.items():
        if side!='home':continue
        away=grouped.get((eid,'away'))
        if not away or (home[0],home[1],home[2],home[3],home[4])!=(away[1],away[0],away[3],away[2],away[4]):continue
        games.append(dict(date=date.fromisoformat(home[4]),season=year,home_team=str(home[0]),away_team=str(home[1]),home_score=home[2],away_score=home[3]))
    return games


def team_compare(games,target_year,first_year):
    from background_moneyline import build_elo_model
    predictions=[]
    for start in (first_year,target_year-3):
        earlier=[r for r in games if start<=r['season']<=target_year]
        _,rows=build_elo_model(earlier)
        predictions.append({(r['Date'],r['Home Team'],r['Away Team']):r for r in rows if r['Season']==target_year})
    pairs=[(predictions[0][key],predictions[1][key])for key in predictions[0].keys()&predictions[1].keys()]
    def metrics(index):
        brier=[];loss=[];wins=[]
        for pair in pairs:
            row=pair[index];p=max(.001,min(.999,row['Home Win Probability']));actual=1. if row['Actual Result']=='Home win'else 0. if row['Actual Result']=='Away win'else .5
            brier.append((p-actual)**2);loss.append(-actual*math.log(p)-(1-actual)*math.log(1-p))
            if actual!=.5:wins.append((p>=.5)==bool(actual))
        return dict(brier=statistics.mean(brier)if brier else None,log_loss=statistics.mean(loss)if loss else None,winner_accuracy=statistics.mean(wins)if wins else None)
    long,recent=metrics(0),metrics(1)
    return dict(validation_season=target_year,matched_games=len(pairs),longer=long,recent_three_year=recent,benefit_supported=bool(len(pairs)>=100 and long['brier']<recent['brier']and long['log_loss']<=recent['log_loss']),scope='Raw fixed-parameter Elo; chronological same-date updates. Same later games; different earlier history windows only. No sportsbook prices, injury adjustment, ROI or confidence-shrinkage tuning.')


def add_team_results(report,output='history_window_study.json'):
    for sport,study in report['sports'].items():
        first,last=study['first_requested_season'],study['last_completed_season'];games=[];issues=[]
        if sport=='NBA':
            for year in range(first,last+1):
                try:games.extend(nba_team_games(year,report['generated_utc'][:10]))
                except Exception as exc:issues.append({'season':year,'error_type':type(exc).__name__})
        else:
            try:
                blob=download('https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv','nfl_games.csv')
                for r in csv.DictReader(io.StringIO(blob.decode('utf-8-sig'))):
                    hs,aws=numeric(r.get('home_score')),numeric(r.get('away_score'))
                    if r.get('game_type')!='REG'or hs is None or aws is None or min(hs,aws)<0:continue
                    year=int(r['season'])
                    if first<=year<=last:games.append(dict(date=date.fromisoformat(r['gameday']),season=year,home_team=r['home_team'],away_team=r['away_team'],home_score=hs,away_score=aws))
            except Exception as exc:issues.append({'error_type':type(exc).__name__})
        observed=sorted({g['season']for g in games})
        study['team_result_coverage']={'seasons':observed,'games':len(games),'issues':issues}
        study['moneyline_history_results']=[team_compare(games,y,first)for y in range(last-2,last+1)]if len(observed)==10 else[]
    target=Path(output);temp=target.with_suffix('.tmp');temp.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n');temp.replace(target)
    return report

if __name__=='__main__':add_team_results(run())
