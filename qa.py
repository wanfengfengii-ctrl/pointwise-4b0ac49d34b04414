"""QA gate for the anonymous-quad dedup pipeline (see CONTRACT.md).

Entries (argv list, same dispatch style as checks.py):
  python3 qa.py verify            re-run every check and rewrite evidence.json
  python3 qa.py replay CASE.json  replay one retained counterexample case
  python3 qa.py demo              landing comparison: shared vs split identity

verify exits non-zero when any semantic deviation is found (including a
retained counterexample that still reproduces) and always rewrites
evidence.json from the fresh run.  Budget exhaustion is recorded as
undetermined, never as an isomorphism verdict.
"""
import glob
import json
import os
import random
import subprocess
import sys
import time

import qa_core
import qa_mutants
import qa_stress

HERE = os.path.dirname(os.path.abspath(__file__))
EVIDENCE_PATH = os.path.join(HERE, 'evidence.json')
CASES_DIR = os.path.join(HERE, 'cases')
RANDOM_SEED = 20261113
RANDOM_TRIALS = 600

LIMITATIONS = [
    'the exhaustive classification covers only the finite domain of 3 blank '
    'ids, one IRI predicate and the default graph; multi-role inputs '
    '(literals, IRI/graph roles, >3 blanks) are covered by random and '
    'constructed cases, not exhaustively',
    'the brute-force bijection oracle is capped at 8 blank ids; larger '
    'isomorphism claims rest on explicit witness bijections, and larger '
    'non-isomorphism claims rest on specific structural certificates '
    '(K4-dichotomy), not on a general decision procedure',
    'stress runs whose search budget is exhausted are recorded as '
    'undetermined and support no (non-)isomorphism conclusion; resource '
    'curves measured on one structure family do not extrapolate to all '
    '32-blank inputs',
    'random differential coverage is bounded by the recorded seed and trial '
    'count; the shrinker demonstration runs against an intentional mutant, '
    'not against production',
    'mutants simulate four specific error classes; they cannot enumerate '
    'every possible implementation error',
    'wall-clock times and allocation peaks are machine-dependent and only '
    'indicate orders of magnitude',
]


# ---------------------------------------------------------------- helpers

def expected_landing(is_iso):
    return ({'kept': [0], 'duplicate_of': [[1, 0]]} if is_iso
            else {'kept': [0, 1], 'duplicate_of': []})


def production_merge(left, right):
    """System-under-test merge verdict; None when it cannot answer."""
    from canon import Invalid, SearchLimit, canonicalize
    try:
        return canonicalize(left)['code'] == canonicalize(right)['code']
    except (Invalid, SearchLimit):
        return None


def evaluate_case(case):
    """Independent judgment vs actual production behavior for one pair."""
    from canon import Invalid, SearchLimit, canonicalize
    from collector import collect
    from samples import page
    left, right = case['left'], case['right']
    verdict, witness = qa_core.oracle_verdict(left, right)
    actual = {}
    try:
        result_left = canonicalize(left)
        result_right = canonicalize(right)
        label_problems = (qa_core.check_labels(left, result_left)
                          + qa_core.check_labels(right, result_right))
        actual = {
            'codes_equal': result_left['code'] == result_right['code'],
            'label_problems': label_problems,
            'landing': collect([page(left), page(right)]),
        }
    except SearchLimit:
        actual = {'undetermined': 'production search budget exhausted'}
    except Invalid as error:
        actual = {'error': 'production rejected input: %s' % error}
    agrees = None
    if verdict != 'undetermined':
        if 'codes_equal' in actual:
            is_iso = verdict == 'isomorphic'
            agrees = (actual['codes_equal'] == is_iso
                      and not actual['label_problems']
                      and actual['landing'] == expected_landing(is_iso))
        elif 'error' in actual:
            agrees = False
    return {'independent': {'verdict': verdict, 'witness': witness},
            'actual': actual, 'agrees': agrees}


# ---------------------------------------------------------------- phases

def phase_retained():
    paths = sorted(glob.glob(os.path.join(CASES_DIR, '*.json')))
    results = []
    still_failing = []
    for path in paths:
        with open(path, encoding='utf-8') as handle:
            case = json.load(handle)
        outcome = evaluate_case(case)
        results.append({'case': os.path.basename(path),
                        'verdict': outcome['independent']['verdict'],
                        'agrees': outcome['agrees']})
        if outcome['agrees'] is not True:
            still_failing.append(os.path.basename(path))
    entry = {'id': 'retained-counterexamples', 'directory': 'cases/',
             'found': len(paths), 'results': results,
             'still_failing': still_failing,
             'result': 'pass' if not still_failing else 'fail'}
    failures = ['retained case %s still deviates' % name
                for name in still_failing]
    return entry, failures


