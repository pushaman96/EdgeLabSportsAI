"""Unattended free research and budgeted odds preparation. Never places bets.
Secrets are read only from the runtime environment and never serialized/logged.
"""
import argparse
import csv
import io
import json
import math
import os
import pickle
import re
import statistics
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone,timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo

SPORTS={'NFL':('football/nfl','americanfootball_nfl'),'NBA':('basketball/nba','basketball_nba')}
MARKETS={'NFL':['h2h','totals','player_pass_yds','player_rush_yds','player_anytime_td','player_reception_yds'],
         'NBA':['h2h','player_points','player_assists','player_rebounds','player_threes','player_points_rebounds_assists']}
CAP=0
CACHE=Path('.research_cache')
REPORT=Path('background_research.json')
BUDGET=Path('background_odds_budget.json')
LEDGER=Path('background_projection_history.json')
def utc(v):return datetime.fromisoformat(str(v).replace('Z','+00:00'))
def day(now):return now.astimezone(ZoneInfo('America/Los_Angeles')).date()
def key(v):return re.sub('[^a-z0-9]','',str(v).lower())
def read(path,default):
    try:return json.loads(Path(path).read_text())
    except (OSError,ValueError):return default
def write(path,data):
    target=Path(path);temp=target.with_suffix('.tmp')
    temp.write_text(json.dumps(data,indent=2,allow_nan=False)+'\n');temp.replace(target)
def get(url):
    with urlopen(url,timeout=20)as r:return json.load(r)
def cached(name,ttl,loader):
    CACHE.mkdir(exist_ok=True)
    target=CACHE/(name+'.pkl')
    if target.exists()and datetime.now().timestamp()-target.stat().st_mtime<ttl:
        with target.open('rb')as f:return pickle.load(f)
    value=loader()
    with target.open('wb')as f:pickle.dump(value,f)
    return value
def upcoming(event,now,hours=30):
    try:
        status=event.get('status',{}).get('type',{})
        return status.get('state')=='pre' and not status.get('completed') and now<utc(event['date'])<=now+timedelta(hours=hours) and event.get('season',{}).get('type')==2
    except (ValueError,KeyError,TypeError):return False
def participants(event):
    return {c['homeAway']:c['team']for c in event.get('competitions',[{}])[0].get('competitors',[])if c.get('homeAway')in ('home','away')}
def boards(sport,now):
    all_events={}
    for date in (day(now)+timedelta(days=i) for i in range(4 if sport=='NFL' else 2)):
        data=get('https://site.api.espn.com/apis/site/v2/sports/'+SPORTS[sport][0]+'/scoreboard?dates='+date.strftime('%Y%m%d'))
        for raw in data.get('events',[]):
            e=dict(raw);e.setdefault('season',data.get('season',{}))
            if upcoming(e,now,hours=72 if sport=='NFL' else 30):all_events[e['id']]=e
    return {'events':list(all_events.values())}
def roster(sport,team):
    url='https://site.api.espn.com/apis/site/v2/sports/'+SPORTS[sport][0]+'/teams/'+str(team['id'])+'/roster'
    data=get(url);rows=[]
    for group in data.get('athletes',[]):
        for a in group.get('items',[group]):
            rows.append({'id':str(a.get('id','')),'name':a.get('displayName'),'status':a.get('status',{}).get('name')if isinstance(a.get('status'),dict)else a.get('status'),'position':a.get('position',{}).get('abbreviation')})
    if not rows:raise ValueError('Roster unavailable')
    return rows
def nba_logs(year,athlete):
    from nba_season_prior import fetch_espn_logs
    ttl=1800 if year==datetime.now(timezone.utc).year+int(datetime.now(timezone.utc).month>=7)else 86400
    return cached('nba_'+str(year)+'_'+athlete['id'],ttl,lambda:fetch_espn_logs(year,athlete['id'],athlete['name']))
