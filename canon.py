"""Canonical codes for finite sets of harvested RDF-like quads."""
import json


class Invalid(ValueError):
    pass


class SearchLimit(RuntimeError):
    pass


def wire(value):
    return json.dumps(value, ensure_ascii=True, separators=(',', ':'))


def canonicalize(quads, limit=100000):
    """Return code, an input-blank-to-integer witness, and search counters."""
    if type(limit) is not int or limit < 1:
        raise Invalid('LIMIT')
    if type(quads) is not list:
        raise Invalid('QUADS')
    edges = set()
    for row in quads:
        if type(row) is not list or len(row) != 4:
            raise Invalid('QUAD')
        terms = []
        for pos, term in enumerate(row):
            if pos == 3 and term is None:
                terms.append(None)
                continue
            if (type(term) is not list or len(term) != 2
                    or term[0] not in ('b', 'i', 'l')
                    or type(term[1]) is not str):
                raise Invalid('TERM')
            kind, value = term
            if kind != 'l' and not value:
                raise Invalid('EMPTY_ID')
            if pos == 0 and kind == 'l' or pos == 1 and kind != 'i':
                raise Invalid('ROLE')
            if pos == 3 and kind == 'l':
                raise Invalid('ROLE')
            terms.append((kind, value))
        edges.add(tuple(terms))
    vertices = sorted({t[1] for row in edges for t in row
                       if t is not None and t[0] == 'b'})
    if len(vertices) > 32:
        raise Invalid('BLANK_COUNT')
    incident = {v: [] for v in vertices}
    for row in edges:
        for v in {t[1] for t in row if t is not None and t[0] == 'b'}:
            incident[v].append(row)
    stats = {'search_nodes': 0, 'twin_prunes': 0}

    def refine(colors):
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
                    observations.append(wire(observation))
                signatures[v] = (colors[v], tuple(sorted(observations)))
            classes = {key: n for n, key in
                       enumerate(sorted(set(signatures.values())))}
            updated = {v: classes[signatures[v]] for v in vertices}
            if len(set(updated.values())) == len(set(colors.values())):
                return updated
            colors = updated

    def swapped(row, a, b):
        return tuple(('b', b if t[1] == a else a if t[1] == b else t[1])
                     if t is not None and t[0] == 'b' else t for t in row)

    def twins(a, b):
        # Only an actual transposition automorphism permits branch suppression.
        return all(swapped(row, a, b) in edges
                   for row in incident[a] + incident[b])

    def encode(labels):
        rows = []
        for row in edges:
            rows.append([['b', labels[t[1]]] if t is not None and t[0] == 'b'
                         else list(t) if t is not None else None for t in row])
        return wire(sorted(rows, key=wire))

    def search(colors):
        stats['search_nodes'] += 1
        if stats['search_nodes'] > limit:
            raise SearchLimit('SEARCH_LIMIT')
        colors = refine(colors)
        cells = {}
        for v in vertices:
            cells.setdefault(colors[v], []).append(v)
        unresolved = [(len(vs), c, vs) for c, vs in cells.items() if len(vs) > 1]
        if not unresolved:
            labels = {v: n for n, v in
                      enumerate(sorted(vertices, key=colors.__getitem__))}
            return encode(labels), labels
        _, _, cell = min(unresolved)
        best = None
        representatives = []
        for chosen in cell:
            if any(twins(chosen, previous) for previous in representatives):
                stats['twin_prunes'] += 1
                continue
            representatives.append(chosen)
            keys = {v: (colors[v], int(v == chosen)) for v in vertices}
            ranks = {k: n for n, k in enumerate(sorted(set(keys.values())))}
            candidate = search({v: ranks[keys[v]] for v in vertices})
            if best is None or candidate[0] < best[0]:
                best = candidate
        return best

    code, labels = search({v: 0 for v in vertices})
    return {'code': code, 'labels': labels, 'stats': stats}
