"""Experimental minutes x per-minute NBA props with chronological validation.
No current-season aggregates are used to predict earlier games.
"""
import math
import re
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

MODEL = 'NBA season-prior minutes-rate v2'
from nba_season_prior import season_projection, season_year, fetch_espn_logs
MARKETS = {'player_points':('Points','PTS'),'player_rebounds':('Rebounds','REB'),'player_assists':('Assists','AST'),'player_threes':('Three-pointers made','FG3M')}


def number(value):
    try:
        value=float(value)
        return value if math.isfinite(value) else None
    except (ValueError,TypeError):
        return None


def normalized(value):
    return re.sub('[^a-z0-9]','',str(value).lower())


def day(value):
    text=str(value)
    try:return datetime.fromisoformat(text.replace('Z','+00:00')).date()
    except ValueError:return datetime.strptime(text,'%b %d, %Y').date()


def normalize_logs(rows, year):
    result=[];seen=set()
    for r in rows:
        if str(r.get('SEASON_ID')) != '2'+str(year-1):
            raise ValueError('NBA player log season/type mismatch')
        if r.get('WL') not in ('W','L'):continue
        minutes=number(r.get('MIN'))
        if minutes is None or minutes<=0:continue
        fields={k:number(r.get(k)) for k in ('PTS','REB','AST','FG3M')}
        if any(v is None or v<0 for v in fields.values()):continue
        identity=(str(r['GAME_ID']),str(r['PLAYER_ID']))
        if identity in seen:raise ValueError('Duplicate NBA player/game')
        seen.add(identity)
        result.append(dict(player=str(r['PLAYER_ID']),name=r['PLAYER_NAME'],team=str(r['TEAM_ID']),date=day(r['GAME_DATE']).isoformat(),game=str(r['GAME_ID']),minutes=minutes,season=year,source='NBA.com regular-season game logs',**fields))
    return sorted(result,key=lambda r:(r['date'],r['game'],r['player']))


def projection(history, field):
    recent=history[-12:]
    if len(recent)<8:return None
    minute_values=[r['minutes'] for r in recent]
    minutes=max(5.,min(40.,.65*statistics.mean(minute_values[-5:])+.35*statistics.mean(minute_values)))
    total_minutes=sum(minute_values)
    rate=sum(r[field] for r in recent)/total_minutes
    return minutes*rate,minutes,statistics.mean(r[field] for r in recent[-8:])


def research(logs, cutoff):
    """Earlier errors calibrate; later games validate each season-stage cohort."""
    older=[r for r in logs if r['date']<str(cutoff)]
    dates=sorted({r['date'] for r in older})
    split=dates[int(.65*len(dates))] if dates else str(cutoff)
    history=defaultdict(list);players=defaultdict(list);errors=defaultdict(list);validation=defaultdict(lambda:defaultdict(list))
    cohort_errors=defaultdict(list);cohort_validation=defaultdict(lambda:defaultdict(list))
    for r in sorted(older,key=lambda r:(r['date'],r['game'],r['player'])):
        h=history[r['player'],r['team']]
        before=[x for x in h if x['date']<r['date']]
        for _,field in MARKETS.values():
            detail=season_projection(players[r['player']],field,season_year(r),r['team'],r['date'])
            f=(detail['projected'],detail['minutes'],detail['baseline']) if detail else projection(before,field)
            if not f:continue
            forecast,minutes,baseline=f
            cohort=detail['cohort'] if detail else 'Established season'
            scale=detail['uncertainty'] if detail else 1.
            error=(r[field]-forecast)/max(1.,math.sqrt(forecast))/scale
            if r['date']<split:
                errors[field].append(error);cohort_errors[field,cohort].append(error)
            else:
                pair=(abs(r[field]-forecast),abs(r[field]-baseline))
                validation[field][r['game']].append(pair)
                if not detail or not detail['role_uncertain']:cohort_validation[field,cohort][r['game']].append(pair)
        h.append(r);players[r['player']].append(r)
    def report(label,groups,calibration):
        fm=statistics.mean(statistics.mean(v[0] for v in values) for values in groups.values()) if groups else None
        bm=statistics.mean(statistics.mean(v[1] for v in values) for values in groups.values()) if groups else None
        return dict(category=label,validation_games=len(groups),calibration_examples=len(calibration),forecast_mae=fm,baseline_mae=bm,passed=bool(len(groups)>=20 and len(calibration)>=50 and fm<bm),split_date=split)
    reports={field:report(label,validation[field],errors[field]) for label,field in MARKETS.values()}
    cohort_reports={(field,cohort):report(label,cohort_validation[field,cohort],cohort_errors[field,cohort]) for label,field in MARKETS.values() for cohort in ('Early season (0–7 appearances)','Established season')}
    return dict(history=history,players=players,errors=errors,reports=reports,cohort_errors=cohort_errors,cohort_reports=cohort_reports)


