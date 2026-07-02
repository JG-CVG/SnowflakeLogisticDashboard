-- Instamotion — Active Document & Registration Cases (DREG) — SNOWFLAKE zdroj (migrace z ☁ Salesforce)
-- Objekt Documents_and_Registration__c NEMA Done/Closed date pole -> "aktivní" se urcuje pres Status__c
-- (mimo car-registration-done / car-registration-closed). Instamotion pres join Order.Instamotion_Customer__c.
-- Vystup: [kroschke_idx, coordination_date] ; stack dle Kroschke, stari = prac. dny od Coordination with Vendor.
WITH r AS (
  SELECT CASE d."Kroschke_Registration_Status__c"
           WHEN '2/6 wartet auf Zulassungsunterlagen'   THEN 0
           WHEN '3/6 Bearbeitung durch Kroschke'         THEN 1
           WHEN '4/6 Weitergeleitet an Zulassungsdienst' THEN 2
           WHEN '5/6 Eingegangen beim Zulassungsdienst'  THEN 3
           ELSE 4 END idx,                               -- else -> "Bez statusu"
         LEFT(d."Coordination_with_Vendor_Date__c",10) dt
  FROM KEBOOLA_2999."in.c-kds-team-ex-salesforce-v2-333729667"."Documents_and_Registration__c" d
  JOIN KEBOOLA_2999."in.c-kds-team-ex-salesforce-v2-333729667"."Order" o ON o."Id"=d."Order__c"
  WHERE d."IsDeleted"='false' AND o."Instamotion_Customer__c"='true'
    AND d."Status__c" NOT IN ('car-registration-done','car-registration-closed')  -- aktivni (nahrada za Done/Closed date)
    AND NOT COALESCE(d."Kroschke_Registration_Status__c",'') LIKE '0/0%'           -- storniert / geloscht = neaktivni
    AND NULLIF(d."Coordination_with_Vendor_Date__c",'') IS NOT NULL
)
SELECT idx, dt FROM r ORDER BY dt, idx;