def phase_validation():
    from canon import Invalid, canonicalize
    from collector import collect
    from samples import page
    checks = []

    def expect_invalid(fn, word, ident):
        try:
            fn()
        except Invalid as error:
            actual = str(error)
        except Exception as error:  # noqa: BLE001 - record any wrong type
            actual = 'wrong-exception:%s' % type(error).__name__
        else:
            actual = 'no-error'
        checks.append({'id': ident, 'expected': word, 'actual': actual,
                       'ok': actual == word})

    good = [[['b', 'x'], ['i', 'urn:qa:p'], ['l', 'ok'], None]]
    expect_invalid(lambda: canonicalize(good, limit=True), 'LIMIT',
                   'canon-limit-bool')
    expect_invalid(lambda: canonicalize(good, limit=0), 'LIMIT',
                   'canon-limit-zero')
    expect_invalid(lambda: canonicalize(good, limit='9'), 'LIMIT',
                   'canon-limit-string')
    expect_invalid(lambda: canonicalize('not-a-list'), 'QUADS',
                   'canon-quads-type')
    expect_invalid(lambda: canonicalize([(('b', 'x'), ['i', 'p'],
                                          ['i', 'o'], None)]),
                   'QUAD', 'canon-quad-row-tuple')
    expect_invalid(lambda: canonicalize([[['b', 'x'], ['i', 'p']]]),
                   'QUAD', 'canon-quad-length')
    expect_invalid(lambda: canonicalize([[['b', 'x'], 'p',
                                           ['i', 'o'], None]]),
                   'TERM', 'canon-term-shape')
    expect_invalid(lambda: canonicalize([[['b', 'x'], ['x', 'p'],
                                           ['i', 'o'], None]]),
                   'TERM', 'canon-term-kind')
    expect_invalid(lambda: canonicalize([[['b', 7], ['i', 'p'],
                                           ['i', 'o'], None]]),
                   'TERM', 'canon-term-value')
    expect_invalid(lambda: canonicalize([[['b', ''], ['i', 'p'],
                                           ['i', 'o'], None]]),
                   'EMPTY_ID', 'canon-empty-blank-id')
    expect_invalid(lambda: canonicalize([[['b', 'x'], ['i', ''],
                                           ['i', 'o'], None]]),
                   'EMPTY_ID', 'canon-empty-iri')
    expect_invalid(lambda: canonicalize([[['l', 'x'], ['i', 'p'],
                                           ['i', 'o'], None]]),
                   'ROLE', 'canon-role-literal-subject')
    expect_invalid(lambda: canonicalize([[['b', 'x'], ['b', 'p'],
                                           ['i', 'o'], None]]),
                   'ROLE', 'canon-role-blank-predicate')
    expect_invalid(lambda: canonicalize([[['b', 'x'], ['i', 'p'],
                                           ['i', 'o'], ['l', 'g']]]),
                   'ROLE', 'canon-role-literal-graph')
    expect_invalid(lambda: canonicalize(
        [[['b', 'n%d' % i], ['i', 'p'], ['i', 'o'], None]
         for i in range(33)]), 'BLANK_COUNT', 'canon-blank-count-33')
    expect_invalid(lambda: collect('not-a-list'), 'PAGES',
                   'collector-pages-type')
    expect_invalid(lambda: collect([7]), 'PAGE', 'collector-page-type')
    expect_invalid(lambda: collect(['<html></html>']), 'CAPTURE_SCRIPT',
                   'collector-script-missing')
    expect_invalid(lambda: collect([page([]) + page([])]),
                   'CAPTURE_SCRIPT', 'collector-script-duplicated')
    expect_invalid(lambda: collect(
        ['<html><script id="capture-graph">{broken</script></html>']),
        'CAPTURE_JSON', 'collector-json-broken')
    expect_invalid(lambda: collect(
        ['<html><script id="capture-graph">{"quads": NaN}</script></html>']),
        'CAPTURE_JSON', 'collector-json-nonstandard-constant')
    expect_invalid(lambda: collect(
        ['<html><script id="capture-graph">'
         '{"quads": [], "extra": 1}</script></html>']),
        'CAPTURE_JSON', 'collector-json-shape')
    positive_empty = canonicalize([])['code'] == '[]'
    checks.append({'id': 'canon-empty-ok', 'expected': True,
                   'actual': positive_empty, 'ok': positive_empty})
    landing_empty = collect([page([])]) == {'kept': [0], 'duplicate_of': []}
    checks.append({'id': 'collector-single-page-ok', 'expected': True,
                   'actual': landing_empty, 'ok': landing_empty})
    failures = ['validation %s: expected %r got %r'
                % (c['id'], c['expected'], c['actual'])
                for c in checks if not c['ok']]
    entry = {'id': 'contract-validation', 'checks': checks,
             'result': 'pass' if not failures else 'fail'}
    return entry, failures


