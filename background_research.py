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
MARKETS={'NFL':['h2h','totals','player_pass_yds','player_rush_yds','player_anytime_td'],
         'NBA':['h2h','player_points','player_assists','player_rebounds','player_threes','player_points_rebounds_assists']}
CAP=8
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
def upcoming(event,now):
    try:
        status=event.get('status',{}).get('type',{})
        return status.get('state')=='pre' and not status.get('completed') and now<utc(event['date'])<=now+timedelta(hours=30) and event.get('season',{}).get('type')==2
    except (ValueError,KeyError,TypeError):return False
def participants(event):
    return {c['homeAway']:c['team']for c in event.get('competitions',[{}])[0].get('competitors',[])if c.get('homeAway')in ('home','away')}
def boards(sport,now):
    all_events={}
    for date in (day(now),day(now)+timedelta(days=1)):
        data=get('https://site.api.espn.com/apis/site/v2/sports/'+SPORTS[sport][0]+'/scoreboard?dates='+date.strftime('%Y%m%d'))
        for raw in data.get('events',[]):
            e=dict(raw);e.setdefault('season',data.get('season',{}))
            if upcoming(e,now):all_events[e['id']]=e
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
            target.extend(cached('nfl_'+kind+'_'+str(season),1800 if season==year else 86400,lambda k=kind,y=season:load_season_stats(k,y)))
    return {'players':players,'teams':teams,'schedule':csv_url(SCHEDULE_URL),'season':year,'retrieved':datetime.now(timezone.utc).isoformat()}
def prepare(now=None):
    now=now or datetime.now(timezone.utc)
    report={'schema':1,'generated_utc':now.isoformat(),'status':'Free research; projections are not betting recommendations','odds_setup':'GitHub Actions ODDS_API_KEY secret required for background prices; Streamlit secrets are separate','sports':{},'issues':[]}
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
                    if os.environ.get('ODDS_API_KEY'):
                        try:
                            from nfl_prop_model import load_prop_research
                            cached('nfl_model_'+str(year),1800,lambda:load_prop_research(year))
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
                    for side,team in sides.items():
                        for athlete in rosters.get(str(team['id']),[]):
                            if str(athlete.get('status')).lower()!='active':continue
                            categories=[('Points','PTS'),('Assists','AST'),('Rebounds','REB'),('Three-pointers made','FG3M')]if sport=='NBA'else [('Passing yards','player_pass_yds')]if athlete['position']=='QB'else [('Rushing yards','player_rush_yds')]if athlete['position']in ('RB','HB','FB')else []
                            for label,field in categories:
                                if sport=='NBA':
                                    f=season_projection(logs.get(athlete['id'],[]),field,year,str(team['id']),cutoff)
                                    model='NBA season-prior preparation v1';base=f['projected']if f else None;volume=f['minutes']if f else None;uncertain=f['role_uncertain']if f else True
                                else:
                                    code=aliases.get(team['abbreviation'],team['abbreviation']);opp=away if side=='home'else home
                                    ids={r['player_id']for r in data['players']if key(r['player_display_name'])==key(athlete['name'])}
                                    f=estimate(next(iter(ids)),year,week,code,opp,field,idx)if len(ids)==1 else None
                                    model='NFL season-prior preparation v1';base=f['projected']if f else None;volume=f['opportunities']if f else None;uncertain=(f['role_uncertain']or f['coverage_gap'])if f else True
                                if base is None:continue
                                identity='|'.join((sport,event['id'],athlete['id'],label,model))
                                row={'id':identity,'sport':sport,'event_id':event['id'],'game':event.get('name'),'player':athlete['name'],'category':label,'model':model,'published_utc':now.isoformat(),'starts_utc':event['date'],'projection':base,'simple_baseline':f.get('baseline'),'workload':volume,'role_uncertain':uncertain,'result':'Pending','status':'Research projection only; no line, selection or win probability. Availability/validation gates still required.'}
                                item['projections'].append(row)
                                if identity not in known and now<start:history['records'].append(row);known.add(identity)
                item['status']='Prepared; review availability and category validation before any pick'
            if not years:item['status']='No upcoming regular-season games in next 30 hours'
        except Exception:
            item['status']='Research source/model unavailable; no substitute forecasts invented'
            item['issues'].append('Preparation incomplete; retry on next scheduled run')
    write(REPORT,report);write(LEDGER,history)
    write('background_status.json',{'generated_utc':now.isoformat(),'odds_setup':report['odds_setup'],'sports':{sport:{'status':item['status'],'upcoming_games':len(item.get('scoreboard',{}).get('events',[])),'prepared_projections':len(item['projections']),'issues':item['issues']}for sport,item in report['sports'].items()}})
    return report

