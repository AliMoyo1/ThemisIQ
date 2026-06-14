require('dotenv').config();
const express = require('express');
const path = require('path');
const cors = require('cors');
const session = require('express-session');

const app = express();
const PORT = process.env.PORT || 3000;

app.use(cors());
app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.use(session({ secret: process.env.SESSION_SECRET || 'auditsphere-secret-2025', resave: false, saveUninitialized: true }));
app.use(express.static(path.join(__dirname, 'public')));
app.use('/uploads', express.static(path.join(__dirname, 'uploads')));

// API routes
app.use('/api', require('./routes/api'));

// Serve frontend
app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

// Start reminder scheduler
const { startReminderCron } = require('./services/email');
startReminderCron();

app.listen(PORT, () => {
  console.log(`\n🔵 AuditSphere running at http://localhost:${PORT}`);
  console.log(`📋 API at http://localhost:${PORT}/api`);
  if (!process.env.ANTHROPIC_API_KEY) {
    console.log(`⚠️  ANTHROPIC_API_KEY not set — AI features disabled. Add to .env file.`);
  } else {
    console.log(`✅ AI features enabled`);
  }
  if (!process.env.SMTP_USER) {
    console.log(`📧 Email: Using Ethereal test mode (no real emails sent)`);
  }
});
