# ADR-0004: SERCOP OCDS 2021 dataset, licence and pseudonymisation

## Context

The project needs a real, redistributable, transactional dataset with enough
joins, dates and free-text values to demonstrate text-to-SQL, retrieval,
evaluation and prompt-injection safety. It must work offline from a bundled
artifact and must not expose personal data. Candidate sources were compared in
the plan's Data sources section: World Bank WDI (macro indicators, not
transactional), INEC (no stable direct CSV verified), Ecuador's CKAN portal
(mixed per-dataset licences) and OCHA/HDX (403 to automated fetch).

SERCOP's OCDS bulk data for 2021 is published through the Open Contracting
Partnership registry under CC BY 3.0 Ecuador. It contains 122,277 contracting
processes, 121,736 awards and 293,287 party records, and the publisher's policy
explicitly allows republication with a link to the source. It also contains
supplier names and RUCs, including 6,086 natural persons.

## Decision

Adopt SERCOP OCDS 2021 CSV as the only bundled warehouse. Consume six members
(`main`, `awards`, `awards_suppliers`, `contracts`, `parties`, `tender_items`)
and pin their SHA-256 hashes because the upstream tarball is regenerated.

Pseudonymise natural-person suppliers at ETL time, before any Parquet is
written: the third RUC digit 0–5 identifies a natural person; those suppliers
get a deterministic `PN-000001…` identifier (ordered by RUC) and the display
name `Persona natural PN-xxxxxx`. Province and canton remain available for
aggregate analysis. Non-natural suppliers keep their RUC. Rows are ordered by
key and the manifest records hashes, row counts and fingerprints.

The 96 legacy supplier identifiers that lack the `EC-RUC-` prefix cannot be
classified safely and are folded into one `other` supplier (`ID-UNKNOWN`) with
a neutral name. This keeps every award foreign key valid and preserves the
pinned 10,217 supplier rows without publishing unverifiable identifiers.

## Consequences

* The repository ships about 4.3 MB of Parquet and works fully offline.
* Real Spanish free-text values exercise the sanitiser and the bilingual
  semantic layer.
* Aggregate analytics on natural persons remain possible by `supplier_id`, but
  names are not recoverable from the bundle.
* 96 legacy suppliers are aggregated into one bucket, so per-supplier analytics
  on that tiny subset is coarser; the limitation is documented in `DATA.md`.
* Upstream regenerations can break the member pins; `--allow-checksum-drift`
  exists for a reviewed rebuild and the committed bundle stays the test source
  of truth.
* The licence requires visible attribution in the READMEs, web UI, `data info`
  and `DATA.md`.

## Alternatives considered

* **World Bank WDI** — CC BY 4.0 and stable, but the EAV macro shape gives almost
  no joins, entities or free text; rejected.
* **INEC** — pages mention CC BY 4.0, but no stable direct transactional CSV was
  verified; rejected as unverifiable.
* **datosabiertos.gob.ec CKAN** — licences vary per dataset (`cc-by`, `cc-nc`,
  empty); not uniformly redistributable; rejected.
* **Synthetic data only** — safe and trivial to license, but loses the realism
  that makes the retrieval, entity-resolution and injection stories credible.
* **Keep RUCs but redact names** — a RUC still identifies a natural person;
  rejected.
