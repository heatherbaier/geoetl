# Core Concepts

geoetl is, literally, an ETL tool: it **E**xtracts imagery from a source's
API, **T**ransforms it (cloud masking, compositing), and **L**oads the
result as a clipped, labeled chip ready for model training. Everything
else in geoetl — the caching, the resumability, the source interface — is
in service of making that three-stage pipeline survive running at the
scale a real dataset actually needs: thousands of AOIs, flaky networks,
HPC jobs that get killed and resubmitted.

```{mermaid}
flowchart LR
    AOI[AOI shapefile] --> Extract

    subgraph Extract["Extract"]
        direction TB
        E1["Search the source's API for\nscenes/tiles covering this AOI"]
    end

    subgraph Transform["Transform"]
        direction TB
        T1[Cloud mask] --> T2[Per-pixel median composite]
    end

    subgraph Load["Load"]
        direction TB
        L1[Clip to the exact AOI boundary] --> L2["Write chip +\nupdate labels/coords JSON"]
    end

    Extract --> Transform --> Load --> Output[(ML-ready dataset)]
```

## AOI-driven, not scene-driven

Satellite imagery APIs are organized around *scenes* — a Sentinel-2 tile,
a Landsat path/row, a Planet basemap quad — each covering a fixed grid
cell that has nothing to do with your actual areas of interest. geoetl
inverts that: you hand it AOIs (points, polygons, buffers, census
tracts — anything geopandas can read), and it handles translating each
one into "which scenes/tiles cover this" and merging whatever it finds
into a single clipped chip. You never think about tile grids.

## What happens per AOI

This is the actual control flow geoetl runs for every AOI in your
shapefile — not a simplification, this is what `pipeline.py` does:

```{mermaid}
flowchart TD
    Start([For each AOI]) --> Exists{Chip file\nalready exists?}
    Exists -- yes --> Skip[Skip] --> Next([Next AOI])
    Exists -- no --> Find[find_local_tiles]
    Find --> Has{has_all_tiles?}
    Has -- yes --> Clip[clip_to_geometry]
    Has -- no --> Download[download_tiles_for_geometry]
    Download --> Build["Build composite:\nsearch + cloud-mask + median"]
    Build --> Cache[(Write to quads/ cache)]
    Cache --> Clip
    Clip --> Write["Write chip to chips/ +\nupdate labels/coords JSON"]
    Write --> Next
```

The `Exists` check is why runs are resumable at zero cost: an AOI whose
chip is already on disk is skipped before geoetl does any network I/O at
all. The `has_all_tiles` check is the same idea one layer down — even if
the final chip isn't done yet, a composite already cached in `quads/`
doesn't get rebuilt.

## Imagery sources: one interface, two different strategies

Every source implements the same four-method interface
(`ImagerySource` in `geoetl/io/base.py`), but *how* `MPCSource` and
`PlanetBasemapSource` satisfy it is genuinely different, because the two
providers hand you fundamentally different things: Planetary Computer
gives you raw scenes to composite yourself; Planet gives you pre-built
basemap quads to merge.

```{mermaid}
classDiagram
    class ImagerySource {
        <<abstract>>
        set_time_filter()
        find_local_tiles()
        download_tiles_for_geometry()
        clip_to_geometry()
        has_all_tiles() shared
        scan_local_tiles() shared
        write_chip() shared
        is_valid_raster() shared
    }
    class MPCSource {
        find_local_tiles() deterministic per-AOI lookup
        download_tiles_for_geometry() STAC search + build + cache composite
        clip_to_geometry() open cached composite, clip
    }
    class PlanetBasemapSource {
        find_local_tiles() scan_local_tiles for quads
        download_tiles_for_geometry() fetch quads from Basemaps API
        clip_to_geometry() merge quads, clip
    }
    ImagerySource <|-- MPCSource
    ImagerySource <|-- PlanetBasemapSource
```

A few consequences of that difference that are worth knowing:

- **MPC caches one file per AOI** — `_tile_path(geom)` produces a
  deterministic filename from the AOI's centroid and the catalog
  settings in play, so `find_local_tiles` can look it up directly rather
  than scanning a directory.
- **Planet caches a grid of quads per region**, potentially shared across
  overlapping AOIs — `find_local_tiles` scans `quads/` for whichever
  quads intersect this AOI's geometry.
- Both still go through the exact same per-AOI flow above, and both get
  `has_all_tiles`, `write_chip`, and the corrupt-cache check
  (`is_valid_raster`) for free from the shared base class rather than
  reimplementing them.

See *Extending geoetl* (coming soon) for what adding a third source
actually looks like.

## Caching and resumability

geoetl's output directory has two tiers, and they get reused
independently:

- **`quads/`** — intermediate cache. For MPC, one composite GeoTIFF per
  AOI per time window; for Planet, the raw downloaded quads. Always
  GeoTIFF, regardless of `output.format`, because these get reopened,
  reprojected, and clipped on future runs — PNG can't carry the
  georeferencing that requires.
- **`chips/`** — the final, per-AOI output your model training code
  actually reads. GeoTIFF or PNG depending on `output.format`.

Because both tiers are checked before any work happens, resuming an
interrupted run is just running the same command again:

```{mermaid}
flowchart LR
    subgraph Run1["Run 1 — interrupted"]
        direction TB
        R1A[Tract 1: built] --> R1B[Tract 2: built]
        R1B --> R1C[Tract 3: in progress]
        R1C -.killed.-> R1D[Job dies]
    end
    subgraph Run2["Run 2 — same command"]
        direction TB
        R2A["Tract 1: skipped\n(chip exists)"] --> R2B["Tract 2: skipped\n(chip exists)"]
        R2B --> R2C["Tract 3: rebuilt\n(was incomplete)"]
        R2C --> R2D[Tract 4: built]
    end
    Run1 --> Run2
```

Nothing needs to be deleted or cleaned up between runs — not even the
partially-built tract. A composite left corrupt by a process that was
killed mid-write (interrupted right as it wrote to `quads/` or `chips/`)
is detected and rebuilt automatically rather than treated as valid
forever; see *Troubleshooting* (coming soon) for how.

## Output formats

`quads/` is always GeoTIFF. The final `chips/` output is GeoTIFF by
default, or PNG if `output.format: png` is set — useful when your
training pipeline wants ordinary images rather than georeferenced
rasters. PNG caps out at 4 bands (RGB/RGBA) and needs its 16-bit
reflectance values scaled down to 0-255, either with a manually chosen
divisor or one auto-calibrated from your own data's actual brightness
range. See the PNG export how-to guide (coming soon) for the full
walkthrough.
