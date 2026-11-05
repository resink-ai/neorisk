# adventureworks

## What this is

AdventureWorks, a bicycle maker: sales orders with lines and shipments, salesperson quotas, currency rates and product reviews.

Version `v1`, kind `spider2`. The input is one ordered event log of 200,832 events; the output is the 13 source tables, rebuilt exactly, and the answers to 1 saved Spider 2.0 questions.

## Raw data

`AdventureWorks.sqlite`, 13 tables. A generated sample database; MIT licence (Microsoft).

Times are midnights, read as UTC. Order money is rebuilt from 1e-4 integers.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/adventureworks.md`](../../docs/research/spider2/adventureworks.md).

## How the log was made

Orders, lines and shipments are events owned by the sales order; quotas (by salesperson), currency rates (by currency) and product reviews are events too. Products, territories and salespersons are entities. Money is held as integers of 1e-4; number-or-empty columns are carried as text. Load stamps, prices, stock policy, a salesperson's territory and pay, and the stale year-to-date counters are snapshot columns: they ride on one `<entity>_snapshot` event per entity row at N.

`uv run dataset build adventureworks` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `product_categories_created` | entity | 4 | `product_category_id`, `ext_id`, `name`, `rowguid` |
| `product_subcategories_created` | entity | 37 | `product_subcategory_id`, `ext_id`, `product_category_id`, `name`, `rowguid` |
| `products_created` | entity | 504 | `product_id`, `ext_id`, `name`, `productnumber`, `finishedgoodsflag`, `color`, `size`, `sizeunitmeasurecode`, `weightunitmeasurecode`, `weight`, `productline`, `class`, `style`, `productsubcategoryid`, `productmodelid`, `sellstartdate`, `rowguid` |
| `product_descriptions_created` | entity | 762 | `product_description_id`, `ext_id`, `description`, `rowguid`, `productmodelid`, `cultureid` |
| `territories_created` | entity | 10 | `territory_id`, `ext_id`, `name`, `countryregioncode`, `group`, `rowguid` |
| `salespersons_created` | entity | 17 | `salesperson_id`, `ext_id`, `rowguid` |
| `country_currencies_created` | entity | 109 | `country_currency_id`, `ext_id`, `countryregioncode`, `currencycode` |
| `product_categories_snapshot` | business | 4 | `product_category_id`, `modifieddate` |
| `product_subcategories_snapshot` | business | 37 | `product_subcategory_id`, `modifieddate` |
| `products_snapshot` | business | 504 | `product_id`, `makeflag`, `safetystocklevel`, `reorderpoint`, `standardcost`, `listprice`, `daystomanufacture`, `sellenddate`, `discontinueddate`, `modifieddate` |
| `product_descriptions_snapshot` | business | 762 | `product_description_id`, `modifieddate`, `link_modifieddate` |
| `territories_snapshot` | business | 10 | `territory_id`, `salesytd`, `saleslastyear`, `costytd`, `costlastyear`, `modifieddate` |
| `salespersons_snapshot` | business | 17 | `salesperson_id`, `territoryid`, `salesquota`, `bonus`, `commissionpct`, `salesytd`, `saleslastyear`, `modifieddate` |
| `country_currencies_snapshot` | business | 109 | `country_currency_id`, `modifieddate` |
| `order_placed` | business | 31,465 | `salesorderid`, `revisionnumber`, `duedate`, `onlineorderflag`, `purchaseordernumber`, `accountnumber`, `customerid`, `salespersonid`, `territory_id`, `billtoaddressid`, `shiptoaddressid`, `shipmethodid`, `creditcardid`, `creditcardapprovalcode`, `currencyrateid`, `taxamt_e4`, `freight_e4`, `comment`, `rowguid` |
| `order_line_added` | business | 121,317 | `salesorderid`, `salesorderdetailid`, `carriertrackingnumber`, `orderqty`, `product_id`, `specialofferid`, `unitprice_e4`, `discount_pct`, `rowguid` |
| `order_shipped` | business | 31,465 | `salesorderid` |
| `currency_rate_published` | business | 13,532 | `tocurrencycode`, `currencyrateid`, `fromcurrencycode`, `averagerate`, `endofdayrate`, `modifieddate` |
| `quota_set` | business | 163 | `salesperson_id`, `quotadate`, `salesquota`, `rowguid` |
| `product_reviewed` | business | 4 | `product_id`, `productreviewid`, `reviewername`, `emailaddress`, `rating`, `comments` |

## Times set by rule

- Every business event carries a source date.
- Entities have no creation date in the source, so each one is created at the dataset's first event time, 2011-04-16 00:00:00.
- N = 2014-07-07 00:00:00, the research's snapshot time: the last shipdate and the last header modifieddate, and the latest event time in the log. Every entity snapshot is at N.

## Snapshot columns

| Entity | Snapshot event | At (UTC) | Rows | Columns |
|---|---|---|---:|---|
| `product_categories` | `product_categories_snapshot` | 2014-07-07 00:00:00 | 4 | `modifieddate` |
| `product_subcategories` | `product_subcategories_snapshot` | 2014-07-07 00:00:00 | 37 | `modifieddate` |
| `products` | `products_snapshot` | 2014-07-07 00:00:00 | 504 | `makeflag`, `safetystocklevel`, `reorderpoint`, `standardcost`, `listprice`, `daystomanufacture`, `sellenddate`, `discontinueddate`, `modifieddate` |
| `product_descriptions` | `product_descriptions_snapshot` | 2014-07-07 00:00:00 | 762 | `modifieddate`, `link_modifieddate` |
| `territories` | `territories_snapshot` | 2014-07-07 00:00:00 | 10 | `salesytd`, `saleslastyear`, `costytd`, `costlastyear`, `modifieddate` |
| `salespersons` | `salespersons_snapshot` | 2014-07-07 00:00:00 | 17 | `territoryid`, `salesquota`, `bonus`, `commissionpct`, `salesytd`, `saleslastyear`, `modifieddate` |
| `country_currencies` | `country_currencies_snapshot` | 2014-07-07 00:00:00 | 109 | `modifieddate` |

| Column | Verdict | Reason |
|---|---|---|
| `ext_id` (every entity) | creation | The source key (`'<country>/<currency>'` for country currencies). |
| `rowguid` (every entity) | creation | An identity stamp, fixed with the row. |
| `modifieddate` (every entity), `productmodelproductdescriptionculture.modifieddate` (`link_modifieddate`) | snapshot | Modification stamps: load times up to 2014-02-08, after the entity's creation time. |
| `productcategory.name`, `productsubcategory.name`, `product.name` | creation | Given names. |
| `productsubcategory.productcategoryid` | creation | An immutable ref. |
| `product.productnumber` | creation | A given code. |
| `product.makeflag` | snapshot | Make or buy is a sourcing decision that can change (when in doubt, snapshot). |
| `product.finishedgoodsflag` | creation | The type the row was created with: a salable good or a component. |
| `product.color`, `size`, `sizeunitmeasurecode`, `weightunitmeasurecode`, `weight` | creation | The physical variant the product row names (e.g. "Mountain-100 Black, 38"). |
| `product.safetystocklevel`, `reorderpoint` | snapshot | Stock policy, as of the extract. |
| `product.standardcost`, `listprice` | snapshot | Prices change after creation. |
| `product.daystomanufacture` | snapshot | A production figure that can change (when in doubt, snapshot). |
| `product.productline`, `class`, `style` | creation | The original category the row was created with. |
| `product.productsubcategoryid`, `productmodelid` | creation | Immutable refs (carried as text: id or `''`). |
| `product.sellstartdate` | creation | A start date, fixed when the product is listed. |
| `product.sellenddate`, `discontinueddate` | snapshot | Only known once the product leaves sale (all `''` here). |
| `productdescription.description` | creation | The row's content; another text would be another row. |
| `productmodelproductdescriptionculture.productmodelid`, `cultureid` | creation | Immutable refs of the description's one link row. |
| `salesterritory.name`, `countryregioncode`, `group` | creation | Given name and fixed geography. |
| `salesterritory.salesytd`, `saleslastyear`, `costytd`, `costlastyear` | snapshot | Stale counters as of the extract, not derivable from the orders (research §3.4). |
| `salesperson.territoryid` | snapshot | The territory held as of the extract; an assignment can change. |
| `salesperson.salesquota`, `bonus`, `commissionpct` | snapshot | Pay and quota as of the extract; `salesquota` is not the latest `quota_set` amount (research §3.4). |
| `salesperson.salesytd`, `saleslastyear` | snapshot | Stale counters as of the extract (research §3.4). |
| `countryregioncurrency.countryregioncode`, `currencycode` | creation | The pair is the row's key. |

No snapshot column decides an event's time or order: entities are created at the dataset's first event time.

No domain name: the source has no creation act for any entity (no creation date; `sellstartdate` is kept as data, not used as the creation time), so all keep `<entity>_created`.

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `salesperson` | 17 | 9 | `salesquota`, `territoryid` |
| `product` | 504 | 25 | `productmodelid`, `productsubcategoryid`, `weight` |
| `productmodelproductdescriptionculture` | 762 | 4 | none |
| `productdescription` | 762 | 4 | none |
| `productreview` | 4 | 9 | none |
| `productcategory` | 4 | 4 | none |
| `productsubcategory` | 37 | 5 | none |
| `salesorderdetail` | 121,317 | 10 | none |
| `salesorderheader` | 31,465 | 25 | `creditcardid`, `currencyrateid`, `salespersonid` |
| `salesterritory` | 10 | 10 | none |
| `countryregioncurrency` | 109 | 3 | none |
| `currencyrate` | 13,532 | 7 | none |
| `SalesPersonQuotaHistory` | 163 | 5 | none |

`expected/queries/` holds the answers of the saved questions (`local141`), computed on the source. `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, and compares them and the answers exactly: rows as multisets, numbers by value, text byte for byte.

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build adventureworks             # → $NEORISK_DATA_ROOT/adventureworks/v1/ (default data/datasets/)
uv run dataset verify adventureworks            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
