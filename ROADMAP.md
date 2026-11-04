# geoetl Roadmap — JOSS Submission Readiness

Working checklist for getting `geoetl` ready for JOSS submission. Check
items off as they land; add new ones as they come up. This file tracks
*our* plan, not community-facing issues — see the note on issues vs. this
file at the bottom.

## Phase 0 — Authorship & repo hygiene

- [x] Git identity for new commits set to the actual author (Heather
      Baier), with AI assistance disclosed via `Co-Authored-By` trailers
      rather than as the commit author
- [ ] Decide whether/how to handle authorship display on already-merged
      history (candidate: `.mailmap`, no history rewrite)
- [ ] `CITATION.cff` at repo root
- [ ] `CONTRIBUTING.md` (even a short one — JOSS checks for this)

## Phase 1 — Documentation site (Sphinx + Read the Docs)

- [x] Home page (`docs/index.md`)
- [x] Installation (`docs/installation.md`)
- [x] Quickstart (`docs/quickstart.md`)
- [x] Core Concepts (`docs/concepts.md`)
- [ ] Extending geoetl (adding a new `ImagerySource`)
- [ ] Troubleshooting (corrupt cache recovery, oversized-AOI skipping, memory
      errors on large composites)
- [ ] PNG export how-to (manual vs. `auto` scale calibration)

## Phase 2 — Automated testing

- [ ] Test suite scaffolding (pytest, fixtures, CI) — see `TESTING_PLAN.md`
      for the full plan; this phase tracks execution against it
- [ ] Unit coverage for `geoetl/io/base.py` shared logic
      (`has_all_tiles`, `scan_local_tiles`, `write_chip`, `is_valid_raster`)
- [ ] Unit coverage for `geoetl/pipelines/pipeline.py` resumability logic
      (skip-if-exists, rebuild-if-corrupt)
- [ ] Source-specific tests for `MPCSource` and `PlanetBasemapSource`
      against mocked APIs (no live network calls in CI)
- [ ] CI workflow running the suite on every push/PR

## Phase 3 — JOSS paper

- [ ] `paper.md` (Statement of Need, summary, references)
- [ ] `paper.bib`
- [ ] Internal review of `paper.md` against the JOSS review checklist

## Phase 4 — Submission

- [ ] Final pass against the JOSS reviewer checklist
      (https://joss.readthedocs.io/en/latest/review_checklist.html)
- [ ] Submit

---

**Issues vs. this file:** JOSS cares about the project being responsive to
issues that come in, not about a self-filed backlog, so day-to-day planned
work lives here rather than as GitHub issues. The one exception is the
missing test suite (Phase 2) — worth its own tracked issue since it's the
one item here that's an actual JOSS submission blocker.
