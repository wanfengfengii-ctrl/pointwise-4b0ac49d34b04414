"""Stress families for resource measurement, each run in its own process.

qa.py enumerates RUNS and spawns `python3 qa_stress.py worker '<params>'`.
The worker builds the input (timing generation separately), then measures
the production canonicalize call: wall clock, Python allocation peak
(tracemalloc), and whether the search budget is exhausted.  A budget
exhaustion is reported as outcome "search_limit" and must be treated as
undetermined, never as an isomorphism verdict.
"""
import json
import sys
import time
import tracemalloc


def build_repeated(params):
    """Many copies of a fixed fact set: exercises set folding."""
    facts = params['facts']
    base = []
    for i in range(facts):
        base.append([['b', 'x%d' % i], ['i', 'urn:qa:p'],
                     ['b', 'y%d' % i], ['i', 'urn:qa:g%d' % (i % 3)]])
        base.append([['b', 'x%d' % i], ['i', 'urn:qa:q'],
                     ['l', 'const-%d' % (i % 2)], None])
    return [list(row) for _ in range(params['copies']) for row in base]


def build_cycles(params):
    """k disjoint directed cycles: vertex-transitive, no twin automorphisms."""
    quads = []
    for c in range(params['components']):
        n = params['length']
        for i in range(n):
            quads.append([['b', 'c%dn%d' % (c, i)], ['i', 'urn:qa:p'],
                          ['b', 'c%dn%d' % (c, (i + 1) % n)], None])
    return quads


def build_srg(params):
    """16-node strongly regular structures with identical local features."""
    from samples import symmetric_exports
    exports = symmetric_exports()
    return exports[0] if params['shape'] == 'rook' else exports[1]


BUILDERS = {'repeated-facts': build_repeated,
            'disjoint-cycles': build_cycles,
            'same-local-features': build_srg}

# Each run: family, params, search budget.  Budgets are part of the record;
# an exhausted budget marks the run undetermined, not (non-)isomorphic.
RUNS = [
    {'family': 'repeated-facts', 'params': {'facts': 8, 'copies': 1},
     'limit': 100000},
    {'family': 'repeated-facts', 'params': {'facts': 8, 'copies': 1000},
     'limit': 100000},
    {'family': 'repeated-facts', 'params': {'facts': 8, 'copies': 10000},
     'limit': 100000},
    {'family': 'disjoint-cycles', 'params': {'components': 2, 'length': 4},
     'limit': 100000},
    {'family': 'disjoint-cycles', 'params': {'components': 3, 'length': 4},
     'limit': 100000},
    {'family': 'disjoint-cycles', 'params': {'components': 4, 'length': 4},
     'limit': 100000},
    {'family': 'disjoint-cycles', 'params': {'components': 6, 'length': 4},
     'limit': 3000},
    {'family': 'disjoint-cycles', 'params': {'components': 8, 'length': 4},
     'limit': 3000},
    {'family': 'same-local-features', 'params': {'shape': 'rook'},
     'limit': 100000},
    {'family': 'same-local-features', 'params': {'shape': 'shrikhande'},
     'limit': 100000},
]


def worker(run_json):
    from canon import SearchLimit, canonicalize
    spec = json.loads(run_json)
    gen_start = time.perf_counter()
    quads = BUILDERS[spec['family']](spec['params'])
    generation_seconds = time.perf_counter() - gen_start
    blanks = len({t[1] for row in quads for t in row
                  if isinstance(t, list) and t[0] == 'b'})
    # Pass 1: clean wall clock, no profiler overhead.
    call_start = time.perf_counter()
    try:
        result = canonicalize(quads, spec['limit'])
        outcome = 'ok'
        search_nodes = result['stats']['search_nodes']
        twin_prunes = result['stats']['twin_prunes']
    except SearchLimit:
        outcome = 'search_limit'
        search_nodes = None
        twin_prunes = None
    wall_seconds = time.perf_counter() - call_start
    # Pass 2: Python allocation peak under tracemalloc (deterministic rerun;
    # its own inflated wall clock is recorded separately for transparency).
    tracemalloc.start()
    traced_start = time.perf_counter()
    try:
        canonicalize(quads, spec['limit'])
    except SearchLimit:
        pass
    traced_wall_seconds = time.perf_counter() - traced_start
    peak_bytes = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    print(json.dumps({
        'family': spec['family'],
        'params': spec['params'],
        'input_quads': len(quads),
        'blank_nodes': blanks,
        'limit': spec['limit'],
        'outcome': outcome,
        'conclusion': 'measured' if outcome == 'ok' else 'undetermined',
        'search_nodes': search_nodes,
        'twin_prunes': twin_prunes,
        'wall_seconds': round(wall_seconds, 6),
        'peak_bytes': peak_bytes,
        'generation_seconds': round(generation_seconds, 6),
        'traced_wall_seconds': round(traced_wall_seconds, 6),
    }, ensure_ascii=True))


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == 'worker':
        worker(sys.argv[2])
    else:
        raise SystemExit('usage: qa_stress.py worker \'<run-json>\'')
