# ADR-0016: Every film is also audio described, for blind and partially sighted fans

- Status: accepted · Date: 2026-10-26

## Context
A blind or partially sighted fan hears the caller shout "GOAL!" but not who had the ball, how the move was built or what the scorer did next. In stadiums, audio descriptive commentary fills that gap, but provision is thin: a Level Playing Field survey found only 4 of the 20 Premier League clubs offering in-house commentary by trained audio describers. RNIB's research with blind football fans names what helps most: where the ball is and who has it, the kits so listeners know who is who, how an attack builds, the score and the time, and "a lot less waffle".

## Decision
- **A describer of its own.** A calm neural voice in each of the seven voiced languages, distinct from the caller, speaks only in the gaps the caller and the analyst leave. It never talks over them and never runs over a cut into the next clip.
- **Facts from code, words from us.** `matchcut_insights.describe` builds every description from the tracking feed and the events: who has the ball (the last completed action, not the nearest player: a pass in flight through a crowded box passes defenders), where (from the attacking side's view: in the box, on the edge of the box, out wide), passes that take an attack forward, one-twos, the ball won, set pieces, who scored with which foot from how far, the celebration the Studio draws for him, and each replay angle as it starts. The phrases are written in each language in code, as the play-by-play calls are: no model writes or translates a description, so there is nothing to verify after the fact.
- **The score and the time, briefly.** Each moment clip opens with the minute and the state of the game ("52 minutes, goalless", "73 minutes, Kestrel Bay FC lead 1-0"); the live track says the full score every five minutes.
- **Gaps are scarce, so the action goes first.** The editor places descriptions by priority (the action, then replays, then who has the ball, then the clock), each in the first gap at or after its moment; one that would land more than 3 s late is left out, because it would describe the past. The describer reads briskly (+30 %) with no padding around its words, as stadium describers do.
- **Made and checked like every film.** The render job makes each moment's described film in every language next to the standard one, and each Recap Factory replica makes its fan's described film from the same pictures (only the sound is mixed again). The QA agent hears every description in them as it hears every call.
- **One tap for the fan.** "Audio description" in the Studio bar switches the reel, shared links and fans' films to their described versions; the choice is remembered on the device.

## Consequences
- The described films cost one more sound mix and one more QA check per film; nothing is rendered twice.
- 2,779 descriptions for the demo match in seven languages, voiced by Azure AI Speech for about US$2 of list price.
- The live show plays at up to 15 times match speed, faster than any describer can follow, so audio description is offered in the films, which play at match speed.
