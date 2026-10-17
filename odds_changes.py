"""Compare already-loaded quotes without making provider requests."""
def estimated_credits(event_count,markets,regions=1):
    return max(0,event_count)*len(set(m for m in markets.split(',') if m))*regions

def quote_map(events):
    rows={}
    for e in events:
        for book in e.get('bookmakers',[]):
            for market in book.get('markets',[]):
                # Alternate lines have multiple points per direction; do not pair unrelated rungs.
                alternate='alternate' in market.get('key','')
                for o in market.get('outcomes',[]):
                    key=(e['id'],book.get('key',book.get('title')),market['key'],o.get('description',''),o.get('name'),o.get('point') if alternate else None)
                    rows[key]={'Game':e['away_team']+' at '+e['home_team'],'Sportsbook':book.get('title'),'Market':market['key'],'Player':o.get('description',''),'Direction':o.get('name'),'Line':o.get('point'),'Odds':o.get('price')}
    return rows

def changes(before,after):
    old=quote_map(before);new=quote_map(after);result=[]
    for key in old.keys()&new.keys():
        a,b=old[key],new[key]
        if (a['Line'],a['Odds'])!=(b['Line'],b['Odds']):result.append(dict(b,**{'Previous line':a['Line'],'Previous odds':a['Odds']}))
    return sorted(result,key=lambda r:(r['Game'],r['Player'],r['Market'],r['Direction']))

def render_changes(events,scope,retrieved):
    import streamlit as st
    key='quote_change_'+scope;previous=st.session_state.get(key)
    if previous and previous['retrieved']!=retrieved:
        diff=changes(previous['events'],events)
        st.session_state[key]={'events':events,'retrieved':retrieved,'changes':diff}
    elif not previous:st.session_state[key]={'events':events,'retrieved':retrieved,'changes':[]}
    diff=st.session_state[key]['changes']
    with st.expander('Line changes between loaded snapshots — viewing costs 0 credits'):
        if diff:st.dataframe(diff,hide_index=True,use_container_width=True)
        else:st.info('No changes detected between the comparable snapshots loaded in this session. This does not confirm current sportsbook prices.')
        st.caption('No provider request is made here. Fresh sportsbook prices require a new odds request. Missing/new markets are not treated as a confirmed line movement.')
