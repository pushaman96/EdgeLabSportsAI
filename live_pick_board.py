from probability_order import highest_probability
"""One live table for frozen picks. ESPN stats only; no sportsbook requests."""
import csv
import io
import json
import math
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from urllib.request import urlopen
from zoneinfo import ZoneInfo

PACIFIC=ZoneInfo('America/Los_Angeles')
NFL_FIELDS={'Passing yards':('passing','YDS'),'Passing attempts':('passing','C/ATT'),'Passing completions':('passing','C/ATT'),'Passing touchdowns':('passing','TD'),'Passing interceptions':('passing','INT'),'Rushing yards':('rushing','YDS'),'Rushing attempts':('rushing','CAR'),'Receiving yards':('receiving','YDS'),'Receptions':('receiving','REC')}
NBA_FIELDS={'Points':'PTS','Rebounds':'REB','Assists':'AST','Three-pointers made':'3PT','Steals':'STL','Blocks':'BLK'}
def utc(v):return datetime.fromisoformat(str(v).replace('Z','+00:00'))
def number(v):
    try:
        n=float(str(v).replace(',',''));return n if math.isfinite(n) else None
    except (ValueError,TypeError):return None

def identity(v):return re.sub(r'[^a-z0-9]','',str(v).lower())

def current_stat(record,data):
    if record['category']in ('PRA','Anytime touchdown','Game total points'):
        from extended_stats import current_value
        return current_value(record['category'],record['player'],data)
    if record['category']=='Moneyline':return None
    nba=record.get('sport','NFL')=='NBA';category=record['category']
    if not nba and category not in NFL_FIELDS:return None
    label=NBA_FIELDS.get(category) if nba else NFL_FIELDS[category][1]
    if not label:return None
    values=[]
    for team in data.get('boxscore',{}).get('players',[]):
        for group in team.get('statistics',[]):
            if not nba and group.get('name')!=NFL_FIELDS[category][0]:continue
            for entry in group.get('athletes',[]):
                if identity(entry.get('athlete',{}).get('displayName'))!=identity(record['player']):continue
                raw=dict(zip(group.get('labels',[]),entry.get('stats',[]))).get(label)
                if raw is None:continue
                if label=='C/ATT':raw=str(raw).split('/')[0 if category=='Passing completions' else -1]
                if label=='3PT':raw=str(raw).replace('/','-').split('-')[0]
                parsed=number(raw)
                if parsed is not None:values.append(parsed)
    return values[0] if len(values)==1 else None

