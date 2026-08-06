---
doc_id: KB-009
title: Teams and Collaboration Tools
category: Productivity Software
product: Microsoft Teams
owner: Collaboration Services
last_reviewed: 2026-06-18
---

# Teams and Collaboration Tools

## Overview

Teams is the sanctioned platform for chat, meetings, and internal file
collaboration. Guest access is permitted for named external collaborators;
anonymous meeting join is permitted only for meetings explicitly configured
for it.

## Audio or video not working in meetings

Distinguish a device selection fault from a driver fault by testing in the Teams
device settings, which previews both without joining a meeting.

Resolution: check the selected input and output devices, particularly after a
dock disconnect, which frequently resets the selection to a device that is no
longer present. If the correct device is selected and the preview still fails,
clear the Teams cache and relaunch. Persistent failure across both Teams and
another application indicates a driver fault; route to Endpoint Management.

## Cannot join a meeting as an external guest

External participants join through the meeting link without an account unless
the organiser restricted the lobby. Where an external guest reports being unable
to join, the organiser's meeting policy is usually the cause rather than a fault
on the guest's side.

Resolution: advise the organiser to adjust the meeting options to admit external
participants. Service desk agents cannot alter another user's meeting policy.

## Guest access request for an external collaborator

Guest access requires the sponsoring manager's approval and expires after 90
days unless renewed. Route requests to Collaboration Services with the sponsor
recorded. Guests are scoped to named teams and cannot be granted tenant-wide
access.

## Files uploaded to a chat cannot be opened by the recipient

Files shared in a one-to-one chat are stored in the sender's OneDrive with a
link permission scoped to the recipient. If the sender later moves or deletes
the file, the link breaks — the file was never copied to the recipient.

Resolution: ask the sender to reshare. For files that must persist, advise
uploading to the team's Files tab rather than sharing in chat, which stores them
in SharePoint under team ownership rather than personal ownership.

## Notifications not arriving

Check whether the user has quiet hours configured, and whether the desktop
client is signed into the same account as the mobile client. Duplicate accounts
across clients is the most common cause and is easily missed.

## Escalation criteria

Escalate to Collaboration Services when: meeting join fails for multiple
participants, a team or channel is inaccessible to all members, or file
permissions behave inconsistently after a reshare.
