// Command gen produces the conformance corpus for the selector packages.
//
// It generates random selectors, label sets, LabelSelector objects and field
// selectors, runs each through k8s.io/apimachinery (the oracle) and writes one
// JSON object per line. Usage:
//
//	go run ./gen -seed 1 -scale 1 -out corpus.jsonl
//
// The output depends only on the seed, the scale and the apimachinery version.
package main

import (
	"bufio"
	"encoding/json"
	"flag"
	"fmt"
	"math/rand/v2"
	"os"
	"sort"
	"strings"

	"k8s.io/apimachinery/pkg/api/validate/content"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/fields"
	"k8s.io/apimachinery/pkg/labels"
	"k8s.io/apimachinery/pkg/selection"
)

var rng *rand.Rand

func pick[T any](xs []T) T  { return xs[rng.IntN(len(xs))] }
func chance(p float64) bool { return rng.Float64() < p }

var longName = strings.Repeat("k", 63)
var longName64 = strings.Repeat("k", 64)
var longPrefix = strings.Repeat("a", 250) + ".io"

var validKeys = []string{
	"app", "env", "tier", "a", "b", "x_y", "A-b.c", "k8s-app", "9", "in", "notin", "gt", "lt", "exists",
	"example.com/app", "kubernetes.io/name", "app.kubernetes.io/name", "x.y.z/w", "a-b.c/D_e", "a/b",
	longName, "example.com/" + longName, "release", "node", "zone", "team", "Version",
}
var invalidKeys = []string{
	"-a", "a-", ".a", "a.", "_x", "x_", "a/b/c", "/a", "a/", "/", "Example.COM/x", "a@b", "ü", "a_b/c",
	longName64, "example.com/" + longName64, longPrefix + "/b", "a..b/c", "-x/y", "x-/y", "a b", "*", "a:b", "é/x", "a​",
	"a\\b", "a'b", "a\"b", "a%b",
}
var validVals = []string{
	"v1", "prod", "dev", "1", "a-b", "A_b.c", "", "true", "web", "db", "5", "10", "0", "-5x", "x-y_z.w",
	longName, "1.0", "us-east-1", "Z",
}
var invalidVals = []string{
	"-x", "x-", ".x", "x.", "_x", "a b", "ü", longName64, "a/b", "a@b", "a,b", "a=b", "a b", "a b", "a\tb", "a\x01b", "\U0001F600", "a<b>&c",
}
var intVals = []string{"0", "5", "10", "1", "7", "100", "9223372036854775807", "9223372036854775808", "99999999999999999999", "+7", "007", "5.0", "abc", "1e3", "0x10", "1_000"}

func genKey() string {
	switch r := rng.Float64(); {
	case r < 0.78:
		return pick(validKeys)
	case r < 0.90:
		return pick(invalidKeys)
	default:
		n := 1 + rng.IntN(5)
		var sb strings.Builder
		for i := 0; i < n; i++ {
			sb.WriteByte("ab-_./AZ09"[rng.IntN(10)])
		}
		return sb.String()
	}
}
func genVal() string {
	switch r := rng.Float64(); {
	case r < 0.80:
		return pick(validVals)
	case r < 0.88:
		return pick(intVals)
	case r < 0.94:
		return pick(invalidVals)
	default:
		n := rng.IntN(5)
		var sb strings.Builder
		for i := 0; i < n; i++ {
			sb.WriteByte("ab-_.AZ09"[rng.IntN(9)])
		}
		return sb.String()
	}
}
func ws() string {
	switch r := rng.Float64(); {
	case r < 0.55:
		return ""
	case r < 0.85:
		return " "
	case r < 0.92:
		return "  "
	case r < 0.96:
		return "\t"
	case r < 0.985:
		return pick([]string{"\n", "\r", "\r\n", " \t "})
	default:
		return pick([]string{"\x00", "\x0b", " ", "\f", "　"})
	}
}
func wsSp() string { // mandatory separator
	switch r := rng.Float64(); {
	case r < 0.75:
		return " "
	case r < 0.9:
		return "  "
	case r < 0.97:
		return "\t"
	default:
		return "\n"
	}
}

