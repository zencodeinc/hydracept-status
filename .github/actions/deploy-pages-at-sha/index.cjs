'use strict';

const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const DEFAULT_PIN = 'd6db90164ac5ed86f2b6aed7e0febac5b3c0c03e';
const PROBE_SHA_ERROR = 'refusing to deploy without a full probe-data sha';
const RUNTIME_TOKEN_ERROR =
  'ACTIONS_RUNTIME_TOKEN is unset. GitHub injects it only for a step that runs as an action.';

const SHA_RE = /^[0-9a-f]{40}$/;

function assertProbeDataSha(raw) {
  const sha = String(raw ?? '').trim();
  if (!SHA_RE.test(sha)) {
    throw new Error(PROBE_SHA_ERROR);
  }
  return sha;
}

function assertRuntimeToken(raw) {
  const token = String(raw ?? '').trim();
  if (!token) {
    throw new Error(RUNTIME_TOKEN_ERROR);
  }
  return token;
}

function assertPin(raw) {
  const pin = String(raw ?? '').trim();
  if (!SHA_RE.test(pin)) {
    throw new Error('refusing to load deploy-pages without a full commit pin');
  }
  return pin;
}

function materializeDeployPages(pin) {
  const checked = assertPin(pin);
  const temp = process.env.RUNNER_TEMP || os.tmpdir();
  const root = path.join(temp, `deploy-pages-${checked}`);
  const entry = path.join(root, 'dist', 'index.js');
  if (!fs.existsSync(entry)) {
    const archive = path.join(temp, `deploy-pages-${checked}.tar.gz`);
    execFileSync(
      'curl',
      ['-fsSL', '-o', archive, `https://codeload.github.com/actions/deploy-pages/tar.gz/${checked}`],
      { stdio: 'inherit' },
    );
    execFileSync('tar', ['-xzf', archive, '-C', temp], { stdio: 'inherit' });
  }
  if (!fs.existsSync(entry)) {
    throw new Error(`deploy-pages pin ${checked} extracted without dist/index.js`);
  }
  return entry;
}

// deploy-pages captures process.env.GITHUB_SHA when its module loads.
// Assign the probe-data SHA first, then load the bundle in this process so
// it keeps the ACTIONS_RUNTIME_TOKEN the runner injected for this action.
function launchDeployPages(env, load) {
  const sha = assertProbeDataSha(env.INPUT_PAGES_BUILD_VERSION);
  assertRuntimeToken(env.ACTIONS_RUNTIME_TOKEN);
  env.GITHUB_SHA = sha;
  load(env);
}

function loadPinnedDeployPages(env, deps) {
  const materialize = (deps && deps.materialize) || materializeDeployPages;
  const load = (deps && deps.require) || require;
  const pin = assertPin(env.INPUT_DEPLOY_PAGES_PIN || DEFAULT_PIN);
  const entry = materialize(pin);
  load(entry);
}

function run(env, deps) {
  launchDeployPages(env, (current) => {
    loadPinnedDeployPages(current, deps);
  });
}

function main() {
  try {
    run(process.env, {});
  } catch (error) {
    const message = error && error.message ? error.message : String(error);
    process.stderr.write(`${message}\n`);
    process.stdout.write(`::error::${message}\n`);
    process.exit(1);
  }
}

if (require.main === module) {
  main();
}

module.exports = {
  DEFAULT_PIN,
  PROBE_SHA_ERROR,
  RUNTIME_TOKEN_ERROR,
  assertPin,
  assertProbeDataSha,
  assertRuntimeToken,
  launchDeployPages,
  loadPinnedDeployPages,
  materializeDeployPages,
  run,
};
