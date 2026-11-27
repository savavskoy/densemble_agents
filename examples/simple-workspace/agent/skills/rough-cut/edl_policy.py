"""Shared EDL timing. Every timing number used by the rough cut lives here."""

# Join kept phrases into one clip when the gap between them is shorter than this.
# The original silence stays inside the clip.
PHRASE_JOIN_GAP = 0.24

# Between two clips, keep this much of the original pause (a retake boundary
# that is not the end of a sentence and is not a long pause).
MIN_GAP_BETWEEN_CLIPS = 0.25
# After a phrase that ends with . ? ! or …, keep a slightly longer breath.
PAUSE_AFTER_SENTENCE = 0.30
# A clip boundary inside a sentence keeps a shorter breath.
PAUSE_INSIDE_SENTENCE = 0.15
# A pause longer than this is compressed instead of kept whole.
PAUSE_LONG = 1.0
PAUSE_LONG_KEEP = 0.35

# Sentence splitter. A pause this long starts a new sentence even without punctuation.
SENTENCE_PAUSE = 0.7
# With HOLD_TIGHT_PUNCTUATION on, a word that ends with .?!… does not split the
# sentence when the next word starts sooner than PUNCT_HOLD_PAUSE. Off by default:
# a fast speaker leaves almost no gap after a period, and holding glued whole
# paragraphs into one "sentence" that no duplicate detector can look inside.
PUNCT_HOLD_PAUSE = 0.25
HOLD_TIGHT_PUNCTUATION = False

# Silence inside a word is removed only when the word is longer than this.
LONG_WORD = 1.5
# ffmpeg silencedetect. Snap looks for an edge of such a silence.
SILENCE_NOISE_DB = -35
SILENCE_MIN = 0.3
# Silence left on the leading edge when a long word is split.
KEEP_SILENCE = 0.3
# Speech islands shorter than this, inside a long word, are dropped as noise.
MIN_ISLAND = 0.15
# A cut may move onto a silence edge at most this far from the word time,
# and only outward so the word itself is not trimmed.
SNAP_WINDOW = 0.1

SENTENCE_ENDINGS = (".", "?", "!", "…", "...")


def phrase_bounds(phrase):
    words = phrase.get("words") or []
    if words:
        return float(words[0]["start"]), float(words[-1]["end"])
    return float(phrase["start"]), float(phrase["end"])


def text_ends_sentence(text):
    core = (text or "").strip().rstrip("\"'»”)]")
    return core.endswith(SENTENCE_ENDINGS)


def pause_to_keep(gap, *, sentence_end, hard_cut=False):
    """Seconds of the original gap that stay attached to the earlier clip.

    The kept audio is the real pause, not a synthetic one. A gap of zero stays
    zero. A gap longer than PAUSE_LONG is compressed to PAUSE_LONG_KEEP.
    """
    gap = float(gap)
    if gap <= 0:
        return 0.0
    if gap > PAUSE_LONG:
        return PAUSE_LONG_KEEP
    if sentence_end:
        return min(gap, PAUSE_AFTER_SENTENCE)
    if hard_cut:
        return min(gap, MIN_GAP_BETWEEN_CLIPS)
    return min(gap, PAUSE_INSIDE_SENTENCE)


def final_bounds(speech, sentence_end, hard_in, media_end, bridge_after=None, ceilings=None):
    """Turn speech ranges into source in/out points that keep a real pause.

    speech, sentence_end and hard_in are parallel sequences. hard_in[i] is true
    when clip i begins on a retake cut. The pause is attached to the earlier
    clip and never crosses the next word. bridge_after[i] False means the gap
    after clip i was a deleted word and must not be filled back in.
    ceilings[i] is where the next transcript word starts, cut or kept. The next
    kept clip can be far away; a cut word right after clip i must not be played.
    """
    bounds = []
    for index, (start, end) in enumerate(speech):
        start = float(start)
        end = float(end)
        if index + 1 < len(speech):
            next_start = float(speech[index + 1][0])
            gap = next_start - end
            if bridge_after is not None and not bridge_after[index]:
                keep = 0.0
            else:
                keep = pause_to_keep(
                    gap,
                    sentence_end=bool(sentence_end[index]),
                    hard_cut=bool(hard_in[index + 1]),
                )
            end = min(next_start, end + keep)
            if ceilings is not None:
                end = min(end, max(float(ceilings[index]), float(speech[index][1])))
        else:
            gap = float(media_end) - end
            keep = pause_to_keep(gap, sentence_end=bool(sentence_end[index]), hard_cut=False)
            end = min(float(media_end), end + keep)
            if ceilings is not None:
                end = min(end, max(float(ceilings[index]), float(speech[index][1])))
        if bounds:
            start = max(start, bounds[-1][1])
        start = max(0.0, start)
        if end < start:
            end = start
        bounds.append((start, end))
    return bounds


def snap_edge(moment, silences, side, window=SNAP_WINDOW):
    """Move a cut onto a nearby silence edge, outward from the word only.

    side "end" may move later (into silence after the word). side "start" may
    move earlier (into silence before the word). An edge farther than `window`
    is ignored. Nothing in this function pulls the cut into the word.
    """
    moment = float(moment)
    edges = []
    for span in silences:
        if span.start - window <= moment <= span.end + window:
            edges.extend((float(span.start), float(span.end)))
        if span.start <= moment <= span.end:
            edges.append(moment)
    near = [edge for edge in edges if abs(edge - moment) <= window + 1e-9]
    if not near:
        return moment
    if side == "end":
        forward = [edge for edge in near if edge >= moment - 1e-9]
        if not forward:
            return moment
        return min(forward, key=lambda edge: (edge - moment, edge))
    backward = [edge for edge in near if edge <= moment + 1e-9]
    if not backward:
        return moment
    return max(backward)


def words_in_span(phrase, start, end):
    """Words whose midpoint lies in the kept span. Empty if the phrase has no word times."""
    chosen = []
    for word in phrase.get("words") or []:
        ws, we = float(word["start"]), float(word["end"])
        mid = (ws + we) / 2
        if start - 0.01 <= mid <= end + 0.01:
            chosen.append(word)
    return chosen


def text_in_span(phrase, start, end):
    words = words_in_span(phrase, start, end)
    if words:
        return " ".join(part for part in ((word.get("word") or "").strip() for word in words) if part)
    if phrase.get("words"):
        return ""
    return (phrase.get("text") or "").strip()
