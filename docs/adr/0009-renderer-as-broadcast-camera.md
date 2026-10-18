# ADR-0009: The renderer is the broadcast camera, with recorded camera truth

- Status: accepted · Date: 2026-10-18

## Context
Three features need pictures of the match:
- the Studio's live feed;
- the input for auto-eventing;
- each fan's highlight films.

Each needs the pictures for a different reason, and the vision lane must be scored against exact ground truth.

## Options considered
1. **Browser-side 3D (Three.js) only.** Beautiful and interactive, but there would be no server-side video for vision or for films without headless-browser capture.
2. **A game engine.** Heavy, hard to run in containers, and licences complicate a public repo.
3. **A server-side 2.5D renderer in Python with Skia** (chosen). Skia is BSD-licensed and is Chrome's graphics engine.

## Decision
- A pinhole camera at the main gantry (behind the near touchline, ~22 m up), steered by a director model: a critically damped pan that leads play and zooms with ball depth and team spread.
- Pitch geometry follows Laws of the Game dimensions. Players are floodlit figures in match kits with numbers. Kit clashes are resolved before rendering.
- 10 Hz tracking is interpolated to 25 fps. Frames are piped as raw RGBA into ffmpeg (H.264, yuv420p, faststart). An explicit RGBA surface avoids the platform-dependent BGRA swap.
- Per frame, `truth.jsonl` records the camera parameters and every player's and the ball's screen box: perfect labels for training and scoring the vision lane.

## Consequences
- One renderer serves the live feed, auto-eventing and films.
- Performance needs care: the camera orientation is computed once per frame, and real-time 720p is the target. Stadium detail (stands, crowd) is a polish item for D7.