var noiseOps = []string{"=", "==", "!=", "in", "notin", "", "!", ">", "<", "=!", "===", "!==", ">=", "<=", "=<", "!!", "=>", "gt", "lt", "IN", "In", "NotIn", "not in", "~", ":", "<>", "><", "!in", "=in"}

func genReq() string {
	k := genKey()
	r := rng.Float64()
	switch {
	case r < 0.28: // exact
		o := pick([]string{"=", "==", "!="})
		return k + ws() + o + ws() + genVal()
	case r < 0.36: // gt lt
		o := pick([]string{">", "<"})
		return k + ws() + o + ws() + genVal()
	case r < 0.60: // set
		o := pick([]string{"in", "notin"})
		n := pick([]int{0, 1, 1, 1, 2, 2, 3, 4})
		vs := make([]string, n)
		for i := range vs {
			vs[i] = genVal()
		}
		sep := ","
		if chance(0.2) {
			sep = ws() + "," + ws()
		}
		sp := wsSp()
		if chance(0.08) {
			sp = ""
		}
		return k + sp + o + ws() + "(" + ws() + strings.Join(vs, sep) + ws() + ")"
	case r < 0.72:
		return k
	case r < 0.82:
		return "!" + ws() + k
	default: // noise
		o := pick(noiseOps)
		if chance(0.5) {
			return k + wsSp() + o + wsSp() + genVal()
		}
		return k + ws() + o + ws() + genVal()
	}
}

func genSel() string {
	n := pick([]int{0, 1, 1, 1, 2, 2, 2, 3, 3, 4, 5, 8, 12, 13, 15})
	rs := make([]string, n)
	for i := range rs {
		rs[i] = genReq()
	}
	sep := ","
	var sb strings.Builder
	sb.WriteString(ws())
	for i, r := range rs {
		if i > 0 {
			s := sep
			if chance(0.15) {
				s = ws() + "," + ws()
			}
			if chance(0.02) {
				s = ",,"
			}
			sb.WriteString(s)
		}
		sb.WriteString(r)
	}
	if chance(0.02) {
		sb.WriteString(",")
	}
	if chance(0.01) {
		return "," + sb.String() + ws()
	}
	sb.WriteString(ws())
	return sb.String()
}

// genManySel builds selectors with many requirements over few keys, which exercises Go's unstable sort.
func genManySel() string {
	n := 13 + rng.IntN(60)
	keys := []string{"a", "b", "c", "d", "e"}[:2+rng.IntN(4)]
	parts := make([]string, n)
	for i := range parts {
		k := pick(keys)
		switch rng.IntN(5) {
		case 0:
			parts[i] = k + "=" + pick(validVals)
		case 1:
			parts[i] = k + "!=" + pick(validVals)
		case 2:
			parts[i] = k + " in (" + pick(validVals) + ")"
		case 3:
			parts[i] = pick([]string{k, "!" + k})
		default:
			parts[i] = k + " notin (" + pick(validVals) + "," + pick(validVals) + ")"
		}
	}
	return strings.Join(parts, ",")
}

func genDupSel() string {
	// duplicate keys / duplicate requirements
	k := pick(validKeys[:8])
	parts := []string{}
	for i := 0; i < 2+rng.IntN(3); i++ {
		switch rng.IntN(4) {
		case 0:
			parts = append(parts, k+"="+pick(validVals))
		case 1:
			parts = append(parts, k+"!="+pick(validVals))
		case 2:
			parts = append(parts, k+" in ("+pick(validVals)+","+pick(validVals)+","+pick(validVals)+")")
		default:
			parts = append(parts, pick([]string{k, "!" + k}))
		}
	}
	return strings.Join(parts, ",")
}

