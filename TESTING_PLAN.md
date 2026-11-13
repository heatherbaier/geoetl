# geoetl Testing Plan

Status: **in progress** — foundational scaffolding + first increment of
tests landed (`tests/`, pytest, CI). This is a living document: update it
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
| `geoetl/io/base.py` shared logic (`has_all_tiles`, `scan_local_tiles`, `write_chip`, `is_valid_raster`, PNG scaling/calibration) | Used by every source; a bug here silently corrupts every dataset built with any source | `tests/unit/io/test_base.py` — 88% line coverage |
| `geoetl/pipelines/pipeline.py` resumability (skip-if-exists, rebuild-if-corrupt) | This is geoetl's core promise ("resumable by default") — if it's wrong, multi-hour HPC runs silently redo or silently skip work | `tests/unit/pipelines/test_pipeline.py` (against a `FakeImagerySource`) — 97% |
| `geoetl/io/mpc.py` (`MPCSource`) | STAC search, cloud masking, compositing — most complex source, most used | `tests/unit/io/test_mpc.py` covers `_tile_path`'s band-fingerprint regression and the `_build_composite` size cap; the search→load→mask→composite pipeline itself is still untested (37%) |
| `geoetl/io/planet.py` (`PlanetBasemapSource`) | Different caching strategy (shared quads) from MPC — easy for a fix to one source to break the other | Interface-conformance only so far (14%) — no mocked-API test yet |
| `geoetl/io/alpha_earth.py` | Optional dependency path (`alpha-earth` extra) — easy to silently bitrot since it's not exercised by default | None (0%) |
| `geoetl/utils/jsonio.py` | Small, but labels/coords JSON corruption or partial writes would be a silent data-quality bug | `tests/unit/utils/test_jsonio.py` — 100% |
| `geoetl/cli.py` | User-facing entry point; config parsing errors should fail clearly, not deep in a stack trace | `_expand_env_vars` covered (81%); the `run` command itself isn't |
| `geoetl/io/__init__.py` (`get_source` factory) | Wrong cfg→source wiring fails silently wrong, not loudly | None yet (15%) |

Baseline as of this increment: **44 tests, 50% overall line coverage**, concentrated exactly where the table above says it should be (base.py/pipeline.py high, the network-heavy source modules still low).

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

## 6. Decisions made

- **Mocking library**: `responses`, added as a test dependency. Not
  actually exercised yet in this increment — see the testability finding
  below for why the first round of `MPCSource` tests used
  `monkeypatch`/dependency substitution instead. `responses` is still the
  right tool for the next increment's real HTTP-level STAC/Planet mocking.
- **Coverage target**: no hard percentage gate. CI runs with
  `--cov-report=term-missing` for visibility, but what's gated (informally,
  by review) is "does every area in §1's table have tests for its actual
  risk," not a line-count threshold.
- **Regression tests for already-fixed bugs**: one test per fixed bug,
  named after what it guards against, living alongside the ordinary unit
  tests for the module it's in rather than a separate `regressions/`
  bucket. Landed so far: the black-PNG fix
  (`test_write_chip_png_scales_values_and_zeroes_nodata`,
  `tests/unit/io/test_base.py`) and the stale-cache-on-band-change fix
  (`test_tile_path_changes_when_bands_override_differs`,
  `tests/unit/io/test_mpc.py`). Still outstanding: a direct regression
  test for the memory-cap fix itself is in (`test_mpc.py`'s
  `test_build_composite_raises_when_estimated_size_exceeds_the_cap`), but
  nothing yet regression-tests the chunked-read behavior that accompanied
  it.

## 7. Testability finding worth fixing separately

`MPCSource.__init__` opens a live STAC catalog connection
(`pystac_client.Client.open(MPC_STAC_URL, ...)`) unconditionally — so
*constructing* an `MPCSource` makes a real network call to Microsoft
Planetary Computer, even just to validate constructor arguments like
`bands`. Every `MPCSource` test in this round has to monkeypatch
`pystac_client.Client.open` before instantiating one. That's a workable
pattern for tests, but it's also a real design smell worth fixing on its
own merits: a config-validation pass (already on `ROADMAP.md`'s Phase 1)
that constructs sources to check them would make a network call per
config just to validate it. Worth lazily opening the catalog connection on
first actual search instead — not doing that here since it's out of scope
for "add tests," but flagging it so it doesn't get lost.
