"""ESPN usage measurements and completed-game archives. No live model fitting."""
import json,math,hashlib
from collections import defaultdict,Counter
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import urlopen

def number(value):
    try:
        n=float(str(value).replace(',',''))
        return n if math.isfinite(n) else None
    except (ValueError,TypeError):return None

def usage_snapshot(data):
    header=data.get('header',{});competition=header.get('competitions',[{}])[0]
    names={str(t['team']['id']):t['team'].get('displayName','Team') for t in competition.get('competitors',[]) if t.get('team',{}).get('id')}
    players=[];teams=[]
    for block in data.get('boxscore',{}).get('players',[]):
        team=block.get('team',{}).get('displayName','Team');athletes={};totals={}
        for group in block.get('statistics',[]):
            kind=group.get('name');fields={'passing':('Passing attempts','C/ATT'),'rushing':('Carries','CAR'),'receiving':('Targets','TGTS')}
            if kind not in fields:continue
            field,label=fields[kind];values=[]
            for a in group.get('athletes',[]):
                ident=a.get('athlete',{});key=str(ident.get('id') or ident.get('displayName'))
                row=athletes.setdefault(key,{'Team':team,'Player':ident.get('displayName','Unknown')})
                stats=dict(zip(group.get('labels',[]),a.get('stats',[])))
                raw=stats.get(label)
                if label=='C/ATT' and raw is not None:raw=str(raw).split('/')[-1]
                value=number(raw)
                if value is not None:row[field]=value;values.append(value)
                if kind=='receiving' and number(stats.get('REC')) is not None:row['Receptions']=number(stats['REC'])
            totals[field]=sum(values) if values else None
        attempts=totals.get('Passing attempts');carries=totals.get('Carries')
        denominator=attempts+carries if attempts is not None and carries is not None else None
        teams.append({'Team':team,**totals,'Pass attempt %':round(100*attempts/denominator,1) if denominator else None,'Rush attempt %':round(100*carries/denominator,1) if denominator else None})
        for row in athletes.values():
            for field in ('Passing attempts','Carries','Targets'):
                total=totals.get(field)
                row[field+' share %']=round(100*row[field]/total,1) if field in row and total else None
            players.append(row)
    grouped=defaultdict(Counter);seen=set();unknown=0
    drives=list(data.get('drives',{}).get('previous',[]));current=data.get('drives',{}).get('current')
    if isinstance(current,dict):drives.append(current)
    for drive in drives:
        for play in drive.get('plays',[]):
            pid=play.get('id')
            if not pid or pid in seen:continue
            seen.add(pid)
            text=str(play.get('text','')).lower();kind=str(play.get('type',{}).get('text','')).lower()
            if 'no play' in text or 'penalty' in kind:continue
            if 'kneel' in text or 'kneel' in kind:category='Kneels'
            elif 'spike' in kind or 'spikes the ball' in text:category='Spikes'
            elif 'sack' in kind or 'sacked' in text:category='Sacks'
            elif 'scrambl' in text:category='QB scrambles'
            elif any(x in kind for x in ('pass','interception')):category='Pass plays'
            elif 'rush' in kind:category='Designed runs'
            else:
                if play.get('start',{}).get('down',0)>0:unknown+=1
                continue
            team_id=str(play.get('start',{}).get('team',{}).get('id') or drive.get('team',{}).get('id',''))
            period=play.get('period',{}).get('number')
            if not team_id or not isinstance(period,int):unknown+=1;continue
            grouped[(names.get(team_id,team_id),period)][category]+=1
    quarters=[]
    for (team,period),counts in sorted(grouped.items()):
        passes=counts['Pass plays']+counts['Sacks']+counts['QB scrambles'];runs=counts['Designed runs'];total=passes+runs
        quarters.append({'Team':team,'Quarter':period,**{k:counts[k] for k in ('Pass plays','Designed runs','QB scrambles','Sacks','Kneels','Spikes')},'Classified pass-call %':round(100*passes/total,1) if total else None,'Classified designed-run %':round(100*runs/total,1) if total else None})
    from game_script import play_review
    script=play_review(data)
    return {'game_script':script,'event_id':str(header.get('id','')),'completed':bool(competition.get('status',{}).get('type',{}).get('completed')),'period':competition.get('status',{}).get('period'),'clock':competition.get('status',{}).get('displayClock'),'retrieved_utc':datetime.now(timezone.utc).isoformat(),'teams':teams,'players':players,'quarters':quarters,'unique_feed_plays':len(seen),'unclassified_scrimmage_plays':unknown,'source':'ESPN summary; box-score usage and classified drive plays'}