def probability(projected, line, errors):
    if len(errors)<20:return None
    cutoff=(line-projected)/max(1.,math.sqrt(projected))
    empirical=(1+sum(error>cutoff for error in errors))/(len(errors)+2)
    return max(.05,min(.95,.5+.8*(empirical-.5)))


def nba_availability(injuries, team, player, now):
    try:
        source=datetime.fromisoformat(injuries['source_timestamp'].replace('Z','+00:00'))
        retrieved=datetime.strptime(injuries['retrieved'],'%Y-%m-%d %H:%M UTC').replace(tzinfo=timezone.utc)
        if not -600<=(now-source).total_seconds()<=21600 or not 0<=(now-retrieved).total_seconds()<=900:return None
        if team not in injuries['teams']:return None
        matches=[r for r in injuries['rows'] if r['Team']==team and normalized(r['Player'])==normalized(player)]
        return matches[0]['Status'] if len(matches)==1 else 'Not listed' if not matches else None
    except (ValueError,KeyError,TypeError):return None


def minutes_replacement(history, roster_names, out_names, current_minutes):
    # Distribute half of absent players' observed minutes by current active
    # minute share; no arbitrary starter designation or 36-minute assumption.
    by_player=defaultdict(list)
    for row in history:
        if normalized(row['name']) in roster_names:by_player[normalized(row['name'])].append(row)
    means={name:statistics.mean(r['minutes'] for r in values[-5:]) for name,values in by_player.items() if len(values)>=3}
    absent=sum(v for name,v in means.items() if name in out_names)
    active=sum(v for name,v in means.items() if name not in out_names)
    factor=1+min(.1,.5*absent/active) if active>0 else 1.
    return min(40.,current_minutes*factor),factor


