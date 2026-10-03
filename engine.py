"""Agents: Planner -> Generator -> Executor -> Analyzer/Oracle -> Reporter (+ mutation and baseline evaluation)."""
import os, random, time
from domains import DOMAINS, SEV
ROOT = os.path.dirname(os.path.abspath(__file__))

def plan(D): return sorted(D["rules"], key=lambda r: (SEV[D["rules"][r][0]], r))
def generate(D):
    o = plan(D); return sorted(D["cases"], key=lambda c: o.index(c[0]))
def execute(D, cases, bugs):
    out = []
    for n, (rule, label, inp) in enumerate(cases, 1):
        e, a = D["sut"](inp), D["sut"](inp, frozenset(bugs))   # oracle = specification model
        out.append(dict(id="T%02d" % n, rule=rule, label=label, inp=inp, exp=e, act=a, ok=e == a))
    return out
def analyze(D, res):
    g = {}
    for r in res:
        if not r["ok"]: g.setdefault(r["rule"], []).append(r)
    out = []
    for n, (rule, fs) in enumerate(sorted(g.items(), key=lambda kv: (SEV[D["rules"][kv[0]][0]], kv[0])), 1):
        causes = {"Over-strict check: valid input rejected" if f["exp"] == "OK" else
                  "Validation missing: invalid input accepted" if f["act"] == "OK" else
                  "Wrong rejection reason (check order or mapping)" for f in fs}
        out.append(dict(id="DEF-%02d" % n, rule=rule, sev=D["rules"][rule][0], text=D["rules"][rule][1], cause="; ".join(sorted(causes)), tests=[f["id"] for f in fs]))
    return out
def mutation(D, cases):
    rows = []
    for b, d in D["bugs"].items():
        k = [x["id"] for x in execute(D, cases, {b}) if not x["ok"]]
        rows.append(dict(bug=b, desc=d, killed=bool(k), by=k[:4]))
    return rows
def write_pytest(dom, D, cases):
    p = os.path.join(ROOT, "tests", "generated"); os.makedirs(p, exist_ok=True)
    rows = ",\n".join("    (%r, %r, %r)" % (c[0], c[2], D["sut"](c[2])) for c in cases)
    open(os.path.join(p, "test_%s_generated.py" % dom), "w").write(
        "import os, sys\nsys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))\n"
        "import pytest\nfrom domains import DOMAINS\n\nSUT = DOMAINS[%r]['sut']\n# Inject bugs with:  set BUGS=UPI_BOUNDARY,DECIMALS  (Windows)\n"
        "BUGS = frozenset(filter(None, os.environ.get('BUGS', '').split(',')))\nCASES = [\n%s\n]\n\n\n"
        "@pytest.mark.parametrize('rule,inp,expected', CASES)\ndef test_case(rule, inp, expected):\n    assert SUT(inp, BUGS) == expected, rule\n" % (dom, rows))
def report(D, dom, k, defects, bugs):
    L = ["# Test Report - " + D["title"], "", "Generated: " + time.strftime("%Y-%m-%d %H:%M:%S"), "Injected bugs: " + (", ".join(bugs) or "none (clean build)"), "",
         "| Tests | Passed | Failed | Defects | Rule coverage | Mutation score | False positives |", "|---|---|---|---|---|---|---|",
         "| %(tests)s | %(passed)s | %(failed)s | %(defects)s | %(coverage)s%% | %(mutation)s%% | %(fp)s |" % k, "", "## Defects", ""]
    L += ["- **%s** [%s] %s - %s. Root cause: %s. Tests: %s" % (d["id"], d["sev"], d["rule"], d["text"], d["cause"], ", ".join(d["tests"])) for d in defects] or ["No defects found."]
    return "\n".join(L)
def run(dom, bugs, mut=True):
    D = DOMAINS[dom]; tr = []
    order = plan(D); tr.append(("Planner", "Risk-ranked %d rules: %s" % (len(order), ", ".join(order))))
    cases = generate(D); tr.append(("Generator", "Generated %d boundary and negative test cases from the domain rules" % len(cases)))
    res = execute(D, cases, bugs); bad = [r for r in res if not r["ok"]]
    tr.append(("Executor", "Ran %d tests against the system under test with %d injected bug(s): %d failed" % (len(res), len(bugs), len(bad))))
    defects = analyze(D, res); tr.append(("Analyzer", "Compared actual vs. specification; grouped failures into %d defect(s) with root-cause hypotheses" % len(defects)))
    fp = len([r for r in execute(D, cases, []) if not r["ok"]])
    m = mutation(D, cases) if mut else []
    k = dict(tests=len(res), passed=len(res) - len(bad), failed=len(bad), defects=len(defects), coverage=round(100 * len({c[0] for c in cases}) / len(D["rules"]), 1),
             mutation=round(100 * sum(x["killed"] for x in m) / len(m), 1) if m else None, fp=fp)
    write_pytest(dom, D, cases); tr.append(("Reporter", "Report built and pytest file saved to tests/generated/test_%s_generated.py" % dom))
    return dict(domain=dom, kpi=k, defects=defects, results=res, trace=[dict(agent=a, msg=b) for a, b in tr], mutation=m, report=report(D, dom, k, defects, bugs))
def compare(dom):
    D = DOMAINS[dom]; cases = generate(D); n = len(cases); allb = list(D["bugs"])
    kills = lambda cs: sum(any(D["sut"](c[2]) != D["sut"](c[2], frozenset([b])) for c in cs) for b in allb)
    happy = [c for c in cases if D["sut"](c[2]) == "OK"]; ks = []
    for s in range(20):
        r = random.Random(s); ks.append(kills([("", "", {k: f(r) for k, f in D["space"].items()}) for _ in range(n)]))
    rows = [dict(method="Agentic (domain-based)", tests=n, killed=kills(cases)), dict(method="Happy-path only", tests=len(happy), killed=kills(happy)),
            dict(method="Random testing (avg of 20 runs)", tests=n, killed=round(sum(ks) / 20, 1))]
    for x in rows: x["rate"] = round(100 * x["killed"] / len(allb), 1)
    return dict(total=len(allb), rows=rows)
