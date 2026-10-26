'use strict';
// Only the packaged test flavor gets a separate name/profile. Release and development keep their identity.
function appIdentity({ packaged = false, packageJson = {} } = {}) {
  const testBuild = packaged && packageJson && packageJson.vietdocTestBuild === true;
  return testBuild
    ? { name: 'VietDoc OCR Test', userDataName: 'VietDoc OCR Test' }
    : { name: 'VietDoc OCR', userDataName: null };
}
module.exports = { appIdentity };
