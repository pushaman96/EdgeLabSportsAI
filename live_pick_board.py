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
        if record.get('category')=='Game total points':
            assets=dict(team_assets or {})
            if valid_data:
                from team_emblems import team_index
                assets.update(team_index(valid_data.get('header',{}).get('competitions',[]),record.get('sport','NFL')))
            names=record['game'].split(' at ')
            if len(names)==2:
                away,home=[assets.get(record.get('sport','NFL')+':'+name,{}) for name in names]
                row['Team logo']=away.get('logo');row['Opponent logo']=home.get('logo')
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
            if graded['result']!='Pending':
                row['Final result']=graded['result'];row['Live stat']=number(graded.get('actual'))
                row['Live position']='Final'
            elif row['Final result'] in ('Win','Loss','Push'):
                row['Live position']='Final — saved grade; current feed statistic incomplete'
            else:
                row['Live position']='Final — stat missing; settlement review needed'
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
    from runtime_health import summary
    return summary('basketball/nba'if sport=='NBA'else'football/nfl',event_id)


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

def current_moneyline_board(saved,records,sport,day,now=None):
    """Show fresh session analysis separately; never rewrite frozen history."""
    now=now or datetime.now(timezone.utc)
    if not saved or len(saved)<5 or saved[0]!=str(day) or saved[4]!=sport:return []
    try:
        if not 0<=(now-utc(saved[3])).total_seconds()<=900:return []
    except (TypeError,ValueError):return []
    groups={}
    for record in records:
        if record.get('sport','NFL')==sport:
            groups.setdefault(record['game'],[]).append(record)
    output={}
    for row in saved[2]:
        game=row.get('Game');frozen=groups.get(game,[])
        p=number(row.get('Model win %',row.get('Estimated win %')))
        if not frozen or row.get('Decision')=='Pass' or row.get('Moneyline selection policy')!='most-likely-winner-v1' or p is None or p<=50:continue
        try:
            if not 0<=(now-utc(row['Quote updated UTC'])).total_seconds()<=900 or any(utc(r['starts_utc'])<=now for r in frozen):continue
        except (KeyError,TypeError,ValueError):continue
        team=row.get('Team to research')or row.get('Player')
        if team not in game.split(' at '):continue
        original=', '.join(sorted({r['player'] for r in frozen if r.get('category')=='Moneyline'})) or 'No earlier saved moneyline'
        output[game]={'Game':game,'Current predicted winner':team,'Estimated win %':p,'Earlier frozen selection':original,'Change':'Changed from saved selection' if any(r['player']!=team for r in frozen if r.get('category')=='Moneyline') else 'Same as saved selection','Analyzed UTC':saved[3],'Status':'Experimental current forecast; earlier pick remains in historical results'}
    return sorted(output.values(),key=lambda r:-r['Estimated win %'])

def latest_moneyline_records(records):
    """Latest saved moneyline per game/strategy; preserve every older record."""
    groups={};visible=[];earlier=[]
    for row in records:
        if row.get('category')!='Moneyline':visible.append(row);continue
        groups.setdefault((row.get('sport','NFL'),str(row.get('event_id')),row.get('strategy','Original')),[]).append(row)
    for values in groups.values():
        def saved_time(row):
            try:return utc(row.get('published_utc')).timestamp()
            except (ValueError,TypeError,OverflowError):return float('-inf')
        latest=max(saved_time(r) for r in values)
        newest=[r for r in values if saved_time(r)==latest]
        if len({r.get('player') for r in newest})!=1:
            earlier.extend(values);continue
        chosen=min(newest,key=lambda r:str(r.get('id','')))
        visible.append(chosen)
        earlier.extend(r for r in values if r is not chosen)
    return visible,earlier

