"""Audition Chatterbox with Nigerian languages and its emotion dial (Kaggle GPU).

Uses the naija-tts LoRA of Chatterbox Multilingual for LISTENING ONLY: its training
data is undisclosed, so it is never shipped. What we learn is whether a
Chatterbox voice with "exaggeration" can carry build-up and goal excitement in
Yoruba, Hausa and Igbo. If it can, we fine-tune our own on Google WAXAL
(CC-BY-4.0) and BibleTTS (CC-BY-SA).

Reference voices are WAXAL test-split recordings (CC-BY-4.0). Each line is made
at three exaggeration levels, calm to excited, with a lower CFG weight on the
excited takes as the Chatterbox authors advise for expressive speech.
"""

import io
import json
import subprocess
import sys

subprocess.run(
    [sys.executable, "-m", "pip", "install", "-q", "chatterbox-tts", "soundfile", "pandas", "pyarrow"],
    check=True,
)
# chatterbox pins its own torch; Kaggle's torchvision then no longer matches and breaks
# transformers' imports. Chatterbox does not use torchvision, so remove it.
subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", "-q", "torchvision"], check=False)

from pathlib import Path  # noqa: E402

import chatterbox.mtl_tts as mtl  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import soundfile as sf  # noqa: E402
import torch  # noqa: E402
from chatterbox.mtl_tts import ChatterboxMultilingualTTS  # noqa: E402
from huggingface_hub import hf_hub_download, snapshot_download  # noqa: E402

LINES = {
    "yo": {
        "call": "Gọ́ọ̀lù! Quinouani! Ìparí tó ya lórí! Kestrel Bay ti ń ṣáájú!",
        "line": "Quinouani ṣe gọ́ọ̀lù ọ̀kan fún Kestrel Bay FC ní ìsẹ́jú àádọ́ta àti mẹ́ta, àsìkò tí ó máa ń di gọ́ọ̀lù nígbà mẹ́sàn-án nínú mẹ́wàá.",
        "build": "Kestrel Bay ń lọ síwájú, Quinouani ti fọ́ taara sí gọ́ọ̀lù...",
    },
    "ha": {
        "call": "GOL! Quinouani! Kai kyakkyawar kammalawa! Kestrel Bay na gaba!",
        "line": "Quinouani na Kestrel Bay FC ya zura, ya sa Kestrel Bay ɗaya zuwa sifili a minti na hamsin da uku. Dama ce da ake cin sau tara cikin goma.",
        "build": "Kestrel Bay sun tashi da hari, Quinouani ya fita kai tsaye kan raga...",
    },
    "ig": {
        "call": "Gọl! Quinouani! Nke a mara mma! Kestrel Bay nọ n’ihu!",
        "line": "Quinouani tọrọ gọl, Kestrel Bay dị otu nula na nkeji iri ise na atọ, ohere a bụ nke ị ga-etọ gọl itoolu n’ime iri.",
        "build": "Kestrel Bay kụrụ ọsọ n’ihu, Quinouani pụtara n’ihu gọl...",
    },
    "en": {
        "call": "Goal! Quinouani! What a finish! Kestrel Bay lead!",
        "line": "Kestrel Bay FC's Quinouani makes it one nil in the fifty-third minute, a chance you would score nine times in ten.",
        "build": "Kestrel Bay break forward, Quinouani is through on goal...",
    },
}  # from research/voices/spoken-lines.json
WAXAL = {"yo": "yor", "ha": "hau", "ig": "ibo"}
# (exaggeration, cfg_weight): calm analysis, rising build-up, goal call
DELIVERY = {"line": [(0.5, 0.5)], "build": [(0.7, 0.4)], "call": [(0.9, 0.3), (1.3, 0.25)]}

out = Path("/kaggle/working/chatterbox")
(out / "refs").mkdir(parents=True, exist_ok=True)


def reference_voices(lang: str, wanted: int = 2) -> list[Path]:
    """Pick clean 5 to 10 second WAXAL test clips from different speakers."""
    code = WAXAL[lang]
    parquet = hf_hub_download(
        "google/WaxalNLP", f"data/TTS/{code}/{code}-test-00000.parquet", repo_type="dataset"
    )
    df = pd.read_parquet(parquet)
    picked, seen = [], set()
    for row in df.itertuples():
        if row.speaker_id in seen:
            continue
        wav, sr = sf.read(io.BytesIO(row.audio["bytes"]))
        if wav.ndim > 1:
            wav = wav.mean(axis=1)
        if 5 <= len(wav) / sr <= 10:
            path = out / "refs" / f"{lang}-spk{row.speaker_id}-{row.gender}.wav"
            sf.write(path, wav.astype(np.float32), sr)
            picked.append(path)
            seen.add(row.speaker_id)
        if len(picked) == wanted:
            break
    return picked


for code, name in [("ha", "Hausa"), ("yo", "Yoruba"), ("ig", "Igbo"), ("en-ng", "Nigerian English")]:
    mtl.SUPPORTED_LANGUAGES[code] = name
repo = snapshot_download("PlotweaverAI/naija-tts")
model = ChatterboxMultilingualTTS.from_local(repo, device="cuda")

manifest = []
for lang in WAXAL:
    for ref in reference_voices(lang):
        for kind, takes in DELIVERY.items():
            for exaggeration, cfg in takes:
                torch.manual_seed(42)
                wav = model.generate(
                    LINES[lang][kind],
                    language_id=lang,
                    audio_prompt_path=str(ref),
                    exaggeration=exaggeration,
                    cfg_weight=cfg,
                )
                audio = wav.squeeze().cpu().numpy().astype(np.float32)
                name = f"{lang}-{kind}-x{exaggeration}-{ref.stem}.wav"
                sf.write(out / name, audio, model.sr)
                manifest.append(
                    {
                        "file": name,
                        "lang": lang,
                        "kind": kind,
                        "exaggeration": exaggeration,
                        "cfg_weight": cfg,
                        "reference": ref.name,
                        "seconds": round(len(audio) / model.sr, 1),
                        "text": LINES[lang][kind],
                    }
                )
                print(json.dumps(manifest[-1], ensure_ascii=False), flush=True)
(out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
