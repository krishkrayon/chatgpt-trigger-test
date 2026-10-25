# Dummy Connectivity Test Plan — test-dummy-001

## Purpose

This is an isolated connectivity test for the SMA GitHub peer-review workflow.

It contains no research findings, no trading instructions, no credentials, and no
implementation recommendations.

## Test objective

Verify that:
1. Claude Code can create a branch, commit, and push a plan file to this repository.
2. ChatGPT Work receives the pull_request.opened trigger.
3. ChatGPT Work reads this file from the specified commit SHA.
4. ChatGPT Work posts a structured `SMA_REVIEW_COMPLETED` comment.
5. Claude Code can retrieve and validate the feedback comment.

## Content

No SMA research content is included. This file is safe to review without any domain knowledge.

## Expected outcome

Status: ACCEPTED (no findings; this is a connectivity test only).
