"""
geoetl/io/base.py
-----------------
Abstract base class defining the interface every imagery source must
implement, and shared helpers for the local-tile-cache bookkeeping that
`pipeline.py` relies on (checking what's already downloaded for an AOI,
and whether the cached tiles fully cover it).
"""

import json
import os
from abc import ABC, abstractmethod
from typing import List

import numpy as np
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

    def __init__(
        self,
        output_format: str = "tif",
        png_scale_divisor: float = 257,
        png_scale_mode: str = "fixed",
        png_scale_calibration_path: str = None,
    ):
        self.output_format = output_format
        self.png_scale_divisor = png_scale_divisor
        self.png_scale_mode = png_scale_mode
        self.png_scale_calibration_path = png_scale_calibration_path
        self._calibrated_divisor = None

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
        Pixel values are scaled from uint16 to uint8 via one fixed divisor
        applied identically to every chip (self.png_scale_divisor if
        png_scale_mode='fixed', or an auto-calibrated value -- see
        _get_png_divisor) rather than a per-image stretch, so brightness
        stays directly comparable across the whole dataset.
        """
        if self.output_format == "png":
            n_bands = data.sizes.get("band", 1)
            if n_bands > 4:
                raise ValueError(
                    f"Cannot write {n_bands}-band data as PNG (max 4: RGB or "
                    f"RGBA). Reduce this sensor's band list to <=4 bands, or "
                    f"set output.format back to 'tif' for this config."
                )
            divisor = self._get_png_divisor(data)
            # fillna before the int cast -- casting NaN to an integer dtype
            # is undefined (numpy emits "invalid value encountered in cast"
            # and typically yields 0), which would silently turn any masked/
            # nodata pixel black instead of a defined value.
            scaled = (data.fillna(0) // divisor).clip(0, 255).astype("uint8")
            scaled.rio.to_raster(out_path, driver="PNG")
        else:
            data.rio.to_raster(out_path, compress="deflate")

    def _get_png_divisor(self, data) -> float:
        """
        Return the uint16->uint8 divisor to use for this chip.

        png_scale_mode='fixed' (default): just self.png_scale_divisor,
        chosen manually in config.

        png_scale_mode='auto': instead of guessing a divisor, calibrate one
        from the first chip actually written this run -- its 98th
        percentile nonzero pixel value, mapped to 255 -- then reuse that
        exact value for every subsequent chip. Still one fixed value
        applied identically across the whole dataset (brightness stays
        comparable chip-to-chip), just chosen from real data instead of a
        blind default. The calibration is persisted to
        png_scale_calibration_path so a resumed/restarted run reuses the
        same value rather than recalibrating from whatever AOI happens to
        run first.
        """
        if self.png_scale_mode != "auto":
            return self.png_scale_divisor

        if self._calibrated_divisor is not None:
            return self._calibrated_divisor

        if self.png_scale_calibration_path and os.path.isfile(self.png_scale_calibration_path):
            try:
                with open(self.png_scale_calibration_path) as f:
                    self._calibrated_divisor = json.load(f)["png_scale_divisor"]
                print(f"🎨 Reusing persisted PNG scale calibration: divisor={self._calibrated_divisor:.2f}")
                return self._calibrated_divisor
            except Exception:
                pass  # fall through and calibrate fresh from this chip

        valid = data.values[data.values > 0]
        if valid.size == 0:
            # Nothing to calibrate from (e.g. an all-nodata chip) -- fall
            # back to the manual default for this one chip, but don't lock
            # it in as the permanent calibration.
            return self.png_scale_divisor

        p98 = float(np.percentile(valid, 98))
        self._calibrated_divisor = max(p98 / 255.0, 1.0)
        print(
            f"🎨 Calibrated PNG scale from this chip's data: divisor="
            f"{self._calibrated_divisor:.2f} (98th percentile pixel value "
            f"{p98:.0f}). Reused for every chip in this dataset."
        )

        if self.png_scale_calibration_path:
            try:
                os.makedirs(os.path.dirname(self.png_scale_calibration_path), exist_ok=True)
                with open(self.png_scale_calibration_path, "w") as f:
                    json.dump({"png_scale_divisor": self._calibrated_divisor}, f)
            except Exception as e:
                print(f"⚠️ Failed to persist PNG scale calibration: {e}")

        return self._calibrated_divisor

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
