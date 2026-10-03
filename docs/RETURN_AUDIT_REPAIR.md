# Narrow return audit repair (2026-10-03)

## Failure scenarios recorded before implementation

The existing synthetic return workflows lack these independent counterexamples:

- A return end marked derived or having NULL, mixed or unsupported precision
  currently permits ICD/gas positives. Expect valid-start all-cause count 1,
  interval-dependent positive count 0, NULL flag and unavailable count 1.
- Two source rows with the same observed start date and conflicting end dates
  currently suppress the all-cause event. Expect the same results as above;
  genuine conflicting start dates and invalid date order remain rejected.
- Source components with identical calendar dates but different clock times
  currently appear conflicting, or fail ED/inpatient progression. Expect the
  same outcomes as their date-only counterparts, retaining all raw rows.
- Unknown-precision starts outside a horizon currently bound possible events.
  Expect NULL timing and unresolved flags at every horizon; derived and unknown
  dates cannot establish either inclusion or exclusion from a time window.
- A concurrent writer can create the report during `validate-returns` and have
  it overwritten on either validation success or failure. Expect nonzero exit
  and identical competing bytes. Existing passed/failed reports are immutable;
  fresh execution failures retain their own failed report.

Extend existing retained partition and product E2Es, using hand-authored results
and source-based independent validation. Retain semantic corruption cases that
must fail even when output hashes are refreshed. No new isolated/unit suite is
needed. Run the affected existing execution/product workflows and hosted CI.

## Owner-approved scope

The owner approved revision 2: exclude unusable dates from timing decisions,
preserve provenance and reasons, use calendar dates, repair the report race,
and qualify this code revision only. No private impact screen, regenerated
product, downstream work or general clinical-eligibility framework is included.
Historical private acceptance retains its original implementation identity.

## Qualification and delivery

The retained v2 partition E2E passed 13 hand-authored audit cases and rejected
16 semantic corruptions, including falsely qualified evidence, invented timing
and a false positive summary. The execution and product E2Es passed; the latter
retains six actual CLI cases using a native synthetic build and validator:
fresh success/failure, existing successful/failed reports and competing writes
on validation success/failure. Independent readback verified artifact hashes
and unchanged columns/types across all six public tables. Ruff and diff checks
are required alongside final-head hosted CI and hosted artifact readback.

The existing CI workflow now runs and retains the v2 partition driver alongside
its other return E2Es. This is a dependent repair branch based on qualified PR26;
the upstream and child migration branches retain their existing scope. The
corrections provide engineering qualification, not new private acceptance.
