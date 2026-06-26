# VIEW_LOGIC — zdroj pravdy pro logiku pohledů (SnowflakeLogisticDashboard)

Tento soubor je **autoritativní, verzovaná** dokumentace business-logiky pohledů na
dashboardu https://jg-cvg.github.io/SnowflakeLogisticDashboard/.
Je úmyslně v repu (ne ve skill cache, která je v session jen pro čtení), takže je
vždy aktuální vůči živému dashboardu a dá se zapisovat + pushovat.

Pravidlo: **jakákoli změna logiky pohledu → nejdřív sem, pak do `build_sf_views.py` / `index.html`.**
Per-pohledové skilly (Settings → Capabilities) mají jen odkazovat sem.

Zdroje dat:
- ❄ Snowflake: `KEBOOLA_2999."in.c-kds-team-ex-salesforce-v2-333729667"` + `AI.CERTIFIED.*` (konektor `sql_exec_tool`)
- ☁ Salesforce: konektor `soqlQuery` (deterministicky přes `build_sf_views.py`)
Refresh: scheduled task `snowflake-dashboard-refresh` (3×/den, jediný zapisovatel, pull-before-push).

---

## Carvago Purchasing — Active Purchases  (container `active-purchases`, `const ROWS`)
**Zdroj:** ☁ Salesforce (CP status-date pole NEJSOU ve Snowflake extraktu).
**Co zobrazuje:** aktivní Car Purchase případy (CP-XXXXXX) = matice fáze (Status) × stáří.

### Přesná definice (= filtry CP reportu „Claude_Purchasing (CP)_data", ověřeno 26.06.2026)
Bez vyřazení „mrtvých" objednávek — report žádný Order-Status filtr nemá:
1. Case Record Type = Car Purchase (`RecordTypeId='0126N000000kE2BQAU'`)
2. Status ∈ {New, Dealer Contacted, Contract Preparation, Awaiting Approval, Contract Signature, Payment Processing} (= ne Done/Closed)
3. CreatedDate (Date/Time Opened) ≥ 2024-01-01 a < 2027-01-01  ← odřízne staré „New" z 2021 (zdroj přehnaných ~525)
4. Is_TEST_Case__c = false
5. Order__r.Instamotion_Customer__c = false  (jen Carvago)
6. Order__r.Customer_Country_Origin__c neobsahuje XK ani AL (`NOT LIKE '%XK%' AND NOT LIKE '%AL%'`)
7. Account.Name ∉ {@carvago, Zářecký, Kohout, Carvago}
8. Contact.Name ∉ {Zářecký, Zarecky, Kohout, Carvago, carvago}
9. CaseNumber ≠ 00034562

Ověřený stav 26.06.2026: **90 aktivních** (živě ±1). Po statusech: New 8 · Dealer Contacted 12 ·
Contract Preparation 6 · Awaiting Approval 0 · Contract Signature 0 · Payment Processing 64.

### Stáří (age)
Pracovní dny (CZ svátky, jako `np.busday_count`) **od data vstupu do AKTUÁLNÍ fáze** do dnes.
Mapování status → datové pole:
| Status | pole |
|---|---|
| New | CP_New_Date__c |
| Dealer Contacted | CP_Dealer_Contacted_Date__c |
| Contract Preparation | CP_Contract_Preparation_Date__c |
| Awaiting Approval | CP_Awaiting_Approval_Date__c |
| Contract Signature | CP_Contract_Signature_Date__c |
| Payment Processing | CP_Payment_Processing_Date__c |
Případy bez data aktuální fáze se PŘESKAKUJÍ. Buckety: b02 (<2), b23 (<3), b35 (<5), b510 (<10), b10 (10+).

### Implementace
- `build_active_purchases(records)` v `scripts/build_sf_views.py` (pure-Python busday + `CZ_HOL` 2025–2027, bez numpy).
- Vstup JSON `sf_cp_active.json`; skript `replace_const(html,'ROWS', …)`. Gated na existenci souboru (chybí → ROWS nesahá).