const mutChars = "=!(),<>\x00 \t\n'\"\\/-_.aZ9"

func mutate(s string) string {
	b := []rune(s)
	for n := 1 + rng.IntN(2); n > 0; n-- {
		if len(b) == 0 {
			b = []rune{rune(mutChars[rng.IntN(len(mutChars))])}
			continue
		}
		i := rng.IntN(len(b))
		c := rune(mutChars[rng.IntN(len(mutChars))])
		switch rng.IntN(4) {
		case 0:
			b = append(b[:i], b[i+1:]...)
		case 1:
			b = append(b[:i], append([]rune{c}, b[i:]...)...)
		case 2:
			b[i] = c
		default:
			j := rng.IntN(len(b))
			b[i], b[j] = b[j], b[i]
		}
	}
	return string(b)
}

func genLabelSets(reqs []labels.Requirement, n int) []map[string]string {
	sets := []map[string]string{{}}
	base := map[string]string{}
	for _, r := range reqs {
		vs := r.ValuesUnsorted()
		switch r.Operator() {
		case selection.In, selection.Equals, selection.DoubleEquals, selection.NotIn, selection.NotEquals:
			if len(vs) > 0 {
				if chance(0.7) {
					base[r.Key()] = pick(vs)
				} else {
					base[r.Key()] = genVal()
				}
			}
		case selection.Exists:
			if chance(0.8) {
				base[r.Key()] = genVal()
			}
		case selection.GreaterThan, selection.LessThan:
			base[r.Key()] = pick(intVals)
		}
	}
	cp := func() map[string]string {
		m := map[string]string{}
		for k, v := range base {
			m[k] = v
		}
		return m
	}
	sets = append(sets, cp())
	for len(sets) < n {
		m := cp()
		switch rng.IntN(5) {
		case 0:
			for k := range m {
				delete(m, k)
				break
			}
		case 1:
			for k := range m {
				m[k] = genVal()
				break
			}
		case 2:
			m[genKey()] = genVal()
		case 3:
			m = map[string]string{}
			for i := rng.IntN(4); i > 0; i-- {
				m[pick(validKeys)] = pick(validVals)
			}
		default:
			for k := range m {
				m[k] = pick(intVals)
			}
		}
		sets = append(sets, m)
	}
	return sets
}

type reqOut struct {
	K string   `json:"k"`
	O string   `json:"o"`
	V []string `json:"v"`
}

func reqsOut(rs labels.Requirements) []reqOut {
	out := []reqOut{}
	for _, r := range rs {
		vs := r.Values().List()
		out = append(out, reqOut{r.Key(), string(r.Operator()), vs})
	}
	return out
}

func bits(sel labels.Selector, sets []map[string]string) string {
	var sb strings.Builder
	for _, s := range sets {
		if sel.Matches(labels.Set(s)) {
			sb.WriteByte('1')
		} else {
			sb.WriteByte('0')
		}
	}
	return sb.String()
}

type rxOut struct {
	K string `json:"k"`
	V string `json:"v"`
	F bool   `json:"f"`
}

func rxOf(sel labels.Selector, rs labels.Requirements) []rxOut {
	out := []rxOut{}
	seen := map[string]bool{}
	for _, r := range rs {
		if seen[r.Key()] {
			continue
		}
		seen[r.Key()] = true
		v, f := sel.RequiresExactMatch(r.Key())
		out = append(out, rxOut{r.Key(), v, f})
	}
	v, f := sel.RequiresExactMatch("zzz-missing")
	out = append(out, rxOut{"zzz-missing", v, f})
	return out
}

type plsOut struct {
	Ok  bool                  `json:"ok"`
	Err string                `json:"e,omitempty"`
	O   *metav1.LabelSelector `json:"o,omitempty"`
}

