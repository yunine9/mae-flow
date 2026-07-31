# Lightcheck Structural Nesting Design

## Problem

Lightcheck currently reports Lizard's McCabe cyclomatic complexity as
`MF-CC-5`. McCabe complexity counts every decision, so six parallel `if`
statements cross the threshold even though the code is only one control level
deep. Mae-Flow intends this advisory rule to detect hard-to-read nesting, not
the total number of independent branches.

## Required Semantics

- Measure the maximum structural control nesting inside each function.
- A top-level control statement has depth 1.
- Parallel `if`, loop, `case`, `catch`, or equivalent statements do not
  accumulate.
- `else if` / `elif` stays at the depth of the original branch.
- A control statement inside another control body increases depth by one.
- Boolean operators and ternary expressions do not increase structural depth.
- Depth 5 is allowed; depth greater than 5 is reported.
- Existing changed-function scope, baseline debt, fail-open behavior, timeout,
  generated-code exclusions, and supported-language boundaries remain
  unchanged.

## Implementation

Add a small first-party Lizard token processor dedicated to structural nesting.
For brace-based languages it tracks control bodies, including braceless bodies,
without counting boolean operators. For Python it consumes the indentation
nesting already maintained by Lizard's Python reader. The processor writes
`max_nesting_depth` onto each parsed function.

Lightcheck reads `max_nesting_depth` instead of
`cyclomatic_complexity`. The public finding becomes:

- rule: `MF-NEST-5`
- metric: `max_nesting_depth`
- message: `函数控制结构嵌套深度超过 5`

The old `MF-CC-5` rule is removed rather than kept as a second warning.

## Verification

Regression tests cover C++, Java, JavaScript/TypeScript, and Python:

- many parallel branches remain at depth 1 and do not report;
- six nested control bodies report `MF-NEST-5`;
- `else if` / `elif` chains remain flat;
- compound boolean conditions remain at depth 1;
- exact depth 5 remains clean;
- baseline debt behavior continues to compare the new metric.