def reserve(now=None,run_id=None,has_key=None):
    now=now or datetime.now(timezone.utc);run_id=run_id or os.environ.get('GITHUB_RUN_ID','local')
    has_key=bool(os.environ.get('ODDS_API_KEY'))if has_key is None else has_key
    budget=read(BUDGET,{'schema':1,'days':{}})
    today=str(day(now));account=budget['days'].setdefault(today,{'cap':CAP,'reserved':0,'requests':[]})
    write('background_pending.json',[])
    # Re-running a job never reuses an old reservation for another HTTP request.
    if any(r['run_id']==run_id for r in account['requests']):return []
    if not has_key:
        account['setup_status']='Missing GitHub Actions ODDS_API_KEY; free preparation still runs'
        write(BUDGET,budget);return []
    remaining=CAP-account['reserved'];candidates=[]
    report=read(REPORT,{})
    if (now-utc(report.get('generated_utc','2000-01-01T00:00:00Z'))).total_seconds()>3600:return []
    for sport,item in report.get('sports',{}).items():
        if sport=='NFL'and day(now).weekday()not in (6,0,3):continue
        if len(MARKETS[sport])>remaining:continue
        try:
            # Provider's event-list endpoint is free; no odds are loaded here.
            listing=get('https://api.the-odds-api.com/v4/sports/'+SPORTS[sport][1]+'/events?'+urlencode({'apiKey':os.environ['ODDS_API_KEY']}))
        except Exception:
            account['setup_status']='Event discovery unavailable; no odds request reserved';continue
        for source in item.get('scoreboard',{}).get('events',[]):
            if not upcoming(source,now):continue
            start=utc(source['date'])
            if not timedelta(minutes=10)<start-now<=timedelta(hours=3):continue
            sides=participants(source)
            if set(sides)!= {'home','away'}:continue
            matched=[e for e in listing if e.get('home_team')==sides['home']['displayName']and e.get('away_team')==sides['away']['displayName']and abs((utc(e['commence_time'])-start).total_seconds())<3600]
            if len(matched)!=1:continue
            event=matched[0]
            if any(r['event_id']==event['id']for r in account['requests']):continue
            candidates.append((start,sport,event,source['id']))
    chosen=[]
    for _,sport,event,eid in sorted(candidates,key=lambda r:(r[0],r[1])):
        cost=len(MARKETS[sport])
        if cost>CAP-account['reserved']:continue
        request={'run_id':run_id,'sport':sport,'event_id':event['id'],'espn_id':eid,'markets':MARKETS[sport],'reserved_cost':cost,'reserved_utc':now.isoformat(),'event':event,'status':'Reserved before HTTP request'}
        account['requests'].append(request);account['reserved']+=cost;chosen.append(request)
    account['setup_status']='Configured; budget is shared across both sports, automatic background requests only'
    write(BUDGET,budget);write('background_pending.json',chosen)
    return chosen
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
    year=int(board['events'][0]['season']['year']);data=cached('nfl_model_'+str(year),1800,lambda:load_prop_research(year))
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
        from nba_tools import load_nba_saved_history
        year=int(board['events'][0]['season']['year'])
        games=[g for g in load_nba_saved_history(year)['games']if g['date']<day(now)]
        aliases={'NY':'NYK','GS':'GSW','NO':'NOP','SA':'SAS','UTAH':'UTA','WSH':'WAS'}
    if len(games)<100:return []
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
        models[home['displayName'],away['displayName']]={'probability':shrink_probability(expected_home_win(ratings[hc],ratings[ac]),strength),'eligible':0<=(day(now)-cutoff).days<=30,'cutoff':cutoff.isoformat(),'injury_verified':False,'injury_reason':'Background Elo has no numerical injury adjustment; review current availability'}
    from sportsbook_tools import moneyline_reviews
    rows=moneyline_reviews([event],models,now=now,sport=sport,include_passes=True)
    for row in rows:row['Reason']='Historical Elo price comparison. Availability/replacement effects are not numerically modeled; experimental.'
    return rows
