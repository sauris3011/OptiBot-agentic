---
doc_id: KB-011
title: Identity Verification Procedure
category: Security & Compliance
product: Service Desk Procedure
owner: Security Operations
last_reviewed: 2026-06-25
---

# Identity Verification Procedure

## Overview

Identity verification is mandatory before any credential, MFA, or access change.
Service desk impersonation is among the most exploited attack paths against
organisations of this size, and the controls below are the primary defence. They
are not discretionary.

## When verification is required

Verification is required before: password reset, MFA reset or re-registration,
account unlock, granting access to any resource, changing a registered phone
number or recovery address, and releasing any information about an account to a
caller.

Verification is not required for general advice, guidance on a documented
procedure, or status updates on an existing ticket raised by the same user.

## The callback procedure

Never verify identity using information the caller supplies. An attacker
supplies convincing information; that is the nature of the attack.

1. End the inbound contact. Do not proceed on the original call.
2. Look up the user's number in the directory. Do not use a number the caller
   provided, even if it appears to match.
3. Call the directory number and confirm the request with the person who
   answers.
4. Record the verification in the ticket, including the number dialled.

Where a callback is impractical — a user genuinely travelling without their
registered number — the alternative is manager confirmation through a separate
channel initiated by the agent.

## Red flags requiring escalation

Treat as suspicious and escalate to Security Operations without completing the
request: urgency or pressure tactics, a request to bypass the callback, a claim
to be an executive or acting on an executive's behalf, a request to change the
registered phone number immediately followed by an MFA reset, or a caller who
becomes hostile when verification is mentioned.

The combination of a contact-detail change followed by an MFA reset is the
signature of an active account takeover and should always be escalated.

## What must never be done

Do not communicate a temporary password by email or chat. Do not confirm or deny
whether an account exists to an unverified caller. Do not read back any part of
an existing credential. Do not accept a manager's approval relayed by the
requester; obtain it directly.

## Recording verification

Every verification must be recorded in the ticket with the method used and the
number or channel through which it was completed. Tickets closed with a
credential change and no verification record are flagged in the monthly audit
and are investigated.

## Escalation criteria

Escalate to Security Operations immediately for any red flag above, any
suspected compromise, or any request to bypass this procedure regardless of who
makes it.
