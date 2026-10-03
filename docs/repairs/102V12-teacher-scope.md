# 102V12 teacher scope

## Security boundary

Teacher access uses the trusted server-side `TEACHER_STUDENT_ASSIGNMENTS` JSON mapping provided by `app.api.deps.teacher_student_ids`. Keys are authenticated teacher usernames; values are student usernames. Missing, malformed, or empty assignments grant no students. Class names and editable student-number aliases never establish authority.

Analytics cards, search, evidence, activity aggregates and diagnosis review queues include only assigned student accounts. Student identity fields use canonical usernames rather than row indices. Individual self-service reads/completion remain authenticated and subject-scoped.

Cached analytics advice, actions and interaction records are teacher-owned and carry explicit student recipients; records whose recipient set no longer fits the roster are hidden. Unowned historical cache records are not implicitly adopted.

Both interaction dispatch routes expand omitted/empty target lists only to actual assigned students, reject foreign or zero-recipient targets before writing, and derive initial counts from distinct real recipients. Client-selected record keys cannot overwrite existing dispatches. Patching cannot change the audience. Completion requires an authorized recipient and remains idempotent.

Dashboard interventions derive the author from authentication, require an assigned target, generate fresh IDs and explicitly target generated homework. Dashboard student interaction/notification views require explicit recipients; old unbounded broadcasts are not treated as worldwide student broadcasts.

Diagnosis review detail, review state, notes and watch flag operations enforce assignment in the service before access or mutation. Weak points use the same latest assigned-account snapshot population. Alternate editable student IDs are display data, not aliases for access control.

## Empty deployment / migration

An unconfigured teacher sees empty student/review/interaction queues and zero student aggregates. Dispatch is rejected (403), never fabricated as 48 recipients. Configure verified assignments outside the user-editable profile system before using teacher workflows. Legacy unowned caches must be regenerated; historical unrestricted broadcasts are intentionally hidden. Existing snapshot identifiers must reference canonical usernames.

## Validation

`backend/tests/test_teacher_scope_repair.py` exercises actual handlers and services against disposable SQLite in-memory tables with two students in the same editable class. Related teacher review tests now provide explicit assigned-account fixtures and synthetic snapshots without starting diagnosis workflow/model work.
