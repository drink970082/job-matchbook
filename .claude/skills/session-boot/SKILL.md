---
name: session-boot
description: >-
  Load this repo's working protocol and current state before starting substantive
  work in it — a feature, a bug fix, a refactor, a design fork, or anything that will
  end in a commit. Walks the read order (PROGRESS "In flight" → task classification →
  the SPEC sections the change touches → PRINCIPLES on a fork) so a session pulls in
  what the task needs instead of the whole doc set. Do NOT use for answering a
  question about the repo, reading one file, or a self-contained edit the user fully
  specified.
---

# Boot a working session

`SPEC.md` (33k tok) and `PROGRESS.md` (~12k tok, down from ~28k before the 2026-07-30
split) are too big to read whole, every session. Read in this order and stop at the point the task doesn't go past.

`PROGRESS.md` is the live delta only. Its catalogue lives in two files you load on
demand, never by default: `docs/BACKLOG.md` (open work that is neither in flight nor
queued) and `docs/REJECTED.md` (proposals already evaluated and turned down — read your
block's entry before proposing a redesign of that block).

## 1. Claim first — `PROGRESS.md` "In flight"

Read that section (`## In flight`, ~2.4k tok) before touching code. Every other
session's claimed branches are there. Rules in
[`docs/DEVELOPMENT.md`](../../../docs/DEVELOPMENT.md) §7 "Claiming work":

- One branch per unit of work; **the In-flight entry is the claim**, not the branch.
- An entry marked *landed, unmerged* is someone else's finished work awaiting a gate.
  Add to it only if your change is the same unit of work.
- Write your own entry when you start; remove it when the work lands.

## 2. Classify the task — `DEVELOPMENT.md` §2

Classification decides which gates apply. Design-shaped work also gets §3's design
gate, which means the fork goes to the user before you build.

## 3. Read only the SPEC sections the change touches

`SPEC.md` is a capability map with numbered sections — grep for the component
(`§6` deployment, `§7.1` scoring backends, `§9` behaviors & invariants) rather than
reading front to back. A change to a §9 behavior/invariant must update that clause
*and* its invariant→test traceability row in the same commit.

## 4. On a design fork only — `PRINCIPLES.md`

Consult it when the work reaches a genuine fork, not preemptively. The four-way
uncertainty policy (keep · fail loud · circuit break · retry) is the part most often
needed and most often misread: "err toward keep" is one row of four, and applying it
to a systemic condition is the error that has recurred five times in this repo.

## 5. Before you finish — `DEVELOPMENT.md` §5 and §6

§5 is the verify gate: run the commands the change touches and paste the output.
§6 is docs + finish. Both are cheap to read at the end; don't front-load them.

## What this skill is not

It does not replace reading the file you are about to edit. It replaces reading
50k tokens of documentation to change one function.
