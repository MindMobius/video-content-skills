# Traceability Boundaries

## Four different claims of confidence

Keep these separate:

1. **Pixel or audio recognition:** OCR/ASR produced a string.
2. **Publisher evidence:** the video displayed or spoke that meaning.
3. **Agent synthesis:** several source passages jointly imply an interpretation.
4. **External verification:** an independent authoritative source supports or
   contradicts a factual assertion.

Agreement between OCR scales supports level 1. Agreement between OCR and ASR
may strengthen level 2. Neither automatically reaches level 4.

## Evidence references

An evidence reference identifies one immutable subtitle artifact and one time
range. Its `text` is a source excerpt, not a cleaned-up quotation. Put translated
or normalized meaning in claim text and retain the original excerpt.

Use `relationship=conflicts` when evidence challenges a claim. Do not omit it
from the map merely because another source was selected as primary.

## Compression

Compression is faithful when omitted material does not change the remaining
claim's meaning, scope, attribution, confidence, or conditions. If it does, the
material is a required caveat or the carrier is too small.

## External sources

When external fact-checking is requested, keep URLs, titles, access dates, and
their conclusions separate from subtitle evidence. External research can change
`external_verification`; it must not rewrite what the video itself said.
