# Moonlight Branch Resolution Design

## Problem

Moonlight suppresses interactive questions, but `branch_create` still assumes a
fresh user acknowledgement. When a delivery resumes on an existing branch, the
workflow can neither safely adopt the branch nor explain why adoption is unsafe.
Agents may then invent an acknowledgement or try destructive Git operations.

## Decision

Before `branch_create done` checks its normal evidence, Moonlight performs one
small, deterministic branch-resolution step:

1. If the activation request explicitly says to continue the current/existing
   branch, adopt it only when the current branch is not the base branch and the
   recorded base HEAD is its ancestor.
2. Otherwise adopt a continuation only when `.mae-flow.json.last` proves the
   same ticket, same branch, and its recorded HEAD is an ancestor of current
   HEAD.
3. A fresh request at the base HEAD follows the existing branch-creation flow.
4. An existing non-base branch with ambiguous provenance, or whose history does
   not contain the base HEAD, records a Moonlight blocker and stops.

Branch names containing a ticket are not proof. Moonlight never synthesizes a
user acknowledgement and never merges, cherry-picks, or resets to manufacture
one.

## Receipt

Safe adoption stores `branch_resolution` with:

- source: `moonlight-request` or `moonlight-continuation`;
- current branch and HEAD;
- base branch and recorded base HEAD;
- Moonlight request SHA;
- for continuation, previous ticket, branch, HEAD, and last-state SHA;
- resolution time.

## Scope

The normal interactive workflow remains unchanged. The change is limited to
Moonlight `branch_create`, its prompt, README guidance, and focused tests.
