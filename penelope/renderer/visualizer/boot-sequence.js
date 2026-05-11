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

export async function runBootSequence({
  face, panels, song, bootEl, statusEl,
  duration = 12000, quick = false,
}) {
  if (statusEl) statusEl.textContent = 'awakening';
  bootEl.classList.remove('hidden');
  bootEl.style.opacity = '0';

  // hide panels
  for (const p of panels) {
    p.style.transition = 'transform 1.2s ease, opacity 1.2s ease';
    p.style.transform = p.id.includes('left')
      ? 'translateX(-120%)'
      : p.id.includes('right')
        ? 'translateX(120%)'
        : 'translateY(120%)';
    p.style.opacity = '0';
  }

  if (song && song.src) {
    try { song.volume = 0; await song.play(); fadeIn(song, 1800, 0.8); } catch {}
  }

  if (quick) {
    // Fast wake (~2.5s): immediate assembly, panels slide in tight, no text shuffle.
    bootEl.style.opacity = '1';
    const el = bootEl.querySelector('.boot-text');
    if (el) el.textContent = 'PENELOPE';
    const assembly = face.bootAssemble(Math.max(1500, duration - 800));
    await sleep(200);
    for (const p of panels) { p.style.transform = ''; p.style.opacity = '1'; }
    await assembly;
    bootEl.style.opacity = '0';
    await sleep(250);
    bootEl.classList.add('hidden');
    if (statusEl) statusEl.textContent = 'listening';
    return;
  }

  // Full cinematic
  await sleep(1500);
  bootEl.style.opacity = '1';
  const texts = [
    'INITIALIZING PENELOPE',
    'LOADING NEURAL CORE',
    'SYNCING FACE GEOMETRY',
    'CONNECTING TO CLAUDE',
    'PULLING ANALYTICS',
    'WELCOME HOME, PAPI',
  ];
  let ti = 0;
  const textInterval = setInterval(() => {
    ti = (ti + 1) % texts.length;
    const el = bootEl.querySelector('.boot-text');
    if (el) el.textContent = texts[ti] + ' …';
  }, 1400);

  await sleep(1500);
  const assemblyPromise = face.bootAssemble(Math.max(4000, duration - 4000));

  await sleep(4000);
  for (const p of panels) { p.style.transform = ''; p.style.opacity = '1'; }

  await sleep(Math.max(500, duration - 9500));
  clearInterval(textInterval);
  bootEl.style.opacity = '0';

  await assemblyPromise;
  await sleep(400);
  bootEl.classList.add('hidden');
  if (statusEl) statusEl.textContent = 'online';
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function fadeIn(audio, ms, target) {
  const start = audio.volume;
  const t0 = performance.now();
  const step = () => {
    const t = (performance.now() - t0) / ms;
    if (t >= 1) { audio.volume = target; return; }
    audio.volume = start + (target - start) * t;
    requestAnimationFrame(step);
  };
  step();
}
