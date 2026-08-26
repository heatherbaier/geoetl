"""
geoetl/alpha_earth.py

Downloads Google AlphaEarth Foundation embedding vectors for point locations,
implementing the same source interface as GEESource and PlanetBasemapSource so
that pipeline.py works without modification.

Because AlphaEarth embeddings are point samples (not image tiles), the
tile-based methods (find_local_tiles, has_all_tiles, download_tiles_for_geometry)
are stubs that satisfy the interface. All real work happens in clip_to_geometry,
which samples the 64-dimensional embedding at the location centroid and writes
a small JSON sidecar in place of a GeoTIFF.

The pipeline will still produce the normal _ys.json and _coords.json outputs,
with clip_path keys pointing to .json files instead of .tif files.

Config example
--------------
aoi:
  path: /home/<asurite>/.../data/phl_schools.shp
catalog:
  sensor: alpha_earth
  collection:                          # always GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL
output:
  root: /scratch/<asurite>/alpha_earth
  sub_root: False
params:
  uid_column: school_id
  label_column: nat_score
  dataset_name: phl_schools
temporal:
  enabled: true
  years:
    - 2022
    - 2023
  steps:
    - 1                                # ignored for alpha_earth — one embedding per year
  cadence: yearly                      # ignored for alpha_earth
  scale: 10                            # AEF native resolution in metres
  use_export: false                    # flip to true for > ~5000 locations
"""

from __future__ import annotations

import os
import json
import numpy as np
from pathlib import Path
from typing import Optional

import ee
from shapely.geometry import mapping

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COLLECTION = "GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL"
EMBEDDING_BANDS = [f"A{str(i).zfill(2)}" for i in range(64)]


# ---------------------------------------------------------------------------
# AlphaEarthSource
# ---------------------------------------------------------------------------


