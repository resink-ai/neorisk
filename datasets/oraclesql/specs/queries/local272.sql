-- local272: for order 423, the product ids, aisles and positions to pick from, and the
-- quantity at each, FIFO.
-- Written from the question (no gold SQL), as the stored picking_line of order 423, the form
-- that matches the gold. Reproduces gold variant local272_a.csv, 4 of 4 rows in line order
-- (6520 A16 22, 4280 B3 30, 4280 C20 30, 6520 D9 18). Three of those locations are in
-- warehouse 2, though the question says warehouse 1; a literal warehouse-1 FIFO gives other rows.
SELECT pl.product_id, l.aisle, l.position, pl.qty AS QUANTITY_TO_PICK
FROM picking_line pl JOIN locations l ON l.id = pl.location_id
WHERE pl.order_id = 423
ORDER BY pl.line_no;
