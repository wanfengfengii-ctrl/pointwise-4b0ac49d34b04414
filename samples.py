"""Small recorded shape: the same anonymous observation is used in two graphs."""
QUADS = [
    [['b', 'obs-7'], ['i', 'urn:station'], ['i', 'urn:A'], ['i', 'urn:page:1']],
    [['b', 'obs-7'], ['i', 'urn:value'], ['l', '007'], ['i', 'urn:page:2']],
    [['b', 'obs-7'], ['i', 'urn:source'], ['b', 'page-node'], ['b', 'page-node']],
    [['b', 'page-node'], ['i', 'urn:href'], ['i', 'urn:export:9'], None],
]


def renamed(rows, mapping):
    return [[[t[0], mapping[t[1]]] if t is not None and t[0] == 'b'
             else list(t) if t is not None else None for t in row]
            for row in rows]


def symmetric_exports():
    # Two portal relationship topologies; names are capture-local.
    coordinates = [(x, y) for x in range(4) for y in range(4)]
    first, second = [], []
    steps = {(1, 0), (3, 0), (0, 1), (0, 3), (1, 1), (3, 3)}
    for a in coordinates:
        for b in coordinates:
            if a == b:
                continue
            row = [['b', str(a)], ['i', 'urn:related'],
                   ['b', str(b)], ['b', str(a)]]
            if a[0] == b[0] or a[1] == b[1]:
                first.append(row)
            if ((b[0]-a[0]) % 4, (b[1]-a[1]) % 4) in steps:
                second.append(row)
    mapping = {str(v): 'capture-' + str(15-i)
               for i, v in enumerate(coordinates)}
    third = renamed(list(reversed(first)), mapping)
    return [first, second, third]


def page(quads):
    import json
    body = json.dumps({'quads': quads}, ensure_ascii=True).replace('</', '<\\/')
    return '<html><script id="capture-graph" type="application/json">' + body + '</script></html>'