### SOQL (sf_cp_active.json)
```
SELECT Status, CP_New_Date__c, CP_Dealer_Contacted_Date__c, CP_Contract_Preparation_Date__c,
       CP_Awaiting_Approval_Date__c, CP_Contract_Signature_Date__c, CP_Payment_Processing_Date__c
FROM Case
WHERE RecordTypeId='0126N000000kE2BQAU'
  AND Status IN ('New','Dealer Contacted','Contract Preparation','Awaiting Approval','Contract Signature','Payment Processing')
  AND CreatedDate >= 2024-01-01T00:00:00Z AND CreatedDate < 2027-01-01T00:00:00Z
  AND Is_TEST_Case__c=false
  AND Order__r.Instamotion_Customer__c=false
  AND (NOT Order__r.Customer_Country_Origin__c LIKE '%XK%')
  AND (NOT Order__r.Customer_Country_Origin__c LIKE '%AL%')
  AND Account.Name NOT IN ('@carvago','Zářecký','Kohout','Carvago')
  AND Contact.Name NOT IN ('Zářecký','Zarecky','Kohout','Carvago','carvago')
  AND CaseNumber != '00034562'
```

---

---

## Seller Payment Backlog — aging (Car Purchase)  (container `seller-backlog`, `const S1` + `const S2`)
**Zdroj:** ☁ Salesforce. **Co zobrazuje:** kde leží peníze — zákazník zaplatil, ale Carvago ještě neposlalo prodejci.
Dvě sekce, obě seskupené po **Invoicing Company** (Order.Invoicing_Company.Name), aging ≤2 / 3-4 / >4 prac. dny.

### Populace (= stejné filtry reportu jako Active Purchases)
Car Purchase, Status ∈ 6 aktivních (ne Done/Closed), CreatedDate 2024-01-01..2027-01-01, Is_TEST=false,
Order.Instamotion=false, Customer Country Origin neobsahuje XK/AL, Account/Contact ∉ interní, CaseNumber≠00034562.

### Dvě sekce
- **S1 „Máme peníze od zákazníka" (5 polí, bez EUR):** Status ≠ Payment Processing **A** `Order.Is_Contract_Paid__c` je vyplněné (≠ null; je to DATUM, ne boolean!).
- **S2 „CVG nezaplatilo vendorovi" (7 polí, s EUR):** Status = Payment Processing.

### EUR částka (jen S2)
`EUR = Order.Car_List_Price__c ÷ kurz(Order.Car_List_Price_Currency__c)`, kde kurzy = SF `CurrencyType.ConversionRate`
(korporátní měna = EUR, kurz=1; tj. dělením z měny prodejce na EUR). Ověřeno: AT = €39 316 sedí na euro.
`eur_over` = EUR jen za case ve věku >4 dny.

### Aging
Pracovní dny (CZ svátky) od data vstupu do **aktuální fáze** (mapování status→CP date pole jako Active Purchases) do dnes.
Buckety: ≤2 / 3-4 / >4 dny. Případy bez data fáze → bucket >4.

### Formát const (index.html)
- `S1=[[invoicingCompany, total, ≤2, 3-4, >4], …]`
- `S2=[[invoicingCompany, total, ≤2, 3-4, >4, eurTotal, eurOver], …]`
Ověřený stav 26.06.2026: S1 = 8 case (CZ 4 / DE 3 / STH 1) · S2 = 67 case, €1 559 759 k zaplacení (€286 355 po termínu).

### Implementace
`build_seller_backlog(records, rates)` v `scripts/build_sf_views.py`. Vstupy: `sf_seller.json` (SOQL níže) + `sf_rates.json` (CurrencyType).

### SOQL
sf_seller.json:
```
SELECT Id, Status, Order__r.Invoicing_Company__r.Name, Order__r.Car_List_Price__c, Order__r.Car_List_Price_Currency__c,
       Order__r.Is_Contract_Paid__c, CP_New_Date__c, CP_Dealer_Contacted_Date__c, CP_Contract_Preparation_Date__c,
       CP_Awaiting_Approval_Date__c, CP_Contract_Signature_Date__c, CP_Payment_Processing_Date__c
FROM Case
WHERE RecordTypeId='0126N000000kE2BQAU'
  AND Status IN ('New','Dealer Contacted','Contract Preparation','Awaiting Approval','Contract Signature','Payment Processing')
  AND CreatedDate >= 2024-01-01T00:00:00Z AND CreatedDate < 2027-01-01T00:00:00Z
  AND Is_TEST_Case__c=false AND Order__r.Instamotion_Customer__c=false
  AND (NOT Order__r.Customer_Country_Origin__c LIKE '%XK%') AND (NOT Order__r.Customer_Country_Origin__c LIKE '%AL%')
  AND Account.Name NOT IN ('@carvago','Zářecký','Kohout','Carvago')
  AND Contact.Name NOT IN ('Zářecký','Zarecky','Kohout','Carvago','carvago')
  AND CaseNumber != '00034562'
```
sf_rates.json: `SELECT IsoCode, ConversionRate FROM CurrencyType WHERE IsActive=true`

