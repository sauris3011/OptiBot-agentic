---
doc_id: KB-007
title: Printing and Print Queues
category: Peripherals
product: Follow-Me Print
owner: Endpoint Management
last_reviewed: 2026-02-25
---

# Printing and Print Queues

# Overview

The estate uses follow-me printing: jobs are held centrally and released at any
device by badge tap. There are no direct device queues. Users describing a
"printer offline" fault are almost always describing a release or driver
problem rather than a device fault.

## Job submitted but nothing releases at the device

The job is held under the submitting account. If the badge is registered to a
different account, or the badge registration has lapsed, the device
authenticates as a different identity and finds no queued jobs.

Resolution: have the user sign in at the device panel manually rather than by
badge. If jobs appear under manual sign-in, the badge registration is the fault
and should be re-registered at the print portal.

## Jobs vanish from the queue

Held jobs expire after 24 hours by design. Jobs submitted the previous day will
not be available and must be resubmitted. This is a retention setting and is not
adjustable per user.

## Printing produces garbled output or blank pages

A driver mismatch, usually after a Windows feature update replaced the universal
driver with a vendor-specific one.

Resolution: remove the printer from the user's device, then reinstall the
universal print driver from Company Portal. Do not install vendor drivers
downloaded from the manufacturer; they conflict with the follow-me
infrastructure and are the most common cause of repeat tickets on this topic.

## Cannot print from a mobile device

Mobile printing requires the print app and works only on the corporate wireless
network, not over VPN. This is a design limitation of the release protocol.

Resolution: confirm the user is on corporate wireless. If they need to print
while remote, the supported path is to email the document to their own account
and print on returning to the office.

## Badge not recognised at any device

Distinguish a badge fault from a registration fault by testing at a second
device. A badge failing everywhere is usually demagnetised and needs
replacement through Facilities, not IT.

## Escalation criteria

Escalate to Endpoint Management when: multiple users cannot release at the same
device, the print portal is unreachable, or driver reinstallation does not
resolve garbled output.
