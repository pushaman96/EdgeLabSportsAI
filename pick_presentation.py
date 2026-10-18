"""Presentation-only team accents and final/live status labels."""
import html,re
from datetime import datetime,timezone

def team_color(value):
    value=str(value or '').lstrip('#')
    return '#'+value if re.fullmatch(r'[0-9a-fA-F]{6}',value) else '#64748b'

def accent_html(color):
    return '<div aria-hidden="true" style="height:4px;border-radius:6px;margin-bottom:12px;background:'+team_color(color)+'"></div>'

def pick_status(record,live_row=None,now=None):
    row=live_row or {};result=row.get('Final result')
    if result not in ('Win','Loss','Push'):result=record.get('result')
    if result in ('Win','Loss','Push'):return {'Win':'Won','Loss':'Lost','Push':'Push'}[result]
    position=row.get('Live position','')
    if position=='Final' or position.startswith('Final —'):return 'Final · review needed'
    if 'ongoing' in position:return 'Live'
    period=row.get('Period / clock','')
    if (period.startswith('Q') or period.startswith('OT')) and 'unavailable' not in position and 'mismatch' not in position:return 'Live'
    try:
        starts=datetime.fromisoformat(record['starts_utc'].replace('Z','+00:00'))
        if (now or datetime.now(timezone.utc))<starts:return 'Pregame'
    except (KeyError,ValueError,TypeError):pass
    return 'Awaiting update'

def badge_html(label):
    palette={'Won':('#dcfce7','#166534'),'Lost':('#fee2e2','#991b1b'),'Push':('#e2e8f0','#334155'),'Live':('#dbeafe','#1e40af'),'Pregame':('#e2e8f0','#334155')}
    background,color=palette.get(label,('#fef3c7','#92400e'))
    return '<span style="display:inline-block;padding:3px 10px;border-radius:12px;font-size:0.85rem;font-weight:600;background:'+background+';color:'+color+'">'+html.escape(label)+'</span>'

def filter_matchup(records,game):
    return list(records) if game=='All games' else [r for r in records if r.get('game')==game]



def result_indicator(row):
    """Only verified final grades receive a win/loss symbol."""
    return {'Win':'✅ Win','Loss':'❌ Loss','Push':'➖ Push'}.get(row.get('Final result'),'⏳ Pending')