type selRec struct {
	Kind  string              `json:"t"`
	S     string              `json:"s"`
	Ok    bool                `json:"ok"`
	Str   string              `json:"str,omitempty"`
	Err   string              `json:"e,omitempty"`
	Empty bool                `json:"em,omitempty"`
	Rq    []reqOut            `json:"rq,omitempty"`
	Ls    []map[string]string `json:"ls,omitempty"`
	M     string              `json:"m,omitempty"`
	Rx    []rxOut             `json:"rx,omitempty"`
	Pls   *plsOut             `json:"pls,omitempty"`
}

func doSel(s string) selRec {
	rec := selRec{Kind: "sel", S: s}
	sel, err := labels.Parse(s)
	if err != nil {
		rec.Err = err.Error()
	} else {
		rec.Ok = true
		rec.Str = sel.String()
		rec.Empty = sel.Empty()
		rs, _ := sel.Requirements()
		rec.Rq = reqsOut(rs)
		rec.Ls = genLabelSets(rs, 4)
		rec.M = bits(sel, rec.Ls)
		rec.Rx = rxOf(sel, rs)
	}
	ls, perr := metav1.ParseToLabelSelector(s)
	if perr != nil {
		rec.Pls = &plsOut{Err: perr.Error()}
	} else {
		rec.Pls = &plsOut{Ok: true, O: ls}
	}
	return rec
}

// ---- LabelSelector objects

type lsExpr struct {
	Key      string   `json:"key"`
	Operator string   `json:"operator"`
	Values   []string `json:"values,omitempty"`
}
type lsObj struct {
	MatchLabels      map[string]string `json:"matchLabels,omitempty"`
	MatchExpressions []lsExpr          `json:"matchExpressions,omitempty"`
}

func toMeta(o *lsObj) *metav1.LabelSelector {
	if o == nil {
		return nil
	}
	ls := &metav1.LabelSelector{}
	if o.MatchLabels != nil {
		ls.MatchLabels = o.MatchLabels
	}
	for _, e := range o.MatchExpressions {
		ls.MatchExpressions = append(ls.MatchExpressions, metav1.LabelSelectorRequirement{Key: e.Key, Operator: metav1.LabelSelectorOperator(e.Operator), Values: e.Values})
	}
	return ls
}

func labelInvalid(k, v string) bool {
	_, err := labels.NewRequirement(k, selection.Equals, []string{v})
	return err != nil
}

type mapOut struct {
	Ok  bool              `json:"ok"`
	Err string            `json:"e,omitempty"`
	M   map[string]string `json:"m,omitempty"`
	Nil bool              `json:"nil,omitempty"`
}

type lselRec struct {
	Kind  string              `json:"t"`
	O     *lsObj              `json:"o"`
	Ok    bool                `json:"ok"`
	Str   string              `json:"str,omitempty"`
	Err   string              `json:"e,omitempty"`
	Empty bool                `json:"em,omitempty"`
	Noth  bool                `json:"nothing,omitempty"`
	Rq    []reqOut            `json:"rq,omitempty"`
	Ls    []map[string]string `json:"ls,omitempty"`
	M     string              `json:"m,omitempty"`
	Fmt   string              `json:"fmt"`
	Map   mapOut              `json:"map"`
}

func genLsObj() *lsObj {
	if chance(0.02) {
		return nil
	}
	o := &lsObj{}
	invalid := 0
	if chance(0.6) {
		o.MatchLabels = map[string]string{}
		for i := rng.IntN(4); i >= 0 && chance(0.9); i-- {
			k, v := genKey(), genVal()
			if chance(0.85) {
				k, v = pick(validKeys), pick(validVals)
			}
			o.MatchLabels[k] = v
		}
		for k, v := range o.MatchLabels {
			if labelInvalid(k, v) {
				invalid++
			}
		}
		if invalid > 1 {
			o.MatchLabels = map[string]string{"app": "x"}
		}
	}
	ops := []string{"In", "NotIn", "Exists", "DoesNotExist", "In", "NotIn", "Exists", "DoesNotExist", "in", "Gt", "", "exists", "Equals"}
	for i := rng.IntN(4); i > 0 || (i == 0 && chance(0.1)); i-- {
		e := lsExpr{Key: genKey(), Operator: pick(ops)}
		if chance(0.8) {
			e.Key = pick(validKeys)
		}
		switch e.Operator {
		case "Exists", "DoesNotExist":
			if chance(0.9) {
				break
			}
			e.Values = []string{genVal()}
		default:
			n := pick([]int{0, 1, 1, 2, 2, 3})
			for j := 0; j < n; j++ {
				e.Values = append(e.Values, genVal())
			}
			if chance(0.15) && n > 0 {
				e.Values = append(e.Values, e.Values[0])
			}
		}
		o.MatchExpressions = append(o.MatchExpressions, e)
		if i == 0 {
			break
		}
	}
	return o
}

