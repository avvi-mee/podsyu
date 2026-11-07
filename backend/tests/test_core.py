"""Self-checks for the pure logic. Run:  .venv\\Scripts\\python -m tests.test_core   (from backend/)"""
from app.ai.llm import clean_hashtags, select_clips
from app.ai.transcribe import sentences_from_segments
from app.core import secure
from app.processors import captions
from app.processors.reframe import crop_x_expr


def _sentences(texts, dur=8.0):
    out, t = [], 0.0
    for i, txt in enumerate(texts):
        out.append({"i": i, "start": t, "end": t + dur, "text": txt})
        t += dur + 0.4
    return out


def test_select_clips_snaps_and_fixes_context():
    S = _sentences(["Intro hello.", "Most people never manage to save money.", "And that is the problem.", "Here is why it matters.",
                    "You need a system.", "Start with ten percent.", "That changes everything.", "Thanks for listening."])
    # Candidate starts on a dangling "And" sentence and is too short: should pull in context and extend.
    got = select_clips([{"start_index": 2, "end_index": 3, "score": 80, "title": "t"}], S, lo=30, hi=60, n=3)
    assert len(got) == 1
    c = got[0]
    assert not c["transcript"].startswith("And"), c["transcript"]
    assert 30 * 0.85 <= c["end"] - c["start"] <= 60 * 1.05 + 1
    assert c["start"] <= S[c["a"]]["start"] and c["end"] >= S[c["b"]]["end"]  # padded outside sentence bounds


def test_select_clips_dedupes_overlaps_and_ranks():
    S = _sentences([f"Sentence number {i} makes a point." for i in range(30)])
    cands = [{"start_index": 5, "end_index": 9, "score": 60}, {"start_index": 6, "end_index": 10, "score": 90},
             {"start_index": 20, "end_index": 24, "score": 70}]
    got = select_clips(cands, S, lo=30, hi=60, n=5)
    assert [c["score"] for c in got] == [90, 70]


def test_select_clips_penalises_unfixable_dangling_start():
    S = _sentences(["And that is why we keep it open for everyone.", "It matters a lot to the whole world.",
                    "We want to share this with people.", "Thanks."])
    got = select_clips([{"start_index": 0, "end_index": 2, "score": 80}], S, lo=20, hi=40, n=1)
    assert got and got[0]["score"] == 65  # nothing earlier to pull in, so it ranks lower


def test_select_clips_rejects_sponsor_reads():
    S = _sentences(["Let me know in the comments what you think.", "The styling partner for this episode is Levi's.",
                    "Great jeans honestly.", "Now back to the show."])
    assert select_clips([{"start_index": 0, "end_index": 3, "score": 99}], S, lo=20, hi=40, n=1) == []


def test_select_clips_never_ends_on_question_or_filler_and_starts_on_real_sentence():
    S = _sentences(["We almost ran out of money.", "So when we started OpenAI there were almost no AGI labs.",
                    "Everyone thought it was crazy.", "That is why it worked.", "How do you find a non-consensus bet?",
                    "Uh, good question.", "Next topic."])
    got = select_clips([{"start_index": 1, "end_index": 5, "score": 90}], S, lo=20, hi=45, n=1)
    assert got, "expected a clip"
    c = got[0]
    assert c["transcript"].startswith("We almost ran out of money."), c["transcript"]  # pulled in context for "So..."
    assert c["transcript"].endswith("That is why it worked.") and "?" not in c["transcript"], c["transcript"]
    assert c["hook"] == "We almost ran out of money."


def test_clip_never_starts_on_a_sentence_fragment():
    S = _sentences(["So when we", "started OpenAI there were almost no AGI labs and it was hard.",
                    "Everyone thought it was crazy and told us to stop.", "That is exactly why it worked."])
    got = select_clips([{"start_index": 1, "end_index": 3, "score": 90}], S, lo=15, hi=40, n=1)
    assert got and not got[0]["transcript"].startswith("started"), got


def test_clip_includes_directly_following_conclusion():
    S = _sentences(["Most founders quit far too early in the journey.", "They see slow growth and assume failure.",
                    "But compounding takes years to show anything.", "So I think patience is the real advantage.",
                    "Anyway, next question."])
    got = select_clips([{"start_index": 0, "end_index": 2, "score": 80}], S, lo=20, hi=45, n=1)
    assert got and got[0]["transcript"].endswith("So I think patience is the real advantage."), got


def test_content_bounds_skip_intro_teaser_and_outro():
    from app.ai.llm import content_bounds
    texts = ["Big teaser quote one."] * 3 + ["Let me know in the comments below what you think."] +             ["Real conversation sentence here."] * 40 + ["Subscribe for more episodes like this."] + ["Bye."]
    S = _sentences(texts)
    first, last = content_bounds(S)
    assert first == S[3]["end"] and last == S[44]["start"]
    got = select_clips([{"start_index": 0, "end_index": 2, "score": 99}], S, lo=15, hi=40, n=1, bounds=(first, last))
    assert got == []  # teaser region is never clipped


def test_weak_openers_and_host_setup_endings_are_avoided():
    S = _sentences(["Something I want to do.", "Hmm but now everything changed for the whole industry.",
                    "Most people in India are wildly optimistic about AI right now.",
                    "A kid used our tools to raise money for his whole school.", "That blew my mind completely.",
                    "You said that 700 people threatened to resign for you.", "What did you do right as a founder?"])
    got = select_clips([{"start_index": 0, "end_index": 5, "score": 90}], S, lo=20, hi=45, n=1)
    assert got, "expected a clip"
    c = got[0]["transcript"]
    assert c.startswith("Most people in India"), c
    assert c.endswith("That blew my mind completely."), c


