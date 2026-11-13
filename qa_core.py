"""Independent oracle, certificates, generators and shrinkers for the QA suite.

Nothing in this module derives an expectation from production code: it never
imports canon, collector or samples.  Expectations come from three sources:

* brute-force blank-node bijection over folded quad sets (small inputs),
* explicit witness bijections re-checked directly against the quad sets,
* structural certificates (clique dichotomies) re-checkable by enumeration.

qa.py invokes the production entry points separately as the system under test.
"""
import itertools
import json


def wire(value):
    # Local compact-ASCII JSON encoding, used only to compare quad sets.
    # Deliberately re-implemented here instead of importing canon.wire.
    return json.dumps(value, ensure_ascii=True, separators=(',', ':'))


def blank_ids(quads):
    return sorted({t[1] for row in quads for t in row
                   if isinstance(t, list) and len(t) == 2 and t[0] == 'b'})


def norm_set(quads):
    """Fold duplicate rows and sort; isomorphism compares these sets."""
    return sorted({wire(row) for row in quads})


def apply_mapping(quads, mapping):
    out = []
    for row in quads:
        out.append([['b', mapping[t[1]]]
                    if isinstance(t, list) and len(t) == 2 and t[0] == 'b'
                    else t for t in row])
    return out


class Undetermined(Exception):
    """The independent oracle cannot decide this pair within its budget."""


def valid_quads(quads):
    """Contract-level input validity, re-implemented without production code.

    Shrunk cases must stay legal production inputs; otherwise a replay would
    exercise the validator instead of the dedup semantics.
    """
    if not isinstance(quads, list):
        return False
    blanks = set()
    for row in quads:
        if not isinstance(row, list) or len(row) != 4:
            return False
        for pos, term in enumerate(row):
            if pos == 3 and term is None:
                continue
            if (not isinstance(term, list) or len(term) != 2
                    or term[0] not in ('b', 'i', 'l')
                    or not isinstance(term[1], str)):
                return False
            kind, value = term
            if kind != 'l' and not value:
                return False
            if pos == 0 and kind == 'l' or pos == 1 and kind != 'i':
                return False
            if pos == 3 and kind == 'l':
                return False
            if kind == 'b':
                blanks.add(value)
    return len(blanks) <= 32


ORACLE_MAX_BLANKS = 8


def find_isomorphism(left, right, max_blanks=ORACLE_MAX_BLANKS):
    """Return a witnessing blank-id bijection, or None if none exists.

    Acts directly on the folded quad sets: every permutation of the right
    side's blank ids is tried and the relabelled left set must equal the
    right set exactly.  Raises Undetermined above the exhaustive budget.
    """
    ids_left, ids_right = blank_ids(left), blank_ids(right)
    if len(ids_left) != len(ids_right):
        return None
    if len(ids_left) > max_blanks:
        raise Undetermined('%d blank ids exceed oracle budget %d'
                           % (len(ids_left), max_blanks))
    target = norm_set(right)
    for perm in itertools.permutations(ids_right):
        if norm_set(apply_mapping(left, dict(zip(ids_left, perm)))) == target:
            return dict(zip(ids_left, perm))
    return None


def oracle_verdict(left, right, max_blanks=ORACLE_MAX_BLANKS):
    """('isomorphic'|'non-isomorphic'|'undetermined', witness-or-None)."""
    try:
        witness = find_isomorphism(left, right, max_blanks)
    except Undetermined:
        return 'undetermined', None
    return ('isomorphic' if witness is not None else 'non-isomorphic'), witness


def check_labels(quads, result):
    """Validate a canonicalize() result's witness labels against its input."""
    problems = []
    ids = blank_ids(quads)
    labels = result.get('labels') if isinstance(result, dict) else None
    if not isinstance(labels, dict) or set(labels) != set(ids):
        problems.append('labels do not mention exactly the input blank ids')
        return problems
    if sorted(labels.values()) != list(range(len(ids))):
        problems.append('labels are not a bijection onto 0..n-1')
        return problems
    try:
        coded = json.loads(result['code'])
    except (ValueError, KeyError, TypeError):
        problems.append('code is not parseable JSON')
        return problems
    if norm_set(apply_mapping(quads, labels)) != norm_set(coded):
        problems.append('relabeling the input by labels does not reproduce '
                        'the code quad set')
    return problems


def clique_witnesses(quads, size, predicate, graph_mode='self'):
    """All `size`-subsets of blank ids pairwise joined by relationship quads.

    With graph_mode='self' a row [subject, [i, predicate], object, subject]
    counts as an edge (the samples.symmetric_exports shape); with
    graph_mode='default' the row's graph must be None.  A clique needs every
    ordered pair of distinct members covered.  Pure set lookups over the
    input quads; no production code involved.
    """
    edges = set()
    for row in quads:
        subject, pred, obj, graph = row
        if not (isinstance(subject, list) and subject[0] == 'b'
                and pred == ['i', predicate]
                and isinstance(obj, list) and obj[0] == 'b'):
            continue
        if graph_mode == 'self' and not (isinstance(graph, list)
                                         and graph[0] == 'b'
                                         and graph[1] == subject[1]):
            continue
        if graph_mode == 'default' and graph is not None:
            continue
        edges.add((subject[1], obj[1]))
    found = []
    for combo in itertools.combinations(blank_ids(quads), size):
        if all((u, v) in edges for u in combo for v in combo if u != v):
            found.append([str(v) for v in combo])
    return found


