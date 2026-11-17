"""Tests for MPCSource-specific logic.

MPCSource.__init__ opens a live STAC catalog connection
(pystac_client.Client.open), and _search_items does a real STAC search
over HTTP -- both go through `requests` under the hood, so `responses`
mocks them at the HTTP layer rather than monkeypatching MPCSource's own
methods. The one thing `responses` can't reach is stac_load's actual pixel
reads (GDAL's /vsicurl/, not the `requests` library) -- that boundary is
still monkeypatched directly, same as the previous round (see
TESTING_PLAN.md §7).
"""

import json
import os

import pytest
import responses
import rioxarray as riox
from shapely.geometry import Point, box

import geoetl.io.mpc as mpc_module
from geoetl.io.base import AOITooLargeError
from geoetl.io.mpc import MPCSource
from tests.conftest import make_raster_dataarray

MPC_STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"

ROOT_CATALOG = {
    "type": "Catalog",
    "id": "microsoft-pc",
    "stac_version": "1.0.0",
    "description": "fake root catalog for tests",
    "conformsTo": [
        "https://api.stacspec.org/v1.0.0/core",
        "https://api.stacspec.org/v1.0.0/item-search",
        "https://api.stacspec.org/v1.0.0/item-search#query",
        "https://api.stacspec.org/v1.0.0/ogcapi-features",
    ],
    "links": [
        {"rel": "self", "href": MPC_STAC_URL, "type": "application/json"},
        {"rel": "root", "href": MPC_STAC_URL, "type": "application/json"},
        {"rel": "search", "href": f"{MPC_STAC_URL}/search", "type": "application/geo+json", "method": "GET"},
        {"rel": "search", "href": f"{MPC_STAC_URL}/search", "type": "application/geo+json", "method": "POST"},
    ],
}


def stac_item(item_id, collection="sentinel-2-l2a", cloud_cover=5.0, datetime_="2020-01-15T10:00:00Z"):
    return {
        "type": "Feature",
        "stac_version": "1.0.0",
        "id": item_id,
        "collection": collection,
        "geometry": {"type": "Point", "coordinates": [10.0, 20.0]},
        "bbox": [9.9, 19.9, 10.1, 20.1],
        "properties": {"datetime": datetime_, "eo:cloud_cover": cloud_cover},
        "links": [],
        "assets": {"B04": {"href": "https://fake/B04.tif", "type": "image/tiff"}},
    }


def stac_feature_collection(items):
    return {"type": "FeatureCollection", "stac_version": "1.0.0", "features": items, "links": []}


