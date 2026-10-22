'use strict';
// Starts the desktop app with the project's Electron. Drops ELECTRON_RUN_AS_NODE (exported by the VS Code
// extension host and some tools), which would make electron.exe run as plain Node instead of the app.
const { spawn } = require('node:child_process');
const path = require('node:path');
const electron = require('electron');  // from Node, this is the path of electron.exe

const env = { ...process.env };
delete env.ELECTRON_RUN_AS_NODE;
const child = spawn(electron, [path.resolve(__dirname, '..'), ...process.argv.slice(2)], { stdio: 'inherit', env });
child.on('exit', (code, signal) => process.exit(code ?? (signal ? 1 : 0)));
for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, () => child.kill(sig));
