# geoetl Testing Plan

Status: **draft — under discussion**. This is a living document: update it
whenever a new feature lands, a new failure mode is found, or the testing
approach changes. It has three jobs:

1. Say what's tested *today* and what isn't.
2. Say what gets tested before each new feature is considered done.
3. Say how tests run automatically (CI) as code gets pushed.

## 1. Scope: what actually needs testing

geoetl's risk is concentrated in a few places, not spread evenly across the
codebase:

| Area | Why it matters | Current coverage |
|---|---|---|
| `geoetl/io/base.py` shared logic (`has_all_tiles`, `scan_local_tiles`, `write_chip`, `is_valid_raster`) | Used by every source; a bug here silently corrupts every dataset built with any source | None |
| `geoetl/pipelines/pipeline.py` resumability (skip-if-exists, rebuild-if-corrupt) | This is geoetl's core promise ("resumable by default") — if it's wrong, multi-hour HPC runs silently redo or silently skip work | None |
| `geoetl/io/mpc.py` (`MPCSource`) | STAC search, cloud masking, compositing — most complex source, most used | None |
| `geoetl/io/planet.py` (`PlanetBasemapSource`) | Different caching strategy (shared quads) from MPC — easy for a fix to one source to break the other | None |
| `geoetl/io/alpha_earth.py` | Optional dependency path (`alpha-earth` extra) — easy to silently bitrot since it's not exercised by default | None |
| `geoetl/utils/jsonio.py`, `geoetl/utils/logging.py` | Small, but labels/coords JSON corruption or partial writes would be a silent data-quality bug | None |
| `geoetl/cli.py` | User-facing entry point; config parsing errors should fail clearly, not deep in a stack trace | None |

**Not in scope for automated tests:** actually hitting the live MPC STAC API
or Planet Basemaps API in CI. Those are rate-limited, require credentials
(Planet), and would make CI flaky and slow. Real-API checks stay a manual
smoke test (see §5), run before a release, not on every push.

## 2. Framework & structure

- **pytest**, with `tests/` mirroring the package layout:
  ```
  tests/
    unit/
      io/
        test_base.py
        test_mpc.py
        test_planet.py
      pipelines/
        test_pipeline.py
      utils/
        test_jsonio.py
    fixtures/
      tiny_rasters/        # small synthetic GeoTIFFs for clip/composite tests
      stac_responses/      # recorded/mocked STAC API JSON responses
    conftest.py
  ```
- **No real network calls in unit tests.** External HTTP (STAC search,
  Planet Basemaps, planetary-computer SAS token signing) gets mocked —
  candidates are `responses` or `pytest-httpserver`; final pick is an open
  question below.
- **Synthetic rasters, not real downloads**, for anything that touches
  actual pixel data (compositing, clipping, PNG scaling). A handful of
  tiny (e.g. 10x10px, 2-4 band) GeoTIFFs checked into `tests/fixtures/`
  cover: a clean tile, a tile with nodata/cloud-masked pixels, a tile that
  doesn't fully cover an AOI (tests the multi-tile merge path).
- **`tmp_path` for every test that touches disk** (`quads/`, `chips/`,
  `aoi_mapping.json`) — nothing in the test suite depends on or writes to
  a real output directory.

## 3. What "done" means for a new feature going forward

Before a PR adding a feature is considered mergeable:

- [ ] At least one unit test exercising the new code path's happy path
- [ ] At least one test for the failure mode that motivated the feature
      (e.g. the memory-error fixes and PNG black-output fix already in
      history should each have had a regression test — retroactively
      adding tests for those specific past bugs is part of Phase 2 of
      `ROADMAP.md`)
- [ ] If it touches the resumability/caching logic: a test that runs the
      pipeline twice over the same AOI and asserts the second run does no
      network I/O / rebuild work
- [ ] `ruff`/`black` (or whatever linter we settle on — not yet configured
      in `pyproject.toml`) and the full test suite pass locally before push

## 4. CI

- GitHub Actions workflow (`.github/workflows/tests.yml`), triggered on
  push and PR against `master`.
- Matrix: at minimum the Python versions the `requires-python = ">=3.9"`
  bound in `pyproject.toml` claims to support — worth checking we actually
  test on the floor of that range, not just whatever's in the dev
  container.
- Install the `alpha-earth` extra in a separate job (or skip those tests
  by default) so a missing optional dependency doesn't fail the main
  matrix.
- Fails the build on any test failure; no "flaky, ignore it" tests — if
  something's flaky, that's a bug in the test (or in geoetl) to fix, not
  to skip.

## 5. Manual / pre-release checks (not automated)

Kept deliberately small and explicit, so it's actually followed:

- [ ] One real MPC run against a small real AOI shapefile (e.g. a handful
      of census tracts), confirming chips, labels, and coords JSON come
      out correctly
- [ ] One real Planet run, if a Planet API key is available
- [ ] Interrupt a run partway through and confirm resuming it picks up
      cleanly (the thing `docs/concepts.md` promises in the resumability
      diagram)

## 6. Open questions to settle before writing the first test

- **Mocking library**: `responses` (simple, request-level) vs.
  `pytest-httpserver` (a real local server, closer to reality but more
  setup) vs. recording real responses once with something like `vcrpy`
  and replaying them. Leaning `responses` for STAC search since the
  response shape is simple JSON, but open to discussion.
- **Coverage target**: do we want a hard number (e.g. 80%) enforced in CI,
  or just "the areas in §1 have tests" without a blanket percentage? A
  hard number on a small, API-heavy codebase like this one can be
  misleading (the actual risk is behavioral, not line-count).
- **Where do the regression tests for already-fixed bugs go** (the PNG
  black-output fix, the MPC memory errors, the stale-cache-on-band-change
  fix)? Proposing one test per fixed bug, named after what it guards
  against, rather than bucketing them generically.
