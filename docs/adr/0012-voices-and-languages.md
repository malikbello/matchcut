# ADR-0012: Voices and languages

- Status: accepted · Date: 2026-10-18

## Context
Matchcut serves fans in their own language, starting with Nigerian fans and Arabic-speaking fans as well as English, Spanish, French and Portuguese. Verified lines should be heard, not only read. Two facts shaped the decision:
- Azure AI Speech has British English, **Nigerian English** (`en-NG`) and many Arabic voices.
- It has no Yoruba, Hausa, Igbo or Nigerian Pidgin voices; its multilingual voices don't cover them either.

## Decision
- **Ten languages, BCP 47 tags:**
  - `en` (British broadcast English), `en-NG` (Nigerian English), `pcm` (Nigerian Pidgin);
  - `yo`, `ha`, `ig`, `ar`, `es`, `fr`, `pt`.

  One registry (`languages.py`) holds each language's style guide for the Localiser, its direction and its voice.
- **Rules every language follows,** checked by the Verifier:
  - the same numbers, with Arabic-Indic digits normalised before comparing;
  - player and club names kept in Latin script, as broadcasters show squad names;
  - no em dashes.
- **Spoken commentary:**
  - Only verified lines are spoken.
  - Azure AI Speech is called keylessly through our Foundry resource, with the *Cognitive Services Speech User* role.
  - SSML reads scores the way fans say them ("one nil", "uno a cero") and says "xG" and "PPDA" as letters, at a brisk broadcast pace.
  - Audio is generated once per cue and cached.
- **Voices:**
  - British English: `en-GB-Harry` on Microsoft MAI-Voice-2.1, chosen in a listening test on 18 Oct over the classic `en-GB-RyanNeural`, Emily (excited) and DragonHD Ollie. The live lane can use the same voice on MAI-Voice-2.1-Flash for lower latency.
  - French: `fr-FR-Marc` on MAI-Voice-2.1 (chosen in the same test).
  - Nigerian English: `en-NG-AbeoNeural`; Nigerian Pidgin: `en-NG-EzinneNeural`, which reads Pidgin text and is to be confirmed by native listening;
  - Arabic: `ar-SA-HamedNeural`; Spanish and Portuguese: national voices.
- **Mood:** expressive voices speak with the moment's mood, set per language and kind of moment: joy for an English goal, a shout for a French goal, surprise for a big chance or a great save, calm for analysis. Classic voices have no styles and keep a brisk pace instead. Cost: MAI-Voice-2.1 is $22 and Flash $15 per million characters, under one US cent per match for every language.
- **Cache:** each match's audio folder has a manifest of which voice and mood made each file, so changing a voice re-renders only those lines.
- **Yoruba, Hausa and Igbo** are captions-only in this release; voices are planned for a later one.
  - **YarnGPT2** (licence clear: model Apache-2.0, WavTokenizer MIT, outetts Apache-2.0, uroman MIT-style with attribution) was trialled on 18 Oct on real Matchcut lines. A native Yoruba listener found the Yoruba and Hausa too fast to make out. The trial also found that it strips tone marks before speaking, reads digits as English words, and runs about 25 times slower than real time on a laptop CPU (about 1.5 GB of memory).
  - Also reviewed and set aside: Naija-TTS, a Chatterbox LoRA (MIT, but Yoruba character error rate 45% and GPU-bound); Meta MMS, SoroTTS and Wayo GPT (non-commercial licences); N-ATLaS (speech recognition, not synthesis, with a 1,000-user cap); paid APIs from Intron, Spitch and NaijaLingo (no public pricing).
  - Before revisiting: spoken numbers written as words in each language, a football glossary for the Localiser, and a slower speaking rate, then another native listening check.
- **Studio:**
  - each card speaks as it cuts in, with a commentary toggle;
  - Arabic cards read right to left in IBM Plex Sans Arabic, while the pitch never mirrors;
  - fonts include the subsets that carry Yoruba and Igbo dotted vowels and tone marks.

## Adding a language (how expansion scales)
Languages are data, not code. To add one:
1. Add an entry to `LANGUAGES` in `services/insights/src/matchcut_insights/languages.py`: BCP 47 tag, names, a style guide for the Localiser, direction, voice (`azure:<voice>` or a self-hosted provider prefix) and moods per kind of moment.
2. Add play-by-play templates to `TEMPLATES` in `calls.py` (or leave the language caption-only).
3. Check fonts cover its script (Studio `fonts/`), and add right-to-left if needed.
4. Run the eval and the native review sheet; a language ships only after a native speaker passes it.
The Verifier, API, Studio menus and voice cache need no change. Yoruba, Hausa and Igbo voices are planned for production this way.

## Consequences
- Nigerian fans get Nigerian English and Pidgin with real Nigerian voices today.
- Correctness is guaranteed in every language. Naturalness is not machine-checkable, so each language needs a native review before we call it supported.
- Voice cost is small (cents per match) and, like captions, is paid only for verified lines.
