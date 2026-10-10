import * as ort from "onnxruntime-web/webgpu";
import {decodeWithStepFn} from "./greedy.mjs";

const $ = (query) => document.querySelector(query);
const status = $("#status");
const log = $("#log");
const button = $("#run");
const downloadButton = $("#download");
let finalReport = null;

function write(message) {
  log.textContent += message + "\n";
  log.scrollTop = log.scrollHeight;
}
function setStatus(value) {
  status.textContent = value;
}

async function getJSON(path) {
  const response = await fetch(path, {cache: "no-store"});
  if (!response.ok) throw new Error("Cannot fetch " + path + ": " + response.status);
  return await response.json();
}

async function downloadChecked(path, expectedSha) {
  const response = await fetch(path, {cache: "no-store"});
  if (!response.ok) throw new Error("Cannot fetch ONNX: " + path + " (" + response.status + ")");
  const buffer = await response.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", buffer);
  const actualSha = Array.from(new Uint8Array(digest), (x) => x.toString(16).padStart(2, "0")).join("");
  if (actualSha !== expectedSha) {
    throw new Error("STOP: ONNX SHA-256 mismatch at " + path);
  }
  return new Uint8Array(buffer);
}

function requireFixtureContract(fixtures, metadata) {
  if (fixtures.kind !== "FROZEN_NONBLIND_PYTORCH_TO_BROWSER_WEBGPU" ||
      fixtures.blind_test_used !== false ||
      fixtures.source_full_parity !== "PASS" ||
      metadata.status !== "EXPORTED_NOT_YET_PARITY_VERIFIED" ||
      fixtures.source_checkpoint_sha256 !== metadata.checkpoint_sha256 ||
      fixtures.encoder_sha256 !== metadata.encoder_sha256 ||
      fixtures.decoder_sha256 !== metadata.decoder_sha256 ||
      fixtures.sample_count !== fixtures.samples.length ||
      fixtures.total_nonblind_crops !== 752 ||
      metadata.image_max_width !== 1024 || metadata.decoder_max_seq_length !== 128) {
    throw new Error("STOP: frozen model or non-blind fixture manifest contract invalid");
  }
  const seen = new Set();
  for (const f of fixtures.samples) {
    if (seen.has(f.id) || !["real_val", "synthetic_val", "bakeoff_regression"].includes(f.split) ||
        !/^\/fixtures\/line_[0-9]{4}\.f32$/.test(f.image_file) ||
        f.image_shape[0] !== 1 || f.image_shape[1] !== 3 || f.image_shape[2] !== 32 ||
        f.image_shape[3] < 32 || f.image_shape[3] > 1024 ||
        typeof f.reference_text !== "string") {
      throw new Error("STOP: invalid or duplicate non-blind fixture");
    }
    seen.add(f.id);
  }
}

async function runOne(sample, encoder, decoder, metadata) {
  const response = await fetch(sample.image_file, {cache: "no-store"});
  if (!response.ok) throw new Error("Missing tensor: " + sample.image_file);
  const buffer = await response.arrayBuffer();
  const expectedBytes = sample.image_shape.reduce((a, b) => a * b, 1) * 4;
  if (buffer.byteLength !== expectedBytes) {
    throw new Error("Tensor byte-length mismatch: " + sample.id);
  }
  const pixels = new Float32Array(buffer);
  const input = new ort.Tensor("float32", pixels, sample.image_shape);
  const memory = (await encoder.run({image: input})).memory;
  if (!memory) throw new Error("Encoder did not produce memory");
  try {
    const translated = await decodeWithStepFn(async (tokenPrefix) => {
      const prefix = new BigInt64Array(tokenPrefix.map((t) => BigInt(t)));
      const tokens = new ort.Tensor("int64", prefix, [prefix.length, 1]);
      let logits;
      try {
        logits = (await decoder.run({tokens, memory})).logits;
        if (!logits) throw new Error("Decoder did not produce logits");
        const values = await logits.getData();
        if (values.length !== metadata.vocab_size) {
          throw new Error("Unexpected decoder vocabulary size " + values.length);
        }
        return values;
      } finally {
        if (logits) logits.dispose();
        tokens.dispose();
      }
    }, metadata.vocab, metadata.decoder_max_seq_length);
    return translated;
  } finally {
    memory.dispose();
    input.dispose();
  }
}

