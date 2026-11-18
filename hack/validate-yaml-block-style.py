#!/usr/bin/env python3
"""Repository-authored YAML uses block style only: no non-empty flow mappings or sequences ({a: b}, [a, b]).

    hack/validate-yaml-block-style.py [repo-root]

Block style is the org's rule for authored YAML: one key per line diffs and reviews cleanly, and a flow collection is
where a quoting mistake hides. Empty collections ({} and []) are allowed, because block style has no way to write them.

Plain YAML files are read through the parser, which reports flow style exactly. Go-templated files (blueprints/*/chart/templates)
are not YAML until rendered, so they are line-scanned for a flow collection opening as a value or a list item, outside
`{{ }}` actions. Out of scope: the vendored upstream CRDs (blueprints/mariadb-operator-crds/chart/templates/crds.yaml, kept byte
equal to upstream by hack/validate-crds-vendored.py) and fetched subcharts (blueprints/*/chart/charts/).

Fails (2) when PyYAML is missing or no YAML file is found.
"""
import os
import re
import sys

try:
    import yaml
except ImportError:
    print("FAILED MEASUREMENT: PyYAML unavailable, so no file was read")
    sys.exit(2)

ROOT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
SKIP_FILES = {os.path.join("blueprints", "mariadb-operator-crds", "chart", "templates", "crds.yaml")}
FLOW_LINE = re.compile(r'(?::|^\s*-)\s+(\{(?!\{)[^}\s]|\[[^\]\s])')
failures, parsed, scanned = [], 0, 0


def flow_events(text):
    for ev in yaml.parse(text):
        if isinstance(ev, (yaml.MappingStartEvent, yaml.SequenceStartEvent)) and ev.flow_style:
            yield ev


for dp, dns, fns in os.walk(ROOT):
    rel_dir = os.path.relpath(dp, ROOT)
    dns[:] = [d for d in dns if d not in (".git", "charts") and not d.startswith(".tmp")]
    for fn in fns:
        if not fn.endswith((".yaml", ".yml")):
            continue
        rel = os.path.normpath(os.path.join(rel_dir, fn))
        if rel in SKIP_FILES:
            continue
        text = open(os.path.join(dp, fn)).read()
        templated = "{{" in text or "/templates/" in "/" + rel.replace(os.sep, "/")
        if not templated:
            parsed += 1
            try:
                for ev in flow_events(text):
                    # An empty flow collection is the only way to write an empty one: allowed.
                    line = text.split("\n")[ev.start_mark.line]
                    rest = line[ev.start_mark.column:]
                    if not re.match(r"^(\{\s*\}|\[\s*\])", rest):
                        failures.append("%s:%d: flow collection %r" % (rel, ev.start_mark.line + 1, rest.strip()[:60]))
            except yaml.YAMLError as e:
                failures.append("%s: not parseable YAML: %s" % (rel, str(e).splitlines()[0]))
        else:
            scanned += 1
            for n, line in enumerate(text.split("\n"), 1):
                code = re.sub(r"\{\{.*?\}\}", "", line)
                if code.lstrip().startswith("#"):
                    continue
                if FLOW_LINE.search(code):
                    failures.append("%s:%d: flow collection in %r" % (rel, n, line.strip()[:80]))

if parsed + scanned == 0:
    print("FAILED MEASUREMENT: no YAML file found under %s" % ROOT)
    sys.exit(2)
if failures:
    for f in failures:
        print("FAIL: " + f)
    sys.exit(1)
print("OK: no non-empty flow collection in %d YAML file(s) (%d parsed, %d Go-templated and line-scanned)"
      % (parsed + scanned, parsed, scanned))
