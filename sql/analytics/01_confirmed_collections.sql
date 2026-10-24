
WITH collection_evidence AS (
    SELECT
        o.ORDER_ID,

        COUNT(p.PROCESSOR_TXN_ID) AS PROCESSOR_RECORD_COUNT,

        MAX(
            CASE
                WHEN p.TRANSACTION_STATUS = 'CAPTURED'
                 AND p.CURRENCY = o.CURRENCY
                THEN 1
                ELSE 0
            END
        ) AS HAS_COMPATIBLE_CAPTURE,

        MAX(
            CASE
                WHEN p.TRANSACTION_STATUS = 'CAPTURED'
                 AND p.CURRENCY <> o.CURRENCY
                THEN 1
                ELSE 0
            END
        ) AS HAS_CURRENCY_MISMATCH,

        SUM(
            CASE
                WHEN p.TRANSACTION_STATUS = 'CAPTURED'
                 AND p.CURRENCY = o.CURRENCY
                THEN p.TRANSACTION_AMOUNT
                ELSE 0
            END
        ) AS COMPATIBLE_CAPTURE_AMOUNT

    FROM SARVAGYA.ORDERS AS o

    LEFT JOIN SARVAGYA.PROCESSOR_TRANSACTIONS AS p
        ON p.ORDER_ID = o.ORDER_ID

    GROUP BY o.ORDER_ID
)

SELECT
    o.ORDER_ID,
    o.ORDER_AMOUNT AS EXPECTED_AMOUNT,
    o.CURRENCY AS ORDER_CURRENCY,

    CASE
        WHEN e.PROCESSOR_RECORD_COUNT = 0
            THEN 'NOT_AVAILABLE'

        WHEN e.HAS_COMPATIBLE_CAPTURE = 1
         AND e.HAS_CURRENCY_MISMATCH = 1
            THEN 'CAPTURED_WITH_CURRENCY_MISMATCH'

        WHEN e.HAS_COMPATIBLE_CAPTURE = 1
            THEN 'CAPTURED'

        WHEN e.HAS_CURRENCY_MISMATCH = 1
            THEN 'CURRENCY_MISMATCH'

        ELSE 'COLLECTION_NOT_CONFIRMED'
    END AS COLLECTION_STATUS,

    CASE
        WHEN e.HAS_COMPATIBLE_CAPTURE = 1
            THEN e.COMPATIBLE_CAPTURE_AMOUNT
        ELSE NULL
    END AS OBSERVED_COLLECTED_AMOUNT,

    CASE
        WHEN e.HAS_COMPATIBLE_CAPTURE = 1
            THEN e.COMPATIBLE_CAPTURE_AMOUNT - o.ORDER_AMOUNT
        ELSE NULL
    END AS DIFFERENCE_AMOUNT

FROM SARVAGYA.ORDERS AS o

JOIN collection_evidence AS e
    ON e.ORDER_ID = o.ORDER_ID

ORDER BY o.ORDER_ID;
