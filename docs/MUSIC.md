# Music: sources and licence check

Plan §5 and §20 require a music library whose licence permits paid advertising, with the check and the licence text recorded here. Checked on **20 Nov 2026**.

## Licence

Every track is released by its own artist under **CC0 1.0 Universal** (public domain dedication). The full legal code is in [music/CC0-1.0-legalcode.txt](music/CC0-1.0-legalcode.txt) (downloaded from `https://creativecommons.org/publicdomain/zero/1.0/legalcode.txt` on 20 Nov 2026). Section 2 waives all copyright and related rights *"for any purpose whatsoever, including without limitation commercial, advertising or promotional purposes"*. So:

- paid advertising: allowed;
- credit: not required (the ads carry none; this page keeps the record);
- redistribution: allowed, so the 30-second beds can live in this public repo.

## The tracks

One bed per theme, picked by the owner from three checked candidates each. Every track page on Free Music Archive (FMA) states: *"&lt;Title&gt; by &lt;Artist&gt; is licensed under a CC0 1.0 Universal License"*, and every page shows "Instrumental: Yes" and "AI generated: No".

| Theme | Track | Artist | Album | Track page |
| --- | --- | --- | --- | --- |
| Sport | ITS A TRAP | HoliznaCC0 | After Dark | https://freemusicarchive.org/music/holiznacc0/after-dark/its-a-trap-1/ |
| Beauty | Ocean Memory | HoliznaCC0 | OCEAN MEMORY ( Lo-fi Chill ) | https://freemusicarchive.org/music/holiznacc0/ocean-memory-lo-fi-chill/ocean-memory/ |
| Tech | Track 1 | HoliznaCC0 | War ( Game Commission ) | https://freemusicarchive.org/music/holiznacc0/war-game-commission/track-1/ |
| Food | Toy Box | HoliznaCC0 | Spring Woke Me Up | https://freemusicarchive.org/music/holiznacc0/spring-woke-me-up/toy-box/ |
| Fashion | Everything is groovy (How to move your body) | Komiku | Helice Awesome Dance Adventure !! | https://freemusicarchive.org/music/Komiku/Helice_Awesome_Dance_Adventure_/everything-is-groovy-how-to-move-your-body/ |

## Composition and recording

FMA shows a generic notice on every CC0 download: a song has two parts (composition and recording), and a CC0 label might not cover both under every national law. For these tracks the artist is the composer and the recording artist and published the work themselves, and CC0 waives "Copyright and Related Rights" (which include the rights in a recording). Statements read on the artists' pages:

- HoliznaCC0 album pages: *"This music is completely Public Domain, so use it how you want!"*; *"This is the project I've made specifically for the creative commons. CC0 use how you want!"* (producer and engineer listed as Holizna).
- HoliznaCC0, "War ( Game Commission )" (the Tech track): *"This is a commision piece I did."* and *"They agreed to allow me to put the music into the public domain as CC0!"*
- Komiku: *"Use it how you want."*

Residual risk, accepted: a third party could still wrongly claim a track (for example through a platform's automatic content matching). If that happens, the claim is disputed with this record, or the theme's bed is swapped.

## How the beds are made

`backend/scripts/make_music_beds.py <folder>` cuts each downloaded track into a 30-second bed at its loudest stretch (skipping the first 4 s), fades it in (0.3 s) and out (1.5 s), normalises it to −18 LUFS, strips all tags and cover art, and writes `backend/app/music/<theme>.m4a` plus `music.yaml` (source, licence, cut). The original downloads are not in the repo. `compose.py` lays the bed under the voiceover and lowers it while the voice speaks.

## Sources tried and dropped

- **FreePD** (planned first choice): the site has closed (`freepd.com` shows "The hosting and maintenance of the site have ceased"; its category pages return 404), so its licence could not be checked at the source.
