# CSV Input Validation Plan — test-auto-002 (Revision 2)

## Purpose

End-to-end integration test of the SMA autonomous peer-review workflow (Phase C3B).
This revision addresses round-1 feedback: undefined schema, unspecified parsing,
encoding, error handling and resource limits, missing acceptance tests, and the
conflation of error collection with passing invalid data downstream.

## Research Question

What is the minimum set of validations a CSV file must pass before it can be safely
consumed by a downstream data processor?

## Processor Contract

- **Schema ownership:** The downstream processor owns the column schema. The validator
  receives it as a declarative input (ordered list of column name, type, required flag,
  and optional value constraints such as range, enum, or regex) and does not hard-code it.
- **Header rule:** The header must contain every required column exactly once, with no
  duplicates and no empty names. Column order is not significant unless the schema
  marks it as ordered. Unknown extra columns are rejected by default (configurable).
- **Value constraints:** Each field is checked against its declared type and constraints.
  Empty values are accepted only for columns not marked required.
- **Handoff:** The validator outputs either a fully valid file (accepted) or nothing
  (rejected) plus a report. Invalid data is never passed downstream.

## Parsing Rules

- Parse per RFC 4180: quoted fields may contain commas, CRLF/LF newlines, and doubled
  quotes (`""`). Unterminated quotes are a fatal error.
- **Encoding:** Accept UTF-8, with or without BOM (BOM is stripped). Reject UTF-16 and
  other encodings with a clear error rather than transcoding. Invalid UTF-8 byte
  sequences are rejected.
- **Line endings:** CRLF and LF are both accepted; mixed endings are accepted but
  recorded as a warning in the report. Field counts are computed after parsing, not by
  splitting on newlines.
- A trailing newline at end of file is permitted; blank lines elsewhere are errors.

## Validation Steps

1. Confirm the file exists, is a regular file, and is readable.
2. Check size against the limit (below) before reading content.
3. Confirm the file is non-empty and decodes as valid UTF-8 (BOM stripped).
4. Parse the header and validate it against the schema (Header rule).
5. Stream-parse each row; verify field count equals header count and every field
   satisfies its type and value constraints.
6. Enforce row, field, and error-count limits during streaming.
7. Emit the report and the accept/reject decision.

## Resource Limits (defaults, configurable)

| Limit | Default |
|---|---|
| Max file size | 100 MB |
| Max rows | 1,000,000 |
| Max fields per row | 256 |
| Max field length | 64 KiB |
| Max errors collected | 100 |

Exceeding any limit is a rejection with a limit-specific error code. Parsing is
streaming so memory use is bounded independent of file size.

## Error Policy

- **Collect, then reject.** The validator collects up to the max-errors limit (each with
  row number, column, and error code) so users can fix many problems in one pass.
  Collection is purely diagnostic: any error means the whole file is rejected.
- Fatal errors (unreadable file, bad encoding, unterminated quote, limit exceeded) stop
  immediately. Row-level errors are collected.
- Warnings (mixed line endings) never cause rejection.
- A strict mode (halt at first error) is available for fast-fail pipelines; the
  decision outcome is identical, only the report is shorter.
- Exit status is deterministic: 0 accepted, 1 rejected, 2 operational failure.

## Acceptance Test Matrix

| # | Input | Expected |
|---|---|---|
| 1 | Valid file matching schema | Accept |
| 2 | Nonexistent / unreadable file | Reject (fatal, exit 2) |
| 3 | Empty file (0 bytes) | Reject |
| 4 | Header only, no rows | Accept (zero data rows) unless schema requires ≥1 |
| 5 | Missing required column | Reject |
| 6 | Duplicate or empty header name | Reject |
| 7 | Row with too few / too many fields | Reject, row number reported |
| 8 | Value violating type or constraint | Reject, row and column reported |
| 9 | Quoted field containing comma and newline | Accept, counted as one field |
| 10 | Unterminated quote | Reject (fatal) |
| 11 | UTF-8 with BOM | Accept, BOM stripped |
| 12 | UTF-16 file | Reject (encoding) |
| 13 | Invalid UTF-8 bytes | Reject |
| 14 | Mixed CRLF/LF | Accept with warning |
| 15 | File over size limit | Reject before parsing |
| 16 | Row count over limit | Reject (fatal) |
| 17 | >100 bad rows | Reject, report truncated at 100 errors |
| 18 | Strict vs. collect mode on same bad file | Same decision, different report length |

## Resolved Open Questions

1. Strict vs. permissive: both modes supported; the decision is always reject-on-any-error.
2. Limits: defined above and configurable.
3. Schema ownership: the downstream processor.

## Remaining Risks

- Default limits are illustrative and should be tuned to the real processor.
- Schema format (JSON vs. YAML) is not yet chosen.

## Expected Outcome

A specified validator contract with deterministic accept/reject behavior, bounded
resource use, and a testable pass/fail matrix, ready for acceptance review.
