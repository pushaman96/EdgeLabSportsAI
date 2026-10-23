"""Archive timestamped observations; never alter picks, grades or model weights."""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import urlopen
from game_situations import situation_snapshot

PATH = 'live_game_research.json'

def utc(value):
    return datetime.fromisoformat(str(value).replace('Z', '+00:00'))

def observe(records, previous, fetch, now=None):
    now = now or datetime.now(timezone.utc)
    output = dict(previous)
    events = {}
    for r in records:
        if r.get('strategy') != 'Original' or r.get('evidence') == 'Historical import':
            continue
        try:
            start = utc(r['starts_utc'])
        except (KeyError, TypeError, ValueError):
            continue
        if not start <= now <= start + timedelta(hours=12):
            continue
        events.setdefault((r.get('sport', 'NFL'), str(r['event_id'])), []).append(r)
    errors = []
    for (sport, event), picks in events.items():
        key = sport + ':' + event
        try:
            data = fetch(sport, event)
            if str(data.get('header', {}).get('id', '')) != event:
                raise ValueError('Feed identity mismatch')
            snapshot = situation_snapshot(data, sport)
            from live_pick_board import current_stat
            competition = (data.get('header', {}).get('competitions') or [{}])[0]
            observation = {
                'observed_utc': now.isoformat(),
                'status': competition.get('status', {}),
                'scores': [{'team': c.get('team', {}).get('displayName'), 'score': c.get('score')} for c in competition.get('competitors', [])],
                'pick_stats': [{'pick_id': r['id'], 'player': r.get('player'), 'category': r.get('category'), 'observed_stat': current_stat(r, data)} for r in picks],
                'situation_splits': snapshot['situation_splits'],
                'last_play': snapshot['last_play'],
            }
            entry = dict(output.get(key, {}))
            timeline = list(entry.get('observations', []))
            if not timeline or timeline[-1].get('observed_utc') != observation['observed_utc']:
                timeline.append(observation)
            entry.update({'event_id': event, 'sport': sport, 'game': picks[0].get('game'), 'updated_utc': now.isoformat(), 'completed': snapshot['completed'], 'latest_situations': snapshot, 'observations': timeline[-100:], 'scope': 'Descriptive observations only. Missing statistics remain unknown. No picks or model weights changed; candidate corrections require chronological validation.'})
            output[key] = entry
        except Exception as exc:
            errors.append({'event_id': event, 'sport': sport, 'error': type(exc).__name__})
    return output, errors

def fetch(sport, event):
    league = 'basketball/nba' if sport == 'NBA' else 'football/nfl'
    with urlopen('https://site.api.espn.com/apis/site/v2/sports/' + league + '/summary?event=' + event, timeout=25) as response:
        return json.load(response)

def run():
    ledger = json.loads(Path('published_picks.json').read_text())
    records = ledger.get('records', []) if isinstance(ledger, dict) else ledger
    path = Path(PATH)
    previous = json.loads(path.read_text()) if path.exists() else {'games': {}}
    games, errors = observe(records, previous.get('games', {}), fetch)
    payload = {'schema': 1, 'checked_utc': datetime.now(timezone.utc).isoformat(), 'games': games, 'errors': errors}
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(payload, indent=2) + '\n')
    temp.replace(path)
    print(json.dumps({'observed_games': len(games), 'errors': errors}))

if __name__ == '__main__':
    run()
