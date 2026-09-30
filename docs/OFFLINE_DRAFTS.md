# Disconnected-device clinical drafts

This release adds an encrypted browser workspace at `/offline/`. Staff can prepare selected patient context while connected, disconnect completely, reload the workspace, unlock it and write drafts. Synchronization requires reconnection, authentication and explicit review. It is not an offline replica of the entire hospital database.

## Supported workflows

Clinical notes, problems/allergies/medication documentation, referrals, observations, maternity visits, labour observations, perioperative entries, rehabilitation sessions/outcomes and suspected vaccine adverse events support append-only drafts. The connected application's role, facility, amendment and form validation rules apply again when synchronizing. Stock movements, prescriptions dispensing, payments, scheduling and result release require the connected workflows.

## Staff workflow

1. Upgrade the server, run migrations and collect static files. Serve the application over HTTPS (localhost is supported for development).
2. Sign in as clinical staff with an assigned facility. Open **Offline clinical drafts** from the workspace.
3. Enroll this browser, choose a passphrase of at least 12 characters and explicitly select up to 20 existing patients. Download their context before disconnecting. Each account can have up to 10 active devices.
4. While disconnected, open the previously prepared `/offline/` workspace, unlock it and save drafts. Only the prepared patients and available related records can be selected.
5. Reconnect, sign in to the same account, unlock, review and synchronize. Resolve any validation or changed-context errors; they do not silently overwrite server data.
6. Refresh patient context while connected before editing/retrying a conflict. Context expires after seven days. A successfully accepted submission can still be recovered by retrying its receipt after that expiry.

Device draft time and server synchronization time are preserved separately and displayed in connected record views. A device clock over five minutes ahead of the server is rejected. Device time is user-device supplied, not a verified clinical event timestamp.

## Storage and synchronization controls

- The service worker caches only the identity-free shell, its stylesheet and JavaScript. Patient/API responses are not cached there.
- Patient context and drafts are encrypted in IndexedDB with AES-GCM (256-bit key, fresh nonce per write). PBKDF2-SHA256 derives the key from the passphrase with a random salt and 600,000 iterations. The passphrase is neither stored nor sent to the server; the nonextractable key stays in memory until locking.
- Hiding the tab or five minutes of inactivity locks the workspace and clears displayed plaintext. There is no passphrase recovery. Clearing browser storage or losing the passphrase loses unsynchronized drafts.
- Signed, time-limited context proofs bind references to a device, patient, module and server snapshot. Synchronization checks snapshots and current permissions under database locks, then invokes the same transactional persistence services as connected forms.
- Each device submission has a unique identifier. Repeating an accepted submission returns its receipt without creating a duplicate. Reusing that identifier for changed content is rejected.
- If the connection fails after sending, the draft remains outcome-unknown and cannot be edited/deleted until retry determines whether it was accepted. This avoids creating a second clinical record after a lost response.
- Owners can revoke their devices. Facility admins can list and revoke devices belonging to their assigned facility. Revocation blocks subsequent synchronization; it cannot erase data from a disconnected device.

Use managed devices with a screen lock and a strong unique passphrase. Browser encryption does not protect plaintext from malware, compromised same-origin scripts or someone using an already-unlocked workspace. This implementation has not undergone an independent security assessment or facility clinical acceptance. Plan retention and device-loss procedures before deployment.

## Verification

Local release checks: **147 passed, 4 PostgreSQL-only tests skipped**; Django checks, migration drift and API schema validation pass.

Automated server coverage includes duplicate retries, independent devices, changed patient context, cross-facility boundaries, revoked devices, tampered proofs, forbidden operations, CSRF, expired context, validation failures and device timestamps. A PostgreSQL-only concurrency test submits the same draft simultaneously and requires exactly one clinical record and receipt.

`scripts/offline_browser.cjs` exercises actual network disconnection and reload, wrong-passphrase rejection, encrypted storage, mobile/desktop layout and accessibility, server-save/lost-response recovery, retry and revocation using synthetic data. Run it only against an isolated test installation using the `CLINIC_TEST_*` environment variables described in the script.

Reference APIs: [MDN deriveKey](https://developer.mozilla.org/en-US/docs/Web/API/SubtleCrypto/deriveKey) and [MDN encrypt](https://developer.mozilla.org/en-US/docs/Web/API/SubtleCrypto/encrypt). These references explain browser cryptographic APIs; they do not certify this application.
