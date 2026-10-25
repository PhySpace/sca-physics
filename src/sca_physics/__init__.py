"""Addon-owned physics metadata; not native SimpleCADAPI physics fields."""

__version__ = "0.1.8rc1"

from .deformable import geometry_source_snapshot, mesh_cache_key, upsert_deformable_volume
from .rigid_chain import upsert_rigid_chain
from .circle_rod import circle_rod
from .update import update_config, update_package
