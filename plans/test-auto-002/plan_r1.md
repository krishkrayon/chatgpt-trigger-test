# CSV Input Validation Plan — test-auto-002

## Purpose

This is an end-to-end integration test of the SMA autonomous peer-review workflow
(Phase C3B). The plan is intentionally incomplete so that a reviewer can provide
meaningful feedback across multiple rounds.

## Research Question

What is the minimum set of validations a CSV file must pass before it can be safely
consumed by a downstream data processor?

## Proposed Validation Steps

1. Confirm the file exists and is readable.
2. Confirm the file is non-empty.
3. Parse the first row as a header and verify it is non-empty.
4. Verify every subsequent row has exactly the same number of fields as the header.

## Known Gaps

The following issues are unresolved and should be addressed by the reviewer:

- **Column names:** The plan does not define which column names are required or
  in what order. Without a schema, step 3 is incomplete.
- **Encoding:** UTF-8 BOM, UTF-16, and mixed line endings (CRLF vs LF) are not
  handled. A file with these characteristics will fail silently or produce
  incorrect field counts.
- **Quoting and escaping:** RFC 4180 allows quoted fields containing commas and
  newlines. The plan does not address these cases.
- **Error policy:** When a row fails validation, the plan does not specify whether
  the processor should skip the row, halt, or log a warning.
- **File size:** No upper bound on file size is proposed. A 10 GB file would pass
  all four steps without warning.

## Open Questions

1. Should validation be strict (halt on first error) or permissive (collect all
   errors, then report)?
2. Is there a maximum acceptable row count or file size?
3. Who owns the column schema — the validator or the downstream processor?

## Expected Outcome

Pending reviewer feedback. This section will be completed in the accepted round.
