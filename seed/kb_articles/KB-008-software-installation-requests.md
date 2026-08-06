---
doc_id: KB-008
title: Software Installation and Licence Requests
category: Software Management
product: Company Portal
owner: Endpoint Management
last_reviewed: 2026-05-07
---

# Software Installation and Licence Requests

## Overview

Users do not hold local administrator rights. Approved software installs
self-service through Company Portal; anything outside the catalogue requires a
request with manager approval and, where licensed, budget code.

## Software not appearing in Company Portal

Catalogue visibility is scoped by security group and by device compliance. A
compliant device missing an expected application usually indicates the user is
not in the entitlement group.

Resolution: confirm the entitlement group in the software register, then request
membership through the manager approval flow. Once granted, the catalogue
refreshes within roughly two hours; a device restart does not accelerate it.

## Installation fails partway through

Most commonly insufficient disk space or a pending restart blocking the
installer. Check both before investigating the package.

Resolution: confirm at least 10GB free (see KB-005), complete any pending
restart, then retry from Company Portal. Where the install still fails, collect
the installation log referenced in the failure dialog and route to Endpoint
Management.

## Request for software outside the catalogue

Requires manager approval, a business justification, and Security review for
anything handling company data. Expect five working days. Requests for software
with a viable catalogue equivalent are routinely rejected — check the catalogue
for an approved alternative before submitting.

Do not advise users to install from vendor websites while awaiting approval.
Users lack the rights to do so, and attempting it generates security alerts that
consume investigation time.

## Licence expired or seat unavailable

Licensed applications reclaim seats after 60 days of non-use. A user returning
from extended leave will commonly find their seat reclaimed.

Resolution: request seat reassignment through the software register. Where the
pool is exhausted, the request requires budget approval and should be routed to
the application owner, not to Endpoint Management.

## Browser extension requests

Extensions are blocked by policy except those on the approved list. Approval
requires Security review regardless of the requester's role, because extensions
run with access to session content. There is no fast path for this.

## Escalation criteria

Escalate to Endpoint Management when: a catalogue install fails twice with logs
attached, the catalogue itself is unreachable, or a package appears corrupt for
multiple users.
