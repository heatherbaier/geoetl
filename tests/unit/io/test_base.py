"""Tests for the shared logic in geoetl/io/base.py -- used by every
imagery source, so a bug here silently corrupts every dataset built with
any source (see TESTING_PLAN.md's scoping table)."""

import json

import numpy as np
import pytest
import rioxarray as riox
from shapely.geometry import box

from geoetl.io.base import ImagerySource
from tests.conftest import make_raster_dataarray


# ---------------------------------------------------------------------------
# is_valid_raster
# ---------------------------------------------------------------------------

def test_is_valid_raster_true_for_a_real_tif(make_raster):
    path = make_raster("good.tif")
    assert ImagerySource.is_valid_raster(path) is True


def test_is_valid_raster_false_for_a_missing_file(tmp_path):
    assert ImagerySource.is_valid_raster(str(tmp_path / "nope.tif")) is False


def test_is_valid_raster_false_for_a_truncated_file(tmp_path):
    # Simulates a process killed mid-write (e.g. an OOM during
    # .rio.to_raster()) leaving a partial file at the expected cache path --
    # this is exactly the case ImagerySource.is_valid_raster exists to catch
    # instead of treating a truncated file as a permanently-valid cache hit.
    bad = tmp_path / "truncated.tif"
    bad.write_bytes(b"not actually a tiff")
    assert ImagerySource.is_valid_raster(str(bad)) is False


# ---------------------------------------------------------------------------
# scan_local_tiles
# ---------------------------------------------------------------------------

def test_scan_local_tiles_returns_empty_list_for_missing_dir(tmp_path):
    assert ImagerySource.scan_local_tiles(str(tmp_path / "missing"), box(0, 0, 1, 1)) == []


def test_scan_local_tiles_only_returns_intersecting_tiles(make_raster, tmp_path):
    inside = make_raster("inside.tif", bounds=(0, 0, 1, 1))
    outside = make_raster("outside.tif", bounds=(10, 10, 11, 11))

    found = ImagerySource.scan_local_tiles(str(tmp_path), box(0.25, 0.25, 0.75, 0.75))

    assert inside in found
    assert outside not in found


def test_scan_local_tiles_skips_unreadable_tif(make_raster, tmp_path):
    make_raster("good.tif", bounds=(0, 0, 1, 1))
    (tmp_path / "corrupt.tif").write_bytes(b"garbage")

    # Should not raise, and the unreadable file should simply be excluded.
    found = ImagerySource.scan_local_tiles(str(tmp_path), box(0, 0, 1, 1))
    assert all("corrupt" not in f for f in found)


# ---------------------------------------------------------------------------
# has_all_tiles
# ---------------------------------------------------------------------------

def test_has_all_tiles_false_for_empty_list(concrete_source):
    source = concrete_source()
    assert source.has_all_tiles([], box(0, 0, 1, 1)) is False


def test_has_all_tiles_true_when_tile_fully_covers_geom(concrete_source, make_raster):
    source = concrete_source()
    tile = make_raster("covers.tif", bounds=(0, 0, 10, 10))
    assert source.has_all_tiles([tile], box(2, 2, 3, 3)) is True


def test_has_all_tiles_false_when_tile_only_partially_covers_geom(concrete_source, make_raster):
    source = concrete_source()
    tile = make_raster("partial.tif", bounds=(0, 0, 1, 1))
    assert source.has_all_tiles([tile], box(0.5, 0.5, 5, 5)) is False


# ---------------------------------------------------------------------------
# write_chip -- PNG band cap
# ---------------------------------------------------------------------------

def test_write_chip_png_rejects_more_than_four_bands(concrete_source, tmp_path):
    source = concrete_source(output_format="png")
    data = make_raster_dataarray(shape=(5, 4, 4))

    with pytest.raises(ValueError, match="Cannot write 5-band"):
        source.write_chip(data, str(tmp_path / "out.png"))


# ---------------------------------------------------------------------------
# write_chip -- PNG scaling + the black-PNG regression
# ---------------------------------------------------------------------------
# geoetl's history already includes a real bug here: rio.clip() leaves NaN
# pixels outside the AOI polygon, and casting NaN to an integer dtype is
# undefined (numpy silently turns it into 0, i.e. black) *unless* fillna(0)
# runs first. This locks that fix in.

