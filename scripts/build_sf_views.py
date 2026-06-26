#!/usr/bin/env python3
"""Deterministicky prepocita Salesforce pohledy a smerguje je do index.html.
Pevna logika (model jako firstcall-monitor build_data.py). Akumulator + ochrany proti clobbering.
Vstupy (v adresari SF_WORK, default $HOME) - zpracuje jen ty, co existuji:
  sf_caraudit_recent.json  -> FC1 (1st Call) + CA1 (CarAudit) weekly  [Case: CA_New_CarAudit_Date__c, CA_Awaiting_Selection_Date__c, CarAudit_Status__c, Status]
  sf_imca_orders.json + sf_imca_invoices.json -> IMCA (IM Contract Accepted)
  sf_pconv_paid.json + sf_pconv_lost.json     -> PCONV (Preferred konverze)
  sf_cp_active.json -> ROWS (Active Purchases: Car Purchase non-terminal, faze x stari)
"""
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
WORK = os.environ.get('SF_WORK', os.path.expanduser('~'))
def load(name):
    p=os.path.join(WORK,name)
    return json.load(open(p)) if os.path.exists(p) else None

# ---- FC1 + CA1 (weekly, z CarAudit casu) ----
def compute_weekly(records):
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
def merge_weekly(html, name, fresh):
    m = re.search(r'const '+name+r'=(\[.*?\]);', html, re.DOTALL)
    if not m: raise SystemExit(f"const {name} not found")
    d = {row[0]: row for row in json.loads(m.group(1))}
    for lab,(dn,ip,cl) in fresh.items():
        old=d.get(lab); oldtot=sum(old[1:]) if old else 0; tot=dn+ip+cl
        if old and oldtot>=50 and tot < oldtot*0.5: continue   # ochrana: nepřepiš partial daty
        d[lab]=[lab,dn,ip,cl]
    rows=sorted(d.values(), key=lambda r: wkkey(r[0]))
    return html[:m.start()]+'const '+name+'='+json.dumps(rows,ensure_ascii=False).replace(' ','')+';'+html[m.end():]

# ---- IMCA ----
def imca_typ(ec,edp,eb):
    if edp and eb: return "DP+FIN"
    if eb and not edp: return "FIN"
    if ec: return "CASH"
    return "—"
def build_imca(orders, invoices):
    inv={}
    for r in invoices:
        nm=r.get('Order__r',{}).get('Name'); dt=r.get('Invoice_Date__c')
        if nm and dt and nm not in inv: inv[nm]=dt   # nejnovejsi (dotaz ORDER BY DESC)
    out=[]
    for o in orders:
        nm=o.get('Name')
        out.append({"num":nm,"acc":(o.get('Account') or {}).get('Name'),
            "typ":imca_typ(o.get('Expected_Payment_From_Customer__c'),o.get('Expected_Down_Payment_from_the_Customer__c'),o.get('Expected_Payment_from_Bank__c')),
            "ca":(o.get('Contract_Accepted_Date__c') or '')[:10],"inv":inv.get(nm),
            "ec":o.get('Expected_Payment_From_Customer__c'),"rc":o.get('Received_Amount_from_Customer__c'),
            "edp":o.get('Expected_Down_Payment_from_the_Customer__c'),"rdp":o.get('Received_Down_Payment_from_the_Customer__c'),
            "ccp":(o.get('Customer_Contract_Paid_Date__c') or None),"eb":o.get('Expected_Payment_from_Bank__c'),
            "rb":o.get('Received_Amount_from_Bank__c'),"bcp":(o.get('Bank_Contract_Paid_Date__c') or None)})
    out.sort(key=lambda r:(r['ca'] or ''))
    return out
def replace_const(html,name,value_js):
    m=re.search(r'const '+name+r'=(\[.*?\]);', html, re.DOTALL)
    if not m: raise SystemExit(f"const {name} not found")
    return html[:m.start()]+'const '+name+'='+value_js+';'+html[m.end():]

# ---- PCONV ----
def build_pconv(paid, lost):
    P={(r['y'],r['m']):r['paid'] for r in paid}; L={(r['y'],r['m']):r['lost'] for r in lost}
    months=[(2025,m) for m in range(3,13)]+[(y,m) for y in range(2026,2031) for m in range(1,13)]
    import datetime as _dt; now=_dt.date.today()
    rows=[]
    for y,m in months:
        if (y,m)>(now.year,now.month): break
        rows.append(["%04d-%02d"%(y,m),P.get((y,m),0),L.get((y,m),0)])
    return rows


