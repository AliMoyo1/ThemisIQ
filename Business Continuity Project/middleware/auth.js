// Auth guards

function requireAuth(req, res, next) {
  if (!req.session.user) {
    req.flash('error', 'Please sign in to continue.');
    return res.redirect('/login');
  }
  next();
}

function requireRole(...roles) {
  return function (req, res, next) {
    if (!req.session.user) return res.redirect('/login');
    if (!roles.includes(req.session.user.role)) {
      req.flash('error', 'You do not have permission to do that.');
      return res.redirect('/dashboard');
    }
    next();
  };
}

module.exports = { requireAuth, requireRole };
