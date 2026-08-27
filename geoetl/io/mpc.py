"""
Microsoft Planetary Computer (MPC) imagery source for geoetl.

Implements the ImagerySource interface (geoetl/io/base.py):

    - set_time_filter(year=, steps=, cadence=)
    - find_local_tiles(geom, quads_dir)
    - has_all_tiles(local_tiles, geom)          [inherited from ImagerySource]
    - download_tiles_for_geometry(geom, quads_dir)
    - clip_to_geometry(geom, out_path, quads_dir)

This produces one composite GeoTIFF per AOI per time slice (not fixed-grid
quads). Composites are built client-side by querying the MPC STAC API for
items overlapping the AOI within the time window, masking clouds, and
taking a per-pixel median across the stack.

Supported sensors: 'sentinel2', 'landsat8', 'landsat5'.

Auth: anonymous works for moderate volumes. For higher throughput set the
PC_SDK_SUBSCRIPTION_KEY environment variable to your MPC API key.
"""

import os

# Bound GDAL's caching before any raster I/O happens (must precede rasterio/
# rioxarray import). Each AOI's STAC search re-signs asset URLs with a fresh
# SAS token, so GDAL's per-URL /vsicurl/ cache never gets a hit across AOIs
# in a batch job like this -- left unbounded, both it and the raster block
# cache grow for the life of the process purely as accumulated waste.
# setdefault() so an operator's own environment settings (e.g. in a SLURM
# job script) still take priority.
os.environ.setdefault("GDAL_CACHEMAX", "512")  # MB, raster block cache
os.environ.setdefault("CPL_VSIL_CURL_CACHE_SIZE", "268435456")  # 256MB, /vsicurl/ cache
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")

import calendar
from typing import List, Optional

import geopandas as gpd
import numpy as np
import planetary_computer as pc
import pystac_client
import rioxarray as riox
from odc.stac import stac_load
from rioxarray.merge import merge_arrays
from shapely.geometry import box, mapping

from geoetl.io.base import AOITooLargeError, ImagerySource

MPC_STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"


# ---------------------------------------------------------------------------
# Sensor configs — mirrors the GEESource SENSOR_CONFIGS dict structure
# ---------------------------------------------------------------------------
# Bands are listed in the order they will be written to the output GeoTIFF
# (matches GEESource convention). Common-name and asset-name fields let us
# query MPC by canonical asset name and also produce a friendly band order.
SENSOR_CONFIGS = {
    "sentinel2": {
        "collection": "sentinel-2-l2a",
        # B4=red, B3=green, B2=blue (matches GEESource's 3-band RGB output).
        # Extend this list to pull more bands.
        "bands": ["B04", "B03", "B02"],
        "scale": 10,                # metres per pixel
        "scale_factor": 0.0001,     # L2A DN -> reflectance
        "offset": 0.0,
        "cloud_property": "eo:cloud_cover",
        "scl_band": "SCL",          # used for cloud masking
    },
    "landsat8": {
        "collection": "landsat-c2-l2",
        # Asset names on MPC for Landsat C2 L2 are lowercase (red, green, blue, ...)
        # GEESource lists 6 bands; we mirror that ordering.
        "bands": ["swir22", "swir16", "nir08", "red", "green", "blue"],
        "scale": 30,
        "scale_factor": 0.0000275,
        "offset": -0.2,
        "cloud_property": "eo:cloud_cover",
        "qa_band": "qa_pixel",
        "platform_filter": ["landsat-8", "landsat-9"],   # use both for L8 era
    },
    "landsat5": {
        "collection": "landsat-c2-l2",
        # L5 TM has 7 bands; match GEESource's L5 ordering (SR_B7..SR_B1)
        "bands": ["swir22", "nir08", "red", "green", "blue", "coastal"],
        "scale": 30,
        "scale_factor": 0.0000275,
        "offset": -0.2,
        "cloud_property": "eo:cloud_cover",
        "qa_band": "qa_pixel",
        "platform_filter": ["landsat-5"],
    },
}


# Sentinel-2 L2A baseline change cutoff. Items processed on/after this date
# have a +1000 offset applied by ESA that we need to remove to match the
# pre-baseline values (and to match GEE's harmonized collection).
S2_HARMONIZATION_CUTOFF = "2022-01-25"
S2_HARMONIZATION_OFFSET = 1000


