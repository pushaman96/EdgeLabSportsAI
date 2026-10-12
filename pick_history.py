"""Durable published ledger plus completed-game grading. No bets are placed."""
import json, math, hashlib, base64
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import urlopen
REPO='pushaman96/EdgeLabSportsAI'
LEDGER='published_picks.json'
SUMMARY='https://site.api.espn.com/apis/site/v2/sports/{sport}/summary?event='

def utc(value):return datetime.fromisoformat(value.replace('Z','+00:00'))

def make_record(row,event_id,start,now=None,strategy='Original'):
    now=now or datetime.now(timezone.utc)
    if now>=utc(start):raise ValueError('Publish before kickoff.')
    if not 0<=(now-utc(row['Quote updated UTC'])).total_seconds()<=900:raise ValueError('Refresh the quote before publishing.')
    category=row['Category']
    if row['Decision']=='Pass' or category not in ('Passing yards','Rushing yards','Receiving yards','Moneyline','Points','Rebounds','Assists','Three-pointers made','Steals','Blocks'):raise ValueError('Unsupported pick category.')
    line=None if category=='Moneyline' else float(row['Line']);odds=float(row['Odds']);prob=float(row['Estimated win %'])/100 if row.get('Estimated win %') is not None else None
    if not math.isfinite(odds) or abs(odds)<100 or (prob is not None and (not math.isfinite(prob) or not 0<prob<1)):raise ValueError('Invalid price or probability.')
    if prob is None and strategy!='Manual':raise ValueError('Model picks need probabilities.')
    if line is not None and (not math.isfinite(line) or line<0 or (strategy!='Manual' and line%1!=.5)):raise ValueError('Invalid prop line.')
    identity='|'.join([str(event_id),row['Player'],category,strategy])
    return {'id':hashlib.sha256(identity.encode()).hexdigest()[:20],'sport':row.get('Sport','NFL'),'event_id':str(event_id),'game':row['Game'],'player':row['Player'],'category':category,'direction':row['Selection'],'line':line,'odds':odds,'probability':prob,'sportsbook':row['Sportsbook'],'model':row.get('Model','Experimental'),'strategy':strategy,'published_utc':now.isoformat(),'starts_utc':start,'evidence':'Published before kickoff','result':'Pending','actual':None,'profit_per_1':None}

def grade_record(record,data):
    r=dict(record)
    if r.get('result')!='Pending':return r
    competitions=data.get('header',{}).get('competitions',[])
    if not competitions or not competitions[0].get('status',{}).get('type',{}).get('completed'):return r
    if str(data.get('header',{}).get('id'))!=str(r['event_id']):raise ValueError('Game identity mismatch.')
    if r['category']=='Moneyline':
        teams=competitions[0].get('competitors',[])
        selected=[t for t in teams if t.get('team',{}).get('displayName')==r['player']]
        if len(teams)!=2 or len(selected)!=1:return r
        scores=[float(t['score']) for t in teams]
        result='Push' if scores[0]==scores[1] else 'Win' if float(selected[0]['score'])==max(scores) else 'Loss'
        odds=r['odds'];profit=odds/100 if odds>0 else 100/abs(odds)
        r.update(result=result,actual={t['team']['displayName']:t['score'] for t in teams},profit_per_1=profit if result=='Win' else -1 if result=='Loss' else 0,graded_utc=datetime.now(timezone.utc).isoformat(),grading_note='Final ESPN score; tied two-way moneyline recorded as Push. Platform rules may differ.')
        return r
    values=[]
    for team in data.get('boxscore',{}).get('players',[]):
        for group in team.get('statistics',[]):
            nba=r.get('sport')=='NBA'
            if not nba and group.get('name')!={'Passing yards':'passing','Rushing yards':'rushing','Receiving yards':'receiving'}.get(r['category']):continue
            labels=group.get('labels',[])
            for entry in group.get('athletes',[]):
                if entry.get('athlete',{}).get('displayName')==r['player']:
                    stats=dict(zip(labels,entry.get('stats',[])))
                    label={'Points':'PTS','Rebounds':'REB','Assists':'AST','Three-pointers made':'3PT','Steals':'STL','Blocks':'BLK'}.get(r['category'],'YDS')
                    if label in stats:values.append(float(str(stats[label]).split('/')[0].split('-')[0]))
    if len(values)!=1:
        r['grading_note']='Player total not uniquely reported; manual settlement review required.'
        return r
    actual=values[0];line=r['line'];win=actual<line if r['direction']=='Under' else actual>line
    result='Push' if actual==line else 'Win' if win else 'Loss'
    odds=r['odds'];profit=odds/100 if odds>0 else 100/abs(odds)
    r.update(actual=actual,result=result,profit_per_1=profit if result=='Win' else -1 if result=='Loss' else 0,graded_utc=datetime.now(timezone.utc).isoformat(),grading_note='Final ESPN yards; platform-specific void rules and fees are not modeled.')
    return r

