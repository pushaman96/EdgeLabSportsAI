"""Durable published ledger plus completed-game grading. No bets are placed."""
import json, math, hashlib, base64
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import urlopen
REPO='pushaman96/EdgeLabSportsAI'
LEDGER='published_picks.json'
SUMMARY='https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event='

def utc(value):return datetime.fromisoformat(value.replace('Z','+00:00'))

def make_record(row,event_id,start,now=None,strategy='Original'):
    now=now or datetime.now(timezone.utc)
    if now>=utc(start):raise ValueError('Publish before kickoff.')
    if not 0<=(now-utc(row['Quote updated UTC'])).total_seconds()<=900:raise ValueError('Refresh the quote before publishing.')
    if row['Decision']=='Pass' or row['Category']!='Passing yards':raise ValueError('Only qualifying passing-yard picks are supported.')
    line=float(row['Line']);odds=float(row['Odds']);prob=float(row['Estimated win %'])/100
    if not all(math.isfinite(x) for x in (line,odds,prob)) or line<0 or line%1!=.5 or abs(odds)<100 or not 0<prob<1:raise ValueError('Invalid line, price or probability.')
    identity='|'.join([str(event_id),row['Player'],'Passing yards',strategy])
    return {'id':hashlib.sha256(identity.encode()).hexdigest()[:20],'event_id':str(event_id),'game':row['Game'],'player':row['Player'],'category':'Passing yards','direction':row['Selection'],'line':line,'odds':odds,'probability':prob,'sportsbook':row['Sportsbook'],'model':row.get('Model','Experimental'),'strategy':strategy,'published_utc':now.isoformat(),'starts_utc':start,'evidence':'Published before kickoff','result':'Pending','actual':None,'profit_per_1':None}

def grade_record(record,data):
    r=dict(record)
    if r.get('result')!='Pending':return r
    competitions=data.get('header',{}).get('competitions',[])
    if not competitions or not competitions[0].get('status',{}).get('type',{}).get('completed'):return r
    if str(data.get('header',{}).get('id'))!=str(r['event_id']):raise ValueError('Game identity mismatch.')
    values=[]
    for team in data.get('boxscore',{}).get('players',[]):
        for group in team.get('statistics',[]):
            if group.get('name')!='passing':continue
            labels=group.get('labels',[])
            for entry in group.get('athletes',[]):
                if entry.get('athlete',{}).get('displayName')==r['player']:
                    stats=dict(zip(labels,entry.get('stats',[])))
                    if 'YDS' in stats:values.append(float(stats['YDS']))
    if len(values)!=1:
        r['grading_note']='Player total not uniquely reported; manual settlement review required.'
        return r
    actual=values[0];line=r['line'];win=actual<line if r['direction']=='Under' else actual>line
    result='Push' if actual==line else 'Win' if win else 'Loss'
    odds=r['odds'];profit=odds/100 if odds>0 else 100/abs(odds)
    r.update(actual=actual,result=result,profit_per_1=profit if result=='Win' else -1 if result=='Loss' else 0,graded_utc=datetime.now(timezone.utc).isoformat(),grading_note='Final ESPN yards; platform-specific void rules and fees are not modeled.')
    return r

def grade_all(records,fetch=None):
    fetch=fetch or (lambda eid:json.load(urlopen(SUMMARY+eid,timeout=20)))
    cache={};out=[]
    for record in records:
        if record.get('result')!='Pending':out.append(record);continue
        eid=record['event_id']
        try:
            if eid not in cache:cache[eid]=fetch(eid)
            out.append(grade_record(record,cache[eid]))
        except (OSError,ValueError,KeyError,TypeError):out.append(record)
    return out

