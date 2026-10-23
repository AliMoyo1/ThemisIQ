function openReminderModal(){
  const m = document.getElementById('reminderModal');
  m.style.display='flex';
  // Pre-select current module from body data attribute
  const mod = document.body.getAttribute('data-module') || 'platform';
  document.getElementById('remModule').value = mod;
  // Default to 1 hour from now
  const now = new Date();
  now.setHours(now.getHours() + 1);
  document.getElementById('remAt').value = now.toISOString().slice(0,16);
}
function closeReminderModal(){ document.getElementById('reminderModal').style.display='none'; }
document.getElementById('reminderModal').addEventListener('click',function(event){
  if(event.target.closest('[data-reminder-close]'))closeReminderModal();
});
document.getElementById('reminderForm').addEventListener('submit',createReminder);
async function createReminder(e){
  e.preventDefault();
  const body = {
    title: document.getElementById('remTitle').value,
    message: document.getElementById('remMessage').value,
    remind_at: document.getElementById('remAt').value,
    repeat_interval: document.getElementById('remRepeat').value,
    module: document.getElementById('remModule').value,
  };
  const resp = await fetch('/api/reminders', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) });
  if(resp.ok){
    closeReminderModal();
    document.getElementById('reminderForm').reset();
    if(typeof showToast==='function') showToast('Reminder created successfully');
  }
}
