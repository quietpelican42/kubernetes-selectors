# kubernetes-selectors

Parse and match Kubernetes label selectors and field selectors with the grammar, error messages and canonical strings of `k8s.io/apimachinery`.

```python
from kubernetes_selectors import parse_selector, parse_field_selector

sel = parse_selector("tier in (b,a), app=web, !legacy")
str(sel)                                      # 'app=web,!legacy,tier in (a,b)'
sel.matches({"app": "web", "tier": "a"})      # True
sel.matches({"app": "web", "tier": "a", "legacy": "1"})  # False

parse_field_selector("status.phase!=Failed").matches({"status.phase": "Running"})  # True
```

## Why

Python Kubernetes libraries build selector strings but do not parse them. Code that needs to evaluate a selector outside a cluster (mock servers, policy checkers, CLIs that filter cached objects) writes its own. The rules are subtle: an empty selector matches everything, `!=` and `notin` match objects that lack the key, keys and values are validated, and `String()` sorts requirements and values.

Hand-written copies exist in `jumpstarter-dev/jumpstarter` (`selectors.py`), `hcgatewood/kuba` (`matches_label_selector`) and `akuity/kargo` (a TypeScript equivalent). This package is a port of the Go code, checked against Go output.

Incumbents checked: `kubernetes` 36.0.3, `kr8s` 0.20.15 and `lightkube` 1.0.1 expose no function that parses or matches a selector string (name scan of their non-model modules with `python bench/incumbents.py`). `pykube-ng` was not scanned, because importing `pykube.console` starts an interactive shell. PyPI has no other package with a selector or label-selector name (checked against the full simple index on 2026-09-29; `libkubeselector` 0.0.3 has no downloadable files).

Measured: `python bench/jumpstarter.py`, the parser in `jumpstarter-dev/jumpstarter` at commit `c6f3978` against the 26,562 selectors of the shared corpus (9,103 are valid in Go). That function is not meant as a validator and skips parts it cannot read, so the first line describes its intent, not a defect:

```
Go-invalid selectors: 17459, silently accepted by jumpstarter parse_label_selector: 17459 (100.00%)
Go-valid selectors: 9103, parsed to the same requirements: 6858 (75.34%)
match results (Go-valid, no gt/lt): 33357/35460 equal (94.07%)
```

This package agrees with Go on every record of the same corpus (see Development).

## Installation

```sh
pip install kubernetes-selectors
```

Python 3.11 or newer. No runtime dependencies. Typed (`py.typed`).

## Usage

### Parse errors

Errors are `SelectorError` (a `ValueError`) and carry the text Go produces.

```python
try:
    parse_selector("-a=b")
except SelectorError as e:
    print(e)
    # unable to parse requirement: <nil>: Invalid value: "-a": name part must consist of
    # alphanumeric characters, '-', '_' or '.', and must start and end with an alphanumeric
    # character (e.g. 'MyName',  or 'my.name',  or '123-abc', regex used for validation is
    # '([A-Za-z0-9][-A-Za-z0-9_.]*)?[A-Za-z0-9]')
```

### LabelSelector objects

`label_selector_as_selector` mirrors `metav1.LabelSelectorAsSelector` (`None` matches nothing, `{}` matches everything). `parse_to_label_selector`, `label_selector_as_map`, `set_as_label_selector` and `format_label_selector` mirror the other `metav1` helpers. Objects are plain dicts with the Kubernetes field names.

```python
label_selector_as_selector({
    "matchLabels": {"app": "web"},
    "matchExpressions": [{"key": "tier", "operator": "NotIn", "values": ["b", "a"]}],
})  # Selector('app=web,tier notin (a,b)')
```

### Field selectors

```python
f = parse_field_selector("status.phase!=Failed,metadata.name==a\\,b")
str(f)  # 'metadata.name=a\\,b,status.phase!=Failed'
```

A field missing from the mapping reads as the empty string, as in Go.

### Validation

```python
validate_label_value("x" * 64)  # ['must be no more than 63 bytes']
validate_label_key("example.com/name")  # []
```

## Reference

Label selectors:

