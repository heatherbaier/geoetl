"""
geoetl/io/base.py
-----------------
Abstract base class defining the interface every imagery source must
implement, and shared helpers for the local-tile-cache bookkeeping that
`pipeline.py` relies on (checking what's already downloaded for an AOI,
and whether the cached tiles fully cover it).
"""

import os
from abc import ABC, abstractmethod
from typing import List

import rioxarray as riox
from shapely.geometry import box
from shapely.ops import unary_union


class AOITooLargeError(RuntimeError):
    """Raised when an AOI's composite would exceed a source's size cap.

    A distinct type (rather than a plain RuntimeError) so pipeline.py can
    tell "this AOI was deliberately skipped for being oversized" apart from
    other failures (network errors, no imagery found, etc.) and log it
    separately instead of lumping it in with ordinary per-AOI errors.
    """


class ImagerySource(ABC):
    """
    Common interface for all imagery sources (MPC, Planet, ...).

    `pipeline.py` drives any source through exactly these five methods, in
    this order, once per AOI:

        find_local_tiles      -> what's already cached for this AOI?
        has_all_tiles         -> is that cache sufficient?
        download_tiles_for_geometry  -> if not, fetch what's missing
        clip_to_geometry      -> merge cached tiles and clip to the AOI

    `set_time_filter` is called separately, once per (year, step), only
    when `temporal.enabled` is set in the config.
    """

    def __init__(self, output_format: str = "tif", png_scale_divisor: float = 257):
        self.output_format = output_format
        self.png_scale_divisor = png_scale_divisor

    @abstractmethod
    def set_time_filter(self, year=None, steps=None, cadence="monthly"):
        """Update the source's active time window for subsequent composites."""
        raise NotImplementedError

    @abstractmethod
    def find_local_tiles(self, geom, quads_dir) -> List[str]:
        """Return cached tile paths in quads_dir relevant to geom."""
        raise NotImplementedError

    @abstractmethod
    def download_tiles_for_geometry(self, geom, quads_dir) -> List[str]:
        """Fetch and cache whatever tiles are needed to cover geom. Return their paths."""
        raise NotImplementedError

    @abstractmethod
    def clip_to_geometry(self, geom, out_path, quads_dir) -> str:
        """Merge the relevant cached tiles and write the AOI clip to out_path."""
        raise NotImplementedError

    # ---- Shared helpers -----------------------------------------------
    #
    # has_all_tiles() is identical for every source: it just checks whether
    # the union of already-found tile bounds covers the AOI. Subclasses get
    # it for free instead of reimplementing it.
    #
    # scan_local_tiles() is a reusable "list every .tif in quads_dir whose
    # bounds intersect geom" helper for sources (like Planet) that cache
    # multiple grid tiles per directory. Sources that cache one
    # deterministically-named file per AOI (like MPCSource) can look the
    # file up directly instead and skip this scan entirely.

    def has_all_tiles(self, local_tiles: List[str], geom) -> bool:
        """True iff the union of local_tiles fully covers geom."""
        if not local_tiles:
            return False
        try:
            tile_bounds = []
            for tile_path in local_tiles:
                with riox.open_rasterio(tile_path) as r:
                    tile_bounds.append(box(*r.rio.bounds()))
            merged = unary_union(tile_bounds)
            return merged.contains(geom)
        except Exception as e:
            print(f"⚠️ Error checking tile coverage: {e}")
            return False

    @staticmethod
    def scan_local_tiles(quads_dir: str, geom) -> List[str]:
        """Return every .tif in quads_dir whose bounds intersect geom."""
        local_tiles: List[str] = []
        if not os.path.isdir(quads_dir):
            return local_tiles

        for fname in os.listdir(quads_dir):
            if not fname.endswith(".tif"):
                continue
            tile_path = os.path.join(quads_dir, fname)
            try:
                with riox.open_rasterio(tile_path) as r:
                    tile_bounds = box(*r.rio.bounds())
                if tile_bounds.intersects(geom):
                    local_tiles.append(tile_path)
            except Exception:
                # Skip a file we can't open as a raster.
                continue
        return local_tiles

    def write_chip(self, data, out_path: str):
        """
        Write a clipped chip DataArray to out_path as either GeoTIFF or PNG,
        per self.output_format. The only thing that decides the format is
        this method -- sources just call it instead of hand-rolling
        rio.to_raster(), so every source's PNG behavior stays identical.

        PNG output: GDAL's PNG driver caps out at 4 bands (RGB/RGBA), so a
        sensor configured with more bands than that raises ValueError rather
        than silently dropping bands -- band selection for PNG export is a
        deliberate per-sensor config choice, not something to guess at.
        Pixel values are scaled from uint16 to uint8 via a fixed divisor
        (self.png_scale_divisor, default 257 -- the full uint16 range mapped
        onto 0-255) rather than a per-image stretch, so brightness is
        directly comparable across every chip in the dataset. Reflectance
        values are usually a small fraction of the uint16 range, so images
        may look dark at the default divisor -- tune png_scale_divisor in
        the sensor config to match your actual data's value range.
        """
        if self.output_format == "png":
            n_bands = data.sizes.get("band", 1)
            if n_bands > 4:
                raise ValueError(
                    f"Cannot write {n_bands}-band data as PNG (max 4: RGB or "
                    f"RGBA). Reduce this sensor's band list to <=4 bands, or "
                    f"set output.format back to 'tif' for this config."
                )
            scaled = (data // self.png_scale_divisor).clip(0, 255).astype("uint8")
            scaled.rio.to_raster(out_path, driver="PNG")
        else:
            data.rio.to_raster(out_path, compress="deflate")

    @staticmethod
    def is_valid_raster(path: str) -> bool:
        """
        True iff path exists and can actually be opened as a raster.

        A "cache exists" check must confirm this, not just os.path.isfile():
        a process killed mid-write (e.g. an earlier OOM during
        `.rio.to_raster()`) leaves a truncated file at the expected cache
        path, which os.path.isfile() alone would treat as valid forever,
        permanently failing that AOI on every future run instead of
        rebuilding it.
        """
        if not os.path.isfile(path):
            return False
        try:
            with riox.open_rasterio(path):
                pass
            return True
        except Exception:
            return False