def test_write_chip_png_scales_values_and_zeroes_nodata(concrete_source, tmp_path):
    source = concrete_source(output_format="png", png_scale_divisor=257)
    data = make_raster_dataarray(shape=(3, 2, 2), dtype="float64", fill=514.0)
    # Simulate rio.clip()'s NaN-outside-the-polygon behavior on one pixel.
    data[0, 0, 0] = np.nan

    out_path = tmp_path / "out.png"
    source.write_chip(data, str(out_path))

    with riox.open_rasterio(str(out_path)) as written:
        arr = written.values
        assert arr[0, 0, 0] == 0  # the NaN pixel -- not black-by-accident, zero-by-design
        assert arr[0, 0, 1] == 2  # 514 // 257 == 2, every other pixel scaled normally
        assert arr.dtype == np.uint8


def test_write_chip_tif_keeps_float_values_untouched(concrete_source, tmp_path):
    source = concrete_source(output_format="tif")
    data = make_raster_dataarray(shape=(2, 2, 2), dtype="uint16", fill=1234)

    out_path = tmp_path / "out.tif"
    source.write_chip(data, str(out_path))

    with riox.open_rasterio(str(out_path)) as written:
        assert (written.values == 1234).all()


# ---------------------------------------------------------------------------
# _get_png_divisor -- fixed vs. auto calibration
# ---------------------------------------------------------------------------

def test_png_divisor_fixed_mode_returns_the_configured_value(concrete_source):
    source = concrete_source(png_scale_mode="fixed", png_scale_divisor=99)
    data = make_raster_dataarray(fill=1000)
    assert source._get_png_divisor(data) == 99


def test_png_divisor_auto_mode_calibrates_from_data(concrete_source):
    source = concrete_source(png_scale_mode="auto")
    data = make_raster_dataarray(shape=(1, 10, 10), dtype="float64", fill=0)
    # 99 real values plus the fill; p98 of a mostly-uniform-with-outlier
    # array is easiest to reason about with a simple ramp.
    data.values[0] = np.arange(100).reshape(10, 10)

    divisor = source._get_png_divisor(data)

    expected = max(float(np.percentile(np.arange(1, 100), 98)) / 255.0, 1.0)
    assert divisor == pytest.approx(expected)


def test_png_divisor_auto_mode_is_fixed_after_first_calibration(concrete_source):
    # Once calibrated from the first chip, every later chip in the run must
    # reuse that exact value rather than recalibrating per-chip -- otherwise
    # brightness wouldn't be comparable across the dataset.
    source = concrete_source(png_scale_mode="auto")
    first = make_raster_dataarray(shape=(1, 5, 5), dtype="float64", fill=0)
    first.values[0, 0, 0] = 500
    first_divisor = source._get_png_divisor(first)

    second = make_raster_dataarray(shape=(1, 5, 5), dtype="float64", fill=0)
    second.values[0, 0, 0] = 999999  # would calibrate very differently if reused
    second_divisor = source._get_png_divisor(second)

    assert second_divisor == first_divisor == pytest.approx(first_divisor)


def test_png_divisor_auto_mode_persists_and_is_reused_across_instances(concrete_source, tmp_path):
    # A resumed run constructs a new source instance -- it must reuse the
    # calibration from the interrupted run's first chip, not recalibrate
    # from whatever AOI happens to run first this time.
    calib_path = str(tmp_path / "calib.json")
    source_a = concrete_source(png_scale_mode="auto", png_scale_calibration_path=calib_path)
    data = make_raster_dataarray(shape=(1, 5, 5), dtype="float64", fill=0)
    data.values[0, 0, 0] = 500
    divisor_a = source_a._get_png_divisor(data)

    assert json.loads(open(calib_path).read())["png_scale_divisor"] == pytest.approx(divisor_a)

    source_b = concrete_source(png_scale_mode="auto", png_scale_calibration_path=calib_path)
    # Even with wildly different data, source_b must pick up the persisted
    # value instead of recalibrating.
    unrelated_data = make_raster_dataarray(shape=(1, 5, 5), dtype="float64", fill=0)
    unrelated_data.values[0, 0, 0] = 1
    divisor_b = source_b._get_png_divisor(unrelated_data)

    assert divisor_b == pytest.approx(divisor_a)


def test_png_divisor_auto_mode_falls_back_when_chip_is_all_nodata(concrete_source):
    # An all-zero/all-nodata chip has nothing to calibrate from -- fall back
    # to the manual default for this one chip without locking it in.
    source = concrete_source(png_scale_mode="auto", png_scale_divisor=257)
    empty = make_raster_dataarray(shape=(1, 3, 3), dtype="float64", fill=0)

    assert source._get_png_divisor(empty) == 257
    assert source._calibrated_divisor is None  # not locked in
