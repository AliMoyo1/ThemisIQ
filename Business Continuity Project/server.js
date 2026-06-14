require('dotenv').config();

const express = require('express');
const session = require('express-session');
const flash = require('connect-flash');
const path = require('path');
const expressLayouts = require('express-ejs-layouts');
const methodOverride = require('method-override');
const bodyParser = require('body-parser');
const cookieParser = require('cookie-parser');

const db = require('./models/db');
const { startScheduler } = require('./services/scheduler');
const { renderMarkdown } = require('./services/markdown');

const app = express();

// ---- View engine ----
app.set('views', path.join(__dirname, 'views'));
app.set('view engine', 'ejs');
app.use(expressLayouts);
app.set('layout', 'layout');

// ---- Static + parsers ----
app.use(express.static(path.join(__dirname, 'public')));
app.use(bodyParser.urlencoded({ extended: true, limit: '2mb' }));
app.use(bodyParser.json({ limit: '2mb' }));
app.use(cookieParser());
app.use(methodOverride('_method'));

// ---- Sessions + flash ----
app.use(session({
  secret: process.env.SESSION_SECRET || 'dev-secret',
  resave: false,
  saveUninitialized: false,
  cookie: { maxAge: 1000 * 60 * 60 * 24 * 7 }
}));
app.use(flash());

// ---- Locals available in every view ----
app.use((req, res, next) => {
  res.locals.appName = process.env.APP_NAME || 'BCM Sentinel';
  res.locals.appTagline = process.env.APP_TAGLINE || 'By Ali Moyo';
  res.locals.user = req.session.user || null;
  res.locals.tenant = req.session.tenant || null;
  res.locals.flash = {
    success: req.flash('success'),
    error: req.flash('error'),
    info: req.flash('info')
  };
  res.locals.currentPath = req.path;
  res.locals.renderMarkdown = renderMarkdown;
  next();
});

// ---- Audit-log middleware (records tenant-scoped writes) ----
app.use(require('./middleware/audit'));

// ---- Routes ----
app.use('/', require('./routes/auth'));
app.use('/dashboard', require('./routes/dashboard'));
app.use('/bia', require('./routes/bia'));
app.use('/risks', require('./routes/risks'));
app.use('/bcp', require('./routes/bcp'));
app.use('/incidents', require('./routes/incidents'));
app.use('/chatbot', require('./routes/chatbot'));
app.use('/plan-generator', require('./routes/plan_generator'));
app.use('/settings', require('./routes/settings'));
// Phase 2
app.use('/vendors', require('./routes/vendors'));
app.use('/exercises', require('./routes/exercises'));
app.use('/compliance', require('./routes/compliance'));
app.use('/audit', require('./routes/audit'));
// Phase 3
app.use('/training', require('./routes/training'));
app.use('/documents', require('./routes/documents'));
app.use('/dependencies', require('./routes/dependencies'));
// Phase 4
app.use('/reports', require('./routes/reports'));
app.use('/coverage', require('./routes/coverage'));

// ---- Landing redirects to /dashboard (auth required) ----
app.get('/', (req, res) => {
  if (req.session.user) return res.redirect('/dashboard');
  res.redirect('/login');
});

// ---- 404 ----
app.use((req, res) => {
  res.status(404).render('error', { title: 'Not found', message: 'Page not found' });
});

// ---- Error handler ----
app.use((err, req, res, next) => {
  console.error(err);
  res.status(500).render('error', { title: 'Error', message: err.message || 'Something went wrong' });
});

const PORT = process.env.PORT || 3000;
// Bind to 0.0.0.0 so anyone on the same corporate network can reach the app
// at http://<this-laptop's-ip>:PORT. Override with HOST=127.0.0.1 to lock it
// down to this machine only.
const HOST = process.env.HOST || '0.0.0.0';

// Collect the machine's LAN IPv4 addresses so we can print them on boot.
function getLanAddresses() {
  const os = require('os');
  const nets = os.networkInterfaces();
  const addrs = [];
  for (const name of Object.keys(nets)) {
    for (const ni of nets[name] || []) {
      if (ni.family === 'IPv4' && !ni.internal) addrs.push({ name, address: ni.address });
    }
  }
  return addrs;
}

app.listen(PORT, HOST, () => {
  const appName = process.env.APP_NAME || 'BCM Sentinel';
  console.log(`\n  ${appName} running on port ${PORT}`);
  console.log(`  Database: ${path.join(__dirname, 'data', 'bcm.db')}`);
  console.log('\n  Sign in at:');
  console.log(`    http://localhost:${PORT}/login        (this machine only)`);
  if (HOST !== '127.0.0.1') {
    const lan = getLanAddresses();
    if (lan.length) {
      lan.forEach(({ name, address }) => {
        console.log(`    http://${address}:${PORT}/login   (shared — ${name})`);
      });
      console.log('\n  Share the LAN URL with anyone on the same corporate network.');
      console.log('  If they cannot connect, allow inbound TCP on this port in Windows Firewall.');
    } else {
      console.log('  (No LAN IPv4 addresses detected — is this laptop on a network?)');
    }
  }
  try {
    startScheduler();
    console.log('\n  Reminder scheduler started.\n');
  } catch (e) {
    console.error('  Scheduler failed to start:', e.message);
  }
});
