# Plus-first development workflow

## Why
ChatGPT Plus can support the project efficiently when expensive agentic coding is reserved for tightly scoped implementation tasks.

## Tool roles
### ChatGPT Project
Use for:
- architecture
- product decisions
- decomposition
- task specifications
- code review
- eval design
- debugging from logs/diffs
- documentation

### Codex
Use for:
- implementing one well-scoped ticket
- targeted refactors
- fixing a reproducible bug
- adding tests around a specific module

### Local machine
Use for:
- Docker
- dependency install
- build
- unit/integration tests
- git status/diff/commit

## Codex budget rule
Prefer this operating ratio, not as an official quota calculation:
- ~80% planning/review/testing coordination in ChatGPT/local tools
- ~15% normal Codex implementation
- ~5% difficult Codex debugging/refactor

## Scope rule
A normal Codex ticket should contain:
- one goal
- 2–6 allowed files
- no unrelated refactor
- one targeted test command
- clear stop conditions

## Stop conditions
Codex should stop and report instead of exploring broadly when:
- a dependency outside allowed files is required
- architecture must change
- database schema must change unexpectedly
- the ticket requires more than one new subsystem
- acceptance criteria are ambiguous

## Review loop
SPEC → Codex → targeted test → git diff → ChatGPT review → commit → next ticket.
