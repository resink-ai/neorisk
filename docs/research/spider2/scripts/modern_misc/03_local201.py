"""local201: first 10 words (alphabetical) of length 4-5 starting with 'r' that have >= 1 anagram
of the same length (case-sensitive); count of anagrams per word. Gold CSVs _a and _b, no gold SQL.

Run: python3 -I docs/research/spider2/scripts/modern_misc/03_local201.py
"""
import csv
import sqlite3
from collections import Counter, defaultdict

con = sqlite3.connect("file:data/spider2/modern_data.sqlite?mode=ro", uri=True)
raw = [r[0] for r in con.execute("SELECT words FROM word_list") if r[0] is not None]
G = "docs/research/spider2/scripts/modern_misc/gold/"


def gold(name):
    with open(G + name) as f:
        rows = list(csv.reader(f))[1:]
    return [(w, int(c)) for w, c in rows]


def reading(words, count_rows):
    """Anagram groups over `words`; a word's count = members of its group other than itself.
    count_rows=True counts rows (a duplicated row of the same word counts as an anagram);
    False counts distinct other words."""
    groups = defaultdict(list)
    for w in words:
        if 4 <= len(w) <= 5:
            groups["".join(sorted(w))].append(w)
    out = {}
    for w in set(words):
        if 4 <= len(w) <= 5 and w.startswith("r"):
            g = groups["".join(sorted(w))]
            if count_rows:
                n = len(g) - 1  # all rows of the group minus one copy of w
            else:
                n = len(set(g)) - 1
            if n >= 1:
                out[w] = n
    return sorted(out.items())[:10]


ga, gb = gold("local201_a.csv"), gold("local201_b.csv")
for label, words, cr in (
    ("R1 distinct words, distinct anagrams", list(set(raw)), False),
    ("R2 raw rows, distinct anagrams", raw, False),
    ("R3 raw rows, count rows (duplicates count as anagrams)", raw, True),
):
    res = reading(words, cr)
    print(label, res, "== _a" if res == ga else "", "== _b" if res == gb else "")

# _b hypothesis: self-joins over raw rows, word = other word allowed when rowids differ,
# i.e. pairs (w, w') with same letters, w' != row, counted per row of w; only words with count>=1.
cnt = Counter(raw)
dups = sorted(w for w, c in cnt.items() if c > 1 and 4 <= len(w) <= 5 and w.startswith("r"))
print("duplicated r-words of length 4-5 (first 10):", dups[:10])
print("_b words:", [w for w, _ in gb])
# check: does each _b word have a distinct-word anagram at all?
groups = defaultdict(set)
for w in set(raw):
    groups["".join(sorted(w))].add(w)
print("_b words with a true (other-word) anagram:", [w for w, _ in gb if len(groups["".join(sorted(w))]) > 1])
