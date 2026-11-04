# geoetl

**A config-driven ETL tool for building GeoAI / remote-sensing training datasets.**

Give `geoetl` a shapefile of areas of interest (AOIs) — points, polygons,
buffers, census tracts, whatever your unit of analysis is — and a YAML
config, and it fetches per-AOI imagery chips from a satellite imagery
source, clips them to each AOI, and writes out a clean, ML-ready dataset
alongside label, coordinate, and metadata files. No manual downloading,
no hand-written clipping/reprojection scripts, no post-hoc format
conversion.

```bash
geoetl run --config configs/ohio_tlag.yml
```

## Why geoetl

Building a satellite imagery training set usually means writing bespoke,
source-specific glue code — one script to query Planetary Computer, a
different one for Planet, hand-rolled cloud masking, manual retry logic
for a job that dies partway through processing a few thousand AOIs. geoetl
exists so that glue code gets written once, well, and config-driven, not
once per project.

## Key features

- **Multiple sources behind one interface** — Microsoft Planetary Computer
  (Sentinel-2 L2A, Landsat 5/8/9 Collection 2) and Planet Labs basemaps
  today, with a small, explicit interface for adding more (see
  *Extending geoetl*, coming soon).
- **AOI-driven, not scene-driven** — you describe *where*, geoetl handles
  searching, cloud masking, compositing, and clipping to get there.
- **Resumable by default** — a run interrupted partway through (a
  multi-hour HPC job, a flaky network) picks back up without re-fetching
  or re-building anything already on disk.
- **TIFF or PNG output** — GeoTIFF for downstream GIS tooling, or PNG with
  either manually chosen or auto-calibrated brightness scaling for model
  training pipelines that expect ordinary images.
- **Static or temporal** — pull one composite per AOI, or a time series
  across multiple years/months/quarters, with the same config shape.
- **Built for scale, not just for demos** — AOI sets spanning a full
  state or country hit real failure modes (a single AOI needing far more
  memory than the rest, a cache file left corrupt by an earlier crash);
  geoetl is built to survive and log those cleanly rather than take the
  whole job down. See *Troubleshooting* (coming soon) for the specifics.

## Where to go next

```{toctree}
:maxdepth: 2

installation
```

```{toctree}
:hidden:
:caption: Project

GitHub <https://github.com/heatherbaier/geoetl>
```
