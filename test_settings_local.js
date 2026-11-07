// Exercise the real page script using a minimal DOM and an in-memory localStorage.
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const html = fs.readFileSync('static/home.html', 'utf8');
const inline = html.match(/<script>([\s\S]*?)<\/script>/)[1];

function makePage(storage, denyStorage = false) {
  const elements = {};
  function element(id) {
    return elements[id] || (elements[id] = {
      id, value: '', hidden: false, innerHTML: '', files: [], disabled: false,
      handlers: {}, classList: { add() {}, remove() {} },
      addEventListener(type, fn) { (this.handlers[type] ||= []).push(fn); },
      dispatch(type, event = {}) { return Promise.all((this.handlers[type] || []).map(fn => fn(event))); },
      setCustomValidity(message) { this.validationMessage = message; },
      reportValidity() {}, focus() {}, appendChild() {},
      showModal() { this.open = true; }, close() { this.open = false; },
      getBoundingClientRect() { return {left: 0, right: 100, top: 0, bottom: 100}; },
    });
  }
  const requests = [];
  const localStorage = {
    getItem(key) { if (denyStorage) throw Error('denied'); return storage[key] ?? null; },
    setItem(key, value) { if (denyStorage) throw Error('denied'); storage[key] = value; },
    removeItem(key) { if (denyStorage) throw Error('denied'); delete storage[key]; },
  };
  const context = vm.createContext({
    document: { getElementById: element, createElement: element, addEventListener() {} },
    window: { location: { href: 'https://cret.example.com/prefix/' } }, URL,
    localStorage, TextDecoder,
    fetch: async (url, options) => {
      requests.push({url, options});
      return {ok: true, body: {getReader: () => ({read: async () => ({done: true})})}};
    },
  });
  vm.runInContext(fs.readFileSync('static/attachments.js', 'utf8'), context);
  vm.runInContext(inline, context);
  return {element, requests};
}

(async () => {
  const storage = {};
  let page = makePage(storage);
  assert.strictEqual(page.element('questionCount').value, '6');
  assert.strictEqual(Boolean(page.element('generateIllustration').checked), false);
  page.element('generateIllustration').checked = true;
  await page.element('generateIllustration').dispatch('change');
  assert.strictEqual(storage['cret2-generate-illustration'], 'true');
  page.element('questionCount').value = '12';
  await page.element('questionCount').dispatch('input');
  assert.strictEqual(storage['cret2-question-count'], '12');
  page = makePage(storage);
  assert.strictEqual(page.element('questionCount').value, '12');
  assert.strictEqual(page.element('generateIllustration').checked, true);
  page.element('input').value = 'Chủ đề';
  await page.element('learn').dispatch('click');
  assert.strictEqual(JSON.parse(page.requests[0].options.body).question_count, 12);
  assert.strictEqual(JSON.parse(page.requests[0].options.body).generate_illustration, true);
  assert.strictEqual(JSON.parse(page.requests[0].options.body).browser_base_url, 'https://cret.example.com/prefix');
  page.element('questionCount').value = '0';
  await page.element('questionCount').dispatch('input');
  await page.element('learn').dispatch('click');
  assert.strictEqual(page.requests.length, 1);
  assert.strictEqual(page.element('settingsDialog').open, true);
  await page.element('resetSettings').dispatch('click');
  assert.strictEqual(page.element('questionCount').value, '6');
  assert.strictEqual(storage['cret2-question-count'], undefined);
  assert.strictEqual(storage['cret2-generate-illustration'], undefined);
  assert.strictEqual(page.element('generateIllustration').checked, false);
  page = makePage(storage);
  assert.strictEqual(page.element('questionCount').value, '6');
  const unavailable = makePage({}, true);
  unavailable.element('questionCount').value = '4';
  await unavailable.element('questionCount').dispatch('input');
  assert(unavailable.element('settingsStorageStatus').textContent.includes('Không lưu được'));
  unavailable.element('input').value = 'Chủ đề';
  await unavailable.element('learn').dispatch('click');
  assert.strictEqual(JSON.parse(unavailable.requests[0].options.body).question_count, 4);
  console.log('Local settings: default, persistence, request, invalid input, reset and storage failure passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