def nfl_data(year):
    from nfl_prop_model import load_season_stats,csv_url,SCHEDULE_URL
    players=[];teams=[]
    for season in sorted({2023,2024,2025,year-1,year}):
        for kind,target in (('player',players),('team',teams)):
            target.extend(cached('nfl_scoring_v2_'+kind+'_'+str(season),1800 if season==year else 86400,lambda k=kind,y=season:load_season_stats(k,y)))
    return {'players':players,'teams':teams,'schedule':csv_url(SCHEDULE_URL),'season':year,'retrieved':datetime.now(timezone.utc).isoformat()}
def prepare(now=None):
    now=now or datetime.now(timezone.utc)
    report={'schema':1,'generated_utc':now.isoformat(),'status':'Free research; projections are not betting recommendations','odds_setup':'Automatic odds spending disabled; use an explicit app load button for prices','sports':{},'issues':[]}
    history=read(LEDGER,{'schema':1,'records':[]});known={r['id']for r in history['records']}
    for sport in SPORTS:
        item={'status':'Pending','projections':[],'issues':[]};report['sports'][sport]=item
        try:
            board=boards(sport,now);item['scoreboard']=board
            teams={str(t['id']):t for e in board['events']for t in participants(e).values()}
            rosters={}
            with ThreadPoolExecutor(max_workers=6)as pool:
                tasks={tid:pool.submit(roster,sport,t)for tid,t in teams.items()}
                for tid,task in tasks.items():
                    try:rosters[tid]=task.result()
                    except Exception:item['issues'].append('Roster unavailable: '+teams[tid]['displayName'])
            item['rosters']=rosters
            # Current availability evidence is refreshed independently of prices.
            try:item['injuries']=get('https://site.api.espn.com/apis/site/v2/sports/'+SPORTS[sport][0]+'/injuries')
            except Exception:item['issues'].append('Current injury source unavailable')
            years={int(e['season']['year'])for e in board['events']}
            for year in sorted(years):
                relevant=[e for e in board['events']if int(e['season']['year'])==year]
                if sport=='NFL':
                    data=nfl_data(year)
                    from nfl_season_prior import indexes,estimate
                    idx=indexes(data['players'],data['teams'])
                    from nfl_scoring_models import td_index,td_estimate,total_estimate,score_games,td_validate,total_validate
                    td_idx=td_index(data['players']);scored_games=score_games(data['schedule'])
                    item['Scoring model validation']={'Anytime touchdown':td_validate(data['players']),'Game total points':{k:v for k,v in total_validate(data['schedule']).items()if k!='residuals'}}
                    if os.environ.get('ODDS_API_KEY'):
                        try:
                            from nfl_prop_model import load_prop_research
                            cached('nfl_model_opportunity_v3_'+str(year),1800,lambda:load_prop_research(year))
                        except Exception:item['issues'].append('Full NFL validation unavailable; quote analysis may remain Pass')
                    aliases={'LAR':'LA','WSH':'WAS','JAC':'JAX'}
                else:
                    jobs={a['id']:a for tid,rs in rosters.items()for a in rs if a.get('id')and a.get('name')}
                    logs={}
                    with ThreadPoolExecutor(max_workers=6)as pool:
                        tasks={pid:pool.submit(lambda a:sum([nba_logs(y,a)for y in (year-1,year)],[]),a)for pid,a in jobs.items()}
                        for pid,task in tasks.items():
                            try:logs[pid]=task.result()
                            except Exception:item['issues'].append('Player history incomplete: '+jobs[pid]['name'])
                    from nba_season_prior import season_projection
                    if os.environ.get('ODDS_API_KEY'):
                        try:
                            from nba_prop_model import load_data,reference_players
                            named={teams[tid]['displayName']:rs for tid,rs in rosters.items()}
                            targets=tuple((a['id'],a['name'])for a in jobs.values())
                            cached('nba_model_'+str(year),1800,lambda:load_data(year,targets,reference_players(named)))
                        except Exception:item['issues'].append('Full NBA validation unavailable; quote analysis may remain Pass')
                for event in relevant:
                    sides=participants(event)
                    if set(sides)!= {'home','away'}:continue
                    start=utc(event['date']);cutoff=day(start).isoformat()
                    if sport=='NFL':
                        home=aliases.get(sides['home']['abbreviation'],sides['home']['abbreviation']);away=aliases.get(sides['away']['abbreviation'],sides['away']['abbreviation'])
                        games=[g for g in data['schedule']if g.get('game_type')=='REG'and int(g['season'])==year and g['home_team']==home and g['away_team']==away and g['gameday']==cutoff]
                        if len(games)!=1:item['issues'].append('Unique schedule unavailable: '+event['id']);continue
                        week=int(games[0]['week'])
                        scoring=total_estimate(dict(games[0],season=year),scored_games)
                        if scoring:
                            identity='|'.join((sport,event['id'],'total','Game total points','NFL scoring total preparation v1'))
                            row={'id':identity,'sport':sport,'event_id':event['id'],'game':event.get('name'),'player':event.get('name'),'category':'Game total points','model':'NFL scoring total preparation v1','published_utc':now.isoformat(),'starts_utc':event['date'],'projection':scoring['projected'],'simple_baseline':scoring['baseline'],'workload':None,'role_uncertain':True,'result':'Pending','status':'Scoring research; no injury/weather adjustment or betting line implied'}
                            item['projections'].append(row)
                            if identity not in known and now<start:history['records'].append(row);known.add(identity)
                    for side,team in sides.items():
                        for athlete in rosters.get(str(team['id']),[]):
                            if str(athlete.get('status')).lower()!='active':continue
                            categories=[('Points','PTS'),('Assists','AST'),('Rebounds','REB'),('Three-pointers made','FG3M'),('PRA','PRA')]if sport=='NBA'else [('Passing yards','player_pass_yds')]if athlete['position']=='QB'else [('Rushing yards','player_rush_yds')]if athlete['position']in ('RB','HB','FB')else []
                            if sport=='NFL'and athlete['position']in ('RB','HB','FB','WR','TE'):categories.append(('Receiving yards','player_reception_yds'))
                            if sport=='NFL'and athlete['position']in ('QB','RB','HB','FB','WR','TE'):categories.append(('Anytime touchdown','anytime'))
                            for label,field in categories:
                                if sport=='NBA':
                                    f=season_projection(logs.get(athlete['id'],[]),field,year,str(team['id']),cutoff)
                                    model='NBA season-prior preparation v1';base=f['projected']if f else None;volume=f['minutes']if f else None;uncertain=f['role_uncertain']if f else True
                                else:
                                    code=aliases.get(team['abbreviation'],team['abbreviation']);opp=away if side=='home'else home
                                    ids={r['player_id']for r in data['players']if key(r['player_display_name'])==key(athlete['name'])}
                                    f=(td_estimate(next(iter(ids)),year,week,code,td_idx)if field=='anytime'else estimate(next(iter(ids)),year,week,code,opp,field,idx))if len(ids)==1 else None
                                    model='NFL offensive TD preparation v1'if field=='anytime'else'NFL season-prior preparation v1';base=f['projected']if f else None;volume=f['opportunities']if f else None;uncertain=(f['role_uncertain']or f.get('coverage_gap',False))if f else True
                                if base is None:continue
                                identity='|'.join((sport,event['id'],athlete['id'],label,model))
                                row={'id':identity,'sport':sport,'event_id':event['id'],'game':event.get('name'),'player':athlete['name'],'category':label,'model':model,'published_utc':now.isoformat(),'starts_utc':event['date'],'projection':base,'simple_baseline':f.get('baseline'),'workload':volume,'role_uncertain':uncertain,'result':'Pending','status':'Research projection only; no line, selection or win probability. Availability/validation gates still required.'}
                                item['projections'].append(row)
                                if identity not in known and now<start:history['records'].append(row);known.add(identity)
                item['status']='Prepared; review availability and category validation before any pick'
            if not years:item['status']='No upcoming regular-season games in next '+('72' if sport=='NFL' else '30')+' hours'
        except Exception:
            item['status']='Research source/model unavailable; no substitute forecasts invented'
            item['issues'].append('Preparation incomplete; retry on next scheduled run')
    write(REPORT,report);write(LEDGER,history)
    write('background_status.json',{'generated_utc':now.isoformat(),'odds_setup':report['odds_setup'],'sports':{sport:{'status':item['status'],'upcoming_games':len(item.get('scoreboard',{}).get('events',[])),'prepared_projections':len(item['projections']),'issues':item['issues']}for sport,item in report['sports'].items()}})
    return report

