# Dummy Test Plan — Phase A (Round 3)

## Objective
Verify that the review-feedback loop works end to end: a plan revision is submitted, a review is returned, and a revised plan is produced for the correct plan, round, and commit.

## Scope
- Limited to this repository, under `plans/test-dummy-001/`.
- No code execution.
- No access to trading systems or any other external system.
- The only artifacts produced are plan markdown files.

## Request-to-Feedback Sequence
1. A plan revision (`plan_r2.md`) is committed on the review branch and a pull request is opened or synchronized.
2. The trigger fires and records the Plan-ID, Round, PR number, and head commit SHA.
3. The reviewer returns feedback tied to those identifiers.
4. The automation supplies the validated metadata and the feedback to the revision step.
5. The revision step reads the current plan and the feedback, then writes the next plan file (`plan_r3.md`).

## Pass/Fail Checks
| Check | Pass | Fail |
|---|---|---|
| Plan-ID | Feedback and output both carry `test-dummy-001` | Missing or different ID |
| Round | Feedback is for round 2 and the output is round 3 | Round mismatch or skipped round |
| PR number | Feedback is attached to the PR that was triggered | Different or missing PR |
| Head-SHA | Feedback SHA exactly matches the verified commit (`136ba6d3fb01efcb8829945c2eb883619fe9e8b4`) | Any difference, including an abbreviated or stale SHA |
| Duplicate suppression | One trigger for a given Plan-ID, Round, and SHA yields exactly one review and one revision | A second review or revision for the same combination |
| Output path | Only `plans/test-dummy-001/plan_r3.md` is written | Any other file written |

## Success Criteria
All checks above pass in a single run with no manual intervention.

## Failure Handling
If any check fails, record which one failed, make no further revisions, and report the failure for manual review.