def grade_all(records,fetch=None):
    fetch=fetch or (lambda eid,sport:json.load(urlopen(SUMMARY.format(sport='basketball/nba' if sport=='NBA' else 'football/nfl')+eid,timeout=20)))
    cache={};out=[]
    for record in records:
        if record.get('result')!='Pending':out.append(record);continue
        eid=record['event_id']
        try:
            if eid not in cache:cache[eid]=fetch(eid,record.get('sport','NFL'))
            out.append(grade_record(record,cache[eid]))
        except (OSError,ValueError,KeyError,TypeError):out.append(record)
    return out

def render_history(sport='NFL'):
    import streamlit as st
    st.divider();st.header('Published pick history and results')
    try:records=json.loads(Path(LEDGER).read_text())['records']
    except (OSError,ValueError,KeyError):st.info('No published picks yet.');return
    st.subheader('Personal paper-pick tracking')
    st.caption('Use Save picks for testing beneath the analyzed shortlist. Personal records stay in this browser session. Download the JSON before closing or restarting, and restore it here next time. This is not automatic permanent storage.')
    uploaded=st.file_uploader('Restore saved paper-pick JSON',type=['json'],key='personal_history_restore')
    if uploaded is not None and st.button('Restore paper-pick records',key='personal_history_restore_button'):
        try:
            imported=json.loads(uploaded.getvalue())['records']
            if not isinstance(imported,list) or len(imported)>5000:raise ValueError()
            clean=[]
            for r in imported:
                if r['category'] not in ('Passing yards','Rushing yards','Receiving yards','Moneyline','Points','Rebounds','Assists','Three-pointers made','Steals','Blocks'):raise ValueError()
                if r['strategy'] not in ('Original','Cushion','Manual') or abs(float(r['odds']))<100:raise ValueError()
                if r.get('probability') is not None and not 0<float(r['probability'])<1:raise ValueError()
                if not math.isfinite(float(r['odds'])):raise ValueError()
                if r['evidence']!='Historical import':
                    if utc(r['published_utc'])>=utc(r['starts_utc']):raise ValueError()
                    r=dict(r,evidence='Personal paper record')
                # Recheck grades from ESPN instead of trusting imported outcomes.
                r=dict(r,result='Pending',actual=None,profit_per_1=None)
                clean.append(r)
            st.session_state['personal_paper_records']=clean
            st.session_state.pop('ledger_live_grades',None)
            st.success('Restored. Refresh completed-game grades to verify results. Imported personal records remain user-editable evidence.')
        except (ValueError,KeyError,TypeError):st.warning('This file could not be restored as a paper-pick ledger.')
    merged={r['id']:r for r in records}
    for r in st.session_state.get('personal_paper_records',[]):merged.setdefault(r['id'],r)
    records=list(merged.values())
    st.caption('Original and cushion strategies are separate. Historical imports are labeled and excluded from the prospective record. Returns assume $1 straight bets at recorded prices, excluding fees and platform void rules. No guaranteed returns.')
    if st.button('Refresh completed-game grades',key='ledger_refresh'):
        st.session_state['ledger_live_grades']=grade_all(records)
    graded={r['id']:r for r in st.session_state.get('ledger_live_grades',[])}
    records=[graded.get(r['id'],r) for r in records]
    all_records=records
    records=[r for r in records if r.get('sport','NFL')==sport]
    evidence=st.selectbox('Results record',['Personal paper record','Published before kickoff','Historical import'],key='ledger_evidence')
    strategy=st.selectbox('Strategy',['Original','Cushion','Manual'],key='ledger_strategy')
    selected=[r for r in records if r['evidence']==evidence and r['strategy']==strategy]
    category=st.selectbox('Pick category',['All']+sorted({r['category'] for r in selected}),key='ledger_category')
    if category!='All':selected=[r for r in selected if r['category']==category]
    settled=[r for r in selected if r['result'] in ('Win','Loss')]
    if settled:
        wins=sum(r['result']=='Win' for r in settled);profit=sum(r['profit_per_1'] for r in settled)
        st.write(f"{wins} wins / {len(settled)-wins} losses · Net per $1 per pick: ${profit:.2f} · ROI: {profit/len(settled):.1%}")
        estimated=[r for r in settled if r.get('probability') is not None]
        if estimated:
            brier=sum((r['probability']-(r['result']=='Win'))**2 for r in estimated)/len(estimated)
            st.write(f"Probability accuracy (Brier, lower is better): {brier:.4f}")
        bins=[]
        for lo in range(0,100,10):
            group=[r for r in estimated if lo<=r['probability']*100<lo+10]
            if group:bins.append({'Probability range':f'{lo}–{lo+10}%','Picks':len(group),'Average estimate %':round(100*sum(r['probability'] for r in group)/len(group),1),'Actual win %':round(100*sum(r['result']=='Win' for r in group)/len(group),1)})
        st.dataframe(bins,hide_index=True,use_container_width=True)
    else:st.info('No settled picks in this record yet.')
    if selected:st.dataframe(selected,hide_index=True,use_container_width=True)
    st.download_button('Download all saved NFL and NBA records',json.dumps({'records':all_records},indent=2),file_name='kamikaze_picks_published_history.json',mime='application/json',key='ledger_download')