def reserve(now=None,run_id=None,has_key=None):
    """Automatic provider requests are disabled, even with a configured key."""
    now=now or datetime.now(timezone.utc)
    budget=read(BUDGET,{'schema':1,'days':{}})
    account=budget['days'].setdefault(str(day(now)),{'cap':0,'reserved':0,'requests':[]})
    account['cap']=0
    account['setup_status']='Automatic odds spending disabled. Load odds only with an explicit app button.'
    write(BUDGET,budget)
    write('background_pending.json',[])
    return []
def append_records(path,rows):
    data=read(path,{'schema':1,'records':[]});existing={r['id']for r in data['records']}
    data['records'].extend(r for r in rows if r['id']not in existing)
    write(path,data)
def model_rows(sport,event,board,now):
    # Reuse production gates. No invented lines, probabilities or relaxed tests.
    if sport=='NBA':
        from nba_prop_model import current_roster_nba,load_data,reference_players,reviews,normalized
        from nba_tools import load_nba_injuries
        teams={t['displayName']:t['id']for e in board['events']for t in participants(e).values()}
        roster={name:current_roster_nba(tid)for name,tid in teams.items()}
        names={normalized(o.get('description',''))for b in event.get('bookmakers',[])for m in b.get('markets',[])for o in m.get('outcomes',[])}
        targets=tuple((p['id'],p['name'])for rs in roster.values()for p in rs if normalized(p['name'])in names)
        year=int(board['events'][0]['season']['year'])
        data=cached('nba_model_'+str(year),1800,lambda:load_data(year,targets,reference_players(roster)))
        from nba_game_context import load_context
        context=load_context([event],board,now=now)
        return reviews([event],board,data,load_nba_injuries(),roster,now=now,context=context)
    from nfl_prop_model import load_prop_research,injury_context,current_roster,prop_reviews
    year=int(board['events'][0]['season']['year']);data=cached('nfl_model_opportunity_v3_'+str(year),1800,lambda:load_prop_research(year))
    roster={t['displayName']:current_roster(t['id'])for e in board['events']for t in participants(e).values()}
    # Additional role sources are optional evidence; absent rows stay unknown.
    return prop_reviews(event,board,data,injury_context(),roster,now=now)
