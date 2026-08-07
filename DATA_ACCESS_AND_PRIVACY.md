# Data access and privacy

The underlying Florida emergency-department files are not redistributed. Access to those files, purchased references, and provider-source extracts remains subject to the original authorization, agreements, and institutional controls.

This public portfolio contains:

- sanitized source-code copies;
- aggregate, whitelisted QA evidence;
- methodology and status documentation; and
- a deterministic dataset made entirely from fictional facilities, fictional provider labels, and synthetic encounter records.

It does not contain raw or processed real encounter rows, the original exploratory sample, provider-master rows, patient identifiers, source extracts, Parquet files, databases, memory maps, model matrices, coefficient tables, partial results, correspondence, or credentials.

`SYS_RECID` and similar names appear only where production code documents source fields. No source values are included. The production visit key is an encounter-record key, not a longitudinal patient identifier. The research source does not support a defensible public patient-level linkage file.

Sanitized evidence is generated through an allowlist. Each evidence file records source filenames, SHA-256 hashes, and an extraction timestamp but omits local paths. The public validator blocks prohibited data extensions, large files, workstation paths, the source username, email addresses, common secret formats, row-level identifier artifacts, result-like files, and filesystem links into private locations.

Anyone adapting the production code must obtain data and reference files separately, confirm that their use is authorized, and supply private roots through environment variables or command-line arguments. The path-free template in `configs/full_production.template.yaml` is documentation, not an access mechanism.