def execute(now=None):
    now=now or datetime.now(timezone.utc);pending=read('background_pending.json',[])
    report=read(REPORT,{})
    budget=read(BUDGET,{'days':{}});account=budget['days'].get(str(day(now)),{})
    quotes=read('background_quotes.json',{'schema':1,'events':[]})
    for request in pending:
        if request.get('run_id')!=os.environ.get('GITHUB_RUN_ID','local'):continue
        try:
            check_time=datetime.now(timezone.utc)
            if utc(request['event']['commence_time'])<=check_time:request['status']='Skipped: game started';continue
            from pick_history import verified_pregame_start
            fresh_board=boards(request['sport'],check_time)
            fresh_source=next(e for e in fresh_board['events']if e['id']==request['espn_id'])
            verified_pregame_start(fresh_source,request['event']['commence_time'],check_time)
            # Exactly one request per durable reservation; no retry on ambiguous failure.
            params={'apiKey':os.environ['ODDS_API_KEY'],'regions':'us','markets':','.join(request['markets']),'oddsFormat':'american','dateFormat':'iso'}
            url='https://api.the-odds-api.com/v4/sports/'+SPORTS[request['sport']][1]+'/events/'+request['event_id']+'/odds?'+urlencode(params)
            with urlopen(url,timeout=25)as response:
                event=json.load(response);request['actual_cost']=response.headers.get('x-requests-last');request['remaining']=response.headers.get('x-requests-remaining')
            request['status']='Prices loaded'
            # Freeze after the HTTP response, not before it; do not backdate.
            quote_time=datetime.now(timezone.utc)
            quotes['events'].append({'sport':request['sport'],'retrieved_utc':quote_time.isoformat(),'event':event})
            sport=request['sport'];board=fresh_board
            from pick_history import verified_pregame_start,make_record
            source=next(e for e in board['events']if e['id']==request['espn_id'])
            start=verified_pregame_start(source,event['commence_time'],quote_time)
            rows=[]
            try:rows.extend(model_rows(sport,event,board,quote_time))
            except Exception:request['forecast_status']='Player model source/validation unavailable; prices saved without fabricated picks'
            try:rows.extend(moneyline_rows(sport,event,board,datetime.now(timezone.utc)))
            except Exception:request['moneyline_status']='Moneyline source unavailable'
            frozen=[];recommendations={};now_freeze=datetime.now(timezone.utc)
            # Recheck the actual current time after slow history/model work.
            verified_pregame_start(source,event['commence_time'],now_freeze)
            for row in rows:
                try:
                    row=dict(row,Sport=sport,**{'Odds scheduled start UTC':event['commence_time'],'ESPN scheduled start UTC':source['date']})
                    r=make_record(row,source['id'],start,now_freeze,strategy='Analysis');r.update(season_type='Regular season',record_purpose='Analyzed forecast; not official pick score',forecast_decision=row['Decision'])
                    frozen.append(r)
                    if row.get('Decision')!='Pass':
                        identity=(row['Player'],row['Category'])
                        recommendations.setdefault(identity,[]).append(row)
                except (ValueError,TypeError,KeyError):continue
            originals=[]
            for values in recommendations.values():
                if len({r['Selection']for r in values})!=1:continue
                row=max(values,key=lambda r:float(r['Estimated win %']))
                r=make_record(row,source['id'],start,now_freeze);r['season_type']='Regular season';originals.append(r)
            append_records('analyzed_forecasts.json',frozen);append_records('published_picks.json',originals)
            request['saved_analysis']=len(frozen);request['saved_originals']=len(originals)
        except Exception:
            request['status']='Request/source/model unavailable or pregame window closed; reservation retained, no automatic retry'
        finally:
            for r in account.get('requests',[]):
                if r['event_id']==request['event_id']and r['run_id']==request['run_id']:r.update({k:v for k,v in request.items()if k!='event'})
    # Latest snapshots only; frozen predictions live in their existing ledgers.
    quotes['events']=quotes['events'][-40:]
    write('background_quotes.json',quotes);write(BUDGET,budget)
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
    report=read(REPORT,{})
    with st.expander('Background research — readiness and daily credit budget'):
        st.write('Last research update (UTC): '+str(report.get('generated_utc','Not run yet')))
        item=report.get('sports',{}).get(sport,{})
        st.write(item.get('status','Waiting for first background research run'))
        if item.get('issues'):st.write(item['issues'])
        st.caption('Preparation uses free sources. Research projections have no sportsbook win probability and are not picks. The scheduled job runs even when this app is closed; GitHub schedules can be delayed.')
        if item.get('projections'):
            st.dataframe([{k:r.get(k)for k in ('game','player','category','projection','simple_baseline','workload','role_uncertain','published_utc')}for r in item['projections']],hide_index=True,use_container_width=True)
        budget=read(BUDGET,{'days':{}}).get('days',{}).get(str(day(datetime.now(timezone.utc))),{})
        st.write('Automated credits reserved today, shared NFL + NBA: '+str(budget.get('reserved',0))+' / '+str(CAP))
        st.write(budget.get('setup_status',report.get('odds_setup','Background prices not configured')))
        st.caption('Reservations are saved before requests and retained after failures. The cap covers background automation; manually requested add-ons spend extra. Eight credits generally cover one game with the full preset, not every game.')
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
