"""Data-job postings scraped from Google Jobs in 2023: each posting is an event; companies,
skills and the posting-skill links are entities. Stage 1, schema only: the events are ingested
from the Spider2 tables (docs/research/spider2/jobpostings.md); stage 2 adds the behavior.

Spider kept an independent ~10% sample of each table, so about 90% of the company, job and
skill ids point at rows that are not here. Every id is therefore a raw i64, never a ref. The
salaries are float32 artefacts and travel as f64 verbatim. A company's website and its
scrape-time Google links ride on one snapshot per company at N, the last posting.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, cat, f64, i32, i64, opt, ref, text

SCHEMA_VERSION = 1

TITLES = ("Business Analyst", "Cloud Engineer", "Data Analyst", "Data Engineer",
          "Data Scientist", "Machine Learning Engineer", "Senior Data Analyst",
          "Senior Data Engineer", "Senior Data Scientist", "Software Engineer")


@dataclass
class Config:
    pass


def t():
    return opt(text())


def define(p: Pack) -> None:
    p.entity("companies", key="company_key",
             doc="job_company; created at its first posting, else the catalog start (rules)",
             cols={"ext_id": text(doc="company_id"), "name": text()})
    p.event("companies_snapshot",
            doc="State at N = 2023-12-31 03:18:00, the last posting: website and scrape links",
            cols={"company_key": ref("companies"), "link": t(),
                  "link_google": opt(text(doc="Carries scrape-session tokens")),
                  "thumbnail": opt(text(doc="Carries scrape-session image ids"))})
    p.entity("skills", key="skill_key", doc="skills_dim; created at the catalog start (a rule)",
             cols={"ext_id": text(doc="skill_id"), "skills": text(),
                   "type": cat("analyst_tools", "async", "cloud", "databases", "programming",
                               "sync", "webframeworks")})
    p.entity("job_skills", key="job_skill_key",
             doc="skills_job_dim; created at its posting, else the catalog start (rules)",
             cols={"ext_id": text(doc="'<job_id>-<skill_id>'"),
                   "job_id": i64(doc="Raw id; 10% are postings here"),
                   "skill_id": i64(doc="Raw id; most are not in skills")})
    p.event("job_posted", doc="One per posting, at job_posted_date",
            cols={"job_id": i64(), "company_id": i64(doc="Raw id; 9.3% are companies here"),
                  "job_title_short": cat(*TITLES), "job_title": t(), "job_location": t(),
                  "job_via": t(), "job_schedule_type": t(), "job_work_from_home": i32(),
                  "search_location": text(), "job_no_degree_mention": i32(),
                  "job_health_insurance": i32(), "job_country": t(),
                  "salary_rate": opt(cat("day", "hour", "month", "week", "year")),
                  "salary_year_avg": opt(f64()), "salary_hour_avg": opt(f64())})
