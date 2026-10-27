# ADR-0014: A QA agent checks every film after it is made

- Status: accepted · Date: 2026-10-23

## Context
The Verifier (ADR-0010) checks every line before it is voiced. That proves the words were true, not that the film says them: a stale voice file, a caption burned from an older line, a mix that buries the commentary or a failed render would all reach fans unseen. Films are made by machines in minutes; nobody watches each one in seven languages before it ships.

## Decision
- **Check the film, not the plan.** After a film is mixed, the QA agent listens to it and reads it. Azure AI Speech fast transcription hears the soundtrack (Entra token, no keys); gpt-5-mini reads the text on the frame at the middle of each caption's window; ffmpeg's EBU R128 meter measures loudness.
- **AI perceives, code judges.** The plan the film was cut from says what must be heard (each call and verified line, at its time) and what must be read (each caption, in its window). `matchcut_editing.qa.judge` compares, in code: a line is heard when 60 % of its words are in the transcript from just before it starts to 1.5 s after its voice ends; a caption is read when 80 % of its words are on the frame; the level must sit within 2 LU of -16 LUFS. No model judges another model's work.
- **Fair to recognisers, strict on content.** Invented club and player names are left out of the word count (a recogniser spells them its own way), near spellings count ("bat" for "but"), and a number counts whether it is heard in digits or in words in the film's language ("73" as "seventy-three", "9th" as "ninth", a score's 0 as "nil"; spelled with num2words), but never nearly ("9th" is not "the", "fifteen" is not "fifty"). Naijá has no Azure recogniser, so its lines are checked for being voiced where the plan puts them, and the report says so.
- **A second listen, as a person checking would.** A line the whole film's transcript misses is listened to again on its own: just its stretch of the film, from 0.5 s before its voice to 0.5 s after. The same code judges it by the same rule; the report keeps both hearings (`first_heard_as`, `listened: again`) and the screens say how many lines needed it. Only missed lines are sent again, a few seconds of audio each.
- **On the render path.** The job mixes each language's film as soon as its clip is captioned and checks it there (`{key}.{lang}.qa.json` beside the film); `matchcut-recap qa` runs the same check locally and exits non-zero on any failure. A perception outage is a flagged film, never a lost one.
- **Fans see the verdict.** Each moment in the reel carries a Checked or Flagged chip with lines heard, captions read and the level; a flagged film lists what failed and when.

## Consequences
- The agent has already caught real faults: voices that no longer matched their rewritten lines (the voice cache keyed on cue id; it now keys on the words) and a clip whose caption predated the history lines.
- About 2.4 US cents of Azure AI per 80 s film at list price (Speech by the audio hour, gpt-5-mini by the token), measured per film.
- The listening window grows with each line's voice: a fixed 6 s window once marked the tail of a 10 s line as unheard.
- Audio description (26 Oct) put a second voice beside the caller. On Azure, 4 of 28 described moment films were flagged although every line was in the mix (measured: the call sat about 10 dB over the crowd, as in the standard film). Two were numbers opening a sentence, which the recogniser writes in words ("Seventy-three minutes ... one-nil"); three were short calls straight after the describer that the whole-film transcript dropped and a second listen to the line alone heard ("C'est au fond. Kinoani.").
