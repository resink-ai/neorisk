"""stacking: one person's automated model-stacking tool, run over 20 Kaggle tasks.
Each run (problem, version) profiles its features, scores a pool of level-0 models and a
level-1 Stack over 3 steps, and weights the models and features at each step.
Stage 1, schema only: the events are ingested from the Spider2 tables
(docs/research/spider2/stacking.md); stage 2 adds the behavior.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, cat, f64, i32, i64, opt, ref, text

SCHEMA_VERSION = 1


@dataclass
class Config:
    pass


def define(p: Pack) -> None:
    p.entity("problems", key="problem_key", doc="Created at its first run's time (a rule)",
             cols={"ext_id": text(doc="name"), "path": text(),
                   "type": cat("classification", "regression"),
                   "target": text(doc="Verbatim; concrete's ends in a space")})
    p.entity("solutions", key="run_key", doc="One run (problem, version): run_configured at the run clock",
             cols={"ext_id": text(doc="name || '#' || version"), "problem": ref("problems"),
                   "version": i32(), "correlation": f64(), "nb_model": i32(),
                   "nb_feature": i32(), "score": f64(), "test_size": f64(),
                   "resampling": i32()})
    row = {"run": ref("solutions"), "src_rowid": i64()}
    p.event("feature_profiled", doc="One eda row, at the run's start",
            cols={**row, "feature": text(), "type": opt(cat("num", "cat")),
                  "range": opt(text(doc="Byte-exact; declared BLOB, holds text")),
                  "drop_user": i32(), "drop_correlation": i32(), "target": i32()})
    p.event("model_scored", doc="A model's scores at a step, the Stack included",
            cols={**row, "step": i32(), "model": text(), "train_score": f64(),
                  "test_score": f64()})
    p.event("model_weighted", doc="A level-0 model's importance at a step",
            cols={**row, "step": i32(), "model": text(), "importance": f64()})
    p.event("feature_weighted", doc="A feature's importance at a step",
            cols={**row, "step": i32(), "feature": text(), "importance": f64()})
    p.event("step_completed", doc="The end of a step, with its level-1 model",
            cols={**row, "step": i32(), "L1_model": cat("regression", "tree")})
