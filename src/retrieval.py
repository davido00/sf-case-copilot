"""
Step 4: find the Knowledge Article(s) relevant to a Case.

This is the "R" in RAG -- Retrieval. Deliberately built with no machine
learning and no extra dependencies, because the naive version is easy to
follow and, on a corpus this size, works well enough to be worth measuring
before reaching for anything heavier.

The idea in one sentence: score every article by how many RARE words it shares
with the case, and return the best ones.
"""

import math
import re

# Words too common to carry meaning. If we didn't remove these, every article
# would score highly on "the", "and", "a" and the ranking would be noise.
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "can",
    "cannot", "do", "does", "for", "from", "has", "have", "how", "i", "if",
    "in", "is", "it", "its", "no", "not", "of", "on", "one", "or", "our",
    "out", "own", "same", "see", "so", "than", "that", "the", "their",
    "them", "then", "there", "these", "they", "this", "to", "up", "use",
    "used", "using", "was", "we", "were", "what", "when", "which", "who",
    "why", "will", "with", "would", "you", "your",
}


def tokenize(text: str) -> list[str]:
    """Break text into lowercase words, dropping punctuation and stopwords.

    Splitting on anything that is not a letter or digit matters more than it
    looks: it turns REQUEST_LIMIT_EXCEEDED into ["request", "limit",
    "exceeded"], so an error string in a case body can match prose in an
    article that never quotes the error verbatim.
    """
    words = re.split(r"[^a-z0-9]+", text.lower())
    return [w for w in words if w and w not in STOPWORDS and len(w) > 2]


def case_text(case: dict) -> str:
    """The part of a Case worth searching on."""
    return f"{case['Subject']} {case['Description']}"


def article_text(article: dict) -> str:
    """The part of an Article worth searching on."""
    return f"{article['Title']} {article['Summary']} {article['Answer__c']}"


def build_idf(articles: list[dict]) -> dict[str, float]:
    """Work out how RARE each word is across the whole set of articles.

    This is IDF -- inverse document frequency -- and it is the one idea that
    makes keyword search work at all.

    A word appearing in ALL 5 articles ("salesforce", "user", "check") tells
    you nothing about which article is the right one, so it scores 0. A word
    appearing in ONE article ("upsert", "bounce", "hierarchy") is a strong
    signal, so it scores high.

    Without this, matching is dominated by whichever words are most common.
    """
    total = len(articles)
    seen_in = {}
    for article in articles:
        # set() so a word repeated 20 times in one article still counts once.
        for word in set(tokenize(article_text(article))):
            seen_in[word] = seen_in.get(word, 0) + 1

    # log(total / count): count=1 -> log(5) = 1.61, count=5 -> log(1) = 0.
    return {word: math.log(total / count) for word, count in seen_in.items()}


# A word in the Title is a much stronger signal than the same word buried in
# the body, so title matches are worth more.
TITLE_WEIGHT = 3.0


def score_article(query_words: set[str], article: dict, idf: dict[str, float]) -> float:
    """How well does this article match these words? Higher is better."""
    body_words = set(tokenize(article_text(article)))
    title_words = set(tokenize(article["Title"] + " " + article["Summary"]))

    total = 0.0
    for word in query_words:
        if word in body_words:
            # .get(..., 0.0) because a word in the case might not appear in
            # any article at all, in which case it has no IDF entry.
            weight = idf.get(word, 0.0)
            if word in title_words:
                weight *= TITLE_WEIGHT
            total += weight
    return total


# Below this score, we treat the best match as "not actually relevant".
#
# Chosen from the threshold sweep in step4_retrieval.py, not guessed:
#   - the best FALSE match (case 00001051, which has no answer) scores 5.7
#   - the weakest TRUE match (case 00001048) scores 11.9
# So anything in (5.7, 11.9] scores a perfect 10/10. Picking 9.0 -- roughly
# the middle -- rather than 6.0 leaves margin on both sides instead of sitting
# 0.3 above a known false positive.
MIN_SCORE = 9.0


def search_articles(
    query: str,
    articles: list[dict],
    top_k: int = 3,
    min_score: float = MIN_SCORE,
) -> list[tuple[dict, float]]:
    """Return the best-matching articles for a piece of text, best first.

    Returns an EMPTY list when nothing clears `min_score`. That is the whole
    point of the threshold: a search engine with no cutoff always returns its
    least-bad guess, and in Step 5 the agent would then draft a confident
    reply from an irrelevant article. Returning nothing lets it say so.
    """
    idf = build_idf(articles)
    query_words = set(tokenize(query))

    scored = [(a, score_article(query_words, a, idf)) for a in articles]
    scored.sort(key=lambda pair: pair[1], reverse=True)

    return [(a, s) for a, s in scored[:top_k] if s >= min_score]


def search_for_case(case: dict, articles: list[dict], **kwargs) -> list[tuple[dict, float]]:
    """Convenience wrapper: search using a Case's own subject and description."""
    return search_articles(case_text(case), articles, **kwargs)
