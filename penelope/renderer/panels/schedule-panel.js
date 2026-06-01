// Schedule + Todos. Clickable rows open Calendar.app / Reminders.app.
// Header click opens the relevant Apple app via URL scheme.
//
// Schedule shape:
//   { "events": [{"time": "10:30", "title": "...", "where": "..."}, ...] }
// Todos shape:
//   { "items": [{"text": "...", "done": false, "priority": "high"}, ...] }

function openApp(scheme) {
  if (window.penelope?.openExternal) window.penelope.openExternal(scheme);
  else window.open(scheme, '_blank');
}
function pulse() { if (window.penelopeDev?.pulse) window.penelopeDev.pulse(); }

export function renderSchedule(schedule, todos) {
  const sched = document.getElementById('schedule-list');
  sched.innerHTML = '';
  for (const e of (schedule.events || []).slice(0, 6)) {
    const li = document.createElement('li');
    li.innerHTML = `<span class="time">${e.time || ''}</span>${escapeHtml(e.title || '')}` +
                   (e.where ? ` <span style="opacity:0.5">@ ${escapeHtml(e.where)}</span>` : '');
    li.style.cursor = 'pointer';
    li.title = 'Open in Calendar.app';
    li.onclick = () => { pulse(); openApp('ical://'); };
    li.addEventListener('mouseenter', () =>
      li.style.boxShadow = 'inset 0 0 0 1px rgba(0,229,255,0.4)');
    li.addEventListener('mouseleave', () => li.style.boxShadow = '');
    sched.appendChild(li);
  }
  if (!sched.childElementCount) {
    sched.innerHTML = '<li style="opacity:0.5;cursor:pointer">nothing scheduled · click to open Calendar</li>';
    sched.firstChild.onclick = () => { pulse(); openApp('ical://'); };
  }

  const t = document.getElementById('todo-list');
  t.innerHTML = '';
  const items = (todos.items || []).slice(0, 8);
  for (const it of items) {
    const li = document.createElement('li');
    if (it.done) li.classList.add('done');
    li.textContent = it.text || '';
    li.style.cursor = 'pointer';
    li.title = 'Open in Reminders.app';
    li.onclick = () => { pulse(); openApp('x-apple-reminderkit://'); };
    li.addEventListener('mouseenter', () =>
      li.style.boxShadow = 'inset 0 0 0 1px rgba(0,229,255,0.4)');
    li.addEventListener('mouseleave', () => li.style.boxShadow = '');
    t.appendChild(li);
  }
  if (!items.length) {
    t.innerHTML = '<li style="opacity:0.5;cursor:pointer">no todos · click to open Reminders</li>';
    t.firstChild.onclick = () => { pulse(); openApp('x-apple-reminderkit://'); };
  }
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
