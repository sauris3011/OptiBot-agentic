---
doc_id: KB-004
title: Outlook and Email Issues
category: Productivity Software
product: Microsoft Outlook
owner: Collaboration Services
last_reviewed: 2026-05-30
---

# Outlook and Email Issues

## Overview

Mail is hosted on Exchange Online. Outlook desktop uses cached Exchange mode by
default with a 12-month sync window. Most reported faults are cache corruption,
quota, or rule-related rather than server-side.

## Outlook stuck on "Trying to connect"

Usually a corrupted local cache file rather than a connectivity fault. Confirm
the user can reach Outlook on the web first — if webmail works, the server is
healthy and the problem is local.

Resolution:

1. Close Outlook completely and confirm no `outlook.exe` process remains.
2. Rename the OST file in the local Outlook data folder, appending `.old`.
3. Relaunch Outlook and allow the cache to rebuild. Expect 10 to 40 minutes for
   a large mailbox; advise the user not to interrupt it.

Do not delete the OST file. Renaming preserves a recovery path if the rebuild
fails.

## Mailbox full and cannot send

The mailbox quota is 50GB with a send-block at 49GB. Users typically hit this
through large attachments retained in Sent Items.

Resolution: direct the user to empty Deleted Items, then use Mailbox Cleanup to
locate items over 10MB. Where the user genuinely requires more space, a quota
increase needs manager approval routed to Collaboration Services. Archiving to a
PST is not permitted under the retention policy.

## Messages disappearing from the inbox

Almost always a client-side rule, frequently one created accidentally by a
sweep action. Check rules before assuming a retention or journaling issue.

Resolution: open Rules and Alerts and review for rules moving or deleting mail.
Also check Outlook on the web separately, as rules created there may not appear
in the desktop client until it resyncs.

## External sender warnings appearing on internal mail

Indicates the message routed via an external relay, typically because it was
sent from a distribution list with an external member, or forwarded from a
personal account. This is expected behaviour and not a fault. Explain it rather
than suppressing the banner; suppression requires Security approval.

## Shared mailbox access requests

Access to a shared mailbox requires approval from the mailbox owner, not the
requester's manager. Route the request with owner approval attached. Automapping
adds the mailbox to Outlook within roughly one hour of the grant; a restart does
not accelerate it.

## Escalation criteria

Escalate to Collaboration Services when: webmail is also failing, mail flow is
delayed for multiple users, or a mailbox rebuild fails twice.
