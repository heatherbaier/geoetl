# Quickstart

This walks through building a real dataset end to end: per-tract
Sentinel-2 composites for US Census tracts, output as georeferenced
GeoTIFF chips. It's adapted directly from a production config used for a
tract-level wealth-mapping project — the only things changed below are
the file paths.

## What you'll need

- geoetl installed ({doc}`installation`)
- A tract-level shapefile with a unique ID column. US Census Bureau
  [TIGER/Line](https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html)
  tract shapefiles work well here — they ship with a `GEOID` column that
  makes a natural AOI identifier.
- Optionally, a column in that same shapefile you want carried through as
  a training label (a poverty rate, a wealth index, anything numeric or
  categorical already joined onto the tracts).

## Write the config

```yaml
aoi:
  path: /path/to/census_tracts.shp

catalog:
  sensor: mpc_sentinel2
  start_date: "2016-10-01"
  end_date: "2016-12-31"
  cloud_cover_max: 30
  mask_clouds: false
  bands: ["B01", "B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B09", "B11", "B12"]

auth:
  mpc_api_key: null

output:
  root: /path/to/output/
  sub_root: False

params:
  uid_column: GEOID
  label_column: wealth_ind
  dataset_name: tracts_2016_q4
```

Save this as `quickstart.yml`. A few things worth calling out:

- `catalog.sensor: mpc_sentinel2` — pulls from Microsoft Planetary
  Computer's Sentinel-2 L2A (surface reflectance) collection. `mpc_api_key`
  can stay `null`; anonymous access works for moderate volumes (see
  {doc}`installation` for higher-throughput setup).
- `start_date`/`end_date` define the time window geoetl searches for
  scenes in — here, Q4 2016. Every matching scene (after the
  `cloud_cover_max` filter) gets cloud-masked and median-composited per
  AOI. `mask_clouds: false` skips that masking step, a legitimate choice
  when you'd rather maximize per-pixel scene coverage over cloud-free
  purity.
- `catalog.bands` requests all 12 of Sentinel-2's bands by name, not just
  the default RGB three — useful when a downstream model wants the full
  spectral signature (SWIR, red edge, etc.) rather than a visual
  composite. Omit this field entirely to get the default `["B04", "B03",
  "B02"]` (red/green/blue).
- `params.uid_column` / `label_column` read directly from your
  shapefile's attribute table: `GEOID` becomes each chip's filename,
  `wealth_ind` gets carried through as that chip's training label.

## Run it

```bash
geoetl run --config quickstart.yml
```

For each tract in the shapefile, geoetl will:

1. Check whether that tract's chip already exists — skip it if so (see
   *Resuming an interrupted run* below)
2. Search Planetary Computer's STAC API for Sentinel-2 scenes matching
   the time window and cloud threshold
3. Build a median composite across the matching scenes and cache it
4. Clip the composite to the exact tract boundary and write the final chip

For a few thousand tracts this can take anywhere from minutes to hours,
depending on cloud cover, how many bands are requested, and tract size —
that's expected, and it's the main reason runs are resumable rather than
all-or-nothing.

## What you get

```
/path/to/output/
  chips/<GEOID>.tif                 # one 12-band GeoTIFF per tract
  quads/                            # cached composites, reused across runs
  aoi_mapping.json                  # per-tract status + which source tiles were used
  tracts_2016_q4_ys.json            # {chip_path: wealth_ind value}
  tracts_2016_q4_coords.json        # {chip_path: [centroid_lon, centroid_lat]}
```

## Resuming an interrupted run

If the job dies partway through — an HPC walltime limit, a network blip,
anything — just run the exact same command again. Any tract whose chip
file already exists is skipped, and any composite already cached in
`quads/` is reused rather than rebuilt. There's nothing to clean up
first.

## Next steps

- *Core Concepts* (coming soon) — the caching/resumability model in more depth
- *Configuration Reference* (coming soon) — every config option, not just the ones used here
- *How-to: export PNGs for model training* (coming soon) — if your training code wants ordinary images instead of GeoTIFFs
