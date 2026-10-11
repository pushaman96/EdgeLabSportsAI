"""Reported sportsbook prices and optional The Odds API connection."""
import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import requests
import streamlit as st

class OddsSourceError(ValueError):
    pass

SPORT_KEYS = {'NFL':'americanfootball_nfl', 'NBA':'basketball_nba'}
PROP_MARKETS = {'NFL':{'Passing yards':'player_pass_yds','Rushing yards':'player_rush_yds','Receiving yards':'player_reception_yds','Receptions':'player_receptions'},'NBA':{'Points':'player_points','Rebounds':'player_rebounds','Assists':'player_assists','Three-pointers made':'player_threes'}}

def numeric(value):
    try:
        number=float(value)
        return number if math.isfinite(number) else None
    except (TypeError,ValueError):return None

def implied(odds):
    value=numeric(odds)
    if value is None or abs(value)<100:return None
    return 100/(value+100) if value>0 else abs(value)/(abs(value)+100)

def odds_text(value):
    number=numeric(value)
    return f'{number:+g}' if number is not None else 'Unavailable'

def pacific(value):
    return datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(ZoneInfo('America/Los_Angeles'))

def espn_lines(scoreboard):
    rows=[]
    for event in scoreboard.get('events',[]):
        competition=event.get('competitions',[{}])[0]
        for quote in competition.get('odds') or []:
            provider=quote.get('provider',{}).get('displayName') or quote.get('provider',{}).get('name','Unknown')
            for key,label,sides in [('moneyline','Moneyline',('home','away')),('pointSpread','Spread',('home','away')),('total','Total',('over','under'))]:
                market=quote.get(key,{})
                for side in sides:
                    price=market.get(side,{}).get('close',{})
                    if not price:continue
                    rows.append({'Game':event.get('name'),'Sportsbook':provider,'Market':label,'Selection':side.title(),'Line':price.get('line','—'),'Odds':odds_text(price.get('odds')),'Quote timestamp':'Not supplied by ESPN','Quote type':'Reported close quote'})
    return rows

@st.cache_data(ttl=300)
def odds_request(api_key,sport,event_id='',markets='h2h,spreads,totals'):
    path=f'sports/{SPORT_KEYS[sport]}/events/{event_id}/odds' if event_id else f'sports/{SPORT_KEYS[sport]}/odds'
    try:
        response=requests.get('https://api.the-odds-api.com/v4/'+path,params={'apiKey':api_key,'regions':'us','markets':markets,'oddsFormat':'american','dateFormat':'iso'},timeout=20)
    except requests.exceptions.RequestException:
        raise OddsSourceError('The odds source did not respond. Try again later.') from None
    if response.status_code != 200:
        messages={401:'API key not accepted. Check your key.',403:'This request is not available for this API key.',429:'Rate or usage limit reached. Check your provider account.'}
        raise OddsSourceError(messages.get(response.status_code,f'Odds source returned HTTP {response.status_code}. Check market coverage and your account.'))
    try:data=response.json()
    except ValueError:raise OddsSourceError('Odds source returned unreadable data.') from None
    if not isinstance(data,(dict,list)):raise OddsSourceError('Unexpected odds source data.')
    return {'data':data,'retrieved':datetime.now(timezone.utc).isoformat(),'remaining':response.headers.get('x-requests-remaining','Not supplied'),'cost':response.headers.get('x-requests-last','Not supplied')}

def bookmaker_rows(events,books=(),props=False):
    rows=[]
    for event in events:
        for book in event.get('bookmakers',[]):
            if books and book['title'] not in books:continue
            for market in book.get('markets',[]):
                for outcome in market.get('outcomes',[]):
                    odds=outcome.get('price');prob=implied(odds)
                    rows.append({'Game':event['away_team']+' at '+event['home_team'],'Sportsbook':book['title'],'Market':market['key'],'Player':outcome.get('description','—'),'Selection':outcome.get('name','—'),'Line':outcome.get('point','—'),'Odds':odds_text(odds),'Implied %':round(prob*100,1) if prob is not None else None,'Quote updated UTC':market.get('last_update') or book.get('last_update','Unavailable')})
    return rows

def moneyline_reviews(events,models,now=None):
    now=now or datetime.now(timezone.utc)
    rows=[]
    for event in events:
        if datetime.fromisoformat(event['commence_time'].replace('Z','+00:00'))<=now:continue
        model=models.get((event['home_team'],event['away_team']))
        if not model or not model['eligible']:continue
        for book in event.get('bookmakers',[]):
            for market in book.get('markets',[]):
                if market['key']!='h2h' or len(market.get('outcomes',[]))!=2:continue
                if {o.get('name') for o in market['outcomes']} != {event['home_team'],event['away_team']}:continue
                updated=market.get('last_update') or book.get('last_update')
                try:age=(now-datetime.fromisoformat(updated.replace('Z','+00:00'))).total_seconds()
                except (ValueError,TypeError,AttributeError):continue
                if age<0 or age>900:continue
                probs=[implied(outcome.get('price')) for outcome in market['outcomes']]
                if any(p is None for p in probs):continue
                for outcome,market_p in zip(market['outcomes'],probs):
                    if outcome['name'] not in (event['home_team'],event['away_team']):continue
                    p=model['probability'] if outcome['name']==event['home_team'] else 1-model['probability']
                    odds=numeric(outcome['price']);decimal=1+odds/100 if odds>0 else 1+100/abs(odds)
                    ev=p*decimal-1
                    if ev<=0 or p-market_p<.05:continue
                    rows.append({'Game':event['away_team']+' at '+event['home_team'],'Team to research':outcome['name'],'Sportsbook':book['title'],'Moneyline':odds_text(odds),'Model win %':round(p*100,1),'Break-even %':round(market_p*100,1),'Market win % without margin':round(market_p/sum(probs)*100,1),'Model minus break-even (pp)':round((p-market_p)*100,1),'Model history through':model['cutoff'],'Quote updated UTC':updated,'Estimated return per $1':round(ev,3)})
    return sorted(rows,key=lambda row:row['Model minus break-even (pp)'],reverse=True)

