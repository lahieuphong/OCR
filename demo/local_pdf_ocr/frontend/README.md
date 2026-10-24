# VietDoc OCR desktop UI

React/JSX in the existing Vite project, with Tailwind CSS 4, shadcn/ui and Lucide.

```sh
npm ci
npm test
npm run build
```

The setup follows the [existing Vite project instructions](https://ui.shadcn.com/docs/installation/vite)
and [JavaScript configuration](https://ui.shadcn.com/docs/javascript). `components.json`
and `jsconfig.json` retain JSX and the `@/` alias. Components in `src/components/ui`
come from the official shadcn `new-york-v4` registry. Type annotations were removed,
the `cn` import was resolved locally, and Radix imports use only the individual
packages required by this UI. The upstream MIT license is included in
`public/licenses/shadcn-ui.txt` and copied into the production build.

The interface uses white/slate surfaces, blue actions, keyboard focus rings,
accessible Radix tabs and tooltips. Two columns use approximately 45%/55% of the
workspace; below 800 CSS pixels the panels stack and the document scrolls normally.
The processing actions stay visible at the bottom of short windows while the
document and options remain scrollable, including when Windows constrains the
requested window size to a smaller display.
Processing shows elapsed time and an **indeterminate** Progress component, with no
invented percentage. All fonts, icons, scripts and styles resolve locally at runtime.

## Typography

The stack is `-apple-system, BlinkMacSystemFont, "Segoe UI Variable", "Segoe UI", sans-serif`.
Windows uses its installed Segoe UI family. This does **not** install or bundle SF Pro.
The referenced Apple-fonts repository is not evidence of redistribution permission
for Windows. No SF Pro distribution rights are asserted, and no Apple font file is
downloaded, copied, committed or packaged. There are no runtime font/CDN requests.

## Verification

The existing Electron smoke entry point and checker remain in use; see
[`desktop/README.md`](../../../desktop/README.md). Use a directory outside Git for
evidence and synthetic documents only. No OCR model is needed for model-free smoke.
The smoke now also verifies:

- White result surfaces, the column ratio, a visible default run button, and no
  horizontal overflow at default, compact and stacked window sizes.
- Busy controls, an indeterminate progress bar and no numeric percentage while a
  real request is briefly paused by the smoke driver.
- Exact full-document and per-page text, real clipboard read-back, TXT/JSON exports,
  and absence of comparison until both independent method results exist.
- Status window actions, summaries and CSP; unexpected UI console errors or requests
  to external fonts, CDNs or models fail the smoke.

The intentional Internet security probes still produce their expected blocked CSP
messages; only that explicit phase is excluded from the UI console-error check.
Clipboard access in the smoke awaits Electron 44's asynchronous API.

The `/api/health` and `/api/ocr` contracts, mode values, result schemas, inference,
frozen-model checks, size/page limits and Electron security settings are unchanged.
Model-free smoke verifies that OCR is refused without models; it does not certify
recognition accuracy. The frontend and status window retain the internal-prototype
notice, and no installer or public release is created by this UI work.

The separate **Thông tin văn bản** tab now supports the 22-field administrative
metadata draft. See [METADATA.md](METADATA.md) for the exact string-valued schema,
verified catalogs, conservative extraction, manual review, export warnings,
synthetic examples and real-OCR regression limits. These drafts never replace
or modify the existing TXT/raw JSON exports.
