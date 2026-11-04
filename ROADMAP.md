# geoetl Roadmap

Working plan for geoetl's development, phased so each step is safe to
build on top of rather than racing ahead on untested ground. Check items
off as they land; add new ones as they come up.

## Phase 1 — Foundations (unlocks everything else safely)

Building providers/formats on a zero-test codebase means every addition
after this point is untested. This phase makes the rest of the plan safe
to execute quickly.

- [ ] **Test suite + CI** — unit tests for the pure logic (band config,
      PNG scaling math, size-cap triggering, path construction, env-var
      expansion), a conformance test for the `ImagerySource` interface so
      a new provider can't silently violate it, integration tests against
      mocked STAC/API responses (not live MPC/Planet calls in CI).
      GitHub Actions wired to run on every PR. See `TESTING_PLAN.md`.
- [ ] **Config validation** — flagged in the original audit, still
      outstanding; matters more once there are more providers/formats
      with more ways to misconfigure.
- [ ] **Remaining docs pages** — Configuration Reference, How-to guides,
      Extending, Troubleshooting, Contributing (from the original
      outline). JOSS explicitly checks for statement-of-need / install /
      example-usage / API-docs / community-guidelines, and these need to
      exist before submission regardless.
- [ ] **PyPI packaging + tagged releases** — needed for "installable via
      a standard package manager" and for the eventual Zenodo
      archival/DOI step.

## Phase 2 — Architecture upgrades everything else builds on

- [ ] **STAC-aware output** (#4) — the "Load" completion already scoped.
      Worth sequencing before temporal stacking and coordinate formats
      because it actually subsumes #8: a STAC Item always carries both
      full geometry and bbox as standard fields, so "different spatial
      output formats" is mostly solved for free once chips are STAC Items
      instead of flat JSON sidecars. A thin example showing a
      geoetl-built catalog loading directly into a TorchGeo dataset would
      be the concrete proof-of-interop.
- [ ] **Parallelization** (#3) — do this once the provider/format surface
      is stabilized, and designed around what we learned this session:
      naive `multiprocessing.map` over AOIs would reintroduce the exact
      memory-variance problem the size-cap/chunking work just fixed.
      Needs size-aware scheduling, not blind parallelism.

## Phase 3 — Breadth

- [ ] **More providers** (#1) — cheapest wins first: AWS Earth Search
      (free, STAC-native, Sentinel-2/Landsat) and anything already
      sitting in MPC's own catalog (NAIP, Copernicus DEM, Sentinel-1 RTC,
      WorldCover, VIIRS nighttime lights) are near-free additions given
      the existing `MPCSource`/`SENSOR_CONFIGS` architecture. Sentinel
      Hub/Copernicus Data Space is a genuinely new provider class, more
      like the Planet integration effort. (Not GEE, per earlier decision.)
- [ ] **More sources per provider** (#2) — expand MPC's `SENSOR_CONFIGS`
      (cheap, same pattern each time). Planet is the bigger lift here —
      currently only Basemaps/quads are wired up; their Orders/Data API
      for full-resolution scenes is a genuinely different, async
      (submit-order-then-poll) workflow, not a drop-in extension of the
      current quad-download code.

## Phase 4 — Output flexibility

- [ ] **NetCDF output + genuine temporal stacking** (#6 + #7, paired) —
      right now `temporal.enabled` produces N separate single-timestep
      chip files per AOI, not one stacked array with a real time
      dimension. NetCDF is the natural format for that (labeled time
      axis, CF-convention CRS, and `xarray`/`rioxarray` already do the
      heavy lifting since they're already dependencies) — worth
      confirming that's actually what "temporal stacks" means before
      building it: there's a real difference between "N files, one per
      step" (current) and "1 file, time as a dimension" (the likely
      intent).
- [ ] **Coordinate output formats** (#8) — solved by Phase 2 for STAC
      output; for anyone still on the plain-JSON path, a small
      `output.coord_format: centroid|bounds` option covers it.
