# Lesson Prep Portable Engineering Acceptance Implementation Plan

> **For agentic workers:** Use the existing native execution workflow, then independent read-only review. Do not delegate implementation or change the production guards.

**Goal:** Replace the nine nonportable lesson-prep engineering failures with reproducible real document/real MySQL checks, preserving a separate fail-closed operator acceptance for the original course pack.

**Architecture:** Ordinary tests receive owned temporary synthetic PDF/PPTX documents and an unsupported legacy-extension sentinel. Successful draft writes use the actual complete app and canonical login on a new network-disabled MySQL schema, reusing the previous native lifecycle and isolation helpers. A read-only operator CLI verifies an explicitly supplied official pack and provenance/hash manifest before applying the original 97-resource assertions.

**Tech Stack:** Existing requirements-dev/native requirements, pytest, pypdf, python-pptx, HTTPX ASGI, SQLAlchemy/PyMySQL, official pinned MySQL 8.4.10 image. No new dependencies.

**Spec:** Parent delegation dated 2026-10-06: resolve nine lesson-prep portability failures; keep clean MySQL root, canonical permissions, real extractor/index/citation; synthetic engineering only; official 97-resource check must fail when its pack/provenance is missing; no browser, provider, credential, original-courseware, CI, main, force or deployment actions.

## Global Constraints

- Base: `6b73e1407fe00746d85512944e8d21a6e3f6c367`, branch `102V12`; ordinary push only after parent CAS confirmation.
- Preserve all product source/migrations and previous evidence bytes unless a real product bug is reproduced RED/GREEN.
- No inherited service credentials or `.env` reads; temporary blank cwd, white-listed environment and explicit audit guards.
- No skips/zero-test success and no fabricated 97-item course pack.
- Genuine PDF/PPTX bytes with known synthetic text; `.ppt` sentinel tests only the already unsupported extension, never claims legacy document parsing.
- Exactly owned schemas/container/volumes/private files are cleaned with receipts; keep unrelated services untouched.

## Review Focus

- Manifest path escape/symlink/duplicate/hash mismatch must fail before acceptance.
- A synthetic or absent source manifest can never authorize the operator pack check.
- Empty PDF/PPTX text or missing dependencies cannot masquerade as successful engineering extraction.
- SQLite draft write remains 503 with no mutation; native teacher-B read/update cannot access teacher-A drafts.
- Zero/skipped selectors, child timeout, changed frozen source or missing cleanup must make the runner fail.

## Tasks and files

1. Modify `backend/tests/test_teacher_lesson_prep_api.py` and `test_teacher_lesson_prep_catalog.py`; add `backend/tests/support/courseware_synthetic.py`. Preserve existing assertions' behavior with explicit small-fixture counts, real page/slide text/citations, refresh and path guards. Rename the SQLite success assumption to an explicit 503/no-write negative test; relocate success semantics to native MySQL.
2. Add `backend/scripts/verify_lesson_prep_courseware.py` and `backend/tests/test_lesson_prep_courseware_operator.py`. Interface: `verify_pack(frontend_root: Path, manifest_path: Path) -> dict`; CLI requires both paths, emits JSON, exits nonzero on every unmet prerequisite. Manifest v1 carries declared official source/acquisition/authorization provenance, `synthetic=false`, exact relative-file inventory, byte sizes and SHA256. The manifest is an operator assertion, not independent proof of course rights/content. Original totals stay 97/58 PDF/38 PPT/1 PPTX/39 slides.
3. Add `backend/tests/native_teacher_lesson_prep.py`, `support/lesson_prep_full_app_scenario.py`, and `run_teacher_lesson_prep_acceptance.py`. Reuse previous owned native server/database wrappers and real app scenario authentication/guard/recording; run one dedicated draft lifecycle on a fresh schema. Unified runner executes the complete expanded ordinary selection and this native selector in separate blank-cwd processes, validates Junit selector counts/no skips/failures, immutable source hashes and cleanup receipts.
4. Add stage report/evidence JSON. Preserve baseline RED, all GREEN commands/counts/exit codes/source hashes, review and cleanup; explicitly keep actual教材/live provider/CI unverified.

## Execution checklist

- [x] Reproduce the original nine failures in an isolated baseline run (RED).
- [x] Write operator fail-closed assertions, observe the absent verifier failure, implement and verify GREEN.
- [x] Add valid synthetic documents; make legacy engineering checks independent of repository course originals; verify all parsing/citation assertions.
- [x] Verify SQLite 503/no-write and successful real-MySQL teacher isolation through actual app routes.
- [x] Freeze sources, independent review, complete expanded ordinary and native acceptance; retain cleanup receipts.
- [ ] Explicit files only, ordinary commit, report candidate to parent and await CAS before push.
