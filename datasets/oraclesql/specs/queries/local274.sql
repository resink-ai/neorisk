-- local274: the products picked for order 421 and the average units per pick, FIFO.
-- Written from the question (no gold SQL), from the stored picking_line of order 421.
-- Reproduces gold variant local274_a.csv, 2 of 2 rows: Hoppy Crude Oil 36.67 (3 picks, 110
-- units), Der Helle Kumpel 23.33 (6 picks, 140 units); local274_b.csv has the same numbers.
SELECT p.name AS NAME, avg(pl.qty) AS AVG_QTY
FROM picking_line pl JOIN products p ON p.id = pl.product_id
WHERE pl.order_id = 421
GROUP BY pl.product_id, p.name
ORDER BY pl.product_id;