def moneyline_rows(sport,event,board,now):
    from background_moneyline import build_elo_model,test_probability_adjustment,shrink_probability,expected_home_win
    if sport=='NFL':
        from nfl_prop_model import csv_url,SCHEDULE_URL
        games=[]
        for r in csv_url(SCHEDULE_URL):
            try:
                when=datetime.fromisoformat(r['gameday']).date();hs=float(r['home_score']);aws=float(r['away_score'])
                if r.get('game_type')!='REG'or when>=day(now)or not all(math.isfinite(v)and v>=0 for v in (hs,aws)):continue
                games.append(dict(date=when,season=int(r['season']),home_team=r['home_team'],away_team=r['away_team'],home_score=hs,away_score=aws))
            except (ValueError,TypeError,KeyError):continue
        aliases={'LAR':'LA','WSH':'WAS'}
    else:
        from nba_moneyline_research import load_history
        year=int(board['events'][0]['season']['year'])
        games=[g for g in load_history(year)['games']if g['date']<day(now)]
        aliases={'NY':'NYK','GS':'GSW','NO':'NOP','SA':'SAS','UTAH':'UTA','WSH':'WAS'}
    if len(games)<100:return []
    nba_history_eligible=False;nba_history_basis=None
    if sport=='NBA':
        from nba_moneyline_research import history_ready
        nba_history_eligible,nba_history_basis=history_ready(games,year,day(now))
    ratings,predictions=build_elo_model(games);validation=test_probability_adjustment(predictions)
    strength=validation['strength']if validation else 1
    models={}
    for source in board['events']:
        sides=participants(source)
        if set(sides)!= {'home','away'}:continue
        home,away=sides['home'],sides['away']
        hc=aliases.get(home['abbreviation'],home['abbreviation']);ac=aliases.get(away['abbreviation'],away['abbreviation'])
        cutoff=max(g['date']for g in games)
        if hc not in ratings or ac not in ratings:continue
        models[home['displayName'],away['displayName']]={'probability':shrink_probability(expected_home_win(ratings[hc],ratings[ac]),strength),'eligible':source.get('season',board.get('season',{})).get('type')==2 and (nba_history_eligible if sport=='NBA'else 0<=(day(now)-cutoff).days<=30),'cutoff':cutoff.isoformat(),'history_basis':nba_history_basis,'validation':{'passed':bool(validation and validation['improvement']>=0),'calibration_examples':validation['calibration_games']if validation else 0,'validation_games':validation['evaluation_games']if validation else 0,'scope':'Chronological Elo shrinkage comparison against the unadjusted model; not sportsbook returns'},'injury_verified':False,'injury_reason':'Background Elo has no numerical injury adjustment; review current availability'}
    from sportsbook_tools import moneyline_reviews
    rows=moneyline_reviews([event],models,now=now,sport=sport,include_passes=True)
    for row in rows:row['Reason']='Higher estimated historical Elo win probability; payout does not choose the team. Availability/replacement effects are not numerically modeled; experimental.'
    return rows
