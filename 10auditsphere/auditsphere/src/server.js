require('dotenv').config();
const express  = require('express');
const session  = require('express-session');
const cors     = require('cors');
const path     = require('path');
const crypto   = require('crypto');
const db       = require('./database');

const app  = express();
const PORT = process.env.PORT || 3000;

app.use(cors({ origin: true, credentials: true }));
app.use(express.json({ limit: '10mb' }));
app.use(express.urlencoded({ extended: true, limit: '10mb' }));
app.use(session({
  secret: process.env.SESSION_SECRET || 'gridai-secret',
  resave: false, saveUninitialized: false,
  cookie: { secure: false, maxAge: 24 * 60 * 60 * 1000 }
}));

app.use(express.static(path.join(__dirname, '../public')));

// Public shared audit view (no auth)
app.get('/shared/:token', (_req, res) =>
  res.sendFile(path.join(__dirname, '../public/shared.html')));

// Routes
app.use('/api/auth',           require('./routes/auth'));
app.use('/api',                require('./routes/audits'));
app.use('/api',                require('./routes/controls'));
app.use('/api',                require('./routes/evidence'));
app.use('/api/ai',             require('./routes/ai'));
app.use('/api/activity',       require('./routes/activity'));
app.use('/api/share-links',    require('./routes/shareLinks'));
app.use('/api/approvals',      require('./routes/approvals'));
app.use('/api/non-conformances', require('./routes/nonConformances'));
app.use('/api/vendors',        require('./routes/vendors'));
app.use('/api/digest',         require('./routes/digest'));
app.use('/api/api-keys',       require('./routes/apiKeys'));
app.use('/api/onedrive',       require('./routes/onedrive'));
app.use('/api/cross-mappings', require('./routes/crossMapping'));

app.get('/api/health', (_req, res) => res.json({ status: 'ok', time: new Date().toISOString() }));
app.get('*', (_req, res) => res.sendFile(path.join(__dirname, '../public/index.html')));
app.use((err, _req, res, _next) => { console.error(err.stack); res.status(500).json({ error: err.message }); });

async function start(port) {
  const key = process.env.ANTHROPIC_API_KEY || '';
  const keyOk = key && !key.startsWith('your-') && key.startsWith('sk-ant-');
  if (!keyOk) {
    console.log('\n  ⚠️  ANTHROPIC_API_KEY not configured — AI features will not work');
    console.log('  Open .env and set ANTHROPIC_API_KEY=sk-ant-...\n');
  } else { console.log('  ✅ Anthropic API key found'); }

  await db.init();
  try { require('./services/scheduler').startScheduler(); } catch(e) { console.log('Scheduler:', e.message); }
  return new Promise(resolve => {
    const server = app.listen(port || PORT, () => {
      console.log(`\n🚀  G.R.I.D AI  →  http://localhost:${port || PORT}`);
      console.log(`    Login: admin@auditsphere.local / admin123\n`);
      resolve(server);
    });
  });
}
module.exports = { app, start };
if (require.main === module) start().catch(e => { console.error(e); process.exit(1); });
