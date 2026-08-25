"""
Step 3: prove the mock data loads and see what we are working with.

No API calls here -- this step costs nothing to run. It just reads
data/sample_cases.json through data_store.py and prints a summary, so we know
the data is valid before Step 4 starts retrieving from it.

Run it:
    source .venv/bin/activate
    python src/step3_explore_data.py
"""

import data_store


def main() -> None:
    cases = data_store.list_cases()
    articles = data_store.list_articles()

    print("=" * 78)
    print(f"CASES ({len(cases)})")
    print("=" * 78)
    for case in cases:
        # :<10 and :<9 pad the columns so they line up.
        print(f"{case['CaseNumber']:<10} {case['Priority']:<9} {case['Subject']}")

    print()
    print("=" * 78)
    print(f"KNOWLEDGE ARTICLES ({len(articles)})")
    print("=" * 78)
    for article in articles:
        body_words = len(article["Answer__c"].split())
        print(f"{article['ArticleNumber']:<11} {article['Title']}")
        print(f"{'':<11} {body_words} words | {article['Summary'][:60]}...")

    # A quick sanity check on the test scaffolding: every case should appear in
    # the ground truth, and every article it points at should really exist.
    # Catching a typo here is much easier than debugging it in Step 4.
    print()
    print("=" * 78)
    print("GROUND TRUTH CHECK")
    print("=" * 78)

    truth = data_store.ground_truth()
    known_articles = {a["ArticleNumber"] for a in articles}
    problems = []

    for case in cases:
        number = case["CaseNumber"]
        if number not in truth:
            problems.append(f"Case {number} is missing from _eval_ground_truth")
            continue
        for expected in truth[number]:
            if expected not in known_articles:
                problems.append(f"Case {number} points at unknown article {expected}")

    if problems:
        for problem in problems:
            print(f"  PROBLEM: {problem}")
    else:
        unmatched = [n for n, arts in truth.items() if not arts]
        print(f"  All {len(cases)} cases mapped, all article numbers resolve.")
        print(f"  Deliberately unmatched (agent must say 'no article'): {unmatched}")


if __name__ == "__main__":
    main()