def execute(now=None):
    """Discard old reservations without making any provider request."""
    write('background_pending.json',[])
    return []
def projection_summary(records,sport):
    groups={}
    for r in records:
        if r.get('sport')!=sport or r.get('result')!='Measured':continue
        actual,base=r.get('actual'),r.get('simple_baseline')
        projected=r.get('projection')
        if not all(isinstance(v,(int,float))and math.isfinite(v)for v in (actual,base,projected)):continue
        groups.setdefault(r['category'],{}).setdefault(r['event_id'],[]).append((abs(actual-projected),abs(actual-base)))
    output=[]
    for category,games in sorted(groups.items()):
        def avg(i):return statistics.mean(statistics.mean(v[i]for v in values)for values in games.values())
        forecast,base=avg(0),avg(1)
        output.append({'Category':category,'Matched forecasts':sum(len(v)for v in games.values()),'Distinct games':len(games),'Projection MAE':forecast,'Simple baseline MAE':base,'Projection minus baseline MAE':forecast-base,'Status':'Descriptive prospective comparison; no automatic promotion'})
    return output

def review_projections(now=None):
    now=now or datetime.now(timezone.utc);data=read(LEDGER,{'schema':1,'records':[]});cache={}
    for row in data['records']:
        if row['result']!='Pending'or utc(row['starts_utc'])>=now:continue
        try:
            k=(row['sport'],row['event_id'])
            if k not in cache:cache[k]=get('https://site.api.espn.com/apis/site/v2/sports/'+SPORTS[k[0]][0]+'/summary?event='+k[1])
            from pick_history import grade_record
            fake=dict(row,result='Pending',line=0,direction='Over',odds=-110)
            graded=grade_record(fake,cache[k])
            if graded.get('result')not in ('Win','Loss','Push'):continue
            actual=graded.get('actual')
            if not isinstance(actual,(int,float))or not math.isfinite(actual):continue
            row.update(result='Measured',actual=actual,actual_workload=graded.get('actual_opportunities'),absolute_error=abs(actual-row['projection']),graded_utc=now.isoformat())
            baseline=row.get('simple_baseline')
            if isinstance(baseline,(int,float))and math.isfinite(baseline):row['baseline_absolute_error']=abs(actual-baseline)
        except Exception:continue
    write(LEDGER,data)
    # Compare learning only where genuinely frozen paired forecasts exist.
    from paired_forecasts import summary
    records=read('published_picks.json',{'records':[]})['records']+read('analyzed_forecasts.json',{'records':[]})['records']
    write('background_validation.json',{'generated_utc':now.isoformat(),'paired':{s:summary(records,s)for s in SPORTS},'projection_baselines':{s:projection_summary(data['records'],s)for s in SPORTS},'promotion_status':'No automatic model promotion. Later chronological validation is required; existing experimental guards remain separate.'})