def phase_exhaustive():
    from canon import canonicalize
    classes = {}
    label_problems = []
    for mask in qa_core.DOMAIN_MASKS:
        quads = qa_core.domain_quads(mask)
        result = canonicalize(quads)
        for problem in qa_core.check_labels(quads, result):
            label_problems.append({'mask': mask, 'problem': problem})
        classes.setdefault(result['code'], []).append(mask)
    perms = qa_core.domain_permutations()
    oracle_classes = []
    for mask in qa_core.DOMAIN_MASKS:
        quads = qa_core.domain_quads(mask)
        for cls in oracle_classes:
            target = qa_core.norm_set(qa_core.domain_quads(cls[0]))
            if any(qa_core.norm_set(qa_core.apply_mapping(quads, perm))
                   == target for perm in perms):
                cls.append(mask)
                break
        else:
            oracle_classes.append([mask])
    canon_partition = sorted(sorted(m) for m in classes.values())
    oracle_partition = sorted(sorted(m) for m in oracle_classes)
    partition_match = canon_partition == oracle_partition
    # Overlapping-scale cross-check: the same clique-enumeration machinery
    # used for the 16-node certificates must be invariant within every
    # brute-force oracle class on this domain (k=2 mutual pairs, k=3).
    clique_status = {}
    for mask in qa_core.DOMAIN_MASKS:
        quads = qa_core.domain_quads(mask)
        clique_status[mask] = (
            len(qa_core.clique_witnesses(quads, 2, qa_core.DOMAIN_PREDICATE,
                                         graph_mode='default')),
            len(qa_core.clique_witnesses(quads, 3, qa_core.DOMAIN_PREDICATE,
                                         graph_mode='default')))
    crosscheck = all(len({clique_status[m] for m in cls}) == 1
                     for cls in oracle_classes)
    failures = []
    if label_problems:
        failures.append('exhaustive domain: %d invalid label witnesses'
                        % len(label_problems))
    if not partition_match:
        failures.append('exhaustive domain: canon partition != oracle '
                        'partition (%d vs %d classes)'
                        % (len(canon_partition), len(oracle_partition)))
    if not crosscheck:
        failures.append('exhaustive domain: clique checker not invariant '
                        'within oracle classes')
    entry = {
        'id': 'exhaustive-3blank-domain',
        'domain': {'blank_ids': qa_core.DOMAIN_IDS,
                   'predicate': qa_core.DOMAIN_PREDICATE, 'graph': None,
                   'self_loops': True, 'masks': len(list(qa_core.DOMAIN_MASKS))},
        'labels_checked': len(list(qa_core.DOMAIN_MASKS)),
        'label_problems': label_problems,
        'canon_classes': len(canon_partition),
        'oracle_classes': len(oracle_partition),
        'partition_matches_oracle': partition_match,
        'classes': [{'code': code, 'size': len(members), 'members': members}
                    for code, members in
                    sorted(classes.items(), key=lambda kv: kv[1][0])],
        'clique_checker_crosscheck': {
            'scale': 'k=2 and k=3 clique counts on the default graph',
            'invariant_within_oracle_classes': crosscheck},
        'result': 'pass' if not failures else 'fail',
    }
    return entry, failures


