---
doc_id: KB-005
title: Laptop Performance and Hardware Faults
category: Hardware
product: Managed Windows Laptop
owner: Endpoint Management
last_reviewed: 2026-06-11
---

# Laptop Performance and Hardware Faults

## Overview

The standard fleet is a managed Windows 11 laptop on a four-year refresh cycle.
Performance complaints are more often software state than failing hardware;
confirm which before raising a hardware replacement, as replacements carry a
two-week lead time.

## Severe slowness after startup

Managed devices run a security scan and policy refresh at boot. On a device that
has been offline for a week or more, this can saturate the disk for 20 to 30
minutes after sign-in.

Resolution: confirm the pattern by checking whether performance recovers after
half an hour. If it does, advise the user to leave the device powered on and
connected overnight weekly. Persistent slowness beyond that window warrants
investigation of startup applications and available disk space.

## Disk nearly full

Below 10GB free, Windows update and profile operations begin failing in ways
that surface as unrelated errors.

Resolution: run Storage Sense, clear the Windows update cache, and remove
downloaded installer files. Check for oversized OneDrive folders configured as
"always keep on this device" — this is the single most common cause on the
current fleet, and switching folders back to on-demand usually reclaims tens of
gigabytes.

## Battery not charging or draining rapidly

Report the battery health figure from the device diagnostics report before
raising a replacement. Batteries below 60% design capacity qualify for
replacement; above that threshold the request will be rejected.

Resolution: run the battery report, attach it to the ticket, and route to
Hardware Support if below threshold. Where the device is within warranty,
Hardware Support handles the vendor claim; do not contact the vendor directly.

## Overheating and fan noise

Usually dust obstruction or a blocked vent from use on soft surfaces. Advise the
user on placement first. Persistent thermal throttling with clean vents,
confirmed in the diagnostics report, is a hardware fault.

## External display not detected

Check the dock firmware version before anything else. Docks below firmware 1.4.2
fail intermittently with 4K displays at 60Hz, and this accounts for the majority
of reported display faults on the current fleet.

Resolution: update dock firmware via the vendor utility pushed through Company
Portal. If the display is still undetected after the update, test with a
different cable before raising hardware.

## Escalation criteria

Escalate to Hardware Support when: battery health is below 60%, thermal
throttling persists with clean vents, or the device fails vendor diagnostics.
Escalate to Endpoint Management for software-state issues that survive a policy
refresh.
