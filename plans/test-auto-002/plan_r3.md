# CSV Input Validation Plan — test-auto-002 (Revision 3)

## Purpose

End-to-end integration test of the SMA autonomous peer-review workflow (Phase C3B).
This revision addresses round-2 feedback: ambiguous schema semantics (presence vs.
nullability, types, minimum rows), inconsistent decision/exit-code mapping, memory
bounds that streaming alone does not guarantee, unit ambiguity, and an unspecified
integrity-preserving handoff. This document is a plan only; it does not authorize
implementation or execution.

## Research Question

What is the minimum set of validations a CSV file must pass before it can be safely
consumed by a downstream data processor?

## Processor Contract

### Schema (declarative input, owned by the downstream processor)

Top-level settings:
- `columns`: ordered list of column definitions (below).
- `ordered` (bool, default false): whether header order must match `columns` order.
- `allow_extra_columns` (bool, default false): if false, unknown header columns are rejected.
- `min_rows` (int, default 0): minimum number of data rows. A header-only file is accepted
  iff `min_rows` = 0.
- `max_rows` (int, optional): schema-level cap, bounded by the global limit below.

Per-column definition:
- `name` (non-empty, unique).
- `type`: one of `string`, `integer`, `decimal`, `boolean`, `date` (ISO 8601 `YYYY-MM-DD`),
  `timestamp` (RFC 3339).
- `required` (bool): the column **must be present in the header**. Concerns presence only.
- `nullable` (bool, default false): whether an **empty value** is allowed in a row.
  Independent of `required`; all four combinations are valid and tested.
- `constraints` (optional): `min`/`max` (integer, decimal, date, timestamp),
  `min_length`/`max_length` (string, in Unicode code points), `enum` (list of strings),
  `regex` (full-match, linear-time engine only to avoid ReDoS).

### Type and conversion policy

- Strict, no coercion: values are checked against the type's lexical grammar exactly as
  written. No trimming, locale-specific parsing, thousands separators, or implicit
  casting. `integer`: `-?[0-9]+`, must fit signed 64-bit. `decimal`: `-?[0-9]+(\.[0-9]+)?`.
  `boolean`: `true` or `false` (lowercase). Unknown type names make the schema invalid
  (operational failure, see Outcome Mapping).
- An empty value (zero-length after CSV unquoting) is "null". If the column is not
  nullable, null is a validation error; if nullable, type and constraints are skipped.
- The validator never rewrites data; the snapshot contains the original bytes.

### Handoff (integrity-preserving)

- The validator reads input exactly once, copying bytes into a private staging file
  (created with exclusive, owner-only permissions in a directory the validator controls)
  while validating the same bytes it copies. The source path is never reread.
- While copying, total bytes are counted; exceeding the byte limit aborts immediately,
  so growth of the file during reading cannot bypass the limit.
- Only after complete successful validation is the staging file fsynced, made read-only,
  recorded with its SHA-256 and byte length, and atomically renamed to the published
  snapshot path. The processor receives the snapshot path plus digest and verifies the
  digest before use.
- On rejection or operational failure the staging file is deleted and nothing is
  published. A crash leaves only staging files, which the processor never reads and which
  are cleaned up on the next run.
- The input file changing during reading is not an error condition for correctness:
  what is validated is exactly what is published. If the source's size/mtime differ
  after reading, a warning is recorded.

## Parsing Rules

- Parse per RFC 4180: quoted fields may contain commas, CRLF/LF newlines, and doubled
  quotes (`""`). Unterminated quotes are a fatal validation error (reject).
- **Encoding:** Accept UTF-8, with or without BOM (BOM stripped). Reject UTF-16 and other
  encodings (detected by BOM or invalid UTF-8) rather than transcoding. Invalid UTF-8
  sequences are rejected.
- **Line endings:** CRLF and LF accepted; mixed endings accepted with a warning. Field
  counts are computed after parsing, not by splitting on newlines.
- A trailing newline at end of file is permitted; blank lines elsewhere are errors.

## Units and Resource Limits (defaults, configurable)

Units are exact: "MiB" = 2^20 bytes, "KiB" = 2^10 bytes. Sizes are in bytes of the raw
(pre-decode) input unless stated; "field length" is in raw bytes of the unquoted field
content.

