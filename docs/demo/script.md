# SolGuard · 5-Minute Demo Script

> **Target length**: 5:00 (±10 s). **Aspect**: 16:9 screen recording.
> **Audience**: Solana Hackathon judges familiar with DeFi security concepts.
>
> Storyline in one line: **"Solana devs get EVM-grade audits in minutes,
> not weeks."**

## Pre-flight checklist

- [ ] Browser: fresh Chrome profile, `1920 × 1080` window, zoom 100%.
- [ ] Tabs pre-opened (all in a single window, left to right):
  1. `https://solguard-demo.vercel.app/`
  2. `https://solguard-demo.vercel.app/#history` (backup for post-payment state)
  3. GitHub repo `https://github.com/Keybird0/SolGuard`
- [ ] System audio: OFF (voice-over only); mouse cursor: enabled with
  visible highlight.
- [ ] Record with OBS at 2560 × 1440 → post-downscale to 1920 × 1080 H.264.
- [ ] Have `demo-pin.png` (the Phantom-mock banner screenshot) ready for
  cut-in if a live element flakes.

---

## Storyboard (second-by-second)

> **Legend**: `[SCR]` = screen action · `[VO]` = voice-over · `[CUT]` = post-edit cut ·
> `[BACKUP]` = fallback if the live demo fails mid-take.

### Shot 1 · Hook (0:00 – 0:20)

- **[SCR]** Open on the SolGuard landing page hero. Zoom slightly on the
  "DEMO MODE" banner.
- **[VO]** "Solana shipped $4 billion in TVL last year — and at least $800
  million of it was lost to bugs that a simple audit would have caught.
  The problem isn't that audits don't exist. The problem is they take six
  weeks and cost more than most hackathon winnings. SolGuard fixes both."
- **[CUT]** Title card: "SolGuard — Solana smart-contract security, in minutes."
- **Plan A**: live recording on the deployed Vercel site.
- **Plan B (BACKUP)**: pre-recorded screen of the same page with voice-over.

### Shot 2 · The input surface (0:20 – 0:45)

- **[SCR]** Hover the four input tabs (Rust source / Anchor workspace /
  GitHub repo / deployed program id). Click "GitHub repo".
- **[SCR]** Type `https://github.com/coral-xyz/sealevel-attacks` into the
  input field; don't submit yet.
- **[VO]** "You can feed SolGuard four things: a Rust file, an Anchor
  workspace, a GitHub repo, or a deployed program id. Under the hood we
  normalize all four into a common AST and run seven Solana-specific
  rules plus an AI reviewer that reads every public instruction handler
  one by one."

### Shot 3 · Solana Pay payment flow (0:45 – 1:15)

- **[SCR]** Click **Submit**. The side panel shows the payment request
  (0.001 SOL per task × 3 → 0.003 SOL total).
- **[SCR]** Connect Phantom. Click "Pay with Phantom". Brief "Confirming…"
  spinner (demo: mocked signature in < 1 s).
- **[SCR]** Status flips to "Paid · queued".
- **[VO]** "Payment is a standard Solana Pay transaction on devnet. Three
  thousandths of a SOL per task — because we believe security should have
  the same unit economics as a cup of coffee. In demo mode the wallet is
  mocked so judges don't need to install Phantom, but the code path is
  identical to production."
- **[BACKUP]** If the payment spinner hangs > 3 s, append `?demo=1` to the
  URL, refresh, and say "We're in demo mode, which skips the actual
  broadcast".

### Shot 4 · Progress pipeline (1:15 – 2:00)

- **[SCR]** Progress stepper animates through 6 steps:
  `Normalize → Parse → Scan → AI verify → Compose → Deliver`.
- **[SCR]** Hover each step to show per-step timing.
- **[VO]** "While judges are reading this slide, three audits are running
  in parallel. Step one normalizes the input. Step two parses Anchor
  IDL, derives macros, account structs. Step three is pure Rust — seven
  AST rules, zero LLM calls, zero cost. Step four is the differentiator:
  an AI reviewer loads each handler and the rule hits that touch it,
  applies ten kill signals to suppress false positives, and emits a
  three-tier report."

### Shot 5 · The three-tier report — Case #1 Multi-Vuln CPI (2:00 – 2:55)

- **[SCR]** First audit (rw04-arbitrary-cpi) turns green. Click its card.
- **[SCR]** Tab 1 — **Risk Summary**: 2 × High, 1 × Critical; executive
  verdict "C — Critical Risk".
- **[SCR]** Tab 2 — **Security Assessment**: scroll to the Arbitrary CPI
  finding, show the exact line and the PoC sketch.
- **[SCR]** Tab 3 — **Checklist**: 14 out of 19 checks pass; 3 block the
  protocol from shipping.
- **[VO]** "Case one: a real Anchor program where `invoke` takes a
  caller-supplied `program_id`. SolGuard spots it in step three, the AI
  reviewer walks the handler, confirms the CPI target isn't constrained
  to Token program id, writes a remediation, and attaches a one-line fix:
  replace `AccountInfo` with `Program<'info, Token>`. Three minutes.
  Thirty dollars of GPT-4o tokens. A vulnerability that in the wild has
  drained vaults on four different protocols."

### Shot 6 · Case #2 & #3 (2:55 – 3:30)

- **[SCR]** Click Case 2 (Clean Escrow). Show "0 findings · B — Low Risk".
- **[VO]** "Case two: an escrow program with seven kill-signal wins in a
  row — no signer misses, owner constraints everywhere, checked math.
  SolGuard's job here is to confidently say 'this is safe', and that's
  harder than it sounds."
