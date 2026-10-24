-- SettlementLens GT-15: order with no processor transaction
-- Safe to rerun: removes only records with the dedicated SL-GT15 test IDs.

-- Remove this scenario's existing records before reseeding.
DELETE FROM SARVAGYA.PROCESSOR_TRANSACTIONS
WHERE PROCESSOR_TXN_ID = 'SL-GT15-PTX';

DELETE FROM SARVAGYA.PAYMENT_ATTEMPTS
WHERE ATTEMPT_ID = 'SL-GT15-ATT';

DELETE FROM SARVAGYA.ORDERS
WHERE ORDER_ID = 'SL-GT15-ORDER';

-- Create an INR 1,000 order.
INSERT INTO SARVAGYA.ORDERS
    (ORDER_ID, ORDER_AMOUNT, CURRENCY, CREATED_AT, MERCHANT_ID)
VALUES
    ('SL-GT15-ORDER', 1000.00, 'INR',
     TIMESTAMP '2026-10-20 10:00:00', 'SL-TEST-MERCHANT');

-- Create a payment attempt, but deliberately insert no processor transaction.
-- A payment attempt alone does not confirm that collection occurred.
INSERT INTO SARVAGYA.PAYMENT_ATTEMPTS
    (ATTEMPT_ID, ORDER_ID, MERCHANT_PAYMENT_REF,
     ATTEMPT_AMOUNT, ATTEMPT_STATUS, CREATED_AT)
VALUES
    ('SL-GT15-ATT', 'SL-GT15-ORDER', 'SL-GT15-REF',
     1000.00, 'SUCCESS',
     TIMESTAMP '2026-10-20 10:01:00');
