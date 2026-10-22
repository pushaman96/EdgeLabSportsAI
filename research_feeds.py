"""Optional authenticated research feeds. Not automatically used by forecasts."""
import re
from datetime import datetime,timezone
from urllib.parse import quote
import requests
import streamlit as st

def feed_request(provider,key,sport,identifier):
    if sport not in ('NFL','NBA'):raise ValueError('Unsupported sport.')
    if provider=='SportsDataIO':
        if not re.fullmatch(r'20\d{2}(REG|PRE|POST)?',identifier):raise ValueError('Use a season such as 2025 or 2025REG.')
        url=f'https://api.sportsdata.io/v3/{sport.lower()}/stats/json/PlayerSeasonStats/{identifier}'
        headers={'Ocp-Apim-Subscription-Key':key}
    elif provider=='Sportradar':
        if not re.fullmatch(r'[0-9a-fA-F-]{36}|sr:(match|sport_event):\d+',identifier):raise ValueError('Enter a Sportradar game ID, not an ESPN or Odds API ID.')
        url=f'https://api.sportradar.com/betting-splits/v3/production/{sport.lower()}/en/game/{quote(identifier,safe="")}'
        headers={'x-api-key':key}
    else:raise ValueError('Unsupported provider.')
    try:
        response=requests.get(url,headers=headers,timeout=20)
        if response.status_code in (401,403):raise ValueError('Key or subscription does not authorize this endpoint. Confirm your provider package and endpoint with support.')
        if response.status_code==429:raise ValueError('Provider request limit reached; wait before retrying.')
        if response.status_code!=200:raise ValueError(f'Provider returned HTTP {response.status_code}. No data connected.')
        return response.json()
    except requests.exceptions.RequestException:raise ValueError('Provider connection failed. No key or request URL is shown.')

def split_percentages(data):
    # Expose only explicitly named percentages. Never disclose raw ticket/stake totals.
    output=[]
    def visit(value,path,depth=0):
        if depth>15 or len(output)>=1000:return
        if isinstance(value,dict):
            for key,item in value.items():
                field=str(key);normalized=re.sub(r'[^a-z]','',field.lower())
                if isinstance(item,(int,float)) and ('percent' in normalized or normalized.endswith('pct')):
                    if 0<=item<=100:output.append({'Provider field':path+'.'+field,'Provider percentage value (original scale)':item})
                elif isinstance(item,(list,dict)):visit(item,path+'.'+field,depth+1)
        elif isinstance(value,list):
            for i,item in enumerate(value[:1000]):visit(item,path+f'[{i}]',depth+1)
    visit(data,'response')
    return output

def render_research_feeds(sport):
    with st.expander(f'{sport} optional research feeds — SportsDataIO and betting splits'):
        st.caption('Personal-use connection tools. Data is kept separate from predictions until schema, coverage and model benefit are validated. No subscription is purchased here.')
        provider=st.selectbox('Research provider',['SportsDataIO','Sportradar'],key='research_provider')
        if provider=='SportsDataIO':
            st.markdown('[SportsDataIO Discovery Lab](https://discoverylab.sportsdata.io/) · [API documentation](https://sportsdata.io/developers/api-documentation/'+sport.lower()+')')
            st.caption('Tests the documented SportsDataIO player-season stats endpoint. Discovery Lab entitlements may differ; verify the endpoint included with your key. Start with a completed season. Current-season season totals cannot be used as historical pregame inputs.')
            st.caption('SportsDataIO free-trial statistics can be scrambled. This optional feed stays outside the prediction models. Current roster, injury and lineup research uses checked ESPN sources; no paid provider is required for the new homework.')
            identifier=st.text_input('Season identifier',value='2025' if sport=='NFL' else '2026',key='research_sdio_season_'+sport)
            quality=st.selectbox('Provider data status',['Access/real-data status not yet verified','Provider-confirmed real data','Scrambled demo data'],key='research_data_quality')
        else:
            st.markdown('[Sportradar Betting Splits documentation](https://developer.sportradar.com/insights/reference/betting-splits-overview)')
            st.caption('Requires Betting Splits entitlement and a Sportradar game ID from its NFL/NBA schedule feed. Automatic game-ID mapping is not implemented yet. This is not your Odds API key. Personal use does not automatically grant access.')
            identifier=st.text_input('Sportradar game ID',key='research_sr_game_'+sport)
            quality='Betting splits — coverage unverified'
        key=st.text_input(provider+' API key',type='password',key='research_key_'+provider,help='Enter privately here. Never send keys in chat or commit them to GitHub.')
        if st.button('Load research feed',key='research_feed_load',disabled=not key or not identifier):
            try:
                data=feed_request(provider,key,sport,identifier.strip())
                if provider=='SportsDataIO':
                    if not isinstance(data,list):raise ValueError('Unexpected player-stat response; endpoint coverage not verified.')
                    fields=['Name','PlayerID','Team','Position','Season','Games','Started','Minutes','FieldGoalsAttempted','ThreePointersAttempted','PassingAttempts','PassingYards','RushingAttempts','RushingYards','ReceivingTargets','Receptions','ReceivingYards','OffensiveSnapsPlayed','OffensiveTeamSnaps','FantasyPoints']
                    rows=[{field:r.get(field) for field in fields if field in r} for r in data if isinstance(r,dict)]
                else:rows=split_percentages(data)
                st.session_state['optional_research_feed']={'provider':provider,'sport':sport,'identifier':identifier.strip(),'quality':quality,'rows':rows,'retrieved':datetime.now(timezone.utc).isoformat()}
            except (ValueError,KeyError,TypeError):st.warning('Unable to load authorized data. Check the provider key, package, season or game ID. Existing forecasts are unchanged.');return
        saved=st.session_state.get('optional_research_feed')
        if saved and (saved['provider'],saved['sport'],saved['identifier'])==(provider,sport,identifier.strip()):
            st.caption(saved['quality']+' · Retrieved '+saved['retrieved'])
            if saved['rows']:st.dataframe(saved['rows'],hide_index=True,use_container_width=True)
            else:st.info('No recognized data fields returned. This requires provider-response validation, not guessed values.')
            st.info('Research-only: this feed is not training or changing the pick models yet. Betting-splits fields retain provider scale and are not normalized until verified; raw bet counts and dollar totals are not displayed.')
