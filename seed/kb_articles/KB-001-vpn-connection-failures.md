---
doc_id: KB-001
title: VPN Connection Failures
category: Network & Connectivity
product: GlobalProtect VPN
owner: Network Operations
last_reviewed: 2026-05-14
---

# VPN Connection Failures

## Overview

The corporate VPN (GlobalProtect) authenticates against Entra ID and requires a
valid MFA token. Most connection failures fall into one of four categories:
credential problems, MFA enrolment drift, client version mismatch, or split
tunnel misconfiguration. Establish which category applies before escalating.

## MFA token rejected after a password change

When a user changes their password, the VPN client caches the previous
credential in the Windows Credential Manager. The client then presents the stale
password, Entra ID rejects it, and the failure surfaces misleadingly as
"MFA token rejected" rather than as an authentication error.

Resolution:

1. Open Credential Manager and remove all entries beginning with `globalprotect`.
2. Sign out of the GlobalProtect client fully (right-click the tray icon, Sign Out).
3. Relaunch and authenticate with the new password.
4. Approve the MFA prompt within 30 seconds; expired prompts report the same error.

If the failure persists after clearing cached credentials, the account's MFA
registration may have been reset. Direct the user to re-enrol at the MFA portal
before escalating to Network Operations.

## Client version below the minimum supported release

The gateway rejects clients older than 6.2.1 with error `GP-4021`. The client
does not self-update on managed devices; it is pushed by Intune on a weekly
cycle, so a device offline for an extended period will drift out of support.

Resolution: instruct the user to open Company Portal and install the pending
GlobalProtect update, then restart. Devices that cannot reach Intune must be
escalated to Endpoint Management for manual remediation.

## Connection drops every few minutes

Repeated disconnects at regular intervals almost always indicate an IKE rekey
failure caused by an intermediate NAT device, most commonly a consumer-grade
home router with SIP ALG enabled.

Resolution: instruct the user to disable SIP ALG in their router's
administration console. Where the user cannot modify the router, enable the
`UDP-fallback` profile on their VPN account; this trades a small amount of
throughput for connection stability.

## Cannot reach internal resources while connected

If the VPN reports connected but internal hosts are unreachable, the split
tunnel policy is likely assigning the wrong route set. Confirm which access
profile the user holds — Standard, Contractor, or Privileged — as Contractor
profiles exclude the internal datacentre range by design.

Resolution: verify the assigned profile in the VPN admin console. If the profile
is correct and routes are still missing, collect the output of `route print`
and escalate to Network Operations with the ticket reference.

## Escalation criteria

Escalate to Network Operations when: the gateway returns a 5xx error, more than
five users report the same failure within an hour, or the issue persists after
both credential clearing and client update have been attempted.
