(() => {
  'use strict';
  window.themisWaitReportRun = async (runId, onProgress = () => {}) => {
    const id = Number(runId);
    if (!Number.isSafeInteger(id) || id < 1) throw new Error('Invalid report job.');
    for (let attempt = 0; attempt < 120; attempt++) {
      const response = await fetch(`/api/reports/runs/${id}`, {cache:'no-store'});
      let result;
      try { result = await response.json(); } catch (_) { result = {}; }
      if (!response.ok) throw new Error(result.error || 'Report job could not be opened.');
      if (result.status === 'completed' && result.frozen) return result;
      if (result.status === 'failed') throw new Error(result.error || 'Report generation failed.');
      onProgress(result.progress_stage || result.status || 'queued');
      await new Promise(resolve => setTimeout(resolve, 2000));
    }
    throw new Error('The report is still running. Open Reports later to see its result.');
  };
})();
