-- Instamotion — Contract Accepted (IMCA) — SNOWFLAKE zdroj (migrace z ☁ Salesforce)
-- Aktivní IM objednávky Status='ord-contract-accepted' (čekají na platbu). Logika: skill im-contract-accepted.
-- Pole ověřena 1:1 (row 668185 shodný se SF snapshotem); queue je živá -> počet kolísá dle plateb.
WITH inv AS (
  SELECT "Order__c" oid, MAX(TRY_TO_TIMESTAMP("Invoice_Date__c")) idt
  FROM KEBOOLA_2999."in.c-kds-team-ex-salesforce-v2-333729667"."Invoice__c"
  WHERE "Order__c" IS NOT NULL AND "Order__c"<>'' GROUP BY 1
)
SELECT o."Name" num, a."Name" acc,
  LEFT(NULLIF(o."Contract_Accepted_Date__c",''),10) ca,
  TO_CHAR(iv.idt,'YYYY-MM-DD') inv,
  TRY_TO_DOUBLE(NULLIF(o."Expected_Payment_From_Customer__c",'')) ec,
  TRY_TO_DOUBLE(NULLIF(o."Received_Amount_from_Customer__c",'')) rc,
  TRY_TO_DOUBLE(NULLIF(o."Expected_Down_Payment_from_the_Customer__c",'')) edp,
  TRY_TO_DOUBLE(NULLIF(o."Received_Down_Payment_from_the_Customer__c",'')) rdp,
  LEFT(NULLIF(o."Customer_Contract_Paid_Date__c",''),10) ccp,
  TRY_TO_DOUBLE(NULLIF(o."Expected_Payment_from_Bank__c",'')) eb,
  TRY_TO_DOUBLE(NULLIF(o."Received_Amount_from_Bank__c",'')) rb,
  LEFT(NULLIF(o."Bank_Contract_Paid_Date__c",''),10) bcp
  -- typ (JS/build): edp&eb->DP+FIN ; eb&!edp->FIN ; ec->CASH ; else —
  -- missing payment = (rc IS NULL AND rdp IS NULL) ; storno dle pracovních dnů od ca (<=5 OK / 6-14 400€ / >=15 800€)
FROM KEBOOLA_2999."in.c-kds-team-ex-salesforce-v2-333729667"."Order" o
LEFT JOIN KEBOOLA_2999."in.c-kds-team-ex-salesforce-v2-333729667"."Account" a ON a."Id"=o."AccountId"
LEFT JOIN inv iv ON iv.oid=o."Id"
WHERE o."IsDeleted"='false' AND o."Status"='ord-contract-accepted' AND o."Instamotion_Customer__c"='true'
ORDER BY ca;
