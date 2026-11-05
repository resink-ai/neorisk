"""India data-science salaries: Glassdoor listings, each the average of the salaries reported for
one company, job title and city. Stage 1, schema only: the rows are ingested from the Spider2
table (docs/research/spider2/edu_misc.md).

The table has no time. Each listing is an entity (company, title, city) created by rule at
2022-01-01, and its reported aggregate is one `salary_aggregate_reported` event at that same
time. The salary text (`₹6,48,573/yr`) travels as a currency, an integer amount and a period,
and is rebuilt with Indian lakh digit grouping.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, cat, i64, opt, ref, text

SCHEMA_VERSION = 1


@dataclass
class Config:
    pass


def define(p: Pack) -> None:
    p.entity("salary_listing", key="listing_id",
             doc="A Glassdoor listing; untimed, created by rule at 2022-01-01",
             cols={"ext_id": text(doc="index, the pandas RangeIndex (rowid - 1)"),
                   "company_name": opt(text()), "job_title": text(),
                   "location": cat("Bangalore", "Hyderabad", "Mumbai", "New Delhi", "Pune")})
    p.event("salary_aggregate_reported", doc="The listing's aggregate, at its creation (a rule)",
            cols={"listing_id": ref("salary_listing"),
                  "salaries_reported": opt(i64(doc="Integral; REAL in the source")),
                  "salary_currency": cat("₹", "$", "£", "AFN "),
                  "salary_amount": i64(doc="The amount without its digit grouping"),
                  "salary_period": cat("yr", "mo", "hr")})
