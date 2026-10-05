# Teacher Work Task4a bounded chat decisions

Date: 2026-10-05 UTC
Stage: pure prompt/result shaping and run decisions; production gates remain closed

## Included

- Canonical prompt data with the current input and at most eleven whole recent history messages, bounded to 24000 Unicode characters including wrappers and selected evidence
- Exact owner/task/revision checks, selected evidence preservation and explicit refusal when the current input plus evidence exceeds the bound
- A separate fixed system prompt that treats history/evidence as quoted data and limits output to four text candidate types
- Strict actual JSON result parsing: bounded UTF8 bytes, duplicate/nonfinite/authority-field rejection, original DTO validation, selected reference checks and server-derived omission
- Exact command/receipt comparisons, cumulative local call/repair/attempt budgets and supplied-deadline call limits
- Pure slot/owner-lease/current-context comparisons and detached cancellation/interruption values

No helper calls a provider, executes a candidate, reserves a durable run/lease or saves a reply. Cancellation values do not prove an upstream call stopped; a live local call must still hold its lease. Dead-process facts are supplied, not discovered by these functions. Deadlines are supplied and never renewed implicitly.

## Verification

33 finite pure source/contract cases passed: five chat cases, seven run-decision cases and the retained 21 contract cases. All twelve new cases were observed failing on their missing modules before implementation.

Tests invoke production helpers with synthetic DTOs, JSON strings and fixed UTC snapshots. They establish shaping, validation and comparison behavior. No actual AI reply, provider/executor, persisted history/run, identity transaction, database or remote cancellation was exercised.

## Still pending and closed

Task4b requires durable exact binary run/message keys, repair counts and message result-type/omission metadata; coordinated schema/DTO/SQL changes; atomic run/message/lease admission and completion; durable budgets/call tokens; real slot, lease release and recovery; and a strict bounded provider bridge.

Aggregate chat deadline policy, fresh authorization after provider return, actual identity/account-incarnation/namespace/teaching/MySQL/HTTP acceptance and legacy integration remain release gates. Existing provider model/settings, legacy AI preparation and saves remain unchanged. This is a bounded Task4a pure slice, not live chat, full Task4 completion or an enabled Teacher Work feature.
