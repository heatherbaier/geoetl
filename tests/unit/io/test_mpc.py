"""Tests for MPCSource-specific logic.

MPCSource.__init__ opens a live STAC catalog connection
(pystac_client.Client.open), so every test here that needs to construct one
patches that open call out -- otherwise just importing/instantiating this
class in CI would make a real network call to Microsoft Planetary Computer.
"""

import pytest
from shapely.geometry import Point

import geoetl.io.mpc as mpc_module
from geoetl.io.base import AOITooLargeError
from geoetl.io.mpc import MPCSource


@pytest.fixture
def mpc_source_factory(monkeypatch):
    monkeypatch.setattr(mpc_module.pystac_client.Client, "open", lambda *a, **kw: object())

    def _make(**kwargs):
        return MPCSource(out_root="/unused", **kwargs)

    return _make


# ---------------------------------------------------------------------------
# _tile_path -- the stale-cache-on-band-change regression
# ---------------------------------------------------------------------------
# Without the band fingerprint in the cache filename, changing a sensor's
# `bands` config (constructor override, or editing SENSOR_CONFIGS) while
# pointing at a quads_dir with composites cached under the old band list
# would make find_local_tiles/has_all_tiles silently reuse the old,
# differently-banded composite -- no error, just missing bands.

def test_tile_path_changes_when_bands_override_differs(mpc_source_factory):
    geom = Point(10.0, 20.0)
    default = mpc_source_factory(sensor="sentinel2")
    custom = mpc_source_factory(sensor="sentinel2", bands=["B04", "B03", "B02", "B08"])

    assert default._tile_path(geom) != custom._tile_path(geom)


def test_tile_path_is_stable_for_the_same_config(mpc_source_factory):
    geom = Point(10.0, 20.0)
    a = mpc_source_factory(sensor="sentinel2")
    b = mpc_source_factory(sensor="sentinel2")

    assert a._tile_path(geom) == b._tile_path(geom)


def test_bands_override_does_not_mutate_the_shared_sensor_config(mpc_source_factory):
    # A per-instance bands override must not leak into other MPCSource
    # instances or later config runs in the same process.
    from geoetl.io.mpc import SENSOR_CONFIGS

    original_bands = list(SENSOR_CONFIGS["sentinel2"]["bands"])
    mpc_source_factory(sensor="sentinel2", bands=["B08", "B11"])

    assert SENSOR_CONFIGS["sentinel2"]["bands"] == original_bands


def test_bands_override_rejects_a_non_list(mpc_source_factory):
    with pytest.raises(ValueError, match="non-empty list"):
        mpc_source_factory(sensor="sentinel2", bands="B04")


def test_empty_bands_override_is_silently_ignored(mpc_source_factory):
    # NB: this documents current behavior, not necessarily desired behavior.
    # mpc.py's `if bands:` guard is falsy for `bands=[]`, so the "must be a
    # non-empty list" check inside it never actually runs for an empty list
    # -- it's unreachable for the one case its message describes. Tracked
    # under the "Config validation" item in ROADMAP.md rather than fixed
    # here, since that's a config-validation concern, not a test-suite one.
    from geoetl.io.mpc import SENSOR_CONFIGS

    source = mpc_source_factory(sensor="sentinel2", bands=[])
    assert source.cfg["bands"] == SENSOR_CONFIGS["sentinel2"]["bands"]


def test_unknown_sensor_raises_immediately(mpc_source_factory):
    with pytest.raises(ValueError, match="Unknown sensor"):
        mpc_source_factory(sensor="not-a-real-sensor")


# ---------------------------------------------------------------------------
# _build_composite -- the memory size-cap trigger
# ---------------------------------------------------------------------------
# A rural, outlier-sized AOI can overwhelm the job even with bounded
# per-chunk reads, purely through chunk count. This is the hard safety cap
# that bails out on that one AOI (as AOITooLargeError, so pipeline.py can
# log and skip it) instead of risking the whole job again.

class _FakeStacDataset:
    """Stands in for odc.stac.stac_load's return value -- _build_composite
    only reads .sizes before the size check runs, so that's all this needs
    to provide."""

    def __init__(self, nx, ny):
        self.sizes = {"x": nx, "y": ny}


def test_build_composite_raises_when_estimated_size_exceeds_the_cap(mpc_source_factory, monkeypatch):
    source = mpc_source_factory(sensor="sentinel2")
    # 5 items x 4 assets (3 bands + SCL) x 20000x20000px x 4 bytes ~= 30 GB,
    # comfortably over the 8000 MB default max_composite_mb.
    monkeypatch.setattr(source, "_search_items", lambda geom: [object()] * 5)
    monkeypatch.setattr(mpc_module, "stac_load", lambda *a, **kw: _FakeStacDataset(20000, 20000))

    with pytest.raises(AOITooLargeError):
        source._build_composite(Point(10.0, 20.0))


def test_build_composite_raises_a_runtime_error_when_no_items_found(mpc_source_factory, monkeypatch):
    source = mpc_source_factory(sensor="sentinel2")
    monkeypatch.setattr(source, "_search_items", lambda geom: [])

    with pytest.raises(RuntimeError, match="No items found"):
        source._build_composite(Point(10.0, 20.0))
