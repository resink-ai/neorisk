"""Synthetic event data framework."""

from neorisk_simkit.attributes import AttrSpec, Cardinality, Volatility
from neorisk_simkit.entities import EntitySpec, EntityTable, attach_asof, build_entities, map_ids
from neorisk_simkit.export import Dataset, export
from neorisk_simkit.features import rolling, rolling_asof
from neorisk_simkit.ids import make_uuids
from neorisk_simkit.references import RefSpec, hubs, resolve_reference, skewed, uniform
from neorisk_simkit.scorer import MLPScorer, XGBScorer, calibrate, sample_labels

__all__ = [
    "AttrSpec",
    "Cardinality",
    "Dataset",
    "EntitySpec",
    "EntityTable",
    "MLPScorer",
    "RefSpec",
    "Volatility",
    "XGBScorer",
    "attach_asof",
    "build_entities",
    "calibrate",
    "export",
    "hubs",
    "make_uuids",
    "map_ids",
    "resolve_reference",
    "rolling",
    "rolling_asof",
    "sample_labels",
    "skewed",
    "uniform",
]