def build_board(records,summaries,now=None,team_assets=None):
    from team_emblems import pick_team
    from pick_history import grade_record
    from saved_pick_explanation import short_reason
    now=now or datetime.now(timezone.utc);rows=[];seen=set();situation_cache={}
    for record in records:
        if record.get('id') in seen:continue
        seen.add(record.get('id'))
        row={'Player / team':record['player'],'Live stat':None,'Pick':record['direction']+(' '+str(record['line']) if record.get('line') is not None else ''),'Category':record['category'],'Live position':'Waiting for kickoff','Final result':'Pending','Game':record['game'],'Period / clock':'—','Score':'—','Difference vs line':None,'Frozen model probability %':round(100*record['probability'],1) if number(record.get('probability')) is not None else None,'Odds':record.get('odds'),'Sportsbook':record.get('sportsbook'),'Strategy':record.get('strategy','Original'),'Kickoff Pacific':utc(record['starts_utc']).astimezone(PACIFIC).strftime('%a %m/%d %I:%M %p'),'Data checked UTC':None,'Model':record.get('model'),'Pick ID':record.get('id')}
        row['Short reason']=short_reason(record)
        key=(record.get('sport','NFL'),str(record['event_id']));item=summaries.get(key)
        valid_data=item.get('data') if item and str(item.get('data',{}).get('header',{}).get('id',''))==str(record['event_id']) else None
        emblem=pick_team(record,valid_data,team_assets)
        row={'Team logo':emblem.get('logo') if emblem else None,**row}
        # Even when the feed is down, retain previously verified final ledger grades.
        if record.get('result') in ('Win','Loss','Push'):
            row['Final result']=record['result'];row['Live position']='Final — saved grade'
            row['Live stat']=number(record.get('actual'))
        if item is None or item.get('error'):
            if row['Final result']=='Pending' and now>=utc(record['starts_utc']):row['Live position']='Feed unavailable — retrying; no result assumed'
            rows.append(row);continue
        data=item.get('data',{});header=data.get('header',{})
        if str(header.get('id',''))!=str(record['event_id']):
            row['Live position']='Feed identity mismatch — no stats used';rows.append(row);continue
        competition=header.get('competitions',[{}])[0];status=competition.get('status',{});kind=status.get('type',{});state=kind.get('state')
        from game_situations import situation_snapshot
        if key not in situation_cache:situation_cache[key]=situation_snapshot(data,record.get('sport','NFL'))
        last=situation_cache[key].get('last_play')
        row['Latest reported play']=last.get('Text') if last else None
        row['Latest play situation']=(' · '.join(str(last[k]) for k in ('Team','Period','Clock','Situation') if last.get(k) is not None)) if last else None
        row['Data checked UTC']=item.get('retrieved_utc')
        competitors=competition.get('competitors',[])
        row['Score']=' · '.join(c.get('team',{}).get('abbreviation',c.get('team',{}).get('displayName','Team'))+' '+str(c.get('score','—')) for c in competitors)
        period=status.get('period');clock=status.get('displayClock') or ''
        row['Period / clock']=(('OT'+str(period-4) if period>4 else 'Q'+str(period))+' '+clock).strip() if state=='in' and period else kind.get('shortDetail') or kind.get('description','—')
        if kind.get('completed'):
            # Feed result is authoritative for the live display; persistence is handled by the grading job.
            graded=grade_record(dict(record,result='Pending'),data)
            row['Final result']=graded['result'];row['Live stat']=number(graded.get('actual'))
            row['Live position']='Final' if graded['result']!='Pending' else 'Final — stat missing; settlement review needed'
        elif state=='pre':row['Live position']=kind.get('detail') or 'Waiting for kickoff'
        elif state!='in':row['Live position']=kind.get('detail') or 'Game status unresolved'
        elif record['category']=='Moneyline':
            selected=[c for c in competitors if c.get('team',{}).get('displayName')==record['player']]
            other=[c for c in competitors if c.get('team',{}).get('displayName')!=record['player']]
            if len(selected)==len(other)==1 and number(selected[0].get('score')) is not None and number(other[0].get('score')) is not None:
                margin=number(selected[0]['score'])-number(other[0]['score'])
                row['Live position']='Leading — game ongoing' if margin>0 else 'Trailing — game ongoing' if margin<0 else 'Tied — game ongoing'
            else:row['Live position']='Live score unavailable'
        else:
            value=current_stat(record,data);row['Live stat']=value
            if value is None:row['Live position']='Live stat not reported — not assumed zero or DNP'
            else:
                line=number(record.get('line'))
                if line is not None:
                    row['Difference vs line']=round(value-line,2)
                    row['Live position']='Above line — game ongoing' if value>line else 'Below line — game ongoing' if value<line else 'At line — game ongoing'
        rows.append(row)
    return rows

def fetch_summary(sport,event_id):
    path='basketball/nba' if sport=='NBA' else 'football/nfl'
    data=json.load(urlopen('https://site.api.espn.com/apis/site/v2/sports/'+path+'/summary?event='+str(event_id),timeout=12))
    return {'data':data,'retrieved_utc':datetime.now(timezone.utc).isoformat()}

def collect_summaries(records,fetch=fetch_summary,now=None):
    now=now or datetime.now(timezone.utc)
    # One request per game, shared by all its props. Upcoming games need no repeated stat request.
    keys={(r.get('sport','NFL'),str(r['event_id'])) for r in records if utc(r['starts_utc'])<=now}
    output={}
    with ThreadPoolExecutor(max_workers=6) as pool:
        tasks={k:pool.submit(fetch,*k) for k in keys}
        for key,task in tasks.items():
            try:output[key]=task.result()
            except Exception:output[key]={'error':'Feed unavailable'}
    return output