class AlphaEarthSource:
    """
    AlphaEarth embedding source that implements the geoetl pipeline interface.

    Parameters
    ----------
    out_root : str
        Root output directory (passed through from config).
    years : list[int]
        Calendar years to pull embeddings for.
    ee_project : str or None
        GEE project ID. If None, uses default credentials.
    scale : int
        Sampling scale in metres. AEF native resolution is 10 m.
    use_export : bool
        If True, submit GEE Drive export tasks instead of pulling directly.
        Use for large datasets (> ~5000 locations).
    """

    def __init__(
        self,
        out_root: str,
        years: list[int],
        ee_project: Optional[str] = None,
        scale: int = 10,
        use_export: bool = False,
    ):
        self.out_root = out_root
        self.years = list(years)
        self.scale = scale
        self.use_export = use_export
        self.ee_project = ee_project

        # Active year — updated by set_time_filter() as pipeline loops over years
        self._active_year: Optional[int] = years[0] if years else None

        # Cache the EE image per year so we don't re-fetch it on every
        # call to clip_to_geometry
        self._image_cache: dict[int, ee.Image] = {}

        self._init_ee()

    # ------------------------------------------------------------------
    # EE initialisation
    # ------------------------------------------------------------------

    def _init_ee(self):
        try:
            if self.ee_project:
                ee.Initialize(project=self.ee_project)
            else:
                ee.Initialize()
        except Exception:
            ee.Authenticate()
            if self.ee_project:
                ee.Initialize(project=self.ee_project)
            else:
                ee.Initialize()

    # ------------------------------------------------------------------
    # set_time_filter — called by pipeline for each year/step combination
    # ------------------------------------------------------------------

    def set_time_filter(self, year=None, steps=None, cadence="yearly"):
        """
        Update the active year. Steps and cadence are ignored for AlphaEarth
        since the collection is annual-only — one embedding per calendar year.
        """
        if year:
            self._active_year = int(year)
            print(f"🕓 AlphaEarthSource active year set to: {self._active_year}")

    # ------------------------------------------------------------------
    # Pipeline interface — tile methods are stubs
    # ------------------------------------------------------------------

    def find_local_tiles(self, geom, quads_dir: str) -> list:
        """
        AlphaEarth has no local tiles — embeddings are sampled on demand.
        Returns an empty list so pipeline proceeds to download_tiles_for_geometry.
        The skip check in pipeline uses clip_path (.json), not tile presence,
        so returning [] here is safe.
        """
        return []

    def has_all_tiles(self, local_tiles: list, geom) -> bool:
        """
        Always returns False so pipeline always calls download_tiles_for_geometry,
        which is itself a no-op. Real work happens in clip_to_geometry.
        """
        return False

    def download_tiles_for_geometry(self, geom, quads_dir: str) -> list:
        """
        No tiles to download for AlphaEarth. Returns an empty list.
        Pipeline checks this return value for logging only and does not
        block the subsequent call to clip_to_geometry.
        """
        return []

    # ------------------------------------------------------------------
    # clip_to_geometry — all real work happens here
    # ------------------------------------------------------------------

    def clip_to_geometry(self, geom, out_path: str, quads_dir: str) -> str:
        """
        Sample the AlphaEarth embedding at the centroid of geom and write the
        result to out_path as a JSON file (replacing the .tif extension).

        Called by pipeline once per AOI row. The returned path is used as the
        key in _ys.json and _coords.json, so it must be consistent and unique
        per location.

        Parameters
        ----------
        geom : shapely geometry
            The AOI geometry (polygon or point). Reduced to centroid internally.
        out_path : str
            Path pipeline expects the output at. We swap .tif → .json.
        quads_dir : str
            Unused for AlphaEarth but required by the interface.

        Returns
        -------
        str
            Path to the written JSON embedding file.
        """
        # Redirect .tif → .json since we write embeddings, not rasters
        out_path = str(out_path).replace(".tif", ".json")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)

        if os.path.exists(out_path):
            print(f"  ✅ Embedding already cached: {os.path.basename(out_path)}")
            return out_path

        if self._active_year is None:
            raise RuntimeError(
                "No active year set. Call set_time_filter(year=...) first, "
                "or ensure temporal.years is set in your config."
            )

        # Reduce polygon to centroid
        centroid = geom.centroid if geom.geom_type != "Point" else geom

        image = ee.ImageCollection(COLLECTION).filterDate(f"{self._active_year}-01-01", f"{self._active_year+1}-01-01").filterBounds(ee.Geometry.Point([centroid.x, centroid.y])).first()

        embedding = image.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=ee.Geometry.Point([centroid.x, centroid.y]).buffer(20),
            scale = self.scale,
            maxPixels=1000,
        ).getInfo()

        embedding = list(embedding.values())

        # # Fetch (or retrieve cached) EE image for this year
        # image = self._get_image(self._active_year)

        # # Sample embedding at centroid
        # embedding = self._sample_point(image, centroid)

        if embedding is None:
            raise RuntimeError(
                f"GEE returned no data for point ({centroid.x:.4f}, {centroid.y:.4f}) "
                f"in year {self._active_year}. Check that the location falls within "
                f"AlphaEarth coverage (land surface, ±82°)."
            )

        # Write JSON sidecar
        result = {
            "year": self._active_year,
            "centroid_lon": centroid.x,
            "centroid_lat": centroid.y,
            "collection": COLLECTION,
            "scale_m": self.scale,
            "embedding": embedding,   # {A00: float, A01: float, ..., A63: float}
        }
        with open(out_path, "w") as f:
            json.dump(result, f)

        print(f"  💾 Embedding saved: {os.path.basename(out_path)}")
        return out_path

    # ------------------------------------------------------------------
    # Internal GEE helpers
    # ------------------------------------------------------------------

    def _get_image(self, year: int) -> ee.Image:
        """Return the AEF annual embedding image for year, with per-run caching."""
        if year not in self._image_cache:
            start = f"{year}-01-01"
            end = f"{year + 1}-01-01"
            collection = ee.ImageCollection(COLLECTION).filterDate(start, end)
            size = collection.size().getInfo()
            if size == 0:
                raise RuntimeError(
                    f"No AlphaEarth embeddings found for year {year}. "
                    f"Available years are 2017–2024."
                )
            self._image_cache[year] = collection.first()
            print(f"  🌐 Loaded AEF image for {year}")
        return self._image_cache[year]

    def _sample_point(self, image: ee.Image, centroid) -> Optional[dict]:
        """
        Sample all 64 embedding bands at a single centroid point using
        reduceRegion, which is more robust than .sample() for exact point
        extraction and handles tile boundaries / masked pixels correctly.

        Returns a dict {A00: float, ..., A63: float} or None if no data.
        """
        point = ee.Geometry.Point([centroid.x, centroid.y])
        result = (
            image.select(EMBEDDING_BANDS)
            .reduceRegion(
                reducer=ee.Reducer.first(),
                geometry=point,
                scale=self.scale,
                maxPixels=1000,
            )
            .getInfo()
        )
        # result is a flat dict {A00: float, ...} or {A00: None, ...} if masked
        if result is None:
            return None
        # Check that at least some bands have actual values
        if all(v is None for v in result.values()):
            return None
        return result