class MPCSource(ImagerySource):
    """
    Microsoft Planetary Computer source.

    Parameters
    ----------
    out_root : str
        Root directory for output chips/quads (unused internally — kept for
        signature compatibility with PlanetBasemapSource).
    sensor : str
        One of 'sentinel2', 'landsat8', 'landsat5'.
    year : int
        Year for the temporal composite.
    month : int or None
        Month (1-12) for a monthly composite. If None, uses full-year median.
    cloud_cover_max : float
        Maximum eo:cloud_cover (percent, 0-100) for scenes to include.
    start_date, end_date : str or None
        Explicit ISO date overrides (YYYY-MM-DD). Take priority over year/month.
    api_key : str or None
        MPC subscription key. Falls back to PC_SDK_SUBSCRIPTION_KEY env var.
    output_format : str
        'tif' (default) or 'png' for the final per-AOI chip. Cached
        composites in quads_dir always stay GeoTIFF regardless -- see
        ImagerySource.write_chip.
    png_scale_divisor : float
        Only used when output_format='png'. See ImagerySource.write_chip.
    """

    def __init__(self,
                 out_root,
                 sensor="sentinel2",
                 year=2020,
                 month=None,
                 cloud_cover_max=20,
                 start_date=None,
                 end_date=None,
                 api_key=None,
                 mask_clouds=True,
                 output_format="tif",
                 png_scale_divisor=257):
        super().__init__(output_format=output_format, png_scale_divisor=png_scale_divisor)

        self.mask_clouds = mask_clouds
        self.out_root = out_root
        self.sensor = sensor.lower()
        self.year = year
        self.month = month
        self.cloud_cover_max = cloud_cover_max
        self.start_date = start_date
        self.end_date = end_date

        if self.sensor not in SENSOR_CONFIGS:
            raise ValueError(
                f"Unknown sensor '{sensor}'. "
                f"Choose from: {list(SENSOR_CONFIGS.keys())}"
            )
        self.cfg = SENSOR_CONFIGS[self.sensor]
        
        # Honour explicit api_key argument, else env var, else anonymous.
        api_key = api_key or os.environ.get("PC_SDK_SUBSCRIPTION_KEY")
        if api_key:
            pc.set_subscription_key(api_key)
        
        # Open the STAC catalog with automatic URL signing.
        self._catalog = pystac_client.Client.open(
            MPC_STAC_URL,
            modifier=pc.sign_inplace,
        )

    # ------------------------------------------------------------------
    # set_time_filter — same signature as GEESource / PlanetBasemapSource
    # ------------------------------------------------------------------
    def set_time_filter(self, year=None, steps=None, cadence="monthly"):
        """
        Update the temporal window for subsequent composites.
        Called by pipeline.py once per (year, step) when temporal mode
        is enabled.
        """
        if not year:
            return
        if not steps or len(steps) == 0:
            raise ValueError("At least one temporal step must be provided.")

        self.year = year
        cadence = cadence.lower().strip()
        step = steps[0]

        if cadence == "monthly":
            self.month = int(step)
        elif cadence == "quarterly":
            # Map quarter -> start month (Q1->Jan, Q2->Apr, Q3->Jul, Q4->Oct)
            self.month = {1: 1, 2: 4, 3: 7, 4: 10}[int(step)]
        else:
            raise ValueError(f"Unsupported cadence: {cadence}")

        # Reset explicit date overrides; year/month now drives the window.
        self.start_date = None
        self.end_date = None

        print(
            f"🕓 MPCSource time filter set to: "
            f"{self.year}-{self.month} ({cadence})"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _build_date_range(self):
        """Return (start, end) ISO strings for the current time filter."""
        if self.start_date and self.end_date:
            return self.start_date, self.end_date

        year = self.year
        month = self.month
        if month is None:
            return f"{year}-01-01", f"{year}-12-31"

        last_day = calendar.monthrange(year, month)[1]
        start = f"{year}-{str(month).zfill(2)}-01"
        end = f"{year}-{str(month).zfill(2)}-{last_day}"
        return start, end

    def _tile_path(self, geom):
        """
        Deterministic per-AOI composite filename. Mirrors GEESource layout
        and additionally includes cloud_cover_max so cache entries built
        with different thresholds don't collide.
        """
        c = geom.centroid
        cc = int(round(self.cloud_cover_max))
        tag = (
            f"mpc_{self.sensor}_{self.year}_{self.month}_"
            f"cc{cc}_{c.x:.4f}_{c.y:.4f}"
        )
        tag = tag.replace("-", "n").replace(".", "p")
        return tag + ".tif"

    def _search_items(self, geom):
        """STAC search for items overlapping geom in the current time window."""
        start, end = self._build_date_range()

        query = {self.cfg["cloud_property"]: {"lt": self.cloud_cover_max}}
        # Landsat: restrict to the platforms appropriate for this 'sensor'.
        if "platform_filter" in self.cfg:
            query["platform"] = {"in": self.cfg["platform_filter"]}

        search = self._catalog.search(
            collections=[self.cfg["collection"]],
            intersects=mapping(geom),
            datetime=f"{start}/{end}",
            query=query,
        )
        items = list(search.items())
        print(
            f"📦 {self.cfg['collection']} items for {start}..{end} "
            f"(cc<{self.cloud_cover_max}): {len(items)}"
        )
        return items

    def _mask_and_scale_s2(self, data):
        """
        Apply SCL cloud mask and Sentinel-2 scale factor / harmonization.
        Mirrors GEESource._build_composite for Sentinel-2.

        `data` is an xarray Dataset from odc.stac.stac_load with one
        variable per band including 'SCL'.
        """
        scl = data["SCL"]
        # SCL classes to drop: 3=shadow, 8=cloud medium, 9=cloud high, 10=cirrus
        # (matches GEESource S2 mask exactly)
        valid = ~scl.isin([3, 8, 9, 10])

        # Harmonize: subtract 1000 from post-baseline items.
        # 'time' is the per-item acquisition time on the dataset.
        if "time" in data.dims:
            cutoff = np.datetime64(S2_HARMONIZATION_CUTOFF)
            post = data["time"].values >= cutoff
            if post.any():
                for b in self.cfg["bands"]:
                    arr = data[b]
                    # Only subtract where the band has nonzero data (preserve nodata=0).
                    adjusted = arr.where(
                        ~((arr.time.values >= cutoff)[:, None, None] & (arr > 0)),
                        arr - S2_HARMONIZATION_OFFSET,
                    )
                    data[b] = adjusted

        if not self.mask_clouds:
            return [data[b] for b in self.cfg["bands"]]                    

        # Apply mask, then per-pixel median across time.
        bands = []
        for b in self.cfg["bands"]:
            masked = data[b].where(valid)
            bands.append(masked)

        return bands

    def _mask_and_scale_landsat(self, data):
        """
        Apply QA_PIXEL cloud mask for Landsat C2 L2.
        Bits 3 (cloud shadow) and 5 (cloud) — matches GEESource L8 mask.
        """
        if not self.mask_clouds:
            return [data[b] for b in self.cfg["bands"]]

        
        qa = data[self.cfg["qa_band"]]
        # Bit 3 = cloud shadow; bit 5 = cloud (high confidence).
        cloud_shadow = (qa.astype("uint16") & (1 << 3)) > 0
        cloud = (qa.astype("uint16") & (1 << 5)) > 0
        valid = ~(cloud_shadow | cloud)

        bands = []
        for b in self.cfg["bands"]:
            masked = data[b].where(valid)
            bands.append(masked)
        return bands


    def _utm_crs_for(self, geom):
            """
            Return the EPSG code (as a string like 'EPSG:32617') for the UTM
            zone that best contains the centroid of `geom`. Assumes geom is
            in WGS84 lat/lon.
            """
            c = geom.centroid
            lon, lat = c.x, c.y
            zone = int((lon + 180) // 6) + 1
            # 326xx = northern hemisphere, 327xx = southern
            if lat >= 0:
                epsg = 32600 + zone
            else:
                epsg = 32700 + zone
            return f"EPSG:{epsg}"
        

    def _build_composite(self, geom):
        """
        Build a cloud-masked median composite over geom in the current
        time window, write as uint16 reflectance × 10000 to match
        GEESource output format.
        """
        items = self._search_items(geom)

        if not items:
            raise RuntimeError(
                f"No items found in {self.cfg['collection']} for the current "
                f"time window over the AOI (cc<{self.cloud_cover_max})."
            )

        # Decide which assets to load: bands + the mask band.
        if self.sensor == "sentinel2":
            mask_assets = [self.cfg["scl_band"]]
        else:
            mask_assets = [self.cfg["qa_band"]]
        assets = list(self.cfg["bands"]) + mask_assets

        # Load lazily with odc.stac. Use the AOI bounds for the read window
        # so we don't pull entire MGRS tiles.
        # bbox = geom.bounds
        # data = stac_load(
        #     items,
        #     bands=assets,
        #     bbox=bbox,
        #     resolution=self.cfg["scale"],
        #     crs="EPSG:4326",
        #     chunks={},   # lazy; computed below when we take the median
        # )

        # Pick a UTM CRS appropriate to the AOI so 'scale' (in metres) is
        # interpreted correctly. Loading in lat/lon would make odc.stac
        # treat resolution as degrees, producing near-empty single-pixel
        # composites for anything smaller than a hemisphere.
        utm_crs = self._utm_crs_for(geom)

        # Bound the spatial chunk size instead of loading the AOI as one
        # single dask chunk (chunks={}). Most AOIs are small enough that
        # this makes no difference -- they still end up as one chunk. But
        # AZ (and other statewide) tract shapefiles mix small urban tracts
        # with enormous rural ones (e.g. a Coconino County tract can be
        # orders of magnitude larger in area than a Phoenix one), and pixel
        # count scales with AOI area at a fixed resolution regardless of
        # item count. With chunks={}, one huge tract forces dask to hold
        # every item x every band x the *entire* tract's pixel grid in
        # memory at once when the median is computed -- effectively eager
        # loading. Bounded chunks let rioxarray's to_raster() (which writes
        # dask-backed arrays block-by-block) compute and write the median
        # one spatial tile at a time, releasing each before the next, so
        # peak memory is bounded by chunk size instead of tract size.
        chunk_px = self.cfg.get("chunk_px", 1024)
        data = stac_load(
            items,
            bands=assets,
            geopolygon=geom,          # AOI, in WGS84
            resolution=self.cfg["scale"],
            crs=utm_crs,              # metres per pixel
            chunks={"x": chunk_px, "y": chunk_px},
        )

        # Diagnostic: confirm the read window's actual size and how many
        # spatial chunks it was split into -- tens/hundreds of pixels in a
        # single chunk for a typical tract, versus a huge tract that now
        # spans many chunks instead of one massive one.
        ny = data.sizes.get("y", 0)
        nx = data.sizes.get("x", 0)
        n_chunks = max(1, -(-nx // chunk_px)) * max(1, -(-ny // chunk_px)) if (nx and ny) else 1
        est_mb = (len(items) * len(assets) * ny * nx * 4) / (1024 * 1024)
        print(
            f"🧮 stac_load window: {nx}x{ny} px in {n_chunks} chunk(s), "
            f"{len(items)} items x {len(assets)} bands -> "
            f"~{est_mb:.0f} MB uncompressed total, "
            f"~{est_mb / n_chunks:.0f} MB per chunk"
        )

        # Hard safety cap. AOI shapefiles covering a whole state mix normal
        # tracts with rare, enormous outliers (e.g. a rural Coconino County
        # tract can be ~100x wider than a Phoenix one) -- chunking bounds
        # per-tile memory, but an outlier this extreme can still overwhelm
        # the job through sheer chunk count / dask concurrency regardless of
        # how small each individual chunk is. Bail out cleanly for this one
        # AOI rather than risk taking the whole job down again. Raised as
        # AOITooLargeError (not plain RuntimeError) so download_tiles_for_
        # geometry lets it propagate instead of swallowing it -- pipeline.py
        # catches this type specifically to log which AOI got skipped and
        # why, separately from ordinary per-AOI errors.
        max_composite_mb = self.cfg.get("max_composite_mb", 8000)
        if est_mb > max_composite_mb:
            raise AOITooLargeError(
                f"Composite would be ~{est_mb:.0f} MB ({nx}x{ny} px, "
                f"{len(items)} items) -- exceeds max_composite_mb="
                f"{max_composite_mb}. Likely an outlier-sized AOI; revisit "
                f"it separately (e.g. a coarser resolution just for this "
                f"geometry) rather than attempting it at full resolution."
            )

        # Sensor-specific masking + harmonization.
        if self.sensor == "sentinel2":
            masked_bands = self._mask_and_scale_s2(data)
        else:
            masked_bands = self._mask_and_scale_landsat(data)

        # Median composite across time per band.
        composite_bands = []
        for masked in masked_bands:
            med = masked.median(dim="time", skipna=True)
            composite_bands.append(med)

        # Convert each band from native DN to uint16 reflectance × 10000,
        # matching GEESource output exactly.
        out_bands = []
        sf = self.cfg["scale_factor"]
        off = self.cfg["offset"]
        for arr in composite_bands:
            refl = arr * sf + off
            scaled = (refl * 10000).clip(0, 65535).fillna(0).astype("uint16")
            out_bands.append(scaled)

        # Stack to (band, y, x) DataArray and attach CRS.
        import xarray as xr
        stacked = xr.concat(out_bands, dim="band")
        stacked = stacked.assign_coords(band=list(self.cfg["bands"]))
        stacked = stacked.rio.write_crs(utm_crs)   # ← was "EPSG:4326"
        return stacked

    # ------------------------------------------------------------------
    # Public interface — same five methods pipeline.py calls
    # ------------------------------------------------------------------
    def find_local_tiles(self, geom, quads_dir) -> List[str]:
        """Return cached composite paths whose bounds overlap geom.

        Composite filenames are deterministic per-AOI (see `_tile_path`),
        so we can look up this AOI's tile directly instead of scanning and
        re-opening every `.tif` ever written to `quads_dir`. A full-directory
        scan here is O(n) per AOI and O(n^2) over the whole job, since
        `quads_dir` accumulates one file per AOI processed and is never
        partitioned when `sub_root` is disabled.
        """
        local_tiles: List[str] = []
        if not os.path.isdir(quads_dir):
            return local_tiles

        tile_path = os.path.join(quads_dir, self._tile_path(geom))
        if not os.path.isfile(tile_path):
            return local_tiles

        try:
            with riox.open_rasterio(tile_path) as r:
                tile_bounds = box(*r.rio.bounds())
            if tile_bounds.intersects(geom):
                local_tiles.append(tile_path)
        except Exception:
            # Skip a file we can't open as a raster.
            pass
        return local_tiles

    # has_all_tiles(local_tiles, geom) is inherited from ImagerySource.

    def download_tiles_for_geometry(self, geom, quads_dir) -> List[str]:
        """
        Build a composite covering geom and write it to quads_dir.
        Returns the list of written tile paths (always 0 or 1 for MPC).
        """
        os.makedirs(quads_dir, exist_ok=True)

        fname = self._tile_path(geom)
        tile_path = os.path.join(quads_dir, fname)

        if os.path.isfile(tile_path):
            if self.is_valid_raster(tile_path):
                print(f"✅ Composite already cached: {fname}")
                return [tile_path]
            # Existing file is present but unreadable -- e.g. left truncated
            # by a process that was killed mid-write. Discard it and rebuild
            # rather than treating this AOI as a permanent failure.
            print(f"⚠️ Cached composite {fname} is invalid, rebuilding")
            os.remove(tile_path)

        try:
            composite = self._build_composite(geom)
        except AOITooLargeError:
            # Let this propagate -- pipeline.py logs it to a dedicated file
            # instead of just printing it, so oversized AOIs are easy to
            # find and revisit later.
            raise
        except RuntimeError as e:
            print(f"⚠️ Composite build failed: {e}")
            return []

        try:
            composite.rio.to_raster(tile_path, compress="deflate")
            print(f"✅ Wrote MPC composite: {fname}")
            return [tile_path]
        except Exception as e:
            print(f"⚠️ Failed to write composite {fname}: {e}")
            return []

    def clip_to_geometry(self, geom, out_path, quads_dir) -> str:
        """
        Clip the cached composite to geom and write to out_path.
        """
        local_tiles = self.find_local_tiles(geom, quads_dir)

        if not local_tiles:
            local_tiles = self.download_tiles_for_geometry(geom, quads_dir)
        if not local_tiles:
            raise RuntimeError(
                f"No tiles available for geometry at {geom.centroid}"
            )

        rasters = [riox.open_rasterio(p) for p in local_tiles]
        try:
            merged = merge_arrays(rasters) if len(rasters) > 1 else rasters[0]
            # Do NOT overwrite the raster's CRS — trust what's written on disk (UTM).

            # Reproject the AOI geometry into the raster's CRS before clipping.
            raster_crs = merged.rio.crs
            geom_gdf = gpd.GeoSeries([geom], crs="EPSG:4326").to_crs(raster_crs)
            raster_dtype = merged.dtype
            clipped = merged.rio.clip(geom_gdf.geometry, geom_gdf.crs, drop=True)
            # rio.clip() fills pixels outside the polygon (but inside its
            # bounding box) with NaN when no nodata value is declared,
            # silently promoting the array to float64. That's invisible for
            # TIFF output (GeoTIFF viewers treat NaN as nodata/transparent)
            # but produces genuinely wrong output either way: a "uint16
            # reflectance x10000" chip that's actually float64, and for PNG
            # (no nodata concept) NaN casts to 0 -- solid black pixels.
            clipped = clipped.fillna(0).astype(raster_dtype)

            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            self.write_chip(clipped, out_path)
        finally:
            for r in rasters:
                r.close()
        return out_path