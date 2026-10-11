"""Reported sportsbook prices and optional The Odds API connection."""
import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import requests
import streamlit as st
from nfl_prop_model import render_prop_research

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
        error = OddsSourceError(messages.get(response.status_code,f'Odds source returned HTTP {response.status_code}. Check market coverage and your account.'))
        error.status_code = response.status_code
        raise error
    try:data=response.json()
    except ValueError:raise OddsSourceError('Odds source returned unreadable data.') from None
    if not isinstance(data,(dict,list)):raise OddsSourceError('Unexpected odds source data.')
    return {'data':data,'retrieved':datetime.now(timezone.utc).isoformat(),'remaining':response.headers.get('x-requests-remaining','Not supplied'),'cost':response.headers.get('x-requests-last','Not supplied')}

def load_all_prop_lines(api_key, sport, events, markets, now=None):
    now = now or datetime.now(timezone.utc)
    fetched, failures = [], []
    for event in events:
        if datetime.fromisoformat(event['commence_time'].replace('Z','+00:00')) <= now:
            continue
        game = event['away_team']+' at '+event['home_team']
        try:
            result = odds_request(api_key,sport,event['id'],markets)
            data = result['data']
            if not isinstance(data,dict) or data.get('id') != event['id'] or (data.get('home_team'),data.get('away_team')) != (event['home_team'],event['away_team']):
                failures.append(game+': no matching prop data returned.')
                continue
            fetched.append(result)
        except OddsSourceError as exc:
            failures.append(game+': '+str(exc))
            if getattr(exc,'status_code',None) in (401,403,429):
                failures.append('Stopped remaining requests because the key, account access, or usage limit needs attention.')
                break
    latest = max(fetched,key=lambda r:r['retrieved']) if fetched else None
    return {'results':fetched,'failures':failures,'remaining':latest['remaining'] if latest else 'Not supplied','loaded':datetime.now(timezone.utc).isoformat()}

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
        st.caption('This feed does not report bet counts or betting volume. Common categories are not a ranking of popular bets. Load yardage props, then use Analyze loaded player props for a watch/pass shortlist. Spreads and totals are not modeled yet.')
        all_option = '__all_nfl_games__'
        event_id=st.selectbox('Player props game',[e['id'] for e in events]+[all_option],format_func=lambda value:'All NFL games on selected date' if value==all_option else next(e['away_team']+' at '+e['home_team'] for e in events if e['id']==value),key='sportsbook_props_game')
        labels=st.multiselect('Prop categories',list(PROP_MARKETS[sport]),default=list(PROP_MARKETS[sport])[:2],key='sportsbook_props_categories')
        markets=','.join(sorted(PROP_MARKETS[sport][label] for label in labels))
        if event_id == all_option:
            targets = [e for e in events if datetime.fromisoformat(e['commence_time'].replace('Z','+00:00')) > datetime.now(timezone.utc)]
            st.caption(f'All games: {len(targets)} upcoming NFL games × {len(labels)} categories = up to {len(targets)*len(labels)} credits for a fresh load. Cached responses may cost no new credits. Started games are skipped. Analysis adds no sportsbook credits.')
            batch_key = (sport,key,str(selected_date),markets,tuple(e['id'] for e in targets))
            loaded_all = st.button('Load all games and analyze player props',key='sportsbook_props_all_load',disabled=not markets or not targets)
            if loaded_all and markets and targets:
                st.session_state.pop('sportsbook_props_all_result',None)
                with st.spinner('Loading selected prop categories for all upcoming NFL games...'):
                    batch = load_all_prop_lines(key,sport,targets,markets)
                st.session_state['sportsbook_props_all_result'] = (batch_key,batch)
            all_saved = st.session_state.get('sportsbook_props_all_result')
            if all_saved and all_saved[0] == batch_key:
                batch = all_saved[1]
                for failure in batch['failures']:st.warning(failure)
                loaded_events = [r['data'] for r in batch['results']]
                st.caption(f"Loaded {len(loaded_events)} of {len(targets)} games. Most recent provider-reported credits remaining: {batch['remaining']}.")
                if loaded_events:
                    if st.checkbox('Show all loaded player prop prices',key='sportsbook_show_all_prices'):
                        st.dataframe(bookmaker_rows(loaded_events,selected_books,True),hide_index=True,use_container_width=True)
                    render_prop_research(loaded_events,scoreboard,selected_books,batch['loaded'],auto_analyze=loaded_all)
                else:st.info('No prop data loaded. Check coverage and the warnings above.')
        else:
            if st.button('Load selected player prop lines',key='sportsbook_props_load') and markets:
                prop_result=odds_request(key,sport,event_id,markets)
                st.session_state['sportsbook_props_result']=(sport,key,event_id,markets,prop_result)
            prop_saved=st.session_state.get('sportsbook_props_result')
            if prop_saved and prop_saved[:4]==(sport,key,event_id,markets):
                props=bookmaker_rows([prop_saved[4]['data']],selected_books,True)
                if props:st.dataframe(props,hide_index=True,use_container_width=True)
                else:st.info('No selected player props returned.')
                st.caption(f"Prop request credits remaining: {prop_saved[4]['remaining']}. Request cost: {prop_saved[4]['cost']}.")
                if props:
                    render_prop_research(prop_saved[4]['data'],scoreboard,selected_books,prop_saved[4]['retrieved'])
        st.subheader('NFL game shortlist — experimental moneylines')
        st.caption('Compares adjusted Elo with the break-even price; requires a gap of at least five percentage points, a quote no more than 15 minutes old, and regular-season model history no more than 30 days old. These are research candidates, not validated betting recommendations. Injuries and lineups are not included.')
        if st.button('Compare model with current moneylines',key='sportsbook_research'):
            models=model_loader(sport,scoreboard)
            reviews=moneyline_reviews(filtered,models)
            if reviews:
                for row in reviews:
                    row['Decision'] = 'Watch — experimental'
                    row['Reason'] = 'Adjusted win probability exceeds the quoted break-even price by at least five percentage points. Check quarterback, injuries and weather.'
                st.dataframe(reviews,hide_index=True,use_container_width=True)
            else:st.info('Pass — no eligible research candidates. The model may be stale, games may be preseason, quotes may be old, or no qualifying price gap exists.')
    except OddsSourceError as exc:
        st.warning(str(exc))
    except (requests.exceptions.RequestException,ValueError,KeyError,TypeError,AttributeError,OSError):
        st.warning('Sportsbook data could not be loaded. Check your API key, credits, market coverage and selected date. Your other app sections remain available.')