func doLsel(o *lsObj) lselRec {
	rec := lselRec{Kind: "lsel", O: o}
	m := toMeta(o)
	sel, err := metav1.LabelSelectorAsSelector(m)
	if err != nil {
		rec.Err = err.Error()
	} else {
		rec.Ok = true
		rec.Str = sel.String()
		rec.Empty = sel.Empty()
		rs, selectable := sel.Requirements()
		rec.Noth = !selectable
		rec.Rq = reqsOut(rs)
		rec.Ls = genLabelSets(rs, 4)
		rec.M = bits(sel, rec.Ls)
	}
	rec.Fmt = metav1.FormatLabelSelector(m)
	mp, merr := metav1.LabelSelectorAsMap(m)
	if merr != nil {
		rec.Map = mapOut{Err: merr.Error()}
	} else {
		rec.Map = mapOut{Ok: true, M: mp, Nil: mp == nil}
	}
	return rec
}

// ---- Requirement API

type reqRec struct {
	Kind string              `json:"t"`
	Key  string              `json:"key"`
	Op   string              `json:"op"`
	Vals []string            `json:"vals"`
	Ok   bool                `json:"ok"`
	Err  string              `json:"e,omitempty"`
	Str  string              `json:"str,omitempty"`
	Uns  []string            `json:"uns,omitempty"`
	Srt  []string            `json:"srt,omitempty"`
	Ls   []map[string]string `json:"ls,omitempty"`
	M    string              `json:"m,omitempty"`
}

func doReq() reqRec {
	ops := []string{"in", "notin", "=", "==", "!=", "exists", "!", "gt", "lt", "in", "notin", "=", "!=", "exists", "!", "gt", "lt", "", ">", "Exists", "DoesNotExist", "eq"}
	rec := reqRec{Kind: "req", Key: genKey(), Op: pick(ops)}
	if chance(0.85) {
		rec.Key = pick(validKeys)
	}
	switch r := rng.Float64(); {
	case r < 0.1:
		rec.Vals = nil
	case r < 0.2:
		rec.Vals = []string{}
	default:
		n := pick([]int{1, 1, 1, 2, 3})
		rec.Vals = []string{}
		for i := 0; i < n; i++ {
			rec.Vals = append(rec.Vals, genVal())
		}
		if chance(0.1) {
			rec.Vals = append(rec.Vals, rec.Vals[0])
		}
		if chance(0.05) {
			rec.Vals = append(rec.Vals, "z", "a")
		}
	}
	req, err := labels.NewRequirement(rec.Key, selection.Operator(rec.Op), rec.Vals)
	if err != nil {
		rec.Err = err.Error()
		return rec
	}
	rec.Ok = true
	rec.Str = req.String()
	rec.Uns = req.ValuesUnsorted()
	rec.Srt = req.Values().List()
	rec.Ls = genLabelSets([]labels.Requirement{*req}, 4)
	var sb strings.Builder
	for _, s := range rec.Ls {
		if req.Matches(labels.Set(s)) {
			sb.WriteByte('1')
		} else {
			sb.WriteByte('0')
		}
	}
	rec.M = sb.String()
	return rec
}