| Limit | Default |
|---|---|
| Max file size | 100 MiB (104,857,600 bytes) |
| Max rows (data rows, excl. header) | 1,000,000 |
| Max fields per row | 256 |
| Max field length | 64 KiB (65,536 bytes) |
| Max record length (raw bytes incl. quotes/delimiters) | 1 MiB (1,048,576 bytes) |
| Max errors stored | 100 |
| Max error-message length | 256 bytes |

A limit is exceeded only when the value is **strictly greater** than the limit; a value
equal to the limit is accepted.

### Enforcement during parsing (before buffering)

- The parser uses a fixed-size read buffer and counts bytes, current field length,
  current record length, and field count incrementally. Each counter is checked as bytes
  are consumed, so the parser aborts the moment a limit is crossed and never accumulates
  an oversized field or record in memory. An unterminated quote is therefore cut off by
  the field/record limit, not by end of file.
- Memory is bounded by: read buffer + one record (≤ max record length) + the error list
  (≤ 100 entries × ≤ 256 bytes) + schema. It is independent of file size and row count.
- The report is likewise bounded: error entries beyond the cap are counted
  (`errors_truncated_count`, a single integer) but not stored; echoed field values in
  messages are truncated to the message-length limit.

## Outcome Mapping (single source of truth)

Every outcome has exactly one decision, exit status, and error class.

| Class | Decision | Exit | Examples |
|---|---|---|---|
| Accepted | accept (snapshot published) | 0 | Valid file, with or without warnings |
| Validation failure | reject | 1 | Bad header, bad row/field, bad encoding, unterminated quote, any limit exceeded, unsupported/UTF-16 content |
| Operational failure | no decision (nothing published) | 2 | Input missing/unreadable/not a regular file, invalid schema file, staging/publish I/O error (disk full, rename or fsync failure), digest-write failure |

Rule: exit 1 means "the input was read and is not acceptable"; exit 2 means "no
determination could be made about the input" and is retriable after fixing the
environment. A missing or unreadable input file is therefore **operational (exit 2)**,
not a rejection. Warnings never change the decision.

## Validation Steps

1. Load and validate the schema; invalid schema → exit 2.
2. Open input; confirm it is a regular, readable file (else exit 2). Record size hint;
   if the hint already exceeds the limit, reject early (exit 1) — this is an
   optimization only; the authoritative check is the byte count during the read.
3. Stream bytes into the staging file while decoding and parsing (UTF-8, BOM stripped);
   empty (0-byte) input is rejected.
4. Validate the header against the schema (presence of `required` columns exactly once,
   no duplicate/empty names, extras and order per settings).
5. For each row: field count equals header count; each field satisfies type, nullability,
   and constraints. Enforce all limits as bytes are consumed.
6. After EOF: check `min_rows`/`max_rows`.
7. If no errors: finalize and publish snapshot atomically (see Handoff), exit 0.
   Otherwise: delete staging, emit report, exit 1. Any I/O failure → delete staging, exit 2.

## Error Policy

- **Collect, then reject.** Row-level errors are collected (up to 100 stored; each with
  row number, column, error code) for diagnostics only; any error rejects the whole file.
- Fatal validation errors (bad encoding, unterminated quote, limit exceeded) stop parsing
  immediately and reject (exit 1).
- Strict mode halts at the first error; the decision and exit code are identical to
  collect mode for the same input, only the report is shorter.
- Report is machine-readable (JSON) with: decision, exit status, error class, stored
  errors, `errors_truncated_count`, warnings, byte/row counts, and snapshot digest (on accept).

## Acceptance Test Matrix

