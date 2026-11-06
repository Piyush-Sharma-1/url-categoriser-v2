# We360 URL Categoriser

An offline Python tool that assigns a URL to one of We360's 29 categories and explains where the answer came from. We360 categorises the site being used rather than the page, so the tool mostly decides from the host name. It tries four sources in order, and the first answer wins: fixed rules for browser and private addresses, a hand-reviewed list of 143 major sites, the homepage listings of the [Curlie](https://curlie.org/) web directory, and a small text model. When the evidence is insufficient, it returns `Undefined` with the reason.

The full spec, taxonomy rules, category definitions, and detailed results are in [docs/DECISIONS.md](docs/DECISIONS.md).

An extension that adds a second dataset (UT1) is in the separate repository [url-categoriser-v2](https://github.com/Piyush-Sharma-1/url-categoriser-v2).

## Quickstart

This needs Python 3.12 or newer. The built lookup and model are in the repo, so you don't need to download the dataset.

Create the environment:

```bash
python -m venv .venv
```

Only needed on systems without `python3-venv`, such as some Debian or Ubuntu installs: install that package first and use `python3` here.

Activate it on Linux or macOS:

```bash
source .venv/bin/activate
```

Or on Windows:

```bash
.venv\Scripts\activate
```

Install the dependencies:

```bash
pip install -r requirements.txt
```

Classify a URL:

```bash
python -m src.cli https://zoom.us
```

```json
{
  "url": "https://zoom.us",
  "normalized": "zoom.us",
  "category": "Meeting",
  "confidence": 1.0,
  "method": "curated",
  "explanation": "The curated list files zoom.us under Meeting: Video meetings.",
  "evidence": [
    "Curated list: zoom.us"
  ],
  "alternatives": [],
  "undefined_reason": null
}
```

Run the tests:

```bash
python -m pytest -q
```

To rebuild from source, `python -m src.build` downloads the Curlie dump (about 177 MB) and regenerates the lookup and model. `python -m src.evaluate gold` reruns the gold evaluation. `python -m src.evaluate test` refuses to run again, because the test set runs once only.

## Results summary

No model, lookup, map, curated list, or threshold changed after these results were seen. Later code changes are listed under [Changes after the test run](#changes-after-the-test-run). Per-category scores and every group are in [docs/DECISIONS.md](docs/DECISIONS.md#detailed-results) and `reports/`.

### Whole pipeline: gold set

The headline group is 75 drafted URLs, none from the sites looked up while building the tool, though 13 are in the curated list. Strict accuracy accepts the label only, and lenient accuracy also accepts a second category where one was allowed.

| Score | Pipeline | Baseline (always `Undefined`) |
|---|---:|---:|
| Strict accuracy | 0.720 | 0.200 |
| Lenient accuracy | 0.733 | 0.200 |
| Coverage | 0.533 | 0.000 |
| Precision on answered URLs | 0.975 | 0.000 |

Of the 21 strict misses, 20 returned `Undefined`, and only 1 gave a wrong category. Without the curated list, strict accuracy falls to 0.627.

One limitation: the 15 rows labelled `Undefined` had earlier notes that suggested that answer, before the notes were cleaned. The pipeline answered all 15 correctly, so that part of the score may not be fully independent.

### Text model: test set

This measures the text model alone, on 37,563 hosts from domains it never saw in training.

| Score | No threshold | Threshold 0.60 | Baseline (always Lifestyle) |
|---|---:|---:|---:|
| Accuracy | 0.394 | 0.059 | 0.235 |
| Macro-F1 | 0.234 | 0.153 | 0.015 |
| Coverage | 1.000 | 0.072 | 1.000 |
| Precision on answered hosts | 0.394 | 0.819 | 0.235 |

With no threshold, the model beats the baseline. Accuracy at the threshold is below the baseline only because `Undefined` counts as wrong, and the baseline always answers.

### Coverage and precision

The threshold is an operating point, not a fixed property of the model. The project's rule chose 0.60, the lowest threshold that reaches 0.80 precision on validation. A business could choose differently: a lower threshold answers more sites and makes more mistakes, and a higher one does the reverse.

These are validation figures, because the test set was only measured at 0.60 and with no threshold.

| Threshold | Coverage | Precision |
|---:|---:|---:|
| 0.10 | 0.745 | 0.467 |
| 0.20 | 0.311 | 0.657 |
| 0.30 | 0.183 | 0.744 |
| 0.40 | 0.132 | 0.774 |
| 0.50 | 0.099 | 0.787 |
| **0.60** | **0.072** | **0.802** |
| 0.70 | 0.051 | 0.809 |
| 0.80 | 0.033 | 0.825 |
| 0.90 | 0.018 | 0.851 |

## Changes after the test run

These post-hoc code changes were made after the test run:

- Removed the unused code and tests for an empty `own` gold group.
- The build now writes the dropped-listing count to `reports/build_report.txt`.
- The model's `alternatives` no longer include its own answer, matching Curlie's.
- `vote()` compares the unrounded share against 0.60 and rounds only for display.

None of them changes a reported number. A rebuild reproduced the model and lookup byte for byte, and the regenerated gold report is identical. None of them needed the test set to run again.

## Key findings

- **Most misses are modern SaaS products missing from Curlie.** Curlie descends from DMOZ, so its coverage of newer products is thin. Of the 21 misses, 16 are missing from the Curlie branches the tool uses. Of those, 12 are SaaS products such as Hotjar, Aircall, Mattermost, and Obsidian, and none of the 12 appear anywhere in the dump.
- **The model rarely clears the threshold on brand names.** A brand name says little about what a site does. Of the 24 drafted URLs that reached the model, it answered one: `fastmail.com`, helped by the n-gram `mail`.
- **The gold set does not measure curated overrides.** It shows no case of the curated list overriding Curlie, but the known override cases, such as `canva.com` and `telegram.org`, were looked up while building the tool, so they were excluded from the drafted rows.

## What works

- Rules, normalisation, the curated list, the Curlie lookup, the text model, and the CLI.
- Offline classification, with no network calls and no need for the dump.
- The full build from source, including the dump download, and the evaluation code.
- A fresh clone without `.venv` or the dump installs from `requirements.txt`, runs the CLI, and passes all tests on Linux.

## What remains

- **Modern SaaS coverage:** a larger curated list or a newer dataset would address most misses.
- **AI assistant taxonomy gap:** no We360 category fits AI assistants, so `chatgpt.com`, `claude.ai`, `gemini.google.com`, `perplexity.ai`, and `copilot.microsoft.com` go to Research & Reference, with Developer and Office Apps as alternatives.
- **No CRM category:** `salesforce.com` and `force.com` go to Marketing, with Office Apps as the alternative.
- **Language limits:** sites listed only under Curlie's World or Regional branches are missing from the lookup, and the model can't reliably recognise non-Latin or transliterated host names. Major Indian and non-English sites rely on the curated list.
- **Leftover model tokens:** the model's `DROP_TOKENS` list still removes tokens from its earlier URL version, so `php.net` reaches the model as just `net`. Fixing this would change the model after the test run, so it stays as it is.
- **Windows:** the build and tests are written to run on Windows, but they have only been run on Linux.
- **Small samples:** each drafted gold row moves a score by about 1.3 points, and some test categories are small, such as File Sharing with 13 examples and Meeting with 16.

## Assumptions

- **Subject mapping:** Curlie groups sites by subject. We map a subject to a We360 category where one matches, and leave it unmapped where none does. About 37% of retained listings are unmapped, mainly religion, literature, law firms, and company sites grouped by industry, and these return `Undefined`.
- **Site, not page:** only homepage listings vote, and the model sees only the host. So `webmd.com` stays Lifestyle because its homepage is listed under `Health`, even though `Health/Conditions_and_Diseases` maps to Research & Reference.
- **Judgement calls:** map rows that needed a judgement say so in their note. For example, `Arts/Music` is mostly bands and instruments rather than streaming, but Music & Videos is the nearest fit.
- **Games includes gambling:** `Games/Gambling` maps to Gaming with the rest of the branch.
- **Knowledge Management:** internal wikis and notes are private, so Curlie can't list them, and the curated list carries most of this category.
- **Excluded branches:** World, Regional, and Kids_and_Teens are ignored. The evidence is in [docs/DECISIONS.md](docs/DECISIONS.md#why-world-regional-and-kids_and_teens-stay-excluded).
- **Model scores are not probabilities,** because the classes use balanced weights. A known failure mode is that an unfamiliar name can score high for a small category. The made-up `acmewidgetsxyz.com` leans to Social Media (0.349) because of the n-gram `widg`, though it falls below the threshold and returns `Undefined`. Nothing was tuned in response, because made-up examples are not evidence.

## Line count

| Group | Lines of Python |
|---|---:|
| Core code (`src/`) | 867 |
| Tests (`tests/`) | 662 |
| Analysis script (`scripts/inspect_dump.py`) | 138 |
| **Total** | **1,667** |

This is over the 1,000-line target because tests make up much of it, and the training and evaluation code was kept readable rather than compressed. CSV data and documentation don't count.

## Curlie attribution

Directory data comes from [Curlie](https://curlie.org/), licensed under [Creative Commons Attribution 3.0 Unported](https://creativecommons.org/licenses/by/3.0/). The licence file in the dump requires this attribution for uses without public-facing components, which this project follows:

> With content from Curlie.org - the largest human-edited directory of the web. Contribute by submitting a website or becoming an editor.

This project filters Curlie's listings and maps its categories to We360's. The results use the snapshot `curlie-rdf-all.tar.gz`, downloaded on 6 November 2026 from `https://curlie.org/directory-dl`, with SHA-256 `696098a50485445886e763c70f330a32e9214036316b0d66e67dbd54a71b0e04`. Its data files are dated 3 February 2026.

## Licence

The code is under the [MIT licence](LICENSE). The data files keep their own licences: Curlie data is CC BY 3.0, and the UT1 data in the separate v2 repository is CC BY-SA 4.0.
