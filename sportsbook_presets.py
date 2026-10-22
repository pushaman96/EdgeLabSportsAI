"""Saved market choices; these do not imply available or validated forecasts."""
STANDARD_PRESETS={
    'NFL':['Passing yards','Rushing yards','Anytime touchdown scorer','Receiving yards'],
    'NBA':['Points','Assists','Rebounds','PRA — points + rebounds + assists','Three-pointers made'],
}
NBA_EXTRA_MARKETS={
    'PRA — points + rebounds + assists':'player_points_rebounds_assists',
    'Field goals made':'player_field_goals',
    'Free throws made':'player_frees_made',
    'Free throws attempted':'player_frees_attempts',
    'Team total points':'team_totals',
}
def preset_budget(sport,games):return 3+games*len(STANDARD_PRESETS[sport])

def archive_market_board(events,retrieved,sport):
    """Archive by game to keep reports manageable; quotations are not training picks."""
    from automatic_reports import autosave_report
    import json
    references=[]
    for event in events:
        name=sport.lower()+'_market_'+str(event['id'])+'.json'
        autosave_report('Loaded market quotes',json.dumps({'retrieved':retrieved,'event':event,'status':'Market quotes, not model recommendations'},sort_keys=True),file_name=name,mime='application/json')
        references.append(name)
    if references:
        autosave_report('Loaded market board index',json.dumps({'retrieved':retrieved,'reports':references,'status':'Market quotes, not model recommendations'},sort_keys=True),file_name=sport.lower()+'_loaded_market_board.json',mime='application/json')

def automatic_plan(sport,selected_date,today,budget,mode,attempted):
    """One automatic run per sport/day/session, within a total eight-credit cap."""
    enabled=(selected_date==today and (sport=='NBA' or today.weekday()in (6,0,3))
             and mode!='Saved data only — 0 credits' and not attempted)
    cap=min(8,int(budget))
    games=max(0,(cap-3)//len(STANDARD_PRESETS[sport])) if enabled else 0
    return {'enabled':enabled and games>0,'max_games':games,'cap':cap}

def reconcile_prop_selection(state,sport,event_ids,category_labels):
    """Reconcile widgets before creation; keep started games visible, never fetch."""
    game_key='sportsbook_props_game_'+sport
    if state.get(game_key) not in set(event_ids)|{'__all_nfl_games__','__multiple_prop_games__'}:
        state[game_key]='__multiple_prop_games__'
    games_key='credit_saver_games_'+sport
    if games_key in state:
        state[games_key]=[v for v in state[games_key] if v in event_ids]
    categories_key='sportsbook_props_categories_'+sport
    if categories_key in state:
        state[categories_key]=[v for v in state[categories_key] if v in category_labels]
