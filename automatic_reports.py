"""Automatic durable copies of report data; frozen betting picks stay in their ledger."""
import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

REPO='pushaman96/EdgeLabSportsAI'

def report_path(file_name):
    if Path(file_name).name!=file_name:raise ValueError('Invalid report name')
    return 'app_archives/'+file_name+'.json'

def load_report(file_name):
    """Restore the most recent report installed with the app's repository."""
    try:return json.loads(Path(report_path(file_name)).read_text())['data']
    except (OSError,ValueError,KeyError):return None

def save_report(data,file_name,mime,token,client):
    from pick_history import storage_status,StorageError
    path=report_path(file_name)
    digest=hashlib.sha256(data.encode()).hexdigest()
    headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json'}
    url=f'https://api.github.com/repos/{REPO}/contents/{path}'
    for attempt in range(3):
        response=client.get(url,headers=headers,params={'ref':'main'},timeout=15)
        sha=None
        if response.status_code!=404:
            storage_status(response,'Reading report archive');payload=response.json();sha=payload['sha']
            if payload.get('encoding')=='none':
                raw=client.get(url,headers=dict(headers,Accept='application/vnd.github.raw+json'),params={'ref':'main'},timeout=15)
                storage_status(raw,'Reading large report archive');prior=raw.json()
            else:prior=json.loads(base64.b64decode(payload['content']))
            if prior.get('digest')==digest:return digest
        document={'schema':1,'file_name':file_name,'mime':mime,'digest':digest,'saved_utc':datetime.now(timezone.utc).isoformat(),'data':data,'purpose':'Latest report snapshot; not independently verified training evidence. Frozen selections remain in published_picks.json.'}
        body={'message':'Automatically save app report','branch':'main','content':base64.b64encode(json.dumps(document).encode()).decode()}
        if sha:body['sha']=sha
        response=client.put(url,headers=headers,json=body,timeout=20)
        if response.status_code in (409,422) and attempt<2:continue
        storage_status(response,'Writing report archive')
        check=client.get(url,headers=headers,params={'ref':'main'},timeout=15)
        storage_status(check,'Verifying report archive')
        payload=check.json()
        if payload.get('encoding')=='none':
            raw=client.get(url,headers=dict(headers,Accept='application/vnd.github.raw+json'),params={'ref':'main'},timeout=15)
            storage_status(raw,'Verifying large report archive');verified=raw.json()
        else:verified=json.loads(base64.b64decode(payload['content']))
        if verified.get('digest')!=digest:continue
        local=Path(path);local.parent.mkdir(parents=True,exist_ok=True);local.write_text(json.dumps(document))
        return digest
    raise ValueError('Concurrent report update; retry required')

def storage_reason(error):
    from pick_history import StorageError
    if isinstance(error,StorageError):return str(error)
    # Never expose raw exception strings: request URLs/bodies may hold credentials.
    return 'Network, timeout or unexpected archive response. Existing data stays queued.'


def flush_reports(token,client,state,now=None,force=False):
    import time
    now=time.time() if now is None else now
    queue=state.setdefault('pending_report_saves',{})
    confirmed=state.setdefault('automatic_report_digests',{})
    failures=state.setdefault('report_save_errors',{})
    attempts=state.setdefault('report_save_attempts',{})
    for name,item in list(queue.items()):
        if not force and now-attempts.get(name,-99999)<60:continue
        attempts[name]=now
        try:digest=save_report(item['data'],name,item['mime'],token,client)
        except Exception as error:failures[name]=storage_reason(error)
        else:
            confirmed[name]=digest;failures.pop(name,None);queue.pop(name,None)
    return len(queue)


def autosave_report(label,data,file_name,mime='text/plain',key=None,**kwargs):
    import streamlit as st
    import requests
    if isinstance(data,bytes):data=data.decode('utf-8')
    digest=hashlib.sha256(data.encode()).hexdigest()
    confirmed=st.session_state.setdefault('automatic_report_digests',{})
    if confirmed.get(file_name)!=digest and load_report(file_name)==data:
        confirmed[file_name]=digest
    if confirmed.get(file_name)==digest:
        st.session_state.setdefault('pending_report_saves',{}).pop(file_name,None)
        return
    # Keep latest report snapshots queued even when credentials are unavailable.
    st.session_state.setdefault('pending_report_saves',{})[file_name]={'data':data,'mime':mime}
    try:token=st.secrets.get('PICK_HISTORY_GITHUB_TOKEN','')
    except Exception:token=''
    if not isinstance(token,str) or not token.strip():
        st.warning('Report queued in this session: missing top-level PICK_HISTORY_GITHUB_TOKEN in Streamlit Secrets. Keep this session open.')
        return
    flush_reports(token.strip(),requests,st.session_state)
    issue=st.session_state.get('report_save_errors',{}).get(file_name)
    if issue:st.warning('Report not permanently saved. '+issue+' Use Storage status → Retry queued saves. No odds reload is needed.')
    elif confirmed.get(file_name)==digest:st.caption('Report saved automatically and verified in GitHub. Original recommended picks remain frozen in pick history.')


def render_storage_status(sport='NFL'):
    import streamlit as st
    import requests
    from pick_history import storage_status,StorageError,sync_session_records
    with st.expander('Storage status — verify saves and retry without loading odds'):
        from forecast_tracking import retry_pending
        retry_pending(sport)
        try:token=st.secrets.get('PICK_HISTORY_GITHUB_TOKEN','')
        except Exception:token=''
        token=token.strip() if isinstance(token,str) else ''
        queued=st.session_state.get('pending_report_saves',{})
        st.write(str(len(queued))+' report snapshots queued in this session.')
        if not token:
            st.warning('Missing top-level PICK_HISTORY_GITHUB_TOKEN in this deployed app. Never paste it into chat.')
            return
        fingerprint=hashlib.sha256(token.encode()).hexdigest()
        if st.session_state.get('storage_probe_fingerprint')!=fingerprint:
            st.session_state.pop('storage_probe_result',None)
            st.session_state['storage_probe_fingerprint']=fingerprint
        st.caption('GitHub token setting found. Presence alone does not verify write access.')
        if st.button('Verify permanent storage — 0 odds credits',key='storage_verify_'+sport):
            try:
                stamp=datetime.now(timezone.utc).isoformat()
                save_report(stamp,'storage_health.txt','text/plain',token,requests)
            except Exception as error:st.session_state['storage_probe_result']=(False,storage_reason(error))
            else:st.session_state['storage_probe_result']=(True,'Write and read-back succeeded for pushaman96/EdgeLabSportsAI at '+stamp+'. This checks the running app’s token; it does not create a pick.')
        result=st.session_state.get('storage_probe_result')
        if result:(st.success if result[0] else st.warning)(result[1])
        if st.button('Retry queued report saves — 0 odds credits',key='report_retry_'+sport):
            remaining=flush_reports(token,requests,st.session_state,force=True)
            if remaining:st.warning(str(remaining)+' report snapshots remain queued.')
            else:st.success('All queued report saves verified in GitHub.')
        for name,reason in list(st.session_state.get('report_save_errors',{}).items())[:5]:st.warning(name+': '+reason)
        st.caption('Frozen picks have a separate retry button above the live board. Reports are latest snapshots; they do not prove pregame publication. No keys are displayed or stored in reports.')

