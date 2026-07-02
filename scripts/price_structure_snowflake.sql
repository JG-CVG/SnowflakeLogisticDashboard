-- Price structure — completed CA from seller (% representation) — SNOWFLAKE zdroj
-- Migrace z ☁ Salesforce (sf_pstr.json) na ❄ Snowflake. Ověřeno 1:1 proti skill referenci
-- (11/25 n=85 free=56, 12/25 n=120 free=74 ... stabilní měsíce přesně; recentní ±1-3 = čerstvost).
--
-- Logika (skill price-structure-ca-from-seller):
--   filtr: Status='CarAudit Done'  -> rekonstruováno z CaseHistory (NewValue='CarAudit Done')
--          + Car_inspection_by_Vendor__c vyplněné (not '', not '-')
--          + CarAudit_Amount__c číselné (0 = Free; prázdné/'-' se vylučuje)
--   měsíc = CA New CarAudit Date  -> Car_Audit__c.CreatedDate (ověřeno 1:1)
--   BEZ Instamotion / XK-AL filtru (shoda nastává bez nich). Data od 11/2025.
--   Cenová pásma identická s "Cost structure DE".
WITH done AS (
  SELECT "CaseId" cid
  FROM KEBOOLA_2999."in.c-kds-team-ex-salesforce-v2-333729667"."CaseHistory"
  WHERE "Field"='Status' AND "NewValue"='CarAudit Done' GROUP BY 1
),
ca AS (
  SELECT "Id" id,
         TRY_TO_DOUBLE(NULLIF("CarAudit_Amount__c",'')) amt,
         NULLIF(NULLIF("Car_inspection_by_Vendor__c",''),'-') insp,
         TRY_TO_TIMESTAMP("CreatedDate") cd
  FROM KEBOOLA_2999."in.c-kds-team-ex-salesforce-v2-333729667"."Car_Audit__c"
),
base AS (
  SELECT ca.cd ndt, ca.amt amt
  FROM KEBOOLA_2999."in.c-kds-team-ex-salesforce-v2-333729667"."Case" c
  JOIN ca   ON ca.id = c."CarAudit__c"
  JOIN done d ON d.cid = c."Id"
  WHERE c."IsDeleted"='false'
    AND ca.insp IS NOT NULL
    AND ca.amt  IS NOT NULL
    AND ca.cd  >= '2025-11-01'
),
agg AS (
  SELECT YEAR(ndt) y, MONTH(ndt) m,
    COUNT_IF(amt=0)                  free,
    COUNT_IF(amt>0   AND amt<=100)   p1_100,
    COUNT_IF(amt>100 AND amt<=120)   p100_120,
    COUNT_IF(amt>120 AND amt<=125)   p120_125,
    COUNT_IF(amt>125 AND amt<=145)   p125_145,
    COUNT_IF(amt>145)                p145plus
  FROM base GROUP BY 1,2
)
-- a) tabulka:
SELECT * FROM agg ORDER BY y,m;
-- b) hotové JS pole pro index.html (const PSTR):
-- SELECT '['||LISTAGG('["'||m||'/'||RIGHT(y::string,2)||'",'||free||','||p1_100||','||p100_120||','||p120_125||','||p125_145||','||p145plus||']',',')
--   WITHIN GROUP (ORDER BY y,m)||'];' FROM agg;
