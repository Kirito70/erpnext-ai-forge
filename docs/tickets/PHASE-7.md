---
id: PHASE-7
title: Skills provenance lockfile — skills-lock.json, forge skills verify
build_state: done
epic: harness-port
depends_on: [PHASE-0]
blocks: []
---

# PHASE-7 — Skills provenance lockfile

## Why

`forge.config.yaml` already has `security.external_skill_threshold: 98` — the
threshold exists, but nothing computes or checks a hash against it. There is no
mechanism to detect that an externally-sourced skill was silently modified
after import. This phase is independent of PHASE-5/6 (no shared files) and can
be picked up in any order relative to them — only depends on PHASE-0's scoring
engine.

## As-built record

Open question resolved before implementing: re-confirmed skill count and
provenance status directly rather than trusting the earlier plan-time figure —
**31 skills** (30 + PHASE-5's `ticket-authoring-guide`), **zero** with
`provenance:` set. The "zero churn on day one" claim held.

### Files created

- `canonical/skills-lock.json` — `{"version": 1, "skills": {}}`, matching the
  confirmed zero-external state.
- `forge/src/forge/skills_lock.py` — `load_lockfile`, `verify`,
  `list_skills`, `sha256_of`. No fetcher/installer, confirmed by a test that
  asserts no `fetch`/`install`/`import_skill`/`download` name exists in the
  module.
- `forge/src/forge/commands/skills.py` + `forge skills verify` / `forge skills
  list` CLI commands (new `skills_app` sub-typer in `cli.py`, matching the
  existing `apps_app`/`audit_app` pattern).
- `forge/tests/test_skills_lock.py` (10 tests) + assertions folded into
  `forge/tests/test_ticket_authoring.py`-style coverage for the `models.py`
  field defaults.

### Files modified

- `forge/src/forge/models.py` — `CanonicalArtifact` gains `provenance: str =
  "internal"`, `source_url: str | None`, `source_ref: str | None`.
- `forge/src/forge/loader.py::_parse_markdown_artifact` — reads the three new
  fields from frontmatter with the documented defaults.
- `forge/src/forge/commands/validate.py` — calls `skills_lock.verify()` and
  folds any finding into the existing issues list.
- `.github/workflows/ci.yml` — new `forge skills verify` step, placed between
  `forge score` and `pytest` per the planned order. Named as its own step
  (rather than relying solely on `forge validate` already covering it
  internally) so a skills-provenance failure surfaces as its own red CI step,
  not buried inside a generic "schema" failure.

### A real, load-bearing bug found and fixed during this ticket

Writing the "mutate an external skill, confirm verify catches a score drop"
test (per the ticket's own draft acceptance criteria) exposed that **the check
could never actually fire**. `canonical/skills/**` is blanket-exempted from
every dangerous-content deduction rule via PHASE-0's `_PROSE_DIRS` regex — that
exemption exists so this repo's *own* skills can discuss bad patterns
didactically ("don't do this") without tripping CRITICAL findings on their own
teaching examples. But that trust assumption does not extend to
`provenance: external` content nobody here wrote, and the exemption made
`score_file()` return 100 for *any* skill file regardless of content,
external or not — making `external_skill_threshold: 98` structurally
unreachable for exactly the case it exists to catch.

Fixed by refactoring `forge/src/forge/scoring.py::score_file` into a thin
wrapper around a new pure core, `score_text(text, rel_path, rules, *, suffix,
honor_path_exemptions)`. `skills_lock.py::verify` calls `score_text` with
`honor_path_exemptions=False` for external skills specifically — scoring their
content as if it carried no prose exemption — while `score_file` (used
everywhere else: `forge score`, the sync security gate, pre-commit) keeps its
exact prior behavior unchanged. Verified the fix doesn't alter internal-skill
scoring: re-ran `forge score --path canonical/skills` after the refactor,
still 100 across all 31 files.

## Original planned scope (for reference — see "As-built record" above for
## what actually happened)

- **`canonical/skills-lock.json`** — new file, one entry per *externally
  sourced* skill only. Schema (compatible with the lockfile shape already used
  by the two reference repos this pattern is drawn from, so nothing needs
  re-deriving):
  ```json
  { "version": 1, "skills": { "<id>": {
      "source": "owner/repo", "sourceType": "github",
      "skillPath": "skills/<x>/SKILL.md",
      "upstreamRef": "<commit sha>",
      "computedHash": "<sha256 of the canonical file as imported>",
      "importedAt": "2026-07-30", "securityScore": 98,
      "reviewedBy": "m.tayyab9736@gmail.com", "reviewedAt": "2026-07-30" }}}
  ```
- **Only skills with `provenance: external` in frontmatter need an entry.**
  Confirmed at plan time: all 30 skills currently in `canonical/skills/` are
  internally authored — **zero churn on day one**. Re-verify this count/status
  hasn't changed before implementing (skills may have been added since).
- **`forge/src/forge/skills_lock.py`** (new module) + **`forge skills verify`**
  / **`forge skills list`** CLI commands (new `commands/skills.py`).
  `verify` recomputes sha256 of `canonical/skills/<domain>/<id>.md` against
  `computedHash`, re-runs `score_file()` on it, and **fails** if either: the
  score has dropped below `external_skill_threshold` (98), or the hash changed
  without a corresponding `importedAt` bump.
- **`models.py::CanonicalArtifact`** gains `provenance`, `source_url`,
  `source_ref` fields, read from `raw_frontmatter` with sensible defaults
  (absent → internal).
- Wire `forge skills verify` into `forge validate` and into
  `.github/workflows/ci.yml` (after `forge score`, before `pytest`, matching
  the CI step ordering already established:
  ruff → mypy → forge validate → forge score → **forge skills verify** →
  pytest → forge sync --all-targets --dry-run).

## Explicit non-goal

**No fetcher/installer.** The lockfile's entire value is *detecting unreviewed
drift* in content that's already in the repo. Building automated import of
network-fetched, untrusted skill content is a materially riskier feature (this
is exactly the class of risk `D-EXTERNAL-UNREVIEWED` in
`canonical/policies/security-scoring.yaml` already exists to flag) and was
explicitly ruled out at plan time. Do not build it as part of this ticket even
if it looks like a natural extension.

## Acceptance criteria — verified

- [x] `canonical/skills-lock.json` exists as `{"version": 1, "skills": {}}` —
      confirmed zero external skills before writing it, not assumed
- [x] `forge skills verify` — green with zero external skills (real repo,
      confirmed)
- [x] `forge skills verify` — tested against a throwaway repo layout (not the
      real `canonical/`, so a test bug could never corrupt real skill files):
      marked a skill `provenance: external` with a matching lock entry,
      mutated it, confirmed `verify` fails with `hash-mismatch` distinct from
      `score-below-threshold`, confirmed a missing lock entry is its own
      `missing-lock-entry` finding. Also manually probed against the **real**
      repo (added `provenance: external` to a real skill temporarily, ran
      `forge skills verify`, confirmed `missing-lock-entry`; added a matching
      lock entry, confirmed clean; mutated content, confirmed
      `hash-mismatch`) — fully restored to original state afterward, verified
      byte-for-byte via the original content and a diff against the intended
      empty lockfile.
- [x] `forge skills list` shows provenance for every skill — confirmed against
      the real repo: 31 skills, 0 external
- [x] `models.py::CanonicalArtifact` provenance fields default correctly —
      test asserts all real skills in this repo currently report
      `provenance == "internal"`, `source_url is None`
- [x] Wired into `forge validate` (folds findings into `issues`) and CI (own
      named step, `forge score` → `forge skills verify` → `pytest`)
- [x] Full test suite: 367 passed, 2 skipped (+10 over PHASE-6's 357); ruff
      and mypy strict both clean; canonical still scores 100 everywhere; live
      self-harness still `RESULT: GREEN`

## Known open questions — resolved

- Re-confirmed `canonical/skills/` count and provenance status directly before
  implementing (see "As-built record") rather than trusting the earlier
  plan-time figure. Count had grown by exactly one (PHASE-5's
  `ticket-authoring-guide`); provenance was still universally unset.
