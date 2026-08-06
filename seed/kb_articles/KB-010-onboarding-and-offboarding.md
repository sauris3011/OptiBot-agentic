---
doc_id: KB-010
title: Onboarding and Offboarding
category: Account Lifecycle
product: Joiner Mover Leaver Process
owner: Identity Services
last_reviewed: 2026-04-09
---

# Onboarding and Offboarding

## Overview

Account lifecycle is driven by the HR system. The service desk does not create
or delete accounts directly; it resolves faults in the automated provisioning
flow. Manual intervention outside this flow breaks the audit chain and will be
reverted.

## New starter account not created on day one

Provisioning runs nightly from the HR feed. A starter whose record was entered
after the previous run will not have an account until the following morning.

Resolution: confirm the start date and record creation time in the HR system. If
the record predates the last run and no account exists, the provisioning job
failed for that record — escalate to Identity Services with the employee ID.
Do not create an interim account; downstream entitlements will not attach to it.

## New starter has an account but no application access

Entitlements attach by role, and the role assignment often lags the account
creation by one cycle. Base entitlements — mail, Teams, the standard laptop
build — arrive with the account. Role-specific applications arrive with the role.

Resolution: confirm the role is populated in the HR record. Where it is blank,
the fix is with the hiring manager, not with IT.

## Leaver still has access after their last day

Deprovisioning triggers on the HR termination date, not the last working day,
and the two frequently differ. Verify the termination date before treating this
as a fault.

Where genuine unauthorised access is suspected, this is a security incident, not
a service request. Escalate to Security immediately rather than working the
ticket.

## Mover retains access to their previous team's resources

Role changes add new entitlements but do not automatically remove old group
memberships where those were granted manually. This is a known gap in the flow
and the reason manual grants are discouraged (see KB-006).

Resolution: raise an access review for the user with Identity Services. Do not
remove group memberships directly; some are shared with legitimate current
entitlements and removal causes outages.

## Mailbox access for a departed colleague

Requires manager approval and is granted as delegated access to the retained
mailbox for 90 days, after which the mailbox is archived. Route to Collaboration
Services with approval attached. Forwarding a departed user's mail to another
account is not permitted under the retention policy.

## Escalation criteria

Escalate to Identity Services when: a provisioning job has failed, entitlements
do not attach after the role is confirmed, or an access review is required.
Escalate to Security immediately for any suspected unauthorised access by a
leaver.
