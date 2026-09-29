'use strict';
const fsp = require('node:fs/promises');
const { buildComponents } = require('./components');
const { loadState, saveState } = require('./state');

/** Components that still have to be installed (missing from state.json, other version, or gone from disk). */
async function pendingComponents(ctx) {
  const state = await loadState(ctx.L.state);
  const all = ctx.components || buildComponents(ctx); // ctx.components: test hook
  const done = new Set();
  for (const c of all) {
    const rec = state.components[c.id];
    if (rec && rec.version === c.version && (await c.verify(ctx))) done.add(c.id);
  }
  return { all, done, state };
}

/** Description of the plan for the UI: what will be installed and how much it weighs. */
async function describePlan(ctx) {
  const { all, done } = await pendingComponents(ctx);
  return all.map((c) => ({ id: c.id, weight: c.weight, network: c.network !== false, done: done.has(c.id) }));
}

/**
 * Installs every missing component in order. `emit` receives
 *   { type: 'component', id, status: 'running'|'done'|'skipped'|'error', done?, total?, note?, error? }.
 * An abort keeps partial downloads so the next run resumes; a failure stops the run and rethrows.
 */
async function runSetup(ctx, emit = () => {}) {
  const skip = new Set(ctx.skip || []);
  await fsp.mkdir(ctx.L.logs, { recursive: true });
  await fsp.mkdir(ctx.L.downloads, { recursive: true });
  const { all, done, state } = await pendingComponents(ctx);

  for (const c of all) {
    ctx.signal?.throwIfAborted();
    if (done.has(c.id)) { emit({ type: 'component', id: c.id, status: 'done' }); continue; }
    if (skip.has(c.id)) { emit({ type: 'component', id: c.id, status: 'skipped' }); continue; }

    emit({ type: 'component', id: c.id, status: 'running' });
    try {
      await c.install(ctx, (progress) => emit({ type: 'component', id: c.id, status: 'running', ...progress }));
    } catch (error) {
      if (ctx.signal?.aborted) throw error;
      emit({ type: 'component', id: c.id, status: 'error', error: error.message });
      error.componentId = c.id;
      throw error;
    }
    state.components[c.id] = { version: c.version, at: new Date().toISOString() };
    await saveState(ctx.L.state, state);
    emit({ type: 'component', id: c.id, status: 'done' });
  }
  return { skipped: [...skip] };
}

/**
 * True when nothing is left to install. Components skipped by the test switch count as missing,
 * unless `ignoreSkipped` is set (used to decide whether the app can start).
 */
async function isSetupComplete(ctx, { ignoreSkipped = false } = {}) {
  const { all, done } = await pendingComponents(ctx);
  const skipped = new Set(ignoreSkipped ? ctx.skip || [] : []);
  return all.every((c) => done.has(c.id) || skipped.has(c.id));
}

module.exports = { describePlan, runSetup, isSetupComplete };
