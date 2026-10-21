"""Verified ESPN NBA context. Associations and scenarios do not change forecasts."""
import math
import re
import statistics
from collections import defaultdict
from datetime import datetime,timezone
from zoneinfo import ZoneInfo

BASE='https://site.api.espn.com/apis/site/v2/sports/basketball/nba'
PACIFIC=ZoneInfo('America/Los_Angeles')
VERSION='nba-game-context-v1'


def utc(value):return datetime.fromisoformat(str(value).replace('Z','+00:00'))
def key(value):return re.sub('[^a-z0-9]','',str(value).lower())
def num(value):
    try:
        value=float(value)
        return value if math.isfinite(value) and value>=0 else None
    except (ValueError,TypeError):return None
def mean(values):return statistics.mean(values) if values else None


def request(path):
    import json
    from urllib.request import urlopen
    with urlopen(BASE+path,timeout=12)as response:return json.load(response)


def fetch_schedule(path):return request(path)


def fetch_final(path):
    data=request(path)
    if not completed_game(data,datetime.now(timezone.utc).isoformat()):raise ValueError('Final regular-season box score not verified')
    return data


def fetch_upcoming(path):return request(path)


def schedule_rows(data,team_id,year,season_type=2):
    if str(data.get('team',{}).get('id'))!=str(team_id):
        raise ValueError('NBA schedule team mismatch')
    # ESPN's top-level season describes the CURRENT season even for a correct
    # historical schedule. Require explicit year/type on each event instead.
    result=[];seen=set()
    for event in data.get('events',[]):
        competitions=event.get('competitions',[])
        if len(competitions)!=1:continue
        c=competitions[0];teams=c.get('competitors',[])
        own=[t for t in teams if str(t.get('team',{}).get('id'))==str(team_id)]
        if len(own)!=1 or len(teams)!=2 or str(event.get('seasonType',{}).get('type'))!=str(season_type) or event.get('season',{}).get('year')!=year:continue
        try:start=utc(event['date'])
        except (KeyError,TypeError,ValueError):continue
        status=c.get('status',{}).get('type',{})
        if any(s in str(status.get('name','')).upper() for s in ('POSTPON','CANCEL','SUSPEND')):continue
        if event.get('timeValid') is False:continue
        eid=str(event.get('id',''))
        if not eid or eid in seen:continue
        seen.add(eid)
        result.append({'id':eid,'date':start.isoformat(),'team':str(team_id),'year':year,'season_type':season_type,'completed':status.get('completed') is True,'venue':c.get('venue',{}).get('fullName'),'city':c.get('venue',{}).get('address',{}).get('city'),'homeAway':own[0].get('homeAway')})
    return sorted(result,key=lambda r:(r['date'],r['id']))


def rest_context(schedule,event_id,start,team_id):
    start=utc(start)
    own=[r for r in schedule if r['team']==str(team_id)]
    current=[r for r in own if r['id']==str(event_id) and abs((utc(r['date'])-start).total_seconds())<3600]
    if len(current)!=1:return {'Status':'Team schedule unavailable or game not verified','Back-to-back':None}
    before=[r for r in own if utc(r['date'])<start and r['id']!=str(event_id)]
    if not before:return {'Status':'No earlier verified NBA schedule entry','Back-to-back':None}
    prior=max(before,key=lambda r:utc(r['date']))
    gap=(start.astimezone(PACIFIC).date()-utc(prior['date']).astimezone(PACIFIC).date()).days
    return {'Status':'Verified team schedule','Back-to-back':gap==1,'Calendar days between scheduled games':gap,'Scheduled off days':max(0,gap-1),'Previous game':prior['id'],'Previous venue':prior.get('venue'),'Upcoming venue':current[0].get('venue'),'Previous city':prior.get('city'),'Upcoming city':current[0].get('city'),'Venue change':prior.get('venue')!=current[0].get('venue') if prior.get('venue') and current[0].get('venue') else None,'Method':'Pacific calendar dates and verified NBA schedules, including preseason and playoffs for rest context; off days are schedule gaps, not verified days of physical rest. No automatic rest or travel penalty.'}


