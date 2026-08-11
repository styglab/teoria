# Extraction policy

## Inclusion

Extract conditions about a bidder's legal or factual eligibility when failure expressly prevents bid entry, invalidates the bid, rejects the bidder during qualification review, or prevents contract execution. The condition must attach to the bidder, representative, or required consortium member. Exclude scoring-only criteria, estimated-price and bid-rate formulas, lowest-price ordering, award-ranking mechanics, and contract-performance obligations.

Eligible attributes include business status, procurement registration, industry or license, region, company scale, bidder-held certificates or registered products, sanctions, past performance, credit rating, consortium composition, and other company qualifications. Personnel, facilities, equipment, insurance, manufacturing status, and supply capacity are included only when the notice clearly makes their pre-existing possession or status a condition of participation.

Use this decision test for every candidate:

1. Does the condition describe the bidder or a required consortium member, rather than the offered product, proposal, work result, vehicle, venue, subcontractor, or post-award operation?
2. Does the document identify when the condition is checked: bid entry, qualification review, or contracting?
3. Would failure cause one of the supported failure effects rather than only affect scoring or performance?

Emit a requirement only when all applicable answers are yes.

Exclude offered-product specifications and conformity, model or quantity requirements, proposal contents, scoring criteria, bid price, ordinary submission formatting, deliverables, deployment or staffing plans, vehicle allocation, venue or meal conditions, resources that may be secured after award, contract-performance obligations, and general schedules. A deadline may be referenced only when a bidder qualification must exist or remain valid on that date.

A submission checklist or request for a copy is evidence about paperwork, not automatically an eligibility rule. When the notice establishes an underlying bidder condition, emit the condition and attach the requested document under `proof_requirements`. If that connection is unclear, place the submission clause only in `unresolved_candidates`.

Do not turn a product requirement into a bidder requirement merely because the bidder must supply it. For example, matching a product's detailed item number or technical specification is excluded unless the notice separately requires the bidder itself to hold a procurement registration for that item number by the participation deadline.

When personnel, facility, equipment, insurance, manufacturing, or supply-capacity wording does not establish whether it is an eligibility gate or a performance condition, omit it from `requirements` and describe the clause and ambiguity in `unresolved_candidates`.

When an eligibility section expressly requires a general ability to perform, warranty, after-service, or experience without a measurable threshold, retain the gate only as manual and qualification-blocking. Do not expose it as a structured company comparison. Likewise, distinguish an existing debarment or conviction from a promise not to obstruct, collude, or otherwise misbehave in the current procurement; the latter is not a current sanction fact.

A clause triggered only when a bidder-specific event occurred is not an unconditional conjunct. If the extraction has no fact establishing the trigger, preserve the clause as qualification-blocking unresolved rather than requiring it of every bidder. Compound insolvency and restructuring lists remain manual until their individual states are represented atomically.

Do not lose a time-bound capability statement merely because it cannot be checked through a company API. When it is expressly located in the participation-qualification section, retain it as manual and qualification-blocking. A bare checklist of business registration, corporate registry, seal, or authorization documents remains non-blocking unless the same clause states that omission changes eligibility.

Qualification-review wording does not imply a bid-deadline condition. Use `qualification_review` and `qualification_rejection` when the document says the fact or proof is checked during qualification review. Use `contracting` only for a bidder condition expressly required before contract execution.

## Fidelity

- Retain both normalized values and `original_text`.
- Copy `original_text` verbatim from one Evidence excerpt. Never use it as a canonical summary; normalized meaning belongs in `value`.
- Anchor the shortest self-contained atomic clause in `proposition_text` with exact offsets inside `original_text`; retain negation, condition date, assessment stage, and failure wording needed to interpret that atom.
- Represent conjunction, alternatives, exceptions, and participation scope with `logic.placements`; do not emit an expression tree or flatten logic into an unordered list.
- Split joined clauses into independently assessable facts. In particular, joint bidding or joint contracting and subcontracting are separate facts and must not be stored as one requirement merely because the source joins them with `및`, `또는`, or punctuation.
- Distinguish a natural-person company representative (`representative`) from the lead company of a consortium (`consortium_representative`).
- If the notice permits both a single bidder and a consortium, emit separate atomic participation-mode facts in `single` and `consortium` scopes. Consortium representative, member count, ownership share, and member-specific qualifications belong only to the consortium scope.
- Use `custom` whenever normalization would lose meaning.
- Set `needs_review` when a clause depends on another unavailable document, ambiguous law, calculation, or human interpretation.
- Mark an unresolved candidate as qualification-blocking only when resolving it can change bidder eligibility. Informational, price-only, scoring-only, and performance-only candidates do not roll up to extraction review.
- Multiple documents may support one requirement. Keep every material citation.
- Do not treat missing company data as a result; this workflow has no company input.

## Semantic normalization

Treat normalization as part of extraction, not as a later keyword cleanup. After drafting all requirements, compare them across every document and structured API record by the bidder fact they test. Merge semantically equivalent propositions, retain all material Evidence, choose one canonical known type, and then rebuild the condition tree with canonical IDs.

`custom` is a last resort. It must never duplicate a proposition represented by a known type. Different wording, document source, or a structured API row does not make a separate requirement when the company would prove all of them with the same fact.

Preserve genuinely distinct alternatives as separate atomic requirements with a shared `alternative_group` and distinct `alternative_branch`. Facts in one branch are conjunctive. Do not merge alternatives merely because they share one source sentence.

Electronic-procurement access facts belong to `procurement_registration`: 나라장터 user or bidder registration, electronic certificate registration, personal authentication, and fingerprint identity verification. Use `certificate` for bidder-held confirmations or certifications outside that electronic-procurement registration process.

A 직접생산확인증명서 is a bidder-held `certificate`, including when it is limited to a detailed product code. `product_registration` means the bidder has registered a manufactured or supplied product or detailed item in an electronic procurement system; it does not mean a product-specific certificate.

`original_text` and Evidence identify the source and may legitimately be shared by multiple atomic requirements split from one compound clause. Their `proposition_text` values identify the distinct atoms. Deduplicate by the normalized bidder fact together with operator and holder scope, never by source text alone.

## Source priority

Structured API license and region rows are authoritative structured candidates. Documents can add detail or reveal conflict. Preserve conflicts with `review_status: needs_review`; never silently choose one source.

## Input efficiency

The caller supplies bounded candidate blocks, not an invitation to inspect the full artifact again.
Extract all eligibility facts present in those blocks. Do not use tools to retrieve omitted content.
Structured restrictions are already normalized inputs and must not be rediscovered from prose.
