# geoetl

A config-driven ETL tool for building GeoAI / remote-sensing training
datasets: given a shapefile of AOIs (points, polygons, buffers, tracts, ...),
`geoetl` fetches per-AOI imagery chips from a satellite imagery source,
clips them to each AOI, and writes out a clean, ML-ready dataset alongside
label/coordinate/metadata JSON files.

## Supported sources

| `catalog.sensor` value | Provider | Notes |
|---|---|---|
| `mpc_sentinel2` | Microsoft Planetary Computer | Sentinel-2 L2A |
| `mpc_landsat8` | Microsoft Planetary Computer | Landsat 8/9 Collection 2 L2 |
| `mpc_landsat5` | Microsoft Planetary Computer | Landsat 5 Collection 2 L2 |
| `planet` | Planet Labs | Basemap mosaics (monthly/quarterly), requires a Planet API key |

MPC composites are built client-side: `geoetl` searches the MPC STAC API for
scenes intersecting the AOI within a time window, applies cloud masking
(SCL for Sentinel-2, QA_PIXEL for Landsat), and takes a per-pixel median
composite. Planet imagery is pulled from the Basemaps API as pre-built quads
that are merged and clipped per AOI.

## Install

```bash
git clone https://github.com/heatherbaier/geoetl.git
cd geoetl
pip install -e .
```

Requires Python >= 3.9.

## Quickstart

```bash
geoetl run --config configs/ohio_tlag.yml
```

For Planet sources, set your API key as an environment variable before running:

```bash
export PLANET_API_KEY=your-key-here
```

(Config files may also reference `${PLANET_API_KEY}` inline — `geoetl`
expands `${VAR}` placeholders from the environment at load time. An unset
variable expands to an empty string, in which case the env var is used as
the fallback.)

## Config format

```yaml
aoi:
  path: /path/to/aois.shp        # any format geopandas can read

catalog:
  sensor: mpc_landsat8           # see supported sources above
  start_date: "2020-01-01"       # ISO date range (or use year/month, MPC only)
  end_date: "2020-12-31"
  cloud_cover_max: 30            # MPC only: max eo:cloud_cover percent
  mask_clouds: false             # MPC only: apply cloud masking before compositing

auth:
  mpc_api_key: null              # optional MPC subscription key (higher throughput)
  # api_key: ${PLANET_API_KEY}   # Planet only

output:
  root: /path/to/output/         # writes <root>/chips, <root>/quads, and dataset JSONs
  sub_root: False                # if True, partition output into subfolders...
  sub_root_column: iso           # ...named after this AOI column (e.g. one folder per country)
  checkpoint_every: 25           # write labels/coords JSON to disk every N AOIs (default 25)

params:
  uid_column: GEOID              # AOI shapefile column used as the unique chip ID
  label_column: poverty_ra       # AOI shapefile column used as the training label (or null)
  dataset_name: ohio2020         # prefix for the output <name>_ys.json / <name>_coords.json

# optional: fetch imagery across multiple time slices instead of one static pull
temporal:
  enabled: true
  cadence: monthly               # or quarterly
  years: [2023, 2024]
  steps: [8, 9, 10, 11, 12, 1, 2, 3, 4, 5]
```

See `configs/` for real examples (static single-pull, temporal multi-slice,
and `sub_root`-partitioned regional runs).

## Output layout

```
<output.root>/
  chips/<aoi_id>.tif                  # per-AOI clipped chip (or nested under sub_root / temporal step)
  quads/                              # cached source tiles, reused across AOIs/runs
  aoi_mapping.json                    # per-AOI status + which tiles were used
  <dataset_name>_ys.json              # labels
  <dataset_name>_coords.json          # AOI centroid coordinates
```

Runs are resumable: an AOI whose chip file already exists is skipped, and
downloaded source tiles in `quads/` are cached and reused rather than
re-fetched.

## Adding a new imagery source

Subclass `ImagerySource` (`geoetl/io/base.py`) and implement its four
abstract methods (see `geoetl/io/mpc.py` for the most complete reference
implementation):

```python
from geoetl.io.base import ImagerySource

class MySource(ImagerySource):
    def set_time_filter(self, year=None, steps=None, cadence="monthly"): ...
    def find_local_tiles(self, geom, quads_dir) -> list[str]: ...
    def download_tiles_for_geometry(self, geom, quads_dir) -> list[str]: ...
    def clip_to_geometry(self, geom, out_path, quads_dir) -> str: ...
```

`has_all_tiles(local_tiles, geom)` comes for free from the base class. If
your source caches multiple grid tiles per AOI (like Planet's quads) rather
than one deterministically-named composite per AOI (like MPC's), you can
also get `find_local_tiles` for free by implementing it as
`return self.scan_local_tiles(quads_dir, geom)`.

Then register it in `geoetl/io/__init__.py:get_source()`.

## License

MIT — see [LICENSE](LICENSE).
