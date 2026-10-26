// Shared language + theme state for the Work'n'Roll pages (persisted in localStorage).
window.WNR = window.WNR || (function () {
  const LK = 'wnr.lang', TK = 'wnr.theme';
  const THEMES = {
    light: {
      bg: '#f3f4ef', surface: '#ffffff', ink: '#18211c', ink2: '#3b443e', muted: '#5d665f', line: '#e2e3db', btnLine: '#c9ccc1',
      accent: '#2e5a37', accentHover: '#24482c', onAccent: '#ffffff', soft: '#ecebe4', okBg: '#e2ede0', okInk: '#2e5a37',
      amberBg: '#fff4dc', amberLine: '#efd59c', amberInk: '#7a4708', blueBg: '#e2e8f4', blueInk: '#22407a',
      deep: '#17211b', header: 'rgba(243,244,239,0.94)', logoBg: '#ffffff', logoFilter: 'none', techFilter: 'none', shadow: 'rgba(23,33,27,0.16)',
    },
    dark: {
      bg: '#0f1511', surface: '#18201b', ink: '#eef1ea', ink2: '#c9d0c8', muted: '#9aa59c', line: '#2a342d', btnLine: '#3d4a41',
      accent: '#8cc796', accentHover: '#a3d6ab', onAccent: '#0f1a12', soft: '#252e28', okBg: '#1f3324', okInk: '#a3d6ab',
      amberBg: '#2b2314', amberLine: '#5a4520', amberInk: '#f0c674', blueBg: '#1c2638', blueInk: '#a9c1ef',
      deep: '#070b08', header: 'rgba(15,21,17,0.92)', logoBg: '#000000', logoFilter: 'invert(1)', techFilter: 'invert(1)', shadow: 'rgba(0,0,0,0.5)',
    },
  };
  function read(k, d) { try { return localStorage.getItem(k) || d; } catch (e) { return d; } }
  function write(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  function initialLang() {
    const s = read(LK, '');
    if (s) return s;
    const n = (navigator.language || 'en').slice(0, 2);
    return n === 'ca' || n === 'es' ? n : 'en';
  }
  function initialTheme() {
    const s = read(TK, '');
    if (s) return s;
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  function cssVars(name) {
    const t = THEMES[name] || THEMES.light;
    const o = {};
    Object.keys(t).forEach(k => { o['--' + k] = t[k]; });
    return o;
  }
  return { THEMES, initialLang, initialTheme, cssVars, save: (l, th) => { write(LK, l); write(TK, th); } };
})();
