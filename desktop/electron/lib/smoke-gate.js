'use strict';
// The smoke test (--smoke-test=<dir> [--smoke-pdf=<file>] [--smoke-timeout=<s>]) drives the real UI through
// the Chromium debugger and writes screenshots, exports and a report into the folder it is given. It is a
// development and CI tool. A packaged build allows it only when its package.json carries
// "vietdocSmokeTest": true, which only the internal test configuration (electron-builder.smoke.yml) sets;
// a release build refuses to start with --smoke-* options instead of silently ignoring them.

function smokeArgs(argv) {
  return Object.fromEntries(argv.filter((a) => a.startsWith('--smoke-'))
    .map((a) => { const [k, ...v] = a.slice(2).split('='); return [k, v.join('=')]; }));
}

function smokeAllowed({ packaged, packageJson }) {
  return !packaged || Boolean(packageJson && packageJson.vietdocSmokeTest === true);
}

module.exports = { smokeArgs, smokeAllowed };
