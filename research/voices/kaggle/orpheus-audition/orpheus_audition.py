"""Audition Sunbird's Orpheus-3B multilingual voices for Yoruba, Hausa and Igbo (Kaggle GPU).

Speakers come from Google's WAXAL recordings (CC-BY-4.0). Each language gets the
same three lines a commentator would say: a build-up, a goal call and an analysis
line with numbers written as words. Every clip is made at three seeds, because
Orpheus samples, so a listener can judge the voice rather than one lucky take.
Outputs land in /kaggle/working as WAV files plus a manifest.
"""

import json
import subprocess
import sys

subprocess.run(
    [sys.executable, "-m", "pip", "install", "-q", "snac", "soundfile", "transformers>=4.51", "accelerate"],
    check=True,
)

from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
import torch  # noqa: E402
from snac import SNAC  # noqa: E402
from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: E402

MODEL_ID = "Sunbird/orpheus-3b-tts-multilingual"
END_OF_TEXT, START_OF_SPEECH, END_OF_SPEECH = 128009, 128257, 128258
START_OF_HUMAN, END_OF_HUMAN = 128259, 128260
AUDIO_LO, AUDIO_HI = 128266, 128266 + 7 * 4096

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

SPEAKERS = {
    "yo": ["waxal_yor_0002", "waxal_yor_0006", "waxal_yor_0008"],
    "ha": ["waxal_hau_0004", "waxal_hau_0006"],
    "ig": ["waxal_ibo_0003", "waxal_ibo_0005"],
}
SEEDS = [7, 42, 123]

out = Path("/kaggle/working/orpheus")
out.mkdir(parents=True, exist_ok=True)
dtype = torch.float16  # T4 and P100 have no fast bfloat16
tok = AutoTokenizer.from_pretrained(MODEL_ID)
model = AutoModelForCausalLM.from_pretrained(MODEL_ID, torch_dtype=dtype).to("cuda").eval()
snac = SNAC.from_pretrained("hubertsiuzdak/snac_24khz").to("cpu").eval()


def decode(ids: torch.Tensor) -> np.ndarray:
    sos = (ids == START_OF_SPEECH).nonzero(as_tuple=True)[0]
    if len(sos):
        ids = ids[sos[-1].item() + 1 :]
    audio = ids[(ids >= AUDIO_LO) & (ids < AUDIO_HI)]
    cl = [t.item() - AUDIO_LO for t in audio[: (audio.size(0) // 7) * 7]]
    l1, l2, l3 = [], [], []
    for i in range(len(cl) // 7):
        l1.append(cl[7 * i])
        l2.append(cl[7 * i + 1] - 4096)
        l3.append(cl[7 * i + 2] - 2 * 4096)
        l3.append(cl[7 * i + 3] - 3 * 4096)
        l2.append(cl[7 * i + 4] - 4 * 4096)
        l3.append(cl[7 * i + 5] - 5 * 4096)
        l3.append(cl[7 * i + 6] - 6 * 4096)
    if not l1:
        return np.zeros(12000, dtype=np.float32)
    clamp = lambda v: [max(0, min(4095, x)) for x in v]  # noqa: E731
    codes = [torch.tensor(clamp(layer)).unsqueeze(0) for layer in (l1, l2, l3)]
    with torch.inference_mode():
        return snac.decode(codes).squeeze().cpu().numpy().astype(np.float32)


def synthesize(text: str, speaker: str, seed: int) -> np.ndarray:
    torch.manual_seed(seed)
    text_ids = tok(f"{speaker}: {text}", return_tensors="pt").input_ids
    ids = torch.cat(
        [torch.tensor([[START_OF_HUMAN]]), text_ids, torch.tensor([[END_OF_TEXT, END_OF_HUMAN]])], dim=1
    ).to("cuda")
    with torch.inference_mode():
        gen = model.generate(
            input_ids=ids,
            attention_mask=torch.ones_like(ids),
            max_new_tokens=1600,
            do_sample=True,
            temperature=0.6,
            top_p=0.95,
            repetition_penalty=1.1,
            eos_token_id=END_OF_SPEECH,
        )
    return decode(gen[0].cpu())


manifest = []
for lang, speakers in SPEAKERS.items():
    for kind in ("build", "call", "line"):
        text = LINES[lang][kind]
        for speaker in speakers:
            for seed in SEEDS:
                wav = synthesize(text, speaker, seed)
                name = f"{lang}-{kind}-{speaker}-s{seed}.wav"
                sf.write(out / name, wav, 24000)
                manifest.append(
                    {
                        "file": name,
                        "lang": lang,
                        "kind": kind,
                        "speaker": speaker,
                        "seed": seed,
                        "seconds": round(len(wav) / 24000, 1),
                        "text": text,
                    }
                )
                print(json.dumps(manifest[-1], ensure_ascii=False), flush=True)
(out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
