# Decisions

The project spec, the taxonomy rules, the category definitions, and the detailed results. The [README](../README.md) has the summary.

## Data decisions

This is the project spec as built.

### Build phases

- **Phase 1:** Inspect the dataset and draft the taxonomy map. No classification code.
- **Phase 2:** Normalisation, rules, curated list, Curlie lookup, and CLI (a usable partial submission).
- **Phase 3:** Text model and threshold.
- **Phase 4:** Evaluation and gold-set candidates.
- **Phase 5:** Final README and cleanup.

Tests are written during the phase they cover. Each phase ends with a report of what was built, how to run it, test results, and total line count, then waits for approval.

### A. Classification order

The first step that returns a result wins:

1. System scheme rule, on the raw input with spaces stripped and the scheme compared in lowercase
2. Normalise; if invalid, return Undefined (`invalid_url`)
3. In House host rule, on the normalised host
4. Curated list
5. Curlie lookup
6. Extra sources (UT1), whenever earlier steps give no category
7. Text model
8. Undefined

The curated list beats Curlie. When Curlie reaches a different category, it goes in `alternatives`.

### B. Rules

**System Processes:** the input starts with one of these schemes followed by `:` : `chrome`, `edge`, `about`, `file`, `chrome-extension`, `moz-extension`, `brave`, `opera`, `view-source`.

**In House Tools:** the normalised host is one of:

- `localhost` or `::1`
- a loopback or private IP (Python `ipaddress`: `is_loopback` or `is_private`)
- a name ending in `.local`, `.internal`, `.corp`, `.lan`, or `.intranet`
- a dotless host when the input has an explicit scheme or a port (`http://jira/`, `jira:8080`)

Both rules give confidence 1.0 and method `rule`.

### C. URL normalisation

One function is used by both the build and classification.

**Scheme detection:** an input has a scheme only if it starts with `scheme://`, or starts with a Section B scheme followed by `:`. Otherwise `http://` is prepended. A later `://`, as in `a.com/r?u=https://b.com`, does not count. This also avoids `urlparse("localhost:3000")` returning the scheme `localhost`.

Steps, in order:

1. Strip whitespace and apply scheme detection.
2. Parse. A parse failure, invalid port, or missing host is invalid.
3. Lowercase the host and convert internationalised hosts to punycode with `.encode("idna")`. A failure is invalid.
4. Remove one leading `www.` and one trailing dot from the host.
5. Remove default ports (`:80`, `:443`). Other ports stay in the normalised string but are ignored for matching.
6. Drop the query string and fragment.
7. Remove trailing slashes from the path.
8. Output host + path, such as `chess.com/play`, or `chess.com` for a root URL.

**Also invalid:**

- illegal host characters: anything except letters, digits, dots, hyphens, and underscores (IPs are exempt)
- a bare dotless word with no scheme or port, such as `banana` (`localhost` is exempt)
- `mailto:`-style input: no `://` and starting with `mailto`, `tel`, `sms`, `javascript`, or `data`
- bare `::1`, which is not valid URL syntax (`[::1]:3000` is valid)

**Registered domain:** `tldextract` with `suffix_list_urls=()`, `cache_dir=None`, and `include_psl_private_domains=True`, so it makes no network calls and each `*.blogspot.com` blog counts as its own site. IPs and platform roots such as `github.io` have no registered domain, so the host is used.

**Required tests,** written as one table-driven `pytest.mark.parametrize` test for normalisation and rules:

- `https://WWW.Chess.com/play/?x=1#top` gives `chess.com/play`
- `zoom.us` gives `zoom.us`
- `bbc.co.uk` has registered domain `bbc.co.uk`
- `localhost:3000` and `192.168.1.5:8080/admin` give In House Tools
- `chrome://settings` gives System Processes
- one test runs with network access blocked

### D. Data filtering

1. Ignore World, Kids_and_Teens, and Regional completely: neither votes nor training data. The dump's paths have no `Top/` prefix.
2. Adult is retained as `unmapped` votes, so listed sites return Undefined (`curlie_unmapped`).
3. Drop rows whose URL fails normalisation and report the count.
4. Report listings per top-level branch and per We360 category after mapping.

