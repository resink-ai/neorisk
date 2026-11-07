"""The Flink engine: Flink SQL in batch mode on the local Docker session cluster
(`apps/dataset/docker/compose.yaml`), running `engines/flink/`.

Statements go through the SQL Gateway's REST API, one at a time, so a block that does not
plan fails only its table. Each block becomes a view; its columns are checked against the
results table, and the sink selects them by name in the results' order. Every block that
plans is inserted in one `EXECUTE STATEMENT SET`, one job: a job that fails fails each of
those tables with Flink's root cause. The data root is mounted at the same path in the
containers, so the run folder is where Flink writes.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from dataset.engines import Built, Job, Timings
from dataset.engines.views import flink_views
from dataset.names import data_root

GATEWAY = "http://localhost:18083/v1"
REST = "http://localhost:18081"
JOBMANAGER = "neorisk-engines-jobmanager-1"
CONTAINERS = (JOBMANAGER, "neorisk-engines-taskmanager-1", "neorisk-engines-sql-gateway-1")
COMPOSE = "apps/dataset/docker/compose.yaml"
JOB_TIMEOUT = 1800.0


class FlinkError(RuntimeError):
    pass


def up_command() -> str:
    return f"NEORISK_DATA_ROOT={data_root()} docker compose -f {COMPOSE} up -d"


def _http(method: str, url: str, body: dict | None = None, timeout: float = 60) -> dict:
    req = urllib.request.Request(url, method=method,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise FlinkError(root_cause(e.read().decode(errors="replace"))) from None


def root_cause(trace: str) -> str:
    """The last `Caused by:` line of a Java trace (or its first line), without the class
    prefix noise of the gateway's wrapping."""
    text = trace.replace("\\n", "\n").replace("\\t", "\t")
    causes = re.findall(r"Caused by: ([^\n]+)", text)
    line = causes[-1] if causes else next((s for s in text.splitlines() if s.strip()), "")
    return line.strip()[:800]


def flink_type(t: pa.DataType) -> str:
    if pa.types.is_int32(t) or pa.types.is_int16(t) or pa.types.is_int8(t):
        return "INT"
    if pa.types.is_integer(t):
        return "BIGINT"
    if pa.types.is_floating(t):
        return "DOUBLE"
    if pa.types.is_boolean(t):
        return "BOOLEAN"
    if pa.types.is_date(t):
        return "DATE"
    if pa.types.is_timestamp(t):
        return "TIMESTAMP(6)"        # UTC wall time, as the views give it
    return "STRING"


