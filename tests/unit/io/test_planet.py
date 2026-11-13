"""Tests for PlanetBasemapSource.

Unlike MPCSource, everything network-bound here goes through either
requests.Session (mockable with `responses`) or urllib.request.urlretrieve
for the actual quad download (NOT intercepted by `responses` -- it patches
requests' transport, not urllib -- so that one call is monkeypatched
directly). merge/clip is real rioxarray/shapely work against tiny synthetic
tiles, no mocking needed there.
"""

import json
import os

import geopandas as gpd
import pytest
import responses
import rioxarray as riox
from shapely.geometry import box

from geoetl.io.planet import PlanetBasemapSource

MOSAIC_LOOKUP_URL = "https://api.planet.com/basemaps/v1/mosaics"


@pytest.fixture
def planet_source():
    return PlanetBasemapSource(api_key="fake-key", out_root="/unused", mosaic_name="global_monthly_2024_01_mosaic")


def _mock_mosaic_lookup(mosaic_id="mosaic-abc"):
    responses.add(
        responses.GET,
        MOSAIC_LOOKUP_URL,
        json={"mosaics": [{"id": mosaic_id}]},
        status=200,
    )


def _mock_quad_search(quad_links, mosaic_id="mosaic-abc"):
    responses.add(
        responses.GET,
        f"{MOSAIC_LOOKUP_URL}/{mosaic_id}/quads",
        json={"items": [{"id": qid, "_links": {"download": link}} for qid, link in quad_links.items()]},
        status=200,
    )


# ---------------------------------------------------------------------------
# download_tiles_for_geometry
# ---------------------------------------------------------------------------

@responses.activate
def test_download_returns_empty_list_when_mosaic_not_found(planet_source, tmp_path):
    responses.add(responses.GET, MOSAIC_LOOKUP_URL, json={"mosaics": []}, status=200)

    result = planet_source.download_tiles_for_geometry(box(0, 0, 1, 1), str(tmp_path))

    assert result == []


@responses.activate
def test_download_returns_empty_list_when_mosaic_lookup_fails(planet_source, tmp_path):
    responses.add(responses.GET, MOSAIC_LOOKUP_URL, json={}, status=500)

    result = planet_source.download_tiles_for_geometry(box(0, 0, 1, 1), str(tmp_path))

    assert result == []


@responses.activate
def test_download_returns_empty_list_when_no_quads_found(planet_source, tmp_path):
    _mock_mosaic_lookup()
    _mock_quad_search({})

    result = planet_source.download_tiles_for_geometry(box(0, 0, 1, 1), str(tmp_path))

    assert result == []


@responses.activate
def test_download_fetches_each_quad_not_already_cached(planet_source, tmp_path, monkeypatch):
    _mock_mosaic_lookup()
    _mock_quad_search({"q1": "https://fake/q1.tif", "q2": "https://fake/q2.tif"})

    fetched = []

    def fake_urlretrieve(url, filename):
        fetched.append((url, filename))
        with open(filename, "wb") as f:
            f.write(b"fake raster bytes")

    monkeypatch.setattr("geoetl.io.planet.urllib.request.urlretrieve", fake_urlretrieve)

    result = planet_source.download_tiles_for_geometry(box(0, 0, 1, 1), str(tmp_path))

    assert len(result) == 2
    assert len(fetched) == 2
    assert all(os.path.exists(p) for p in result)


@responses.activate
def test_download_skips_a_quad_already_validly_cached(planet_source, tmp_path, monkeypatch, make_raster):
    _mock_mosaic_lookup()
    _mock_quad_search({"q1": "https://fake/q1.tif"})

    # Pre-populate the cache with a real, valid raster at the expected path.
    cached_path = os.path.join(str(tmp_path), "q1.tif")
    real_tile = make_raster("elsewhere.tif")
    os.rename(real_tile, cached_path)

    called = []
    monkeypatch.setattr(
        "geoetl.io.planet.urllib.request.urlretrieve",
        lambda url, filename: called.append(filename),
    )

    result = planet_source.download_tiles_for_geometry(box(0, 0, 1, 1), str(tmp_path))

    assert called == []  # never re-fetched
    assert result == [cached_path]


@responses.activate
def test_download_redownloads_a_truncated_cached_quad(planet_source, tmp_path, monkeypatch):
    _mock_mosaic_lookup()
    _mock_quad_search({"q1": "https://fake/q1.tif"})

    cached_path = os.path.join(str(tmp_path), "q1.tif")
    with open(cached_path, "wb") as f:
        f.write(b"truncated, not a real tiff")  # left behind by an interrupted download

    fetched = []

    def fake_urlretrieve(url, filename):
        fetched.append(filename)
        with open(filename, "wb") as f:
            f.write(b"a full replacement download")

    monkeypatch.setattr("geoetl.io.planet.urllib.request.urlretrieve", fake_urlretrieve)

    planet_source.download_tiles_for_geometry(box(0, 0, 1, 1), str(tmp_path))

    assert fetched == [cached_path]  # discarded and re-fetched, not left as permanently broken