| Function | Description |
| --- | --- |
| `parse_selector(s)` | `labels.Parse`. Returns a `Selector`, raises `SelectorError`. |
| `parse_requirements(s)` | `labels.ParseToRequirements`. Sorted list of `Requirement`. |
| `matches(selector, labels)` | Selector (str or `Selector`) against any mapping. |
| `new_requirement(key, op, values=None)` | `labels.NewRequirement`. Operators: `in notin = == != exists ! gt lt`. |
| `selector_from_set(labels)` | `labels.SelectorFromSet`. No validation. |
| `validated_selector_from_set(labels)` | `labels.ValidatedSelectorFromSet`. |
| `everything()` / `nothing()` | Selectors that match all or no label sets. |
| `validate_label_key(s)` / `validate_label_value(s)` | `IsQualifiedName` / `IsValidLabelValue` error strings. Empty list means valid. |

`Selector`: `matches(labels)`, `empty()`, `selectable`, `requirements()`, `add(*reqs)`, `requires_exact_match(key)` (value or `None`), `str()`.
`Requirement`: `key`, `operator`, `values()` (sorted, de-duplicated), `values_unsorted()`, `matches(labels)`, `str()`.

Objects: `label_selector_as_selector`, `label_selector_as_map`, `parse_to_label_selector`, `set_as_label_selector`, `format_label_selector`.

Field selectors: `parse_field_selector`, `field_selector_from_set`, `everything_fields`, `nothing_fields`, `escape_field_value`, `unescape_field_value`, and `FieldSelector` (`matches`, `empty`, `requirements`, `requires_exact_match`, `str()`).

## How it works

The lexer and parser are ports of `pkg/labels/selector.go`, including its quirks: a NUL character ends a token, `!a=b` fails at the `=`, `x in ()` means the single value `""`, and `Gt`/`Lt` (`a>1`) are accepted. Requirements are ordered with a port of Go's `sort.Sort` (pdqsort), because Go's sort is not stable and equal keys keep Go's order only under the same algorithm. Key and value validation uses linear scans instead of regular expressions, so long inputs cannot cause backtracking. Integers for `Gt`/`Lt` follow `strconv.ParseInt` (base 10, ASCII digits, int64 range).

Conformance corpus: `gen/main.go` generates selectors, label sets, `LabelSelector` objects, requirement calls, field selectors and validation strings, runs them through apimachinery v0.37.1, and writes the results. `tests/fixtures/corpus.jsonl.gz` is one such output (seed 1). The Node sibling package `k8s-label-selector` uses the identical file.

## Limitations

- Verified against apimachinery v0.37.1 only. Other releases may differ.
- Strings are Python `str`. Go strings that are not valid UTF-8 cannot be represented.
- `field_selector_from_set` sorts by field. Go iterates a map in random order, so its string form for several fields is not deterministic.
- Go's `Transform`/`ParseAndTransformSelector`, `labels.Set` helpers (`Merge`, `Conflicts`, `Set.String`) and `ValidatedSetSelector` are not provided.
- The sort port follows Go 1.19 and later. A Go toolchain older than that orders equal keys differently.

## Compatibility

Run here: Python 3.14.7, mypy (strict), Go 1.27.1 for the oracle. The CI workflow lists Python 3.11 to 3.14; only 3.14 has been run.

## Development

```sh
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -q   # includes the corpus and, when `go` is available, a live run against Go
.venv/bin/python -m mypy --strict
```

`tests/test_live.py` runs `go run ./gen` with a fresh random seed and checks every record. It skips with a loud message when `go` or the Go module cache is unavailable. `K8SSEL_SCALE=1` runs a full-size corpus. To regenerate the fixture: `cd gen && GOFLAGS=-mod=mod go run . -seed 1 -out corpus.jsonl && gzip -9 -n corpus.jsonl`.

## License

MIT, see [LICENSE](LICENSE). Files derived from Kubernetes carry the Kubernetes Authors header and are under Apache-2.0, see [LICENSE-apache](LICENSE-apache). `_gosort.py` is derived from the Go standard library, see [LICENSE-go](LICENSE-go).