def render_live_usage(data):
    import streamlit as st
    snapshot=usage_snapshot(data)
    st.subheader('NFL live usage — team run/pass and player workload')
    st.caption('Live measurements only; pregame picks remain frozen. Updated with Refresh scores and live stats. No sportsbook credits used.')
    if snapshot['teams']:st.dataframe(snapshot['teams'],hide_index=True,use_container_width=True)
    st.caption('Attempt percentages = reported passing attempts versus rushing carries. These exclude sacks from the denominator and include scrambles/kneels in official rushing totals; they are not designed play-call percentages.')
    if snapshot['players']:st.dataframe(snapshot['players'],hide_index=True,use_container_width=True)
    st.caption('Target and carry shares use the sum of reported player totals. Missing values stay unknown. Snap counts, routes and time on field are not supplied by this box score.')
    if snapshot['quarters']:
        st.write('Play-calling by quarter — classified available plays')
        st.dataframe(snapshot['quarters'],hide_index=True,use_container_width=True)
        st.caption(f"Based on {snapshot['unique_feed_plays']} unique feed plays; {snapshot['unclassified_scrimmage_plays']} scrimmage plays could not be classified. Pass calls include sacks and identified scrambles; designed runs exclude kneels. Spikes and no-play penalties are excluded. Feed coverage may be incomplete and classification is descriptive, not official charting.")
    else:st.info('Play-by-play usage is not available from ESPN yet; reported box-score usage remains above.')
    st.write('Passing volume by game situation')
    st.dataframe(snapshot['game_script']['attempt_totals'],hide_index=True,use_container_width=True)
    st.dataframe(snapshot['game_script']['score_states'],hide_index=True,use_container_width=True)
    st.caption('Score states use the score before each available play. Regulation/overtime totals are shown only when classified attempts match the official team box score. This describes the game; it does not prove why the forecast missed.')
    if snapshot['completed']:
        try:reviews=json.loads(Path('game_usage_history.json').read_text())['games'].get(snapshot['event_id'],{}).get('forecast_reviews',[])
        except (OSError,ValueError,KeyError):reviews=[]
        if reviews:
            st.write('Saved pregame workload versus final usage')
            st.dataframe(reviews,hide_index=True,use_container_width=True)
        else:st.info('Final usage is visible now. Tracked-game forecast comparisons appear after the scheduled archive job runs.')
    st.caption('Completed-game usage for tracked NFL games is archived by the scheduled grading job. After grading, eligible frozen forecasts update experimental per-game forecast and probability adjustments. Completed weekly histories also update the base models as feeds arrive. The underlying trees are not automatically retrained.')

def archive_completed_usage(records,fetch=None,path='game_usage_history.json'):
    fetch=fetch or (lambda eid:json.load(urlopen('https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event='+eid,timeout=20)))
    target=Path(path)
    try:archive=json.loads(target.read_text())
    except (OSError,ValueError):archive={'games':{}}
    added=0
    for eid in sorted({str(r['event_id']) for r in records if r.get('sport','NFL')=='NFL' and r.get('event_id')}):
        if archive['games'].get(eid,{}).get('completed') and archive['games'][eid].get('game_script') and archive['games'][eid].get('situations',{}).get('schema')==1 and archive['games'][eid]['situations'].get('plays'):continue
        try:
            data=fetch(eid)
            snap=usage_snapshot(data)
            if snap['event_id']!=eid or not snap['completed']:continue
            reviews=[]
            fields={'Passing yards':'Passing attempts','Passing attempts':'Passing attempts','Passing completions':'Passing attempts','Passing touchdowns':'Passing attempts','Rushing yards':'Carries','Rushing attempts':'Carries','Receiving yards':'Targets','Receptions':'Targets'}
            for record in records:
                if str(record.get('event_id'))!=eid or record.get('sport','NFL')!='NFL':continue
                field=fields.get(record.get('category'));expected=number(record.get('expected_opportunities'))
                matched=[p for p in snap['players'] if p['Player']==record.get('player')]
                actual=number(matched[0].get(field)) if len(matched)==1 and field else None
                if expected is not None:reviews.append({'Pick ID':record.get('id'),'Player':record.get('player'),'Category':record.get('category'),'Model':record.get('model'),'Expected opportunities':expected,'Reported final opportunities':actual,'Opportunity miss':actual-expected if actual is not None else None})
            from game_situations import situation_snapshot, forecast_situation_reviews
            situations=situation_snapshot(data,'NFL')
            situations['forecast_reviews']=forecast_situation_reviews(records,situations)
            snap['situations']=situations
            snap['forecast_reviews']=reviews
            archive['games'][eid]=snap;added+=1
        except (OSError,ValueError,KeyError,TypeError):continue
    # NBA uses its own sport-qualified keys; forecasts and box-score grades remain separate.
    from game_situations import situation_snapshot, forecast_situation_reviews
    nba_fetch=lambda eid:json.load(urlopen('https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event='+eid,timeout=20))
    for eid in sorted({str(r['event_id']) for r in records if r.get('sport')=='NBA' and r.get('event_id')}):
        key='NBA:'+eid
        if archive['games'].get(key,{}).get('situations',{}).get('plays'):continue
        try:
            data=nba_fetch(eid)
            snap=situation_snapshot(data,'NBA')
            if snap['event_id']!=eid or not snap['completed']:continue
            snap['forecast_reviews']=forecast_situation_reviews(records,snap)
            archive['games'][key]={'completed':True,'situations':snap};added+=1
        except (OSError,ValueError,KeyError,TypeError):continue
    if added:target.write_text(json.dumps(archive,indent=2)+'\n')
    return added

