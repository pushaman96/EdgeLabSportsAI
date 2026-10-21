"""NBA probability reliability from frozen prospective original selections."""
import statistics
from collections import defaultdict
from datetime import datetime,timezone
from pick_learning import eligible,build_feedback,utc


def reliability(records,asof=None,sport='NBA'):
    asof=asof or datetime.now(timezone.utc);groups=defaultdict(list);seen=set()
    for r in sorted(records,key=lambda r:r.get('published_utc','9999')):
        if r.get('sport','NFL')!=sport or r.get('strategy')!='Original' or r.get('evidence')not in ('Published before kickoff','Personal paper record')or r.get('season_type')!='Regular season':continue
        try:
            if utc(r['published_utc'])>=utc(r['starts_utc']):continue
        except (KeyError,ValueError,TypeError):continue
        identity=(r.get('event_id'),r.get('player'),r.get('category'))
        if identity in seen:continue
        seen.add(identity)
        if not eligible(r,asof):continue
        try:
            if not 0<float(r['probability'])<1:continue
        except (KeyError,ValueError,TypeError):continue
        model=r.get('base_model')or r.get('model','Unknown')
        groups[model,r['category']].append(r)
    output=[]
    for (model,category),rows in sorted(groups.items()):
        for low,high in ((0,.5),(.5,.6),(.6,.7),(.7,.8),(.8,1)):
            subset=[r for r in rows if low<=float(r['probability'])<high]
            if not subset:continue
            games=defaultdict(list)
            for r in subset:games[r['event_id']].append(r)
            def game_mean(fn):return statistics.mean(statistics.mean(fn(r)for r in values)for values in games.values())
            output.append({'Model':model,'Category':category,'Probability band':f'{low:.0%}–{high:.0%}','Original picks':len(subset),'Distinct games':len(games),'Mean estimated %':100*game_mean(lambda r:float(r['probability'])),'Observed win %':100*game_mean(lambda r:int(r['result']=='Win')),'Game-weighted Brier':game_mean(lambda r:(float(r['probability'])-int(r['result']=='Win'))**2),'Evidence status':'Small sample; descriptive only' if len(games)<30 else 'Descriptive reliability; calibration still requires chronological validation'})
    return output


def render(records,sport='NBA'):
    import streamlit as st
    with st.expander(sport+' probability calibration — estimated versus actual'):
        nba=[r for r in records if r.get('sport','NFL')==sport and r.get('strategy')=='Original']
        rows=reliability(nba,sport=sport)
        if rows:st.dataframe(rows,hide_index=True,use_container_width=True)
        else:st.info('Appears after original '+sport+' selections have official final results and saved grading times.')
        state=build_feedback(nba)
        st.caption('Original pregame regular-season picks only, with earliest player/game/category selected once. Each game receives equal weight within a probability band. Missing, pending, manual and historical imports are excluded. Same-game picks are not independent evidence.')
        st.write(str(state['active_corrections'])+' probability corrections passed the separate chronological checks.')
        st.caption('Corrections require at least 100 eligible selections and 30 distinct games per model/category/direction, earlier-game fitting, later-game Brier improvement of at least 0.005, positive game-level uncertainty bound and no worse log loss. Until then, no larger-sample calibration correction is applied. This does not block early-season picks.')

