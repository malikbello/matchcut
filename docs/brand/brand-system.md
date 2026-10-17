# Matchcut brand, design and experience system

Version 1 · 17 Oct 2026 · Visual reference: [brand board](brand-board.png)

## The idea
**Matchcut = the editor's cut.** In film a *match cut* joins two shots by shape or motion. Matchcut cuts the match into each fan's story.
Personality: **precise · cinematic · warm · global · trustworthy.** A broadcast confidence, never hype.
Tagline: **Every fan's cut.**

## Logo
- Wordmark **MATCHCUT** in Big Shoulders Display (ExtraBold, all caps, tight tracking). A single diagonal **cut** (14°) slices the second C, and that sliver is shifted in **Signal**.
- The symbol, **the Cut Mark**, is a rounded frame (a screen) with the same 14° cut and a dot (the ball) where the cut exits. It works at 16 px.
- Clear space = the height of the "M" crossbar. Never on busy imagery without a scrim.

## Colour (dark-first "floodlit night"; a light set for documents)
| Token | Hex | Role |
|---|---|---|
| ink-950 | #07090D | Canvas |
| ink-900 | #0C1016 | App background |
| ink-800 | #141A22 | Surfaces, cards |
| ink-700 | #212A35 | Lines, dividers |
| chalk | #F4F6F9 | Primary text (pitch-chalk white) |
| mist | #9AA6B5 | Secondary text |
| **signal** | **#FF4A2E** | Brand accent: LIVE, the cut, primary actions (broadcast tally-light) |
| **verified** | **#2DE3A0** | Reserved *only* for "checked against data" |
| floodlight | #FFB547 | Pending, warnings, checks in progress |
| data | #6CC8FF | Analytics lines and charts |
| turf-900 / turf-600 | #0B2E23 / #1B6A4C | Pitch only |
Rules: one accent per view; verified mint never decorative; colour always paired with an icon or label; text contrast ≥ 4.5:1 (chalk on ink-950 ≈ 18:1; signal on ink-950 ≈ 5.7:1). The palette is deliberately far from the Premier League's purple, neon green and pink.

**Clubs:** 20 fictional clubs get generated kit pairs. The system guarantees ΔE ≥ 30 between opponents in any match, with an automatic switch to away kits.

## Type (all SIL Open Font Licence, free to ship)
- **Big Shoulders Display:** scores, headlines, big numbers (the stadium voice).
- **Inter:** UI and body, with tabular figures for every stat.
- **JetBrains Mono:** match clock, timecodes, evidence IDs.
- **IBM Plex Sans Arabic** (right to left) and **Noto Sans Devanagari** (Hindi).
- Scale: 12 · 14 · 16 · 20 · 28 · 40 · 64 · 96. Line-height 1.15 for display, 1.5 for body.

## Motion: broadcast cut grammar
- Graphics **cut in**: 160 ms wipe (clip-path) + 12 px slide, ease-out; exit 120 ms. No bounce, no spin.
- Numbers tick up with tabular figures; the score bug never shifts width.
- **Verified stamp:** a 240 ms mint underline sweep after the verifier passes.
- `prefers-reduced-motion` turns this into opacity fades.

## Imagery
- No real people, crests or footage. Players are **stylised floodlit figures**: kit colours, numbers, rim light, ground shadow. Crests are generated geometric marks per club.
- High definition: highlights render at **1080p** (16:9) and **1080×1920** (9:16 for stories); UI at 60 fps.

## Product experience
**Personas**
1. **Tunde, Lagos:** casual and loyal; watches on a phone; English or Pidgin; data-conscious; shares on WhatsApp status.
2. **Sofía, Madrid:** analyst and fantasy player; Spanish; wants xG, pressing, evidence.
3. **Omar, Riyadh:** family viewer; Arabic, right to left; wants the story and the big moments.
4. **Priya, Bengaluru:** a new fan; Hindi or English; needs explanations without jargon.
5. **Studio producer** at a rights-holder: needs reliable, timed, machine-readable graphics.
6. **Hackathon judge:** needs to understand the value in 2 minutes and try it in 2 clicks.

**Principles:** readable in 2 seconds · one hero number per card · evidence one tap away · spoiler-safe · thumb-zone controls · captions always · right-to-left mirrored · WCAG 2.2 AA.

**Shareables:** "Your Cut" vertical video; player-of-the-match card; milestone card. All are watermarked "Matchcut · synthetic match", so nobody can mistake them for real footage.

## Football expertise layer (what the analytics staff insist on)
- **Metrics with published foundations:**
  - xG from distance, angle, body part, assist type and pressure;
  - expected threat (xT, Karun Singh's grid) for pass value;
  - PPDA for pressing;
  - field tilt;
  - progressive passes;
  - pass difficulty;
  - momentum (rolling xT difference);
  - control vs chaos (possession stability vs turnover and transition rate).
- **Realism targets (top-flight norms):** ~2.7–2.9 goals per match; 24–27 shots; pass completion 80–85%; outfield distance 10–11.5 km; top speeds 33–36 km/h; 10–14 fouls per team.
- **Commentary tone per market:** UK broadcast (understated, judgement then number); Nigerian (warm, Pidgin optional, proverb-light); Spanish (rhythmic, celebratory); Arabic (formal, poetic); Hindi (clear, explanatory). Native-quality review checklist for each language.