def athlete_rows(summary):
    result={}
    for team in summary.get('boxscore',{}).get('players',[]):
        tid=str(team.get('team',{}).get('id',''))
        for group in team.get('statistics',[]):
            labels=group.get('labels',[])
            for athlete in group.get('athletes',[]):
                name=athlete.get('athlete',{}).get('displayName')
                if not name:continue
                stats=dict(zip(labels,athlete.get('stats',[])))
                minutes=stats.get('MIN')
                if isinstance(minutes,str) and ':'in minutes:
                    try:minutes=float(minutes.split(':')[0])+float(minutes.split(':')[1])/60
                    except (ValueError,IndexError):minutes=None
                row={'team':tid,'name':name,'starter':athlete.get('starter') if isinstance(athlete.get('starter'),bool)else None,'didNotPlay':athlete.get('didNotPlay') if isinstance(athlete.get('didNotPlay'),bool)else None,'minutes':num(minutes)}
                for field in ('PTS','REB','AST'):row[field]=num(stats.get(field))
                row['PRA']=sum(row[f]for f in ('PTS','REB','AST'))if all(row[f]is not None for f in ('PTS','REB','AST'))else None
                for field,label in (('FG3M','3PT'),('FGA','FG'),('FG3A','3PT'),('FTA','FT')):
                    parts=str(stats.get(label,'')).replace('/','-').split('-')
                    row[field]=num(parts[0] if field=='FG3M' else parts[1]) if len(parts)==2 else None
                result[tid,key(name)]=row
    return result


def lineup_context(summary,event_id,start,team_id,player,now):
    result={'Status':'Starting lineup unconfirmed','Starter':None,'Checked UTC':now.isoformat()}
    try:
        header=summary.get('header',{});c=header['competitions'][0]
        if str(header.get('id'))!=str(event_id) or abs((utc(c['date'])-utc(start)).total_seconds())>=3600 or utc(start)<=now:return result
        if c.get('status',{}).get('type',{}).get('state')!='pre':return result
    except (KeyError,ValueError,TypeError,IndexError):return result
    rows=athlete_rows(summary)
    starters=[r for (tid,_),r in rows.items() if tid==str(team_id) and r['starter'] is True and r['didNotPlay'] is not True]
    player_row=rows.get((str(team_id),key(player)))
    if len(starters)!=5 or not player_row:return result
    if player_row['starter'] is None or player_row['didNotPlay'] is True:return result
    return {'Status':'ESPN explicitly lists five starters; not a guarantee of minutes','Starter':player_row['starter'],'Checked UTC':now.isoformat(),'Source game':str(event_id)}


def restriction_context(injuries,team,player,now):
    matches=[r for r in injuries.get('rows',[]) if r.get('Team')==team and key(r.get('Player'))==key(player)]
    if len(matches)!=1:return {'Status':'No explicit current minutes-limit report found in checked injury feed','Review required':False}
    row=matches[0];text=str(row.get('Short comment')or '')
    try:fresh=0<=(now-utc(row['Report updated (UTC)'])).total_seconds()<=86400
    except (ValueError,TypeError,KeyError):fresh=False
    # Short current report only; long comments can discuss an old restriction.
    mentioned=bool(re.search(r'minute[s]?[ -](?:restriction|limit)|limited to \d+ minutes',text,re.I))
    cleared=bool(re.search(r'\b(?:no|without|not under|not on|off)(?: a| any)? minutes?[ -](?:restriction|limit)|\bno longer (?:on|under|has)(?: a| any)? minutes?[ -](?:restriction|limit)|(?:restriction|limit) (?:has been|was|is) (?:lifted|removed)',text,re.I))
    return {'Status':'Current report mentions a minutes limit; manual verification required' if fresh and mentioned and not cleared else 'No explicit current minutes-limit report found in checked injury feed','Review required':fresh and mentioned and not cleared,'Report text':text if fresh and mentioned else None,'Report updated UTC':row.get('Report updated (UTC)'),'Limitation':'Text flag only. No numeric minutes cap inferred; absence of a flag does not confirm unrestricted minutes.'}


def completed_game(summary,cutoff):
    try:
        header=summary['header'];c=header['competitions'][0]
        return bool(header.get('id')) and header.get('season',{}).get('type')==2 and c.get('status',{}).get('type',{}).get('completed') is True and utc(c['date'])<utc(cutoff)
    except (KeyError,IndexError,ValueError,TypeError):return False


