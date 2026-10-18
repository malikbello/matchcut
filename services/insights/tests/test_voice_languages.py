import httpx
from matchcut_contracts import Cue, CueStatus, Fact, MomentKind
from matchcut_insights.languages import LANGUAGES, canonical
from matchcut_insights.verify import numbers_in, verify_translation
from matchcut_insights.voice import AzureSpeech, ssml, voice_cues

NAMES = {"Quinouani", "Kestrel Bay FC"}


def _cue(lang: str, status: CueStatus = CueStatus.VERIFIED, text: str = "Quinouani scores: 1-0.") -> Cue:
    return Cue(
        match_id="kes-wcr-7",
        cue_id=f"CU-00002-{lang}",
        moment_id="MO-00002",
        kind=MomentKind.GOAL,
        t_ms=1000,
        clock="0:01",
        language=lang,
        status=status,
        text=text,
        facts=[Fact(fact_id="F-002", label="score", value="1-0", source="analytics")],
    )


def test_every_language_has_a_valid_tag_and_style():
    for tag, lang in LANGUAGES.items():
        _cue(tag)  # the contract accepts every tag we ship
        assert lang.style
    assert LANGUAGES["ar"].rtl
    assert LANGUAGES["en-NG"].voice == "azure:en-NG-AbeoNeural"
    assert LANGUAGES["yo"].voice is None  # captions only until a voice passes the native listening check


def test_tags_match_case_insensitively():
    assert canonical("EN-ng") == "en-NG"
    assert canonical("PCM") == "pcm"
    assert canonical("xx") is None


def test_arabic_indic_digits_count_as_the_same_numbers():
    assert numbers_in("النتيجة ١-٠ بعد ٥٣ دقيقة") == ["1", "0", "53"]
    src = "Quinouani scores in minute 53: 1-0."
    assert verify_translation(src, "سجل Quinouani في الدقيقة ٥٣: ١-٠.", NAMES).passed
    assert not verify_translation(src, "سجل Quinouani في الدقيقة ٥٤: ١-٠.", NAMES).passed


def test_ssml_reads_scores_and_abbreviations_like_a_broadcaster():
    s = ssml("Quinouani & co: 0.93 xG, 1-0. PPDA 1.9", "en-NG", "en-NG-AbeoNeural")
    assert 'xml:lang="en-NG"' in s
    assert '<sub alias="1 nil">1-0</sub>' in s
    assert '<sub alias="x G">xG</sub>' in s
    assert '<sub alias="P P D A">PPDA</sub>' in s
    assert "&amp;" in s  # text is escaped
    assert '<sub alias="2 a 1">2-1</sub>' in ssml("2-1", "es", "es-ES-AlvaroNeural")


def test_azure_speech_is_keyless_and_skips_caption_only_languages(tmp_path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["Authorization"]
        seen["url"] = str(request.url)
        return httpx.Response(200, content=b"ID3fake-mp3")

    speech = AzureSpeech(
        "https://example.cognitiveservices.azure.com/",
        "/subscriptions/x/resourceGroups/y/providers/Microsoft.CognitiveServices/accounts/z",
        lambda: "entra-token",
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    cues = [_cue("en-NG"), _cue("yo"), _cue("pcm", CueStatus.PLAIN)]
    assert voice_cues(cues, speech, tmp_path) == 1
    assert seen["auth"].startswith("Bearer aad#/subscriptions/x/")
    assert seen["auth"].endswith("#entra-token")
    assert seen["url"].endswith("/tts/cognitiveservices/v1")
    assert cues[0].audio == "audio/kes-wcr-7/CU-00002-en-NG.mp3"
    assert cues[0].voice == "azure:en-NG-AbeoNeural"
    assert cues[1].audio is None  # Yoruba: captions only for now
    assert cues[2].audio is None  # plain cards are not spoken
    assert (tmp_path / cues[0].audio).read_bytes() == b"ID3fake-mp3"
    # second run reuses the cached file without calling the service
    seen.clear()
    fresh = [_cue("en-NG")]
    assert voice_cues(fresh, speech, tmp_path) == 1
    assert not seen