def q(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


def lit(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


class Gateway:
    """One SQL Gateway session."""

    def __init__(self, properties: dict[str, str], url: str = GATEWAY):
        self.url = url
        self.session = _http("POST", f"{url}/sessions",
                             {"properties": properties})["sessionHandle"]

    def run(self, statement: str, timeout: float = 120) -> list[dict]:
        """Execute one statement; its result rows (`{"kind", "fields"}`) and, for a job, the
        job id under the key `job`. Raises FlinkError with the root cause."""
        base = f"{self.url}/sessions/{self.session}"
        op = _http("POST", f"{base}/statements", {"statement": statement})["operationHandle"]
        end = time.monotonic() + timeout
        while True:
            st = _http("GET", f"{base}/operations/{op}/status")["status"]
            if st not in ("RUNNING", "PENDING", "INITIALIZED"):
                break
            if time.monotonic() > end:
                raise FlinkError(f"the statement did not finish within {timeout:.0f} s")
            time.sleep(0.2)
        rows, job, uri = [], None, f"/sessions/{self.session}/operations/{op}/result/0"
        while uri:
            res = _http("GET", f"{self.url}{uri}?rowFormat=JSON")
            job = job or res.get("jobID")
            rows += res.get("results", {}).get("data", [])
            uri = None if res.get("resultType") == "EOS" else res.get("nextResultUri")
            if uri:
                uri = uri.removeprefix("/v1")
                if res.get("resultType") == "NOT_READY":
                    time.sleep(0.2)
        return [*rows, {"job": job}] if job else rows

    def close(self) -> None:
        try:
            _http("DELETE", f"{self.url}/sessions/{self.session}", timeout=10)
        except (FlinkError, OSError):
            pass


def wait_job(job_id: str, timeout: float = JOB_TIMEOUT) -> dict:
    """The job's final state from the JobManager's REST API; cancels it on timeout."""
    end = time.monotonic() + timeout
    while True:
        j = _http("GET", f"{REST}/jobs/{job_id}")
        if j["state"] in ("FINISHED", "FAILED", "CANCELED"):
            return j
        if time.monotonic() > end:
            _http("PATCH", f"{REST}/jobs/{job_id}?mode=cancel")
            raise FlinkError(f"the job ran past {timeout:.0f} s and was cancelled")
        time.sleep(0.5)


def job_failure(job_id: str) -> str:
    ex = _http("GET", f"{REST}/jobs/{job_id}/exceptions")
    entries = ex.get("exceptionHistory", {}).get("entries", [])
    trace = entries[0].get("stacktrace", "") if entries else (ex.get("root-exception") or "")
    return root_cause(trace) or "the job failed"


def _mounts() -> list[str]:
    out = subprocess.run(["docker", "inspect", JOBMANAGER, "--format", "{{json .Mounts}}"],
                         capture_output=True, text=True, timeout=20, check=False).stdout
    try:
        return [m["Source"] for m in json.loads(out or "[]")]
    except json.JSONDecodeError:
        return []


class Flink:
    name = "flink"
    mode = "batch"
    containers = CONTAINERS

    def check(self) -> str | None:
        try:
            ov = _http("GET", f"{REST}/overview", timeout=3)
            _http("GET", f"{GATEWAY}/info", timeout=3)
        except (FlinkError, OSError):
            return f"the Flink cluster is not running; start it: {up_command()}"
        if ov.get("taskmanagers", 0) < 1:
            return "the Flink cluster has no TaskManager yet; wait and retry"
        root = data_root().resolve()
        if not any(root.is_relative_to(Path(m)) for m in _mounts()):
            return (f"the containers do not mount the data root {root}; restart them: "
                    f"docker compose -f {COMPOSE} down && {up_command()}")
        return None

    # --- the parts flink-stream replaces -------------------------------------------------

    def prepare(self, job: Job) -> float | None:
        """Make the log readable; the seconds it took, or None."""
        return None

    def source(self, job: Job) -> str:
        return (f"CREATE TABLE log (seq BIGINT, event_time TIMESTAMP_LTZ(6), event_type STRING, "
                f"entity_type STRING, entity_key STRING, schema_version INT, payload STRING) "
                f"WITH ('connector' = 'filesystem', 'path' = {lit(str(job.root / 'log'))}, "
                f"'format' = 'parquet')")

    def sink_with(self, job: Job, table: str) -> str:
        return (f"'connector' = 'filesystem', 'path' = {lit(str(job.table_dir(table)))}, "
                f"'format' = 'parquet'")

    def collect(self, job: Job, tables: list[str], errors: dict[str, str]) -> float | None:
        """Turn the sinks into `tables/<t>/` Parquet; the seconds it took, or None. The batch
        filesystem sink writes no file for zero rows, so a finished table without one is
        written empty, with the expected columns."""
        from dataset.engines.grade import data_files
        for t in tables:
            try:
                data_files(job.table_dir(t))
            except FileNotFoundError:
                job.table_dir(t).mkdir(parents=True, exist_ok=True)
                schema = pa.schema([(c, ty) for c, ty in job.columns[t]])
                pq.write_table(schema.empty_table(), job.table_dir(t) / "part-0.parquet")
        return None

    # --------------------------------------------------------------------------------------

    def properties(self, job: Job) -> dict[str, str]:
        return {"execution.runtime-mode": self.mode, "table.local-time-zone": "UTC",
                "table.dml-sync": "false", "parallelism.default": "4",
                "pipeline.name": f"{job.cfg.name} {self.name} {job.out.name}"}

    def build(self, job: Job) -> Built:
        load = self.prepare(job)
        schema = json.loads((job.root / "schema" / "events.json").read_text())
        errors: dict[str, str] = {}
        inserts: list[tuple[str, str]] = []
        build = 0.0
        t_plan = time.perf_counter()
        gw = Gateway(self.properties(job))
        try:
            try:
                gw.run(self.source(job))
                for name, sql in flink_views(schema):
                    gw.run(f"CREATE TEMPORARY VIEW {q(name)} AS {sql}")
            except FlinkError as e:
                return Built(Timings(build=0.0, load=load),
                             {t: f"the log cannot be read: {e}" for t in job.columns})
            synthetic = job.cfg.kind == "synthetic"
            for blocks in job.blocks.values():
                for table, sql in blocks.items():
                    view = table if synthetic else f"__port__{table}"   # Spider2 names clash
                    want = [c for c, _ in job.columns[table]]
                    try:
                        gw.run(f"CREATE TEMPORARY VIEW {q(view)} AS {sql.rstrip().rstrip(';')}")
                        have = [r["fields"][0] for r in gw.run(f"DESCRIBE {q(view)}")
                                if "fields" in r]
                        if sorted(have) != sorted(want):
                            raise FlinkError(
                                f"columns differ: missing {sorted(set(want) - set(have))}, "
                                f"extra {sorted(set(have) - set(want))}")
                        cols = ", ".join(f"{q(c)} {flink_type(t)}" for c, t in job.columns[table])
                        gw.run(f"CREATE TABLE {q('__sink__' + table)} ({cols}) "
                               f"WITH ({self.sink_with(job, table)})")
                        ins = (f"INSERT INTO {q('__sink__' + table)} SELECT "
                               f"{', '.join(q(c) for c in want)} FROM {q(view)}")
                        gw.run(f"EXPLAIN {ins}")
                    except FlinkError as e:
                        errors[table] = f"the block fails: {e}"
                        continue
                    inserts.append((table, ins))
            plan = time.perf_counter() - t_plan
            if inserts:
                t0 = time.perf_counter()
                try:
                    res = gw.run("EXECUTE STATEMENT SET BEGIN\n"
                                 + ";\n".join(i for _, i in inserts) + ";\nEND")
                    job_id = next(r["job"] for r in res if "job" in r)
                    state = wait_job(job_id)
                    if state["state"] != "FINISHED":
                        raise FlinkError(f"the Flink job {state['state'].lower()}: "
                                         f"{job_failure(job_id)}")
                except (FlinkError, StopIteration) as e:
                    for t, _ in inserts:
                        errors[t] = str(e) or "the statement set returned no job"
                build = time.perf_counter() - t0
        finally:
            gw.close()
        write = self.collect(job, [t for t, _ in inserts if t not in errors], errors)
        return Built(Timings(build=build, load=load, plan=plan, write=write), errors)
