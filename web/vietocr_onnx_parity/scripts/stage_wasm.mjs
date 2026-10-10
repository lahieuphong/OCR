import {readdir, copyFile, mkdir} from "node:fs/promises";
import {resolve} from "node:path";
const root = resolve("node_modules/onnxruntime-web/dist");
const dest = resolve("public/ort");
await mkdir(dest, {recursive: true});
let copied = 0;
for (const name of await readdir(root)) {
  if (!name.endsWith(".wasm")) continue;
  await copyFile(resolve(root, name), resolve(dest, name));
  copied++;
}
if (copied === 0) throw new Error("No ONNX Runtime Web WASM found under " + root);
console.log("Staged ONNX Runtime Web WASM files:", copied);
