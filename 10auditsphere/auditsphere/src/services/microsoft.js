/**
 * microsoft.js — Microsoft Graph API service
 * Handles OneDrive uploads and Teams notifications
 * Uses MSAL with username/password flow for personal accounts
 */
const msal = require('@azure/msal-node');
const https = require('https');
const fs    = require('fs');
const path  = require('path');

// For personal Microsoft accounts we use the Device Code flow or
// Resource Owner Password Credentials (ROPC) with a registered app.
// Since we have an app password, we use SMTP for email and a simple
// approach for OneDrive using the OneDrive REST API directly.

// ── OneDrive via Microsoft Graph ─────────────────────────────────────
// We'll use a simple fetch-based approach with MSAL token acquisition

let _msalApp = null;
let _tokenCache = null;
let _tokenExpiry = 0;

function getMsalApp() {
  if (_msalApp) return _msalApp;
  const clientId = process.env.MS_CLIENT_ID;
  if (!clientId) return null; // OneDrive not configured

  _msalApp = new msal.PublicClientApplication({
    auth: {
      clientId,
      authority: `https://login.microsoftonline.com/${process.env.MS_TENANT_ID || 'consumers'}`,
    },
    system: { loggerOptions: { loggerCallback: () => {} } },
  });
  return _msalApp;
}

async function getGraphToken() {
  if (_tokenCache && Date.now() < _tokenExpiry) return _tokenCache;

  const app = getMsalApp();
  if (!app) return null;

  try {
    const accounts = await app.getTokenCache().getAllAccounts();
    if (accounts.length > 0) {
      const result = await app.acquireTokenSilent({ scopes: ['Files.ReadWrite', 'User.Read'], account: accounts[0] });
      _tokenCache  = result.accessToken;
      _tokenExpiry = Date.now() + (result.expiresOn - Date.now()) - 60000;
      return _tokenCache;
    }
    // ROPC flow for personal account
    const result = await app.acquireTokenByUsernamePassword({
      scopes: ['Files.ReadWrite', 'User.Read', 'Chat.ReadWrite'],
      username: process.env.MS_EMAIL,
      password: process.env.MS_APP_PASSWORD,
    });
    _tokenCache  = result.accessToken;
    _tokenExpiry = Date.now() + (result.expiresOn ? result.expiresOn - Date.now() : 3600000) - 60000;
    return _tokenCache;
  } catch (e) {
    console.error('MS Graph token error:', e.message);
    return null;
  }
}

async function graphRequest(method, endpoint, body, token) {
  const tok = token || await getGraphToken();
  if (!tok) return { error: 'Not authenticated with Microsoft Graph' };

  return new Promise((resolve) => {
    const data   = body ? JSON.stringify(body) : null;
    const url    = new URL('https://graph.microsoft.com' + endpoint);
    const opts   = {
      hostname: url.hostname, path: url.pathname + url.search, method,
      headers: {
        Authorization: `Bearer ${tok}`,
        'Content-Type': 'application/json',
        ...(data ? { 'Content-Length': Buffer.byteLength(data) } : {}),
      },
    };
    const req = https.request(opts, res => {
      let raw = '';
      res.on('data', d => raw += d);
      res.on('end', () => {
        try { resolve(JSON.parse(raw)); }
        catch { resolve({ raw, status: res.statusCode }); }
      });
    });
    req.on('error', e => resolve({ error: e.message }));
    if (data) req.write(data);
    req.end();
  });
}

