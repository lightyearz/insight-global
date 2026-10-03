# Third-party notices

The code and documentation written for this repository are released under the MIT licence (see
[`LICENSE`](LICENSE)). The material listed below belongs to third parties. It stays under its owners' terms,
and nothing in this repository's licence changes those terms.

## 1. Code and fonts shipped in this repository

These files are vendored **unmodified** so the deck and its video never load scripts or fonts from a CDN.
Their licence texts are in [`deck/assets/licenses/`](deck/assets/licenses/) and next to the font.

| Asset | Path | Owner | Licence | Licence text |
|---|---|---|---|---|
| GSAP 3.14.2 | `deck/assets/vendor/gsap-3.14.2.min.js` | GreenSock / Webflow, Inc. | GSAP Standard "no charge" licence | [`GSAP-NOTICE.txt`](deck/assets/licenses/GSAP-NOTICE.txt), <https://gsap.com/standard-license> |
| HyperFrames runtime 0.8.114 | `deck/assets/vendor/hyperframe.runtime-0.8.114.iife.js` | HeyGen | Apache-2.0 | [`HYPERFRAMES-LICENSE.txt`](deck/assets/licenses/HYPERFRAMES-LICENSE.txt) |
| postcss 8.5.28, nanoid (non-secure), picocolors 1.1.1, @chenglou/pretext (bundled inside the HyperFrames runtime) | same file | their authors | MIT / MIT / ISC / MIT | [`HYPERFRAMES-RUNTIME-BUNDLED.txt`](deck/assets/licenses/HYPERFRAMES-RUNTIME-BUNDLED.txt) |
| Lucide icon paths, inlined as SVG | `deck/compositions/*.html` | Lucide Contributors (some icons derived from Feather, Cole Bemis) | ISC (Feather-derived icons: MIT) | [`LUCIDE-LICENSE.txt`](deck/assets/licenses/LUCIDE-LICENSE.txt) |
| Atkinson Hyperlegible Next (variable font) | `deck/assets/fonts/AtkinsonHyperlegibleNext-Variable.ttf` | The Atkinson Hyperlegible Next Project Authors (Braille Institute) | SIL Open Font License 1.1 | [`OFL.txt`](deck/assets/fonts/OFL.txt) |

Notes:

- **GSAP.** GSAP is free to use under Webflow's Standard "no charge" licence, which allows it to be used,
  reproduced and displayed. The licence forbids removing or altering GSAP's proprietary notices, so the
  copyright banner at the top of the vendored file is kept. It also forbids using GSAP in no-code visual
  animation builders that compete with Webflow. This repository is not such a tool. If you reuse the deck in a
  product like that, GSAP's licence does not cover it. GSAP is **not** released under this repository's MIT
  licence.
- **HyperFrames.** Upstream ships no `NOTICE` file, so Apache-2.0 section 4(d) requires no further notice. The
  runtime is redistributed unmodified with a copy of the licence (section 4(a)).
- **Font.** The font is unmodified and is distributed with its licence. Under the OFL it must not be sold on its
  own.

## 2. Dependencies installed at build time (not shipped)

Python and npm dependencies are declared in `api/pyproject.toml` (locked in `api/uv.lock`), `web/package.json` and
`deck/package.json` (locked in their `package-lock.json` files). They are downloaded when you install, not
committed. The direct dependencies and their licences are:

- **API:** FastAPI, Pydantic, pydantic-settings, LangGraph, langgraph-checkpoint-sqlite, SQLAlchemy and aiosqlite
  (MIT); uvicorn, httpx and sse-starlette (BSD-3-Clause); google-genai and tenacity (Apache-2.0); defusedxml
  (PSF-2.0).
- **Web:** Next.js, React, Tailwind CSS and ESLint (MIT); lucide-react (ISC); TypeScript and Playwright
  (Apache-2.0).
- **Deck:** the HyperFrames CLI (Apache-2.0).

None of them is copyleft, so the repository can be released under MIT. A container image you build from the
Dockerfiles bundles these packages, and anyone who redistributes that image must include their licence notices.

## 3. Data sources and attribution

The app reads public U.S. National Library of Medicine (NLM) services at run time. The offline fixtures
(`fixtures/replay/`) and UI mocks (`web/src/mocks/`) contain records that were **retrieved on 3 October 2026**.
Neither NLM nor any other data provider endorses this project, and none of them has reviewed its output.

### PubMed (NCBI E-utilities)

