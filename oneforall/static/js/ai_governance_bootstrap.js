/* Initialize AI Governance views from escaped HTML data, never executable template text. */
(function () {
  'use strict';
  var api = window.AIGov;
  if (!api) return;
  function element(id) { return document.getElementById(id); }
  function enabled(value) { return value === 'true'; }
  function number(value) { return Number(value) || 0; }

  var target = element('aigAssessment');
  if (target) api.assessmentForm(target, {
    assessmentId: number(target.dataset.assessmentId),
    applicationId: number(target.dataset.applicationId)
  });
  target = element('aigAssessments');
  if (target) api.assessmentList(target, {
    canManage: enabled(target.dataset.canManage),
    dimensionsButton: element('aigDimensionsBtn')
  });
  target = element('aigDecisionQueue');
  if (target) api.decisionQueue(target);
  target = element('aigImport');
  if (target) api.importer(target);
  target = element('aigIntake');
  if (target) api.intake(target, {
    intakeId: number(target.dataset.intakeId),
    userId: number(target.dataset.userId),
    userName: target.dataset.userName || '',
    sourceRef: target.dataset.sourceRef || '',
    sourceName: target.dataset.sourceName || '',
    canEdit: enabled(target.dataset.canEdit)
  });
  target = element('aigInventory');
  if (target) api.inventory(target, { canRegister: enabled(target.dataset.canRegister) });
  target = element('aigPortfolio');
  if (target) api.portfolio(target);
  target = element('aigOverview');
  if (target) api.overview(target);
  target = element('aigRegulatory');
  if (target) api.regulatoryQueue(target);
  target = element('aigRequests');
  if (target) api.requests(target, { canCreate: enabled(target.dataset.canCreate) });
  target = element('aigWorklist');
  if (target) api.worklist(target);
  target = element('aigReview');
  if (target) api.review(target);
  target = element('aigWorkspace');
  if (target) api.workspace(target, { applicationId: number(target.dataset.applicationId) });
}());