async function uploadToOneDrive(localFilePath, remoteFileName, auditName) {
  const tok = await getGraphToken();
  if (!tok) return { ok: false, error: 'Microsoft Graph not configured — file saved locally only' };

  try {
    const folder     = process.env.MS_ONEDRIVE_FOLDER || 'GRID-AI-Evidence';
    const safeAudit  = (auditName || 'General').replace(/[^a-zA-Z0-9 \-_]/g, '');
    const remotePath = `${folder}/${safeAudit}/${remoteFileName}`;
    const fileData   = fs.readFileSync(localFilePath);
    const fileSize   = fileData.length;

    // Use simple upload for files under 4MB, resumable for larger
    if (fileSize < 4 * 1024 * 1024) {
      return new Promise((resolve) => {
        const url  = new URL(`https://graph.microsoft.com/v1.0/me/drive/root:/${remotePath}:/content`);
        const opts = {
          hostname: url.hostname, path: url.pathname, method: 'PUT',
          headers: {
            Authorization: `Bearer ${tok}`,
            'Content-Type': 'application/octet-stream',
            'Content-Length': fileSize,
          },
        };
        const req = https.request(opts, res => {
          let raw = '';
          res.on('data', d => raw += d);
          res.on('end', () => {
            try {
              const result = JSON.parse(raw);
              resolve({ ok: true, id: result.id, url: result.webUrl, name: result.name });
            } catch { resolve({ ok: false, error: raw }); }
          });
        });
        req.on('error', e => resolve({ ok: false, error: e.message }));
        req.write(fileData);
        req.end();
      });
    } else {
      // Create upload session for large files
      const session = await graphRequest('POST',
        `/v1.0/me/drive/root:/${remotePath}:/createUploadSession`,
        { item: { '@microsoft.graph.conflictBehavior': 'rename' } }, tok);
      if (!session.uploadUrl) return { ok: false, error: 'Could not create upload session' };

      // Upload in chunks
      const CHUNK = 3 * 1024 * 1024;
      let start   = 0;
      let result  = null;
      while (start < fileSize) {
        const end   = Math.min(start + CHUNK - 1, fileSize - 1);
        const chunk = fileData.slice(start, end + 1);
        result = await new Promise((resolve) => {
          const url  = new URL(session.uploadUrl);
          const opts = {
            hostname: url.hostname, path: url.pathname + url.search, method: 'PUT',
            headers: {
              'Content-Length': chunk.length,
              'Content-Range': `bytes ${start}-${end}/${fileSize}`,
            },
          };
          const req = https.request(opts, res => {
            let raw = '';
            res.on('data', d => raw += d);
            res.on('end', () => { try { resolve(JSON.parse(raw)); } catch { resolve({ raw }); } });
          });
          req.on('error', e => resolve({ error: e.message }));
          req.write(chunk);
          req.end();
        });
        start = end + 1;
      }
      return { ok: true, id: result?.id, url: result?.webUrl };
    }
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

// ── Teams Webhook Notification ────────────────────────────────────────
async function sendTeamsNotification({ title, text, facts = [], color = '1a6b3a', actionUrl }) {
  const webhookUrl = process.env.MS_TEAMS_WEBHOOK;
  if (!webhookUrl) {
    console.log(`📣 [Teams simulated] ${title}: ${text}`);
    return { ok: true, simulated: true };
  }

  const card = {
    '@type': 'MessageCard',
    '@context': 'http://schema.org/extensions',
    themeColor: color,
    summary: title,
    sections: [{
      activityTitle: `**${title}**`,
      activitySubtitle: 'G.R.I.D AI Compliance System',
      activityText: text,
      facts: facts.map(f => ({ name: f.label, value: f.value })),
    }],
    potentialAction: actionUrl ? [{
      '@type': 'OpenUri', name: 'Open G.R.I.D AI',
      targets: [{ os: 'default', uri: actionUrl }],
    }] : [],
  };

  return new Promise((resolve) => {
    const url    = new URL(webhookUrl);
    const data   = JSON.stringify(card);
    const opts   = {
      hostname: url.hostname, path: url.pathname + url.search, method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) },
    };
    const req = https.request(opts, res => {
      let raw = '';
      res.on('data', d => raw += d);
      res.on('end', () => resolve({ ok: res.statusCode < 300, status: res.statusCode, body: raw }));
    });
    req.on('error', e => resolve({ ok: false, error: e.message }));
    req.write(data);
    req.end();
  });
}

module.exports = { uploadToOneDrive, sendTeamsNotification, getGraphToken, graphRequest };