def decorate_symmetric(quads):
    """Embed a symmetric export in named-graph/shared-identity/literal roles."""
    extra = []
    for blank in qa_core.blank_ids(quads):
        extra.append([['b', 'hub'], ['i', 'urn:qa:member'], ['b', blank],
                      ['i', 'urn:qa:main']])
    extra.append([['b', 'hub'], ['i', 'urn:qa:label'], ['l', 'const-007'],
                  ['i', 'urn:qa:main']])
    extra.append([['b', 'hub'], ['i', 'urn:qa:seed'], ['i', 'urn:qa:const'],
                  None])
    return quads + extra


def _symmetric_verdicts(exports, k4_lists, witness_02):
    """Independent equivalence verdicts for one symmetric triple."""
    pairs = []
    witness_ok = (qa_core.norm_set(qa_core.apply_mapping(exports[0],
                                                         witness_02))
                  == qa_core.norm_set(exports[2]))
    pairs.append({'pair': [0, 2], 'verdict': 'isomorphic',
                  'evidence': {'kind': 'witness-bijection',
                               'mapping': witness_02,
                               'rechecked_on_quad_sets': witness_ok},
                  'verdict_valid': witness_ok})
    for a, b in ((0, 1), (1, 2)):
        counts = (len(k4_lists[a]), len(k4_lists[b]))
        example = (k4_lists[a][0] if k4_lists[a]
                   else (k4_lists[b][0] if k4_lists[b] else None))
        valid = (counts[0] > 0) != (counts[1] > 0) and example is not None
        pairs.append({'pair': [a, b], 'verdict': 'non-isomorphic',
                      'evidence': {'kind': 'k4-dichotomy',
                                   'k4_count_per_export': counts,
                                   'k4_example': example,
                                   'enumeration': 'all C(16,4) blank-id '
                                   'subsets re-enumerated from raw quads'},
                      'verdict_valid': valid})
    return pairs


def _expected_landing_from_pairs(pairs, size):
    parent = list(range(size))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for pair in pairs:
        if pair['verdict'] == 'isomorphic' and pair['verdict_valid']:
            a, b = pair['pair']
            parent[find(a)] = find(b)
    first = {}
    kept, duplicates = [], []
    for index in range(size):
        root = find(index)
        if root in first:
            duplicates.append([index, first[root]])
        else:
            first[root] = index
            kept.append(index)
    return {'kept': kept, 'duplicate_of': duplicates}


def phase_symmetric():
    from canon import canonicalize
    from collector import collect
    from samples import page, symmetric_exports
    failures = []
    exports = symmetric_exports()
    coordinates = [(x, y) for x in range(4) for y in range(4)]
    witness_02 = {str(v): 'capture-%d' % (15 - i)
                  for i, v in enumerate(coordinates)}
    k4_lists = [qa_core.clique_witnesses(e, 4, 'urn:related')
                for e in exports]
    pairs = _symmetric_verdicts(exports, k4_lists, witness_02)
    codes, label_problems = [], []
    for quads in exports:
        result = canonicalize(quads)
        codes.append(result['code'])
        label_problems += qa_core.check_labels(quads, result)
    for pair in pairs:
        a, b = pair['pair']
        equal = codes[a] == codes[b]
        pair['canon_codes_equal'] = equal
        pair['agrees'] = (pair['verdict_valid']
                          and equal == (pair['verdict'] == 'isomorphic'))
        if not pair['agrees']:
            failures.append('symmetric exports pair %s: canon disagrees '
                            'with independent %s verdict'
                            % (pair['pair'], pair['verdict']))
    if label_problems:
        failures.append('symmetric exports: invalid label witnesses')
    landing = collect([page(e) for e in exports])
    expected = _expected_landing_from_pairs(pairs, len(exports))
    landing_ok = landing == expected
    if not landing_ok:
        failures.append('symmetric exports landing %r != expected %r'
                        % (landing, expected))
    # Same family decorated with named-graph roles, a cross-graph shared
    # identity and literal constants; identical local features preserved.
    decorated = [decorate_symmetric(e) for e in exports]
    decorated_witness = dict(witness_02)
    decorated_witness['hub'] = 'hub'
    decorated_k4 = [qa_core.clique_witnesses(e, 4, 'urn:related')
                    for e in decorated]
    decorated_pairs = _symmetric_verdicts(decorated, decorated_k4,
                                          decorated_witness)
    decorated_codes = []
    decorated_label_problems = []
    for quads in decorated:
        result = canonicalize(quads)
        decorated_codes.append(result['code'])
        decorated_label_problems += qa_core.check_labels(quads, result)
    for pair in decorated_pairs:
        a, b = pair['pair']
        equal = decorated_codes[a] == decorated_codes[b]
        pair['canon_codes_equal'] = equal
        pair['agrees'] = (pair['verdict_valid']
                          and equal == (pair['verdict'] == 'isomorphic'))
        if not pair['agrees']:
            failures.append('decorated symmetric pair %s: canon disagrees'
                            % pair['pair'])
    if decorated_label_problems:
        failures.append('decorated symmetric family: invalid labels')
    entry = {
        'id': 'symmetric-exports',
        'pairs': pairs,
        'landing': {'expected': expected, 'actual': landing,
                    'ok': landing_ok},
        'label_problems': label_problems,
        'decorated_family': {
            'roles_embedded': ['named-graph urn:qa:main',
                               'cross-graph shared blank hub',
                               "literal constant 'const-007'"],
            'pairs': decorated_pairs,
            'label_problems': decorated_label_problems},
        'result': 'pass' if not failures else 'fail',
    }
    return entry, failures