def reviews(events, scoreboard, data, injuries, rosters, now=None):
    from online_learning import adjust_forecast, adjust_probability
    now=now or datetime.now(timezone.utc)
    output=[]
    research_cache={}
    for event in events:
        start=datetime.fromisoformat(event['commence_time'].replace('Z','+00:00'))
        matches=[e for e in scoreboard.get('events',[]) if e.get('name')==event['away_team']+' at '+event['home_team'] and abs((datetime.fromisoformat(e['date'].replace('Z','+00:00'))-start).total_seconds())<3600]
        if len(matches)!=1 or start<=now:continue
        source=matches[0];season=source.get('season',scoreboard.get('season',{}))
        if season.get('type')!=2:continue
        # The dataset was loaded for the matching ESPN ending-year season.
        if int(season.get('year',0))!=data['season']:continue
        competitors=source.get('competitions',[{}])[0].get('competitors',[])
        teams={c['team']['displayName']:str(c['team']['id']) for c in competitors}
        game_day=start.astimezone(ZoneInfo('America/Los_Angeles')).date()
        if game_day not in research_cache:research_cache[game_day]=research(data['logs'],game_day)
        model=research_cache[game_day]
        for book in event.get('bookmakers',[]):
            for market in book.get('markets',[]):
                if market['key'] not in MARKETS:continue
                label,field=MARKETS[market['key']]
                for quote in market.get('outcomes',[]):
                    row=dict(Game=event['away_team']+' at '+event['home_team'],Player=quote.get('description','Unknown'),Category=label,Selection=quote.get('name'),Line=quote.get('point'),Odds=quote.get('price'),Sportsbook=book['title'],Decision='Pass',Reason='',Model=MODEL,**{'Quote updated UTC':market.get('last_update') or book.get('last_update'),'Estimated win %':None})
                    output.append(row)
                    line,odds=number(row['Line']),number(row['Odds'])
                    try:age=(now-datetime.fromisoformat(row['Quote updated UTC'].replace('Z','+00:00'))).total_seconds()
                    except (ValueError,TypeError,AttributeError):age=99999
                    if not 0<=age<=900 or line is None or line<0 or line%1!=.5 or odds is None or abs(odds)<100 or row['Selection'] not in ('Over','Under'):
                        row['Reason']='Fresh valid half-unit quote required';continue
                    matched=[(team,p) for team,players in rosters.items() if team in teams for p in players if normalized(p['name'])==normalized(row['Player'])]
                    if len(matched)!=1:row['Reason']='Current game roster match unavailable or ambiguous';continue
                    team,athlete=matched[0]
                    if athlete.get('status','').lower()!='active':row['Reason']='Player roster status is not active';continue
                    status=nba_availability(injuries,team,row['Player'],now)
                    if status is None or status.lower() not in ('active','not listed'):
                        row['Reason']='Availability unverified or uncertain: '+str(status);continue
                    # NBA.com and ESPN athlete IDs differ. Match unique full name
                    # within the verified team, never join those ID namespaces.
                    # ESPN and NBA.com team/player IDs are different namespaces.
                    abbr=next((c['team']['abbreviation'] for c in competitors if c['team']['displayName']==team),None)
                    nba_abbr={'NY':'NYK','GS':'GSW','NO':'NOP','SA':'SAS','UTAH':'UTA','WSH':'WAS'}.get(abbr,abbr)
                    nba_team=teams[team] if data.get('id_namespace')=='ESPN' else data['team_ids'].get(nba_abbr)
                    if not nba_team:row['Reason']='NBA.com/ESPN team mapping unavailable';continue
                    ids={r['player'] for r in data['logs'] if normalized(r['name'])==normalized(row['Player']) and r['date']<game_day.isoformat()}
                    if len(ids)!=1:row['Reason']='Current-team player history unavailable or ambiguous';continue
                    player_history=model['players'].get(next(iter(ids)),[])
                    history=[r for r in model['history'].get((next(iter(ids)),nba_team),[]) if (game_day-day(r['date'])).days<=240]
                    detail=season_projection(player_history,field,data['season'],nba_team,game_day)
                    forecast=(detail['projected'],detail['minutes'],detail['baseline']) if detail else projection(history,field)
                    if not forecast:row['Reason']='Need 8 verified last-season appearances or 8 recent current-team appearances; rookies require a separate model';continue
                    projected,minutes,baseline=forecast
                    roster_names={normalized(p['name']) for p in rosters[team]}
                    out_names={normalized(r['Player']) for r in injuries['rows'] if r['Team']==team and str(r['Status']).lower() in ('out','injured reserve','suspended')}
                    team_history=[r for values in model['history'].values() for r in values if r['team']==nba_team and (game_day-day(r['date'])).days<=60]
                    adjusted_minutes,factor=minutes_replacement(team_history,roster_names,out_names,minutes)
                    projected*=adjusted_minutes/minutes
                    row.update({'Minutes forecast':round(adjusted_minutes,2),'Injury adjustment %':round(100*(factor-1),2),'Injury adjustment reason':'Half of confirmed absent teammates’ observed minutes redistributed by active minute share, capped at 10%; experimental','Availability checked UTC':now.isoformat(),'Statistics retrieved UTC':data['retrieved'],'Player history through':detail['history_through'] if detail else max(r['date'] for r in history),'Base model':MODEL})
                    cohort=detail['cohort'] if detail else 'Established season'
                    calibration=model['cohort_errors'][field,cohort] if detail else model['errors'][field]
                    uncertainty=detail['uncertainty'] if detail else 1.
                    calibration=[e*uncertainty for e in calibration]
                    row.update({'Projection (count)':round(projected,2),'Expected opportunities':round(adjusted_minutes,2),'Opportunity type':'Minutes','History source':data.get('source','NBA.com'),'Season stage':cohort,'Last-season games':detail['prior_games'] if detail else 0,'Current-season appearances':detail['current_games'] if detail else len(history),'Current-season weight %':round(100*detail['current_weight'],1) if detail else 100.,'Role uncertainty':'New team; fewer than 3 current-team games' if detail and detail['role_uncertain'] else 'Historical minutes assumption; lineup changes may differ','Uncertainty multiplier':round(uncertainty,3)})
                    p=probability(projected,line,calibration)
                    if p is None:row['Reason']='Insufficient earlier calibration errors';continue
                    row['Base estimated win %']=100*(1-p if row['Selection']=='Under' else p)
                    projected,adjusted_minutes=adjust_forecast(row,projected,adjusted_minutes,now,sport='NBA')
                    p=probability(projected,line,calibration)
                    if row['Selection']=='Under':p=1-p
                    if row.get('Candidate projection') is not None:
                        candidate=probability(row['Candidate projection'],line,calibration)
                        row['Candidate input win %']=100*(1-candidate if row['Selection']=='Under' else candidate)
                    p=adjust_probability(row,p,now,sport='NBA')
                    breakeven=100/(odds+100) if odds>0 else abs(odds)/(abs(odds)+100)
                    row.update({'Projection (count)':round(projected,2),'Expected opportunities':round(adjusted_minutes,2),'Opportunity type':'Minutes','Estimated win %':round(100*p,1),'Break-even %':round(100*breakeven,1),'Model edge (pp)':round(100*(p-breakeven),1),'Raw estimated win %':row['Online input win %'],'Feedback status':row.get('Online learning status','Collecting prospective evidence'),'Validation':model['cohort_reports'][field,cohort] if detail else model['reports'][field]})
                    report=row['Validation']
                    if next(iter(ids)) in data.get('missing_current',set()):row['Reason']='Last-season forecast shown; current-season history could not be verified';continue
                    if detail and detail['role_uncertain']:row['Reason']='Last-season starting estimate shown; new-team minutes role unverified until 3 current-team appearances';continue
                    if not report['passed']:row['Reason']='Season-stage model has not beaten the prior-season/recent-average baseline on later games; forecast shown for research';continue
                    if p-breakeven<.05:row['Reason']='Estimated edge below five percentage points';continue
                    row['Decision']='Watch — experimental'
                    row['Reason']='Last-season minutes × production blended with current-season appearances; season-stage validation passed. Confirmed absences receive capped minutes adjustment. Later-game stat baseline passed; probability and actual-price profitability remain unverified.'
    return output