// ---- Set selectors

type setRec struct {
	Kind string              `json:"t"`
	Set  map[string]string   `json:"set"`
	Nil  bool                `json:"nil,omitempty"`
	Str  string              `json:"str"`
	Em   bool                `json:"em"`
	Vok  bool                `json:"vok"`
	Verr string              `json:"ve,omitempty"`
	Vstr string              `json:"vstr,omitempty"`
	Ls   []map[string]string `json:"ls"`
	M    string              `json:"m"`
}

func doSet() setRec {
	rec := setRec{Kind: "set", Set: map[string]string{}}
	bad := 0
	for i := rng.IntN(4); i > 0; i-- {
		k, v := pick(validKeys), pick(validVals)
		if chance(0.15) {
			k, v = genKey(), genVal()
		}
		rec.Set[k] = v
	}
	for k, v := range rec.Set {
		if labelInvalid(k, v) {
			bad++
		}
	}
	if bad > 1 {
		rec.Set = map[string]string{"a": "b"}
	}
	if len(rec.Set) == 0 && chance(0.3) {
		rec.Nil = true
		rec.Set = nil
	}
	sel := labels.SelectorFromSet(labels.Set(rec.Set))
	rec.Str = sel.String()
	rec.Em = sel.Empty()
	vs, err := labels.ValidatedSelectorFromSet(labels.Set(rec.Set))
	if err != nil {
		rec.Verr = err.Error()
	} else {
		rec.Vok = true
		rec.Vstr = vs.String()
	}
	rs, _ := sel.Requirements()
	rec.Ls = genLabelSets(rs, 4)
	rec.M = bits(sel, rec.Ls)
	return rec
}

// ---- validation

type valRec struct {
	Kind string   `json:"t"`
	S    string   `json:"s"`
	Key  []string `json:"key"`
	Val  []string `json:"val"`
}

func doVal() valRec {
	var s string
	switch rng.IntN(6) {
	case 0:
		s = genKey()
	case 1:
		s = genVal()
	case 2:
		s = pick(validKeys) + "/" + pick(validKeys)
	case 3:
		s = strings.Repeat("a", 60+rng.IntN(8))
		if chance(0.5) {
			s += pick([]string{"-", ".", "_", "!", ""})
		}
	case 4:
		s = strings.Repeat(pick([]string{"a", "a.", "a-"}), 100+rng.IntN(100)) + pick([]string{"", "a", "-", ".", "/x"})
	default:
		n := rng.IntN(8)
		var sb strings.Builder
		for i := 0; i < n; i++ {
			sb.WriteString(pick([]string{"a", "Z", "0", "-", "_", ".", "/", " ", "é", "\U0001F600", "\n", "A.b"}))
		}
		s = sb.String()
	}
	k := content.IsLabelKey(s)
	v := content.IsLabelValue(s)
	if k == nil {
		k = []string{}
	}
	if v == nil {
		v = []string{}
	}
	return valRec{"val", s, k, v}
}

// ---- fields

var fieldNames = []string{"metadata.name", "metadata.namespace", "spec.nodeName", "status.phase", "a", "b", "x.y", "spec.restartPolicy", "", "a b", "é", "a\\b", "f-1", "F"}
var fieldVals = []string{"v", "", "Running", "default", "a\\,b", "a\\=b", "a\\\\b", "a\\", "a,b", "a=b", "\\x", "ü", "a\\\\,b", "\\\\", "\\,", "\\=", "x y", "1", "a\\\\\\,b", "a\\=\\=b"}

func genFieldTerm() string {
	f := pick(fieldNames)
	r := rng.Float64()
	var op string
	switch {
	case r < 0.4:
		op = "="
	case r < 0.65:
		op = "=="
	case r < 0.9:
		op = "!="
	default:
		op = pick([]string{"", "!", "=!", "!==", "===", "<", ">", "in", "!!="})
	}
	v := pick(fieldVals)
	if chance(0.15) {
		var sb strings.Builder
		for i := rng.IntN(5); i > 0; i-- {
			sb.WriteByte("ab\\,=!"[rng.IntN(6)])
		}
		v = sb.String()
	}
	if chance(0.1) {
		f = pick([]string{"a=b", "a!", "a\\", "x,y"}) // odd lhs
	}
	return f + op + v
}

