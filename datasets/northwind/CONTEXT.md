# northwind

## What this is

Northwind, a food wholesaler: orders with a promised date, their lines, and shipments days later.

Version `v1`, kind `spider2`. The input is one ordered event log of 4,175 events; the output is the 15 source tables, rebuilt exactly, and the answers to 2 saved Spider 2.0 questions.

## Raw data

`northwind.sqlite`, 15 tables. A generated sample database; MIT licence (Microsoft).

Dates only, read as midnight UTC. float4 money (freight, prices, discount) is rebuilt from cents.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/northwind.md`](../../docs/research/spider2/northwind.md).

## How the log was made

Orders, order lines and shipments are events owned by the customer. Products, suppliers, employees, territories and the rest are entities. Money is held in cents and printed back as float4 at 9 digits; the two empty demographics tables are rebuilt empty.

`uv run dataset build northwind` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `categories_created` | entity | 8 | `category_id`, `ext_id`, `categoryname`, `description`, `picture` |
| `suppliers_created` | entity | 29 | `supplier_id`, `ext_id`, `companyname`, `contactname`, `contacttitle`, `address`, … (13 in all) |
| `products_created` | entity | 77 | `product_id`, `ext_id`, `productname`, `supplier_id`, `category_id`, `quantityperunit`, … (11 in all) |
| `shippers_created` | entity | 6 | `shipper_id`, `ext_id`, `companyname`, `phone` |
| `region_created` | entity | 4 | `region_id`, `ext_id`, `regiondescription` |
| `territories_created` | entity | 53 | `territory_id`, `ext_id`, `territorydescription`, `region_id` |
| `employees_created` | entity | 9 | `employee_id`, `ext_id`, `lastname`, `firstname`, `title`, `titleofcourtesy`, … (18 in all) |
| `employeeterritories_created` | entity | 49 | `et_id`, `ext_id`, `employee_id`, `territory_id` |
| `customers_created` | entity | 91 | `customer_id`, `ext_id`, `companyname`, `contactname`, `contacttitle`, `address`, … (12 in all) |
| `usstates_created` | entity | 51 | `state_id`, `ext_id`, `statename`, `stateabbr`, `stateregion` |
| `customergroupthreshold_created` | entity | 4 | `group_id`, `ext_id`, `rangebottom`, `rangetop` |
| `order_placed` | business | 830 | `customer_id`, `orderid`, `employee_id`, `required_lead_days`, `ship_via`, `freight`, … (12 in all) |
| `order_line_added` | business | 2,155 | `customer_id`, `orderid`, `product_id`, `unit_price`, `quantity`, `discount_pct` |
| `order_shipped` | business | 809 | `customer_id`, `orderid` |

## Times set by rule

Customers are created at their first order, and the 2 with none at the snapshot time N.

## Snapshot columns

Classified in PR 2. Until then every entity attribute travels in its creation event.

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `categories` | 8 | 4 | none |
| `customercustomerdemo` | 0 | 2 | none |
| `customerdemographics` | 0 | 2 | none |
| `customers` | 91 | 11 | none |
| `employees` | 9 | 18 | none |
| `employeeterritories` | 49 | 2 | none |
| `order_details` | 2,155 | 5 | none |
| `orders` | 830 | 14 | none |
| `products` | 77 | 10 | none |
| `region` | 4 | 2 | none |
| `shippers` | 6 | 3 | none |
| `suppliers` | 29 | 12 | none |
| `territories` | 53 | 3 | none |
| `usstates` | 51 | 4 | none |
| `customergroupthreshold` | 4 | 3 | none |

`expected/queries/` holds the answers of the saved questions (`local081`, `local085`), computed on the source. `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, and compares them and the answers exactly: rows as multisets, numbers by value, text byte for byte.

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build northwind             # → $NEORISK_DATA_ROOT/northwind/v1/ (default data/datasets/)
uv run dataset verify northwind            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