def phase_random():
    from canon import canonicalize
    from collector import collect
    from samples import page
    rng = random.Random(RANDOM_SEED)
    counters = {'isomorphic': 0, 'non_isomorphic': 0}
    mismatches, shrunk_cases = [], []
    labels_checked = 0
    label_problem_count = 0
    failures = []
    for trial in range(RANDOM_TRIALS):
        left = qa_core.random_quads(rng, rng.randint(1, 6))
        constructed_iso = trial % 2 == 0
        if constructed_iso:
            right, _ = qa_core.random_isomorphic(rng, left)
        else:
            right = qa_core.random_quads(rng, rng.randint(1, 6))
        verdict, _ = qa_core.oracle_verdict(left, right)
        expect_iso = verdict == 'isomorphic'
        if constructed_iso and not expect_iso:
            failures.append('trial %d: constructed isomorphic pair rejected '
                            'by the oracle (QA self-check)' % trial)
            continue
        counters['isomorphic' if expect_iso else 'non_isomorphic'] += 1
        problems = []
        for quads in (left, right):
            problems += qa_core.check_labels(quads, canonicalize(quads))
        labels_checked += 2
        label_problem_count += len(problems)
        got = production_merge(left, right)
        landing = collect([page(left), page(right)])
        landing_ok = landing == expected_landing(expect_iso)
        if got is not expect_iso or not landing_ok or problems:
            small_left, small_right, log = qa_core.shrink_mismatch(
                left, right, expect_iso, production_merge)
            case = {'left': small_left, 'right': small_right,
                    'seed': RANDOM_SEED}
            os.makedirs(CASES_DIR, exist_ok=True)
            path = os.path.join(CASES_DIR, 'case-%03d.json' % trial)
            with open(path, 'w', encoding='utf-8') as handle:
                json.dump(case, handle, ensure_ascii=True, indent=1)
            mismatches.append({'trial': trial, 'expected_iso': expect_iso,
                               'actual_merge': got, 'landing_ok': landing_ok,
                               'label_problems': problems,
                               'retained_case': os.path.basename(path)})
            shrunk_cases.append({'trial': trial, 'case': case, 'log': log})
    if mismatches:
        failures.append('%d random differential mismatches (shrunk and '
                        'retained under cases/)' % len(mismatches))
    if label_problem_count:
        failures.append('%d invalid label witnesses in random phase'
                        % label_problem_count)
    entry = {'id': 'random-differential',
             'seed': RANDOM_SEED, 'trials': RANDOM_TRIALS,
             'isomorphic_pairs': counters['isomorphic'],
             'non_isomorphic_pairs': counters['non_isomorphic'],
             'labels_checked': labels_checked,
             'label_problems': label_problem_count,
             'mismatches': mismatches,
             'shrunk_cases': shrunk_cases,
             'result': 'pass' if not failures else 'fail'}
    return entry, failures


