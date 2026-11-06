# UT1 source

`lookup.json.gz` and `mapping.csv` in this folder are shared under the [Creative Commons Attribution-ShareAlike 4.0 International licence](https://creativecommons.org/licenses/by-sa/4.0/). This licence applies to these two files, not to the rest of the project. The lookup is kept separate from the Curlie lookup and must never be merged with it.

## Attribution

The data comes from the UT1 categorised domain lists by Université Toulouse Capitole, maintained by Fabrice Prigent, and is licensed under CC BY-SA 4.0. The source is <https://dsi.ut-capitole.fr/blacklists/>.

The licence comes with no warranty. Use of this data does not imply that Université Toulouse Capitole endorses this project.

## What was changed

`lookup.json.gz` is adapted from the archive below:

- It uses only each list's `domains` file, not its `urls` or `expressions` files.
- It leaves out 11 lists marked `excluded` in `mapping.csv`, including `examen_pix` and `tricheur_pix`, which UT1 marks as not for general use.
- Entries are normalised: lowercase, punycode for international names, and no leading `www.`. Entries that are invalid or contain a path are dropped.
- Each host is stored with a precomputed We360 decision and the UT1 lists that voted on it.
- Hosts listed only in `unmapped` lists, such as adult and malware lists, are left out. A host that is also on a mapped list stays, and its record names all its lists.

`mapping.csv` is new work that maps UT1's categories to We360's.

## Snapshot

- **Download:** `https://dsi.ut-capitole.fr/blacklists/download/blacklists.tar.gz`
- **Archive date (HTTP Last-Modified):** 5 November 2026, 21:50:17 GMT
- **Downloaded:** 6 November 2026, 04:34 GMT
- **Size:** 26,650,450 bytes
- **SHA-256:** `e12f93efa8687f641132b54ad37ce8e4889f1e8c1be646f357b200d93e329d96`
- **Licence file in the archive:** `LICENSE.pdf`

The archive stays in `data/raw/ut1`, which git ignores. `python -m src.build_sources` downloads it and rebuilds the lookup.
