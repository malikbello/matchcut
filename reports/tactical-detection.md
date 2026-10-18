# Tactical-shift detection vs hidden truth

8 full matches; each contains one hidden tactical change (a switch to a high press).
A detection counts if it names the right team within 10 minutes after the change.
Detector settings were tuned on 16 separate matches (seeds 400-415); these 8 are held out.

**Precision 83% · Recall 62%**

| Match | True changes | Detections | Correct |
|---|---|---|---|
| kes-wcr-300 | 1 | 1 | 1 |
| cpt-lth-301 | 1 | 1 | 1 |
| asm-tdw-302 | 1 | 1 | 1 |
| hcn-rkh-303 | 1 | 1 | 1 |
| wxm-sol-304 | 1 | 1 | 0 |
| thw-kes-305 | 1 | 0 | 0 |
| flm-cpt-306 | 1 | 0 | 0 |
| irv-asm-307 | 1 | 1 | 1 |