def render_live_board(records,sport='NFL'):
    import streamlit as st
    selected=[r for r in records if r.get('sport','NFL')==sport]
    st.subheader('Live pick board — all saved predictions in one table')
    if not selected:st.info('Saved predictions will appear here automatically.');return
    now=datetime.now(timezone.utc)
    dates=sorted({utc(r['starts_utc']).astimezone(PACIFIC).date() for r in selected})
    upcoming=[d for d in dates if d>=now.astimezone(PACIFIC).date()];default=upcoming[0] if upcoming else dates[-1]
    day=st.selectbox('Pick-board game date (Pacific)',dates,index=dates.index(default),key='pick_board_date_'+sport)
    strategies=sorted({r.get('strategy','Original') for r in selected})
    chosen=st.multiselect('Pick-board strategies',strategies,default=['Original'] if 'Original' in strategies else strategies,key='pick_board_strategies_'+sport)
    selected=[r for r in selected if utc(r['starts_utc']).astimezone(PACIFIC).date()==day and r.get('strategy','Original') in chosen]
    include_moneylines=st.checkbox('Include saved moneyline picks',value=True,key='pick_board_ml_'+sport)
    if not include_moneylines:selected=[r for r in selected if r['category']!='Moneyline']
    from pick_presentation import filter_matchup
    games=sorted({r['game'] for r in selected})
    game=st.selectbox('Focus on a matchup',['All games']+games,key='pick_board_matchup_'+sport)
    selected=highest_probability(filter_matchup(selected,game),"probability")
    if game!='All games' and ' at ' in game:
        away,home=game.split(' at ',1)
        index=st.session_state.get('team_emblems',{})
        for column,name in zip(st.columns(2),(away,home)):
            team=index.get(sport+':'+name,{})
            if team.get('logo'):
                icon,label=column.columns([1,7]);icon.image(team['logo'],width=28);label.write('**'+name+'**')
            else:column.write('**'+name+'**')
    count=sum(r['category']!='Moneyline' for r in selected);moneylines=len(selected)-count
    st.caption('Sorted by frozen estimated win probability, highest first; unmodeled entries appear last.')
    st.write(f'**{count} saved props · {moneylines} moneyline picks**')
    auto=st.toggle('Auto-refresh live stats every 30 seconds',value=True,key='pick_board_auto_'+sport)
    st.caption('Uses ESPN stats, not sportsbook credits. Updates while this app session is active; feed delays and stat corrections are possible. Original lines and probabilities remain frozen. Below an Under line during a game is not a final win. Missing stats are never treated as zero or DNP.')
    @st.cache_data(ttl=25,show_spinner=False)
    def cached_fetch(league,eid):return fetch_summary(league,eid)
    @st.fragment(run_every='30s' if auto else None)
    def panel():
        if st.button('Refresh pick-board stats now',key='pick_board_refresh_'+sport):cached_fetch.clear()
        summaries=collect_summaries(selected,cached_fetch)
        rows=build_board(selected,summaries,team_assets=st.session_state.get("team_emblems",{}))
        from pick_presentation import pick_status,result_indicator
        original={r['id']:r for r in selected}
        rows=[{'Result':result_indicator(row),'Status':pick_status(original[row['Pick ID']],row),**row} for row in rows]
        tracking_tab,cards_tab=st.tabs(['Live tracking table','Pick cards'])
        with tracking_tab:
            st.caption('✅ Win · ❌ Loss · ➖ Push · ⏳ Pending or review needed. Win/loss marks appear only after final grading.')
            if rows:
                st.dataframe(rows,hide_index=True,use_container_width=True,column_config={"Team logo":st.column_config.ImageColumn("Team",width="small")},height=min(1000,max(200,35*(len(rows)+1))))
                wins=sum(r['Final result']=='Win' for r in rows);losses=sum(r['Final result']=='Loss' for r in rows)
                st.caption(f'Final only: {wins} wins, {losses} losses. Other picks remain pending or unresolved. Display refreshed {datetime.now(PACIFIC).strftime("%I:%M:%S %p Pacific")}. Final results are saved by the existing scheduled grading job.')
            else:st.info('No saved picks match the selected date and strategies.')
        with cards_tab:
            from pick_cards import render_pick_cards
            render_pick_cards(selected,sport,live_rows=rows)
    panel()
    from saved_pick_explanation import render_saved_explanations
    render_saved_explanations(selected,sport)
