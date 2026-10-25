import json, re, sys

t = open(sys.argv[1], encoding='utf8').read()
s = t.index("JSON.parse('", t.index('__INITIAL_STATE__')) + len("JSON.parse('")
e = s
while True:
    e = t.index("')", e)
    if t[e - 1] != '\\':
        break
    e += 1
raw = t[s:e]

SIMPLE = {'n': '\n', 't': '\t', 'r': '\r', 'b': '\b', 'f': '\f', '0': '\0'}


def js_unescape(m):
    if m.group(1):
        return chr(int(m.group(1), 16))
    if m.group(2):
        return chr(int(m.group(2), 16))
    c = m.group(3)
    return SIMPLE.get(c, c)


# The page holds the state as a JS single-quoted string; undo one level of JS escaping to get JSON text.
text = re.sub(r'\\(?:u([0-9a-fA-F]{4})|x([0-9a-fA-F]{2})|(.))', js_unescape, raw, flags=re.S)
state = json.loads(text, strict=False)
json.dump(state, open(sys.argv[2], 'w', encoding='utf8'), ensure_ascii=False)
prods = state['domains']['products']
print('keys', list(state.keys()), 'products', len(prods))
k = sys.argv[3] if len(sys.argv) > 3 else next(iter(prods))
print(json.dumps(prods[k], ensure_ascii=False)[:7000])
