// Keep unit cases wholly fictional. Real-document labels and OCR outputs belong
// only to the external acceptance evidence, never the repository fixtures.
import {STAMP_TEST_SUBJECT,stampSubjectDocument} from "./stampSubject.js";

export const DECREE_SUBJECT=STAMP_TEST_SUBJECT;
export function fastMetadataDocument(options={}) {
  return stampSubjectDocument(options);
}
