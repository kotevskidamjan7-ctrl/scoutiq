"""Rule-based request parser: free, offline, English and Macedonian (FR-15).

It recognises the phrasings a scout typically uses: positions (with counts), age limits, prices and
budgets, leagues, nationalities, "still playing", and a formation. Anything it does not recognise is
simply not turned into a filter; the page shows what was understood so the user can check it.
"""

import re
import unicodedata

from app.assistant.filters import AssistantFilters

# ---------- vocabulary ----------
ROLE_WORDS = {
    "GK": ["goalkeeper", "goal keeper", "keeper", "goalie", "gk", "голман", "голмани", "golman", "чувар на мрежа"],
    "CB": ["centre-back", "center-back", "centre back", "center back", "centreback", "centerback", "central defender",
           "centre-half", "center-half", "cb", "stopper", "штопер", "stoper", "централен бек", "центархалф", "штоперот"],
    "FB": ["full-back", "fullback", "full back", "left-back", "right-back", "left back", "right back", "leftback",
           "rightback", "wing-back", "wingback", "wing back", "lb", "rb", "lwb", "rwb", "лев бек", "десен бек", "бек",
           "бекови", "krilen bek", "bek"],
    "CM": ["central midfielder", "defensive midfielder", "attacking midfielder", "holding midfielder", "midfielder",
           "midfield", "playmaker", "cm", "cdm", "dm", "cam", "number 6", "number 8", "number 10", "везист", "везисти",
           "среден ред", "плејмејкер", "vezist", "srednji red"],
    "AW": ["left winger", "right winger", "winger", "wide player", "wide forward", "wide attacker", "lw", "rw",
           "крило", "крила", "крилен напаѓач", "krilo"],
    "ST": ["centre-forward", "center-forward", "centre forward", "center forward", "striker", "forward", "cf", "st",
           "number 9", "target man", "нападач", "нападачи", "шпиц", "центарфор", "napadac", "napagjac"],
}
GROUP_WORDS = {  # words that mean more than one position
    ("CB", "FB"): ["defender", "defenders", "одбранбен", "одбрана", "дефанзивец", "branitel"],
    ("AW", "ST"): ["attacker", "attackers", "напаѓач", "напаѓачи"],
}
NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "pair of": 2, "couple of": 2,
                "еден": 1, "една": 1, "два": 2, "две": 2, "три": 3, "четири": 4, "пет": 5}