---

## Instamotion — Active Document & Registration Cases  (canvas `dreg`, `const DREG`)
**Zdroj:** ☁ Salesforce, objekt **Documents_and_Registration__c** (ne Case). **Co zobrazuje:** aktivní registrační případy Instamotion dle Kroschke statusu × stáří.
- **Populace:** `Order__r.Instamotion_Customer__c=true` AND `Status__c` NOT IN (car-registration-done, car-registration-closed) AND Kroschke status nezačíná „0/0" (vyřazuje *storniert/gelöscht* a *Klärfall beendet* = neaktivní).
- **Formát:** `DREG=[[kroschke_idx, "YYYY-MM-DD"], …]`, kde datum = `Coordination_with_Vendor_Date__c`.
- **kroschke_idx** (mapování `Kroschke_Registration_Status__c`): 2/6 wartet auf Zulassungsunterlagen→0 · 3/6 Bearbeitung durch Kroschke→1 · 4/6 Weitergeleitet an Zulassungsdienst→2 · 5/6 Eingegangen beim Zulassungsdienst→3 · ostatní (null, Request Sent, 1/6…)→4 „Bez statusu".
- **Aging** (počítá JS na dashboardu): pracovní dny od Coordination with Vendor do dnes, buckety 0–5 / 6–10 / 11–15 / 16–20 / >20 WD.
- Ověřeno 26.06.2026: 56 aktivních (2/6=31, 3/6=2, 4/6=13, 5/6=7, Bez statusu=3).
- **Implementace:** `build_dreg(records)` v build_sf_views.py, vstup `sf_dreg.json`.
- **SOQL:** `SELECT Kroschke_Registration_Status__c, Coordination_with_Vendor_Date__c, Status__c FROM Documents_and_Registration__c WHERE Order__r.Instamotion_Customer__c=true AND Status__c NOT IN ('car-registration-done','car-registration-closed')`

## PSTR — Price structure (completed CA from seller, % po měsících)  (canvas `pstruct`, `const PSTR`)  ✅ IMPLEMENTOVÁNO 26.06.2026
**Zdroj:** ☁ Salesforce. Skill: `price-structure-ca-from-seller`. **Co zobrazuje:** 100% stacked bar po měsících = % zastoupení cenových pásem (CarAudit Amount) u dokončených CA od prodejce; `n` nad sloupcem; nejnovější měsíc vlevo; od 11/25.

### Filtr (ověřeno 1:1 proti referenci — 11/25: [56,13,6,9,1,0], n=85, Free 65.9 %)
1. `Status` = **`CarAudit Done`** (standardní Case status).
2. `CarAudit__r.Car_inspection_by_Vendor__c` **vyplněné** (≠ null, ≠ `-`).
3. `CarAudit__r.CarAudit_Amount__c` **číselné** (0 = Free OK; null/blank se VYLUČUJE i z `n`).
4. Měsíc = `CA_New_CarAudit_Date__c`, label `m/yy`.
- **ŽÁDNÝ** Instamotion / XK-AL filtr (přidání by čísla rozhodilo — ověřeno).

### ⚠️ Důležité zjištění (oprava roadmap-poznámky níže)
Standardní `Status='CarAudit Done'` reprodukuje referenci **přesně** a staré měsíce (11/25, 12/25)
po 7+ měsících **nedegradují** → `'CarAudit Done'` je u CarAudit case terminální.
**NENÍ tedy nutná rekonstrukce z CaseHistory** (na rozdíl od původního TODO předpokladu).
Pozn.: `Case_Status__c` (custom) ≈ 0 — nepoužívat; standardní `Status` ano.

### Cenová pásma (identická s Cost structure DE)
free `==0` · p1_100 `0<a≤100` · p100_120 `100<a≤120` · p120_125 `120<a≤125` · p125_145 `125<a≤145` · p145plus `a>145`.
`const PSTR=[label,free,p1_100,p100_120,p120_125,p125_145,p145plus]` (oldest first; chart reverses).

### Implementace
`build_pstr(records)` v `scripts/build_sf_views.py` (gated na `sf_pstr.json`; guard: total <800 → přeskočí, nepřepíše).

