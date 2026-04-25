# Demo Deck — Export & Delivery Notes

> `deck-source.md` is a [**Slidev**](https://sli.dev/) Markdown deck. Use
> the commands below to preview, export, and ship the hackathon deliverable.
> We **do not** commit `deck.pdf` into the repo — generating it needs a
> local headless Chromium, and we keep the source-of-truth editable.

## Prerequisites

| Tool | Version | Install |
|---|---|---|
| Node.js | ≥ 20 | [nodejs.org](https://nodejs.org/) |
| Chromium (for PDF export) | ≥ 120 | macOS: `brew install --cask chromium`; Linux: `apt install chromium` |

Slidev is invoked via `npx`, no global install needed.

## 1. Live preview (hot-reload while editing)

```bash
cd docs/demo
npx slidev deck-source.md
```

- Opens at [http://localhost:3030](http://localhost:3030).
- Any save to `deck-source.md` reloads.
- Press `?` for the Slidev keymap (arrow keys, `o` for overview,
  `d` for dark-mode toggle, `p` for presenter notes).

## 2. Export to PDF (hackathon submission)

```bash
cd docs/demo
npx slidev export deck-source.md \
  --output ../../outputs/demo/SolGuard-Deck.pdf \
  --format pdf
```

- Output lands at `SolGuard/outputs/demo/SolGuard-Deck.pdf`
  (git-ignored).
- On macOS the first run may prompt you to grant Terminal "Screen
  Recording" and "Accessibility" permission (needed by Playwright /
  headless Chromium).
- To shrink the PDF further (e.g. for a 5 MB Colosseum cap):

```bash
gs -sDEVICE=pdfwrite -dCompatibilityLevel=1.5 \
   -dPDFSETTINGS=/ebook -dNOPAUSE -dBATCH -dQUIET \
   -sOutputFile=SolGuard-Deck.min.pdf SolGuard-Deck.pdf
```

## 3. Export to PNG (for README / thumbnails)

```bash
cd docs/demo
npx slidev export deck-source.md \
  --output ../../outputs/demo/slides \
  --format png --dark
```

One PNG per slide at `outputs/demo/slides/001.png`, `002.png`, …

## 4. Export speaker notes

Slidev extracts HTML comments (`<!-- ... -->`) as presenter notes.
Preview with `--with-clicks` (shows them below the canvas) or export:

```bash
cd docs/demo
npx slidev export deck-source.md \
  --output ../../outputs/demo/SolGuard-Deck-with-notes.pdf \
  --format pdf --with-clicks
```

## 5. Build a static web deck (for the repo README)

```bash
cd docs/demo
npx slidev build deck-source.md --base /deck/ --out ../../public/deck
```

Deploy `public/deck/` anywhere — it's a self-contained static bundle.
Useful for hosting the clickable deck alongside the demo video.

## 6. Deliverables checklist

For the hackathon submission zip:

- [ ] `SolGuard-Deck.pdf` (≤ 10 MB)
- [ ] `SolGuard-Deck.min.pdf` (≤ 5 MB backup)
- [ ] `SolGuard-Demo.mp4` (from `docs/demo/script.md`)
- [ ] Cover slide exported as `SolGuard-Cover.png`

## 7. Troubleshooting

- **"Failed to launch browser"** → `export PUPPETEER_EXECUTABLE_PATH=$(which chromium)`
  and retry.
- **Chinese glyphs rendered as tofu** → add `fonts:` block to
  `deck-source.md` frontmatter (already set to Inter / JetBrains Mono;
  for Simplified Chinese, add `sans: "Noto Sans SC"` + `npm i -D
  @fontsource/noto-sans-sc`).
- **Mermaid diagrams not rendering in PDF** → bump Slidev to latest
  (`npx slidev@latest`); older versions had a mermaid-in-PDF bug.
- **Export takes > 5 min** → Slidev 0.48 shipped a regression. Pin to
  `npx slidev@0.49.27` via `SLIDEV_VERSION=0.49.27 npx slidev …`.

## 8. Keeping the deck in sync with `script.md`

The 5-minute demo script (`docs/demo/script.md`) is the **narrative
source of truth**. If you re-time a shot, update the corresponding slide
in `deck-source.md` so the presenter can flip through in lock-step.
