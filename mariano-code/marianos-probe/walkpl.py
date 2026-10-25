import json, sys
from collections import Counter
st = json.load(open(sys.argv[1], encoding='utf8'))
def walk(o, path):
    if isinstance(o, dict):
        for k, v in o.items(): yield from walk(v, path + [k])
    elif isinstance(o, list):
        for i, v in enumerate(o): yield from walk(v, path + [i])
    elif isinstance(o, str) and '/pl/' in o: yield path, o
paths = Counter(); ex = {}
for p, v in walk(st, []):
    key = '/'.join(str(x) for x in p[:4]); paths[key] += 1; ex.setdefault(key, (p, v))
for k, n in paths.most_common(12): print(n, k, ex[k][0], ex[k][1][:90])