type frq struct {
	O string `json:"o"`
	F string `json:"f"`
	V string `json:"v"`
}
type fldRec struct {
	Kind string              `json:"t"`
	S    string              `json:"s"`
	Ok   bool                `json:"ok"`
	Str  string              `json:"str,omitempty"`
	Err  string              `json:"e,omitempty"`
	Em   bool                `json:"em,omitempty"`
	Rq   []frq               `json:"rq,omitempty"`
	Fs   []map[string]string `json:"fs,omitempty"`
	M    string              `json:"m,omitempty"`
	Rx   []rxOut             `json:"rx,omitempty"`
}

func doFld(s string) fldRec {
	rec := fldRec{Kind: "fld", S: s}
	sel, err := fields.ParseSelector(s)
	if err != nil {
		rec.Err = err.Error()
		return rec
	}
	rec.Ok = true
	rec.Str = sel.String()
	rec.Em = sel.Empty()
	rec.Rq = []frq{}
	base := map[string]string{}
	for _, r := range sel.Requirements() {
		rec.Rq = append(rec.Rq, frq{string(r.Operator), r.Field, r.Value})
		if r.Operator == selection.Equals || chance(0.3) {
			base[r.Field] = r.Value
		} else if chance(0.5) {
			base[r.Field] = pick(fieldVals)
		}
	}
	sets := []map[string]string{{}, base}
	for len(sets) < 4 {
		m := map[string]string{}
		for k, v := range base {
			m[k] = v
		}
		switch rng.IntN(3) {
		case 0:
			for k := range m {
				delete(m, k)
				break
			}
		case 1:
			for k := range m {
				m[k] = pick(fieldVals)
				break
			}
		default:
			m[pick(fieldNames)] = pick(fieldVals)
		}
		sets = append(sets, m)
	}
	rec.Fs = sets
	var sb strings.Builder
	for _, m := range sets {
		if sel.Matches(fields.Set(m)) {
			sb.WriteByte('1')
		} else {
			sb.WriteByte('0')
		}
	}
	rec.M = sb.String()
	rec.Rx = []rxOut{}
	seen := map[string]bool{}
	for _, r := range sel.Requirements() {
		if seen[r.Field] {
			continue
		}
		seen[r.Field] = true
		v, f := sel.RequiresExactMatch(r.Field)
		rec.Rx = append(rec.Rx, rxOut{r.Field, v, f})
	}
	return rec
}

func genFld() string {
	if chance(0.05) {
		return ""
	}
	n := pick([]int{1, 1, 2, 2, 3, 4, 6, 14})
	ts := make([]string, n)
	for i := range ts {
		ts[i] = genFieldTerm()
	}
	if chance(0.03) {
		ts = append(ts, "")
	}
	s := strings.Join(ts, ",")
	if chance(0.05) {
		s += ","
	}
	return s
}

type escRec struct {
	Kind string `json:"t"`
	V    string `json:"v"`
	Esc  string `json:"esc"`
	Ok   bool   `json:"ok"`
	Out  string `json:"out,omitempty"`
	Err  string `json:"e,omitempty"`
}

func doEsc() escRec {
	var sb strings.Builder
	for i := rng.IntN(7); i > 0; i-- {
		sb.WriteString(pick([]string{"a", "\\", ",", "=", "\\\\", "\\,", "\\=", "b", "ü", "\\n", " "}))
	}
	v := sb.String()
	rec := escRec{Kind: "esc", V: v, Esc: fields.EscapeValue(v)}
	out, err := fields.UnescapeValue(v)
	if err != nil {
		rec.Err = err.Error()
	} else {
		rec.Ok = true
		rec.Out = out
	}
	return rec
}