def phase_shrinker_demo():
    """Demonstrate shrinking on an intentional mutant deviation (M1)."""
    rng = random.Random(RANDOM_SEED + 1)
    mutant = qa_mutants.build_mutant('M1')

    def actual(left, right):
        try:
            return mutant(left)['code'] == mutant(right)['code']
        except Exception:  # noqa: BLE001 - mutant raised: not a verdict
            return None

    while True:
        left = qa_core.random_quads(rng, 4)
        if any(isinstance(row[3], list) and row[3][0] == 'i' for row in left):
            break
    mapping = {'n%d' % i: 'm%d' % i for i in range(4)}
    right = qa_core.apply_mapping(left, mapping)
    right = [[['i', t[1] + ':alt']
              if isinstance(t, list) and t[0] == 'i' and pos == 3 else t
              for pos, t in enumerate(row)] for row in right]
    verdict, _ = qa_core.oracle_verdict(left, right)
    entry = {'id': 'shrinker-demonstration',
             'against': 'mutant M1 (graph names dropped)',
             'note': 'intentional mutant deviation; demonstrates replay-case '
                     'production, not a production counterexample'}
    if verdict != 'non-isomorphic' or actual(left, right) is not True:
        entry['result'] = 'skip'
        entry['reason'] = 'demonstration pair did not exhibit the intended '
        'mutant mismatch (oracle %s)' % verdict
        return entry, []
    small_left, small_right, log = qa_core.shrink_mismatch(
        left, right, False, actual)
    minimality = log[-1]
    ok = (minimality['action'] == 'minimality-check'
          and minimality['removals_still_mismatching'] == 0)
    entry.update({
        'initial_quads': [len(left), len(right)],
        'final_case': {'left': small_left, 'right': small_right,
                       'seed': RANDOM_SEED + 1},
        'shrink_log': log,
        'minimal': ok,
        'result': 'pass' if ok else 'fail',
    })
    failures = [] if ok else ['shrinker demonstration did not reach a '
                              '1-minimal mutant mismatch']
    return entry, failures


def phase_mutants():
    from collector import collect
    from samples import QUADS, page, renamed, symmetric_exports
    exports = symmetric_exports()

    def cycle(names):
        n = len(names)
        return [[['b', names[i]], ['i', 'urn:qa:p'],
                 ['b', names[(i + 1) % n]], None] for i in range(n)]

    split = json.loads(json.dumps(QUADS))
    split[1][0] = ['b', 'obs-8']
    m4_left = cycle(['a', 'b', 'c']) + cycle(['d', 'e', 'f', 'g'])
    m4_right = renamed(m4_left, {'a': 'w', 'b': 'x', 'c': 'y', 'd': 'a',
                                 'e': 'b', 'f': 'c', 'g': 'd'})
    cases = [
        {'mutant': 'M1',
         'left': [[['b', 'x'], ['i', 'urn:qa:p'], ['i', 'urn:qa:o'],
                   ['i', 'urn:qa:g1']]],
         'right': [[['b', 'x'], ['i', 'urn:qa:p'], ['i', 'urn:qa:o'],
                    ['i', 'urn:qa:g2']]]},
        {'mutant': 'M2', 'left': QUADS, 'right': split},
        {'mutant': 'M3', 'left': exports[0], 'right': exports[1]},
        {'mutant': 'M4', 'left': m4_left, 'right': m4_right},
    ]
    entries = []
    failures = []
    for case in cases:
        verdict, witness = qa_core.oracle_verdict(case['left'],
                                                  case['right'])
        if verdict == 'undetermined':
            # 16-blank pairs rest on the K4 certificate instead.
            k4_left = qa_core.clique_witnesses(case['left'], 4,
                                               'urn:related')
            k4_right = qa_core.clique_witnesses(case['right'], 4,
                                                'urn:related')
            verdict = ('non-isomorphic'
                       if (len(k4_left) > 0) != (len(k4_right) > 0)
                       else 'undetermined')
            witness = None
            basis = 'k4-dichotomy certificate'
        else:
            basis = ('brute-force bijection oracle'
                     + (' (witness %s)' % witness if witness else ''))
        is_iso = verdict == 'isomorphic'
        expected = expected_landing(is_iso)
        production_landing = collect([page(case['left']),
                                      page(case['right'])])
        production_ok = production_landing == expected
        payload = json.dumps({'mutant': case['mutant'], 'left': case['left'],
                              'right': case['right']}, ensure_ascii=True)
        proc = subprocess.run(
            [sys.executable, 'qa_mutants.py', 'run', payload],
            cwd=HERE, capture_output=True, text=True, timeout=180)
        entry = {'id': case['mutant'],
                 'simulated_error': qa_mutants.DESCRIPTIONS[case['mutant']],
                 'independent_expectation': {'verdict': verdict,
                                             'basis': basis},
                 'expected_landing': expected,
                 'production_landing': production_landing,
                 'production_matches_expectation': production_ok}
        if proc.returncode != 0:
            entry.update({'detected': False,
                          'error': 'mutant subprocess failed: %s'
                                   % proc.stderr.strip()[-500:],
                          'result': 'error'})
            failures.append('mutant %s subprocess failed (not a detection)'
                            % case['mutant'])
        else:
            output = json.loads(proc.stdout)
            mutant_landing = output['landing']
            detected = mutant_landing != expected
            entry.update({'mutant_landing': mutant_landing,
                          'mutant_codes_equal': output['codes_equal'],
                          'detected': detected,
                          'result': 'pass' if detected and production_ok
                          else 'fail'})
            if not detected:
                failures.append('mutant %s was not detected' % case['mutant'])
            if not production_ok:
                failures.append('mutant %s case: production itself deviates '
                                'from the independent expectation'
                                % case['mutant'])
        entries.append(entry)
    return entries, failures


