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
  - British English: `en-GB-RyanNeural`; Nigerian English: `en-NG-AbeoNeural`;
  - Nigerian Pidgin: `en-NG-EzinneNeural`, which reads Pidgin text and is to be confirmed by native listening;
  - Arabic: `ar-SA-HamedNeural`;
  - Spanish, French and Portuguese: national voices.
- **Yoruba, Hausa and Igbo** are captions-only until a self-hosted **YarnGPT2** voice passes a native listening check. Its licence chain is clear: model Apache-2.0, WavTokenizer MIT, outetts Apache-2.0, uroman MIT-style with attribution. SoroTTS and Wayo GPT were rejected because their licences are non-commercial.
- **Studio:**
  - each card speaks as it cuts in, with a commentary toggle;
  - Arabic cards read right to left in IBM Plex Sans Arabic, while the pitch never mirrors;
  - fonts include the subsets that carry Yoruba and Igbo dotted vowels and tone marks.

## Consequences
- Nigerian fans get Nigerian English and Pidgin with real Nigerian voices today.
- Correctness is guaranteed in every language. Naturalness is not machine-checkable, so each language needs a native review before we call it supported.
- Voice cost is small (cents per match) and, like captions, is paid only for verified lines.
