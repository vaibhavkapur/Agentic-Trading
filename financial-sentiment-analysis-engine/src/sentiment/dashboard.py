"""Self-contained evaluation view that works in a browser or as an offline file."""
from html import escape
from .domain import LABELS


def render(report):
    models = report["models"]
    result = models["served"]
    names = {"prior":"Training prior", "lexicon":"Finance lexicon", "supervised":"Text classifier",
             "calibrated":"Temperature-scaled", "served":"Served decisions"}
    comparisons = "".join(f"<tr><th>{names[k]}</th><td>{v['macro_f1']:.3f}</td><td>{v['brier']:.3f}</td>"
                          f"<td>{v['ece']:.3f}</td><td>{v['coverage']:.0%}</td></tr>" for k,v in models.items())
    headers = "".join(f"<th>{v.title()}</th>" for v in LABELS)
    grid = "".join("<tr><th>"+k.title()+"</th>"+"".join(f"<td>{result['confusion'][k][v]}</td>"
                   for v in LABELS)+"</tr>" for k in LABELS)
    review = []
    for row in report["test_predictions"]:
        if row["label"] != row["gold"] or row["abstain_reason"]:
            cells = [row["article_id"], row["issuer"], row["gold"], row["label"],
                     (row["abstain_reason"] or "classification error").replace("_"," ")]
            review.append("<tr>"+"".join(f"<td>{escape(v)}</td>" for v in cells)+"</tr>")
    cuts = [s[:10] for s in report["available_cutoffs"]]
    drift = report["drift"]
    return f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Issuer sentiment · Model evaluation</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#f6f5ef;color:#182d29;font:16px/1.55 "Inter",system-ui,sans-serif}}
main{{max-width:1080px;margin:auto;padding:35px clamp(16px,4vw,52px) 64px}}
header{{border-bottom:2px solid #294b42;padding-bottom:22px}}h1,h2{{font-family:"Baskervville",Georgia,serif;font-weight:500}}
h1{{font-size:clamp(38px,6vw,66px);line-height:1.05;margin:12px 0}}h2{{font-size:28px;margin:0 0 10px}}
header small,dt{{color:#39594e}}section{{margin-top:32px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:16px}}
dl{{margin:0;border-left:3px solid #467d69;padding-left:15px}}dd{{margin:4px 0;font:38px Georgia,serif}}
.scroll{{overflow:auto}}table{{width:100%;border-collapse:collapse;background:#fffefa;font-variant-numeric:tabular-nums}}
th,td{{padding:9px 12px;border-bottom:1px solid #d1d8d1;text-align:right}}th:first-child,td:first-child{{text-align:left}}
thead{{background:#e6ebe4}}footer{{margin-top:26px;font:13px monospace;overflow-wrap:anywhere}}
</style><main><header><small>Financial research / Model evaluation</small><h1>Issuer sentiment</h1>
<p>Held-out synthetic desk notes · {cuts[1]} to {cuts[2]} (exclusive), UTC</p></header>
<section class="cards"><dl><dt>Served macro-F1</dt><dd>{result['macro_f1']:.3f}</dd></dl>
<dl><dt>Decision coverage</dt><dd>{result['coverage']:.0%}</dd></dl>
<dl><dt>Evaluated issuer labels</dt><dd>{result['n']}</dd></dl>
<dl><dt>Syndicated copies</dt><dd>{len(report['duplicates'])}</dd></dl></section>
<section><h2>Baseline comparison</h2><div class="scroll"><table><thead><tr><th>Method</th><th>Macro-F1 ↑</th>
<th>Brier ↓</th><th>Calibration error ↓</th><th>Coverage</th></tr></thead><tbody>{comparisons}</tbody></table></div>
<p>Coverage counts directional and neutral decisions. Probability metrics use the distribution before abstention.</p></section>
<section><h2>Confusion matrix</h2><div class="scroll"><table><thead><tr><th>Gold ↓ / Served →</th>{headers}</tr></thead>
<tbody>{grid}</tbody></table></div></section>
<section><h2>Distribution drift</h2><p>{drift['test_oov_feature_rate']:.1%} of test token and bigram occurrences are outside
the training vocabulary. Gold label divergence is {drift['gold_label_js_bits']:.4f} bits (Jensen–Shannon).</p></section>
<section><h2>Abstentions and errors</h2><div class="scroll"><table><thead><tr><th>Article</th><th>Issuer</th><th>Gold</th>
<th>Served</th><th>Reason</th></tr></thead><tbody>{''.join(review)}</tbody></table></div></section>
<footer>Model {escape(report['model_version'])}</footer></main></html>"""