def phase_stress():
    entries = []
    failures = []
    for spec in qa_stress.RUNS:
        proc = subprocess.run(
            [sys.executable, 'qa_stress.py', 'worker', json.dumps(spec)],
            cwd=HERE, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            entries.append({'family': spec['family'], 'params': spec['params'],
                            'limit': spec['limit'], 'outcome': 'worker-error',
                            'conclusion': 'undetermined',
                            'stderr': proc.stderr.strip()[-500:]})
            failures.append('stress worker failed for %s %s'
                            % (spec['family'], spec['params']))
        else:
            entries.append(json.loads(proc.stdout))
    return entries, failures


# ---------------------------------------------------------------- entries

def verify():
    started = time.time()
    evidence = {'cases': [], 'mutants': [], 'stress': [],
                'limitations': LIMITATIONS}
    failures = []

    for phase in (phase_retained, phase_validation, phase_exhaustive,
                  phase_symmetric, phase_random, phase_shrinker_demo):
        entry, phase_failures = phase()
        evidence['cases'].append(entry)
        failures += phase_failures

    mutant_entries, mutant_failures = phase_mutants()
    evidence['mutants'] = mutant_entries
    failures += mutant_failures

    stress_entries, stress_failures = phase_stress()
    evidence['stress'] = stress_entries
    failures += stress_failures

    undetermined = [e['family'] + ':' + json.dumps(e['params'])
                    for e in stress_entries
                    if e.get('conclusion') == 'undetermined']
    with open(EVIDENCE_PATH, 'w', encoding='utf-8') as handle:
        json.dump(evidence, handle, ensure_ascii=False, indent=1)
        handle.write('\n')
    print(json.dumps({'result': 'pass' if not failures else 'fail',
                      'failures': failures,
                      'undetermined_stress_runs': undetermined,
                      'elapsed_seconds': round(time.time() - started, 3),
                      'evidence': os.path.basename(EVIDENCE_PATH)},
                     ensure_ascii=False, indent=2))
    return 0 if not failures else 1


def replay():
    if len(sys.argv) < 3:
        raise SystemExit('usage: qa.py replay CASE.json')
    with open(sys.argv[2], encoding='utf-8') as handle:
        case = json.load(handle)
    outcome = evaluate_case(case)
    print(json.dumps({'input': {'left': case['left'], 'right': case['right'],
                                'seed': case.get('seed')},
                      'independent': outcome['independent'],
                      'actual': outcome['actual'],
                      'agrees': outcome['agrees']},
                     ensure_ascii=False, indent=2))
    if outcome['agrees'] is True:
        return 0
    if outcome['agrees'] is False:
        return 1
    return 2  # independent oracle undetermined


def demo():
    from collector import collect
    from samples import QUADS, page, renamed
    split = json.loads(json.dumps(QUADS))
    split[1][0] = ['b', 'obs-8']  # page:2 observation becomes another node
    output = {
        'shared_identity_renamed_page': collect([
            page(QUADS),
            page(renamed(QUADS, {'obs-7': 'n', 'page-node': 'm'}))]),
        'shared_identity_vs_split_node': collect([page(QUADS), page(split)]),
        'reading': 'same anonymous observation shared across both named '
                   'graphs lands once even after renaming; splitting it '
                   'into two nodes keeps both pages',
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit({'verify': verify, 'replay': replay, 'demo': demo}[sys.argv[1]]())
