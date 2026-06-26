-- Preferred CA Funnel (weekly) — Snowflake reconstrukce (❄). Výstup = hotový 'const PF=[...];'.
-- Stage date z CaseHistory (Case_Status__c nespolehlivý). Preferred = Opportunity_Asset__c.Is_Preferred__c.
-- Kategorie: done > closed(1stCall/CA dle PREFERRED reject setu) > inprogress. Týden = ISO(Europe/Prague stage_dt).
-- rec/notrec/with_cp jen pro done (rec=Approved, notrec=Not recommended, cp=order má Car Purchase case). fcu=untrusty+cannot contacted.
WITH ch AS (
  SELECT "CaseId" cid,
    MAX(CASE WHEN "NewValue"='CarAudit Done' THEN TRY_TO_TIMESTAMP("CreatedDate") END) done_dt,
    MAX(CASE WHEN "NewValue"='CarAudit Closed' THEN TRY_TO_TIMESTAMP("CreatedDate") END) closed_dt,
    MAX_BY("NewValue", TRY_TO_TIMESTAMP("CreatedDate")) last_nv,
    MAX(TRY_TO_TIMESTAMP("CreatedDate")) last_ts
  FROM KEBOOLA_2999."in.c-kds-team-ex-salesforce-v2-333729667"."CaseHistory"
  WHERE "Field"='Status' GROUP BY "CaseId"),
cp AS (SELECT DISTINCT "Order__c" oid FROM KEBOOLA_2999."in.c-kds-team-ex-salesforce-v2-333729667"."Case" WHERE "RecordTypeId"='0126N000000kE2BQAU' AND "IsDeleted"='false' AND "Order__c" IS NOT NULL),
pref AS (SELECT DISTINCT "Order__c" oid FROM KEBOOLA_2999."in.c-kds-team-ex-salesforce-v2-333729667"."Opportunity_Asset__c" WHERE LOWER("Is_Preferred__c") IN ('true','1') AND "Order__c" IS NOT NULL),
base AS (
  SELECT ca."Id" caid, ca."Order__c" oid, LOWER(ca."Status__c") st, ca."Reason_Code__c" rc, ca."Detail_Reason_Code__c" dr,
         ch.done_dt, ch.closed_dt, ch.last_nv, ch.last_ts
  FROM KEBOOLA_2999."in.c-kds-team-ex-salesforce-v2-333729667"."Car_Audit__c" ca
  JOIN KEBOOLA_2999."in.c-kds-team-ex-salesforce-v2-333729667"."Case" c ON c."Id"=ca."Case__c" AND c."RecordTypeId"='0126N000000kDxBQAU' AND c."IsDeleted"='false'
  JOIN KEBOOLA_2999."in.c-kds-team-ex-salesforce-v2-333729667"."Order" o ON o."Id"=ca."Order__c" AND o."Instamotion_Customer__c"='false' AND (o."Customer_Country_Origin__c" IS NULL OR o."Customer_Country_Origin__c" NOT IN ('XK','AL'))
  JOIN pref ON pref.oid=ca."Order__c"
  LEFT JOIN ch ON ch.cid=ca."Case__c"),
cat AS (
  SELECT caid, oid, st, rc, dr,
    CASE WHEN done_dt IS NOT NULL THEN 'done'
         WHEN closed_dt IS NOT NULL THEN IFF(st IN ('reject new ca','reject car check','reject vin check','reject awaiting selection'),'closed_1stcall','closed_caraudit')
         WHEN last_nv IN ('Car Check','VIN Check','Awaiting Selection','Auditor Selection','Audit Order','Audit Result','CarAudit Preparation') THEN 'inprogress'
         ELSE NULL END category,
    CASE WHEN done_dt IS NOT NULL THEN done_dt WHEN closed_dt IS NOT NULL THEN closed_dt ELSE last_ts END stage_dt
  FROM base),
ww AS (
  SELECT YEAROFWEEKISO(CONVERT_TIMEZONE('UTC','Europe/Prague',stage_dt)) yr, WEEKISO(CONVERT_TIMEZONE('UTC','Europe/Prague',stage_dt)) wn,
         cat.category, LOWER(cat.rc)='approved' is_rec, LOWER(cat.rc)='not recommended' is_notrec,
         IFF(cp.oid IS NOT NULL,TRUE,FALSE) has_cp, cat.rc, cat.dr
  FROM cat LEFT JOIN cp ON cp.oid=cat.oid
  WHERE cat.category IS NOT NULL AND cat.stage_dt IS NOT NULL),
agg AS (
  SELECT yr, wn, COUNT(*) total,
    SUM(IFF(category='closed_1stcall',1,0)) c1, SUM(IFF(category='closed_caraudit',1,0)) cc,
    SUM(IFF(category='inprogress',1,0)) inp, SUM(IFF(category='done',1,0)) done,
    SUM(IFF(category='done' AND is_rec,1,0)) rec, SUM(IFF(category='done' AND is_notrec,1,0)) notrec,
    SUM(IFF(category='done' AND is_rec AND has_cp,1,0)) wcp,
    SUM(IFF(category='closed_1stcall' AND rc='Fault at seller side - Untrusty seller' AND dr='Cannot be contacted',1,0)) fcu
  FROM ww GROUP BY yr,wn)
SELECT 'const PF=['||LISTAGG('["W'||LPAD(wn::string,2,'0')||'/'||RIGHT(yr::string,2)||'",'||total||','||c1||','||cc||','||inp||','||done||','||rec||','||notrec||','||wcp||','||fcu||']', ',') WITHIN GROUP (ORDER BY yr,wn)||'];' js
FROM agg WHERE yr*100+wn >= 202531;