def teammate_context(summaries,cutoff,team_id,player,absent_names,field):
    output=[]
    for absent in sorted(set(absent_names),key=key):
        with_player=[];without=[];seen=set()
        for data in summaries:
            if not completed_game(data,cutoff):continue
            eid=str(data['header']['id'])
            if eid in seen:continue
            seen.add(eid)
            rows=athlete_rows(data);target=rows.get((str(team_id),key(player)));mate=rows.get((str(team_id),key(absent)))
            if not target or not mate or target['didNotPlay'] is not False or not target.get('minutes') or target.get(field) is None:continue
            sample={'minutes':target['minutes'],'stat':target[field],'shots':target.get('FGA'),'per_minute':target[field]/target['minutes']}
            if mate['didNotPlay'] is True:without.append(sample)
            elif mate['didNotPlay'] is False and mate.get('minutes') and mate['minutes']>0:with_player.append(sample)
        def aggregate(rows):return {'Games':len(rows),'Minutes':mean([r['minutes']for r in rows]),'Stat':mean([r['stat']for r in rows]),'Stat per minute':mean([r['per_minute']for r in rows]),'FG attempts':mean([r['shots']for r in rows if r['shots']is not None])}
        a,b=aggregate(with_player),aggregate(without)
        enough=len(with_player)>=3 and len(without)>=3
        output.append({'Unavailable teammate':absent,'With teammate':a,'Without teammate':b,'Observed stat difference':b['Stat']-a['Stat'] if enough else None,'Status':'Descriptive comparison only; no causal effect or automatic adjustment' if enough else 'Insufficient matched with/without samples (need 3 each)','Source':'Explicit played/DNP box-score flags; missing roster rows excluded'})
    return output


def team_possessions(team):
    stats={s.get('name'):s.get('displayValue')for s in team.get('statistics',[])}
    def attempts(name):
        parts=str(stats.get(name,'')).replace('/','-').split('-')
        return num(parts[1])if len(parts)==2 else None
    fga=attempts('fieldGoalsMade-fieldGoalsAttempted');fta=attempts('freeThrowsMade-freeThrowsAttempted')
    orb=num(stats.get('offensiveRebounds'));turnovers=num(stats.get('totalTurnovers',stats.get('turnovers')))
    if any(v is None for v in (fga,fta,orb,turnovers)):return None
    value=fga-orb+turnovers+.44*fta
    return value if value>0 else None


def opponent_context(summaries,cutoff,team_id,opponent_id,field):
    own=[];opponents=[];seen=set()
    for data in summaries:
        if not completed_game(data,cutoff):continue
        eid=str(data['header'].get('id'))
        if eid in seen:continue
        seen.add(eid)
        c=data['header']['competitions'][0];teams=data.get('boxscore',{}).get('teams',[])
        if len(teams)!=2:continue
        period=c.get('status',{}).get('period')
        if not isinstance(period,int):
            # Archived ESPN summaries often omit status.period, but report
            # every quarter/overtime explicitly in both teams' line scores.
            lengths=[len(t.get('linescores',[]))for t in c.get('competitors',[])]
            period=lengths[0]if len(lengths)==2 and lengths[0]==lengths[1]and lengths[0]>=4 else None
        if not isinstance(period,int)or period<4:continue
        duration=48+5*max(0,period-4)
        possessions=[team_possessions(t)for t in teams]
        if any(v is None for v in possessions):continue
        pace=mean(possessions)*48/duration
        tids=[str(t.get('team',{}).get('id'))for t in teams]
        if str(team_id)in tids:own.append(pace)
        if str(opponent_id)in tids:
            opponent=str(opponent_id);other=next(tid for tid in tids if tid!=opponent)
            team_rows=[r for (tid,_),r in athlete_rows(data).items() if tid==other]
            rows=[r for r in team_rows if r['didNotPlay']is False]
            # All played rows must have the requested value: no missing zeros.
            complete=rows and all(r['didNotPlay']is not None for r in team_rows) and all(r.get(field)is not None and r.get('minutes')is not None for r in rows) and abs(sum(r['minutes']for r in rows)-5*duration)<=5
            opponents.append({'pace':pace,'allowed':sum(r[field]for r in rows)*48/duration if complete else None})
    allowed=[r['allowed']for r in opponents if r['allowed']is not None]
    return {'Team games':len(own),'Opponent games':len(opponents),'Team estimated possessions per 48':mean(own)if len(own)>=3 else None,'Opponent estimated possessions per 48':mean([r['pace']for r in opponents])if len(opponents)>=3 else None,'Opponent allowed stat per 48':mean(allowed)if len(allowed)>=3 else None,'Allowed-stat games':len(allowed),'Status':'Research context; no player-level or position-specific multiplier applied','Method':'Estimated possessions: FGA − offensive rebounds + total turnovers + 0.44 × FTA; average both teams, normalize overtime. Recent verified final regular-season games only.'}


