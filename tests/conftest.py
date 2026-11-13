"""Shared fixtures for the geoetl test suite.

Nothing here hits a real network or a real imagery provider -- see
TESTING_PLAN.md for why (CI must stay fast and deterministic, and Planet
needs a real API key we won't have in CI anyway).
"""

import numpy as np
import pytest
import rioxarray  # noqa: F401 -- registers the .rio accessor on DataArray
import xarray as xr

from geoetl.io.base import ImagerySource


def make_raster_dataarray(
    bounds=(0.0, 0.0, 1.0, 1.0),
    shape=(2, 10, 10),
    crs="EPSG:4326",
    dtype="uint16",
    fill=1000,
):
    """Build a tiny in-memory, georeferenced DataArray -- a stand-in for a
    real satellite tile/composite, cheap enough to construct in every test
    that needs actual pixel data rather than a real download."""
    nbands, ny, nx = shape
    minx, miny, maxx, maxy = bounds
    xs = np.linspace(minx, maxx, nx, endpoint=False) + (maxx - minx) / nx / 2
    ys = np.linspace(maxy, miny, ny, endpoint=False) - (maxy - miny) / ny / 2
    data = np.full((nbands, ny, nx), fill, dtype=dtype)
    da = xr.DataArray(
        data,
        dims=("band", "y", "x"),
        coords={"band": np.arange(1, nbands + 1), "y": ys, "x": xs},
    )
    return da.rio.write_crs(crs)


@pytest.fixture
def make_raster(tmp_path):
    """Factory fixture: write a tiny synthetic GeoTIFF to disk, return its path."""

    def _write(name="tile.tif", **kwargs):
        da = make_raster_dataarray(**kwargs)
        path = tmp_path / name
        da.rio.to_raster(str(path))
        return str(path)

    return _write


class _ConcreteSource(ImagerySource):
    """The smallest possible concrete ImagerySource, for exercising the
    shared, non-abstract logic in ImagerySource itself (write_chip,
    has_all_tiles, _get_png_divisor, ...) without pulling in a real
    provider (which would mean real network calls -- see MPCSource.__init__
    opening a live STAC catalog connection)."""

    def set_time_filter(self, year=None, steps=None, cadence="monthly"):
        pass

    def find_local_tiles(self, geom, quads_dir):
        return []

    def download_tiles_for_geometry(self, geom, quads_dir):
        return []

    def clip_to_geometry(self, geom, out_path, quads_dir):
        return out_path


@pytest.fixture
def concrete_source():
    def _make(**kwargs):
        return _ConcreteSource(**kwargs)

    return _make
