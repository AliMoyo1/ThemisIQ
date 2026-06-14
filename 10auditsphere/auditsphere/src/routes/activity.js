const express = require('express');
const router  = express.Router();
const { getLog } = require('../services/activityLog');

router.get('/', (req, res) => {
  const { entity_id, entity_type, user_id, limit, offset } = req.query;
  res.json(getLog({ entityId: entity_id, entityType: entity_type, userId: user_id,
    limit: parseInt(limit) || 100, offset: parseInt(offset) || 0 }));
});

module.exports = router;