def load_context(events,scoreboard,now=None,max_history=120,per_team=12):
    """Cached free ESPN calls, bounded historical summaries, partial failure safe."""
    import streamlit as st
    from concurrent.futures import ThreadPoolExecutor
    now=now or datetime.now(timezone.utc)
    # Distinct functions are required: wrapping one function with three TTLs
    # shares a Streamlit function key and can continually evict its own cache.
    schedule_fetch=st.cache_data(ttl=1800)(fetch_schedule)
    final_fetch=st.cache_data(ttl=86400)(fetch_final)
    upcoming_fetch=st.cache_data(ttl=120)(fetch_upcoming)
    games={};team_years=set();issues=[]
    for event in events:
        try:start=utc(event['commence_time'])
        except (KeyError,ValueError,TypeError):continue
        if start<=now:continue
        matches=[e for e in scoreboard.get('events',[])if e.get('name')==event['away_team']+' at '+event['home_team'] and abs((utc(e['date'])-start).total_seconds())<3600]
        if len(matches)!=1:continue
        source=matches[0];season=source.get('season',scoreboard.get('season',{}))
        if season.get('type')!=2:continue
        teams=source.get('competitions',[{}])[0].get('competitors',[])
        if len(teams)!=2:continue
        games[str(source['id'])]={'event':source,'start':event['commence_time'],'teams':{t['team']['displayName']:str(t['team']['id'])for t in teams}}
        for team in teams:
            for year,kind in ((int(season['year'])-1,2),(int(season['year'])-1,3),(int(season['year']),1),(int(season['year']),2)):
                team_years.add((str(team['team']['id']),year,kind))
    schedules=[]
    with ThreadPoolExecutor(max_workers=8)as pool:
        tasks={(tid,year,kind):pool.submit(schedule_fetch,f'/teams/{tid}/schedule?season={year}&seasontype={kind}')for tid,year,kind in sorted(team_years)}
        for (tid,year,kind),task in tasks.items():
            try:schedules.extend(schedule_rows(task.result(),tid,year,kind))
            except Exception:issues.append('Team '+tid+' schedule '+str(year)+' type '+str(kind)+' unavailable')
    # Allocate history round-robin so an alphabetical first team cannot consume
    # the entire cold-load budget. No paid odds endpoint is used.
    pools={}
    for game in games.values():
        for tid in game['teams'].values():
            pools[tid]=sorted((r for r in schedules if r['team']==tid and r['season_type']==2 and r['completed'] and utc(r['date'])<min(utc(game['start']),now)),key=lambda r:r['date'],reverse=True)[:per_team]
    history_ids=[];seen=set()
    for depth in range(per_team):
        for tid,rows in sorted(pools.items()):
            if depth<len(rows)and rows[depth]['id']not in seen:
                seen.add(rows[depth]['id']);history_ids.append(rows[depth]['id'])
                if len(history_ids)>=max_history:break
        if len(history_ids)>=max_history:break
    history=[];upcoming={}
    with ThreadPoolExecutor(max_workers=8)as pool:
        jobs={eid:pool.submit(final_fetch,'/summary?event='+eid)for eid in history_ids}
        live={eid:pool.submit(upcoming_fetch,'/summary?event='+eid)for eid in games}
        for eid,task in jobs.items():
            try:
                data=task.result()
                if str(data.get('header',{}).get('id'))!=eid:raise ValueError('Game identity mismatch')
                if completed_game(data,now.isoformat()):history.append(data)
            except Exception:issues.append('Historical game '+eid+' unavailable')
        for eid,task in live.items():
            try:upcoming[eid]=task.result()
            except Exception:issues.append('Pregame lineup '+eid+' unavailable')
    return {'version':VERSION,'games':games,'schedules':schedules,'history':history,'upcoming':upcoming,'retrieved':datetime.now(timezone.utc).isoformat(),'issues':issues,'history_requested':len(history_ids),'history_loaded':len(history),'history_limit':max_history}


def attach_context(row,context,event_id,team,team_id,player,start,field,injuries,now):
    context=context or {};games=context.get('games',{});game=games.get(str(event_id),{})
    opponent=next((tid for name,tid in game.get('teams',{}).items()if str(tid)!=str(team_id)),None)
    absent=[r['Player']for r in injuries.get('rows',[])if r.get('Team')==team and str(r.get('Status','')).lower()in ('out','injured reserve','suspended')]
    row.update({'NBA context version':VERSION,'NBA context checked UTC':context.get('retrieved'),'Starting lineup check':lineup_context(context.get('upcoming',{}).get(str(event_id),{}),event_id,start,team_id,player,now),'Minutes restriction check':restriction_context(injuries,team,player,now),'Verified schedule context':rest_context(context.get('schedules',[]),event_id,start,team_id),'Teammate absence usage':teammate_context(context.get('history',[]),start,team_id,player,absent,field),'Opponent and pace context':opponent_context(context.get('history',[]),start,team_id,opponent,field),'NBA context limitation':'Historical associations and estimated pace are not validated causal/player multipliers; they do not change the base projection or probability.'})
    return row
