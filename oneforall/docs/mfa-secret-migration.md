# MFA secret encryption release steps

New enrollments use Fernet encryption. Existing plaintext rows remain readable until migrated. The production deploy preflight now requires a separate `MFA_ENCRYPTION_KEY` in the root-owned `/etc/themisiq/themisiq.env`; it does not print the value. Generate a key with `cryptography.fernet.Fernet.generate_key()` in a private session, store it only in the secure environment and password manager, and include it in backup and recovery procedures. Keep it separate from `SECRET_KEY`. Do not paste it into chat or commit it.

Before releasing the application:

1. Take and verify a database backup.
2. Add `MFA_ENCRYPTION_KEY` to the private service environment file, then run the normal deploy preflight. Do not proceed if it rejects the key.
3. After the new code is installed and the service is healthy, run `python oneforall/scripts/encrypt_mfa_secrets.py` for a count-only preview, then `python oneforall/scripts/encrypt_mfa_secrets.py --apply` using the same application environment. The script prints counts only.
4. Run the preview again and require `legacy_plaintext=0` and `previous_key_rows=0` before considering the migration complete.

For key rotation, put the old key in `MFA_ENCRYPTION_PREVIOUS_KEYS`, install the new current key, run the migration again, and only then remove the previous key. All service instances must use the same current key during rotation. An encrypted row without a matching key cannot be used to verify MFA, so keep retired keys until migration and backup recovery are confirmed.

The script is intentionally separate from application startup: an automatic partial migration could leave a restored database unreadable after rollback. The deployed revision and its matching key must be rolled back together if needed.
