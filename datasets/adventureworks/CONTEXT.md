# adventureworks

## What this is

AdventureWorks, a bicycle maker: sales orders with lines and shipments, salesperson quotas, currency rates and product reviews.

Version `v1`, kind `spider2`. The input is one ordered event log of 199,389 events; the output is the 13 source tables, rebuilt exactly, and the answers to 1 saved Spider 2.0 questions.

## Raw data

`AdventureWorks.sqlite`, 13 tables. A generated sample database; MIT licence (Microsoft).

Times are midnights, read as UTC. Order money is rebuilt from 1e-4 integers.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/adventureworks.md`](../../docs/research/spider2/adventureworks.md).

## How the log was made

Orders, lines and shipments are events owned by the sales order; quotas (by salesperson), currency rates (by currency) and product reviews are events too. Products, territories and salespersons are entities. Money is held as integers of 1e-4; number-or-empty columns are carried as text.

`uv run dataset build adventureworks` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `product_categories_created` | entity | 4 | `product_category_id`, `ext_id`, `name`, `rowguid`, `modifieddate` |
| `product_subcategories_created` | entity | 37 | `product_subcategory_id`, `ext_id`, `product_category_id`, `name`, `rowguid`, `modifieddate` |
| `products_created` | entity | 504 | `product_id`, `ext_id`, `name`, `productnumber`, `makeflag`, `finishedgoodsflag`, … (26 in all) |
| `product_descriptions_created` | entity | 762 | `product_description_id`, `ext_id`, `description`, `rowguid`, `modifieddate`, `productmodelid`, … (8 in all) |
| `territories_created` | entity | 10 | `territory_id`, `ext_id`, `name`, `countryregioncode`, `group`, `salesytd`, … (11 in all) |
| `salespersons_created` | entity | 17 | `salesperson_id`, `ext_id`, `territoryid`, `salesquota`, `bonus`, `commissionpct`, … (10 in all) |
| `country_currencies_created` | entity | 109 | `country_currency_id`, `ext_id`, `countryregioncode`, `currencycode`, `modifieddate` |
| `order_placed` | business | 31,465 | `salesorderid`, `revisionnumber`, `duedate`, `onlineorderflag`, `purchaseordernumber`, `accountnumber`, … (19 in all) |
| `order_line_added` | business | 121,317 | `salesorderid`, `salesorderdetailid`, `carriertrackingnumber`, `orderqty`, `product_id`, `specialofferid`, … (9 in all) |
| `order_shipped` | business | 31,465 | `salesorderid` |
| `currency_rate_published` | business | 13,532 | `tocurrencycode`, `currencyrateid`, `fromcurrencycode`, `averagerate`, `endofdayrate`, `modifieddate` |
| `quota_set` | business | 163 | `salesperson_id`, `quotadate`, `salesquota`, `rowguid` |
| `product_reviewed` | business | 4 | `product_id`, `productreviewid`, `reviewername`, `emailaddress`, `rating`, `comments` |

## Times set by rule

None. Every event carries a source date.

## Snapshot columns

Classified in PR 2. Until then every entity attribute travels in its creation event.

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
