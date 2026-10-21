# 12. Email provider cutover runbook (plan 06, phase E4)

**Status:** Written 2026-10-15. The seams this runbook uses are built: pausing and resuming the outbox, and the comparison of
deliveries by provider on the Email Settings page. Nothing in this runbook has been run, because no managed sender identity
exists yet. It is for the person who owns the mail account and the sending domain.

## Before the day

1. Have the new sender ready: a domain you control, SPF and DKIM published for it, DMARC at least in monitoring mode, a
   mailbox or service identity that is allowed to send as the From address, and its credentials in the service environment
   (`SMTP_PASS` or `MS_CLIENT_SECRET` or `SENDGRID_API_KEY`). Do not type them into the settings page.
2. Decide the From and Reply-To addresses and who reads replies and bounces (owner questions 1 and 2 in
   [09](09-email-inventory.md)). Set `SMTP_REPLY_TO` if replies are monitored.
3. Check `APP_URL` is the HTTPS address people use. A message links there.
4. Note the count of messages by provider for the last 30 days (Email Settings, Delivery queue). That is the baseline.

## Cutover

1. **Pause sending** (Email Settings, Delivery queue, Pause sending). Critical messages still go, so a deadline alert is not
   held. Everything else waits.
2. Wait until no message is in the state *sending* and the queue shows nothing you expect to leave under the old identity.
   A message already accepted by the old provider stays under it in the comparison.
3. Change the provider and the sender on the Email Settings page, restart the service if you changed an environment value.
4. Press **Send test email**. The page says whether the new provider accepted it, and asks you to say whether it arrived.
   Confirm receipt from the mailbox. Look at the message headers: SPF, DKIM and DMARC should read pass and the From domain
   should align.
5. **Resume sending.** Watch the comparison: the new provider's accepted count should rise and its failed count should stay
   at zero. A permanent failure shows in the attention list with its reason class and code.
6. After a few days with no unexplained failures, revoke the old credential (for the temporary Gmail account, the app
   password) and use **Clear stored secrets** if a copy was ever saved in the database.

## What not to do

- Do not change the From identity while a message for an outside recipient (an audit share, a review pack) is in flight.
  Those are sent at once and are not in the queue; do the cutover when none is being issued.
- Do not leave sending paused. A pause is a tool for the switch, not a setting. The page shows a notice while it is on.
- Do not delete queued messages to "clear" them. Use *Send again* on a message after the cause is fixed, or leave it:
  a message whose work is done is suppressed when it comes due.

## If it goes wrong

- Set the provider back and resume. Messages that failed under the new provider are in the attention list and can be sent
  again from there.
- A provider that accepts mail it then drops is not visible to the application: the comparison shows acceptance, not
  arrival. That is what the test message and the mailbox check are for.