def render_history():
    import streamlit as st
    st.divider();st.header('Published pick history and results')
    try:records=json.loads(Path(LEDGER).read_text())['records']
    except (OSError,ValueError,KeyError):st.info('No published picks yet.');return
    st.caption('Original and cushion strategies are separate. Historical imports are labeled and excluded from the prospective record. Returns assume $1 straight bets at recorded prices, excluding fees and platform void rules. No guaranteed returns.')
    if st.button('Refresh completed-game grades',key='ledger_refresh'):
        st.session_state['ledger_live_grades']=grade_all(records)
    records=st.session_state.get('ledger_live_grades',records)
    evidence=st.selectbox('Results record',['Published before kickoff','Historical import'],key='ledger_evidence')
    strategy=st.selectbox('Strategy',['Original','Cushion'],key='ledger_strategy')
    selected=[r for r in records if r['evidence']==evidence and r['strategy']==strategy]
    settled=[r for r in selected if r['result'] in ('Win','Loss')]
    if settled:
        wins=sum(r['result']=='Win' for r in settled);profit=sum(r['profit_per_1'] for r in settled)
        st.write(f"{wins} wins / {len(settled)-wins} losses · Net per $1 per pick: ${profit:.2f} · ROI: {profit/len(settled):.1%}")
        brier=sum((r['probability']-(r['result']=='Win'))**2 for r in settled)/len(settled)
        st.write(f"Probability accuracy (Brier, lower is better): {brier:.4f}")
        bins=[]
        for lo in range(0,100,10):
            group=[r for r in settled if lo<=r['probability']*100<lo+10]
            if group:bins.append({'Probability range':f'{lo}–{lo+10}%','Picks':len(group),'Average estimate %':round(100*sum(r['probability'] for r in group)/len(group),1),'Actual win %':round(100*sum(r['result']=='Win' for r in group)/len(group),1)})
        st.dataframe(bins,hide_index=True,use_container_width=True)
    else:st.info('No settled picks in this record yet.')
    if selected:st.dataframe(selected,hide_index=True,use_container_width=True)
    st.download_button('Download permanent pick ledger',json.dumps({'records':records},indent=2),file_name='kamikaze_picks_published_history.json',mime='application/json',key='ledger_download')

def publish_rows(rows,events,cushions=()):
    import streamlit as st
    import requests
    try:token=st.secrets.get('PICK_HISTORY_GITHUB_TOKEN','')
    except Exception:token=''
    if not token:
        st.caption('Permanent publishing needs the administrator’s PICK_HISTORY_GITHUB_TOKEN in Streamlit secrets. Viewing and grading history do not require it.')
        return
    with st.expander('Administrator: publish current original and cushion picks'):
        password=st.text_input('Publishing password',type='password',key='ledger_password')
        if not st.button('Publish qualifying picks permanently',key='ledger_publish'):return
        if not st.secrets.get('PICK_HISTORY_ADMIN_PASSWORD') or password!=st.secrets.get('PICK_HISTORY_ADMIN_PASSWORD'):
            st.warning('Administrator password required.');return
        try:
            new=[]
            to_publish=[(row,'Original') for row in rows]
            for c in cushions:
                if c['Cushion decision']=='Pass':continue
                original=next(r for r in rows if r['Player']==c['Player'] and r['Game']==c['Game'])
                alternate=dict(original,Line=c['Available line'],Odds=c['Actual odds'],Sportsbook=c['Sportsbook'])
                alternate['Estimated win %']=c['Recalculated win %'];alternate['Quote updated UTC']=c['Quote updated UTC']
                to_publish.append((alternate,'Cushion'))
            for row,strategy in to_publish:
                match=next((e for e in events if e['away_team']+' at '+e['home_team']==row['Game']),None)
                if match:
                    # Resolve the ESPN event identity independently of the odds-provider ID.
                    board=requests.get('https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard',params={'dates':utc(match['commence_time']).strftime('%Y%m%d')},timeout=15).json()
                    espn=next((e for e in board.get('events',[]) if e.get('name')==row['Game'] and abs((utc(e['date'])-utc(match['commence_time'])).total_seconds())<3600),None)
                    if espn:new.append(make_record(row,espn['id'],match['commence_time'],strategy=strategy))
            headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json'}
            url=f'https://api.github.com/repos/{REPO}/contents/{LEDGER}'
            response=requests.get(url,headers=headers,params={'ref':'main'},timeout=15);response.raise_for_status();payload=response.json()
            data=json.loads(base64.b64decode(payload['content']));existing={r['id'] for r in data['records']}
            new=[r for r in new if r['id'] not in existing]
            if not new:st.info('No new eligible passing picks to publish.');return
            data['records'].extend(new)
            response=requests.put(url,headers=headers,json={'message':'Publish frozen pregame paper picks','branch':'main','sha':payload['sha'],'content':base64.b64encode(json.dumps(data,indent=2).encode()).decode()},timeout=20);response.raise_for_status()
            st.success(f'{len(new)} picks saved permanently. History appears after the app updates.')
        except (requests.exceptions.RequestException,ValueError,KeyError,TypeError):st.warning('Publishing did not complete. Refresh and check history before retrying.')

if __name__=='__main__':
    path=Path(LEDGER);data=json.loads(path.read_text());data['records']=grade_all(data['records']);path.write_text(json.dumps(data,indent=2)+'\n')
