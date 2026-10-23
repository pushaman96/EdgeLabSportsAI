"""Small append-only analysis partitions; never rewrites the legacy large ledger."""
import hashlib
from collections import defaultdict

def partitions(records):
    groups=defaultdict(list)
    for row in records:
        sport=row.get('sport','NFL')
        event=str(row['event_id'])
        if sport not in ('NFL','NBA') or not event.isdigit():
            raise ValueError('Invalid analysis archive identity')
        bucket=int(hashlib.sha256(str(row['id']).encode()).hexdigest()[:2],16)%4
        groups[f'forecast_analysis/{sport}_{event}_{bucket}.json'].append(row)
    return groups

def flush(pending,confirmed,token,client,writer=None):
    if writer is None:
        from pick_history import persist_records
        writer=persist_records
    saved=0
    for path,rows in sorted(partitions(list(pending.values())).items()):
        writer(rows,token,client,ledger=path,allow_create=True)
        # Remove only IDs read back successfully. Partial success survives a later failure.
        for row in rows:
            confirmed.add(row['id'])
            pending.pop(row['id'],None)
            saved+=1
    return saved
