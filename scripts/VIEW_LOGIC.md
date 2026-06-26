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

## TODO — pohledy k doplnění do build_sf_views.py (zatím statické)
FCTOP (1st Call Top-10 Phase 1), CATOP (CarAudit Top-10 Phase 2), CADR (CarAudit reason breakdown weekly),
CA from seller / Price structure, Doc & Registration, Seller Backlog, Preferred Funnel.
Postup: definici sem → funkci do build_sf_views.py → SOQL do scheduled tasku → ověřit proti známé hodnotě.
