# Reference probe, not production code. Runs paperweight.md's Assess prologue and epilogue
# under Lua 5.4 (lupa) with stubbed store/models/tasks and synthetic Grade replies,
# and prints the diagnostics the real Lua computes. Usage: python lua_shim_probe.py <paper.md>
# Expects paperweight.md at the path below; edit PROMPT_PATH for your checkout.
import re, sys, random, lupa.lua54 as L
PROMPT_PATH = 'crates/paperweight/paperweight.md'
src = open(PROMPT_PATH).read()
blocks = re.findall(r'```lua\n(.*?)\n```', src, re.S)
print('lua blocks', len(blocks))
assess_pro, assess_epi = blocks[1], blocks[2]
paper = open(sys.argv[1]).read()
rt = L.LuaRuntime(unpack_returned_tuples=True)
store = {'paper.md': paper}
g = rt.globals()
def sread(p):
    if p in store: return store[p]
    raise Exception('missing '+p)
def swrite(p, v): store[p] = v
g.store = rt.table_from({'read': sread, 'write': swrite})
g.untrusted = lambda s: s
g.models = rt.table_from({'use': lambda *a: None, 'default': lambda *a: None, 'infer': lambda *a: 'PROPOSAL'})
g.var = rt.table()
rnd = random.Random(7)
def fanout(name, jobs):
    # synthetic Grade replies: pick a real sentence from the chunk as quote
    for i in range(1, len(jobs)+1):
        job = jobs[i]
        c, k, s = job.split('|')
        chunk = store['pg_chunk_%s.md' % k]
        words = [w for w in re.split(r'\s+', chunk) if w]
        grade = rnd.choice([0,0,1,2])
        quote = ''
        if grade and len(words) > 12:
            st = rnd.randrange(0, len(words)-10); quote = ' '.join(words[st:st+8])
        store['pg_reply_%s_%s_%s.md' % (c,k,s)] = 'SCORE: %d\nQUOTE: %s' % (grade, quote)
    return rt.table()
g.tasks = rt.table_from({'fanout': fanout})
g.prose = 'x'
rt.execute(assess_pro)
rt.execute(assess_epi)
d = store['diagnostics.md']
print(store['weight.md'])
print('\n'.join(l for l in d.splitlines() if l.startswith(('Totals','grades','single','sample'))))