# (codes, words): league names always mean the league; countries mean the league they host
LEAGUE_WORDS = [
    ("GB1", ["premier league", "epl", "english league", "england", "англија", "премиер лига"]),
    ("ES1", ["la liga", "laliga", "spanish league", "spain", "шпанија", "шпанска лига"]),
    ("IT1", ["serie a", "italian league", "italy", "италија", "италијанска лига"]),
    ("L1", ["german bundesliga", "bundesliga", "german league", "germany", "германија", "бундеслига"]),
    ("FR1", ["ligue 1", "french league", "france", "франција", "француска лига"]),
    ("PO1", ["primeira liga", "liga portugal", "portuguese league", "portugal", "португалија"]),
    ("NL1", ["eredivisie", "dutch league", "netherlands", "holland", "холандија"]),
    ("BE1", ["pro league", "jupiler", "belgian league", "belgium", "белгија"]),
    ("TR1", ["super lig", "süper lig", "turkish league", "turkey", "türkiye", "турција"]),
    ("A1", ["austrian bundesliga", "austria", "австрија"]),
    ("C1", ["swiss super league", "switzerland", "швајцарија"]),
    ("PL1", ["ekstraklasa", "poland", "полска"]),
    ("KR1", ["hnl", "croatian league", "croatia", "хрватска"]),
    ("SER1", ["serbian superliga", "serbian league", "serbia", "србија"]),
]
NATIONALITY_WORDS = {  # adjective / country -> Transfermarkt country name
    "North Macedonia": ["macedonian", "north macedonian", "north macedonia", "macedonia", "македонец", "македонски",
                        "македонија", "makedonec"],
    "Spain": ["spanish", "шпанец"], "England": ["english", "англичанец"], "Italy": ["italian", "италијанец"],
    "Germany": ["german", "германец"], "France": ["french", "французин"], "Portugal": ["portuguese", "португалец"],
    "Netherlands": ["dutch", "холанѓанец"], "Belgium": ["belgian", "белгиец"], "Türkiye": ["turkish", "турчин"],
    "Croatia": ["croatian", "хрват"], "Serbia": ["serbian", "србин"], "Albania": ["albanian", "albania", "албанец", "албанија"],
    "Bosnia-Herzegovina": ["bosnian", "bosnia", "босанец", "босна"], "Slovenia": ["slovenian", "slovenia", "словенец"],
    "Montenegro": ["montenegrin", "montenegro", "црногорец", "црна гора"], "Kosovo": ["kosovan", "kosovo", "косово"],
    "Bulgaria": ["bulgarian", "bulgaria", "бугарин", "бугарија"], "Greece": ["greek", "greece", "грк", "грција"],
    "Brazil": ["brazilian", "brazil", "бразилец", "бразил"], "Argentina": ["argentine", "argentinian", "argentina", "аргентинец"],
    "Austria": ["austrian"], "Switzerland": ["swiss"], "Poland": ["polish"], "Denmark": ["danish", "denmark"],
    "Norway": ["norwegian", "norway"], "Sweden": ["swedish", "sweden"], "Scotland": ["scottish", "scotland"],
    "Morocco": ["moroccan", "morocco"], "Senegal": ["senegalese", "senegal"], "Nigeria": ["nigerian", "nigeria"],
    "Japan": ["japanese", "japan"], "Uruguay": ["uruguayan", "uruguay"], "Colombia": ["colombian", "colombia"],
}
STILL_PLAYING = ["still playing", "plays regularly", "playing regularly", "regular starter", "regular", "active",
                 "first-team", "first team", "игра редовно", "редовен", "активен", "redovno"]
LOW_MINUTES = ["fringe", "few minutes", "less reliable", "include rotation", "малку минути"]
YOUNG = ["young", "youngster", "talent", "prospect", "млад", "млада", "младо", "млади", "талент", "mlad"]
OLD = ["experienced", "veteran", "искусен", "искусна", "искусно", "искусни", "ветеран", "iskusen"]
CHEAP = ["cheap", "bargain", "low cost", "евтин", "евтина", "евтино", "евтини", "evtin"]
BUDGET_CONTEXT = ["budget", "total", "in total", "буџет", "вкупно", "budzet"]
PRICE_CONTEXT = ["under", "below", "less than", "max", "maximum", "up to", "at most", "for", "cheaper than", "до",
                 "под", "максимум", "помалку од", "најмногу"]
YOUNG_AGE, OLD_AGE, CHEAP_PRICE = 23, 29, 2_000_000

# word boundary that works for Cyrillic too
B = r"(?<![\w-])"
E = r"(?![\w-])"


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).lower()
    t = t.replace("’", "'").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", t).strip()


def _find(words: list[str], text: str) -> list[tuple[int, int, str]]:
    """Matches of any of the words, longest first; a shorter word inside a longer match is not counted again."""
    hits: list[tuple[int, int, str]] = []
    for w in sorted(words, key=len, reverse=True):
        for m in re.finditer(B + re.escape(w) + r"(?:s|es|и)?" + E, text):
            if not any(m.start() < e and s < m.end() for s, e, _ in hits):
                hits.append((m.start(), m.end(), w))
    return sorted(hits)


def _count_before(before: str) -> int | None:
    """The number right before a position word: '2 strikers', 'two strikers', 'a pair of strikers'."""
    tokens = before.split()[-3:]
    for i in range(len(tokens) - 1, -1, -1):
        tok = tokens[i]
        if i > 0 and f"{tokens[i - 1]} {tok}" in NUMBER_WORDS:
            return NUMBER_WORDS[f"{tokens[i - 1]} {tok}"]
        if tok.isdigit() and 1 <= int(tok) <= 11:
            return int(tok)
        if tok in NUMBER_WORDS:
            return NUMBER_WORDS[tok]
        if tok not in ("young", "good", "new", "quality", "strong", "fast", "left", "right", "central", "млад", "добар",
                       "нов", "брз", "of", "experienced", "cheap", "creative"):
            return None  # another word in between: the number belongs to something else
    return None


