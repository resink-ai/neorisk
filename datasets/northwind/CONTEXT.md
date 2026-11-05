# northwind

## What this is

Northwind, a food wholesaler: orders with a promised date, their lines, and shipments days later.

Version `v1`, kind `spider2`. The input is one ordered event log of 4,387 events; the output is the 15 source tables, rebuilt exactly, and the answers to 2 saved Spider 2.0 questions.

## Raw data

`northwind.sqlite`, 15 tables. A generated sample database; MIT licence (Microsoft).

Dates only, read as midnight UTC. float4 money (freight, prices, discount) is rebuilt from cents.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/northwind.md`](../../docs/research/spider2/northwind.md).

## How the log was made

Orders, order lines and shipments are events owned by the customer. Products, suppliers, employees, territories and the rest are entities. An employee is created by an `employee_hired` event at the hire date. Contacts, addresses and phones, an employee's title, notes and manager, and a product's list price and stock are values as of the extract, not as of creation, so they travel in one `<entity>_snapshot` event per row at N. Money is held in cents and printed back as float4 at 9 digits; the two empty demographics tables are rebuilt empty.

`uv run dataset build northwind` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `categories_created` | entity | 8 | `category_id`, `ext_id`, `categoryname`, `description`, `picture` |
| `suppliers_created` | entity | 29 | `supplier_id`, `ext_id`, `companyname` |
| `products_created` | entity | 77 | `product_id`, `ext_id`, `productname`, `supplier_id`, `category_id`, `quantityperunit` |
| `shippers_created` | entity | 6 | `shipper_id`, `ext_id`, `companyname` |
| `region_created` | entity | 4 | `region_id`, `ext_id`, `regiondescription` |
| `territories_created` | entity | 53 | `territory_id`, `ext_id`, `territorydescription`, `region_id` |
| `employee_hired` | entity | 9 | `employee_id`, `ext_id`, `lastname`, `firstname`, `titleofcourtesy`, `birthdate` |
| `employeeterritories_created` | entity | 49 | `et_id`, `ext_id`, `employee_id`, `territory_id` |
| `customers_created` | entity | 91 | `customer_id`, `ext_id`, `companyname` |
| `usstates_created` | entity | 51 | `state_id`, `ext_id`, `statename`, `stateabbr`, `stateregion` |
| `customergroupthreshold_created` | entity | 4 | `group_id`, `ext_id`, `rangebottom`, `rangetop` |
| `order_placed` | business | 830 | `customer_id`, `orderid`, `employee_id`, `required_lead_days`, `ship_via`, `freight`, `ship_name`, `ship_address`, `ship_city`, `ship_region`, `ship_postal_code`, `ship_country` |
| `order_line_added` | business | 2,155 | `customer_id`, `orderid`, `product_id`, `unit_price`, `quantity`, `discount_pct` |
| `order_shipped` | business | 809 | `customer_id`, `orderid` |
| `suppliers_snapshot` | business | 29 | `supplier_id`, `contactname`, `contacttitle`, `address`, `city`, `region`, `postalcode`, `country`, `phone`, `fax`, `homepage` |
| `products_snapshot` | business | 77 | `product_id`, `unitprice`, `unitsinstock`, `unitsonorder`, `reorderlevel`, `discontinued` |
| `shippers_snapshot` | business | 6 | `shipper_id`, `phone` |
| `employees_snapshot` | business | 9 | `employee_id`, `title`, `address`, `city`, `region`, `postalcode`, `country`, `homephone`, `extension`, `photo`, `notes`, `reportsto`, `photopath` |
| `customers_snapshot` | business | 91 | `customer_id`, `contactname`, `contacttitle`, `address`, `city`, `region`, `postalcode`, `country`, `phone`, `fax` |

## Times set by rule

Customers are created at their first order, and the 2 with none at the snapshot time N. Snapshots are at N = 1998-05-06 00:00:00, the last orderdate and the last shippeddate, so the latest event time in the log. Entities with no creation column (categories, suppliers, products, shippers, lookups, links) are created at T0 = 1996-07-04 00:00:00, the first order date.

## Snapshot columns

| Entity | Snapshot event | At (UTC) | Rows | Columns |
|---|---|---|---:|---|
| `suppliers` | `suppliers_snapshot` | 1998-05-06 00:00:00 | 29 | `contactname`, `contacttitle`, `address`, `city`, `region`, `postalcode`, `country`, `phone`, `fax`, `homepage` |
| `products` | `products_snapshot` | 1998-05-06 00:00:00 | 77 | `unitprice`, `unitsinstock`, `unitsonorder`, `reorderlevel`, `discontinued` |
| `shippers` | `shippers_snapshot` | 1998-05-06 00:00:00 | 6 | `phone` |
| `employees` | `employees_snapshot` | 1998-05-06 00:00:00 | 9 | `title`, `address`, `city`, `region`, `postalcode`, `country`, `homephone`, `extension`, `photo`, `notes`, `reportsto`, `photopath` |
| `customers` | `customers_snapshot` | 1998-05-06 00:00:00 | 91 | `contactname`, `contacttitle`, `address`, `city`, `region`, `postalcode`, `country`, `phone`, `fax` |

| Column | Verdict | Reason |
|---|---|---|
| `categories.ext_id` | creation | The source key (`categoryid`). |
| `categories.categoryname` | creation | A given name. |
| `categories.description` | creation | Part of the category's definition; the source shows no change. |
| `categories.picture` | creation | Part of the category's definition (the literal `\x` in every row). |
| `suppliers.ext_id` | creation | The source key (`supplierid`). |
| `suppliers.companyname` | creation | A given name. |
| `suppliers.contactname` | snapshot | The current contact person, who can change. |
| `suppliers.contacttitle` | snapshot | A title held by the contact. |
| `suppliers.address` | snapshot | An address, known only as of the extract. |
| `suppliers.city` | snapshot | An address. |
| `suppliers.region` | snapshot | An address. |
| `suppliers.postalcode` | snapshot | An address. |
| `suppliers.country` | snapshot | An address. |
| `suppliers.phone` | snapshot | A phone. |
| `suppliers.fax` | snapshot | A phone. |
| `suppliers.homepage` | snapshot | Contact data as of the extract; when in doubt, snapshot. |
| `products.ext_id` | creation | The source key (`productid`). |
| `products.productname` | creation | A given name. |
| `products.supplier_id` | creation | An immutable ref: the supplier the product was listed from. |
| `products.category_id` | creation | An immutable ref: the original category. |
| `products.quantityperunit` | creation | The pack size the product was listed with; the source shows no change. |
| `products.unitprice` | snapshot | The list price as of the extract; it changed during the window (§4 of the research), and the price paid is on `order_line_added`. Research kept it on the entity as "state at N". |
| `products.unitsinstock` | snapshot | Stock; no inventory ledger explains it. |
| `products.unitsonorder` | snapshot | Stock; no purchase orders explain it. |
| `products.reorderlevel` | snapshot | A stock setting as of the extract. |
| `products.discontinued` | snapshot | A current status flag; all 10 discontinued products were still ordered in 1998. |
| `shippers.ext_id` | creation | The source key (`shipperid`). |
| `shippers.companyname` | creation | A given name. |
| `shippers.phone` | snapshot | A phone. |
| `region.ext_id` | creation | The source key (`regionid`). |
| `region.regiondescription` | creation | A given name. |
| `territories.ext_id` | creation | The source key (`territoryid`, text). |
| `territories.territorydescription` | creation | A given name. |
| `territories.region_id` | creation | An immutable ref: the region the territory belongs to. |
| `employees.ext_id` | creation | The source key (`employeeid`). |
| `employees.created_at` (`hiredate`) | creation | The hire date; it is the event's time. |
| `employees.lastname` | creation | Given names. |
| `employees.firstname` | creation | Given names. |
| `employees.titleofcourtesy` | creation | Part of the given name (Mr., Ms., Mrs., Dr.). |
| `employees.birthdate` | creation | A birth date. |
| `employees.title` | snapshot | A title held; the notes record promotions after the hire. |
| `employees.address` | snapshot | An address. |
| `employees.city` | snapshot | An address. |
| `employees.region` | snapshot | An address. |
| `employees.postalcode` | snapshot | An address. |
| `employees.country` | snapshot | An address. |
| `employees.homephone` | snapshot | A phone. |
| `employees.extension` | snapshot | A phone. |
| `employees.photo` | snapshot | A profile picture that can be replaced; when in doubt, snapshot. |
| `employees.notes` | snapshot | A biography written as of the extract (it tells of later promotions). |
| `employees.reportsto` | snapshot | The current manager, a self-ref; the org chart can change. |
| `employees.photopath` | snapshot | Goes with the photo; when in doubt, snapshot. |
| `employeeterritories.ext_id` | creation | The link's two source ids. |
| `employeeterritories.employee_id` | creation | An immutable ref: one end of the link. |
| `employeeterritories.territory_id` | creation | An immutable ref: one end of the link. |
| `customers.ext_id` | creation | The source key (`customerid`). |
| `customers.created_at` | creation | The first order, or N for the 2 with none (a rule); it is the event's time. |
| `customers.companyname` | creation | A given name. |
| `customers.contactname` | snapshot | The current contact person. |
| `customers.contacttitle` | snapshot | A title held by the contact. |
| `customers.address` | snapshot | An address; the ship-to address on orders differs in 82 of 830 orders. |
| `customers.city` | snapshot | An address. |
| `customers.region` | snapshot | An address. |
| `customers.postalcode` | snapshot | An address. |
| `customers.country` | snapshot | An address. |
| `customers.phone` | snapshot | A phone. |
| `customers.fax` | snapshot | A phone. |
| `usstates.ext_id` | creation | The source key (`stateid`). |
| `usstates.statename` | creation | Static reference data. |
| `usstates.stateabbr` | creation | Static reference data. |
| `usstates.stateregion` | creation | Static reference data. |
| `customergroupthreshold.ext_id` | creation | The source key (`groupname`). |
| `customergroupthreshold.rangebottom` | creation | Static reference data (a spend band). |
| `customergroupthreshold.rangetop` | creation | Static reference data (a spend band). |

Only employees carry a domain name, `employee_hired`: the source dates the hire. Customers are created at their first order by rule, so they keep `customers_created`.

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
