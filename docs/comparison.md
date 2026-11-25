# Compared with the other councils

## A single prompt versus the tribunal

| | One prompt to one model | Strategy Tribunal |
|---|---|---|
| Who framed the decision | nobody | a framer, with user‑stated constraints kept verbatim and assumptions labelled |
| When the scoring rules were written | never | before any option exists, as gates and weighted criteria |
| Who argued the other side | nobody | reviewers with typed objections, then a challenger whose job is to make the leader lose |
| How options were compared | one impression | per criterion, one option at a time, aggregated by the controller, matched across rounds |
| What happens when evidence changes | nothing | affected options are rescored |
| What you can audit afterwards | the answer | every request, reply, rejection, score, promotion and stop reason |
| What tells you when to change your mind | nothing | reversal conditions and the objections still open |
| How you continue | start over | a follow‑up prompt that carries the decision and its caveats into the next step |

---

---


Six open‑source projects explore the same idea, a panel of model personas deliberating on a question. Each was read in full, prompts and orchestration code included, before this engine was designed; several of their ideas are in it and are credited below. The difference is where the authority sits. Five of the six are debate councils, and in all five the model that writes the verdict also decides when the debate is over, whether a reply counted, and how the options compare. (The sixth, LLM‑as‑a‑Verifier, is a scoring method applied to candidates you already have — no framing, no debate, no verdict.) Here those decisions are code.

| Project | Pattern | Where it stops | What Strategy Tribunal does at that point |
|---|---|---|---|
| [llm‑council](https://github.com/karpathy/llm-council) pattern as implemented by Geoffrey Byers for Claude Code | five advisors answer in parallel, blind to each other; a chairman synthesises | no peer review and no attack on the consensus; if all five share one bad assumption only the chairman can notice; the rebuttal round is sketched in prose and never wired; nothing is persisted | reviewers file typed objections against every candidate, a challenger must name the scenario in which the leader loses, owners answer, and every record is written to disk and resumable |
| [council‑review](https://github.com/ngmeyer/skills) (Neal Meyer) | five reasoning methods, anonymous peer review, devil's advocate, mediating assessments, dissent preservation | the orchestrating model shuffles the answers "in its head", so anonymity is a promise, not a mechanism; convergence and diversity are numbers the model estimates about itself; the tests grep the prompt file | pseudonyms are assigned by the controller and the alias map never reaches a model; stability is measured on comparable judgements; 130 tests execute the engine |
| [LLM‑Council‑Decide](https://github.com/danielrosehill/LLM-Council-Projects) (Daniel Rosehill) | fifteen formal frameworks, a selector picks five, cross‑review, a chairman dossier with kill criteria | a random model per call and the model is not recorded; the brief parser falls back to raw text in silence; cross‑review letters go out in panel order with the author's own analysis unmarked | per‑role routing with the actual provider and model recorded per participant; a parse failure is rejected and retried; review order is a seeded shuffle done by the controller |
| [NeuralHats](https://github.com/georgekobaidze/neuralhats) (Giorgi Kobaidze) | Six Thinking Hats, sequential, multi‑round, local Ollama, live web UI | a facilitator model decides CONTINUE or STOP and an unparseable answer defaults to CONTINUE; each hat sees the previous ones, so anchoring is built in | continuation is a controller decision from ranking stability, open blocking objections and budget; a malformed reply never advances a run; hats are observer‑only lenses collected before review |
| [council](https://github.com/dubs3c/council) (Michael Dubell) | personas propose, then REVISE / AGREE / CONCERN turns, a moderator consensus, an approval vote | proposals have no ids or versions, lists are replaced wholesale and state is replayed from the transcript; an approval that fails to parse counts as approval; a failed turn is written into the debate as a concern | immutable option versions with lineage (`parent_version_id`, `supersedes`); a reply that fails validation is rejected and retried; a failed request becomes an event, never a deliberation record |
| [LLM‑as‑a‑Verifier](https://github.com/llm-as-a-verifier/llm-as-a-verifier) | ranks candidates you already have by criterion‑level pairwise scoring over log‑probabilities, swapped order, pivot tournament | a judge, not a council: it does not frame, generate or challenge; missing results are silently scored 0.5; log‑probability scoring needs backends most people do not have | criterion‑first scoring and swapped‑order tiebreaks adopted; a missing judgement is explicit and makes the comparison non‑comparable, never imputed; the log‑probability method is an optional setting for providers that expose it |

### Why the controller matters

**The rules are written before the ranking.** A policy setter registers gates, three to six criteria, their anchors and weights before a single option exists, and nobody can amend them for the rest of the run. In the debate councils with a synthesizer, the chairman or moderator decides what mattered after reading the answers.

**Models propose, code commits.** Every reply is validated against a typed protocol: ids must exist, scores must cite evidence or a stated assumption, a challenge must name a legal target. What fails goes back with the error and the previous reply. In the reference projects a malformed answer is dropped, retried silently, or counted as a vote.

**Comparisons are matched.** Judgements are keyed by brief version, rubric version, evidence snapshot and judge configuration. A challenger is promoted only when its conservative lower bound clears the incumbent's upper bound. When new evidence lands, the affected options are rescored. None of the six compares across rounds on matched inputs — and only three of them iterate across rounds at all (council‑master's debate turns, NeuralHats' facilitator rounds, council‑review's convergence rounds); the rest run a fixed pass.

**The verdict can be overturned.** The challenger's case is a record with a losing scenario, a strongest alternative and the evidence that would separate them. If it could alter the action and stays unanswered, a firm recommendation becomes a conditional one and the report says so. The devil's advocate in council‑review is the closest relative; its output is advice to the chairman.

**Stopping is a measured condition.** Two comparable rounds within the materiality threshold, no blocking objection, budget intact. Not agreement counts, not a model's CONTINUE token, not a fixed number of turns.

**Everything is auditable.** Append‑only event log, every request and raw reply, the discussion transcript in order, who answered with which model, measured tokens where the provider reports them. The reference projects keep a transcript at best; none keeps scores, promotions and stops in an auditable record.

### What was taken from them, with thanks

The reasoning‑lens catalogue and the sycophancy guardrail (council‑review); the fifteen‑framework map, the kill criteria and the "option or gather X" verdict shape (LLM‑Council‑Decide); blind first‑pass generation, the "what did everyone miss" question and the single concrete next step (llm‑council); criterion‑level scoring and swapped‑order comparisons (LLM‑as‑a‑Verifier); the six hats as a bundle (NeuralHats); typed debate actions and per‑persona routing (council). Each is listed against its source, with the test that exercises it, in `docs/llm_council.md` §2.

### Where they are still better

llm‑council installs by copying markdown files and needs no code at all. NeuralHats streams the debate live into a browser and runs fully local on Ollama out of the box. LLM‑as‑a‑Verifier's log‑probability scoring is a sharper signal than integer scores when a backend exposes it. If one of those is the whole job, use that project.

---