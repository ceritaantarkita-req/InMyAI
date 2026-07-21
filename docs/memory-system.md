# Persistent Memory and Context Engine

## Memory classes

- working: current task state
- episodic: events and previous attempts
- semantic: stable project facts
- procedural: repeatable processes
- artifact: references to files and outputs
- decision ledger: approved choices with active/superseded state

## Context compilation

A request does not receive the entire conversation or repository. The compiler gathers:

1. active decisions
2. recent/relevant memories
3. FTS-ranked file excerpts
4. source paths
5. current user request

The result is capped by a route-specific context budget.

## Decision supersession

A new decision may reference `supersedes_id`. The previous decision is atomically changed to `superseded` and the new decision becomes `active`.

## Why this differs from a log file

A log records history. The decision ledger explicitly represents current authority. Raw history is retained, but context selection prefers active decisions.

## Write-back policy

P0 only stores memories and decisions when the user explicitly submits them. Automatic memory extraction is postponed until P1 to avoid silently storing incorrect model inferences.
