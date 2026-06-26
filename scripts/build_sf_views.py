#!/usr/bin/env python3
"""Deterministicky prepocita Salesforce WEEKLY pohledy (FC1=1st Call, CA1=CarAudit Done/IP/Closed)
a smerguje je do index.html. Pevna logika (model jako firstcall-monitor). Akumulator: tydny ze
vstupu prepise, starsi nechá. OCHRANY proti clobbering spatnymi/castecnymi daty."""
import json, re, os
from datetime import datetime, timedelta, timezone
PRAGUE = timezone(timedelta(hours=2))
REJ1 = {'REJECT New CA','REJECT Data Validation','REJECT Car Check','REJECT VIN Check'}
P2KW = ['reject awaiting selection','reject auditor selection','reject audit order','reject caraudit preparation','reject audit result']
P2_PROG = {'Auditor selection','Audit order','CarAudit preparation','Audit result'}
def pdt(s): return datetime.fromisoformat(s.replace('+0000','+00:00')) if s else None
def iso_label(dt):
    iso = dt.astimezone(PRAGUE).isocalendar(); return f"{iso[1]}/{str(iso[0])[2:]}"
def wkkey(label): w,y = label.split('/'); return (2000+int(y), int(w))
def compute(records):
    fc, ca = {}, {}
    for r in records:
        cn = pdt(r.get('CA_New_CarAudit_Date__c'))
        if not cn: continue
        lab = iso_label(cn); fc.setdefault(lab,[0,0,0]); ca.setdefault(lab,[0,0,0])
        aws=r.get('CA_Awaiting_Selection_Date__c'); st=(r.get('Status') or '').strip()
        cs=(r.get('CarAudit_Status__c') or '').strip(); csl=cs.lower()
        if aws not in (None,''): fc[lab][0]+=1
        elif cs in REJ1: fc[lab][2]+=1
        else: fc[lab][1]+=1
        if st=='CarAudit Done': ca[lab][0]+=1
        elif st=='Awaiting Selection' and 'approved awaiting selection' in csl: ca[lab][1]+=1
        elif st in P2_PROG: ca[lab][2 if 'reject' in csl else 1]+=1
        elif st=='CarAudit Closed' and any(k in csl for k in P2KW): ca[lab][2]+=1
    return fc, ca
def merge_const(html, name, fresh):
    m = re.search(r'const '+name+r'=(\[.*?\]);', html, re.DOTALL)
    if not m: raise SystemExit(f"const {name} not found")
    existing = json.loads(m.group(1)); d = {row[0]: row for row in existing}
    for lab,(dn,ip,cl) in fresh.items():
        tot=dn+ip+cl; old=d.get(lab); oldtot=sum(old[1:]) if old else 0
        # OCHRANA: nepřepisuj existujici tyden hodnotou drasticky nizsi (partial/spatna data)
        if old and oldtot>=50 and tot < oldtot*0.5:
            continue
        d[lab] = [lab, dn, ip, cl]
    rows = sorted(d.values(), key=lambda r: wkkey(r[0]))
    return html[:m.start()] + 'const '+name+'='+json.dumps(rows,ensure_ascii=False).replace(' ','')+';' + html[m.end():]
def main():
    work = os.environ.get('SF_WORK', os.path.expanduser('~'))
    recs = json.load(open(os.path.join(work,'sf_caraudit_recent.json')))['records']
    if len(recs) < 200:
        raise SystemExit(f"ABORT: jen {len(recs)} CarAudit zaznamu (<200) - podezrele malo, NEPREPISUJI (ochrana).")
    fc, ca = compute(recs)
    html = open('index.html', encoding='utf-8').read()
    html = merge_const(html, 'FC1', fc)
    html = merge_const(html, 'CA1', ca)
    open('index.html','w',encoding='utf-8').write(html)
    print(f"OK | FC1+CA1 merged, weeks={sorted(fc,key=wkkey)}, input_recs={len(recs)}")
if __name__=='__main__': main()