def publish_rows(rows,events,cushions=(),key_prefix='ledger',sport='NFL',manual=False):
    import streamlit as st
    import requests
    with st.expander('Save picks for testing — no password'):
        st.caption('Saves qualifying originals and cushions before kickoff. Download your paper-pick JSON from Personal paper-pick tracking to preserve it between sessions. These are experimental selections, not automatically placed bets.')
        if st.button('Save picks for testing',key=key_prefix+'_personal_save'):
            try:
                to_save=[(dict(r,Sport=sport),'Manual' if manual else 'Original') for r in rows]
                for c in cushions:
                    if c['Cushion decision']=='Pass':continue
                    original=next(r for r in rows if r['Player']==c['Player'] and r['Game']==c['Game'])
                    alternate=dict(original,Line=c['Available line'],Odds=c['Actual odds'],Sportsbook=c['Sportsbook'])
                    alternate['Estimated win %']=c['Recalculated win %'];alternate['Quote updated UTC']=c['Quote updated UTC']
                    to_save.append((alternate,'Cushion'))
                boards={};saved=st.session_state.setdefault('personal_paper_records',[]);existing={r['id'] for r in saved};added=0
                for row,strategy in to_save:
                    match=next((e for e in events if e['away_team']+' at '+e['home_team']==row['Game']),None)
                    if not match:continue
                    day=utc(match['commence_time']).strftime('%Y%m%d')
                    if day not in boards:
                        path='basketball/nba' if sport=='NBA' else 'football/nfl'
                        response=requests.get('https://site.api.espn.com/apis/site/v2/sports/'+path+'/scoreboard',params={'dates':day},timeout=15);response.raise_for_status();boards[day]=response.json()
                    espn=next((e for e in boards[day].get('events',[]) if e.get('name')==row['Game'] and abs((utc(e['date'])-utc(match['commence_time'])).total_seconds())<3600),None)
                    if not espn:continue
                    record=make_record(row,espn['id'],match['commence_time'],strategy=strategy)
                    record['season_type']='Preseason' if espn.get('season',{}).get('type')==1 else 'Regular season' if espn.get('season',{}).get('type')==2 else 'Other/unknown'
                    record['evidence']='Personal paper record'
                    if record['id'] not in existing:saved.append(record);existing.add(record['id']);added+=1
                st.success(f'{added} new picks saved for testing. Download your JSON to keep them.')
            except (requests.exceptions.RequestException,ValueError,KeyError,TypeError):st.warning('Some picks could not be saved. Check your history, refresh stale prices, and try again.')
    try:token=st.secrets.get('PICK_HISTORY_GITHUB_TOKEN','')
    except Exception:token=''
    if not token:
        return
    with st.expander('Administrator: publish current original and cushion picks'):
        password=st.text_input('Publishing password',type='password',key=key_prefix+'_password')
        if not st.button('Publish qualifying picks permanently',key=key_prefix+'_publish'):return
        if not st.secrets.get('PICK_HISTORY_ADMIN_PASSWORD') or password!=st.secrets.get('PICK_HISTORY_ADMIN_PASSWORD'):
            st.warning('Administrator password required.');return
        try:
            new=[]
            to_publish=[(dict(row,Sport=sport),'Manual' if manual else 'Original') for row in rows]
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
                    path='basketball/nba' if sport=='NBA' else 'football/nfl'
                    board=requests.get('https://site.api.espn.com/apis/site/v2/sports/'+path+'/scoreboard',params={'dates':utc(match['commence_time']).strftime('%Y%m%d')},timeout=15).json()
                    espn=next((e for e in board.get('events',[]) if e.get('name')==row['Game'] and abs((utc(e['date'])-utc(match['commence_time'])).total_seconds())<3600),None)
                    if espn:new.append(make_record(row,espn['id'],match['commence_time'],strategy=strategy))
            headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json'}
            url=f'https://api.github.com/repos/{REPO}/contents/{LEDGER}'
            response=requests.get(url,headers=headers,params={'ref':'main'},timeout=15);response.raise_for_status();payload=response.json()
            data=json.loads(base64.b64decode(payload['content']));existing={r['id'] for r in data['records']}
            new=[r for r in new if r['id'] not in existing]
            if not new:st.info('No new eligible picks to publish.');return
            data['records'].extend(new)
            response=requests.put(url,headers=headers,json={'message':'Publish frozen pregame paper picks','branch':'main','sha':payload['sha'],'content':base64.b64encode(json.dumps(data,indent=2).encode()).decode()},timeout=20);response.raise_for_status()
            st.success(f'{len(new)} picks saved permanently. History appears after the app updates.')
        except (requests.exceptions.RequestException,ValueError,KeyError,TypeError):st.warning('Publishing did not complete. Refresh and check history before retrying.')

if __name__=='__main__':
    path=Path(LEDGER);data=json.loads(path.read_text());data['records']=grade_all(data['records']);path.write_text(json.dumps(data,indent=2)+'\n')
