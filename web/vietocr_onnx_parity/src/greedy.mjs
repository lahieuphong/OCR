/** Frozen VietOCR Vocab decoding, with the pinned PyTorch translation semantics. */
export function decodeVietocrTokens(tokenIds, vocab) {
  const chars = Array.from(vocab);
  const first = tokenIds.includes(1) ? 1 : 0;
  const eos = tokenIds.indexOf(2);
  const last = eos < 0 ? tokenIds.length : eos;
  const special = ["<pad>", "<sos>", "<eos>", "*"];
  return tokenIds.slice(first, last).map((id) => {
    if (!Number.isInteger(id) || id < 0 || id >= chars.length + 4) {
      throw new Error("Out-of-vocabulary token ID: " + id);
    }
    return id < 4 ? special[id] : chars[id - 4];
  }).join("");
}

export function greedyArgmax(logits) {
  if (!logits || logits.length === 0) throw new Error("Empty decoder logits");
  let best = -Infinity;
  let index = -1;
  for (let i = 0; i < logits.length; i++) {
    const value = logits[i];
    if (!Number.isFinite(value)) throw new Error("Non-finite decoder logit at " + i);
    if (value > best) {
      best = value;
      index = i;
    }
  }
  return index;
}

export async function decodeWithStepFn(stepFn, alphabet, maxSeqLength = 128) {
  const tokens = [1];
  // Pinned translate() uses while (max_length <= max_seq_length), so at
  // maxSeqLength=128 it can generate 129 outputs, plus the initial SOS.
  for (let step = 0; step <= maxSeqLength; step++) {
    const nextId = greedyArgmax(await stepFn(tokens));
    tokens.push(nextId);
    if (nextId === 2) {
      return { text: decodeVietocrTokens(tokens, alphabet), hitDecoderLimit: false, tokens };
    }
  }
  return { text: decodeVietocrTokens(tokens, alphabet), hitDecoderLimit: true, tokens };
}