def render_live_board(records,sport='NFL'):
    import streamlit as st
    selected=[r for r in records if r.get('sport','NFL')==sport]
    st.subheader('Live pick board — grouped by model probability')
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
    selected,earlier_moneylines=latest_moneyline_records(filter_matchup(selected,game))
    selected=highest_probability(selected,"probability")
    if game!='All games' and ' at ' in game:
        away,home=game.split(' at ',1)
        index=st.session_state.get('team_emblems',{})
        for column,name in zip(st.columns(2),(away,home)):
            team=index.get(sport+':'+name,{})
            if team.get('logo'):
                icon,label=column.columns([1,7]);icon.image(team['logo'],width=28);label.write('**'+name+'**')
            else:column.write('**'+name+'**')
    if sport=='NFL':
        from team_emblems import pick_team,roster_emblems
        assets=st.session_state.get('team_emblems',{})
        missing=[r for r in selected if r.get('category') not in ('Moneyline','Game total points') and utc(r['starts_utc'])>now and not pick_team(r,index=assets)]
        if missing:
            from nfl_prop_model import current_roster
            @st.cache_data(ttl=900,show_spinner=False)
            def emblem_roster(team_id):
                try:return current_roster(team_id)
                except Exception:return []
            teams={name for r in missing for name in r['game'].split(' at ')}
            with ThreadPoolExecutor(max_workers=4) as pool:
                tasks={name:pool.submit(emblem_roster,assets[sport+':'+name]['id']) for name in teams if assets.get(sport+':'+name,{}).get('id')}
                rosters={name:task.result() for name,task in tasks.items()}
            st.session_state['team_emblems']=roster_emblems(missing,assets,rosters,sport)
    count=sum(r['category']!='Moneyline' for r in selected);moneylines=len(selected)-count
    st.caption('Sorted by frozen estimated win probability, highest first; unmodeled entries appear last.')
    st.write(f'**{count} saved props · {moneylines} moneyline picks**')
    latest_moneylines=current_moneyline_board(st.session_state.get('moneyline_history_candidates'),selected,sport,day)
    if latest_moneylines:
        st.write('**Current moneyline forecast — latest analysis**')
        st.dataframe(latest_moneylines,hide_index=True,use_container_width=True)
        st.caption('The current forecast above can differ from an earlier saved pick below. Updating the forecast never changes the original pick or its eventual result.')
    elif moneylines:
        st.info('Main table shows the latest saved moneyline per game. Earlier versions are in moneyline history below. Use Compare model with current moneylines for a fresh analysis of loaded prices; no new odds request is needed.')

    auto=st.toggle('Auto-refresh live stats every 30 seconds',value=True,key='pick_board_auto_'+sport)
    st.caption('Uses ESPN stats, not sportsbook credits. Updates while this app session is active; feed delays and stat corrections are possible. Original lines and probabilities remain frozen. Below an Under line during a game is not a final win. Missing stats are never treated as zero or DNP.')
    @st.cache_data(ttl=25,show_spinner=False)
    def cached_fetch(league,eid):return fetch_summary(league,eid)
    @st.cache_data(ttl=60,show_spinner=False)
    def cached_grades():
        from settlement_sync import fetch_grades
        return fetch_grades(with_status=True)
    @st.fragment(run_every='30s' if auto else None)
    def panel():
        if st.button('Refresh pick-board stats now',key='pick_board_refresh_'+sport):
            from runtime_health import invalidate_public
            invalidate_public('summary');invalidate_public('settlement')
            cached_fetch.clear();cached_grades.clear()
        from settlement_sync import merge_grades
        try:
            updates,grade_meta=cached_grades()
            st.session_state['latest_settlement_grades']=updates
            st.caption(('Permanent history delayed — last-good final grades from 'if grade_meta['stale']else'Saved final grades synchronized; checked ')+grade_meta['retrieved_utc'])
        except Exception:
            updates=st.session_state.get('latest_settlement_grades',[])
            st.caption('Permanent grade refresh unavailable; retaining last verified results and retrying.')
        current=merge_grades(selected,updates)
        # Remember verified settlements for full-page accuracy and review panels.
        st.session_state['ledger_live_grades']=merge_grades(
            st.session_state.get('ledger_live_grades',[])+[r for r in current if r['id'] not in {g['id'] for g in st.session_state.get('ledger_live_grades',[])}],updates)
        prior=merge_grades(earlier_moneylines,updates)
        summaries=collect_summaries(current+prior,cached_fetch)
        if any(v.get('stale')for v in summaries.values()):st.caption('Some game feeds are delayed; showing last-good stats with their original timestamps. Automatic retry is pending.')
        rows=build_board(current,summaries,team_assets=st.session_state.get("team_emblems",{}))
        forecasts={r['Game']:r for r in current_moneyline_board(st.session_state.get('moneyline_history_candidates'),current,sport,day)}
        for row in rows:
            if row['Category']=='Moneyline':
                forecast=forecasts.get(row['Game'])
                row['Recommendation status']='Earlier saved pick — current forecast selects '+forecast['Current predicted winner'] if forecast and forecast['Current predicted winner']!=row['Player / team'] else 'Latest saved moneyline; original forecast remains frozen'

        from pick_presentation import pick_status,result_indicator
        original={r['id']:r for r in current}
        rows=[{'Result':result_indicator(row),'Status':pick_status(original[row['Pick ID']],row),**row} for row in rows]
        tracking_tab,cards_tab=st.tabs(['Live tracking table','Pick cards'])
        with tracking_tab:
            st.caption('✅ Win · ❌ Loss · ➖ Push · ⏳ Pending or review needed. Win/loss marks appear only after final grading.')
            if rows:
                from probability_labels import grouped, LEGEND
                st.caption(LEGEND)
                for group, values in grouped(rows).items():
                    if not values:continue
                    st.write('**'+group+' — '+str(len(values))+' picks**')
                    st.dataframe(values,hide_index=True,use_container_width=True,column_config={"Team logo":st.column_config.ImageColumn("Team / total away",width="small"),"Opponent logo":st.column_config.ImageColumn("Total home",width="small")},height=min(1000,max(200,35*(len(values)+1))))
                wins=sum(r['Final result']=='Win' for r in rows);losses=sum(r['Final result']=='Loss' for r in rows)
                st.caption(f'Final only: {wins} wins, {losses} losses. Other picks remain pending or unresolved. Display refreshed {datetime.now(PACIFIC).strftime("%I:%M:%S %p Pacific")}. Final results are saved by the existing scheduled grading job.')
            else:st.info('No saved picks match the selected date and strategies.')
        with cards_tab:
            from pick_cards import render_pick_cards
            render_pick_cards(current,sport,live_rows=rows)
        if prior:
            with st.expander('Earlier moneyline history — replaced selections',expanded=False):
                st.caption('Earlier versions are retained for original-pick grading and accuracy reports. They are not additional current recommendations. Main-table counts cover displayed latest selections only.')
                history_rows=build_board(prior,summaries,team_assets=st.session_state.get('team_emblems',{}))
                for row in history_rows:row['Recommendation status']='Replaced — history only'
                st.dataframe(history_rows,hide_index=True,use_container_width=True,column_config={'Team logo':st.column_config.ImageColumn('Team',width='small')})

    panel()
    from saved_pick_explanation import render_saved_explanations
    render_saved_explanations(selected,sport)