# ---- Active Purchases (Car Purchase, faze x stari) ----
import datetime as _dt
# CZ statni svatky (rozsah pro busday vypocet stari aktivni faze)
CZ_HOL = {d for d in [
  "2025-01-01","2025-04-18","2025-04-21","2025-05-01","2025-05-08","2025-07-05","2025-07-06","2025-09-28","2025-10-28","2025-11-17","2025-12-24","2025-12-25","2025-12-26",
  "2026-01-01","2026-04-03","2026-04-06","2026-05-01","2026-05-08","2026-07-05","2026-07-06","2026-09-28","2026-10-28","2026-11-17","2026-12-24","2026-12-25","2026-12-26",
  "2027-01-01","2027-03-26","2027-03-29","2027-05-01","2027-05-08","2027-07-05","2027-07-06","2027-09-28","2027-10-28","2027-11-17","2027-12-24","2027-12-25","2027-12-26"]}
CP_DATEFIELD = {
  "New":"CP_New_Date__c","Dealer Contacted":"CP_Dealer_Contacted_Date__c",
  "Contract Preparation":"CP_Contract_Preparation_Date__c","Awaiting Approval":"CP_Awaiting_Approval_Date__c",
  "Contract Signature":"CP_Contract_Signature_Date__c","Payment Processing":"CP_Payment_Processing_Date__c"}
CP_ORDER = ["New","Dealer Contacted","Contract Preparation","Awaiting Approval","Contract Signature","Payment Processing"]
def _busday(start, end):
    # pracovni dny v [start, end) mimo vikendy a CZ_HOL (jako np.busday_count)
    if start >= end: return 0
    cnt=0; d=start
    while d < end:
        if d.weekday() < 5 and d.isoformat() not in CZ_HOL: cnt+=1
        d += _dt.timedelta(days=1)
    return cnt
def _bucket(a):
    if a < 2:  return "b02"
    if a < 3:  return "b23"
    if a < 5:  return "b35"
    if a < 10: return "b510"
    return "b10"
def build_active_purchases(records):
    today = _dt.datetime.now(PRAGUE).date()
    mat = {s:{"b02":0,"b23":0,"b35":0,"b510":0,"b10":0} for s in CP_ORDER}
    for r in records:
        s = r.get("Status")
        if s not in mat: continue
        dv = r.get(CP_DATEFIELD[s])
        if not dv: continue   # bez data aktualni faze -> preskoc (skipped_no_date)
        d = _dt.date(int(dv[:4]), int(dv[5:7]), int(dv[8:10]))
        mat[s][_bucket(_busday(d, today))] += 1
    return [dict(status=s, **mat[s]) for s in CP_ORDER]

def main():
    html=open('index.html',encoding='utf-8').read(); did=[]
    car=load('sf_caraudit_recent.json')
    if car is not None:
        recs=car['records']
        if len(recs)<200: raise SystemExit(f"ABORT: jen {len(recs)} CarAudit zaznamu (<200).")
        fc,ca=compute_weekly(recs); html=merge_weekly(html,'FC1',fc); html=merge_weekly(html,'CA1',ca); did+=['FC1','CA1']
    od=load('sf_imca_orders.json'); iv=load('sf_imca_invoices.json')
    if od is not None and iv is not None:
        imca=build_imca(od['records'], iv['records'])
        html=replace_const(html,'IMCA',json.dumps(imca,ensure_ascii=False)); did.append('IMCA')
    pp=load('sf_pconv_paid.json'); pl=load('sf_pconv_lost.json')
    if pp is not None and pl is not None:
        pconv=build_pconv(pp['records'], pl['records'])
        html=replace_const(html,'PCONV',json.dumps(pconv,ensure_ascii=False).replace(' ','')); did.append('PCONV')
    cp=load('sf_cp_active.json')
    if cp is not None:
        rows=build_active_purchases(cp['records'])
        html=replace_const(html,'ROWS',json.dumps(rows,ensure_ascii=False)); did.append('ROWS')
    open('index.html','w',encoding='utf-8').write(html)
    print("OK | updated:", did)
if __name__=='__main__': main()
