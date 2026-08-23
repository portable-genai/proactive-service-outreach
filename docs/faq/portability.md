# FAQ: portability and exit

## How do we leave?

Every boundary is a `typing.Protocol` with three adapter families, selected by one environment
variable. `make portability` runs the executable claim: eight ports across three profiles, all
bound and conforming, the offline family answering, the exit family refusing loudly, the audit
trail exported to JSON Lines and reloaded elsewhere with its hash chain intact, and no cloud SDK
imported anywhere in the run. It prints a pass or fail per named check.

## Why do the on-premises adapters raise instead of doing something?

Because a placeholder that returned successfully would make the portability claim silently
false. Three of them would be actively harmful: a review router that returned would convert
every consequential result into an unreviewed one, a delivery adapter that returned a receipt
would count a contact that never happened against a customer's frequency cap and tell the
consent store about it, and a consent adapter that returned anything would be inventing a legal
position about a person. `docs/onprem-migration.md` lists what each one needs.

## What is NOT claimed?

That an on-premises deployment exists. That the model is portable. That the infrastructure is.
The claim is bounded to the seams and the record, and the demo says so on screen rather than
leaving an auditor to discover it.

## Is the audit trail ours?

Yes. It exports to JSON Lines with the hashes included, so a consumer can re-verify the chain
without this codebase. The chain catches an edit, a deletion or a reorder; the external head
anchor, on a different volume under different credentials, is what catches a truncated tail,
because a truncated chain still verifies perfectly on its own.

## What about the consent and speech commons?

`consent-preference-kit` and `speech-lexicon-kit` are pinned by tag and by commit, are pure
standard library with zero runtime dependencies, and are read-only dependencies of this repo.
Both are public in `portable-genai` since 2026-08-22, so a build environment needs no credential
at all; this answer used to describe provisioning one. Vendoring a copy is still the wrong fix
for a consent client, for the reason `docs/runbook.md` gives.
