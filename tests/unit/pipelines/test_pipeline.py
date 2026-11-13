"""Tests for pipeline.py's per-AOI control flow: this is geoetl's core
promise ("resumable by default", "a single bad AOI doesn't take the whole
job down") -- if it's wrong, multi-hour HPC runs silently redo work, or
silently drop it, with nothing in the logs to show it happened.

Driven against a FakeImagerySource rather than MPCSource/PlanetBasemapSource
-- no real tiles, no real raster I/O, just enough to exercise pipeline.py's
own logic in isolation.
"""

import json
import os

import geopandas as gpd
import pytest
from shapely.geometry import Point

import geoetl.pipelines.pipeline as pipeline_module
from geoetl.io.base import AOITooLargeError, ImagerySource
from geoetl.pipelines.pipeline import run_pipeline


class FakeImagerySource(ImagerySource):
    """A source whose behavior per-AOI is controlled directly by the test,
    keyed by each AOI's (x, y) centroid since pipeline.py never passes the
    AOI id into the source."""

    def __init__(self, oversized=None, boom=None):
        super().__init__()
        self.oversized = oversized or set()
        self.boom = boom or set()
        self.time_filters_set = []
        self.downloaded = []
        self.clipped = []

    def set_time_filter(self, year=None, steps=None, cadence="monthly"):
        self.time_filters_set.append((year, tuple(steps or []), cadence))

    def find_local_tiles(self, geom, quads_dir):
        return []

    def download_tiles_for_geometry(self, geom, quads_dir):
        key = (geom.centroid.x, geom.centroid.y)
        if key in self.oversized:
            raise AOITooLargeError(f"AOI at {key} is too large to build")
        if key in self.boom:
            raise RuntimeError(f"simulated failure building AOI at {key}")
        self.downloaded.append(key)
        return [f"fake_tile_{key}.tif"]

    def clip_to_geometry(self, geom, out_path, quads_dir):
        with open(out_path, "w") as f:
            f.write("fake chip")
        self.clipped.append(out_path)
        return out_path


@pytest.fixture
def aoi_path(tmp_path):
    def _write(rows):
        gdf = gpd.GeoDataFrame(rows)
        path = tmp_path / "aois.geojson"
        gdf.to_file(path, driver="GeoJSON")
        return str(path)

    return _write


def base_cfg(tmp_path, aoi_file, sub_root=None, sub_root_column=None):
    cfg = {
        "aoi": {"path": aoi_file},
        "output": {"root": str(tmp_path / "out")},
        "params": {
            "label_column": "label",
            "uid_column": "id",
            "dataset_name": "testset",
        },
        "catalog": {"sensor": "irrelevant-mocked-out"},
    }
    if sub_root:
        cfg["output"]["sub_root"] = sub_root
        cfg["output"]["sub_root_column"] = sub_root_column
    return cfg


@pytest.fixture(autouse=True)
def patch_get_source(monkeypatch):
    """Swap in whatever FakeImagerySource the test constructed, in place of
    the real get_source() factory (which would otherwise try to build a
    real MPCSource/PlanetBasemapSource from the config)."""
    holder = {}

    def _fake_get_source(sensor, cfg):
        return holder["source"]

    monkeypatch.setattr(pipeline_module, "get_source", _fake_get_source)

    def _set(source):
        holder["source"] = source

    return _set


def test_resumability_skips_aois_whose_chip_already_exists(tmp_path, aoi_path, patch_get_source):
    aoi_file = aoi_path(
        [
            {"id": "a", "label": 1, "geometry": Point(0, 0)},
            {"id": "b", "label": 0, "geometry": Point(1, 1)},
        ]
    )
    cfg = base_cfg(tmp_path, aoi_file)

    chips_dir = os.path.join(cfg["output"]["root"], "chips")
    os.makedirs(chips_dir, exist_ok=True)
    pre_existing_chip = os.path.join(chips_dir, "a.tif")
    with open(pre_existing_chip, "w") as f:
        f.write("ALREADY THERE")

    source = FakeImagerySource()
    patch_get_source(source)
    run_pipeline(cfg)

    # "a" was skipped before any work happened: not rebuilt, not re-downloaded.
    assert open(pre_existing_chip).read() == "ALREADY THERE"
    assert (0.0, 0.0) not in source.downloaded
    # "b" had no existing chip, so it was actually built.
    assert (1.0, 1.0) in source.downloaded
    assert os.path.exists(os.path.join(chips_dir, "b.tif"))


def test_rerunning_after_a_full_run_rebuilds_nothing(tmp_path, aoi_path, patch_get_source):
    aoi_file = aoi_path([{"id": "a", "label": 1, "geometry": Point(0, 0)}])
    cfg = base_cfg(tmp_path, aoi_file)

    source = FakeImagerySource()
    patch_get_source(source)
    run_pipeline(cfg)
    assert source.downloaded == [(0.0, 0.0)]

    # A second run over the same output dir, same AOIs, must do no work at all.
    run_pipeline(cfg)
    assert source.downloaded == [(0.0, 0.0)]  # unchanged -- not called again


