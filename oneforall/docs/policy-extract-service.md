# Policy extraction isolation

ARIA's existing-policy import accepts untrusted DOCX and PDF bytes. In a Linux
non-debug deployment, the web app now sends those bytes over a root-created
UNIX socket to a separate, per-request systemd service. The worker is given no
application environment file, database connection or source filesystem path.
DOCX archive structure is checked in that worker before python-docx opens it;
the web process only checks the upload size, extension and PDF signature.
It runs under a distinct dynamic UID, with a private network namespace,
IP-address denial, read-only system files, private temporary files and bounded
memory, tasks and lifetime. The app returns 503 if the socket or response is
unavailable; it does not fall back to an app-identity parser. Local debug and
Windows tests retain the bounded subprocess path. A rejected document returns
a generic 422; a missing or malformed worker response returns 503.

The wire protocol is a four-byte big-endian header length, JSON header
(`version`, `extension`, `filename`, `size`), exact source bytes, then a four-byte
response length and JSON result. Requests are limited to 25 MB and responses
to 1.5 MB. No parser error body is returned to the caller.

## Release order

1. Before switching app code, verify the service's `.socket` and `@.service`
   files against the intended commit and install them to
   `/etc/systemd/system/` as root with mode 0644. Run `systemctl daemon-reload`
   and `systemctl enable --now themisiq-policy-extract.socket`. The socket must
   be owned by `themisiq`, mode 0600; the parser service is started on demand.
2. Run `scripts/deploy.py` preflight using the existing ARIA pilot allowlist and
   acknowledgements. It now refuses an enabled ARIA release if the installed
   units differ from the checkout, daemon reload is pending, or the active
   socket has the wrong type, owner or mode.
3. Switch code with the normal backup/restore-tested release. The app and the
   worker must use the same checkout and pinned Python environment. After
   health checks, upload a small synthetic DOCX as an authorized specialist,
   verify suggestions and source anchors, and check that a deliberately
   unavailable socket returns a 503 without parsing inside the app. Restore
   the socket immediately after the negative test.
4. Preserve the old code and backup for rollback. If new code is rolled back,
   the socket can stay installed but is not used by the old app. Do not restore
   an older database snapshot over newer accepted records.

The worker's dynamic UID can read installed application code and libraries;
storage paths and `/etc/themisiq` are hidden or inaccessible. Validate the
actual effective unit with `systemctl show` and the host's MAC policy during
release. A host that cannot enforce the network and filesystem restrictions
must not enable ARIA import. The service does not make hostile file parsers
perfectly safe; parser dependency updates and resource monitoring still matter.