def render(sport):
    import streamlit as st
    from runtime_health import snapshot
    report=read('background_status.json',{})
    with st.expander('Background research — free preparation only'):
        st.write('Last research update (UTC): '+str(report.get('generated_utc','Not run yet')))
        item=report.get('sports',{}).get(sport,{})
        if st.toggle('Load prepared research projections',value=False,key='load_background_projections_'+sport):
            def dashboard(data):
                fields=('game','player','category','projection','simple_baseline','workload','role_uncertain','published_utc')
                return {'generated_utc':data.get('generated_utc'),'sports':{league:{'status':part.get('status'),'issues':part.get('issues',[]),'projections':[{k:r.get(k)for k in fields}for r in part.get('projections',[])]}for league,part in data.get('sports',{}).items()}}
            expanded=snapshot(REPORT,'background-dashboard-v1',dashboard,{})
            item=expanded.get('sports',{}).get(sport,item)
        else:st.caption('Prepared projections: '+str(item.get('prepared_projections','Not reported'))+'. Detailed data loads only when requested; background research continues.')
        st.write(item.get('status','Waiting for first background research run'))
        if item.get('issues'):st.write(item['issues'])
        st.caption('Preparation uses free sources. Research projections have no sportsbook win probability and are not picks. The scheduled job runs even when this app is closed; GitHub schedules can be delayed.')
        if item.get('projections'):
            st.dataframe([{k:r.get(k)for k in ('game','player','category','projection','simple_baseline','workload','role_uncertain','published_utc')}for r in item['projections']],hide_index=True,use_container_width=True)
        budget=read(BUDGET,{'days':{}}).get('days',{}).get(str(day(datetime.now(timezone.utc))),{})
        st.write('Automated credits reserved today, shared NFL + NBA: '+str(budget.get('reserved',0))+' / '+str(CAP))
        st.write(budget.get('setup_status',report.get('odds_setup','Background prices not configured')))
        st.caption('Automatic odds requests are disabled for NFL and NBA. Only an explicit app load button can request new odds. Free research, live observations and grading continue without odds credits.')
        validation=read('background_validation.json',{})
        if validation.get('paired',{}).get(sport):st.dataframe(validation['paired'][sport],hide_index=True,use_container_width=True)
        if validation.get('projection_baselines',{}).get(sport):
            st.write('**Matched projection versus simple baseline**')
            st.dataframe(validation['projection_baselines'][sport],hide_index=True,use_container_width=True)
        measured=[r for r in read(LEDGER,{'records':[]})['records']if r['sport']==sport and r.get('result')=='Measured']
        if measured:
            st.write('**Projection-only research results — separate from pick accuracy**')
            groups={}
            for r in measured:groups.setdefault(r['category'],{}).setdefault(r['event_id'],[]).append(r['absolute_error'])
            st.dataframe([{'Category':c,'Distinct games':len(g),'Game-weighted mean absolute error':statistics.mean(statistics.mean(v)for v in g.values())}for c,g in groups.items()],hide_index=True,use_container_width=True)
        st.caption(validation.get('promotion_status','No automatic model promotion or accuracy guarantee.'))
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('phase',choices=['prepare','reserve','execute','review','smoke']);args=parser.parse_args()
    if args.phase=='prepare':prepare();review_projections()
    elif args.phase=='reserve':reserve()
    elif args.phase=='execute':execute()
    elif args.phase=='review':review_projections()
    else:
        # Free connectivity check on code pushes, no odds or model-history requests.
        now=datetime.now(timezone.utc);write('background_connectivity.json',{'checked_utc':now.isoformat(),'events':{s:len(boards(s,now)['events'])for s in SPORTS}})


