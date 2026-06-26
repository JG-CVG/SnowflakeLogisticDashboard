#!/usr/bin/env python3
"""Deterministicky prepocita Salesforce pohledy a smerguje je do index.html.
Pevna logika (model jako firstcall-monitor build_data.py). Akumulator + ochrany proti clobbering.
Vstupy (v adresari SF_WORK, default $HOME) - zpracuje jen ty, co existuji:
  sf_caraudit_recent.json  -> FC1 (1st Call) + CA1 (CarAudit) weekly  [Case: CA_New_CarAudit_Date__c, CA_Awaiting_Selection_Date__c, CarAudit_Status__c, Status]
  sf_imca_orders.json + sf_imca_invoices.json -> IMCA (IM Contract Accepted)
  sf_pconv_paid.json + sf_pconv_lost.json     -> PCONV (Preferred konverze)
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
    open('index.html','w',encoding='utf-8').write(html)
    print("OK | updated:", did)
if __name__=='__main__': main()