def _take(text: str, start: int, end: int) -> str:
    """Blank out a matched span so it is not read twice (e.g. 'bundesliga' after 'austrian bundesliga')."""
    return text[:start] + " " * (end - start) + text[end:]


MONEY = re.compile(B + r"(?:€|eur|euro)?\s*(\d+(?:[.,]\d+)?)\s*(m|mil|mln|million|millions|милион[и]?|мил|м|k|thousand|илјади|к)"
                   r"(?:\s*(?:€|eur|euros?|евра))?" + E
                   + r"|" + B + r"(?:€|eur)\s*(\d[\d,.]*)" + E
                   + r"|" + B + r"(\d[\d,.]*)\s*(?:€|eur|euros|евра)" + E)


def _money_value(m: re.Match) -> int | None:
    if m.group(1):
        n = float(m.group(1).replace(",", "."))
        unit = m.group(2)
        mult = 1_000 if unit in ("k", "thousand", "илјади", "к") else 1_000_000
        return int(round(n * mult))
    raw = m.group(3) or m.group(4)
    digits = re.sub(r"[,.](?=\d{3}\b)", "", raw)
    try:
        v = float(digits.replace(",", "."))
    except ValueError:
        return None
    return int(v) if v >= 10_000 else None  # "€5" alone is not a football price


