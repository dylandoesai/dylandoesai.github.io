// 12-second cinematic boot sequence.
//
// Timeline:
//   0.0s  panels invisible, face fully scattered, song fades in
//   1.5s  boot text "INITIALIZING PENELOPE..." fades in
//   3.0s  particles begin assembling (face.bootAssemble drives this)
//   7.0s  panels begin sliding in from edges
//   9.5s  boot text fades out
//  10.5s  face fully assembled, song reaches its hook
//  12.0s  resolve -> greeting + daily brief begins

// 12-second cinematic boot sequence — full-screen, particle face
// assembles from a scatter, modules fly in from the edges in waves,
// boot text cycles through stages.
//
// Timeline (full mode):
//   0.0s   boot overlay visible, "INITIALIZING PENELOPE"
//   0.0s   face starts assembling from scattered cloud
//   1.5s   left-edge modules fly in
//   3.0s   right-edge channels fly in (staggered)
//   6.0s   bottom compose dock fades up
//   9.5s   boot text fades, status → online
//  12.0s   resolve → daily brief begins

export async function runBootSequence({
  face, panels, bootEl, statusEl,
  duration = 12000, quick = false,
}) {
  if (statusEl) statusEl.textContent = 'awakening';
  bootEl.classList.remove('hidden');
  bootEl.style.opacity = '1';

  // Set initial offscreen positions BEFORE turning panels on.
  // Left modules from the left, right channels from the right,
  // compose dock from below.
  for (const p of panels) {
    p.style.transition = 'transform 1.4s cubic-bezier(0.16, 1, 0.3, 1), opacity 1.4s ease';
    if (p.classList.contains('channel-mod')) {
      p.style.transform = 'translateX(140%) scale(0.96)';
    } else {
      p.style.transform = 'translateX(-140%) scale(0.96)';
    }
    p.style.opacity = '0';
  }
  const composeDock = document.getElementById('compose-dock');
  if (composeDock) {
    composeDock.style.transition = 'transform 1.6s cubic-bezier(0.16, 1, 0.3, 1), opacity 1.6s ease';
    composeDock.style.transform = 'translate(-50%, 120%)';
    composeDock.style.opacity = '0';
  }
  const topbar = document.getElementById('topbar');
  if (topbar) {
    topbar.style.transition = 'opacity 1.4s ease';
    topbar.style.opacity = '0';
  }

  // QUICK wake (Hey Penelope): compressed timeline
  if (quick) {
    const el = bootEl.querySelector('.boot-text');
    if (el) el.textContent = 'HEY PAPI';
    const assembly = face.bootAssemble(Math.max(1500, duration - 600));
    await sleep(150);
    for (const p of panels) {
      p.style.transform = ''; p.style.opacity = '1';
    }
    if (composeDock) { composeDock.style.transform = 'translate(-50%, 0)'; composeDock.style.opacity = '1'; }
    if (topbar)      { topbar.style.opacity = '1'; }
    await assembly;
    bootEl.style.opacity = '0';
    await sleep(250);
    bootEl.classList.add('hidden');
    if (statusEl) statusEl.textContent = 'listening';
    return;
  }

  // FULL cinematic. Boot text cycles every 1.4s.
  const texts = [
    'INITIALIZING PENELOPE',
    'LOADING NEURAL CORE',
    'SYNCING FACE GEOMETRY',
    'CONNECTING TO CLAUDE',
    'PULLING ANALYTICS',
    'WELCOME HOME, PAPI',
  ];
  let ti = 0;
  const bootTextEl = bootEl.querySelector('.boot-text');
  if (bootTextEl) bootTextEl.textContent = texts[0] + ' …';
  const textInterval = setInterval(() => {
    ti = (ti + 1) % texts.length;
    if (bootTextEl) bootTextEl.textContent = texts[ti] + ' …';
  }, 1400);

  // Face assembly runs the whole boot duration.
  const assemblyPromise = face.bootAssemble(Math.max(4000, duration - 1500));

  // 1.5s: left modules fly in
  await sleep(1500);
  for (const p of panels) {
    if (!p.classList.contains('channel-mod')) {
      p.style.transform = ''; p.style.opacity = '1';
    }
  }

  // 3.0s: right-edge channels fly in, staggered for a wave effect
  await sleep(1500);
  const channels = panels.filter(p => p.classList.contains('channel-mod'));
  for (let i = 0; i < channels.length; i++) {
    setTimeout(() => {
      channels[i].style.transform = ''; channels[i].style.opacity = '1';
    }, i * 140);
  }

  // 6.0s: compose dock + topbar fade up
  await sleep(3000);
  if (topbar)      topbar.style.opacity = '1';
  if (composeDock) { composeDock.style.transform = 'translate(-50%, 0)'; composeDock.style.opacity = '1'; }

  // 9.5s: boot text fades
  await sleep(Math.max(500, duration - 9500));
  clearInterval(textInterval);
  bootEl.style.opacity = '0';

  await assemblyPromise;
  await sleep(400);
  bootEl.classList.add('hidden');
  if (statusEl) statusEl.textContent = 'online';
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
