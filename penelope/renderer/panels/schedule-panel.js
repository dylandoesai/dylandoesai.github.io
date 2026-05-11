// Schedule + Todos.
// Schedule shape (config/schedule.json):
//   { "events": [{"time": "10:30", "title": "...", "where": "..."}, ...] }
// Todos shape (config/todos.json):
//   { "items": [{"text": "...", "done": false, "priority": "high"}, ...] }

export function renderSchedule(schedule, todos) {
  const sched = document.getElementById('schedule-list');
  sched.innerHTML = '';
  for (const e of (schedule.events || []).slice(0, 6)) {
    const li = document.createElement('li');
    li.innerHTML = `<span class="time">${e.time || ''}</span>${escapeHtml(e.title || '')}` +
                   (e.where ? ` <span style="opacity:0.5">@ ${escapeHtml(e.where)}</span>` : '');
    sched.appendChild(li);
  }
  if (!sched.childElementCount) {
    sched.innerHTML = '<li style="opacity:0.5">nothing scheduled</li>';
  }

  const t = document.getElementById('todo-list');
  t.innerHTML = '';
  const items = (todos.items || []).slice(0, 8);
  for (const it of items) {
    const li = document.createElement('li');
    if (it.done) li.classList.add('done');
    li.textContent = it.text || '';
    t.appendChild(li);
  }
  if (!items.length) {
    t.innerHTML = '<li style="opacity:0.5">no todos</li>';
  }
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
