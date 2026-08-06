---
doc_id: KB-002
title: MFA Enrolment and Reset
category: Identity & Access
product: Entra ID MFA
owner: Identity Services
last_reviewed: 2026-06-02
---

# MFA Enrolment and Reset

## Overview

Multi-factor authentication is mandatory for all staff accounts. Enrolment uses
the Microsoft Authenticator app by default; hardware tokens are issued only to
users in Privileged roles. Service desk agents can reset enrolment but cannot
grant exemptions.

## User has a new phone and cannot approve prompts

Authenticator registrations are bound to the device, not the phone number, so
restoring a phone backup does not carry the registration across. The user must
re-enrol.

Resolution:

1. Verify identity using the callback procedure in KB-011. Do not skip this;
   MFA reset is the most commonly abused social engineering vector.
2. In the Entra admin centre, open the user and select **Require re-register MFA**.
3. Instruct the user to sign in at the MFA portal within 24 hours and complete
   enrolment on the new device.
4. Confirm the registration appears before closing the ticket.

Do not delete the existing authentication method before the user has completed
re-enrolment; doing so locks the account out entirely and requires a Privileged
role to recover.

## Prompts arrive but approval fails

If the user receives the prompt and approves it, yet sign-in still fails, the
device clock has almost certainly drifted. Time-based codes tolerate roughly 90
seconds of skew.

Resolution: instruct the user to enable automatic date and time on the device,
then retry. Where automatic time is enforced by policy and drift persists, the
device has a failing battery and should be routed to Hardware Support.

## Account locked after repeated failed attempts

Ten consecutive failures lock the account for 30 minutes. The lockout is
deliberate and cannot be shortened, but it can be cleared.

Resolution: confirm identity per KB-011, then clear the lockout in the Entra
admin centre. Investigate the source of the failed attempts before closing — a
lockout with no user activity behind it usually indicates a stale credential on
a secondary device such as a phone mail client, or a genuine attack.

## Hardware token requests

Hardware tokens require Privileged role membership and manager approval.
Requests without both are rejected. Route approved requests to Identity Services
with the user's role attestation attached; do not issue tokens from the service
desk directly.

## Escalation criteria

Escalate to Identity Services when: the user holds a Privileged role, the
lockout source cannot be identified, re-enrolment fails twice, or there is any
indication of account compromise.