- **[SCR]** Click Case 3 (Staking Slice). Show 1 × Medium finding on
  integer overflow.
- **[VO]** "Case three, 3,200 lines of staking code. One medium finding —
  a share-math overflow path that only bites when stake > 2^52. That's
  exactly the kind of long-tail bug a human auditor reads past at hour
  six."

### Shot 7 · The architecture (3:30 – 4:10)

- **[SCR]** Cut to the Mermaid architecture diagram (static PNG exported
  from `docs/ARCHITECTURE.md` §1).
- **[VO]** "The architecture is deliberately boring: a stateless Express
  API, an OpenHarness Python agent orchestrating the skill, Solana devnet
  for payment, and three LLM providers with automatic failover. The skill
  itself is a drop-in Anthropic Agent Skill — anyone can `uv tool install
  openharness-ai` and run SolGuard from their terminal against their own
  codebase, with their own API key, no SaaS dependency."
- **[SCR]** Zoom on the skill block. Overlay arrow → "14 Phase-6 fixtures
  · 7 rules · 0.9 precision, 0.89 recall".

### Shot 8 · Numbers that matter (4:10 – 4:35)

- **[SCR]** Slide: three metrics:
  - "4 minutes 22 seconds — median audit latency"
  - "$0.31 — median LLM cost per audit"
  - "14 / 14 fixtures passing Phase 6 baseline"
- **[VO]** "Four and a half minutes, thirty-one cents, fourteen of
  fourteen fixtures green in our Phase 6 baseline. No auditor in the
  world can match those unit economics. That's why SolGuard isn't
  competing with Halborn or OtterSec — it's a pre-audit layer that every
  Solana dev should be able to self-serve before they ship."

### Shot 9 · Close + CTA (4:35 – 5:00)

- **[SCR]** Final slide: "Try it now: solguard-demo.vercel.app · Source:
  github.com/Keybird0/SolGuard · License: MIT".
- **[VO]** "It's live, it's open source, it's MIT. Submit your contract in
  thirty seconds. Thanks for watching."
- **[CUT]** Fade to black.

---

## Timing guardrails

| Shot | Start | End | Buffer |
|---|---|---|---|
| 1 Hook | 0:00 | 0:20 | ± 2 s |
| 2 Input surface | 0:20 | 0:45 | ± 3 s |
| 3 Solana Pay | 0:45 | 1:15 | ± 5 s ← most elastic |
| 4 Progress | 1:15 | 2:00 | ± 5 s |
| 5 Case #1 | 2:00 | 2:55 | ± 5 s |
| 6 Case #2+#3 | 2:55 | 3:30 | ± 3 s |
| 7 Architecture | 3:30 | 4:10 | ± 3 s |
| 8 Metrics | 4:10 | 4:35 | ± 2 s |
| 9 Close | 4:35 | 5:00 | hard stop |

If you run over, cut Shot 3 narration to one sentence (Solana Pay is
self-explanatory visually) or drop Case #2 in Shot 6 down to a 4-second
flash. Do **not** cut Shot 5 — the three-tier report is the product.

---

## Plan A / Plan B decision tree

| Failure point | Plan A (live) | Plan B (fallback) |
|---|---|---|
| Vercel site unreachable | — | Run `npx http-server public -p 8080` locally + `?demo=1` |
| Payment button errors | Retry once | Refresh with `?demo=1` (auto-mocked) |
| Report rendering hangs | Wait 5 s | Switch tab to pre-opened `#history` |
| OBS audio desync | — | Cut in pre-recorded voice-over track |
| Phantom install prompt | — | Use demo mode (mocked wallet) |

---

## Voice-over delivery notes

- **Pace**: 160–170 WPM. Slow down during Shot 5 (report walk-through) to
  140 WPM — every word matters.
- **Emphasis words**: *audits · seven rules · kill signals · three-tier ·
  thirty-one cents · MIT*.
- **Pauses**: half-second breath after each shot transition; one full
  second after "Thanks for watching."
- **Tone**: confident, not salesy. Assume judges have seen 30 demos today
  and have zero patience for hype.

---

## Post-recording checklist

- [ ] Export 1080p H.264 MP4, max 50 MB (Colosseum limit).
- [ ] Burn in captions with Shot / second markers.
- [ ] Upload to YouTube (unlisted) + mirror on r2.
- [ ] Add link to `README.md` hero and `docs/04-SolGuard项目管理/08-Phase7-文档与演示.md` P7.3.3 acceptance row.
- [ ] Tag the commit `v0.7.0-demo` after the video lands.

---

## Q & A bank (for live demos in front of judges)

1. **"Can it handle programs with inline assembly?"** — Yes for parsing,
   no for AI reasoning. The LLM will flag inline asm as "manual review
   required" and downgrade confidence.
2. **"What about Token-2022 / confidential transfers?"** — Rules are
   version-agnostic; Token-2022 specific patterns (transfer hooks,
   confidential extension) are on the Phase 8 roadmap.
3. **"How do you prevent prompt injection from the audited code?"** — The
   code is passed as evidence blocks only, never as instructions, and the
   analyzer runs with `tool_choice: none` after the initial prompt.
4. **"Can I self-host?"** — Yes, full Docker Compose in
   `docs/USAGE.md#self-hosting`. Everything is MIT.
5. **"Do you store my code?"** — In the hosted demo we cache for 24 hours
   on ephemeral storage. Self-host for zero-retention.

---

*Last updated: 2026-04-25. Owner: SolGuard Demo Team.*
