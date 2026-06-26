#!/usr/bin/env python3
"""Deterministicky prepocita Salesforce pohledy a smerguje je do index.html.
Pevna logika (model jako firstcall-monitor build_data.py). Akumulator + ochrany proti clobbering.
Vstupy (v adresari SF_WORK, default $HOME) - zpracuje jen ty, co existuji:
  sf_caraudit_recent.json  -> FC1 (1st Call) + CA1 (CarAudit) weekly  [Case: CA_New_CarAudit_Date__c, CA_Awaiting_Selection_Date__c, CarAudit_Status__c, Status]
  sf_imca_orders.json + sf_imca_invoices.json -> IMCA (IM Contract Accepted)
  sf_pconv_paid.json + sf_pconv_lost.json     -> PCONV (Preferred konverze)
  sf_cp_active.json -> ROWS (Active Purchases: Car Purchase non-terminal, faze x stari)
  sf_seller.json + sf_rates.json -> S1/S2 (Seller Payment Backlog)
  sf_dreg.json -> DREG (Instamotion Document & Registration: aktivni dle Kroschke statusu, [idx,date])
  sf_pstr.json -> PSTR (Price structure completed CA from seller, % po mesicich; [m/yy,free,p1_100,p100_120,p120_125,p125_145,p145plus])
  sf_suit_total.json + sf_suit_seller.json -> SUIT (CA from seller evaluated as suitable, mesicne; [m/yy,fromSeller,total]; od 12/25)
  sf_fctop_{normal,detail,lost,neither}.json -> FCTOP (1st Call Closed Top reasons, Phase 1; [reason,m_cur,ytd,prev])
  sf_catop_{normal,detail,lost,neither}.json -> CATOP (CarAudit Closed Top reasons, Phase 2; [reason,m_cur,ytd,prev])
  sf_car2.json -> CAR2 (CarAudit Closed reason breakdown weekly, Phase 2; [wk,car_na,car_cond,seller,auto,client,carvago,other])
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


# ---- Seller Payment Backlog (S1 = Is Contract Paid & not PP ; S2 = Payment Processing) ----
def _sb_eur(o, rates):
    p=o.get('Car_List_Price__c'); c=o.get('Car_List_Price_Currency__c')
    if p is None or not c or not rates.get(c): return 0.0
    return p/rates[c]                       # korporatni mena = EUR (kurz=1) -> delenim na EUR
def build_seller_backlog(records, rates):
    from collections import defaultdict
    today=_dt.datetime.now(PRAGUE).date()
    def grp(sub, money):
        d=defaultdict(lambda:[0,0,0,0,0.0,0.0])   # tot, <=2, 3-4, >4, eur, eur_over
        for r in sub:
            o=r.get('Order__r') or {}
            comp=(o.get('Invoicing_Company__r') or {}).get('Name') or '— (bez Invoicing Company)'
            dv=r.get(CP_DATEFIELD.get(r.get('Status'),''))
            a=_busday(_dt.date(int(dv[:4]),int(dv[5:7]),int(dv[8:10])), today) if dv else None
            b=0 if (a is not None and a<=2) else (1 if (a is not None and a<=4) else 2)
            e=_sb_eur(o,rates); row=d[comp]; row[0]+=1; row[1+b]+=1; row[4]+=e
            if b==2: row[5]+=e
        out=[]
        for comp,row in sorted(d.items(), key=lambda x:-x[1][4]):
            out.append([comp,row[0],row[1],row[2],row[3]]+([round(row[4]),round(row[5])] if money else []))
        return out
    s1=grp([r for r in records if r.get('Status')!='Payment Processing' and (r.get('Order__r') or {}).get('Is_Contract_Paid__c')], False)
    s2=grp([r for r in records if r.get('Status')=='Payment Processing'], True)
    return s1, s2


# ---- Doc & Registration (Instamotion) : [kroschke_idx, coordination_date] ----
DREG_KROSCHKE_IDX = {
  "2/6 wartet auf Zulassungsunterlagen":0,   # 2/6 Waiting For Reg. Documents
  "3/6 Bearbeitung durch Kroschke":1,         # 3/6 Bearbeitung durch Kroschke
  "4/6 Weitergeleitet an Zulassungsdienst":2, # 4/6 Forwarded To Reg. Service
  "5/6 Eingegangen beim Zulassungsdienst":3}  # 5/6 Received By Reg. Service
def build_dreg(records):
    out=[]
    for r in records:
        st=r.get('Status__c')
        if st in ('car-registration-done','car-registration-closed'): continue   # ne-aktivni
        k=r.get('Kroschke_Registration_Status__c')
        if k and k.startswith('0/0'): continue   # storniert / Klarfall beendet = neaktivni
        dv=r.get('Coordination_with_Vendor_Date__c')
        if not dv: continue
        out.append([DREG_KROSCHKE_IDX.get(k,4), dv[:10]])   # else -> 4 = "Bez statusu"
    return out


# ---- PSTR (Price structure - completed CA from seller, % po mesicich) ----
# Filtr je v SOQL (Status='CarAudit Done' + Car_inspection_by_Vendor__c vyplneno, ne '-').
# Mesic = CA_New_CarAudit_Date__c. Amount=null -> vyloucit (i z n). 0=Free OK.
# Bez Instamotion/XK-AL filtru (overeno 1:1 proti referenci: 11/25 free56 n85).
def _pstr_bucket(a):
    if a==0:   return 'free'
    if a<=100: return 'p1_100'
    if a<=120: return 'p100_120'
    if a<=125: return 'p120_125'
    if a<=145: return 'p125_145'
    return 'p145plus'
PSTR_KEYS=['free','p1_100','p100_120','p120_125','p125_145','p145plus']
def build_pstr(records):
    from collections import defaultdict
    agg=defaultdict(lambda: defaultdict(int))
    for r in records:
        dv=r.get('CA_New_CarAudit_Date__c')
        if not dv: continue
        ca=r.get('CarAudit__r') or {}
        a=ca.get('CarAudit_Amount__c')
        if a is None: continue                      # blank amount -> vyloucit (i z n)
        y=int(dv[:4]); m=int(dv[5:7])
        agg[(y,m)][_pstr_bucket(float(a))]+=1
    rows=[]
    for (y,m) in sorted(agg):                       # oldest first (chart reverses -> newest left)
        lab=f"{m}/{str(y)[2:]}"
        b=agg[(y,m)]
        rows.append([lab]+[b.get(k,0) for k in PSTR_KEYS])
    return rows


# ---- SUIT (CA from seller - evaluated as suitable, mesicne; od 12/25) ----
# Dve aggregate SOQL (PCONV-style, GROUP BY rok/mesic), kazda {yr,mo,c}:
#   total      = CarAudit (RecordType CarAudit/Carvago CarAudit), Carvago (Instamotion=false),
#                NOT XK/AL, CarAudit_Status__c != 'REJECT New CA', dle CA New date.
#   fromSeller = total + CarAudit__r.Car_inspection_by_Vendor__c vyplneno (!= null, != '-').
# Overeno proti referenci (live SF 26.06.2026, settled mesice ±<=5): 12/25 300/944, 5/26 816/1954.
def build_suit(seller, total):
    T={(r['yr'],r['mo']):r['c'] for r in total}
    S={(r['yr'],r['mo']):r['c'] for r in seller}
    rows=[]
    for (y,m) in sorted(set(T)|set(S)):
        if (y,m) < (2025,12): continue            # od 12/25
        rows.append([f"{m}/{str(y)[2:]}", S.get((y,m),0), T.get((y,m),0)])
    return rows


# ---- FCTOP / CATOP (Top reasons, Phase 1 / Phase 2; [reason, m_cur, ytd, prev]) ----
# Efektivni duvod (= compute_all.py get_effective_reason) je rozlozen do 4 groupable aggregate SOQL:
#   normal  = CarAudit__r.Reason_Code__c (rc), kde rc != 'Closed Order, automatically reject'
#   detail  = auto-reject + Detail_Reason_Code__c (dr) vyplneno  -> efektivni = dr
#   lost    = auto-reject + Detail=null + Order Sales LOST (sl)  -> efektivni = sl
#   neither = auto-reject + Detail=null + SalesLOST=null         -> efektivni = 'Closed Order, automatically reject'
# Obdobi dle CA New date: m_cur = aktualni mesic, ytd = aktualni rok, prev = predchozi rok. Top 15 dle ytd.
AUTO_REJECT='Closed Order, automatically reject'
def build_top_reasons(normal, detail, lost, neither, topn=15):
    from collections import defaultdict
    now=_dt.datetime.now(PRAGUE).date(); cy,cm,py=now.year,now.month,now.year-1
    per=defaultdict(lambda: defaultdict(int))     # (yr,mo)->reason->count
    for r in normal:  per[(r['yr'],r['mo'])][r['rc']]+=r['c']
    for r in detail:  per[(r['yr'],r['mo'])][r['dr']]+=r['c']
    for r in lost:    per[(r['yr'],r['mo'])][r['sl']]+=r['c']
    for r in neither: per[(r['yr'],r['mo'])][AUTO_REJECT]+=r['c']
    mcur=defaultdict(int); ytd=defaultdict(int); prev=defaultdict(int)
    for (y,m),d in per.items():
        for reason,c in d.items():
            if y==cy and m==cm: mcur[reason]+=c
            if y==cy: ytd[reason]+=c
            if y==py: prev[reason]+=c
    reasons=set(mcur)|set(ytd)|set(prev)
    rows=[[r,mcur.get(r,0),ytd.get(r,0),prev.get(r,0)] for r in reasons]
    rows.sort(key=lambda x:(-x[2],-x[3],-x[1]))
    return rows[:topn]


# ---- CAR2 (CarAudit Closed reason breakdown, weekly, Phase 2) ----
# Vstup = denni agregace {d:'YYYY-MM-DD', rc:CarAudit__r.Reason_Code__c, c}. ISO tyden + kategorie (map_reason_ca).
# Phase 2 filtr je v SOQL. Kategorie dle compute_all.py map_reason_ca (poradi check DULEZITE).
def _map_reason_ca(reason):
    r=str(reason).strip().lower()
    if 'car not available' in r or 'no longer online' in r or 'not for b2b sale' in r: return 'car_na'
    if 'fault at client' in r or 'client' in r: return 'client'
    if 'fault in car condition' in r or 'car was damaged' in r or 'damaged or with faults' in r or 'not recommended' in r: return 'car_cond'
    if 'fault at seller' in r or 'don\u00b4t selling' in r or "doesn't cooperate" in r or 'don\u00b4t cooperate' in r or 'wrong pricing' in r or 'untrusty' in r: return 'seller'
    if 'automatically reject' in r or 'closed order' in r: return 'auto'
    if 'carvago decision' in r: return 'carvago'
    return 'other'
CAR2_CATS=['car_na','car_cond','seller','auto','client','carvago','other']
def build_car2(records):
    from collections import defaultdict
    wk=defaultdict(lambda: defaultdict(int))
    for rec in records:
        d=rec.get('d');
        if not d: continue
        iso=_dt.date(int(d[:4]),int(d[5:7]),int(d[8:10])).isocalendar()
        iy,iw=iso[0],iso[1]
        wk[(iy*100+iw, f"{iw}/{str(iy)[2:]}")][_map_reason_ca(rec.get('rc'))]+=rec['c']
    rows=[]
    for (sk,lab) in sorted(wk):
        c=wk[(sk,lab)]
        rows.append([lab]+[c.get(k,0) for k in CAR2_CATS])
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
    cp=load('sf_cp_active.json')
    if cp is not None:
        rows=build_active_purchases(cp['records'])
        html=replace_const(html,'ROWS',json.dumps(rows,ensure_ascii=False)); did.append('ROWS')
    sb=load('sf_seller.json'); rt=load('sf_rates.json')
    if sb is not None and rt is not None:
        rates={x['IsoCode']:x['ConversionRate'] for x in rt['records']}
        s1,s2=build_seller_backlog(sb['records'], rates)
        html=replace_const(html,'S1',json.dumps(s1,ensure_ascii=False))
        html=replace_const(html,'S2',json.dumps(s2,ensure_ascii=False)); did.append('S1/S2')
    dr=load('sf_dreg.json')
    if dr is not None:
        dreg=build_dreg(dr['records'])
        html=replace_const(html,'DREG',json.dumps(dreg,ensure_ascii=False)); did.append('DREG')
    ps=load('sf_pstr.json')
    if ps is not None:
        pstr=build_pstr(ps['records'])
        tot=sum(sum(r[1:]) for r in pstr)
        if tot < 800:
            print(f'WARN PSTR: jen {tot} zaznamu (<800) -> PRESKAKUJI, nepřepisuji')
        else:
            html=replace_const(html,'PSTR',json.dumps(pstr,ensure_ascii=False).replace(' ',''))
            did.append('PSTR')
    st=load('sf_suit_total.json'); ss=load('sf_suit_seller.json')
    if st is not None and ss is not None:
        suit=build_suit(ss['records'], st['records'])
        tot=sum(r[2] for r in suit)
        if tot < 3000:
            print(f'WARN SUIT: total {tot} (<3000) -> PRESKAKUJI, nepřepisuji')
        else:
            html=replace_const(html,'SUIT',json.dumps(suit,ensure_ascii=False).replace(' ',''))
            did.append('SUIT')
    fctop_n=load('sf_fctop_normal.json'); fctop_d=load('sf_fctop_detail.json'); fctop_l=load('sf_fctop_lost.json'); fctop_x=load('sf_fctop_neither.json')
    if fctop_n is not None and fctop_d is not None and fctop_l is not None and fctop_x is not None:
        rows=build_top_reasons(fctop_n['records'],fctop_d['records'],fctop_l['records'],fctop_x['records'])
        tot=sum(r[2] for r in rows)
        if tot < 200:
            print('WARN FCTOP: ytd total',tot,'(<200) -> PRESKAKUJI')
        else:
            html=replace_const(html,'FCTOP',json.dumps(rows,ensure_ascii=False))
            did.append('FCTOP')
    catop_n=load('sf_catop_normal.json'); catop_d=load('sf_catop_detail.json'); catop_l=load('sf_catop_lost.json'); catop_x=load('sf_catop_neither.json')
    if catop_n is not None and catop_d is not None and catop_l is not None and catop_x is not None:
        rows=build_top_reasons(catop_n['records'],catop_d['records'],catop_l['records'],catop_x['records'])
        tot=sum(r[2] for r in rows)
        if tot < 200:
            print('WARN CATOP: ytd total',tot,'(<200) -> PRESKAKUJI')
        else:
            html=replace_const(html,'CATOP',json.dumps(rows,ensure_ascii=False))
            did.append('CATOP')
    c2=load('sf_car2.json')
    if c2 is not None:
        car2=build_car2(c2['records'])
        if sum(sum(r[1:]) for r in car2) < 200:
            print('WARN CAR2: <200 -> PRESKAKUJI')
        else:
            html=replace_const(html,'CAR2',json.dumps(car2,ensure_ascii=False).replace(' ',''))
            did.append('CAR2')
    open('index.html','w',encoding='utf-8').write(html)
    print("OK | updated:", did)
if __name__=='__main__': main()