- Source: PubMed, U.S. National Library of Medicine, via NCBI E-utilities. Requests identify the tool and follow
  NCBI's usage policy.
- **NCBI disclaimer and copyright notice:** <https://www.ncbi.nlm.nih.gov/home/about/policies/>. In NLM's words:
  *"NLM does not claim the copyright on the abstracts in PubMed; however, journal publishers or authors may."*
- **What this repository holds:** titles, authors, journal, PMID, DOI and dates, unchanged. For **excerpts**,
  each abstract is cut down to only the sentences quoted as evidence by the briefing, with gaps marked ` … `.
  The full text is at each record's PubMed link. See [`fixtures/README.md`](fixtures/README.md#excerpts-in-this-public-copy).
- **Licence status of every PubMed record in the fixtures and mocks.** It was checked on 3 October 2026 against
  Europe PMC (`isOpenAccess` and `license`). None of them is CC0 or CC BY, so all of them are truncated.

  | PMID | Journal | Licence found | Excerpt in this repo |
  |---|---|---|---|
  | 28135725, 34152826, 29507945, 36623286, 38639546, 38639549 | Annals of Internal Medicine (ACP) | none (publisher copyright) | quoted sentences only |
  | 33332584, 35000192, 39688187 | Cochrane Database of Systematic Reviews (Wiley) | none stated | quoted sentences only |
  | 32371789 | Journal of Hypertension | CC BY-NC-ND | quoted sentences only |
  | 40419299 | CMAJ | CC BY-NC-ND | quoted sentences only |
  | 40813129 | BMJ | CC BY-NC | quoted sentences only |
  | 39589443 | Herz (Springer Medizin) | none (publisher copyright) | quoted sentences only. Seven quotes cover almost every sentence of this short abstract (see `fixtures/README.md`) |
  | 35029593 | Medicine & Science in Sports & Exercise | none stated | quoted sentences only |
  | 37874122 | Deutsches Ärzteblatt International | none stated | quoted sentences only |
  | 41842862 | Endocrine Practice | none (publisher copyright) | quoted sentences only |

### MedlinePlus

- **Source: MedlinePlus, National Library of Medicine.** The health-topic summaries ("High Blood Pressure",
  "Type 2 Diabetes") are U.S. government works in the public domain and are kept in full. The connector strips
  their HTML markup and keeps only the text. Read the current versions at <https://medlineplus.gov>.
- MedlinePlus content licensed from other publishers, such as A.D.A.M. encyclopedia articles, drug monographs
  and images, is neither used nor stored.

### MeSH

- Courtesy of the U.S. National Library of Medicine. The fixtures store MeSH descriptor IDs and entry terms
  (D006973 Hypertension, D003924 Diabetes Mellitus, Type 2) as retrieved on 3 October 2026. They may not match
  the current MeSH version. NLM makes no warranty about the accuracy or completeness of the data.

### NLM Clinical Table Search Service (conditions autocomplete)

- The condition suggestions in `web/src/mocks/lookups.json` are labels with ICD-10-CM codes. They come from the
  Clinical Table Search Service's `conditions` list, which NLM derived from the Regenstrief Institute's Medical
  Gopher program and provides "as is". NLM's names may not be used to endorse or promote products derived from
  the service.

### ClinicalTrials.gov and openFDA (planned, not used yet)

The planned "emerging treatments" agent will use these services. The current code and fixtures contain no data
from either. When it is added:

- **ClinicalTrials.gov:** name ClinicalTrials.gov (NLM) as the source, show the date each record was retrieved
  or last processed, and say whether the data was changed (for example, summarised or filtered). Say also that
  *listing a study on ClinicalTrials.gov does not mean it has been evaluated by the U.S. Federal Government*.
  Terms: <https://clinicaltrials.gov/about-site/terms-conditions>.
- **openFDA:** the data is in the public domain under CC0 1.0, and FDA asks to be credited. openFDA data is not
  for clinical decisions, and FDA gives no warranty that it is error-free. Terms: <https://open.fda.gov/terms/>.

### Model output

The `llm/*.json` files in the fixtures were hand-authored from the excerpts. They are not Gemini output. In live
use, generated text comes from Google Gemini and is subject to Google's terms for the API you call.

## 4. Trademarks

Journal, publisher, product and organisation names (including GSAP, HyperFrames, Lucide, PubMed, MedlinePlus,
ClinicalTrials.gov, openFDA and Gemini) belong to their owners. Mentioning them does not imply endorsement.