def test_oversized_aoi_is_skipped_and_logged_without_killing_the_run(tmp_path, aoi_path, patch_get_source):
    aoi_file = aoi_path(
        [
            {"id": "too_big", "label": 1, "geometry": Point(5, 5)},
            {"id": "normal", "label": 0, "geometry": Point(1, 1)},
        ]
    )
    cfg = base_cfg(tmp_path, aoi_file)

    source = FakeImagerySource(oversized={(5.0, 5.0)})
    patch_get_source(source)
    run_pipeline(cfg)

    skipped_path = os.path.join(cfg["output"]["root"], "skipped_oversized_aois.txt")
    with open(skipped_path) as f:
        lines = f.readlines()
    assert len(lines) == 1
    assert lines[0].startswith("too_big\t")

    # The oversized AOI never got a chip; the normal one did.
    assert not os.path.exists(os.path.join(cfg["output"]["root"], "chips", "too_big.tif"))
    assert os.path.exists(os.path.join(cfg["output"]["root"], "chips", "normal.tif"))


def test_oversized_skip_is_not_logged_twice_across_resumed_runs(tmp_path, aoi_path, patch_get_source):
    aoi_file = aoi_path([{"id": "too_big", "label": 1, "geometry": Point(5, 5)}])
    cfg = base_cfg(tmp_path, aoi_file)
    skipped_path = os.path.join(cfg["output"]["root"], "skipped_oversized_aois.txt")

    source = FakeImagerySource(oversized={(5.0, 5.0)})
    patch_get_source(source)
    run_pipeline(cfg)
    run_pipeline(cfg)  # resumed run -- AOI is still "too big", still unbuilt

    with open(skipped_path) as f:
        lines = f.readlines()
    assert len(lines) == 1


def test_an_unexpected_error_on_one_aoi_does_not_stop_the_others(tmp_path, aoi_path, patch_get_source):
    aoi_file = aoi_path(
        [
            {"id": "broken", "label": 1, "geometry": Point(9, 9)},
            {"id": "fine", "label": 0, "geometry": Point(1, 1)},
        ]
    )
    cfg = base_cfg(tmp_path, aoi_file)

    source = FakeImagerySource(boom={(9.0, 9.0)})
    patch_get_source(source)
    run_pipeline(cfg)  # must not raise

    assert not os.path.exists(os.path.join(cfg["output"]["root"], "chips", "broken.tif"))
    assert os.path.exists(os.path.join(cfg["output"]["root"], "chips", "fine.tif"))


def test_static_labels_and_coords_are_written_correctly(tmp_path, aoi_path, patch_get_source):
    aoi_file = aoi_path([{"id": "a", "label": "cat", "geometry": Point(3.0, 4.0)}])
    cfg = base_cfg(tmp_path, aoi_file)

    source = FakeImagerySource()
    patch_get_source(source)
    run_pipeline(cfg)

    clip_path = os.path.join(cfg["output"]["root"], "chips", "a.tif")
    labels = json.loads(open(os.path.join(cfg["output"]["root"], "testset_ys.json")).read())
    coords = json.loads(open(os.path.join(cfg["output"]["root"], "testset_coords.json")).read())

    assert labels[clip_path] == "cat"
    assert coords[clip_path] == [3.0, 4.0]


def test_temporal_mode_builds_nested_chip_lists_per_aoi(tmp_path, aoi_path, patch_get_source):
    aoi_file = aoi_path([{"id": "a", "label": "cat", "geometry": Point(0, 0)}])
    cfg = base_cfg(tmp_path, aoi_file)
    cfg["temporal"] = {
        "enabled": True,
        "years": [2020],
        "steps": [1],
        "cadence": "monthly",
    }

    source = FakeImagerySource()
    patch_get_source(source)
    run_pipeline(cfg)

    assert source.time_filters_set == [(2020, (1,), "monthly")]

    labels = json.loads(open(os.path.join(cfg["output"]["root"], "testset_ys.json")).read())
    expected_chip = os.path.join(cfg["output"]["root"], "chips", "2020_m01", "a.tif")
    assert labels["a"]["label"] == "cat"
    assert labels["a"]["chips"] == [expected_chip]
    assert os.path.exists(expected_chip)


def test_sub_root_partitions_chips_and_quads_by_column(tmp_path, aoi_path, patch_get_source):
    aoi_file = aoi_path(
        [
            {"id": "a", "label": 1, "region": "east", "geometry": Point(0, 0)},
            {"id": "b", "label": 1, "region": "west", "geometry": Point(1, 1)},
        ]
    )
    cfg = base_cfg(tmp_path, aoi_file, sub_root=True, sub_root_column="region")

    source = FakeImagerySource()
    patch_get_source(source)
    run_pipeline(cfg)

    assert os.path.exists(os.path.join(cfg["output"]["root"], "chips", "east", "a.tif"))
    assert os.path.exists(os.path.join(cfg["output"]["root"], "chips", "west", "b.tif"))