def render_sportsbooks(sport,selected_date,scoreboard,model_loader):
    if sport != 'NFL':return
    st.divider();st.header('NFL Sportsbook Game Lines & Player Props')
    source=st.selectbox('Sportsbook data source',['ESPN reported lines (free)','Multiple sportsbooks & props — The Odds API'],key='sportsbook_source')
    if source.startswith('ESPN'):
        rows=espn_lines(scoreboard)
        st.caption('Source: ESPN sportsbook feed. Uses reported close quotes; the feed does not supply quote update times. These are not verified live prices. Refresh live data reloads the scoreboard.')
        if rows:st.dataframe(rows,hide_index=True,use_container_width=True)
        else:st.info('ESPN has no sportsbook prices for these NFL games.')
        st.info('Select Multiple sportsbooks & props to compare books and load player props. That connection requires a data-provider API key.')
        return
    st.markdown('[Get your own key from The Odds API](https://the-odds-api.com/)')
    st.caption('Start with the free allowance. Loads consume provider credits; no paid plan is purchased by this app. Game lines request three markets; props load only for the game and categories you select. Responses are cached five minutes. Coverage differs by book and season.')
    key=st.text_input('The Odds API key',type='password',key='sportsbook_api_key',help='Enter it here privately. Do not post your key in chat or GitHub. It is sent to The Odds API to retrieve your data and stays in this app session.')
    if not key:return
    try:
        if st.button('Load / refresh sportsbook game lines',key='sportsbook_load'):
            odds_request.clear()
            result=odds_request(key,sport)
            st.session_state['sportsbook_result']=(sport,key,result)
        saved=st.session_state.get('sportsbook_result')
        if not saved or saved[:2]!=(sport,key):
            st.info('Click Load / refresh sportsbook game lines.');return
        result=saved[2]
        events=[event for event in result['data'] if pacific(event['commence_time']).date()==selected_date]
        st.caption(f"Retrieved {result['retrieved']}. Credits remaining at retrieval: {result['remaining']}. Last request cost: {result['cost']}. Displaying sidebar date in Pacific time.")
        if not events:st.info('No bookmaker events for the selected date. Choose a different sidebar date; preseason or distant dates may not be covered.');return
        names=sorted({book['title'] for event in events for book in event.get('bookmakers',[])})
        selected_books=st.multiselect('Compare sportsbooks',names,default=names,key='sportsbook_books')
        if not selected_books:st.info('Select at least one sportsbook.');return
        filtered=[dict(event,bookmakers=[b for b in event.get('bookmakers',[]) if b['title'] in selected_books]) for event in events]
        st.dataframe(bookmaker_rows(filtered),hide_index=True,use_container_width=True)
        st.caption('Bookmaker names and quote timestamps come from the provider. Refresh before acting; displayed prices can change. Compare prices only for the same market, selection and line.')
        st.subheader('Player props — common categories')
        st.caption('This feed does not report bet counts or betting volume. Common categories are not a ranking of popular bets. The current winner model cannot price player props, spreads or totals.')
        event_id=st.selectbox('Player props game',[e['id'] for e in events],format_func=lambda value:next(e['away_team']+' at '+e['home_team'] for e in events if e['id']==value),key='sportsbook_props_game')
        labels=st.multiselect('Prop categories',list(PROP_MARKETS[sport]),default=list(PROP_MARKETS[sport])[:2],key='sportsbook_props_categories')
        markets=','.join(sorted(PROP_MARKETS[sport][label] for label in labels))
        if st.button('Load selected player prop lines',key='sportsbook_props_load') and markets:
            prop_result=odds_request(key,sport,event_id,markets)
            st.session_state['sportsbook_props_result']=(sport,key,event_id,markets,prop_result)
        prop_saved=st.session_state.get('sportsbook_props_result')
        if prop_saved and prop_saved[:4]==(sport,key,event_id,markets):
            props=bookmaker_rows([prop_saved[4]['data']],selected_books,True)
            if props:st.dataframe(props,hide_index=True,use_container_width=True)
            else:st.info('No selected player props returned. Coverage can be limited during preseason.')
            st.caption(f"Prop request credits remaining: {prop_saved[4]['remaining']}. Request cost: {prop_saved[4]['cost']}.")
        st.subheader('Games to research — experimental moneyline comparison')
        st.caption('Compares adjusted Elo with the break-even price; requires a gap of at least five percentage points, a quote no more than 15 minutes old, and regular-season model history no more than 30 days old. These are research candidates, not validated betting recommendations. Injuries and lineups are not included.')
        if st.button('Compare model with current moneylines',key='sportsbook_research'):
            models=model_loader(sport,scoreboard)
            reviews=moneyline_reviews(filtered,models)
            if reviews:st.dataframe(reviews,hide_index=True,use_container_width=True)
            else:st.info('No eligible research candidates. The model may be stale, games may be preseason, quotes may be old, or no qualifying price gap exists.')
    except OddsSourceError as exc:
        st.warning(str(exc))
    except (requests.exceptions.RequestException,ValueError,KeyError,TypeError,AttributeError,OSError):
        st.warning('Sportsbook data could not be loaded. Check your API key, credits, market coverage and selected date. Your other app sections remain available.')