# --- Exhaustive finite domain: 3 blank ids, one IRI predicate, default graph.

DOMAIN_IDS = ['b0', 'b1', 'b2']
DOMAIN_PREDICATE = 'urn:qa:p'
DOMAIN_POSITIONS = [(s, o) for s in DOMAIN_IDS for o in DOMAIN_IDS]
DOMAIN_MASKS = range(1 << len(DOMAIN_POSITIONS))


def domain_quads(mask):
    return [[['b', s], ['i', DOMAIN_PREDICATE], ['b', o], None]
            for bit, (s, o) in enumerate(DOMAIN_POSITIONS) if mask >> bit & 1]


def domain_permutations():
    return [dict(zip(DOMAIN_IDS, p)) for p in itertools.permutations(DOMAIN_IDS)]


# --- Random differential generator -------------------------------------

def random_quads(rng, blanks, max_quads=9):
    ids = ['n%d' % i for i in range(blanks)]
    iris = ['urn:qa:a', 'urn:qa:b', 'urn:qa:c']
    literals = ['lit-x', '007', '']
    quads = []
    for _ in range(rng.randint(1, max_quads)):
        subject = (['b', rng.choice(ids)] if rng.random() < 0.75
                   else ['i', rng.choice(iris)])
        predicate = ['i', rng.choice(iris)]
        roll = rng.random()
        if roll < 0.5:
            obj = ['b', rng.choice(ids)]
        elif roll < 0.8:
            obj = ['l', rng.choice(literals)]
        else:
            obj = ['i', rng.choice(iris)]
        graph = rng.choice([None, None,
                            ['i', rng.choice(iris)],
                            ['b', rng.choice(ids)]])
        quads.append([subject, predicate, obj, graph])
    return quads


def random_isomorphic(rng, quads):
    """Rename blanks to fresh ids, shuffle rows, maybe duplicate one row."""
    ids = blank_ids(quads)
    fresh = ['r%d' % i for i in range(len(ids))]
    rng.shuffle(fresh)
    mapping = dict(zip(ids, fresh))
    out = apply_mapping(quads, mapping)
    rng.shuffle(out)
    if out and rng.random() < 0.5:
        out = out + [list(out[0])]
    return out, mapping


# --- Mismatch shrinker ---------------------------------------------------

def shrink_mismatch(left, right, expect_iso, actual_iso):
    """Shrink a judgment mismatch to a 1-minimal, replayable case.

    expect_iso: the independent oracle verdict (bool) that must be preserved.
    actual_iso: callable(left, right) -> bool|None, the system-under-test
    merge verdict (None means it could not answer, e.g. budget exhausted).
    Returns (left, right, log) with the minimality re-check recorded.
    """
    def holds(pair_left, pair_right):
        if not (valid_quads(pair_left) and valid_quads(pair_right)):
            return False
        verdict, _ = oracle_verdict(pair_left, pair_right)
        if verdict == 'undetermined':
            return False
        actual = actual_iso(pair_left, pair_right)
        return (actual is not None and (verdict == 'isomorphic') == expect_iso
                and actual != expect_iso)

    log = []

    def removal_pass(pair_left, pair_right):
        for side in (0, 1):
            quads = pair_left if side == 0 else pair_right
            for index in range(len(quads)):
                cand = quads[:index] + quads[index + 1:]
                pair = (cand, pair_right) if side == 0 else (pair_left, cand)
                if holds(*pair):
                    log.append({'action': 'drop-quad', 'side': side,
                                'index': index})
                    return pair[0], pair[1], True
        return pair_left, pair_right, False

    def strings_of(quads):
        return {(t[0], t[1]) for row in quads for t in row
                if isinstance(t, list) and len(t) == 2}

    pool = ['', 'a', 'b', 'c', 'd', 'p', 'q', 'x']

    def string_pass(pair_left, pair_right):
        for kind, value in sorted(strings_of(pair_left)
                                  | strings_of(pair_right)):
            for text in pool:
                if len(text) >= len(value):
                    continue
                if kind == 'b' and (text in blank_ids(pair_left)
                                    or text in blank_ids(pair_right)):
                    continue

                def repl(quads):
                    return [[[t[0], text]
                             if isinstance(t, list) and len(t) == 2
                             and t[0] == kind and t[1] == value else t
                             for t in row] for row in quads]

                if holds(repl(pair_left), repl(pair_right)):
                    log.append({'action': 'shrink-string', 'kind': kind,
                                'from': value, 'to': text})
                    return repl(pair_left), repl(pair_right), True
        return pair_left, pair_right, False

    changed = True
    while changed:  # alternate removals and string shrinking to a fixpoint
        left, right, removed = removal_pass(left, right)
        left, right, shrunk = string_pass(left, right)
        changed = removed or shrunk

    checks = []  # prove 1-minimality: no single removal keeps the mismatch
    for side in (0, 1):
        quads = left if side == 0 else right
        for index in range(len(quads)):
            cand = quads[:index] + quads[index + 1:]
            pair = (cand, right) if side == 0 else (left, cand)
            checks.append({'side': side, 'removed_index': index,
                           'mismatch_preserved': holds(*pair)})
    log.append({'action': 'minimality-check',
                'removals_still_mismatching':
                sum(1 for c in checks if c['mismatch_preserved']),
                'removals_checked': len(checks),
                'checks': checks})
    return left, right, log
