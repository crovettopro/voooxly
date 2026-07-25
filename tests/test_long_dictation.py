"""A long dictation cannot be half-lost.

The 60s cap defeated the latch, which exists precisely for long dictations:
the user pinned the recording, spoke for two minutes and everything past
second 60 vanished without warning. These tests pin the three caps that have
to rise AT THE SAME TIME — fixing only the first one moves the problem instead
of solving it: without the audio cap, the ceiling becomes max_tokens (text cut
off mid-sentence) and then the LLM timeout (the raw transcription gets pasted).
"""
from voooxly import audio
from voooxly.config import load_config

# 5 minutes: a real long dictation. The cap is not removed entirely because it
# is still the safety net against a stuck key, which would record until the
# disk fills up.
MIN_DURACION = 300.0


def test_el_dataclass_permite_dictados_largos():
    assert audio.AudioConfig().max_duration >= MIN_DURACION


def test_el_yaml_permite_dictados_largos():
    cfg = load_config()
    assert cfg.get("audio.max_duration", 0) >= MIN_DURACION


def test_refine_does_not_cut_long_dictation_text():
    # 5 min of speech ≈ 750 words ≈ 1000 output tokens. With 1200 the text
    # came out cut mid-sentence as soon as the 60s cap was removed.
    cfg = load_config()
    assert cfg.get("llm.claude.max_tokens", 0) >= 4000


def test_local_llm_has_time_for_long_text():
    # 20s was enough for 150 words; not for 750. On expiry, the code falls
    # back to pasting the raw transcription: the user experiences it as "the
    # AI stopped working precisely on long dictations".
    cfg = load_config()
    assert cfg.get("llm.ollama.timeout", 0) >= 60