# ---------------------------------------------------------------------------
# clip_to_geometry -- real merge/clip over synthetic tiles, no mocking
# ---------------------------------------------------------------------------
# geom is reprojected to EPSG:3857 inside clip_to_geometry (Planet quads are
# always Web Mercator), so tiles here are built directly in EPSG:3857 with
# bounds comfortably covering a tiny AOI near the origin (where lon/lat
# (0, 0) also maps to Web Mercator (0, 0)).

AOI_NEAR_ORIGIN = box(-0.001, -0.001, 0.001, 0.001)  # ~111m x 111m at the equator


def test_clip_merges_and_clips_a_single_cached_quad(planet_source, tmp_path, make_raster):
    make_raster(
        "quad1.tif",
        bounds=(-500, -500, 500, 500),
        shape=(3, 20, 20),
        crs="EPSG:3857",
        dtype="uint16",
        fill=500,
    )

    out_path = tmp_path / "chip.tif"
    planet_source.clip_to_geometry(AOI_NEAR_ORIGIN, str(out_path), str(tmp_path))

    with riox.open_rasterio(str(out_path)) as chip:
        # The black-PNG-style regression this mirrors from MPCSource: clip()
        # leaves NaN outside the polygon on a non-rectangular-pixel-aligned
        # clip; fillna+astype must restore the original dtype with no NaN.
        assert chip.dtype == "uint16"
        assert (chip.values == 500).all()


def test_clip_merges_two_overlapping_quads(planet_source, tmp_path, make_raster):
    # Two quads, each only partially covering the AOI -- has_all_tiles-style
    # coverage is Planet's whole reason for caching a grid of quads instead
    # of one composite per AOI; the merge must stitch them seamlessly.
    make_raster(
        "west.tif", bounds=(-500, -500, 0, 500), shape=(1, 20, 20), crs="EPSG:3857", dtype="uint16", fill=100
    )
    make_raster(
        "east.tif", bounds=(0, -500, 500, 500), shape=(1, 20, 20), crs="EPSG:3857", dtype="uint16", fill=200
    )

    out_path = tmp_path / "chip.tif"
    planet_source.clip_to_geometry(AOI_NEAR_ORIGIN, str(out_path), str(tmp_path))

    with riox.open_rasterio(str(out_path)) as chip:
        values = set(chip.values.ravel().tolist())
        # Both quads contributed -- not just whichever merge_arrays happened
        # to place "on top".
        assert values <= {100, 200}
        assert len(values) == 2


@responses.activate
def test_clip_downloads_when_nothing_is_cached_locally(planet_source, tmp_path, monkeypatch, make_raster):
    _mock_mosaic_lookup()
    _mock_quad_search({"q1": "https://fake/q1.tif"})

    tile_source = make_raster(
        "built_elsewhere.tif", bounds=(-500, -500, 500, 500), shape=(1, 10, 10), crs="EPSG:3857", fill=42
    )

    def fake_urlretrieve(url, filename):
        os.replace(tile_source, filename)

    monkeypatch.setattr("geoetl.io.planet.urllib.request.urlretrieve", fake_urlretrieve)

    out_path = tmp_path / "chip.tif"
    planet_source.clip_to_geometry(AOI_NEAR_ORIGIN, str(out_path), str(tmp_path))

    assert out_path.exists()


@responses.activate
def test_clip_raises_when_no_quads_available_anywhere(planet_source, tmp_path):
    _mock_mosaic_lookup()
    _mock_quad_search({})  # nothing cached locally, and nothing to download either

    with pytest.raises(RuntimeError, match="No Planet quads available"):
        planet_source.clip_to_geometry(box(50, 50, 51, 51), str(tmp_path / "chip.tif"), str(tmp_path))


# ---------------------------------------------------------------------------
# set_time_filter
# ---------------------------------------------------------------------------

def test_set_time_filter_monthly(planet_source):
    planet_source.set_time_filter(year=2024, steps=[3], cadence="monthly")
    assert planet_source.mosaic_name == "global_monthly_2024_03_mosaic"


def test_set_time_filter_quarterly(planet_source):
    planet_source.set_time_filter(year=2024, steps=[2], cadence="quarterly")
    assert planet_source.mosaic_name == "global_quarterly_2024q2_mosaic"


def test_set_time_filter_requires_at_least_one_step(planet_source):
    with pytest.raises(ValueError, match="At least one temporal step"):
        planet_source.set_time_filter(year=2024, steps=[], cadence="monthly")


def test_set_time_filter_is_a_noop_for_static_imagery(planet_source):
    original = planet_source.mosaic_name
    planet_source.set_time_filter(year=None)
    assert planet_source.mosaic_name == original
