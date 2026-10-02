# Partition worker lifetime recovery

## Failure modes recorded before implementation

Small correctness fixtures and short resource pilots do not establish memory
behaviour across a complete sequence of partitions. Closing a DuckDB connection
does not guarantee that every native allocation is returned by a persistent
Python process. The underlying allocator or leak mechanism remains unconfirmed.

The retained worker lifecycle E2E must cover these concrete failures:

- A persistent worker retains touched native pages between jobs. A one-worker
  route can instead retain them in the controller. Both require independent
  native process observations across the complete synthetic job sequence.
- More jobs are submitted than the requested concurrency, or a replacement
  starts before the previous process has exited.
- A worker exception or abrupt exit submits later jobs, loses the error, leaves
  active children behind, or produces a false passing result.
- Closing the result iterator leaves active processes or descriptors behind.
- Controller death releases the advisory lock while an active child still owns
  work. The same lock handoff is required at one, two and four workers.
- Empty/uneven job lists lose jobs or change the existing `(job, result)` surface.
- Isolation changes schemas, keys, NULLs, duplicates, routing, calendar-day
  definitions or the independence of the two variants. Existing execution and
  product E2Es retain their independent clinical and multiset oracles.

The implementation uses bounded executors with one spawned process and one job
each. Executor shutdown must join that process before its slot is replaced or a
result is exposed. Submitted work is drained on failure or iterator closure;
no subsequent job is scheduled. Private verification must use the actual
installed build and validation paths over their complete declared sequence.
Synthetic process evidence does not establish private resource acceptance.
