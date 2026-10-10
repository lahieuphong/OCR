import test from "node:test";
import assert from "node:assert/strict";
import {decodeVietocrTokens, greedyArgmax, decodeWithStepFn} from "../src/greedy.mjs";

test("Unicode and pinned VietOCR special-token mapping", () => {
  assert.equal(decodeVietocrTokens([1, 4, 5, 2, 6], "ấđớ"), "ấđ");
  assert.equal(decodeVietocrTokens([1, 0, 3, 2], "ấđớ"), "<pad>*");
  assert.equal(decodeVietocrTokens([1, 4, 5], "ấđớ"), "ấđ");
  assert.throws(() => decodeVietocrTokens([1, 999], "ấđớ"));
});
test("argmax uses the lowest ID for ties and rejects NaN", () => {
  assert.equal(greedyArgmax(new Float32Array([0, 1, 1, -2])), 1);
  assert.throws(() => greedyArgmax([NaN, 1]));
});
test("greedy decode respects EOS and literal Unicode", async () => {
  const samples = [4, 5, 2];
  let i = 0;
  const answer = await decodeWithStepFn(
    async () => {
      const result = new Float32Array(7);
      result[samples[i++]] = 10;
      return result;
    },
    "ấđớ"
  );
  assert.equal(answer.text, "ấđ");
  assert.equal(answer.hitDecoderLimit, false);
  assert.deepEqual(answer.tokens, [1, 4, 5, 2]);
});
test("pinned max length 128 allows 129 iterations", async () => {
  let calls = 0;
  const r = await decodeWithStepFn(async () => {
    calls++;
    return new Float32Array([0, 0, 0, 0, 2]);
  }, "a", 128);
  assert.equal(calls, 129);
  assert.equal(r.text, "a".repeat(129));
  assert.equal(r.hitDecoderLimit, true);
});
