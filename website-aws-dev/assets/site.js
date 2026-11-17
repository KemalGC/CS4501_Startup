(function () {
  'use strict';
  const key = 'strokesense-color-theme';
  let theme = 'light';
  try {
    const saved = window.localStorage.getItem(key);
    theme = saved === 'dark' || saved === 'light' ? saved :
      (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  } catch (_) {
    theme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  document.documentElement.dataset.theme = theme;

  document.addEventListener('DOMContentLoaded', () => {
    const toggle = document.querySelector('[data-theme-toggle]');
    const label = toggle && toggle.querySelector('.theme-label');
    const icon = toggle && toggle.querySelector('.theme-icon');
    function updateControl() {
      if (!toggle) return;
      toggle.setAttribute('aria-label', theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode');
      toggle.setAttribute('aria-pressed', String(theme === 'dark'));
      if (label) label.textContent = theme === 'dark' ? 'Light mode' : 'Dark mode';
      if (icon) icon.textContent = theme === 'dark' ? '☀' : '☾';
    }
    updateControl();
    if (toggle) toggle.addEventListener('click', () => {
      theme = theme === 'dark' ? 'light' : 'dark';
      document.documentElement.dataset.theme = theme;
      try { window.localStorage.setItem(key, theme); } catch (_) {}
      updateControl();
      document.dispatchEvent(new CustomEvent('strokesense:theme-changed', { detail: { theme } }));
    });

    const menu = document.querySelector('[data-menu-toggle]');
    const mobile = document.getElementById('mobile-nav');
    if (menu && mobile) {
      menu.addEventListener('click', () => {
        const open = menu.getAttribute('aria-expanded') !== 'true';
        menu.setAttribute('aria-expanded', String(open));
        mobile.classList.toggle('is-open', open);
      });
      for (const link of mobile.querySelectorAll('a')) {
        link.addEventListener('click', () => { menu.setAttribute('aria-expanded', 'false'); mobile.classList.remove('is-open'); });
      }
    }

  });
})();
