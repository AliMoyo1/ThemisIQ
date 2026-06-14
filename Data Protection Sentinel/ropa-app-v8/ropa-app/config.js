/**
 * RoPA AI Assistant — Configuration File
 * ========================================
 * Edit this file to change login credentials,
 * add users, or update app settings.
 *
 * SECURITY NOTE: This is a local-only app.
 * Credentials here are stored in plain text
 * which is fine for single-user local use.
 * Do NOT expose this file on a public server.
 */

const ROPA_CONFIG = {

  // ── Users ──────────────────────────────────
  // Add or edit users below.
  // Each user needs: username, password, displayName
  users: [
    {
      username:    "admin",
      password:    "ropa2024",
      displayName: "Administrator"
    },
    // To add another user, copy the block above and paste here:
    // {
    //   username:    "jane",
    //   password:    "MyPassword123",
    //   displayName: "Jane Smith"
    // },
  ],

  // ── App Settings ───────────────────────────
  appName:    "RoPA AI Assistant",
  orgName:    "Your Organisation Name",   // Shown in the header
  version:    "1.0.0",

  // Session timeout in minutes (0 = never expire)
  sessionTimeoutMinutes: 0,

};
