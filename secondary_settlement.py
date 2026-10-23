"""Free final-stat fallbacks. Exact identities, explicit values; no odds or keys."""
import csv,io,json,math,re,time
from functools import lru_cache
from datetime import datetime,timezone
from urllib.request import urlopen
from zoneinfo import ZoneInfo

NFL_SCHEDULE='https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv'
NBA_SCHEDULE='https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json'
NBA_BOX='https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{}.json'
NFL_TEAMS={'Arizona Cardinals':'ARI','Atlanta Falcons':'ATL','Baltimore Ravens':'BAL','Buffalo Bills':'BUF','Carolina Panthers':'CAR','Chicago Bears':'CHI','Cincinnati Bengals':'CIN','Cleveland Browns':'CLE','Dallas Cowboys':'DAL','Denver Broncos':'DEN','Detroit Lions':'DET','Green Bay Packers':'GB','Houston Texans':'HOU','Indianapolis Colts':'IND','Jacksonville Jaguars':'JAX','Kansas City Chiefs':'KC','Las Vegas Raiders':'LV','Los Angeles Chargers':'LAC','Los Angeles Rams':'LA','Miami Dolphins':'MIA','Minnesota Vikings':'MIN','New England Patriots':'NE','New Orleans Saints':'NO','New York Giants':'NYG','New York Jets':'NYJ','Philadelphia Eagles':'PHI','Pittsburgh Steelers':'PIT','San Francisco 49ers':'SF','Seattle Seahawks':'SEA','Tampa Bay Buccaneers':'TB','Tennessee Titans':'TEN','Washington Commanders':'WAS'}
NFL_FIELDS={'Passing yards':'passing_yards','Passing attempts':'attempts','Passing completions':'completions','Passing interceptions':'passing_interceptions','Passing touchdowns':'passing_tds','Rushing yards':'rushing_yards','Rushing attempts':'carries','Receiving yards':'receiving_yards','Receptions':'receptions'}
NBA_FIELDS={'Points':'points','Rebounds':'reboundsTotal','Assists':'assists','Three-pointers made':'threePointersMade','Steals':'steals','Blocks':'blocks'}

def key(value):return re.sub('[^a-z0-9]','',str(value).lower())
def number(value):
    if value is None or isinstance(value,bool) or str(value).strip()=='':return None
    try:
        n=float(value)
        return n if math.isfinite(n) else None
    except (ValueError,TypeError):return None
def day(record):
    return datetime.fromisoformat(record['starts_utc'].replace('Z','+00:00')).astimezone(ZoneInfo('America/Los_Angeles')).date()
@lru_cache(maxsize=16)
def download(url,bucket):
    with urlopen(url,timeout=25) as response:raw=response.read().decode('utf-8-sig')
    return json.loads(raw) if raw.lstrip().startswith(('{','[')) else list(csv.DictReader(io.StringIO(raw)))
