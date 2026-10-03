# Third-party licences

| Asset | Source | Licence | File |
|---|---|---|---|
| Atkinson Hyperlegible Next (variable, wght 200-800) | google/fonts `ofl/atkinsonhyperlegiblenext` (Braille Institute, Applied Design Works) | SIL Open Font License 1.1 | `../fonts/OFL.txt` |
| Lucide icons (paths inlined as SVG in `compositions/*.html`) | lucide-static 1.51.0 | ISC | `LUCIDE-LICENSE.txt` |
| GSAP 3.14.2 | npm `gsap@3.14.2` | GSAP Standard "no charge" license | `GSAP-NOTICE.txt` |
| HyperFrames CLI 0.8.114 (dev dependency, not shipped) | npm `hyperframes` (HeyGen) | Apache-2.0 | `HYPERFRAMES-LICENSE.txt` |
| HyperFrames runtime 0.8.114 (`../vendor/hyperframe.runtime-0.8.114.iife.js`) | copied unmodified from `node_modules/hyperframes/dist/hyperframe.runtime.iife.js` (HeyGen, `@hyperframes/core`) | Apache-2.0 | `HYPERFRAMES-LICENSE.txt` (copied from https://github.com/heygen-com/hyperframes/blob/main/LICENSE; upstream ships no NOTICE file) |

The HyperFrames runtime bundle also contains postcss 8.5.28 (MIT), nanoid (MIT), picocolors 1.1.1 (ISC) and
@chenglou/pretext (MIT), minified without their licence banners. Their notices are in
`HYPERFRAMES-RUNTIME-BUNDLED.txt`. GSAP is not covered by the repository's MIT licence; see
`../../../THIRD_PARTY_NOTICES.md`.
