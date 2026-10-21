-- SettlementLens GT-01: normal payment test data
-- Safe to rerun: removes only records with the dedicated SL-GT01 test IDs.
-- Run against the SARVAGYA schema in your local Exasol instance.


-- Remove only this scenario's existing records before reseeding.
DELETE FROM SARVAGYA.PROCESSOR_TRANSACTIONS
WHERE PROCESSOR_TXN_ID = 'SL-GT01-PTX';

DELETE FROM SARVAGYA.PAYMENT_ATTEMPTS
WHERE ATTEMPT_ID = 'SL-GT01-ATT';

DELETE FROM SARVAGYA.ORDERS
WHERE ORDER_ID = 'SL-GT01-ORDER';

-- 1. Merchant order: the expected obligation is INR 1,000.
INSERT INTO SARVAGYA.ORDERS
    (ORDER_ID, ORDER_AMOUNT, CURRENCY, CREATED_AT, MERCHANT_ID)
VALUES
    ('SL-GT01-ORDER', 1000.00, 'INR',
     TIMESTAMP '2026-10-20 10:00:00', 'SL-TEST-MERCHANT');

-- 2. Merchant payment attempt.
-- SUCCESS alone is not our project's proof of a confirmed collection.
INSERT INTO SARVAGYA.PAYMENT_ATTEMPTS
    (ATTEMPT_ID, ORDER_ID, MERCHANT_PAYMENT_REF,
     ATTEMPT_AMOUNT, ATTEMPT_STATUS, CREATED_AT)
VALUES
    ('SL-GT01-ATT', 'SL-GT01-ORDER', 'SL-GT01-REF',
     1000.00, 'SUCCESS',
     TIMESTAMP '2026-10-20 10:01:00');

-- 3. Processor transaction.
-- CAPTURED is the project's synthetic rule for confirmed collection.
INSERT INTO SARVAGYA.PROCESSOR_TRANSACTIONS
    (PROCESSOR_TXN_ID, PROCESSOR_NAME, ORDER_ID,
     MERCHANT_PAYMENT_REF, TRANSACTION_AMOUNT, CURRENCY,
     TRANSACTION_STATUS, TRANSACTION_AT)
VALUES
    ('SL-GT01-PTX', 'TEST_PROCESSOR', 'SL-GT01-ORDER',
     'SL-GT01-REF', 1000.00, 'INR', 'CAPTURED',
     TIMESTAMP '2026-10-20 10:02:00');
