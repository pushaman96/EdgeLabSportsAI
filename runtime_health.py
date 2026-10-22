"""Bounded recovery for public read-only feeds and compact dashboard snapshots.
No credentials, paid odds, model changes, ledger writes or automatic code edits.
"""
import copy
import importlib
import json
import threading
import time
from collections import OrderedDict
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlparse
import requests

VERSION='Runtime recovery v1'
_LOCK=threading.RLock()
_FEEDS=OrderedDict();_FILES=OrderedDict();_EVENTS=OrderedDict();_MODULES={}
MAX_FEEDS=96;MAX_FILES=8;COOLDOWN=30

class FeedUnavailable(requests.RequestException):pass

def _utc():return datetime.now(timezone.utc).isoformat()
def note(key,status,seconds=0):
    with _LOCK:
        _EVENTS[key]={'Component':key,'Status':status,'Seconds':round(seconds,3),'Checked UTC':_utc()}
        _EVENTS.move_to_end(key)
        while len(_EVENTS)>48:_EVENTS.popitem(last=False)

def public_json(key,url,params=None,fresh=30,max_stale=120,validate=None,ttl=None,client=None):
    parsed=urlparse(url)
    if parsed.scheme!='https'or parsed.netloc not in ('site.api.espn.com','raw.githubusercontent.com')or parsed.username or parsed.password or parsed.query:
        raise ValueError('Only approved public read-only feeds are recoverable')
    if parsed.netloc=='raw.githubusercontent.com'and parsed.path!='/pushaman96/EdgeLabSportsAI/main/published_picks.json':raise ValueError('Public ledger path required')
    if any(k not in ('dates','event')for k in (params or {})):raise ValueError('Unsupported public feed parameter')
    identity=(key,url,tuple(sorted((params or {}).items())))
    now=time.monotonic()
    with _LOCK:
        item=_FEEDS.setdefault(identity,{})
        _FEEDS.move_to_end(identity)
        age=now-item.get('success',-1e20)
        if 'data'in item and age<item['ttl']:return copy.deepcopy(item['data']),dict(item['meta'],stale=False)
        if now<item.get('retry_at',0)or item.get('inflight'):
            if 'data'in item and age<=max_stale:
                note(key,'Last-good data — retry cooldown')
                return copy.deepcopy(item['data']),dict(item['meta'],stale=True)
            raise FeedUnavailable('Public feed temporarily unavailable; automatic retry is cooling down')
        item['inflight']=True
        while len(_FEEDS)>MAX_FEEDS:
            oldest=next((k for k,v in _FEEDS.items()if not v.get('inflight')),None)
            if oldest is None:break
            _FEEDS.pop(oldest)
    start=time.monotonic()
    try:
        response=(client or requests).get(url,params=params,headers={'User-Agent':'KamikazePicks/1.0'},timeout=(2,5))
        response.raise_for_status();data=response.json()
        if not isinstance(data,dict)or(validate is not None and not validate(data)):raise ValueError('Invalid public feed identity or schema')
        meta={'retrieved_utc':_utc(),'stale':False}
        with _LOCK:
            item.update(data=data,success=time.monotonic(),ttl=ttl(data)if ttl else fresh,meta=meta,retry_at=0,inflight=False)
        note(key,'Live public feed',time.monotonic()-start)
        return copy.deepcopy(data),dict(meta)
    except (requests.RequestException,ValueError,TypeError,KeyError):
        with _LOCK:
            item.update(retry_at=time.monotonic()+COOLDOWN,inflight=False)
            age=time.monotonic()-item.get('success',-1e20)
            fallback='data'in item and age<=max_stale
        note(key,'Last-good data — automatic retry pending'if fallback else'Unavailable — automatic retry pending',time.monotonic()-start)
        if fallback:return copy.deepcopy(item['data']),dict(item['meta'],stale=True)
        raise FeedUnavailable('Public feed unavailable; no usable cached response')from None
    finally:
        with _LOCK:item['inflight']=False

def invalidate_public(prefix=None):
    """Refresh eligible reads, retaining last-good data and failure cooldowns."""
    with _LOCK:
        for key,item in _FEEDS.items():
            if prefix is None or key[0].startswith(prefix):item['ttl']=0

def summary(sport_path,event_id):
    eid=str(event_id)
    if sport_path not in ('football/nfl','basketball/nba')or not eid.isdigit():raise ValueError('Invalid public game identity')
    def lifetime(data):
        comp=(data.get('header',{}).get('competitions')or[{}])[0]
        return 600 if comp.get('status',{}).get('type',{}).get('completed')is True else 20
    data,meta=public_json('summary '+sport_path+' '+eid,'https://site.api.espn.com/apis/site/v2/sports/'+sport_path+'/summary',params={'event':eid},max_stale=120,validate=lambda d:str(d.get('header',{}).get('id',''))==eid,ttl=lifetime)
    return {'data':data,'retrieved_utc':meta['retrieved_utc'],'stale':meta['stale']}

def snapshot(path,tag,selector,default):
    """Parse once per file version; retain only a compact selected view in memory."""
    path=Path(path);key=(str(path.resolve()),tag);now=time.monotonic()
    try:stat=path.stat();signature=(stat.st_mtime_ns,stat.st_size)
    except OSError:signature=None
    with _LOCK:
        old=_FILES.get(key,{})
        if signature is not None and old.get('signature')==signature:return copy.deepcopy(old['data'])
        if now<old.get('retry_at',0):return copy.deepcopy(old.get('data',default))if now-old.get('success',-1e20)<=600 else copy.deepcopy(default)
    start=time.monotonic()
    try:
        data=selector(json.loads(path.read_text()))
    except (OSError,ValueError,KeyError,TypeError):
        with _LOCK:
            old.update(retry_at=now+COOLDOWN);_FILES[key]=old
        note(path.name,'Snapshot unavailable — retaining recent verified view')
        return copy.deepcopy(old.get('data',default))if now-old.get('success',-1e20)<=600 else copy.deepcopy(default)
    with _LOCK:
        _FILES[key]={'signature':signature,'data':data,'success':now,'retry_at':0};_FILES.move_to_end(key)
        while len(_FILES)>MAX_FILES:_FILES.popitem(last=False)
    note(path.name,'Dashboard snapshot ready',time.monotonic()-start)
    return copy.deepcopy(data)

def reload_if_changed(module):
    path=getattr(module,'__file__',None)
    if not path:return module
    try:signature=Path(path).stat().st_mtime_ns
    except OSError:return module
    with _LOCK:
        before=_MODULES.get(module.__name__);_MODULES[module.__name__]=signature
        if before is not None and before!=signature:return importlib.reload(module)
    return module

def render():
    import streamlit as st
    with st.sidebar.expander('App health & automatic recovery'):
        st.caption(VERSION+' · public data only · no odds credits')
        with _LOCK:rows=list(_EVENTS.values())[-12:]
        if rows:st.dataframe(rows,hide_index=True,use_container_width=True)
        else:st.caption('No public-feed requests recorded in this server process yet.')
        st.caption('Failed reads pause for 30 seconds, then retry on the next request. Last-good data retains its original timestamp. This does not rewrite models, alter picks or repair arbitrary code defects. Runtime records reset when the server restarts.')
