# Source policy

This repository is a **clean-room implementation**.

Everything here was written from generic, publicly-taught systems-engineering
practice: requirements traceability matrices, defect severity classification,
and phase-gated acceptance. These concepts are described in ISO/IEC/IEEE 29119
and in every standard systems-engineering curriculum.

## What is not in this repository

- No content, wording, structure, or data from any employer or customer document
- No customer, project, product, or site names
- No internal identifiers, document numbers, or project codes
- No internal IP addresses, hostnames, or credentials
- No cost, price, or commercial figures

All data in the demo application is **synthetically generated** from a seeded
random number generator. `REQ-001`, `TC-001` and `DEF-C1` are format
placeholders, not references to anything real.

## Enforcement

`scripts/check-sources.sh` runs in CI on every push and fails the build if any
blocked identifier appears anywhere in the tree. The block list lives in that
script. Adding to it is always correct; removing from it requires a reason.

If you believe something in this repository derives from a non-public source,
please open an issue and it will be removed immediately.
