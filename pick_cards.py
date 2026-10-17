"""Compact paginated cards for frozen predictions; no new provider requests."""
import math
from saved_pick_explanation import explanation
from pick_readiness import risk_notes
from team_emblems import pick_team

def render_pick_cards(records,sport,live_rows=None):
    import streamlit as st
    from pick_presentation import accent_html,badge_html,pick_status
    live={r.get("Pick ID"):r for r in (live_rows or [])}
    unique={r['id']:r for r in records};rows=list(unique.values())
    if not rows:st.info('No saved picks match these filters.');return
    pages=math.ceil(len(rows)/6)
    page=st.selectbox('Pick-card page',list(range(pages)),format_func=lambda i:f'{i+1} of {pages}',key='pick_card_page_'+sport) if pages>1 else 0
    for offset in range(page*6,min((page+1)*6,len(rows)),2):
        columns=st.columns(2)
        for column,r in zip(columns,rows[offset:offset+2]):
            e=explanation(r)
            with column.container(border=True):
                team=pick_team(r,index=st.session_state.get('team_emblems',{}))
                st.markdown(accent_html(team.get('color') if team else None),unsafe_allow_html=True)
                st.markdown(badge_html(pick_status(r,live.get(r['id']))),unsafe_allow_html=True)
                if team and team.get('logo'):
                    icon,title=st.columns([1,7]);icon.image(team['logo'],width=28);title.write('**'+r.get('player','Unknown')+'**')
                else:st.write('**'+r.get('player','Unknown')+'**')
                st.write(e['selection'])
                st.caption(r.get('game',''))
                prob=r.get('probability');prob_text=f'{prob:.0%}' if isinstance(prob,(int,float)) and 0<prob<1 else 'Not modeled'
                metrics=st.columns(2);metrics[0].metric('Estimated win chance',prob_text)
                metrics[1].metric('Recorded odds',str(r.get('odds','Unknown')))
                st.caption('Manual selection' if r.get('strategy')=='Manual' else 'Experimental analyzed pick · '+r.get('strategy','Original'))
                st.write(e['forecast'].split(' The central forecast')[0])
                st.caption(r.get('sportsbook','Unknown sportsbook')+' · '+r.get('result','Pending'))
                with st.expander('Evidence, freshness and game-flow risks'):
                    st.write(e['workload']);st.write(e['price']);st.write(e['reason'])
                    st.write(risk_notes(r))
                    source=r.get('source_audit') or {}
                    if source:
                        for label,value in source.items():st.caption(label+': '+str(value))
                    else:st.caption('Detailed source timestamps were not saved with this older pick. Reanalyze current prices for a fresh availability check; the original pick remains frozen.')
                st.caption('Frozen forecast for tracking; recorded odds are not confirmed current prices.')