@pytest.fixture
def mocked_mpc_catalog():
    """Mocks the one HTTP call MPCSource.__init__ makes (the STAC root
    catalog GET) so constructing a real MPCSource needs no live network --
    at the HTTP layer, not by stubbing out pystac_client itself."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, MPC_STAC_URL, json=ROOT_CATALOG, status=200)
        yield rsps


@pytest.fixture
def mpc_source_factory(mocked_mpc_catalog):
    def _make(**kwargs):
        return MPCSource(out_root="/unused", **kwargs)

    return _make


# ---------------------------------------------------------------------------
# _search_items -- the real search request/response round trip
# ---------------------------------------------------------------------------

def test_search_items_sends_the_configured_filters(mpc_source_factory, mocked_mpc_catalog):
    source = mpc_source_factory(sensor="sentinel2", cloud_cover_max=15, year=2021, month=6)
    mocked_mpc_catalog.add(
        responses.POST, f"{MPC_STAC_URL}/search", json=stac_feature_collection([]), status=200
    )

    source._search_items(Point(10.0, 20.0))

    search_call = [c for c in mocked_mpc_catalog.calls if c.request.method == "POST"][0]
    sent = json.loads(search_call.request.body)
    assert sent["collections"] == ["sentinel-2-l2a"]
    assert sent["query"] == {"eo:cloud_cover": {"lt": 15}}
    assert sent["datetime"].startswith("2021-06-01")


def test_search_items_adds_a_platform_filter_for_landsat(mpc_source_factory, mocked_mpc_catalog):
    source = mpc_source_factory(sensor="landsat8")
    mocked_mpc_catalog.add(
        responses.POST, f"{MPC_STAC_URL}/search", json=stac_feature_collection([]), status=200
    )

    source._search_items(Point(10.0, 20.0))

    search_call = [c for c in mocked_mpc_catalog.calls if c.request.method == "POST"][0]
    sent = json.loads(search_call.request.body)
    assert sent["query"]["platform"] == {"in": ["landsat-8", "landsat-9"]}


def test_search_items_parses_returned_items(mpc_source_factory, mocked_mpc_catalog):
    source = mpc_source_factory(sensor="sentinel2")
    mocked_mpc_catalog.add(
        responses.POST,
        f"{MPC_STAC_URL}/search",
        json=stac_feature_collection([stac_item("a"), stac_item("b")]),
        status=200,
    )

    items = source._search_items(Point(10.0, 20.0))

    assert sorted(i.id for i in items) == ["a", "b"]


# ---------------------------------------------------------------------------
# _build_composite -- "no items" path, driven through a real (mocked) search
# ---------------------------------------------------------------------------

def test_build_composite_raises_a_runtime_error_when_no_items_found(mpc_source_factory, mocked_mpc_catalog):
    source = mpc_source_factory(sensor="sentinel2")
    mocked_mpc_catalog.add(
        responses.POST, f"{MPC_STAC_URL}/search", json=stac_feature_collection([]), status=200
    )

    with pytest.raises(RuntimeError, match="No items found"):
        source._build_composite(Point(10.0, 20.0))


# ---------------------------------------------------------------------------
# _build_composite -- the memory size-cap trigger
# ---------------------------------------------------------------------------
# A rural, outlier-sized AOI can overwhelm the job even with bounded
# per-chunk reads, purely through chunk count. This is the hard safety cap
# that bails out on that one AOI (as AOITooLargeError, so pipeline.py can
# log and skip it) instead of risking the whole job again.
#
# The search side is real (mocked over HTTP, same as above); only
# stac_load is monkeypatched, since that's GDAL's own /vsicurl/ pixel
# fetch, a different I/O stack `responses` has no visibility into.

class _FakeStacDataset:
    """Stands in for odc.stac.stac_load's return value -- _build_composite
    only reads .sizes before the size check runs, so that's all this needs
    to provide."""

    def __init__(self, nx, ny):
        self.sizes = {"x": nx, "y": ny}


def test_build_composite_raises_when_estimated_size_exceeds_the_cap(
    mpc_source_factory, mocked_mpc_catalog, monkeypatch
):
    source = mpc_source_factory(sensor="sentinel2")
    # 5 real (mocked) items x 4 assets (3 bands + SCL) x 20000x20000px x 4
    # bytes ~= 30 GB, comfortably over the 8000 MB default max_composite_mb.
    mocked_mpc_catalog.add(
        responses.POST,
        f"{MPC_STAC_URL}/search",
        json=stac_feature_collection([stac_item(f"item{i}") for i in range(5)]),
        status=200,
    )
    monkeypatch.setattr(mpc_module, "stac_load", lambda *a, **kw: _FakeStacDataset(20000, 20000))

    with pytest.raises(AOITooLargeError):
        source._build_composite(Point(10.0, 20.0))


# ---------------------------------------------------------------------------
# find_local_tiles -- deterministic per-AOI cache lookup
# ---------------------------------------------------------------------------

def test_find_local_tiles_returns_empty_list_when_quads_dir_missing(mpc_source_factory, tmp_path):
    source = mpc_source_factory(sensor="sentinel2")
    assert source.find_local_tiles(Point(10.0, 20.0), str(tmp_path / "missing")) == []


def test_find_local_tiles_returns_empty_list_when_no_cached_composite(mpc_source_factory, tmp_path):
    source = mpc_source_factory(sensor="sentinel2")
    assert source.find_local_tiles(Point(10.0, 20.0), str(tmp_path)) == []


def test_find_local_tiles_finds_the_deterministic_cache_path(mpc_source_factory, tmp_path, make_raster):
    source = mpc_source_factory(sensor="sentinel2")
    geom = box(9.5, 19.5, 10.5, 20.5)
    expected_name = source._tile_path(geom)
    make_raster(expected_name, bounds=(9.0, 19.0, 11.0, 21.0))

    found = source.find_local_tiles(geom, str(tmp_path))

    assert found == [os.path.join(str(tmp_path), expected_name)]


# ---------------------------------------------------------------------------
# download_tiles_for_geometry -- the composite cache lifecycle
# ---------------------------------------------------------------------------

def test_download_reuses_a_valid_cached_composite_without_rebuilding(mpc_source_factory, tmp_path, make_raster, monkeypatch):
    source = mpc_source_factory(sensor="sentinel2")
    geom = Point(10.0, 20.0)
    tile_path = os.path.join(str(tmp_path), source._tile_path(geom))
    make_raster(source._tile_path(geom), bounds=(9.0, 19.0, 11.0, 21.0))

    monkeypatch.setattr(source, "_build_composite", lambda g: (_ for _ in ()).throw(AssertionError("should not rebuild")))

    result = source.download_tiles_for_geometry(geom, str(tmp_path))

    assert result == [tile_path]


def test_download_rebuilds_a_truncated_cached_composite(mpc_source_factory, tmp_path, monkeypatch):
    source = mpc_source_factory(sensor="sentinel2")
    geom = Point(10.0, 20.0)
    tile_path = os.path.join(str(tmp_path), source._tile_path(geom))
    os.makedirs(str(tmp_path), exist_ok=True)
    with open(tile_path, "wb") as f:
        f.write(b"truncated, not a real tiff")

    rebuilt = make_raster_dataarray(bounds=(9.0, 19.0, 11.0, 21.0), dtype="uint16", fill=100)
    monkeypatch.setattr(source, "_build_composite", lambda g: rebuilt)

    result = source.download_tiles_for_geometry(geom, str(tmp_path))

    assert result == [tile_path]
    with riox.open_rasterio(tile_path) as written:
        assert (written.values == 100).all()


def test_download_lets_aoi_too_large_propagate(mpc_source_factory, tmp_path, monkeypatch):
    source = mpc_source_factory(sensor="sentinel2")

    def boom(geom):
        raise AOITooLargeError("too big")

    monkeypatch.setattr(source, "_build_composite", boom)

    with pytest.raises(AOITooLargeError):
        source.download_tiles_for_geometry(Point(10.0, 20.0), str(tmp_path))


def test_download_returns_empty_list_when_build_fails_with_a_runtime_error(mpc_source_factory, tmp_path, monkeypatch):
    source = mpc_source_factory(sensor="sentinel2")

    def boom(geom):
        raise RuntimeError("no items found")

    monkeypatch.setattr(source, "_build_composite", boom)

    assert source.download_tiles_for_geometry(Point(10.0, 20.0), str(tmp_path)) == []


# ---------------------------------------------------------------------------
# clip_to_geometry -- the float64/black-output regression
# ---------------------------------------------------------------------------
# Mirrors PlanetBasemapSource's identical fix: rio.clip() fills pixels
# outside the polygon (but inside its bounding box) with NaN when no
# nodata is declared, silently promoting to float64 -- fillna+astype must
# restore the composite's real dtype.

def test_clip_restores_original_dtype_with_no_nan_leakage(mpc_source_factory, tmp_path, make_raster):
    source = mpc_source_factory(sensor="sentinel2")
    geom = box(9.9995, 19.9995, 10.0005, 20.0005)  # tiny AOI, not pixel-aligned
    tile_name = source._tile_path(geom)
    make_raster(
        tile_name,
        bounds=(9.99, 19.99, 10.01, 20.01),
        shape=(3, 30, 30),
        crs="EPSG:4326",
        dtype="uint16",
        fill=4000,
    )

    out_path = tmp_path / "chip.tif"
    source.clip_to_geometry(geom, str(out_path), str(tmp_path))

    with riox.open_rasterio(str(out_path)) as chip:
        assert chip.dtype == "uint16"
        assert (chip.values == 4000).all()


def test_clip_raises_when_nothing_is_cached_and_build_fails(mpc_source_factory, tmp_path, monkeypatch):
    source = mpc_source_factory(sensor="sentinel2")
    monkeypatch.setattr(source, "_build_composite", lambda g: (_ for _ in ()).throw(RuntimeError("no items")))

    with pytest.raises(RuntimeError, match="No tiles available"):
        source.clip_to_geometry(Point(10.0, 20.0), str(tmp_path / "chip.tif"), str(tmp_path))


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
# set_time_filter
# ---------------------------------------------------------------------------

def test_set_time_filter_monthly(mpc_source_factory):
    source = mpc_source_factory(sensor="sentinel2")
    source.set_time_filter(year=2021, steps=[7], cadence="monthly")
    assert (source.year, source.month) == (2021, 7)


def test_set_time_filter_quarterly_maps_to_start_month(mpc_source_factory):
    source = mpc_source_factory(sensor="sentinel2")
    source.set_time_filter(year=2021, steps=[3], cadence="quarterly")
    assert (source.year, source.month) == (2021, 7)  # Q3 -> July


def test_set_time_filter_requires_at_least_one_step(mpc_source_factory):
    source = mpc_source_factory(sensor="sentinel2")
    with pytest.raises(ValueError, match="At least one temporal step"):
        source.set_time_filter(year=2021, steps=[], cadence="monthly")


def test_set_time_filter_clears_explicit_date_overrides(mpc_source_factory):
    source = mpc_source_factory(sensor="sentinel2", start_date="2019-01-01", end_date="2019-01-31")
    source.set_time_filter(year=2021, steps=[7], cadence="monthly")
    assert source.start_date is None
    assert source.end_date is None