def parse(text: str, bare_amount: str = "price") -> tuple[AssistantFilters, list[str]]:
    """Return the filters and the parts of the text that were used (for display).

    bare_amount: how to read an amount with no word around it ("25m"): "price" (most for one player,
    the Players page) or "budget" (the squad builder and club improvement, where it is the money to spend).
    """
    t = _norm(text)
    used: list[str] = []
    f: dict = {}

    # formation
    m = re.search(r"\b([345])-([1-5])-([1-5])(?:-([1-5]))?\b", t)
    if m and m.group(0) in ("4-3-3", "4-2-3-1", "4-4-2", "3-5-2", "3-4-3"):
        f["formation"] = m.group(0)
        used.append(m.group(0))
        t = _take(t, m.start(), m.end())

    # money (before ages, so "2m" is never read as an age)
    for m in list(MONEY.finditer(t)):
        value = _money_value(m)
        if not value or value > 2_000_000_000:
            continue  # not a football amount
        before = t[max(0, m.start() - 25): m.start()]
        is_budget = any(re.search(B + re.escape(w) + E, before) for w in BUDGET_CONTEXT)
        is_price = any(re.search(B + re.escape(w) + E, before) for w in PRICE_CONTEXT)
        if is_budget or (not is_price and (bare_amount == "budget" or any(re.search(B + w + E, t) for w in BUDGET_CONTEXT))):
            f["budget_eur"] = value
        else:
            f["max_price_eur"] = value
        used.append(m.group(0).strip())
        t = _take(t, m.start(), m.end())

    # ages
    no_num = r"(?!\s*\d)"  # "30 and under" is an upper limit only when no number follows ("30 and under 25")
    age_patterns = [
        # negations first: "not older than 24" is an upper limit, never a lower one
        (r"(?:not older than|no older than|not over|не постар\w* од)\s*(\d{2})(?:\s*(?:years|yrs|години|год))?", "max"),
        (r"(?:not younger than|no younger than|not under|не помлад\w* од)\s*(\d{2})(?:\s*(?:years|yrs|години|год))?", "min"),
        (r"between (\d{2}) and (\d{2})|од (\d{2}) до (\d{2})(?: години)?|(\d{2})\s*-\s*(\d{2}) (?:years|години)"
         r"|aged? (\d{2}) to (\d{2})|(\d{2}) to (\d{2}) (?:years|yrs)", "range"),
        (r"(\d{2})\s*(?:years old|year old|yo|години)?\s*(?:or younger|or under|and younger|and under|и помлад\w*)" + no_num, "max"),
        (r"(\d{2})\s*(?:years old|year old|yo|години)?\s*(?:or older|or over|and older|and over|и постар\w*)" + no_num, "min"),
        (r"(?:under|younger than|below|помлад\w* од|под)\s*(\d{2})(?:\s*(?:years|yrs|години|год))?", "max_excl"),
        (r"(?:up to|max(?:imum)?|at most|not older than|до|најмногу)\s*(\d{2})\s*(?:years|yrs|години|год)", "max"),
        (r"(?:age|aged|возраст)\s*(?:up to|under|max|до)?\s*(\d{2})", "max"),
        (r"(?:over|older than|above|постар\w* од|над)\s*(\d{2})(?:\s*(?:years|yrs|години|год))?", "min_excl"),
        (r"(?:at least|minimum|најмалку)\s*(\d{2})\s*(?:years|yrs|години|год)", "min"),
        (r"\bu-?(\d{2})\b", "max"),
    ]
    for pattern, kind in age_patterns:
        for m in list(re.finditer(pattern, t)):
            nums = [int(g) for g in m.groups() if g]
            if not nums or not all(15 <= n <= 45 for n in nums):
                continue
            if kind == "range":
                f["age_min"], f["age_max"] = min(nums), max(nums)
            elif kind == "max":
                f["age_max"] = nums[0]
            elif kind == "max_excl":
                f["age_max"] = nums[0] - 1
            elif kind == "min":
                f["age_min"] = nums[0]
            elif kind == "min_excl":
                f["age_min"] = nums[0] + 1
            used.append(m.group(0).strip())
            t = _take(t, m.start(), m.end())
    if "age_max" not in f and (hits := _find(YOUNG, t)):
        f["age_max"] = YOUNG_AGE
        used.append(hits[0][2])
    if "age_min" not in f and (hits := _find(OLD, t)):
        f["age_min"] = OLD_AGE
        used.append(hits[0][2])
    if "max_price_eur" not in f and (hits := _find(CHEAP, t)):
        f["max_price_eur"] = CHEAP_PRICE
        used.append(hits[0][2])

    # leagues (league names and "in/from <country>"), before positions: "bundesliga" is not a role
    leagues: list[str] = []
    for code, words in LEAGUE_WORDS:
        for start, end, w in _find(words, t):
            leagues.append(code)
            used.append(w)
            t = _take(t, start, end)
    f["leagues"] = list(dict.fromkeys(leagues))

    # nationalities (adjectives, or countries without a league in the app)
    nats = []
    for country, words in NATIONALITY_WORDS.items():
        for start, end, w in _find(words, t):
            nats.append(country)
            used.append(w)
            t = _take(t, start, end)
    f["nationalities"] = list(dict.fromkeys(nats))

    # positions, with counts when a number comes right before them
    found: list[tuple[int, str, int | None, str]] = []
    original = t
    all_words = [(w, role) for role, words in ROLE_WORDS.items() for w in words]
    for start, end, w in _find([w for w, _ in all_words], t):
        role = next(r for word, r in all_words if word == w)
        found.append((start, role, _count_before(original[:start]), w))
        t = _take(t, start, end)
    for roles, words in GROUP_WORDS.items():
        for start, end, w in _find(words, t):
            for r in roles:
                found.append((start, r, None, w))
            t = _take(t, start, end)
    found.sort()
    f["roles"] = list(dict.fromkeys(r for _, r, _, _ in found))
    explicit = [x for x in found if x[2] is not None and x[2] != 1]
    if explicit or sum(1 for x in found if x[2] is not None) >= 2:
        counts: dict[str, int] = {}
        for _, r, n, _ in found:
            counts[r] = counts.get(r, 0) + (n or 1)
        f["role_counts"] = counts
    used += [w for _, _, _, w in found]

    if _find(STILL_PLAYING, t):
        f["still_playing"] = True
        used.append(_find(STILL_PLAYING, t)[0][2])
    if _find(LOW_MINUTES, t):
        f["include_low_minutes"] = True
        used.append(_find(LOW_MINUTES, t)[0][2])

    if f.get("age_min") and f.get("age_max") and f["age_min"] > f["age_max"]:
        f.pop("age_min")  # contradictory: keep the upper limit, which scouts state more often
    if f.get("max_price_eur", 0) > 500_000_000:
        f.pop("max_price_eur")  # more than any player has ever cost: not a usable price limit
    return AssistantFilters(**f), list(dict.fromkeys(used))
