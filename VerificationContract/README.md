# VerificationContract Schema

**Container:** `Contract.contractAttributes`
**Protocol Version:** 2.0
**Semantic Model:** generalised
**Use Cases:** Driver licence verification for employment onboarding, identity KYC, bank account verification for payroll, skill certificate verification for job matching, background checks
**Tag:** verification contract consent subject PII

## Overview

The VerificationContract schema captures the transaction-level metadata for a verification
request. It binds the subject (who is being verified), the purpose (why), the consent
reference (under what authorization), and the aggregate result (what was the outcome).

## Attachment Points

This schema extends `beckn:contractAttributes` on the core `Contract` object. The Contract
also uses core `participants` to list the REQUESTER, VERIFIER, and SUBJECT parties.

## Design Rationale

- **SubjectReference is minimal**: The subject reference carries only the name and typed
  identifiers needed by the verification provider. Full PII exchange happens during
  init/confirm under consent, not during discovery or select.

- **ConsentReference is external**: The schema references a consent artifact by ID and
  mechanism rather than embedding consent terms. This allows integration with external
  consent management systems (e.g., DigiLocker, Account Aggregator consent framework).

- **aggregateResult at Contract level**: When a contract covers multiple verification
  types (e.g., both identity and driving licence), the aggregate result summarizes the
  overall outcome. Individual verification results are in `performanceAttributes`.

- **purpose as CodedValue**: Verification purpose affects both regulatory compliance
  and provider processing. Making it machine-readable enables automated policy matching.

- **issuedCredentials separates evidence from deliverables**: `VerificationPerformance`
  carries `evidence` — the provider's internal proof chain (source API response hashes,
  audit logs, processing records). `issuedCredentials` on the contract carries the
  *deliverable*: the signed artifact the Requesting NP receives as portable proof.
  Keeping these distinct prevents conflating "how we verified it" with "what you can
  carry and reuse".

- **issuedCredentials is contract-scoped**: Credentials at this level attest to the
  aggregate outcome across all verification types in the contract (e.g., a single
  enterprise KYC bundle VC). Per-check credentials attesting to a single verification
  type belong in `VerificationPerformance`. Both levels are optional; implementations
  may use either, both, or neither depending on whether the network issues portable
  credentials.

- **url + embeddedCredential dual model**: W3C VCs can be referenced by URL (for
  externally hosted credentials where the provider manages persistence) or embedded
  inline (for cases where URL longevity cannot be guaranteed or the requester wants a
  self-contained payload). `embeddedCredential` takes precedence for cryptographic
  verification when both are present.

- **credentialExpiresAt is distinct from contract expiresAt**: The contract's validity
  window reflects when the verification result is considered stale for reliance purposes.
  The credential's own expiry is an issuer policy on the artifact itself. These may
  differ — a credential may outlive the contract's reliance period, or vice versa.

## Non-Goals

- Individual verification check results (→ `VerificationPerformance`)
- Per-check credentials attesting to a single verification type (→ `VerificationPerformance`)
- Pricing and payment (→ core `Consideration` / `Settlement`)
- Consent management UI or consent collection (external system)
- Credential storage or wallet management (external system)

## Upstream Candidates

- `ConsentReference` pattern — applicable to any PII-handling contract
- `SubjectReference` pattern — applicable to any person-centric service
- `aggregateResult` with status enum — applicable to any multi-check contract
- `IssuedCredential` pattern — applicable to any service that produces signed portable
  artifacts (skill certificates, health licences, background check reports)