### SOQL (sf_pstr.json)
```
SELECT CA_New_CarAudit_Date__c, CarAudit__r.CarAudit_Amount__c
FROM Case
WHERE Status='CarAudit Done'
  AND CA_New_CarAudit_Date__c >= 2025-11-01T00:00:00Z
  AND CarAudit__r.Car_inspection_by_Vendor__c != null
  AND CarAudit__r.Car_inspection_by_Vendor__c != '-'
```
Ověřený stav (live SF 26.06.2026): 11/25 n=85 · 12/25 120 · 1/26 162 · 2/26 200 · 3/26 234 · 4/26 241 · 5/26 258 · 6/26 277 (roste).

---

## TODO — pohledy k doplnění do build_sf_views.py (zatím statické) — ROADMAP

Zmapovaná pole (ověřeno 26.06.2026, getObjectSchema):
- **Car_Audit__c**: `Car_inspection_by_Vendor__c` (picklist: "Suitable car" / "Vendor will perform" / "Vendor will not perform"), `CarAudit_Amount__c` (double, EUR bez VAT), `Reason_Code__c` (picklist – Phase reason), `Case_Status__c` (= AKTUÁLNÍ stav, NE milník!), `Status__c` (APPROVED/REJECT ...). Vazba na Case: `Case.CarAudit__r.*`.
- ⚠️ **POZOR:** `Case_Status__c='CarAudit Done'` vrací ~0 (případ se přes Done posune dál). „CarAudit Done" se MUSÍ rekonstruovat z **CaseHistory** (změna Status → 'CarAudit Done'), stejně jako u skillu `snowflake-caraudit-cost-structure`.
- CA New date = `Case.CA_New_CarAudit_Date__c`. Reason long-text na Case = `CA_Reason_Code__c` (length 1300 → NELZE GROUP BY).

### ~~PSTR — Price structure~~ ✅ HOTOVO 26.06.2026 → viz sekce „PSTR" výše (implementováno v build_sf_views.py).
- Oprava původního předpokladu: NENÍ potřeba CaseHistory — standardní `Status='CarAudit Done'` stačí (ověřeno 1:1: 11/25 [56,13,6,9,1,0] n=85). Bez Instamotion/XK-AL filtru.

### SUIT — CA from seller, evaluated as suitable (měsíčně) — ☁ SF, od 12/25
- `const SUIT=[month, from_seller, total]`. total = CA NE 'REJECT New CA' (Phase 1 první reject) dle CA New date; from_seller = `Car_inspection_by_Vendor__c` vyplněné. Ověř proti SUIT v index.html (6/26: 834/1319). Vysoký objem → stránkování.

### FCTOP / CATOP — Top-10 reason (Phase 1 / Phase 2) — 3 období (měsíc/YTD/loni)
- Skilly: `fc-closed-top-reasons` (Phase 1), `ca-closed-top-reasons` (Phase 2). Reason = `CA_Reason_Code__c` (Case) NEBO `CarAudit__r.Reason_Code__c`. Phase 1 rejecty {REJECT New CA, Data Validation, Car Check, VIN Check}; Phase 2 = ostatní rejecty. Long-text → NELZE GROUP BY: stáhni řádky a agreguj v Pythonu; >2000/období → stránkovat (ORDER BY + Id cursor).
- `const FCTOP/CATOP=[[reason, m_cur, ytd, prev], ...]` top ~12-15.

### CADR — CarAudit Closed reason breakdown (weekly) — Phase 2
- `const CADR=[[week, count, ?], ...]` (ověř formát v index.html ~ř.851). Phase 2 closed po týdnech dle CA New date.

### PF — Preferred CA Funnel (weekly) — ❄ Snowflake (Car_Audit__c + History + Opportunity_Asset + Case Car Purchase)
- Skilly: `preferred-ca-funnel-table`, `preferred-ca-weekly`, `preferred-ca-cp-weekly`. `const PF=[label, total, 1stCall_closed, CA_closed, inprogress, done, recommended, not_recommended, with_cp]`. Funnel buckety dle CA New date; recommended/CP dle CA Done date.

Postup pro každý: definice sem → funkce do build_sf_views.py (gated na sf_*.json) → SOQL do scheduled tasku `snowflake-dashboard-refresh` → ověřit proti referenci/known value → node --check → commit/push.
