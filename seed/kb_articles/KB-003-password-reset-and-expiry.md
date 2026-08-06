---
doc_id: KB-003
title: Password Reset and Expiry
category: Identity & Access
product: Entra ID
owner: Identity Services
last_reviewed: 2026-04-28
---

# Password Reset and Expiry

## Overview

Passwords expire every 180 days. Self-service reset is available to all staff
who have completed MFA enrolment. Agents should direct users to self-service
wherever possible; agent-initiated resets require identity verification and
generate an audit event.

## Self-service reset

Users with active MFA can reset at the password portal without contacting the
service desk. The new password must differ from the previous five and satisfy
the complexity policy: minimum 14 characters, no dictionary words, not
containing the username.

Common failure: the portal rejects a password that appears to meet policy. This
is nearly always the banned-password list, which blocks seasonal and
company-related terms regardless of complexity. Advise a passphrase instead.

## Agent-initiated reset

Use only when the user cannot complete self-service — typically because MFA
enrolment is incomplete or the user is locked out entirely.

1. Verify identity per KB-011.
2. Issue a temporary password in the Entra admin centre with **User must change
   at next sign-in** enabled.
3. Communicate the temporary password by voice, never by email or chat.
4. Confirm the user has changed it before closing the ticket.

## Password changed but old password still works

This is expected for a short window. Token lifetimes mean existing sessions
remain valid for up to 60 minutes after a change. If a user reports that an old
password still authenticates a *new* sign-in after that window, treat it as a
potential replication fault and escalate immediately.

## Downstream effects of a password change

A password change invalidates cached credentials across every device the user
has signed into. The most common follow-on tickets are VPN failures (see
KB-001), mobile mail clients prompting repeatedly, and mapped network drives
disconnecting (see KB-006).

Proactively advise the user to expect these, which measurably reduces repeat
contacts.

## Escalation criteria

Escalate to Identity Services when: an old password authenticates a new session
after 60 minutes, reset fails repeatedly with a server error, or the account
shows sign-in attempts from unexpected geographies.
