// Attach `req.audit(...)` to every request so route handlers can emit
// audit entries cheaply without boilerplate.

const { fromReq } = require('../services/audit');

module.exports = function (req, res, next) {
  req.audit = fromReq(req);
  next();
};
