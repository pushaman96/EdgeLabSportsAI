"""Keep NBA moneyline history current using free, completed ESPN games."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from urllib.request import urlopen

ALIASES={'NY':'NYK','GS':'GSW','NO':'NOP','SA':'SAS','UTAH':'UTA','WSH':'WAS'}


def merge_completed(history,boards,season,today):
    games={(r['date'],r['home_team'],r['away_team']):dict(r)for r in history if r['date']<today}
    for board in boards:
        for event in board.get('events',[]):
            c=event.get('competitions',[{}])[0];status=c.get('status',event.get('status',{})).get('type',{})
            if not status.get('completed')or event.get('season',board.get('season',{})).get('type')!=2:continue
            if event.get('season',board.get('season',{})).get('year')!=season:continue
            try:
                when=datetime.fromisoformat(event['date'].replace('Z','+00:00')).date()
                teams=c['competitors'];home=next(t for t in teams if t.get('homeAway')=='home');away=next(t for t in teams if t.get('homeAway')=='away')
                hc=ALIASES.get(home['team']['abbreviation'],home['team']['abbreviation']);ac=ALIASES.get(away['team']['abbreviation'],away['team']['abbreviation'])
                hs,aws=float(home['score']),float(away['score'])
                if when>=today or len(teams)!=2 or hc==ac or hs==aws or not all(0<=v<1000 for v in (hs,aws)):continue
            except (KeyError,ValueError,TypeError,StopIteration):continue
            games[when,hc,ac]=dict(date=when,season=season,home_team=hc,away_team=ac,home_score=hs,away_score=aws)
    return sorted(games.values(),key=lambda r:(r['date'],r['home_team']))


def load_history(season):
    import streamlit as st
    from nba_tools import load_nba_saved_history
    @st.cache_data(ttl=300,show_spinner=False)
    def refresh(year,today):
        base=load_nba_saved_history(year)['games'];issues=[]
        def fetch(day):
            url='https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates='+day.strftime('%Y%m%d')
            with urlopen(url,timeout=12)as response:return json.load(response)
        boards=[]
        with ThreadPoolExecutor(max_workers=5)as pool:
            jobs={day:pool.submit(fetch,day)for day in (today-timedelta(days=i)for i in range(1,11))}
            for day,task in jobs.items():
                try:boards.append(task.result())
                except Exception:issues.append(day.isoformat())
        return {'games':merge_completed(base,boards,year,today),'issues':issues,
                'checked_utc':datetime.now(timezone.utc).isoformat(),'source':'Saved NBA.com regular-season history plus verified completed ESPN scoreboards; today/future and preseason excluded'}
    return refresh(season,datetime.now(timezone.utc).date())


def history_ready(games,season,today):
    earlier=[g for g in games if g['date']<today]
    if not earlier:return False,'No completed regular-season history'
    age=(today-max(g['date']for g in earlier)).days
    if age<=30:return True,'Recent completed regular-season ratings'
    prior=[g for g in earlier if g['season']==season-1]
    if today.year==season-1 and len(prior)>=100 and age<=210:
        return True,'Opening-season prior: last-season team ratings; current roster changes are not numerically modeled'
    return False,'History is stale beyond the allowed prior-season opening window'
