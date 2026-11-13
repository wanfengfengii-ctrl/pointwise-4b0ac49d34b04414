import json
import sys
from canon import canonicalize, Invalid, SearchLimit
from collector import collect
from samples import QUADS, renamed, page


def normal():
    result = canonicalize(QUADS)
    relabeled = renamed(list(reversed(QUADS)), {'obs-7': 'z', 'page-node': 'a'})
    assert result['code'] == canonicalize(relabeled)['code']
    assert collect([page(QUADS), page(relabeled)]) == {'kept': [0], 'duplicate_of': [[1, 0]]}
    assert result['code'] == canonicalize(QUADS + [QUADS[0]])['code']
    assert sorted(result['labels'].values()) == [0, 1]
    assert canonicalize([])['code'] == '[]'
    changed = json.loads(json.dumps(QUADS))
    changed[1][2][1] = '7'
    assert result['code'] != canonicalize(changed)['code']
    try:
        canonicalize([[['l', 'bad'], ['i', 'p'], ['i', 'o'], None]])
    except Invalid as error:
        assert str(error) == 'ROLE'
    else:
        raise AssertionError('literal subject accepted')
    # A one-node budget is insufficient to individualize a directed cycle.
    ring = [[['b', str(i)], ['i', 'p'], ['b', str((i+1) % 4)], None]
            for i in range(4)]
    try:
        canonicalize(ring, limit=1)
    except SearchLimit as error:
        assert str(error) == 'SEARCH_LIMIT'
    else:
        raise AssertionError('budget ignored')
    print('NORMAL_REGRESSION_OK')


def demo():
    output = canonicalize(QUADS)
    print(json.dumps({'input': QUADS, 'canonical': json.loads(output['code']),
                      'labels': output['labels'], 'stats': output['stats'],
                      'landing': collect([page(QUADS), page(renamed(QUADS, {'obs-7': 'n', 'page-node': 'm'}))])},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    {'normal': normal, 'demo': demo}[sys.argv[1]]()