def test_needs_context_detects_list_items_and_back_references():
    from app.ai.llm import needs_context
    assert needs_context("One is that there's like a loss of control to AI.")
    assert needs_context("I was not good at sport either.")
    assert needs_context("And that is the problem.")
    assert not needs_context("I believe it is the best time in history to build something.")


def test_select_clips_drops_impossible():
    S = _sentences(["One very long monologue sentence."], dur=200)
    assert select_clips([{"start_index": 0, "end_index": 0, "score": 99}], S, 30, 90, 3) == []


def test_sentences_split_on_punctuation_and_pauses():
    words = [{"w": "Hello", "s": 0, "e": 0.4}, {"w": "there.", "s": 0.5, "e": 0.9}, {"w": "no", "s": 1.0, "e": 1.2},
             {"w": "punctuation", "s": 1.3, "e": 1.8}, {"w": "after", "s": 4.0, "e": 4.3}, {"w": "pause", "s": 4.4, "e": 4.8}]
    s = sentences_from_segments([{"words": words}])
    # a 2.2s thinking pause mid-sentence must NOT split it (that produced clips starting mid-sentence)
    assert [x["text"] for x in s] == ["Hello there.", "no punctuation after pause"]


def test_captions_max_two_lines_and_highlight_events():
    style = captions.resolve_style({"preset": "hormozi"})
    words = [{"w": w, "s": i * 0.3, "e": i * 0.3 + 0.25} for i, w in enumerate(
        "this is a fairly long caption test that should wrap into chunks nicely".split())]
    for chunk in captions.chunk_words(words, style, 1080):
        assert 1 <= len(chunk) <= 2 and all(len(line) <= style["words_per_line"] for line in chunk)
    ass = captions.build_ass(words, style, 0.0, 10.0, 1080, 1920)
    dialogues = [line for line in ass.splitlines() if line.startswith("Dialogue:")]
    assert len(dialogues) == len(words)  # one event per spoken word (word-level highlight)
    assert "&H0000E6FF&" in ass  # yellow highlight in ASS BGR order
    assert "THIS" in ass  # uppercase preset


def test_captions_relative_to_clip_and_validation():
    style = captions.resolve_style({"preset": "minimal"})
    ass = captions.build_ass([{"w": "Hi.", "s": 100.0, "e": 100.5}], style, 99.0, 110.0, 1080, 1920)
    assert "0:00:01.00" in ass
    try:
        captions.resolve_style({"preset": "minimal", "text_color": "red"})
        raise AssertionError("bad colour accepted")
    except ValueError:
        pass


def test_crop_expression_is_flat_step_function():
    assert crop_x_expr([(0.0, 100)]) == "100"
    assert crop_x_expr([(0.0, 100), (2.5, 600)]) == "100+(500)*gte(t\\,2.50)"


def test_audio_mix_has_fades_and_ducked_low_music():
    from app.processors.media import audio_mix_args

    inputs, args = audio_mix_args(30.0)
    assert inputs == [] and "afade=t=out:st=29.500" in args[1] and "loudnorm" in args[1]
    inputs, args = audio_mix_args(30.0, "track.mp3", 0.1)
    graph = args[args.index("-filter_complex") + 1]
    assert inputs == ["-stream_loop", "-1", "-i", "track.mp3"]
    assert "volume=0.100" in graph and "sidechaincompress" in graph and "amix=inputs=2:duration=first" in graph


def test_llm_loop_salvage_and_script_cleanup():
    from app.ai.llm import _salvage
    from app.services.stories import SCRIPT_SCHEMA, clean_script

    raw = ('{"script": "I lost a bet. Four cups waited. [5s-10s] Cut to Alex grinning. I lost again. '
           'The end. Fade out. Cut to black. The end. Fade out. Cut to black. The end. Fa')
    saved = _salvage(raw, SCRIPT_SCHEMA)
    assert saved and clean_script(saved["script"], 100) == "I lost a bet. Four cups waited. I lost again."
    long = " ".join(f"Sentence number {i} is here." for i in range(50))
    assert len(clean_script(long, 20).split()) <= 26  # trimmed near 130% of the target at a sentence end


def test_hashtags_cleaned():
    assert clean_hashtags(["Money Tips", "#money_tips", "#Shorts", "bad tag!"]) == "#MoneyTips #money_tips #Shorts #badtag"


def test_autopilot_plan_resolve():
    from datetime import datetime
    from app.services.autopilot import resolve
    now = datetime(2026, 11, 7, 10, 0)
    plan = [{"mode": "now", "at": None}, {"mode": "schedule", "at": "2026-11-07T18:00:00"},
            {"mode": "skip", "at": None}, {"mode": "schedule", "at": "2026-11-07T09:00:00"}]
    # row 4's time passed while processing -> post now instead of failing
    assert resolve(plan, now) == [None, datetime(2026, 11, 7, 18, 0), "skip", None]


def test_dpapi_roundtrip():
    data = b'{"refresh_token": "x"}'
    enc = secure.encrypt(data)
    assert secure.decrypt(enc) == data


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print("ok ", t.__name__)
    print(f"{len(tests)} passed")