| # | Input / condition | Expected decision | Exit |
|---|---|---|---|
| 1 | Valid file matching schema | Accept, snapshot published, digest matches | 0 |
| 2 | Nonexistent input path | No decision, nothing published | 2 |
| 3 | Unreadable input (permissions) / directory given | No decision | 2 |
| 4 | Invalid schema (unknown type, duplicate column name) | No decision | 2 |
| 5 | Empty file (0 bytes) | Reject | 1 |
| 6 | Header only, `min_rows`=0 | Accept | 0 |
| 7 | Header only, `min_rows`=1 | Reject | 1 |
| 8 | Missing `required` column | Reject | 1 |
| 9 | Duplicate or empty header name | Reject | 1 |
| 10 | Extra column, `allow_extra_columns` false / true | Reject / Accept | 1 / 0 |
| 11 | Column order differs, `ordered` true / false | Reject / Accept | 1 / 0 |
| 12 | `required`=false column absent from header | Accept | 0 |
| 13 | Empty value: nullable=false / nullable=true (required either way) | Reject / Accept | 1 / 0 |
| 14 | Type violations: `integer` "1.5", " 1", "1,000", 2^63; `boolean` "True"; bad date | Reject, row+column reported | 1 |
| 15 | Constraint violations: min/max, enum, regex, max_length | Reject, row+column reported | 1 |
| 16 | Row with too few / too many fields | Reject, row number reported | 1 |
| 17 | Quoted field containing comma and newline | Accept, one field | 0 |
| 18 | Unterminated quote (small file) | Reject (fatal) | 1 |
| 19 | Unterminated quote followed by >1 MiB of data | Reject at record limit; peak memory stays within bound | 1 |
| 20 | UTF-8 with BOM | Accept, BOM stripped | 0 |
| 21 | UTF-16 file | Reject (encoding) | 1 |
| 22 | Invalid UTF-8 bytes | Reject | 1 |
| 23 | Mixed CRLF/LF | Accept with warning | 0 |
| 24 | File of exactly 104,857,600 bytes (otherwise valid) | Accept | 0 |
| 25 | File of 104,857,601 bytes | Reject | 1 |
| 26 | File grows past the byte limit while being read (size hint under limit) | Reject on byte count; nothing published | 1 |
| 27 | Exactly 1,000,000 rows / 1,000,001 rows | Accept / Reject | 0 / 1 |
| 28 | Exactly 256 fields per row / 257 | Accept / Reject | 0 / 1 |
| 29 | Field of exactly 65,536 bytes / 65,537 bytes | Accept / Reject | 0 / 1 |
| 30 | Record of exactly 1,048,576 bytes / 1,048,577 bytes | Accept / Reject | 0 / 1 |
| 31 | >100 bad rows | Reject; 100 errors stored, `errors_truncated_count` correct, report size bounded | 1 |
| 32 | Strict vs. collect mode on same bad file | Same decision and exit, different report length | 1 |
| 33 | Source file mutated after validation begins | Published snapshot digest equals digest of bytes actually validated; mismatch warning recorded | per content |
| 34 | Source replaced/appended between validation and processor start | Processor reads snapshot, unaffected; digest verifies | 0 |
| 35 | Disk full / write error while staging | No snapshot, staging removed | 2 |
| 36 | Rename/fsync failure at publish | No snapshot visible, staging removed | 2 |
| 37 | Crash (kill) mid-validation | No published snapshot; stale staging ignored and cleaned next run | n/a |
| 38 | Processor given snapshot with altered bytes | Digest verification fails; processor refuses | n/a |
| 39 | Rejected file (any validation failure) | No snapshot path exists afterwards | 1 |
| 40 | Memory profile on 100 MiB file vs. 1 MiB file | Peak memory comparable (within fixed bound) | 0 |

## Resolved Open Questions

1. Strict vs. permissive: both supported; decision and exit code are identical.
2. Limits: defined with exact units, boundary semantics, and in-parse enforcement.
3. Schema ownership: the downstream processor; `required` (presence) and `nullable`
   (empty values) are separate; types and `min_rows` are defined.
4. Missing/unreadable input: operational failure (exit 2), not a rejection.
5. Handoff: validated private snapshot with digest, published atomically only on success.

## Remaining Risks

- Default limits are illustrative and should be tuned to the real processor.
- Schema serialization format (JSON vs. YAML) is not yet chosen; the semantics above are
  format-independent.
- Snapshot storage needs up to the max file size in free disk; the processor must
  clean up consumed snapshots (retention policy to be defined).
- Atomic rename requires staging and snapshot directories on the same filesystem.

## Expected Outcome

A specified validator contract with unambiguous schema semantics, one consistent
decision/exit mapping, parse-time enforcement of exact-unit limits, an
integrity-preserving handoff, and a testable pass/fail matrix with boundary and failure
cases, ready for acceptance review.