async function run() {
  finalReport = null;
  downloadButton.disabled = true;
  button.disabled = true;
  log.textContent = "";
  setStatus("Checking WebGPU…");
  let encoder;
  let decoder;
  let results = [];
  try {
    if (!window.isSecureContext || !navigator.gpu) {
      throw new Error("WebGPU unavailable. Use recent Chrome/Edge on localhost or HTTPS.");
    }
    const adapter = await navigator.gpu.requestAdapter();
    if (!adapter) throw new Error("No WebGPU adapter; inspect chrome://gpu and drivers.");
    write("WebGPU adapter found. This does NOT prove every ONNX operator will execute on GPU.");
    const [fixtures, metadata] = await Promise.all([
      getJSON("/fixtures/manifest.json"), getJSON("/artifacts/metadata.json")
    ]);
    requireFixtureContract(fixtures, metadata);
    write("Frozen checkpoint: " + metadata.checkpoint_sha256);
    write("Non-blind fixtures: " + fixtures.sample_count + " / 752");
    setStatus("Verifying model hashes…");
    // Hash and load exact graphs, not URLs that could silently change between
    // metadata fetching and session initialization.
    const [encBytes, decBytes] = await Promise.all([
      downloadChecked("/artifacts/encoder.onnx", metadata.encoder_sha256),
      downloadChecked("/artifacts/decoder_step.onnx", metadata.decoder_sha256)
    ]);
    ort.env.wasm.wasmPaths = "/ort/";
    ort.env.wasm.numThreads = 1; // localhost smoke requires no cross-origin isolation
    const sessionOptions = {executionProviders: ["webgpu"], enableGraphCapture: false};
    setStatus("Loading WebGPU encoder…");
    encoder = await ort.InferenceSession.create(encBytes, sessionOptions);
    setStatus("Loading WebGPU decoder…");
    decoder = await ort.InferenceSession.create(decBytes, sessionOptions);
    write("Both ONNX Runtime Web sessions created with requested EP: webgpu");
    write("CPU/WASM kernel fallback within a session may still occur; inspect browser diagnostics.");
    const started = performance.now();
    let mismatches = 0;
    let limitHits = 0;
    for (const [i, sample] of fixtures.samples.entries()) {
      setStatus("Decoding line " + (i + 1) + " / " + fixtures.sample_count);
      const t0 = performance.now();
      const actual = await runOne(sample, encoder, decoder, metadata);
      const matched = actual.text === sample.reference_text;
      if (!matched) mismatches += 1;
      if (actual.hitDecoderLimit) limitHits += 1;
      results.push({
        id: sample.id,
        split: sample.split,
        match: matched,
        hit_decoder_limit: actual.hitDecoderLimit,
        elapsed_ms: Math.round(performance.now() - t0),
        ...(matched ? {} : {pytorch_reference: sample.reference_text, browser_output: actual.text})
      });
      write("[" + (i + 1) + "/" + fixtures.sample_count + "] " +
        (matched ? "MATCH" : "MISMATCH") + " " + sample.id +
        " (" + results[results.length - 1].elapsed_ms + " ms)");
      if (!matched) write(" PyTorch: " + JSON.stringify(sample.reference_text) +
                          "\n Browser: " + JSON.stringify(actual.text));
    }
    const strictPassed = mismatches === 0 && limitHits === 0;
    const full = fixtures.sample_count === 752;
    const result = strictPassed ? (full ? "WEBGPU_FULL_PARITY_PASS" : "WEBGPU_SMOKE_DIAGNOSTIC_PASS") : "FAIL";
    finalReport = {
      result,
      browser_user_agent: navigator.userAgent,
      requested_execution_provider: "webgpu",
      all_operator_placement_verified: false,
      checkpoint_sha256: metadata.checkpoint_sha256,
      encoder_sha256: metadata.encoder_sha256,
      decoder_sha256: metadata.decoder_sha256,
      lines_processed: results.length,
      total_nonblind_lines: 752,
      text_mismatches: mismatches,
      decoder_limit_hits: limitHits,
      total_ms: Math.round(performance.now() - started),
      source_reference: "frozen non-blind PyTorch/CUDA predictions",
      blind_test_used: false,
      deployment_approved: false,
      rows: results
    };
    setStatus(result);
    write("RESULT: " + result + " | mismatches " + mismatches + " | limit hits " + limitHits);
    downloadButton.disabled = false;
  } catch (error) {
    setStatus("STOP / FAIL");
    write("ERROR: " + (error?.stack || String(error)));
    finalReport = {
      result: "FAIL", error: String(error),
      requested_execution_provider: "webgpu",
      browser_user_agent: navigator.userAgent,
      partial_results: results,
      blind_test_used: false, deployment_approved: false
    };
    downloadButton.disabled = false;
  } finally {
    if (decoder) await decoder.release();
    if (encoder) await encoder.release();
    button.disabled = false;
  }
}

button.addEventListener("click", run);
downloadButton.addEventListener("click", () => {
  if (!finalReport) return;
  const blob = new Blob([JSON.stringify(finalReport, null, 2) + "\n"], {type: "application/json"});
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "vietocr_webgpu_parity_report.json";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
