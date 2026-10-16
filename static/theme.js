// Cret2 theme switch. Dark is the default and is already set on <html> in the
// markup, so the first paint is dark with no flash and no JS needed. This file
// only (a) re-applies a remembered choice before the body parses and (b) wires
// the "Chế độ tối" switch on each page.
(function () {
  var STORAGE_KEY = 'cret2-theme';
  var DARK = 'dark';
  var LIGHT = 'light';
  var root = document.documentElement;

  function read() {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch (error) {
      return null; // private mode / storage disabled: keep the markup default
    }
  }

  function write(theme) {
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch (error) {
      /* not fatal: the choice just will not outlive the page */
    }
  }

  function sync(theme) {
    root.setAttribute('data-theme', theme);
    var toggle = document.getElementById('themeToggle');
    if (!toggle) return;
    var dark = theme === DARK;
    toggle.setAttribute('aria-checked', dark ? 'true' : 'false');
    toggle.classList.toggle('is-on', dark);
  }

  // Runs in <head>: a remembered choice lands before the body is painted.
  var remembered = read();
  if (remembered === DARK || remembered === LIGHT) sync(remembered);

  function wire() {
    var toggle = document.getElementById('themeToggle');
    if (!toggle) return;
    sync(root.getAttribute('data-theme') === LIGHT ? LIGHT : DARK);
    toggle.addEventListener('click', function () {
      var next = root.getAttribute('data-theme') === DARK ? LIGHT : DARK;
      sync(next);
      write(next);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', wire);
  } else {
    wire();
  }
})();
