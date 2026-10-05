# Image and LLM security

## Safe image handling

The embedding service accepts JPEG, PNG and WebP images with a default 4 MB byte
limit and 20 million pixel limit. Invalid or blocked images use the existing
text-only fallback. Base64 size is checked before decoding. Local references,
including ordinary file paths, must resolve inside `IMAGE_ROOT`; reads are bounded.

Remote images require HTTPS on port 443 and an exact hostname in
`IMAGE_ALLOWED_HOSTS` (a JSON array in `.env`). The defaults cover Amazon image
CDNs. Every DNS answer must be a public IP. The connection uses a validated IP
directly while retaining the original hostname for Host, TLS SNI and certificate
verification, preventing a second DNS lookup from changing the destination.
Redirects, embedded credentials, HTTP and compressed HTTP responses are rejected.
Downloads stop at the byte limit and the embedding wrapper bounds the whole fetch
with `IMAGE_FETCH_TIMEOUT_S`. Environment proxies are disabled for this client.

Add your own trusted CDN explicitly. Network egress restrictions remain useful
defense in depth. Do not expose the internal embedding service directly.

This loader protects the embedding service only. The standalone
`ingestion/download_images.py` tool and UI image display use separate paths.
The current tests verify connection pinning with a mocked transport; a live
CDN/TLS deployment check is still pending. Configuration examples are in
[Running](RUNNING.md#configure-image-security).

## Untrusted LLM output

Queries are serialized as untrusted JSON data. Model output must be a bounded JSON
object with strict types, finite nonnegative budgets, valid ranges and no unknown
keys. Both fresh responses and cached intent outputs are validated; invalid outputs
fall back to deterministic parsing. Canonical vocabulary normalization still applies.

LLM output cannot overwrite explicit rule-derived categories or introduce hard
budget, size or gender constraints. Those constraints require rule-parser evidence.
This deliberately means number/size expressions the parser cannot recognize are
not converted into hard filters by the LLM. Multilingual parser expansion is a
separate task. LLM semantic slots can still influence ranking; schema validation
does not prove that an interpretation is correct or defeat every prompt injection.

Optional LLM explanations now select complete sentences from the approved template
without rewriting. Only ordered exact sentence selections are accepted. User needs,
titles and descriptions are not added to the explanation validator's evidence.
Invented claims, numbers and instructions cause the template to be retained.
This protects against model-added claims, but does not authenticate catalogue
metadata or guarantee that upstream enrichment is correct.

## Verification

Run `python -m pytest tests/test_image_security.py tests/test_llm_security.py`.
Tests use fake DNS and HTTP transports, with no external provider credentials.
They cover private and mixed DNS answers, URL restrictions, connection pinning,
redirects, bounded streams, local traversal, pixel/base64 limits, malformed model
outputs, hard constraint preservation and unsupported explanation rejection.
Live provider, CDN and deployment validation should accompany deployment.
See [Evaluation](EVALUATION.md#6-security-verification-after-commit-29901c6) for
test-run evidence and the distinction from historical performance measurements.
