'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const {
  DEFAULT_PIN,
  PROBE_SHA_ERROR,
  RUNTIME_TOKEN_ERROR,
  launchDeployPages,
  run,
} = require('./index.cjs');

const PROBE = 'f08facac2e339bacd268b9b1b9c3ecc6caeb920a';
const WORKFLOW_SHA = 'af337fe8dacf1396728219f4cff775470620465a';

test('loads deploy-pages only after GITHUB_SHA is the probe-data commit', () => {
  const env = {
    INPUT_PAGES_BUILD_VERSION: `  ${PROBE}\n`,
    ACTIONS_RUNTIME_TOKEN: 'runtime-token',
    GITHUB_SHA: WORKFLOW_SHA,
  };
  let seen = '';
  launchDeployPages(env, (atLoad) => {
    seen = atLoad.GITHUB_SHA;
  });
  assert.equal(seen, PROBE);
  assert.equal(env.GITHUB_SHA, PROBE);
  assert.notEqual(env.GITHUB_SHA, WORKFLOW_SHA);
});

test('a process without ACTIONS_RUNTIME_TOKEN does not load deploy-pages', () => {
  const env = {
    INPUT_PAGES_BUILD_VERSION: PROBE,
    GITHUB_SHA: PROBE,
  };
  assert.throws(
    () =>
      launchDeployPages(env, () => {
        throw new Error('loaded');
      }),
    (error) => error.message === RUNTIME_TOKEN_ERROR,
  );
  assert.equal(env.GITHUB_SHA, PROBE);
});

test('refuses a value that is not a full probe-data sha before loading', () => {
  for (const sha of ['', 'af337fe8', 'not-a-sha', PROBE.slice(0, 39), `${PROBE}a`, PROBE.toUpperCase()]) {
    const env = {
      INPUT_PAGES_BUILD_VERSION: sha,
      ACTIONS_RUNTIME_TOKEN: 'runtime-token',
      GITHUB_SHA: WORKFLOW_SHA,
    };
    assert.throws(
      () =>
        launchDeployPages(env, () => {
          throw new Error('loaded');
        }),
      (error) => error.message === PROBE_SHA_ERROR,
    );
    assert.equal(env.GITHUB_SHA, WORKFLOW_SHA);
  }
});

test('the action entrypoint loads the bundle after the probe-data SHA is assigned', () => {
  const env = {
    INPUT_PAGES_BUILD_VERSION: PROBE,
    INPUT_DEPLOY_PAGES_PIN: DEFAULT_PIN,
    ACTIONS_RUNTIME_TOKEN: 'runtime-token',
    GITHUB_SHA: WORKFLOW_SHA,
  };
  const events = [];
  run(env, {
    materialize(pin) {
      events.push(['materialize', pin, env.GITHUB_SHA, env.ACTIONS_RUNTIME_TOKEN]);
      return '/tmp/deploy-pages-test/dist/index.js';
    },
    require(entry) {
      events.push(['require', entry, env.GITHUB_SHA, env.ACTIONS_RUNTIME_TOKEN]);
    },
  });
  assert.deepEqual(events, [
    ['materialize', DEFAULT_PIN, PROBE, 'runtime-token'],
    ['require', '/tmp/deploy-pages-test/dist/index.js', PROBE, 'runtime-token'],
  ]);
});

test('main does not start a second node process or load the bundle itself', () => {
  const source = fs.readFileSync(require.resolve('./index.cjs'), 'utf8');
  const mainSource = source.slice(source.indexOf('function main()'), source.indexOf('if (require.main'));
  assert.match(mainSource, /run\(process\.env,\s*\{\}\)/);
  assert.equal(mainSource.includes('require('), false);
  assert.equal(mainSource.includes('materializeDeployPages'), false);
  assert.equal(source.includes("execFileSync('node'"), false);
  assert.equal(source.includes('spawn('), false);
  assert.equal(DEFAULT_PIN, 'd6db90164ac5ed86f2b6aed7e0febac5b3c0c03e');
});