def load_data(end_year, targets=()):
    import streamlit as st
    data=st.cache_data(ttl=3600)(_try_load_data)(end_year)
    if data is not None:return data
    if not targets:raise ValueError('NBA.com unavailable and no current roster athlete IDs available for ESPN fallback')
    # Each player/season is cached independently; a single failed request does
    # not discard the other players or a completed prior season.
    from concurrent.futures import ThreadPoolExecutor
    completed=st.cache_data(ttl=86400)(fetch_espn_logs)
    current=st.cache_data(ttl=1800)(fetch_espn_logs)
    logs=[];issues=[];missing_current=set()
    def fetch(job):
        year,pid,name=job
        return (current if year==end_year else completed)(year,pid,name)
    jobs=[(year,pid,name) for pid,name in targets for year in range(end_year-3,end_year+1)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        tasks={job:pool.submit(fetch,job) for job in jobs}
        for job,task in tasks.items():
            try:logs.extend(task.result())
            except Exception:
                issues.append(f'{job[2]}: season ending {job[0]} unavailable')
                if job[0]==end_year:missing_current.add('espn:'+job[1])
    if not logs:raise ValueError('NBA.com and ESPN player game logs unavailable; saved prices are preserved')
    return dict(logs=logs,team_ids={},season=end_year,retrieved=datetime.now(timezone.utc).isoformat(),source='ESPN regular-season game logs (NBA.com unavailable)',id_namespace='ESPN',issues=issues,missing_current=missing_current)


def _try_load_data(end_year):
    # Cache failures too, so reruns do not repeat a slow blocked host request.
    try:return _load_data(end_year)
    except Exception:return None


def _load_data(end_year):
    from nba_tools import nba_request,flat_rows,season_name
    logs=[];team_ids={};issues=[]
    for year in range(end_year-3,end_year+1):
        params=dict(LeagueID='00',Season=season_name(year),SeasonType='Regular Season',PlayerOrTeam='P',Direction='ASC',Sorter='DATE',Counter=1000,DateFrom='',DateTo='')
        try:
            raw=flat_rows(nba_request('leaguegamelog',params))
            for row in raw:
                if row.get('TEAM_ABBREVIATION') and row.get('TEAM_ID'):team_ids[row['TEAM_ABBREVIATION']]=str(row['TEAM_ID'])
            logs.extend(normalize_logs(raw,year))
        except Exception:
            if year==end_year:raise
            else:raise
    if not logs:raise ValueError('No verified NBA player game logs available')
    return dict(logs=logs,team_ids=team_ids,season=end_year,retrieved=datetime.now(timezone.utc).isoformat(),source='NBA.com regular-season game logs',issues=issues)


def render(events, scoreboard, books, auto_analyze=False, key_prefix='nba_props'):
    import streamlit as st
    from nba_tools import load_nba_injuries
    from forecast_tracking import archive
    from pick_history import publish_rows
    from team_emblems import render_team_table
    st.subheader('NBA player forecasts — minutes and production')
    st.caption('Points, rebounds, assists and threes. Experimental minutes × production forecasts use last-season minutes and season-long production, then blend new-season appearances with weight n/(n+8). At least 8 prior-season games or 8 recent current-team games are required. Current rosters, fresh injuries and separate early-season baseline tests remain required. New-team roles have greater uncertainty. Preseason stays on Pass. Loading statistics uses no Odds API credits.')
    if auto_analyze or st.button('Analyze saved NBA prop prices',key=key_prefix+'_analyze'):
        try:
            years={e.get('season',scoreboard.get('season',{})).get('year') for e in scoreboard.get('events',[]) if e.get('season',scoreboard.get('season',{})).get('type')==2}
            if len(years)!=1:st.info('No unique regular-season NBA slate to analyze. Preseason does not qualify.');return
            with st.spinner('Loading NBA game logs, rosters and availability…'):
                injuries=load_nba_injuries()
                teams={c['team']['displayName']:c['team']['id'] for e in scoreboard.get('events',[]) for c in e.get('competitions',[{}])[0].get('competitors',[])}
                from concurrent.futures import ThreadPoolExecutor
                roster={}
                with ThreadPoolExecutor(max_workers=6) as pool:
                    tasks={name:pool.submit(current_roster_nba,tid) for name,tid in teams.items()}
                    for name,task in tasks.items():
                        try:roster[name]=task.result()
                        except Exception:roster[name]=[]

                names={normalized(q.get('description','')) for e in events for b in e.get('bookmakers',[]) if b['title'] in books for m in b.get('markets',[]) if m.get('key') in MARKETS for q in m.get('outcomes',[])}
                targets=tuple(sorted({(p['id'],p['name']) for players in roster.values() for p in players if p.get('id') and normalized(p['name']) in names}))
                data=load_data(next(iter(years)),targets)
                st.caption('Forecast history source: '+data.get('source','NBA.com'))
                if data.get('issues'):st.info('; '.join(data['issues'][:8]))
                filtered=[dict(e,bookmakers=[b for b in e.get('bookmakers',[]) if b['title'] in books]) for e in events]
                rows=reviews(filtered,scoreboard,data,injuries,roster)
                st.session_state[key_prefix+'_results']=(rows,datetime.now(timezone.utc).isoformat())
        except Exception as exc:
            st.warning('NBA forecast data unavailable; no substitute statistics or picks invented. '+str(exc)[:180]);return
    saved=st.session_state.get(key_prefix+'_results')
    if not saved:return
    rows,analyzed=saved
    # Archive raw usable forecasts first; recommendations are consolidated below.
    archive(rows,events,scoreboard,'NBA')
    current=[];now=datetime.now(timezone.utc)
    for row in rows:
        event=next((e for e in events if e['away_team']+' at '+e['home_team']==row['Game']),None)
        if event is None:continue
        if datetime.fromisoformat(event['commence_time'].replace('Z','+00:00'))<=now or (now-datetime.fromisoformat(analyzed)).total_seconds()>900:
            row=dict(row,Decision='Pass',Reason='Analysis expired or game started; reanalyze before use')
        current.append(row)
    grouped=defaultdict(list)
    for r in current:grouped[r['Game'],r['Player'],r['Category']].append(r)
    picks=[]
    for group in grouped.values():
        qualified=[r for r in group if r['Decision']!='Pass']
        if len({r['Selection'] for r in qualified})>1:continue
        if qualified:picks.append(max(qualified,key=lambda r:r['Estimated win %']/100*(1+float(r['Odds'])/100 if float(r['Odds'])>0 else 1+100/abs(float(r['Odds'])))-1))
    st.write(f'{len(picks)} experimental NBA paper picks; all usable analyzed forecasts are tracked separately.')
    if picks:render_team_table(picks,hide_index=True,use_container_width=True,sport='NBA')
    forecasts=[r for r in current if r.get('Projection (count)') is not None]
    if forecasts:
        unique={}
        for r in forecasts:unique.setdefault((r['Game'],r['Player'],r['Category']),r)
        with st.expander('NBA projections — last-season starting point and new-season blend',expanded=not bool(picks)):
            st.caption('Stat estimates can be shown before a category qualifies for a recommendation. Role uncertainty and failed or insufficient validation remain explicit. These projections are not a promise of hitting a sportsbook line.')
            fields=('Game','Player','Category','Projection (count)','Minutes forecast','Last-season games','Current-season appearances','Current-season weight %','Role uncertainty','History source')
            render_team_table([{**{k:r.get(k) for k in fields},'Recommendation status':r['Decision'],'Reason':r['Reason']} for r in unique.values()],hide_index=True,use_container_width=True,sport='NBA')
    with st.expander('All NBA forecasts and Pass reasons'):
        if current:render_team_table(current,hide_index=True,use_container_width=True,sport='NBA')
    publish_rows(picks,events,key_prefix=key_prefix+'_publish',sport='NBA')


def current_roster_nba(team_id):
    import requests
    response=requests.get(f'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}/roster',timeout=20)
    response.raise_for_status()
    athletes=response.json().get('athletes',[])
    if not isinstance(athletes,list):raise ValueError('NBA roster unavailable')
    # NBA uses a flat athlete list; accept grouped form when explicitly present.
    flattened=[]
    for item in athletes:
        flattened.extend(item.get('items',[]) if 'items' in item else [item])
    rows=[]
    for athlete in flattened:
        status=athlete.get('status',{})
        rows.append(dict(id=str(athlete.get('id','')),name=athlete.get('displayName'),status=status.get('name') if isinstance(status,dict) else str(status)))
    if not rows:raise ValueError('NBA roster empty')
    return rows

