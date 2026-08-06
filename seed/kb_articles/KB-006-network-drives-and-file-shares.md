---
doc_id: KB-006
title: Network Drives and File Shares
category: Network & Connectivity
product: SMB File Shares
owner: Infrastructure Services
last_reviewed: 2026-03-19
---

# Network Drives and File Shares

## Overview

Departmental shares are mapped by Group Policy at sign-in. Access is granted
through security groups, never to individual accounts. Most reported faults are
group membership propagation or credential caching rather than share
availability.

## Mapped drive shows a red X

The mapping exists but the session is not authenticated. This is the expected
appearance after a password change until the cached credential is refreshed.

Resolution: instruct the user to open the drive directly, which forces
reauthentication. If prompted for credentials, the entry in Credential Manager
is stale and should be removed. A sign-out and sign-in resolves it in most
cases; a full restart is rarely necessary.

## Access denied on a folder the user could previously open

Group membership changes take effect at the next sign-in because the access
token is issued at authentication time. A user added to a group ten minutes ago
will still be denied until they sign out and back in.

Resolution: confirm the group membership in the directory, then have the user
sign out completely and sign back in. If access is still denied with confirmed
membership after a fresh sign-in, the folder has an explicit deny entry that
overrides the group grant — escalate to Infrastructure Services.

## Drive missing entirely after sign-in

Group Policy did not apply, usually because the device signed in without a
domain connection — common when working remotely and signing in before the VPN
connects.

Resolution: connect the VPN, then run a policy refresh and sign out and back in.
Advise remote users to connect the VPN before signing in where possible.

## Slow file access over VPN

SMB over VPN is latency-sensitive, and large files behave far worse than the
throughput figures suggest. This is a protocol characteristic, not a fault.

Resolution: direct users to the SharePoint equivalent of the share for remote
work. Where the workflow genuinely requires SMB, request a sync client
configuration from Infrastructure Services rather than raising a performance
ticket.

## Requesting access to a new share

Access requests require the data owner's approval, which is recorded in the
share register. Route requests with owner approval attached. Do not grant access
by adding users directly to the ACL; this bypasses the audit trail and will be
reverted at the next reconciliation.

## Escalation criteria

Escalate to Infrastructure Services when: access is denied despite confirmed
group membership after a fresh sign-in, a share is unreachable for multiple
users, or an explicit deny entry is suspected.