func main() {
	seed := flag.Uint64("seed", 1, "PRNG seed")
	scale := flag.Float64("scale", 1, "corpus size multiplier")
	out := flag.String("out", "corpus.jsonl", "output file")
	flag.Parse()
	rng = rand.New(rand.NewPCG(*seed, 0x6b38735f73656c))
	f, err := os.Create(*out)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	w := bufio.NewWriterSize(f, 1<<20)
	enc := json.NewEncoder(w)
	n := func(base int) int { return max(1, int(float64(base)**scale)) }
	emit := func(v any) {
		if err := enc.Encode(v); err != nil {
			panic(err)
		}
	}

	// fixed selectors first
	fixed := []string{"", "app=web", "app!=web", "!app", "app", "app in (a,b)", "app notin (a,b)", "a=b,c=d", "a==b", "a = b", "a in ()", "a in (b,)", "a in (,b)", "a in(b)", "a notin(b, c)", "a gt 1", "a>1", "a<2", "a > 1", "a in (b) ,c", "in in (in)", "notin=notin", "in", "notin", "!in", "a in (b", "a in b)", "x=y=z", "a=", "=b", "a=b,", "!!a", "! a", "x in (foo,,baz),y,z notin ()", "a in (b,c,b)", "a in (c,b)", "b=1,a=2", "a=1,a=2", "a=1,a!=1", "a,!a", " a", "a\x00b", "a=\x00", "a in (b\x00)", "a\n=\nb", "a\r\n!=\r\nb", "  ", ",", "a,,b", "a=b c", "a=b,,c=d", "!", "a ! = b", "a!==b", "a=!b", "a<=3", "a=>3", "a>-1", "a>99999999999999999999", "a < 5, a > 1", "key in (v1, v2), other notin (x)", "z=1,y=2,x=3,w=4,v=5,u=6,t=7,s=8,r=9,q=10,p=11,o=12,n=13,m=14"}
	for _, s := range fixed {
		emit(doSel(s))
	}
	for i := 0; i < n(24000); i++ {
		var s string
		switch r := rng.Float64(); {
		case r < 0.55:
			s = genSel()
		case r < 0.65:
			s = genDupSel()
		default:
			base := genSel()
			for tries := 0; tries < 20; tries++ {
				if _, e := labels.Parse(base); e == nil && base != "" {
					break
				}
				base = genSel()
			}
			s = mutate(base)
		}
		emit(doSel(s))
	}
	for i := 0; i < n(2500); i++ {
		emit(doSel(genManySel()))
	}
	for i := 0; i < n(5600); i++ {
		emit(doLsel(genLsObj()))
	}
	emit(doLsel(nil))
	emit(doLsel(&lsObj{}))
	for i := 0; i < n(3000); i++ {
		emit(doReq())
	}
	for i := 0; i < n(1500); i++ {
		emit(doSet())
	}
	for i := 0; i < n(6000); i++ {
		emit(doVal())
	}
	ffixed := []string{"", "a=b", "a==b", "a!=b", "a=b,c!=d", "a=b=c", "a=\\", "a=\\x", "a=b\\,c", "a=b,,c=d", "=", "==", "!=", "=,=", "a", "a!b", ",", "a=b,", "metadata.name=foo,metadata.namespace!=bar", "a=\\\\,b=c", "a!=b,a=b", "b=1,a=1", "a=\\=", "a=,b=", "spec.nodeName=", "x=y\\,z", "x\\=y=z"}
	for _, s := range ffixed {
		emit(doFld(s))
	}
	for i := 0; i < n(5600); i++ {
		emit(doFld(genFld()))
	}
	for i := 0; i < n(2000); i++ {
		emit(doEsc())
	}
	if err := w.Flush(); err != nil {
		panic(err)
	}
	f.Close()
	_ = sort.Strings
}