The evidence for these exclusions is under [Why World, Regional, and Kids_and_Teens stay excluded](#why-world-regional-and-kids_and_teens-stay-excluded).

### E. Taxonomy map

`data/taxonomy_map.csv` has the columns `curlie_path`, `we360_category`, `status`, and `note`. The longest whole-segment prefix wins. Prefixes only, with no wildcards, and every row has a note. `status` is exactly one of:

- `confident`: one category chosen; judgement calls are flagged in the note
- `ambiguous`: plausibly fits two or more, listed with `|`, such as `Job Search|Hiring & Recruitment`
- `unmapped`: no We360 equivalent, with `we360_category` empty

Map one level deeper where that resolves an ambiguity. Definitions for overlapping categories are fixed; see [Category definitions](#category-definitions).

**Mapping principle:** Curlie groups sites by subject. We map a subject to a We360 category where one matches, and leave it unmapped where none does.

The map is frozen unless the evaluation shows a clear problem.

### F. Curated list

`data/known_domains.csv` has the columns `host_or_prefix`, `we360_category`, `alternative_category`, and `note`.

- Match whole host labels: `google.com` matches `mail.google.com`, never `notgoogle.com`.
- Match whole path segments: `google.com/drive` matches `google.com/drive/x`, not `google.com/drivex`.
- The longest match wins: more host labels first, then more path segments.
- Cover the major workplace apps by subdomain or path, plus major Indian and non-English sites such as `naukri.com`, `flipkart.com`, and `paytm.com`.
- Include `khanacademy.org`, whose homepage listing is lost by ignoring Kids_and_Teens.
- `alternative_category` is optional and goes in `alternatives`, such as Teams: Meeting, alternative Chat & Messaging. Several are separated with `|`.

Confidence 1.0, method `curated`, 143 rows, and every row is reviewed by the project owner.

### G. Curlie lookup

Each listing, after filtering, is one vote labelled by the taxonomy map. Only homepage listings vote: a deep-page listing describes that page's subject, while We360 categorises the site being used. A listing is a homepage listing when its normalised URL has no path.

Find the listings to use, stopping at the first level that has any:

1. Homepage listings of the same host.
2. Homepage listings of any host under the same registered domain.
3. If the registered domain has only deep-page listings, return Undefined (`curlie_deep_page_only`) with their categories in `alternatives`.
4. No listings: go to the text model.

The input URL's path plays no part in the lookup, so a deep URL gets the same answer as its site's homepage.

Decide from the listings found, where share = votes for a confident category / all listings found (confident + ambiguous + unmapped):

- Top confident share of at least 0.60, compared before rounding: that category, confidence = share rounded to 3 decimals, method `curlie`.
- Otherwise, any confident votes: Undefined (`curlie_split_votes`), top candidates in `alternatives`.
- Otherwise, any ambiguous votes: Undefined (`curlie_ambiguous`), candidates in `alternatives`.
- Otherwise, only unmapped: Undefined (`curlie_unmapped`), Curlie path in `evidence`.

If Curlie lists the site, the text model does not run. The lookup uses all filtered Curlie data, not just the training split. There is one test per outcome.

### H. Text model

**Examples:** one per host, labelled with the lookup's rule: the top confident category, only with at least 60% of that host's homepage listings. Hosts without homepage listings are not examples. We360 categorises the site, not the page, so the model sees only the host. Paths, titles, and descriptions are never model input, and a deep URL gets the same answer as its site's homepage.

**`url_to_text(host)`,** shared by training and prediction: lowercase, replace every character outside `a-z0-9` with a space, and drop the tokens `www`, `http`, `https`, `html`, `htm`, `php`, `asp`, `aspx`, `index`, and `xn`. The TLD stays. `chess-puzzles.net` becomes `chess puzzles net`.

**Splits:** hosts go into train, validation, and test at 70/15/15 by registered domain, seed 42, with each domain in exactly one split.

- Hosts with no confident label are dropped from training. `unmapped` hosts stay in validation and test but are excluded from accuracy, macro-F1, and threshold selection.
- Cap every split at 50 rows per registered domain (random, seed 42). In validation and test the cap covers labelled and `unmapped` rows together.
- In training, apply the per-domain cap first, then cap at 2,000 examples per category (random, seed 42).
- A category needs at least 50 training examples to enter the model. Excluded categories are listed under [Model training](#model-training).

**Fixed model, no grid search:**

- `TfidfVectorizer(analyzer="char_wb", ngram_range=(3,5), min_df=2, sublinear_tf=True)`
- `LogisticRegression(C=1.0, class_weight="balanced", max_iter=1000, random_state=42)`

If the saved model exceeds 25 MB, raise `min_df` to 3 and note it here. With balanced class weights, scores are not true probabilities.

**Prediction:** if the top score reaches the threshold, return that category, method `model`, the next 2 categories in `alternatives`, and the top 5 contributing n-grams in `evidence` (contribution = TF-IDF value x coefficient for the predicted class). `alternatives` excludes the model's own answer, as it does for Curlie. Otherwise return Undefined (`model_low_confidence`), with the top 3 candidates in `alternatives`. A host with no known n-gram always returns Undefined.

### I. Threshold

Fixed before seeing any test results. Coverage is the share of hosts not returned as Undefined, and precision is accuracy on the covered hosts. Try 0.00 to 0.95 in steps of 0.05 on validation, and choose the lowest threshold with precision of at least 0.80. If none reaches 0.80, choose the highest-precision threshold with coverage of at least 10%, and say so here. Run the test set exactly once, with the chosen threshold.

### J. Output format

Every result has all fields:

```json
{
  "url": "input as given",
  "normalized": "normalised URL or null",
  "category": "a We360 category or Undefined",
  "confidence": 0.0,
  "method": "rule | curated | curlie | ut1 | model | undefined",
  "explanation": "one plain-English sentence",
  "evidence": ["Curlie paths, rule matched, top n-grams"],
  "alternatives": [{"category": "name", "confidence": 0.0}],
  "undefined_reason": "null or a reason below"
}
```

- `undefined_reason` is `null` or one of `invalid_url`, `curlie_deep_page_only`, `curlie_split_votes`, `curlie_ambiguous`, `curlie_unmapped`, `ut1_split_votes`, `ut1_ambiguous`, `model_low_confidence`, or `model_unavailable` (no model file exists, as in Phase 2).
- Undefined results have confidence 0.0.
- `alternatives` use the measured share or score, or `null` where none exists, such as a curated alternative.
- `normalized` is `null` for System Processes results.

### K. Evaluation

**Domain-separated test set:** measures the text model only, on hosts. `python -m src.evaluate test` reports accuracy, macro-F1, coverage, the most-confused category pairs, and separately the share of `unmapped` hosts the model assigns a category. Undefined counts as wrong for accuracy and macro-F1. Precision on covered hosts and no-threshold scores are also reported. Every model score appears beside the majority-class baseline, and every per-category score shows the number of test examples beside it. The same code reports on validation first, and a second test run is refused. The one exception is the post-hoc confusion matrix under "Detailed results", made after every decision was final.

**Gold set:** `data/gold_urls.csv` has the columns `url`, `label`, `also_acceptable`, `in_curated`, and `note`, and measures the whole pipeline. `also_acceptable` is empty or one other category. It reports:

- strict accuracy (`label` only), lenient accuracy (`label` or `also_acceptable`), and coverage, overall and per method
- the Undefined rate, broken down by `undefined_reason`
- results with and without the curated list
- every case where the curated list overrode Curlie
- separate groups for the drafted candidates, `major-app` rows, and Indian and non-English rows

`Undefined` is a valid gold label: predicting Undefined for it is correct, and predicting a category is wrong. Every score appears beside the majority-label baseline. There are no per-category gold scores because the set is too small.

**Gold candidates:** about 75 drafted URLs, with at least 2 per category where possible, about 15 likely to be Undefined, and about 10 Indian or non-English tagged in `note`. Notes describe the site without suggesting a label. The 92 hosts in `data/mapping_probe_hosts.txt` were looked up while drafting the map or testing the lookup, so neither they nor any host under the same registered domain can be drafted candidates.

**Known limitation of the gold set:** the 15 rows labelled `Undefined` had earlier notes that suggested that answer, before the notes were cleaned. The pipeline answered all 15 correctly, so that part of the score may not be fully independent.

**Tagged rows:** a tag is a whole word in `note`.

- `major-app`: 10 realistic URLs for major workplace apps. The probe-host exclusion does not apply, because the curated list decides them, not Curlie.

### O. Extra sources (version 2)

Version 2 adds UT1, the Université Toulouse Capitole categorised domain lists, through a generic source design. Curlie keeps its own logic.

**A source** has a loader that yields `(host, source_category)` rows and its own folder under `data/sources/`, holding `mapping.csv` and a lookup file. `src/sources.py` lists the sources, and `python -m src.build_sources` builds their lookups without touching the Curlie lookup or the model.

**Mapping:** `mapping.csv` has the columns `source_category`, `we360_category`, `status`, and `note`, with one row per list. It maps whole lists, never individual domains. `status` is `confident`, `ambiguous`, `unmapped`, or:

- `excluded`: the list is not about a subject. It gives no votes and is not read by the loader. `examen_pix` and `tricheur_pix` are marked by UT1 as not for general use, so they must not be used at all.

**Decisions are precomputed at build time.** The build applies the 60% vote rule from Section G over each host's lists, counting each list once, with unmapped lists in the denominator. It ships only hosts with one of these outcomes:

- a category, with its share as the confidence
- `ut1_split_votes`, with the top candidates
- `ut1_ambiguous`, with the candidates

**Lookup format:** `lookup.json.gz` is a plain compressed dictionary of `{host: decision}`, like the Curlie lookup. Classification doesn't need the mapping file.

**Matching:** check the host, then each parent host one label at a time, stopping at the registered domain. The first match wins, so the longest entry wins. An entry applies only to its own host and that host's subdomains, and never to sibling hosts. So `copilot.microsoft.com` says nothing about `learn.microsoft.com`, while `bankofamerica.com` covers `secure.bankofamerica.com`. An entry on a public or platform suffix, such as `blogspot.com`, labels only itself, because each site under it is its own registered domain.

**Output:**

- A category gives method `ut1`, with confidence = share, the UT1 category named in the explanation, and the matched entry in `evidence`.
- `ut1_split_votes` and `ut1_ambiguous` return Undefined, and the model does not run.
- If Curlie lists the site without a category and UT1 gives no category either, the Curlie reason stands.

**Trade-off of precomputing:** no host listed only in unmapped UT1 lists is shipped, so no host listed only in adult or malware lists is shipped. There are 5,028,634 such hosts, and they used to return a UT1 Undefined. Now:

- A URL on such a host reaches the model, unless an earlier step answers or a parent entry matches.
- 14,257 of these hosts match a parent entry with a category and take that category. Another 293,634 match a parent entry with no category and stay Undefined.
- In a random sample of 10,000 of them, 74 got a category from the model and 32 from a parent entry, so about 1% now get a category they didn't get before. Curlie answered another 107, as before, and the other 9,787 stayed Undefined.

In return, the lookup is 1.3 MB and needs no special format. `reports/ut1_build_report.txt` and `reports/ut1_report.txt` record the counts in this section.

**Mixed votes:** a host that is also on a mapped list is still shipped, and its record names all its lists, because the vote needs them. 6,004 shipped hosts have a vote from an adult or malware list this way. None of them gets a category, so they return Undefined. They stay because removing them would let the model guess on hosts that are partly flagged as adult or malware.

**Subdomains inherit:** a subdomain with no entry of its own takes its parent's UT1 decision, and 14,257 of the hosts above take a category this way. The curated list works the same way: `shopify.com` covers every store subdomain, and a longer entry such as `mail.google.com` takes priority. So a phishing subdomain on a shopping site gets Shopping from its parent. This is accepted, because detecting malicious subdomains is a security task, outside a categoriser's job.

**Lookup only:** UT1 is never model training data. The model, Curlie lookup, taxonomy map, curated list, and threshold are unchanged from version 1.

**Licence:** the UT1 lookup is a separate file under CC BY-SA 4.0 and is never merged with the Curlie lookup. `data/sources/ut1/README.md` holds the notice, attribution, source link, licence link, and what was changed.

**Gold v2:** `data/gold_v2_urls.csv` is version 2's headline. It has the same columns as the original gold set, with the note `v2-new` on every row. It has 54 URLs, and none of them is in the curated list. Of the 56 rows given, 2 were dropped and not replaced, because no row may be on an original gold domain, a probe host, or a host seen while building version 2:

- `https://www.semrush.com/` is a probe host.
- `https://www.gov.uk/` appeared as a UT1 example in the analysis output during V2-1.

A host counted as seen if it appeared in a project text file other than the curated list, or in the output from V2-1 and V2-2. Curated rows would have been allowed, as they are in the original set, but none came up.

**Comparing the versions:** `python -m src.evaluate gold-v2` scores version 2 beside version 1 on the new set. `python -m src.evaluate gold` does the same on the original set, which is post-hoc for version 2, and `reports/gold_report.txt` stays as the record of version 1's run.

- Version 1's answers come from the frozen version 1 folder through `scripts/classify_with_v1.py`, which saves them in `reports/`.
- Each report confirms that version 2 with UT1 switched off gives the same answers as version 1.
- Intervals are 95% Wilson intervals, which behave on small samples.
- A wrong answer gives a category. On the strict rate, that category isn't the label, and on the lenient rate, it isn't the label or `also_acceptable`. Undefined is never a wrong answer, though it still counts against accuracy unless the label is Undefined.

**Test-set results stay valid:** they measure the text model alone, and the model file is byte-identical to version 1's.

### L. Language limitation

The tool only sees URLs, so language matters in two ways: sites listed only under World are missing from the lookup, and the model won't recognise non-Latin or transliterated host names. World and Regional stay excluded, and the curated list covers major Indian and non-English sites. Non-Latin hosts share few n-grams with the training data, so they normally score below the threshold and return Undefined. Transliterated names may share more n-grams with English words, so Undefined can't be guaranteed for either group.

### M. Repo and runnability

- The raw dump and `.venv` are in `.gitignore`, and `python -m src.build` downloads and builds everything on any platform.
- The Curlie licence allows it, so the built lookup (`.json.gz`) and trained model (`joblib`) are committed, and the quickstart works without the dump.
- Exact versions are pinned in `requirements.txt`, and seed 42 is used everywhere.
- The build warns if the dump differs from the snapshot named in the README, because Curlie refreshes it.

### N. Working style

- Aim for under 1,000 lines of Python including tests. This is a target, not a hard limit. CSV data and documentation don't count.
- Readable code matters more than line count: don't compress code or cut tests to fit, but avoid unnecessary code.
- The current count is in the README.
- Each phase report includes a per-file line breakdown, grouped as core code, tests, and one-off dataset analysis.
- Plain functions, with no unnecessary classes or abstraction.
- Throwaway scripts need not be kept, but every number in the README and this document must be reproducible from project code.

## Category definitions

| Category | Definition | Main evidence |
|---|---|---|
| Analytics | Web analytics, business intelligence, and data analysis tools | Curlie |
| Banking & Finance | Banks, payments, insurance, investing, and accounting | Curlie |
| Calling & Phone | Phone carriers, internet calling, and call centre services | Curated list |
| Chat & Messaging | Chat, instant messaging, and SMS tools | Curated list |
| Design | Graphic, web, and engineering design tools and studios | Curlie |
| Developer | Programming, version control, databases, and web development | Curlie |
| E-commerce | Sellers, store platforms, and management | Curlie |
| Education | Learning platforms and institutions | Curlie |
| Email | Email services, clients, and servers | Curated list |
| File Sharing | Cloud storage, file transfer, and peer-to-peer tools | Curated list |
| Gaming | Games of all kinds, including gambling | Curlie |
| Hiring & Recruitment | Employers and recruiters | Curlie |
| In House Tools | Private or intranet hosts | Rules |
| Internet | Search engines, browsers, ISPs, hosting, and domain registrars | Curlie |
| Job Search | Candidates looking for jobs | Curlie |
| Knowledge Management | Internal wikis and notes | Curated list |
| Lifestyle | Health, home, food, travel, pets, and hobbies | Curlie |
| Marketing | Advertising, agencies, search engine optimisation, and email marketing | Curlie |
| Meeting | Video and audio conferencing | Curated list |
| Music & Videos | Streaming media | Curlie |
| News & Entertainment | News and editorial content | Curlie |
| Office Apps | Documents, spreadsheets, presentations, calendars, and team software | Curated list |
| Photos | Photo sharing, stock photos, and photographers | Curlie |
| Research & Reference | Public reference material | Curlie |
| Shopping | Consumers buying things | Curlie |
| Social Media | Social networks and community platforms | Curated list |
| Sports | Sports news, teams, and events | Curlie |
| System Processes | Browser and OS addresses | Rules |
| Undefined | Not enough evidence for any category | Pipeline outcome |

## Detailed results

### Test results: the text model

These are **test results** from the single run of `python -m src.evaluate test`, saved in `reports/test_report.txt`. They sit beside validation results from `reports/validation_report.txt`. The threshold was fixed on validation before the test set ran.

With no threshold, the model beats the majority-class baseline on the test set: 0.394 against 0.235 accuracy, and 0.234 against 0.015 macro-F1.

The threshold trades coverage for precision. At 0.60, the model answers 7.2% of test hosts with 0.819 precision, and returns Undefined for the rest.

Accuracy at the threshold (0.059) is below the baseline only because Undefined counts as wrong. The baseline always answers, so it never takes that penalty.

| Score | Test, no threshold | Test, threshold 0.60 | Test baseline (always Lifestyle) | Validation, no threshold | Validation, threshold 0.60 | Validation baseline (always Lifestyle) |
|---|---:|---:|---:|---:|---:|---:|
| Accuracy | 0.394 | 0.059 | 0.235 | 0.391 | 0.058 | 0.229 |
| Macro-F1 | 0.234 | 0.153 | 0.015 | 0.249 | 0.179 | 0.014 |
| Coverage | 1.000 | 0.072 | 1.000 | 1.000 | 0.072 | 1.000 |
| Precision on covered | 0.394 | 0.819 | 0.235 | 0.391 | 0.802 | 0.229 |

The test set has 37,563 labelled hosts and 29,940 unmapped hosts, and validation has 37,300 and 30,416. On both, the model assigns a category to 0.011 of the unmapped hosts. At the threshold, the most-confused test pairs are Research & Reference answered as Education (170), Shopping answered as Music & Videos (28), and Lifestyle answered as Education (27).

| Category | Test examples | Test F1, threshold 0.60 | Test F1, no threshold | Test F1, baseline | Validation examples | Validation F1, threshold 0.60 | Validation F1, no threshold | Validation F1, baseline |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Analytics | 51 | 0.035 | 0.039 | 0.000 | 60 | 0.030 | 0.051 | 0.000 |
| Banking & Finance | 1,759 | 0.181 | 0.480 | 0.000 | 1,766 | 0.158 | 0.470 | 0.000 |
| Calling & Phone | 62 | 0.216 | 0.079 | 0.000 | 67 | 0.156 | 0.071 | 0.000 |
| Chat & Messaging | 37 | 0.093 | 0.059 | 0.000 | 49 | 0.254 | 0.113 | 0.000 |
| Design | 1,198 | 0.112 | 0.288 | 0.000 | 1,153 | 0.122 | 0.289 | 0.000 |
| Developer | 823 | 0.010 | 0.256 | 0.000 | 893 | 0.027 | 0.258 | 0.000 |
| E-commerce | 139 | 0.082 | 0.074 | 0.000 | 128 | 0.058 | 0.073 | 0.000 |
| Education | 2,227 | 0.526 | 0.629 | 0.000 | 2,154 | 0.504 | 0.601 | 0.000 |
| Email | 39 | 0.351 | 0.123 | 0.000 | 50 | 0.395 | 0.215 | 0.000 |
| File Sharing | 13 | 0.111 | 0.071 | 0.000 | 23 | 0.222 | 0.191 | 0.000 |
| Gaming | 967 | 0.100 | 0.305 | 0.000 | 998 | 0.081 | 0.321 | 0.000 |
| Hiring & Recruitment | 86 | 0.192 | 0.077 | 0.000 | 95 | 0.132 | 0.086 | 0.000 |
| Internet | 224 | 0.206 | 0.144 | 0.000 | 262 | 0.302 | 0.187 | 0.000 |
| Job Search | 73 | 0.289 | 0.140 | 0.000 | 94 | 0.474 | 0.211 | 0.000 |
| Knowledge Management | 38 | 0.130 | 0.075 | 0.000 | 29 | 0.205 | 0.044 | 0.000 |
| Lifestyle | 8,822 | 0.002 | 0.430 | 0.380 | 8,549 | 0.001 | 0.426 | 0.373 |
| Marketing | 554 | 0.065 | 0.165 | 0.000 | 530 | 0.066 | 0.174 | 0.000 |
| Meeting | 16 | 0.276 | 0.053 | 0.000 | 26 | 0.350 | 0.075 | 0.000 |
| Music & Videos | 2,812 | 0.091 | 0.375 | 0.000 | 2,947 | 0.079 | 0.368 | 0.000 |
| News & Entertainment | 1,509 | 0.048 | 0.305 | 0.000 | 1,570 | 0.053 | 0.305 | 0.000 |
| Office Apps | 67 | 0.119 | 0.073 | 0.000 | 48 | 0.179 | 0.053 | 0.000 |
| Photos | 686 | 0.440 | 0.372 | 0.000 | 717 | 0.454 | 0.390 | 0.000 |
| Research & Reference | 5,269 | 0.036 | 0.423 | 0.000 | 5,127 | 0.036 | 0.431 | 0.000 |
| Shopping | 5,848 | 0.000 | 0.429 | 0.000 | 5,718 | 0.001 | 0.409 | 0.000 |
| Social Media | 24 | 0.071 | 0.038 | 0.000 | 27 | 0.133 | 0.078 | 0.000 |
| Sports | 4,220 | 0.189 | 0.578 | 0.000 | 4,220 | 0.171 | 0.574 | 0.000 |

### Test confusion matrices (post-hoc)

**Post-hoc: this is a second scoring of the test split,** made at the project owner's request after every decision was final, and nothing changed as a result. These come from `python -m scripts.confusion_matrix`, with the matrices in `reports/test_confusion_threshold_0.60.csv` and `reports/test_confusion_no_threshold.csv`. They reproduce the saved test report: every overall score, all 52 per-category F1 values, and all 20 listed pairs. The model file is byte-identical, so they apply to both versions.

- **No threshold:** 14,799 of the 37,563 hosts are right. Small categories are heavily over-predicted, probably because of the balanced class weights. Analytics has 51 true hosts but receives 566 answers, so its precision is 0.021, and Social Media has 24 but receives 240, also at 0.021.
- **The largest error source is Lifestyle:** of its 8,822 hosts, 2,805 are right, 1,078 go to Research & Reference, and 1,006 go to Shopping.
- **Threshold 0.60:** the model answers 2,708 hosts, with 2,217 right and 491 wrong, and 34,855 are Undefined. The largest error is Research & Reference answered as Education, which is 170 of the 491.
- **Two large categories almost vanish at the threshold:** the model never answers Shopping (5,848 hosts) and answers Lifestyle only 7 times (8,822 hosts), so the threshold's coverage comes from other categories.

### Gold results: the whole pipeline

These are version 1's **gold results**, from its own `python -m src.evaluate gold`, saved in `reports/gold_report.txt`. Strict accuracy uses `label` only, and lenient accuracy also accepts `also_acceptable`. Each drafted row moves a score by about 1.3 points, so small differences mean little. High scores on curated rows are weak evidence, because the list and the labels both rest on human or AI knowledge of those sites.

| Group | Curated list | URLs | Strict accuracy | Lenient accuracy | Coverage | Precision on covered |
|---|---|---:|---:|---:|---:|---:|
| **Drafted candidates (headline)** | With | 75 | 0.720 | 0.733 | 0.533 | 0.975 |
| Drafted candidates | Without | 75 | 0.627 | 0.640 | 0.440 | 0.970 |
| Drafted candidates baseline (always Undefined) | Not used | 75 | 0.200 | 0.200 | 0.000 | 0.000 |
| major-app rows | With | 10 | 1.000 | 1.000 | 1.000 | 1.000 |
| major-app rows | Without | 10 | 0.400 | 0.400 | 0.400 | 1.000 |
| major-app baseline (always Email) | Not used | 10 | 0.200 | 0.200 | 1.000 | 0.200 |
| Indian and non-English rows | With | 14 | 0.643 | 0.643 | 0.571 | 1.000 |
| Indian and non-English rows | Without | 14 | 0.357 | 0.357 | 0.286 | 1.000 |
| Indian and non-English baseline (always Lifestyle) | Not used | 14 | 0.143 | 0.143 | 1.000 | 0.143 |
| All rows | With | 85 | 0.753 | 0.765 | 0.588 | 0.980 |
| All rows | Without | 85 | 0.600 | 0.612 | 0.435 | 0.973 |
| All rows baseline (always Undefined) | Not used | 85 | 0.176 | 0.176 | 0.000 | 0.000 |

Drafted candidates by method, with the curated list:

| Method | Share of rows | Strict accuracy | Lenient accuracy |
|---|---:|---:|---:|
| Rule | 0.053 | 1.000 | 1.000 |
| Curated | 0.173 | 1.000 | 1.000 |
| Curlie | 0.293 | 0.955 | 1.000 |
| Model | 0.013 | 1.000 | 1.000 |
| Undefined | 0.467 | 0.429 | 0.429 |

Undefined rate by reason, as row counts:

| Group | Curated list | Undefined rate | `model_low_confidence` | `curlie_split_votes` | `curlie_deep_page_only` | `curlie_unmapped` | `invalid_url` |
|---|---|---:|---:|---:|---:|---:|---:|
| Drafted candidates | With | 0.467 | 23 | 4 | 2 | 3 | 3 |
| Drafted candidates | Without | 0.560 | 29 | 4 | 3 | 3 | 3 |
| major-app rows | With | 0.000 | 0 | 0 | 0 | 0 | 0 |
| major-app rows | Without | 0.600 | 2 | 2 | 2 | 0 | 0 |
| Indian and non-English rows | With | 0.429 | 5 | 0 | 1 | 0 | 0 |
| Indian and non-English rows | Without | 0.714 | 8 | 0 | 2 | 0 | 0 |

The curated list overrode a Curlie answer on no gold row. Of the 21 rows missed on strict accuracy, 20 returned Undefined and 1 gave a wrong category (`tiktok.com` as Music & Videos, which `also_acceptable` allows). The gold report lists all 21.

**No post-hoc changes to results:** no map rows, curated rows, or thresholds changed after these results were seen, and the checksums of the model, lookup, taxonomy map, and curated list matched before and after both runs. Later code changes, which change no reported number, are listed in the README under "Changes after the test run".

### Version 2 gold results: new gold set

These come from `python -m src.evaluate gold-v2`, saved in `reports/gold_v2_report.txt`, which also lists every row either version missed. Each row moves a score by about 1.9 points. No code, mapping, lookup, curated row, or threshold changed after these results were seen. An AI model drafted the set after seeing UT1's categories, so its authorship may favour UT1, and this isn't an independent test.

| Score | Version 1 | Version 2 | Baseline (always Undefined) |
|---|---:|---:|---:|
| Strict accuracy | 0.370 | 0.463 | 0.074 |
| Strict accuracy, 95% interval | 0.254 to 0.504 | 0.337 to 0.594 | 0.029 to 0.176 |
| Lenient accuracy | 0.407 | 0.500 | 0.074 |
| Lenient accuracy, 95% interval | 0.287 to 0.540 | 0.371 to 0.629 | 0.029 to 0.176 |
| Coverage | 0.389 | 0.481 | 0.000 |
| Precision on covered, strict | 0.762 | 0.808 | 0.000 |
| Precision on covered, lenient | 0.857 | 0.885 | 0.000 |
| Wrong-answer rate, strict | 0.093 | 0.093 | 0.000 |
| Wrong-answer rate, lenient | 0.056 | 0.056 | 0.000 |

On strict accuracy, both versions got 20 rows right and both missed 29. Only version 2 got 5 right, and only version 1 got none right. An exact two-sided sign test on those 5 gains and 0 losses gives p = 2 × 0.5^5 = 0.0625, so the gain is suggestive but not conclusive. Version 2 with UT1 switched off gives the same answers as version 1 on all 54 rows.

By method:

| Method | Version 1 share | Strict | Lenient | Version 2 share | Strict | Lenient |
|---|---:|---:|---:|---:|---:|---:|
| Rule | 0.056 | 1.000 | 1.000 | 0.056 | 1.000 | 1.000 |
| Curlie | 0.278 | 0.667 | 0.800 | 0.278 | 0.667 | 0.800 |
| UT1 | Not used | | | 0.111 | 1.000 | 1.000 |
| Model | 0.056 | 1.000 | 1.000 | 0.037 | 1.000 | 1.000 |
| Undefined | 0.611 | 0.121 | 0.121 | 0.519 | 0.143 | 0.143 |

Undefined by reason, as row counts:

| Version | Undefined rate | `model_low_confidence` | `curlie_deep_page_only` | `curlie_unmapped` | `curlie_split_votes` | `ut1_ambiguous` |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 0.611 | 25 | 4 | 3 | 1 | 0 |
| 2 | 0.519 | 20 | 3 | 3 | 1 | 1 |

Every row UT1 decided:

| Host | Label | Version 1 | Version 2 | UT1 lists |
|---|---|---|---|---|
| `revolut.com` | Banking & Finance | Undefined | Banking & Finance | `bank` |
| `coinbase.com` | Banking & Finance | Undefined | Banking & Finance | `bitcoin` |
| `sendspace.com` | File Sharing | Undefined | File Sharing | `filehosting` |
| `lichess.org` | Gaming | Undefined | Gaming | `games` |
| `soundcloud.com` | Music & Videos | Undefined | Music & Videos | `audio-video`, `radio`, `social_networks` |
| `mastodon.social` | Social Media | Social Media, from the model | Social Media | `social_networks` |
| `gotomeeting.com` | Meeting | Undefined | Undefined (`ut1_ambiguous`) | `remote-control` |

All 5 wrong answers on strict accuracy come from Curlie, in both versions: `dribbble.com`, `duolingo.com`, and `hey.com` are wrong on both rates, and `framer.com` and `pexels.com` are wrong on the strict rate only. Of these, only `hey.com` was looked up in the dump, and nothing changed as a result. Its one listing, `http://www.hey.com/`, is titled "Hey!" and describes YouTube channel management and video marketing, under `Business/Marketing_and_Advertising/Marketing_Support_Services/Media/Video`. That isn't today's HEY email service, so the listing appears stale.

**Which categories UT1 helps:** 14 We360 categories have a confident UT1 list, and 14 don't. `reports/gold_v2_report.txt` has the counts per label.

| We360 categories | Rows | Version 1 right | Version 2 right |
|---|---:|---:|---:|
| With a confident UT1 list | 27 | 12 | 17 |
| With no confident UT1 list | 23 | 4 | 4 |
| Label is Undefined | 4 | 4 | 4 |

- **It helps** where a web-filtering list has a topic: Banking & Finance gained 2 rows, and File Sharing, Gaming, and Music & Videos gained 1 each. The original set adds News & Entertainment.
- **It doesn't help** the 14 categories with no confident list: Analytics, Calling & Phone, Design, Developer, E-commerce, Education, Hiring & Recruitment, In House Tools, Job Search, Knowledge Management, Marketing, Meeting, Office Apps, and Photos. These hold most of the workplace software that version 1 misses. The 4 rows right on the new set came from the rules, Curlie, or the model, not UT1.
- **Coverage is patchy where a list exists:** UT1 gave no answer for `signal.org`, `pcloud.com`, `razorpay.com`, `ajio.com`, or `urbancompany.com`.
- **The lists are lopsided:** Gaming has 63.5% of the hosts with a category and Shopping has 18.3%, while System Processes has 29 hosts and Chat & Messaging has 214 (`reports/ut1_report.txt`).

**The new set is harder than the original for both versions**, so version 1's 0.370 here shouldn't be compared with its 0.720 there. The new set has no curated rows, where the original drafted group has 13, and 4 rows labelled Undefined, where that group has 15. Curlie's answers are also weaker: 10 of 15 right here, against 21 of 22 there. So version 1's precision of 0.975 may be optimistic, though some of these rows are judgement calls on labels.

### Version 2 gold results: original gold set (post-hoc)

**Post-hoc: seen while building v2.** These come from `python -m src.evaluate gold`, saved in `reports/gold_posthoc_report.txt`. Version 1's column reproduces its reported scores exactly, and `reports/gold_report.txt` is unchanged.

| Group | URLs | Strict v1 | Strict v2 | Lenient v1 | Lenient v2 | Coverage v1 | Coverage v2 | Precision v1 | Precision v2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Drafted candidates | 75 | 0.720 | 0.733 | 0.733 | 0.747 | 0.533 | 0.547 | 0.975 | 0.976 |
| major-app rows | 10 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| Indian and non-English rows | 14 | 0.643 | 0.714 | 0.643 | 0.714 | 0.571 | 0.643 | 1.000 | 1.000 |
| All rows | 85 | 0.753 | 0.765 | 0.765 | 0.776 | 0.588 | 0.600 | 0.980 | 0.980 |

The 95% intervals on strict accuracy for the drafted group are 0.610 to 0.809 and 0.624 to 0.820. For all rows they are 0.652 to 0.832 and 0.664 to 0.842.

UT1 decided 2 rows. `spiegel.de` went from Undefined to News & Entertainment, through the `press` list, and `fastmail.com` moved from the model to UT1 with the same answer. No row got worse. Both versions still miss 20 rows, and 15 of them are in categories with no confident UT1 list.

The gain here is 1 row in 85, and on the new set it's 5 in 54. The original set wasn't built with UT1 in view, and the new one was drafted after seeing UT1's categories, so the true gain could well be nearer the smaller figure.

### Model training

Every number in this section comes from `python -m src.build`, which saves it in `reports/training_report.txt`.

| Category | Training hosts |
|---|---:|
| Analytics | 211 |
| Banking & Finance | 2,000 |
| Calling & Phone | 330 |
| Chat & Messaging | 222 |
| Design | 2,000 |
| Developer | 2,000 |
| E-commerce | 573 |
| Education | 2,000 |
| Email | 222 |
| File Sharing | 55 |
| Gaming | 2,000 |
| Hiring & Recruitment | 409 |
| Internet | 1,289 |
| Job Search | 347 |
| Knowledge Management | 131 |
| Lifestyle | 2,000 |
| Marketing | 2,000 |
| Meeting | 98 |
| Music & Videos | 2,000 |
| News & Entertainment | 2,000 |
| Office Apps | 273 |
| Photos | 2,000 |
| Research & Reference | 2,000 |
| Shopping | 2,000 |
| Social Media | 114 |
| Sports | 2,000 |

The model has 30,274 training hosts and 74,378 n-grams, and it saves at 14.4 MB with `min_df=2`. In House Tools and System Processes are excluded because they have no examples; rules handle them.

The threshold rule chose 0.60 because it is the lowest threshold that reaches 0.80 precision on validation.

### Dump statistics

Every number in this section comes from `python -m scripts.inspect_dump`, which saves it in `reports/dump_report.txt`.

Listings per top-level branch (2,739,037 in total):

| Branch | Listings | Treatment |
|---|---:|---|
| World | 1,259,441 | Ignored |
| Regional | 706,465 | Ignored |
| Business | 126,852 | Mapped |
| Arts | 124,697 | Mapped |
| Society | 121,208 | Mapped |
| Science | 57,129 | Mapped |
| Sports | 56,690 | Mapped |
| Computers | 56,203 | Mapped |
| Recreation | 51,620 | Mapped |
| Shopping | 41,996 | Mapped |
| Reference | 33,760 | Mapped |
| Health | 31,618 | Mapped |
| Kids_and_Teens | 26,164 | Ignored |
| Games | 20,799 | Mapped |
| Home | 12,988 | Mapped |
| Adult | 6,403 | Mapped as `unmapped` |
| News | 5,004 | Mapped |

Of the 746,967 retained listings, 470,372 are `confident`, 276,408 are `unmapped`, and 187 are `ambiguous`. The build drops 3 of them because their URLs fail normalisation, as recorded in `reports/build_report.txt`.

Listings per We360 category after mapping:

| Category | Listings | Registered domains |
|---|---:|---:|
| Analytics | 553 | 483 |
| Banking & Finance | 12,775 | 12,298 |
| Calling & Phone | 506 | 493 |
| Chat & Messaging | 490 | 397 |
| Design | 9,796 | 8,739 |
| Developer | 16,569 | 8,290 |
| E-commerce | 958 | 945 |
| Education | 27,817 | 13,759 |
| Email | 832 | 599 |
| File Sharing | 175 | 129 |
| Gaming | 20,799 | 8,421 |
| Hiring & Recruitment | 627 | 618 |
| In House Tools | 0 | 0 |
| Internet | 2,771 | 2,211 |
| Job Search | 661 | 603 |
| Knowledge Management | 266 | 237 |
| Lifestyle | 89,453 | 64,761 |
| Marketing | 3,903 | 3,818 |
| Meeting | 154 | 151 |
| Music & Videos | 40,936 | 22,202 |
| News & Entertainment | 44,850 | 13,328 |
| Office Apps | 561 | 507 |
| Photos | 5,522 | 5,033 |
| Research & Reference | 90,090 | 40,416 |
| Shopping | 42,356 | 40,299 |
| Social Media | 262 | 222 |
| Sports | 56,690 | 31,381 |
| System Processes | 0 | 0 |

In House Tools and System Processes have no Curlie listings because they come from rules.

World has 1,259,441 listings in 91 languages. The largest ten are Deutsch (394,751), Français (167,277), Japanese (123,049), Italiano (109,187), Russian (80,312), Español (78,019), Nederlands (56,629), Polski (38,884), Türkçe (36,171), and Dansk (22,128). Nine Indian languages hold 1,052 listings: Hindi (614), Tamil (166), Telugu (71), Gujarati (54), Marathi (46), Urdu (37), Punjabi_Gurmukhi (28), Bangla (19), and Kannada (17).

The dump has no cross-language field. Category descriptions contain occasional free-text links: 150 links from 75 of the 291,321 World categories point to English topics, and those categories directly hold 531 listings. They are too sparse to map World into the lookup, so World stays excluded.

`Regional/Asia/India` has 7,532 listings. The most common topic segments across all 706,465 Regional listings are Business_and_Economy (240,640), Society_and_Culture (81,357), Travel_and_Tourism (65,286), Education (42,879), Arts_and_Entertainment (40,264), Government (35,405), Lodging (31,369), Health (29,499), Recreation_and_Sports (29,392), Shopping (21,469), Religion (21,428), Real_Estate (20,397), Construction_and_Maintenance (16,437), Computers_and_Internet (15,806), and Restaurants_and_Bars (14,380). A segment counts as a topic when it appears under at least 100 different parent paths, excluding `Localities`, which only organises places.

Ignoring Kids_and_Teens removes these registered domains from the lookup: 5,120 are listed only in Kids_and_Teens anywhere in the dump (1,605 of them have an English listing, and the rest appear only under its International branch), and 8,874 have no retained listing (2,006 with an English listing).

### Why World, Regional, and Kids_and_Teens stay excluded

- **World:** cross-language links reach only 0.04% of World's listings (531 of 1,259,441), so there is no practical way to map them.
- **Regional:** India's largest topic is Business_and_Economy (3,329 of 7,532 listings), which would largely stay unmapped, like the Business branch.
- **Kids_and_Teens:** 1,605 registered domains with an English listing appear only there. Major ones, such as `khanacademy.org`, go in the curated list instead.
