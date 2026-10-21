CREATE TABLE IF NOT EXISTS orders (
    order_id VARCHAR(50) NOT NULL,
    order_amount DECIMAL(12,2) NOT NULL,
    currency CHAR(3) NOT NULL,
    created_at TIMESTAMP NOT NULL
);

ALTER TABLE orders ADD merchant_id VARCHAR(50) NOT NULL;