
-- GT-10: settlement component discrepancy.
-- Purpose: test non-zero fees, refunds, chargebacks, and a negative
-- signed adjustment against the processor-reported net amount.
-- Ground truth:
--   Expected net = 1000 - 20 - 50 - 10 + (-5) = INR 915
--   Reported net = INR 925
--   Difference   = expected net - reported net = INR -10
-- Safe to rerun: removes only GT-10 test records.

-- 1. Remove existing GT-10 links before deleting referenced records.
DELETE FROM SARVAGYA.SETTLEMENT_TRANSACTIONS
WHERE PROCESSOR_TXN_ID = 'SL-GT10-PTX';

-- 2. Remove this scenario's settlement batch.
DELETE FROM SARVAGYA.SETTLEMENTS
WHERE BATCH_ID = 'SL-GT10-BATCH';

-- 3. Remove the processor transaction.
DELETE FROM SARVAGYA.PROCESSOR_TRANSACTIONS
WHERE PROCESSOR_TXN_ID = 'SL-GT10-PTX';

-- 4. Remove the payment attempt.
DELETE FROM SARVAGYA.PAYMENT_ATTEMPTS
WHERE ATTEMPT_ID = 'SL-GT10-ATT';

-- 5. Remove the order.
DELETE FROM SARVAGYA.ORDERS
WHERE ORDER_ID = 'SL-GT10-ORDER';

-- 6. Create the merchant order.
INSERT INTO SARVAGYA.ORDERS
    (ORDER_ID, ORDER_AMOUNT, CURRENCY, CREATED_AT, MERCHANT_ID)
VALUES
    ('SL-GT10-ORDER', 1000.00, 'INR',
     TIMESTAMP '2026-10-20 10:00:00', 'SL-TEST-MERCHANT');

-- 7. Record the payment attempt.
INSERT INTO SARVAGYA.PAYMENT_ATTEMPTS
    (ATTEMPT_ID, ORDER_ID, MERCHANT_PAYMENT_REF,
     ATTEMPT_AMOUNT, ATTEMPT_STATUS, CREATED_AT)
VALUES
    ('SL-GT10-ATT', 'SL-GT10-ORDER', 'SL-GT10-REF',
     1000.00, 'SUCCESS',
     TIMESTAMP '2026-10-20 10:01:00');

-- 8. Record synthetic evidence of a confirmed collection.
-- SUCCESS alone is not proof of collection CAPTURED is the project's
-- synthetic confirmation rule.
INSERT INTO SARVAGYA.PROCESSOR_TRANSACTIONS
    (PROCESSOR_TXN_ID, PROCESSOR_NAME, ORDER_ID,
     MERCHANT_PAYMENT_REF, TRANSACTION_AMOUNT, CURRENCY,
     TRANSACTION_STATUS, TRANSACTION_AT)
VALUES
    ('SL-GT10-PTX', 'TEST_PROCESSOR', 'SL-GT10-ORDER',
     'SL-GT10-REF', 1000.00, 'INR', 'CAPTURED',
     TIMESTAMP '2026-10-20 10:02:00');

-- 9. Create a settlement batch with a deliberately incorrect reported net.
-- ADJUSTMENT_AMOUNT is signed: -5.00 decreases the expected net.
INSERT INTO SARVAGYA.SETTLEMENTS
    (BATCH_ID, GROSS_AMOUNT, FEE_AMOUNT, REFUND_AMOUNT,
     CHARGEBACK_AMOUNT, ADJUSTMENT_AMOUNT, REPORTED_NET_AMOUNT,
     CURRENCY, EXPECTED_SETTLEMENT_DATE, SETTLED_AT, SETTLEMENT_STATUS)
VALUES
    ('SL-GT10-BATCH', 1000.00, 20.00, 50.00,
     10.00, -5.00, 925.00, 'INR',
     DATE '2026-10-21',
     TIMESTAMP '2026-10-21 18:00:00', 'SETTLED');

-- 10. Link the processor transaction to the settlement batch.
INSERT INTO SARVAGYA.SETTLEMENT_TRANSACTIONS
    (BATCH_ID, PROCESSOR_TXN_ID)
VALUES
    ('SL-GT10-BATCH', 'SL-GT10-PTX');

INSERT INTO SARVAGYA.BANK_TRANSACTIONS
    (BANK_TXN_ID, BANK_REFERENCE, AMOUNT, CURRENCY,
     TRANSACTION_AT, DESCRIPTION, SOURCE_FILE)
VALUES
    ('SL-GT10-BANK', 'SL-GT10-BATCH', 925.00, 'INR',
     TIMESTAMP '2026-10-21 18:30:00',
     'Synthetic bank payout for GT10',
     'synthetic_gt10_bank.csv');
