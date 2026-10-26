// Work'n'Roll landing page: translations, hero animation, language/theme switch, demo video.
(function () {
const T = {
  en: {
    navHow: 'How it works', navLogin: 'Agronomist login',
    scenes: [
      { name: 'Fieldwork', tag: 'Live now', tagline: 'VOICE NOTE · ES', dur: '0:04', quote: 'Catorce kilos de cobre en los almendros, toda la parcela.', fields: [['Parcel', 'P5 · Almond'], ['Product', 'Copper 50% WP'], ['Quantity', '14 kg']], done: 'Field record confirmed', placeholder: 'Drop a fieldwork photo' },
      { name: 'Construction', tag: 'Next', tagline: 'VOICE NOTE · EN', dur: '0:05', quote: 'Poured the slab on level two, east wing, eighteen cubic metres.', fields: [['Site', 'Level 2 · East'], ['Task', 'Concrete pour'], ['Volume', '18 m³']], done: 'Site log entry confirmed', placeholder: 'Drop a construction photo' },
    ],
    eyebrow: 'SA.TECH presents', h1: 'Any job can be logged by voice.', sub: 'First gig: the farm. Farmers talk, the field log fills itself.',
    cta1: 'Try the bot on Telegram', cta2: '▶ Watch the demo', cta3: 'Agronomist login',
    badges: ['Open source', 'Gemma 4', 'ElevenLabs', 'Telegram'],
    probH: 'Nobody types at work', probIntro: 'Hands are busy, phones stay in pockets, and the paperwork piles up.',
    p1h: 'Hands busy', p1: 'Gloves on, engine running. Logs get written weeks later, from memory.',
    p2h: '4 languages', p2: 'Catalan, Spanish, Russian, English on one crew. One official record.',
    p3h: 'Deadline', p3: 'From 1 Jan 2027, Spanish farms must log treatments digitally in the CUE.',
    src: 'Source: Euskadi.eus, Cuaderno Digital de la Explotación Agrícola',
    howH: 'Say it. Check it. Done.',
    steps: [
      { n: '01', h: 'Say it', p: 'Send a voice note on Telegram, in English, Russian, Catalan or Spanish.' },
      { n: '02', h: 'Check it', p: 'Get a card and a voice reply in your language. One tap to confirm.' },
      { n: '03', h: 'Done', p: 'An official record in Catalan and English, linked to your parcel. Excel on request.' },
    ],
    caption: 'Real app: a voice note in Telegram becomes a confirmed field record. Powered by ElevenLabs Scribe + TTS and Gemma 4.',
    expH: 'The expert teaches the machine',
    exp: "The record said 40. The agronomist fixes it once, with a reason: 'she said catorce'. That fix becomes an example. Next time, Gemma gets it right.",
    expSmall: 'Every row is confirmed by the worker, then scored 0–1. Below 0.80 goes to the expert.',
    useH: 'Today the field. Tomorrow any job.', live: 'Live now', nextTag: 'Next', farms: 'Farms',
    next: ['Construction sites', 'Warehouses', 'Kitchens', 'Cleaning crews', 'Workshops'],
    contact: 'Your crew logs work too? Get in touch:',
    openH: 'Built on open technology',
    safeH: 'Safe by design',
    safe: [
      { h: 'Worker confirms first', p: 'Nothing is saved until the person who spoke taps confirm on the card.' },
      { h: 'Expert checks the rest', p: 'Every record gets a score. Anything below 0.80 waits for the agronomist.' },
      { h: 'Every change is traced', p: 'Corrections are stored with the reason and kept in the record history.' },
      { h: 'Your server, your data', p: 'Open source under Apache 2.0, with an open-weight model you can run yourself.' },
    ],
    ckH: 'Cookies', ck: 'We only store your language and light/dark choice on this device. No tracking, no ads.', ckOk: 'OK',
    tech: { gemma: 'Open-weight model that turns speech into a structured record', eleven: 'Scribe for speech-to-text, TTS for voice replies', tg: 'Where workers send voice notes', docker: 'One container setup, runs anywhere', apache: 'Apache 2.0 open-source licence' },
    by: "Work'n'Roll by SA.TECH", book: 'Book a call', dark: 'Switch to dark mode', light: 'Switch to light mode',
  },
  ca: {
    navHow: 'Com funciona', navLogin: 'Accés agrònom',
    scenes: [
      { name: 'Feina de camp', tag: 'Ja disponible', tagline: 'NOTA DE VEU · ES', dur: '0:04', quote: 'Catorce kilos de cobre en los almendros, toda la parcela.', fields: [['Parcel·la', 'P5 · Ametller'], ['Producte', 'Coure 50% WP'], ['Quantitat', '14 kg']], done: 'Registre de camp confirmat', placeholder: 'Deixa una foto de camp' },
      { name: 'Obres', tag: 'Properament', tagline: 'NOTA DE VEU · CA', dur: '0:05', quote: "Hem formigonat la llosa de la planta dos, ala est, divuit metres cúbics.", fields: [['Obra', 'Planta 2 · Est'], ['Tasca', 'Formigonat'], ['Volum', '18 m³']], done: "Entrada de l'obra confirmada", placeholder: "Deixa una foto d'obra" },
    ],
    eyebrow: 'SA.TECH presenta', h1: 'Qualsevol feina es pot registrar amb la veu.', sub: "Primer encàrrec: el camp. El pagès parla i el quadern de camp s'omple sol.",
    cta1: 'Prova el bot a Telegram', cta2: '▶ Mira la demo', cta3: 'Accés agrònom',
    badges: ['Codi obert', 'Gemma 4', 'ElevenLabs', 'Telegram'],
    probH: 'A la feina ningú escriu', probIntro: "Les mans estan ocupades, el mòbil és a la butxaca i la paperassa s'acumula.",
    p1h: 'Mans ocupades', p1: "Amb guants i el motor en marxa. Els registres s'escriuen setmanes després, de memòria.",
    p2h: '4 idiomes', p2: 'Català, castellà, rus i anglès en una mateixa colla. Un sol registre oficial.',
    p3h: 'Termini', p3: "A partir de l'1 de gener de 2027, les explotacions espanyoles hauran de registrar els tractaments digitalment al CUE.",
    src: 'Font: Euskadi.eus, Cuaderno Digital de la Explotación Agrícola',
    howH: 'Digues-ho. Revisa-ho. Fet.',
    steps: [
      { n: '01', h: 'Digues-ho', p: 'Envia una nota de veu per Telegram, en anglès, rus, català o castellà.' },
      { n: '02', h: 'Revisa-ho', p: 'Reps una fitxa i una resposta de veu en el teu idioma. Un toc per confirmar.' },
      { n: '03', h: 'Fet', p: 'Un registre oficial en català i anglès, vinculat a la teva parcel·la. Excel si el demanes.' },
    ],
    caption: "App real: una nota de veu a Telegram es converteix en un registre de camp confirmat. Amb ElevenLabs Scribe + TTS i Gemma 4.",
    expH: "L'expert ensenya la màquina",
    exp: "El registre deia 40. L'agrònom ho corregeix un cop, amb un motiu: «ha dit catorce». Aquesta correcció es converteix en un exemple. La propera vegada, Gemma ho encerta.",
    expSmall: "Cada fila la confirma el treballador i després rep una puntuació de 0 a 1. Per sota de 0,80 passa a l'expert.",
    useH: 'Avui el camp. Demà qualsevol feina.', live: 'Ja disponible', nextTag: 'Properament', farms: 'Explotacions agrícoles',
    next: ['Obres', 'Magatzems', 'Cuines', 'Equips de neteja', 'Tallers'],
    contact: 'El teu equip també registra feina? Escriu-nos:',
    openH: 'Fet amb tecnologia oberta',
    safeH: 'Segur des del disseny',
    safe: [
      { h: 'Primer confirma el treballador', p: 'No es desa res fins que qui ha parlat confirma la fitxa.' },
      { h: "L'expert revisa la resta", p: "Cada registre té una puntuació. Per sota de 0,80 espera l'agrònom." },
      { h: 'Cada canvi queda registrat', p: "Les correccions es desen amb el motiu i queden a l'historial del registre." },
      { h: 'El teu servidor, les teves dades', p: 'Codi obert amb llicència Apache 2.0 i un model de pesos oberts que pots executar tu mateix.' },
    ],
    ckH: 'Galetes', ck: "Només desem l'idioma i el mode clar/fosc en aquest dispositiu. Sense seguiment ni publicitat.", ckOk: "D'acord",
    tech: { gemma: 'Model de pesos oberts que converteix la veu en un registre estructurat', eleven: 'Scribe per transcriure, TTS per a les respostes de veu', tg: 'On els treballadors envien les notes de veu', docker: 'Instal·lació amb contenidors, funciona a qualsevol lloc', apache: 'Llicència de codi obert Apache 2.0' },
    by: "Work'n'Roll de SA.TECH", book: 'Reserva una trucada', dark: 'Mode fosc', light: 'Mode clar',
  },
  es: {
    navHow: 'Cómo funciona', navLogin: 'Acceso agrónomo',
    scenes: [
      { name: 'Trabajo de campo', tag: 'Ya disponible', tagline: 'NOTA DE VOZ · ES', dur: '0:04', quote: 'Catorce kilos de cobre en los almendros, toda la parcela.', fields: [['Parcela', 'P5 · Almendro'], ['Producto', 'Cobre 50% WP'], ['Cantidad', '14 kg']], done: 'Registro de campo confirmado', placeholder: 'Suelta una foto de campo' },
      { name: 'Obras', tag: 'Próximamente', tagline: 'NOTA DE VOZ · ES', dur: '0:05', quote: 'Hemos hormigonado la losa de la planta dos, ala este, dieciocho metros cúbicos.', fields: [['Obra', 'Planta 2 · Este'], ['Tarea', 'Hormigonado'], ['Volumen', '18 m³']], done: 'Entrada de obra confirmada', placeholder: 'Suelta una foto de obra' },
    ],
    eyebrow: 'SA.TECH presenta', h1: 'Cualquier trabajo se puede registrar con la voz.', sub: 'Primer encargo: el campo. El agricultor habla y el cuaderno de campo se rellena solo.',
    cta1: 'Prueba el bot en Telegram', cta2: '▶ Ver la demo', cta3: 'Acceso agrónomo',
    badges: ['Código abierto', 'Gemma 4', 'ElevenLabs', 'Telegram'],
    probH: 'En el trabajo nadie escribe', probIntro: 'Las manos están ocupadas, el móvil en el bolsillo y el papeleo se acumula.',
    p1h: 'Manos ocupadas', p1: 'Con guantes y el motor en marcha. Los registros se escriben semanas después, de memoria.',
    p2h: '4 idiomas', p2: 'Catalán, castellano, ruso e inglés en una misma cuadrilla. Un solo registro oficial.',
    p3h: 'Plazo', p3: 'Desde el 1 de enero de 2027, las explotaciones españolas deberán registrar los tratamientos digitalmente en el CUE.',
    src: 'Fuente: Euskadi.eus, Cuaderno Digital de la Explotación Agrícola',
    howH: 'Dilo. Revísalo. Hecho.',
    steps: [
      { n: '01', h: 'Dilo', p: 'Envía una nota de voz por Telegram, en inglés, ruso, catalán o castellano.' },
      { n: '02', h: 'Revísalo', p: 'Recibes una ficha y una respuesta de voz en tu idioma. Un toque para confirmar.' },
      { n: '03', h: 'Hecho', p: 'Un registro oficial en catalán e inglés, vinculado a tu parcela. Excel si lo pides.' },
    ],
    caption: 'App real: una nota de voz en Telegram se convierte en un registro de campo confirmado. Con ElevenLabs Scribe + TTS y Gemma 4.',
    expH: 'El experto enseña a la máquina',
    exp: 'El registro decía 40. El agrónomo lo corrige una vez, con un motivo: «ha dicho catorce». Esa corrección se convierte en un ejemplo. La próxima vez, Gemma acierta.',
    expSmall: 'Cada fila la confirma el trabajador y luego recibe una puntuación de 0 a 1. Por debajo de 0,80 pasa al experto.',
    useH: 'Hoy el campo. Mañana cualquier trabajo.', live: 'Ya disponible', nextTag: 'Próximamente', farms: 'Explotaciones agrícolas',
    next: ['Obras', 'Almacenes', 'Cocinas', 'Equipos de limpieza', 'Talleres'],
    contact: '¿Tu equipo también registra trabajo? Escríbenos:',
    openH: 'Hecho con tecnología abierta',
    safeH: 'Seguro desde el diseño',
    safe: [
      { h: 'Primero confirma el trabajador', p: 'No se guarda nada hasta que quien ha hablado confirma la ficha.' },
      { h: 'El experto revisa el resto', p: 'Cada registro tiene una puntuación. Por debajo de 0,80 espera al agrónomo.' },
      { h: 'Cada cambio queda registrado', p: 'Las correcciones se guardan con el motivo y quedan en el historial del registro.' },
      { h: 'Tu servidor, tus datos', p: 'Código abierto con licencia Apache 2.0 y un modelo de pesos abiertos que puedes ejecutar tú mismo.' },
    ],
    ckH: 'Cookies', ck: 'Solo guardamos el idioma y el modo claro/oscuro en este dispositivo. Sin seguimiento ni publicidad.', ckOk: 'De acuerdo',
    tech: { gemma: 'Modelo de pesos abiertos que convierte la voz en un registro estructurado', eleven: 'Scribe para transcribir, TTS para las respuestas de voz', tg: 'Donde los trabajadores envían las notas de voz', docker: 'Instalación con contenedores, funciona en cualquier sitio', apache: 'Licencia de código abierto Apache 2.0' },
    by: "Work'n'Roll de SA.TECH", book: 'Reserva una llamada', dark: 'Modo oscuro', light: 'Modo claro',
  },
};

  const $ = id => document.getElementById(id);
  const clamp = v => Math.max(0, Math.min(1, v));
  const reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const SCENE_MS = 8000;
  const HTS = [8, 14, 20, 11, 18, 24, 10, 19, 13, 22, 9, 16, 21, 12];
  const TECH = [
    { name: 'Gemma 4', key: 'gemma' },
    { name: 'ElevenLabs', key: 'eleven', src: 'https://cdn.jsdelivr.net/npm/simple-icons@13.21.0/icons/elevenlabs.svg' },
    { name: 'Telegram', key: 'tg', src: 'https://cdn.jsdelivr.net/npm/simple-icons@13.21.0/icons/telegram.svg' },
    { name: 'Docker', key: 'docker', src: 'https://cdn.jsdelivr.net/npm/simple-icons@13.21.0/icons/docker.svg' },
    { name: 'Apache 2.0', key: 'apache', src: 'https://cdn.jsdelivr.net/npm/simple-icons@13.21.0/icons/apache.svg' },
  ];

  const prefs = window.WNR;
  let lang = prefs ? prefs.initialLang() : 'en';
  let theme = prefs ? prefs.initialTheme() : 'light';
  let scene = 0, el = 0;

  const el$ = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };

  // Static hero widgets that don't change with language.
  const bars = HTS.map(h => { const s = el$('span'); s.style.height = h + 'px'; $('c-bars').appendChild(s); return s; });
  const fieldEls = [0, 1, 2].map(() => {
    const d = el$('div'), k = el$('div', 'k'), v = el$('div', 'v');
    d.append(k, v); $('c-fields').appendChild(d);
    return { d, k, v };
  });
  const scenes = document.querySelectorAll('.scene');
  const canvases = [...scenes].map(s => s.querySelector('canvas'));
  const tabs = [0, 1].map(i => {
    const b = el$('button', 'tab glass'), name = el$('b'), tag = el$('small'), track = el$('span', 'track'), fill = el$('span', 'fill');
    b.type = 'button'; track.appendChild(fill); b.append(name, tag, track);
    b.addEventListener('click', () => { scene = i; el = 0; frame(); });
    $('tabs').appendChild(b);
    return { b, name, tag, fill };
  });

  function applyTheme() {
    const vars = prefs ? prefs.cssVars(theme) : {};
    Object.keys(vars).forEach(k => document.documentElement.style.setProperty(k, vars[k]));
    document.documentElement.dataset.theme = theme;
    const t = T[lang] || T.en;
    $('theme').setAttribute('aria-label', theme === 'dark' ? t.light : t.dark);
    $('theme').title = $('theme').getAttribute('aria-label');
  }

  function applyLang() {
    const t = T[lang] || T.en;
    document.documentElement.lang = lang;
    document.querySelectorAll('[data-t]').forEach(n => { n.textContent = t[n.dataset.t]; });
    document.querySelectorAll('[data-lang]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.lang === lang)));
    $('demo-video').setAttribute('aria-label', t.caption);
    $('cookies').setAttribute('aria-label', t.ckH);

    $('steps').replaceChildren(...t.steps.map(s => { const li = el$('li'); li.append(el$('div', 'n', s.n), el$('h3', '', s.h), el$('p', '', s.p)); return li; }));

    const live = el$('div', 'use live'); live.append(el$('span', 'pill', t.live), el$('b', '', t.farms));
    $('uses').replaceChildren(live, ...t.next.map(u => { const d = el$('div', 'use'); d.append(el$('span', 'pill', t.nextTag), el$('b', '', u)); return d; }));

    $('tech').replaceChildren(...TECH.map(x => {
      const d = el$('div'), name = el$('div', 'name');
      if (x.src) { const img = el$('img'); img.src = x.src; img.alt = ''; img.onerror = () => img.remove(); name.appendChild(img); }
      name.appendChild(el$('span', '', x.name));
      d.append(name, el$('div', 'role', t.tech[x.key]));
      return d;
    }));

    $('safe').replaceChildren(...t.safe.map(q => { const d = el$('div'); d.append(el$('h3', '', q.h), el$('p', '', q.p)); return d; }));

    t.scenes.forEach((s, i) => { tabs[i].name.textContent = s.name; tabs[i].tag.textContent = s.tag; });
    applyTheme();
    frame();
  }

  function set(l, th) {
    lang = l; theme = th;
    if (prefs) prefs.save(lang, theme);
    applyLang();
  }

  // One hero frame: scene cross-fade, tab progress, and the voice-note card build-up.
  function frame() {
    const t = T[lang] || T.en, sc = t.scenes[scene];
    scenes.forEach((s, i) => s.classList.toggle('on', i === scene));
    tabs.forEach((tb, i) => {
      tb.b.setAttribute('aria-pressed', String(i === scene));
      tb.fill.style.width = (i === scene ? (el / SCENE_MS) * 100 : 0) + '%';
    });
    $('c-tagline').textContent = sc.tagline;
    $('c-tag').textContent = sc.tag;
    $('c-tag').classList.toggle('live', scene === 0);
    $('c-dur').textContent = sc.dur;
    $('c-done').textContent = sc.done;
    $('c-quote').textContent = '“' + sc.quote.slice(0, Math.round(sc.quote.length * clamp((el - 600) / 2600))) + '”';
    const recP = clamp((el - 300) / 2900);
    bars.forEach((b, i) => b.classList.toggle('on', i / HTS.length < recP));
    fieldEls.forEach((f, i) => {
      const p = clamp((el - 3400 - i * 250) / 350);
      f.k.textContent = sc.fields[i][0]; f.v.textContent = sc.fields[i][1];
      f.d.style.opacity = p; f.d.style.transform = 'translateY(' + (1 - p) * 6 + 'px)';
    });
    const cp = clamp((el - 4600) / 400);
    const c = $('c-confirm'); c.style.opacity = cp; c.style.transform = 'scale(' + (0.96 + 0.04 * cp) + ')';
  }

  function drawBG(time) {
    if (!window.WNRBG) return;
    ['field', 'site'].forEach((k, i) => {
      const c = canvases[i];
      if (i !== scene && el > 1200) return;
      const dpr = Math.min(1.5, window.devicePixelRatio || 1);
      const W = Math.round(c.clientWidth * dpr), H = Math.round(c.clientHeight * dpr);
      if (!W || !H) return;
      if (c.width !== W || c.height !== H) { c.width = W; c.height = H; }
      window.WNRBG[k](c.getContext('2d'), W, H, time);
    });
  }

  document.querySelectorAll('[data-lang]').forEach(b => b.addEventListener('click', () => set(b.dataset.lang, theme)));
  $('theme').addEventListener('click', () => set(lang, theme === 'dark' ? 'light' : 'dark'));

  let seen = false; try { seen = localStorage.getItem('wnr.cookies') === 'ok'; } catch (e) {}
  $('cookies').hidden = seen;
  $('cookies-ok').addEventListener('click', () => { try { localStorage.setItem('wnr.cookies', 'ok'); } catch (e) {} $('cookies').hidden = true; });

  applyLang();

  if (reduced) {
    el = SCENE_MS * 0.9; frame(); drawBG(2);
    window.addEventListener('resize', () => drawBG(2));
  } else {
    let last = performance.now();
    const loop = now => {
      el += now - last; last = now;
      if (el >= SCENE_MS) { el = 0; scene = (scene + 1) % 2; }
      frame(); drawBG(now / 1000);
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  }

  // Demo video: autoplay muted; if the MP4 is missing, the poster behind it stays visible.
  const v = $('demo-video'), play = $('play');
  v.muted = true;
  v.querySelector('source').addEventListener('error', () => { v.style.display = 'none'; play.hidden = true; });
  if (reduced) play.hidden = false;
  else { const p = v.play(); if (p && p.catch) p.catch(() => {}); }
  play.addEventListener('click', () => { v.controls = true; v.play().catch(() => {}); play.hidden = true; });
})();
