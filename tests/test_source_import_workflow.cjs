// Run with: node --test tests/test_source_import_workflow.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const script = fs.readFileSync(path.join(__dirname, '../iam_automation/static/js/source-import-workflow.js'), 'utf8');

function setup() {
  const handlers = {};
  const state = {task: null, scroll: null, focus: null};
  const timeline = {id: 'source-timeline', getAttribute: () => '/watcher-status?view=RECENT_FILES', getBoundingClientRect: () => ({top: -600})};
  const heading = {focus: options => {state.focus = options.preventScroll;}};
  const source = selector => ({matches: value => value === selector});
  const document = {
    addEventListener: (name, handler) => {handlers[name] = handler;},
    querySelector: () => state.task,
    getElementById: id => id === 'source-timeline' ? timeline : heading,
  };
  vm.runInNewContext(script, {document, window: {scrollY: 1000, scrollTo: options => {state.scroll = options.top;}}});
  function emit(name, detail) {
    const event = {detail, prevented: false, preventDefault() {this.prevented = true;}};
    handlers[name](event);
    return event;
  }
  return {state, timeline, source, emit};
}

test('a refresh started before Import cannot swap while preparation is pending', () => {
  const {emit, source, timeline} = setup();
  const poll = {elt: source(''), target: timeline, xhr: {}, shouldSwap: true};
  assert.equal(emit('htmx:beforeRequest', poll).prevented, false);
  emit('htmx:beforeRequest', {elt: source('.source-import-form'), target: {}, xhr: {}});
  emit('htmx:beforeSwap', poll);
  assert.equal(poll.shouldSwap, false);
  assert.equal(emit('htmx:beforeRequest', {...poll, xhr: {}}).prevented, true);
});

test('a second Import is rejected before synchronization can abort the first', () => {
  const {emit, source} = setup();
  const detail = {elt: source('.source-import-form'), target: {}, xhr: {}};
  emit('htmx:beforeRequest', detail);
  assert.equal(emit('htmx:confirm', {...detail, xhr: {}}).prevented, true);
  emit('htmx:afterRequest', detail);
  assert.equal(emit('htmx:confirm', {...detail, xhr: {}}).prevented, false);
});

test('task progress and completed results remain visible until Close', () => {
  const {emit, source, timeline, state} = setup();
  state.task = {};
  const poll = {elt: source(''), target: timeline, xhr: {}, shouldSwap: true};
  assert.equal(emit('htmx:beforeRequest', poll).prevented, true);
  emit('htmx:beforeSwap', poll);
  assert.equal(poll.shouldSwap, false);
  const progress = {elt: source(''), target: {id: 'import-task-1'}, xhr: {}, shouldSwap: true};
  assert.equal(emit('htmx:beforeRequest', progress).prevented, false);
  emit('htmx:beforeSwap', progress);
  assert.equal(progress.shouldSwap, true);
});

test('Close retains the selected view and returns to workflow after layout settles', () => {
  const {emit, source, timeline, state} = setup();
  state.task = {};
  const close = {elt: source('[data-import-close]'), target: timeline, xhr: {}, shouldSwap: true};
  emit('htmx:configRequest', close);
  assert.equal(close.path, '/watcher-status?view=RECENT_FILES');
  assert.equal(emit('htmx:beforeRequest', close).prevented, false);
  emit('htmx:beforeSwap', close);
  assert.equal(close.shouldSwap, true);
  emit('htmx:afterRequest', close);
  assert.equal(state.scroll, null);
  emit('htmx:afterSettle', close);
  assert.equal(state.scroll, 376);
  assert.equal(state.focus, true);
});

test('a failed POST releases preparation lock for retry and automatic refresh', () => {
  const {emit, source, timeline} = setup();
  const post = {elt: source('.source-import-form'), target: {}, xhr: {}, successful: false};
  emit('htmx:beforeRequest', post);
  emit('htmx:afterRequest', post);
  assert.equal(emit('htmx:beforeRequest', {elt: source(''), target: timeline, xhr: {}}).prevented, false);
});

test('background refreshes never move focus or scroll', () => {
  const {emit, state} = setup();
  emit('htmx:afterSettle', {xhr: {}});
  assert.equal(state.scroll, null);
  assert.equal(state.focus, null);
});
