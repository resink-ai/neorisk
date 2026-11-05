-- local273: the average pick percentage per product name, FIFO. Each product's order lines
-- (in order id, line id order) cover consecutive ranges of its demand, and its inventory lots
-- (earliest purchase first, then smaller quantity, then lot id) consecutive ranges of its
-- stock; a pick is the overlap of an order-line range with a lot range, and its percentage is
-- the overlap over the lot's quantity.
-- Written from the question (no gold SQL); no gold variant is reproduced. The only gold,
-- local273_a.csv, is degenerate: product ids as names, and 0.0 for both.
WITH ol AS (SELECT product_id, qty,
                   sum(qty) OVER (PARTITION BY product_id ORDER BY order_id, id
                                  ROWS UNBOUNDED PRECEDING) AS hi
            FROM orderlines),
inv AS (SELECT i.product_id, i.qty,
               sum(i.qty) OVER (PARTITION BY i.product_id ORDER BY pu.purchased, i.qty, i.id
                                ROWS UNBOUNDED PRECEDING) AS hi
        FROM inventory i JOIN purchases pu ON pu.id = i.purchase_id),
pick AS (SELECT inv.product_id, inv.qty AS lot_qty,
                min(ol.hi, inv.hi) - max(ol.hi - ol.qty, inv.hi - inv.qty) AS picked
         FROM ol JOIN inv ON inv.product_id = ol.product_id
         WHERE ol.hi - ol.qty < inv.hi AND inv.hi - inv.qty < ol.hi)
SELECT p.name AS PRODUCT_NAME, avg(pick.picked / pick.lot_qty) AS AVG_PICK_PERCENTAGE
FROM pick JOIN products p ON p.id = pick.product_id
GROUP BY p.name
ORDER BY p.name;
