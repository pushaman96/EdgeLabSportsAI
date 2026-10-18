"""Opening possessions from explicit half-opening plays; expectations stay labeled."""
def half_possession(data):
    competition=(data.get('header',{}).get('competitions') or [{}])[0]
    names={str(c.get('team',{}).get('id') or c.get('id','')):c.get('team',{}).get('displayName','Unknown') for c in competition.get('competitors',[])}
    drives=list(data.get('drives',{}).get('previous',[]));current=data.get('drives',{}).get('current')
    if isinstance(current,dict):drives.append(current)
    plays=[p for d in drives for p in d.get('plays',[])]+list(data.get('plays',[]))
    def order(p):
        try:return int(p.get('sequenceNumber'))
        except (ValueError,TypeError):return 10**12
    plays.sort(key=order);seen=set();openers={}
    for play in plays:
        ident=play.get('id')
        if not ident or ident in seen:continue
        seen.add(ident)
        period=play.get('period',{}).get('number');clock=play.get('clock',{}).get('displayValue')
        if period not in (1,3) or period in openers or clock not in ('15:00','15:00.0'):continue
        kind=str(play.get('type',{}).get('text','')).lower();text=str(play.get('text','')).lower()
        if 'kickoff' not in kind and 'kick off' not in kind:continue
        if 'no play' in text or play.get('isPenalty'):continue
        kicker=str(play.get('start',{}).get('team',{}).get('id',''))
        possessor=str(play.get('end',{}).get('team',{}).get('id',''))
        openers[period]={'kicker':kicker,'possessor':possessor,'unusual':('onside' in text or 'onside' in kind or 're-kick' in text),'play':str(ident)}
    first=openers.get(1,{});second=openers.get(3,{})
    opening=names.get(first.get('possessor'))
    # Fallback only when the drive explicitly starts at the opening of Q1.
    if not opening:
        for drive in drives:
            start=drive.get('start') or {}
            if start.get('period',{}).get('number')==1 and start.get('clock',{}).get('displayValue')=='15:00' and drive.get('offensivePlays',0)>0:
                opening=names.get(str(drive.get('team',{}).get('id','')));break
    confirmed=names.get(second.get('possessor'))
    expected=names.get(first.get('kicker')) if first and len(names)==2 and first.get('kicker') in names and first.get('possessor') in names and not first.get('unusual') and first.get('kicker')!=first.get('possessor') and opening else None
    return {'Opening possession':opening or 'Not reported','Second-half start':('Confirmed: '+confirmed) if confirmed else ('Expected: '+expected+' — unconfirmed') if expected else 'Not confirmed','Second-half confirmed':bool(confirmed),'Note':'Opening possession uses the reported kickoff outcome or an explicitly timed opening drive. Expected second-half possession assumes the usual alternating kickoff choices; coin-toss choices and unusual kickoffs can differ. Confirmed means the Q3 opening kickoff outcome was reported.'}
