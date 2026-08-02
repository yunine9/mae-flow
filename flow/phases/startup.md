## Objective
Confirm one complete operational card and choose Full or Focused delivery with a commit pace that fits the work.

## Inspect
Read the requirement source, repository defaults, current Git branch, initial
dirty files, affected boundaries, and known risks. Read
`docs/specs/index.md` when it exists, select only relevant
business capability domains, and read only their behavior documents. A missing index is
valid and does not block first use.

## Stop for the user
Present worker, ticket and type, requirement source, Full/Focused,
Continuous/Staged, base and derived working branches, exact Build route, UT
generation, UT run entry, and the natural-language quality combination in one
card. For C++, the Build route may be the configured `build-fix` Skill; for
Java/Maven use the confirmed Maven command (normally `mvn compile -q`); for any
other project record the exact repository Skill or command. Stop once for natural-language
confirmation or modification. Ask separately only for genuine domain ambiguity
or an irreversible action.

## Outputs
Record the complete configuration, selected business domains, path, pace,
initial dirty files, and unresolved risks. Derive the working branch as
`{base}_{worker}_{ticket}` unless the confirmed card supplies another exact
branch. Immediately create or switch to that confirmed working branch after
Intake; do not postpone branch placement until Delivery. Declare local Spec,
Story, and UT-handoff paths only for Full; Focused
adds them only if it upgrades to Full.

## Next
Full proceeds to Spec; Focused proceeds to Construction. The next meaningful action is to confirm the selected route.
