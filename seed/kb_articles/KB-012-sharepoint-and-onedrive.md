---
doc_id: KB-012
title: SharePoint and OneDrive
category: Productivity Software
product: OneDrive for Business
owner: Collaboration Services
last_reviewed: 2026-05-21
---

# SharePoint and OneDrive

## Overview

OneDrive syncs the user's personal work files and any SharePoint libraries they
add. Files On-Demand is enabled by default, so files appear in Explorer without
consuming local disk until opened.

## Sync stuck or paused

Sync pauses automatically on metered connections and when battery saver is
active. Both are easily missed because the client reports "paused" without
naming the cause.

Resolution: check whether the connection is marked metered and whether battery
saver is on. If neither applies, reset the sync client rather than unlinking the
account — unlinking forces a full resync of the entire library, which on a large
library takes hours and generates further tickets.

## Disk filling because of OneDrive

Folders set to "always keep on this device" defeat Files On-Demand and are the
leading cause of full disks on the current fleet (see KB-005).

Resolution: right-click the affected folders and select "free up space" to
return them to on-demand. Advise the user that files remain accessible; only the
local copy is released.

## Shared link recipient gets access denied

Default link scope is people in the organisation. A link shared with an external
collaborator will fail unless the sender explicitly selected a specific-people
link and added the external address.

Resolution: have the sender reshare with the correct scope. External sharing
must be enabled for the site; where it is not, the request routes to
Collaboration Services with the site owner's approval.

## File locked for editing by another user

The lock persists for a period after the other user closes the document,
particularly if their client closed uncleanly. This is expected and usually
clears on its own.

Resolution: advise waiting, or open in the web client, which supports
co-authoring and bypasses the desktop lock entirely. Forcing a checkout discard
loses the other user's unsaved changes and should not be done without contacting
them first.

## Recovering a deleted file

Deleted files remain in the site recycle bin for 93 days, then the second-stage
recycle bin. Users can restore from the first stage themselves; the second stage
requires a site collection administrator.

Resolution: direct the user to the recycle bin. For files beyond 93 days,
recovery is not possible and the user should be told so plainly rather than
having a request raised that cannot be fulfilled.

## Version history and accidental overwrite

Version history retains 500 versions by default and is the correct remedy for an
overwrite, not the recycle bin. Users frequently raise a recovery ticket without
knowing version history exists — check it before escalating.

## Escalation criteria

Escalate to Collaboration Services when: second-stage recycle bin recovery is
needed, a site is inaccessible to all members, or sync fails after a client
reset.
