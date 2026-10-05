# Teacher Work Office exporter source slice

Date: 2026-10-04 UTC
Status: four finite offline byte matrices passed; application integration and actual Office acceptance remain open.

## Implemented

- Native editable PPTX text boxes, columns, speaker notes and source text in six fixed layouts, at 16:9 geometry
- A versioned white/light-gray/red GeZhi theme, 24-point body text and conservative density checks that reject overflow without clipping or dropping content
- DOCX mapping of a frozen lesson through the unchanged legacy exporter, rejecting input that its normalization would alter
- Deterministic byte packaging, frozen-input preservation, exact content/digest/evidence comparison and bounded ZIP/XML validation
- Narrow removal of known vendor bootstrap metadata only; changed, partial or unexpected content is rejected instead of sanitized

Public functions are build_pptx, build_docx and validate_office_bytes. These modules return or inspect bytes; they do not write files, run converters, fetch fonts or contact external services. Named font families are disclosures, not proof of availability or redistribution rights.

## Verification

Four finite test matrices passed, with all twelve setup/call/teardown phases passing:

1. Native Chinese PPTX: 6/8/12 slides, six layouts, exact text/notes/sources, geometry, font size, input preservation and deterministic repeated builds
2. Density: bounded Chinese/newline overflow cases refused without clipping, truncation, undersized text or added pages
3. DOCX: 45- and 60-minute lessons, paragraphs/tables/lists/summary/citations, strict frozen mapping and repeated-byte determinism
4. OOXML: malformed archives, unsafe relationships/XML/parts, version mismatches, exact cleanup and reviewed security regressions

These tests actually construct synthetic PPTX/DOCX bytes, independently inspect ZIP/XML and reopen valid output using python-pptx/python-docx. They are not mock-writer tests or a whole-project test pass.

Three issue families were observed failing before correction and passed afterward: unsupported ZIP flag/decompression exceptions escaping controlled validation; extra grouped slide text bypassing the frozen projection; and XML comments being discarded during narrowly permitted metadata cleanup. The corrected validator rejects unsupported content before convenience-library reopening and normalizes only specific parser exceptions.

## Limits and remaining work

Files are limited to 10 MiB compressed, 256 members, 1 MiB per XML part and 8 MiB total uncompressed content. Builders use cooperative 30-second checkpoints; later orchestration must provide cancellation and supervision of individual blocking calls.

Actual PowerPoint/Word opening, editing, all-page rendering, Chinese font substitution, pagination and visual overflow have not been tested. Structural checks and library reopening do not establish those outcomes.

Production import assembly, dependency/license acceptance, immutable version freezing, real transactions, private artifact storage, downloads, providers and desktop UI integration remain pending. The legacy eager package initializer remains unchanged; isolated exporter-body tests do not establish its production importability.

Teacher Work capabilities remain disabled. Classroom publishing and rendered-preview capability remain closed. This is the pure exporter portion of Task8, not the completed Teacher Work feature.