_failed_downloads={}
def load(url):
    bucket=int(time.time()//900)
    if _failed_downloads.get(url)==bucket:raise OSError('Secondary source retry pending')
    try:return download(url,bucket)
    except Exception:
        _failed_downloads[url]=bucket
        raise

def final_summary(record,home,away,home_score,away_score,players=None):
    return {'header':{'id':str(record['event_id']),'competitions':[{'status':{'type':{'completed':True,'state':'post'}},'competitors':[{'homeAway':'home','team':{'displayName':home},'score':str(home_score)},{'homeAway':'away','team':{'displayName':away},'score':str(away_score)}]}]},'boxscore':{'players':players or []}}

def nfl_summary(record,schedule,stats=None):
    names=record['game'].split(' at ')
    if len(names)!=2:raise ValueError('Invalid game identity')
    away,home=names;ac,hc=NFL_TEAMS.get(away),NFL_TEAMS.get(home)
    matches=[g for g in schedule if ac and hc and g.get('away_team')==ac and g.get('home_team')==hc and g.get('gameday')==day(record).isoformat() and str(g.get('espn'))==str(record['event_id']) and g.get('game_type')=='REG']
    if len(matches)!=1:raise ValueError('No unique NFL game/date/ESPN identity match')
    g=matches[0];hs,aws=number(g.get('home_score')),number(g.get('away_score'))
    if hs is None or aws is None or min(hs,aws)<0:raise ValueError('Final NFL scores unavailable')
    output=final_summary(record,home,away,hs,aws)
    if record['category'] in ('Moneyline','Game total points'):return output
    field=NFL_FIELDS.get(record['category'])
    if field is None:raise ValueError('Category unsupported by NFL fallback')
    matched=[r for r in (stats or []) if r.get('game_id')==g['game_id'] and r.get('season_type')=='REG' and key(r.get('player_display_name'))==key(record['player']) and r.get('team') in (ac,hc)]
    if len(matched)!=1:raise ValueError('NFL player total not uniquely reported')
    r=matched[0];v=number(r.get(field))
    if v is None:raise ValueError('Requested NFL statistic missing')
    group='passing' if record['category'].startswith('Passing') else 'rushing' if record['category'].startswith('Rushing') else 'receiving'
    if group=='passing':
        labels=['YDS','INT','TD'];values=[r.get('passing_yards'),r.get('passing_interceptions'),r.get('passing_tds')]
        attempts,completions=number(r.get('attempts')),number(r.get('completions'))
        if attempts is not None and completions is not None:labels+=['C/ATT'];values+=[f'{completions}/{attempts}']
    elif group=='rushing':labels=['YDS','CAR'];values=[r.get('rushing_yards'),r.get('carries')]
    else:labels=['YDS','REC','TGTS'];values=[r.get('receiving_yards'),r.get('receptions'),r.get('targets')]
    # Omit absent fields entirely. Never create a zero for missing evidence.
    pairs=[(k,v) for k,v in zip(labels,values) if v is not None and str(v).strip()!='']
    output['boxscore']['players']=[{'statistics':[{'name':group,'labels':[k for k,v in pairs],'athletes':[{'athlete':{'displayName':record['player']},'stats':[str(v) for k,v in pairs]}]}]}]
    return output

def nba_name(team):
    return (str(team.get('teamCity',''))+' '+str(team.get('teamName',''))).strip().replace('LA Clippers','Los Angeles Clippers')
def nba_game_id(record,schedule):
    away,home=record['game'].split(' at ')
    matches=[]
    for date_entry in schedule.get('leagueSchedule',{}).get('gameDates',[]):
        for g in date_entry.get('games',[]):
            try:when=datetime.fromisoformat(g['gameDateTimeUTC'].replace('Z','+00:00')).astimezone(ZoneInfo('America/Los_Angeles')).date()
            except (KeyError,ValueError,TypeError):continue
            if when==day(record) and nba_name(g.get('homeTeam',{}))==home and nba_name(g.get('awayTeam',{}))==away and g.get('gameStatus')==3:matches.append(str(g['gameId']))
    if len(matches)!=1:raise ValueError('No unique final NBA game/date/team match')
    return matches[0]
def nba_summary(record,game,expected_id):
    away,home=record['game'].split(' at ')
    if str(game.get('gameId'))!=expected_id or game.get('gameStatus')!=3:raise ValueError('NBA final game identity mismatch')
    if nba_name(game.get('homeTeam',{}))!=home or nba_name(game.get('awayTeam',{}))!=away:raise ValueError('NBA team identity mismatch')
    hs,aws=number(game['homeTeam'].get('score')),number(game['awayTeam'].get('score'))
    if hs is None or aws is None or min(hs,aws)<0:raise ValueError('NBA final scores missing')
    output=final_summary(record,home,away,hs,aws)
    if record['category'] in ('Moneyline','Game total points'):return output
    entries=[p for side in ('homeTeam','awayTeam') for p in game[side].get('players',[]) if key(p.get('name') or (str(p.get('firstName',''))+' '+str(p.get('familyName',''))).strip())==key(record['player'])]
    if len(entries)!=1 or entries[0].get('played') not in ('1',1,True):raise ValueError('NBA participation/player identity unverified')
    stats=entries[0].get('statistics',{});category=record['category']
    needed=['points','reboundsTotal','assists'] if category=='PRA' else [NBA_FIELDS.get(category)]
    if None in needed or any(number(stats.get(f)) is None for f in needed):raise ValueError('Required NBA final statistic missing')
    labels=[];values=[]
    for category,field in NBA_FIELDS.items():
        v=number(stats.get(field))
        if v is not None:
            labels.append({'Points':'PTS','Rebounds':'REB','Assists':'AST','Three-pointers made':'3PT','Steals':'STL','Blocks':'BLK'}[category])
            values.append(str(v))
    # NBA minutes are ISO durations, not assumed from participation.
    duration=stats.get('minutes')
    if isinstance(duration,str):
        match=re.fullmatch(r'PT(\d+)M([\d.]+)S',duration)
        if match:labels.append('MIN');values.append(str(float(match[1])+float(match[2])/60))
    output['boxscore']['players']=[{'statistics':[{'labels':labels,'athletes':[{'athlete':{'displayName':record['player']},'stats':values}]}]}]
    return output

NBA_ARCHIVE='https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_nba_player_boxscores/player_box_{}.csv'
ARCHIVE_FIELDS={'Points':'points','Rebounds':'rebounds','Assists':'assists','Three-pointers made':'three_point_field_goals_made','Steals':'steals','Blocks':'blocks'}

def final_status(record,data):
    header=data.get('header',{})
    competitions=header.get('competitions') or [{}]
    return str(header.get('id'))==str(record['event_id']) and competitions[0].get('status',{}).get('type',{}).get('completed') is True

def archive_summary(record,rows,primary):
    if not final_status(record,primary or {}):raise ValueError('Final NBA status not verified')
    away,home=record['game'].split(' at ')
    selected=[r for r in rows if str(r.get('game_id'))==str(record['event_id']) and r.get('game_date')==day(record).isoformat() and str(r.get('season_type'))=='2']
    expected={home:away,away:home};scores={}
    for r in selected:
        team=r.get('team_display_name')
        if team not in expected or r.get('opponent_team_display_name')!=expected[team]:raise ValueError('NBA archive team identity mismatch')
        score=number(r.get('team_score'));opp=number(r.get('opponent_team_score'))
        if score is None or opp is None or min(score,opp)<0:raise ValueError('NBA archive final scores missing')
        pair=(score,opp)
        if team in scores and scores[team]!=pair:raise ValueError('NBA archive scores disagree')
        scores[team]=pair
    if set(scores)!={home,away} or scores[home]!=(scores[away][1],scores[away][0]):raise ValueError('NBA archive game incomplete')
    output=final_summary(record,home,away,scores[home][0],scores[away][0])
    if record['category'] in ('Moneyline','Game total points'):return output
    matched=[r for r in selected if key(r.get('athlete_display_name'))==key(record['player'])]
    if len(matched)!=1:raise ValueError('NBA archive athlete identity ambiguous')
    row=matched[0]
    if str(row.get('did_not_play')).lower()!='false' or number(row.get('minutes')) is None or number(row.get('minutes'))<=0:raise ValueError('NBA archive participation unverified')
    required=['points','rebounds','assists'] if record['category']=='PRA' else [ARCHIVE_FIELDS.get(record['category'])]
    if None in required or any(number(row.get(f)) is None for f in required):raise ValueError('NBA archive requested statistic missing')
    pairs=[({'Points':'PTS','Rebounds':'REB','Assists':'AST','Three-pointers made':'3PT','Steals':'STL','Blocks':'BLK'}[cat],number(row.get(field))) for cat,field in ARCHIVE_FIELDS.items() if number(row.get(field)) is not None]
    pairs.append(('MIN',number(row['minutes'])))
    output['boxscore']['players']=[{'statistics':[{'labels':[k for k,v in pairs],'athletes':[{'athlete':{'displayName':record['player']},'stats':[str(v) for k,v in pairs]}]}]}]
    return output

def archive_fallback(record,primary):
    verified=primary if final_status(record,primary or {}) else None
    if verified is None:
        board=load('https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates='+day(record).strftime('%Y%m%d'))
        events=[e for e in board.get('events',[]) if str(e.get('id'))==str(record['event_id']) and e.get('name')==record['game']]
        if len(events)!=1:raise ValueError('Final NBA scoreboard event unavailable')
        verified={'header':{'id':str(record['event_id']),'competitions':events[0].get('competitions',[])}}
    year=day(record).year+int(day(record).month>=7)
    return archive_summary(record,load(NBA_ARCHIVE.format(year)),verified),'SportsDataverse ESPN-derived archive; final status verified separately'

def secondary(record,primary=None):
    if record.get('sport','NFL')=='NFL':
        schedule=load(NFL_SCHEDULE)
        stats=None
        if record['category'] not in ('Moneyline','Game total points'):
            candidates=[g for g in schedule if str(g.get('espn'))==str(record['event_id'])]
            if len(candidates)!=1:raise ValueError('NFL season identity unavailable')
            stats=load('https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_'+str(candidates[0]['season'])+'.csv')
        return nfl_summary(record,schedule,stats),'nflverse final schedule/weekly player statistics'
    try:
        gid=nba_game_id(record,load(NBA_SCHEDULE))
        return nba_summary(record,load(NBA_BOX.format(gid))['game'],gid),'NBA official final box score'
    except Exception:
        return archive_fallback(record,primary)

def resolve(record,primary=None,fetch=secondary):
    from pick_history import grade_record
    now=datetime.now(timezone.utc).isoformat()
    try:
        data,source=fetch(record,primary)
        # If both feeds provide final scores, disagreement requires review.
        if primary and (primary.get('header',{}).get('competitions') or [{}])[0].get('status',{}).get('type',{}).get('completed'):
            def scores(d):
                return {c.get('team',{}).get('displayName'):number(c.get('score')) for c in d['header']['competitions'][0].get('competitors',[])}
            a,b=scores(primary),scores(data)
            if len(a)==2 and all(v is not None for v in a.values()) and a!=b:
                return dict(record,grading_note='Final sources disagree on score; remains Pending for reconciliation.',settlement_checked_utc=now,settlement_source_status='Conflict')
        graded=grade_record(record,data)
        if graded.get('result') in ('Win','Loss','Push'):
            return dict(graded,settlement_source=source,settlement_checked_utc=now,settlement_source_status='Verified fallback',grading_note='Verified final statistic via '+source+'. Platform-specific void rules and corrections may differ.')
        return dict(record,grading_note='Secondary final evidence incomplete; automatic retry pending.',settlement_checked_utc=now,settlement_source_status='Incomplete')
    except Exception as error:
        # Do not expose request URLs or raw error strings.
        return dict(record,grading_note='Final statistic not verified by primary or secondary source; automatic retry pending.',settlement_checked_utc=now,settlement_source_status='Unavailable or unmatched ('+type(error).__name__+')')
