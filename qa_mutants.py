"""Semantic mutants of the dedup pipeline, executed for detection testing.

Each mutant simulates one realistic production error.  Mutants are built in
memory only: stand-in callables wrapping the real canon, or an in-memory
source rewrite executed inside this process.  Production files on disk are
never modified.  This module is both a library (build_mutant) and the
subprocess worker used by qa.py (`python3 qa_mutants.py run '<case-json>'`).
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def _m1_drop_graph_names():
    """M1: graph names discarded before canonicalization (collector-level)."""
    from canon import canonicalize

    def mutant(quads, limit=100000):
        stripped = [[row[0], row[1], row[2], None] for row in quads]
        return canonicalize(stripped, limit)
    return mutant


def _m2_split_shared_nodes():
    """M2: blank identity scoped per graph instead of per page export."""
    from canon import canonicalize

    def mutant(quads, limit=100000):
        scoped = []
        for row in quads:
            graph_key = json.dumps(row[3], ensure_ascii=True,
                                   separators=(',', ':'))
            scoped.append([['b', t[1] + '|' + graph_key]
                           if isinstance(t, list) and len(t) == 2
                           and t[0] == 'b' else t for t in row])
        return canonicalize(scoped, limit)
    return mutant


def _m3_stable_colors_only():
    """M3: equality decided by stable color refinement alone, no search."""

    def mutant(quads, limit=100000):
        edges = set()
        for row in quads:
            edges.add(tuple((t[0], t[1]) if isinstance(t, list) else None
                            for t in row))
        vertices = sorted({t[1] for row in edges for t in row
                           if t is not None and t[0] == 'b'})
        incident = {v: [] for v in vertices}
        for row in edges:
            for v in {t[1] for t in row if t is not None and t[0] == 'b'}:
                incident[v].append(row)
        colors = {v: 0 for v in vertices}
        while True:
            signatures = {}
            for v in vertices:
                observations = []
                for row in incident[v]:
                    observation = []
                    for t in row:
                        if t is None:
                            observation.append(('d',))
                        elif t[0] != 'b':
                            observation.append(t)
                        elif t[1] == v:
                            observation.append(('self',))
                        else:
                            observation.append(('color', colors[t[1]]))
                    observations.append(json.dumps(
                        observation, ensure_ascii=True, separators=(',', ':')))
                signatures[v] = (colors[v], tuple(sorted(observations)))
            classes = {key: n for n, key in
                       enumerate(sorted(set(signatures.values())))}
            updated = {v: classes[signatures[v]] for v in vertices}
            if len(set(updated.values())) == len(set(colors.values())):
                digest = sorted(json.dumps(list(sig), ensure_ascii=True,
                                           separators=(',', ':'))
                                for sig in set(signatures.values()))
                return {'code': json.dumps(digest, ensure_ascii=True,
                                           separators=(',', ':')),
                        'labels': {}, 'stats': {'search_nodes': 0,
                                                'twin_prunes': 0}}
            colors = updated
    return mutant


def _m4_blank_ids_in_routing():
    """M4: in-memory rewrite of canon.py so the first branch wins.

    The production search keeps the lexicographically smallest code over all
    branches; replacing that with "first branch wins" makes the result depend
    on the branch visiting order, which follows the raw blank-id strings.
    """
    with open(os.path.join(_HERE, 'canon.py'), encoding='utf-8') as handle:
        source = handle.read()
    needle = 'if best is None or candidate[0] < best[0]:'
    if source.count(needle) != 1:
        raise RuntimeError('M4 mutation point not found or ambiguous')
    namespace = {'__name__': 'canon_mutant_m4'}
    exec(compile(source.replace(needle, 'if best is None:'),
                 'canon_mutant_m4.py', 'exec'), namespace)
    return namespace['canonicalize']


BUILDERS = {
    'M1': _m1_drop_graph_names,
    'M2': _m2_split_shared_nodes,
    'M3': _m3_stable_colors_only,
    'M4': _m4_blank_ids_in_routing,
}

DESCRIPTIONS = {
    'M1': 'graph names are dropped before canonicalization, so exports '
          'differing only in graph position collapse (wrong merge)',
    'M2': 'blank identity is scoped per graph instead of per page, so a '
          'page sharing one node across graphs collapses with a page that '
          'uses distinct nodes (wrong merge)',
    'M3': 'equality is decided by stable color refinement alone without '
          'search, so locally indistinguishable non-isomorphic exports '
          'collapse (wrong merge)',
    'M4': 'blank-id strings decide which search branch defines the code '
          '("first branch wins"), so renamed equivalent exports land '
          'separately (missed merge)',
}


def build_mutant(mutant_id):
    return BUILDERS[mutant_id]()


def run(case_json):
    """Worker: run one mutant against one pair through the real collector."""
    case = json.loads(case_json)
    import collector
    from samples import page
    mutant = build_mutant(case['mutant'])
    collector.canonicalize = mutant  # inject into the real collector
    left, right = case['left'], case['right']
    landing = collector.collect([page(left), page(right)])
    print(json.dumps({
        'mutant': case['mutant'],
        'code_left': mutant(left)['code'],
        'code_right': mutant(right)['code'],
        'codes_equal': mutant(left)['code'] == mutant(right)['code'],
        'landing': landing,
    }, ensure_ascii=True))


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == 'run':
        run(sys.argv[2])
    else:
        raise SystemExit('usage: qa_mutants.py run \'<case-json>\'')
