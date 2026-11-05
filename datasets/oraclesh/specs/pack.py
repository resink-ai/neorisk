"""Oracle Sales History (SH): a sports retailer's daily unit sales by customer, product,
channel and promotion, with the daily price and cost quotes they were sold at. Stage 1, schema
only: the events are ingested from the Spider2 tables (docs/research/spider2/oraclesh.md); stage
2 adds the behavior.

51 of the 72 sold products have no product row; they are placeholder products (catalogued = 0),
so the sales keep a ref. The currency table is a rule and is not stored.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, amount, f64, i64, opt, ref, text

SCHEMA_VERSION = 1


@dataclass
class Config:
    pass


def define(p: Pack) -> None:
    p.entity("countries", key="country_id", doc="Countries with their region rollups",
             cols={
                  "ext_id": text(), "country_iso_code": text(), "country_name":
                  text(), "country_subregion": text(), "country_subregion_id":
                  i64(), "country_region": text(), "country_region_id": i64(),
                  "country_total": text(), "country_total_id": i64()})
    p.entity("channels", key="channel_id", doc="Sales channels",
             cols={
                  "ext_id": text(), "channel_desc": text(), "channel_class": text(),
                  "channel_class_id": i64(), "channel_total": text(),
                  "channel_total_id": i64()})
    p.entity("promotions", key="promo_id", doc="Promotions; 999 is 'no promotion' (dates to 9999-01-01)",
             cols={
                  "ext_id": text(), "promo_name": text(), "promo_subcategory":
                  text(), "promo_subcategory_id": i64(), "promo_category": text(),
                  "promo_category_id": i64(),
                  "promo_begin_date": text(), "promo_end_date": text(),
                  "promo_total": text(), "promo_total_id": i64()})
    p.entity("customers", key="cust_id",
             doc="Created at cust_eff_from (2019-01-01 for all); address, contact, marital "
                 "status, income, credit limit and validity are a snapshot",
             cols={
                  "ext_id": text(), "cust_first_name": text(), "cust_last_name":
                  text(), "cust_gender": text(), "cust_year_of_birth": i64(),
                  "cust_total": text(), "cust_total_id": i64(), "cust_src_id": opt(i64()),
                  "cust_eff_from": text()})
    p.entity("times", key="time_id", doc="The date dimension, stored: 10 fiscal and id columns are not calendar arithmetic",
             cols={
                  "ext_id": text(), "day_name": text(), "day_number_in_week": i64(),
                  "day_number_in_month": i64(), "calendar_week_number": i64(),
                  "fiscal_week_number": i64(), "week_ending_day": text(),
                  "week_ending_day_id": i64(), "calendar_month_number": i64(),
                  "fiscal_month_number": i64(), "calendar_month_desc": text(),
                  "calendar_month_id": i64(), "fiscal_month_desc": text(),
                  "fiscal_month_id": i64(), "days_in_cal_month": i64(),
                  "days_in_fis_month": i64(), "end_of_cal_month": text(),
                  "end_of_fis_month": text(), "calendar_month_name": text(),
                  "fiscal_month_name": text(), "calendar_quarter_desc": text(),
                  "calendar_quarter_id": i64(), "fiscal_quarter_desc": text(),
                  "fiscal_quarter_id": i64(), "days_in_cal_quarter": i64(),
                  "days_in_fis_quarter": i64(), "end_of_cal_quarter": text(),
                  "end_of_fis_quarter": text(), "calendar_quarter_number": i64(),
                  "fiscal_quarter_number": i64(), "calendar_year": i64(),
                  "calendar_year_id": i64(), "fiscal_year": i64(), "fiscal_year_id":
                  i64(), "days_in_cal_year": i64(), "days_in_fis_year": i64(),
                  "end_of_cal_year": text(), "end_of_fis_year": text()})
    p.entity("products", key="prod_id", doc="24 catalogued products and 51 placeholders",
             cols={"ext_id": text(), "catalogued": i64(doc="1 for a source products row, 0 for a "
                                                         "placeholder: a sold id with no row"),
                   **{c: opt(text()) for c in (
                       "prod_name", "prod_desc", "prod_subcategory", "prod_subcategory_desc",
                       "prod_category", "prod_category_desc", "prod_unit_of_measure",
                       "prod_pack_size", "prod_total", "prod_src_id", "prod_eff_from")},
                   **{c: opt(i64()) for c in (
                       "prod_subcategory_id", "prod_category_id", "prod_weight_class",
                       "prod_total_id")}})
    p.entity("demographics", key="demographics_id",
             doc="For 8.1% of customers; every answer is a snapshot",
             cols={"ext_id": text(doc="cust_id"), "customer_id": ref("customers")})
    p.event("promotions_snapshot", doc="State at N: the promotion's cost",
            cols={"promo_id": ref("promotions"), "promo_cost": f64()})
    p.event("customers_snapshot",
            doc="State at N: address, contact, marital status, income, credit limit, validity",
            cols={"cust_id": ref("customers"), "cust_marital_status": opt(text()),
                  "cust_street_address": text(), "cust_postal_code": text(),
                  "cust_city": text(), "cust_city_id": i64(), "cust_state_province": text(),
                  "cust_state_province_id": i64(), "country_id": ref("countries"),
                  "cust_main_phone_number": text(), "cust_income_level": opt(text()),
                  "cust_credit_limit": f64(), "cust_email": text(),
                  "cust_eff_to": opt(i64()), "cust_valid": text()})
    p.event("products_snapshot",
            doc="State at N, for the 24 catalogued products: status, prices, supplier, validity",
            cols={"prod_id": ref("products"), "supplier_id": opt(i64()),
                  "prod_status": opt(text()), "prod_list_price": opt(f64()),
                  "prod_min_price": opt(f64()), "prod_eff_to": opt(text()),
                  "prod_valid": opt(text())})
    p.event("demographics_snapshot", doc="State at N: the survey answers",
            cols={"demographics_id": ref("demographics"), "education": text(),
                  "occupation": text(),
                  "household_size": text(doc="Text: '2', '4-5', '9+'"), "yrs_residence": i64(),
                  **{c: i64() for c in ("affinity_card", "cricket", "baseball", "tennis",
                                       "soccer", "golf", "unknown", "misc")},
                  "comments": opt(text())})
    p.event("price_quoted", doc="A product's price and cost for a day, channel and promotion",
            cols={"prod_id": ref("products"), "channel_id": ref("channels"),
                  "promo_id": ref("promotions"), "unit_cost": amount("USD", doc="Can be negative"),
                  "unit_price": amount("USD")})
    p.event("unit_sold", doc="One unit to one customer (quantity is always 1); the price is carried",
            cols={"cust_id": ref("customers"), "prod_id": ref("products"),
                  "channel_id": ref("channels"), "promo_id": ref("promotions"),
                  "quantity_sold": i64(min=1), "amount_sold": amount("USD")})
