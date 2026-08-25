"""
Step 4: run retrieval over every Case and MEASURE it.

No API calls -- this is free to run. The point is not to look at the output
and decide it seems fine, but to count how often it is right, using the
_eval_ground_truth block we put in the mock data in Step 3.

Run it:
    source .venv/bin/activate
    python src/step4_retrieval.py
"""

import data_store
import retrieval


def show_results_per_case() -> None:
    """For each case: what came back, what should have, and did it match."""
    cases = data_store.list_cases()
    articles = data_store.list_articles()
    truth = data_store.ground_truth()

    print("=" * 78)
    print("RETRIEVAL, CASE BY CASE")
    print("=" * 78)

    hits = 0
    scored_cases = 0

    for case in cases:
        number = case["CaseNumber"]
        expected = truth[number]

        # min_score=0 so we see the raw ranking including weak matches --
        # we want to know what the threshold is filtering out.
        results = retrieval.search_for_case(case, articles, top_k=3, min_score=0.0)

        print()
        print(f"Case {number}: {case['Subject'][:58]}")
        for article, score in results:
            print(f"    {score:6.1f}  {article['ArticleNumber']}  {article['Title'][:48]}")

        top_number = results[0][0]["ArticleNumber"] if results else None
        top_score = results[0][1] if results else 0.0

        if expected:
            scored_cases += 1
            correct = top_number == expected[0]
            hits += correct
            verdict = "HIT " if correct else "MISS"
            print(f"    -> expected {expected[0]}, got {top_number}  [{verdict}]")
        else:
            # No article should match. Success here means the top score is low
            # enough that our threshold will reject it.
            print(f"    -> expected NOTHING, best score was {top_score:.1f}")

    print()
    print(f"Top-1 accuracy on answerable cases: {hits}/{scored_cases}")


def tune_threshold() -> None:
    """Pick MIN_SCORE from evidence instead of guessing at it.

    The threshold has to do two jobs at once: keep the correct article for
    cases that have one, and reject everything for case 00001051, which has
    no answer. This sweep shows which values manage both.
    """
    cases = data_store.list_cases()
    articles = data_store.list_articles()
    truth = data_store.ground_truth()

    # Collect the top hit for every case once, then test thresholds against it.
    tops = {}
    for case in cases:
        results = retrieval.search_for_case(case, articles, top_k=1, min_score=0.0)
        tops[case["CaseNumber"]] = results[0] if results else (None, 0.0)

    print()
    print("=" * 78)
    print("THRESHOLD SWEEP")
    print("=" * 78)
    print(f"{'MIN_SCORE':>10}  {'correct':>8}  {'wrongly kept':>13}  {'wrongly dropped':>16}")

    for threshold in [0, 2, 4, 6, 8, 10, 12, 15, 20]:
        correct = 0
        wrongly_kept = 0     # returned an article for a case that has none
        wrongly_dropped = 0  # threshold killed a correct answer

        for number, (article, score) in tops.items():
            expected = truth[number]
            passes = score >= threshold

            if not expected:
                if passes:
                    wrongly_kept += 1
                else:
                    correct += 1
            else:
                if not passes:
                    wrongly_dropped += 1
                elif article and article["ArticleNumber"] == expected[0]:
                    correct += 1

        print(f"{threshold:>10}  {correct:>8}  {wrongly_kept:>13}  {wrongly_dropped:>16}")

    print()
    print(f"retrieval.MIN_SCORE is currently {retrieval.MIN_SCORE}")


if __name__ == "__main__":
    show_results_per_case()
    tune_threshold()
