"""Attach already loaded totals to prop snapshots without another odds call."""
def with_game_totals(events,game_events):
    games={e['id']:e for e in game_events};output=[]
    for event in events:
        source=games.get(event['id'],{})
        books={b.get('key')or b['title']:dict(b,markets=list(b.get('markets',[])))for b in event.get('bookmakers',[])}
        for b in source.get('bookmakers',[]):
            totals=[m for m in b.get('markets',[])if m.get('key')=='totals']
            if not totals:continue
            identity=b.get('key')or b['title']
            target=books.setdefault(identity,dict(b,markets=[]))
            if not any(m.get('key')=='totals'for m in target['markets']):target['markets'].extend(totals)
        output.append(dict(event,bookmakers=list(books.values())))
    return output
