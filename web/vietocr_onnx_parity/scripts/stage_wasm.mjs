import {readdir, copyFile, mkdir, stat} from "node:fs/promises";
import {resolve} from "node:path";

// WebGPU's native ONNX Runtime Web EP loads the .asyncify.mjs JS glue by
// dynamic import, then locates the matching .asyncify.wasm binary. Staging
// only .wasm leaves the dynamic import pointing at a Vite 404 HTML response.
//
// Always copy BOTH from the exact installed onnxruntime-web/dist version.
// Do not silently fall back to another ORT build or a CDN release.
const root = resolve("node_modules/onnxruntime-web/dist");
const dest = resolve("public/ort");
const moduleName = "ort-wasm-simd-threaded.asyncify.mjs";
const binaryName = "ort-wasm-simd-threaded.asyncify.wasm";
const files = await readdir(root);

for (const required of [moduleName, binaryName]) {
  if (!files.includes(required)) {
    throw new Error(
      "STOP: required ONNX Runtime WebGPU asset is absent in " +
      root + ": " + required +
      ". Check installed onnxruntime-web version; do not mix binaries."
    );
  }
}

await mkdir(dest, {recursive: true});
for (const file of [moduleName, binaryName]) {
  const source = resolve(root, file);
  const target = resolve(dest, file);
  await copyFile(source, target);
  const {size} = await stat(target);
  if (size === 0) throw new Error("STOP: zero-length WebGPU runtime asset: " + target);
  console.log("Staged: /ort/" + file + " (" + size + " bytes)");
}
console.log("ONNX Runtime WebGPU JS glue + WASM binary staged from same installed package.");
