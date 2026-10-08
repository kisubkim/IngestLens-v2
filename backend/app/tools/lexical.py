"""BM25 over a run's chunks: the lexical half of hybrid search.

Korean has no spaces between morphemes, so Hangul runs are indexed as character bigrams;
Latin words and numbers stay whole. No tokenizer model is needed, which keeps offline deployment simple.
"""

import math
import re
from collections import Counter, OrderedDict

_TOKEN = re.compile(r"[a-z0-9_]+|[가-힣]+")


def tokenize(text: str) -> list[str]:
    out: list[str] = []
    for m in _TOKEN.finditer(text.lower()):
        w = m.group(0)
        if "가" <= w[0] <= "힣" and len(w) > 1:
            out.extend(w[i:i + 2] for i in range(len(w) - 1))
        else:
            out.append(w)
    return out


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.tfs = [Counter(tokenize(d)) for d in docs]
        self.lens = [sum(tf.values()) for tf in self.tfs]
        self.avg = (sum(self.lens) / len(self.lens)) if self.lens else 0.0
        df: Counter = Counter()
        for tf in self.tfs:
            df.update(tf.keys())
        n = len(docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def scores(self, query: str) -> list[float]:
        q = set(tokenize(query))
        out = []
        for tf, ln in zip(self.tfs, self.lens):
            s = 0.0
            norm = self.k1 * (1 - self.b + self.b * ln / (self.avg or 1.0))
            for t in q:
                f = tf.get(t)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + norm)
            out.append(s)
        return out


_cache: "OrderedDict[str, tuple[BM25, list[str]]]" = OrderedDict()


def forget(run_id: str) -> None:
    _cache.pop(run_id, None)


def forget_all() -> None:
    _cache.clear()


def index_for(run_id: str, chunks: list[tuple[str, str]]) -> tuple[BM25, list[str]]:
    """chunks: (chunk_id, text). Cached per run; chunks of a finished run never change."""
    if run_id in _cache:
        _cache.move_to_end(run_id)
        return _cache[run_id]
    idx = (BM25([t for _, t in chunks]), [cid for cid, _ in chunks])
    _cache[run_id] = idx
    while len(_cache) > 8:
        _cache.popitem(last=False)
    return idx
