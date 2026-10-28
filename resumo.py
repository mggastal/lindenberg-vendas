#!/usr/bin/env python3
"""
Resumo Geral — Lindenberg Vendas (Grigoletti Mídias)
Lê a aba meta-ads da planilha e gera um HTML enxuto: KPIs, leads/CPL por semana e por mês.
Sem criativos e sem quebra por produto/campanha.
"""

import csv, io, json, re, sys
import requests
from pathlib import Path
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

SHEET_ID    = "1cyDFUzGxwSJVwMOIzeBrrqe-q9SrOxaeewkUs2YVZjM"
URL_META    = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet=meta-ads"
OUTPUT_FILE = sys.argv[1] if len(sys.argv) > 1 else "resumo.html"
LEADS_COL   = "Conversões"   # mesma coluna de leads do dashboard.py
CRIATIVO_EMPREENDIMENTOS = ["Ibirapuera"]   # empreendimentos que mostram o melhor criativo

MESES = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho",
         "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]

def num(v):
    v = (v or "").strip().replace("R$", "").strip()
    if not v: return 0.0
    if "," in v: v = v.replace(".", "").replace(",", ".")
    try: return float(v)
    except ValueError: return 0.0

def carregar():
    resp = requests.get(URL_META, timeout=60); resp.raise_for_status()
    raw = resp.content.decode("utf-8")
    rows = []
    for r in csv.DictReader(io.StringIO(raw)):
        try: d = date.fromisoformat(r["Date"][:10])
        except (KeyError, ValueError): continue
        rows.append({
            "d": d,
            "spend": num(r.get("Spend (Cost, Amount Spent)")),
            "imp": num(r.get("Impressions")),
            "lc": num(r.get("Action Link Clicks")),
            "leads": num(r.get(LEADS_COL)),
            "camp": r.get("Campaign Name", ""), "ad": r.get("Ad Name", ""),
            "thumb": (r.get("Image URL") or r.get("Thumbnail URL") or "").strip(),
        })
    return rows

def somar(rows):
    t = {"spend": 0.0, "imp": 0.0, "lc": 0.0, "leads": 0.0}
    for r in rows:
        for k in t: t[k] += r[k]
    return t

def metricas(t, dias=None):
    sp, imp, lc, ld = t["spend"], t["imp"], t["lc"], t["leads"]
    m = {
        "spend": round(sp, 2), "imp": int(imp), "lc": int(lc), "leads": int(ld),
        "cpl": round(sp / ld, 2) if ld else None,
        "ctr": round(lc / imp * 100, 2) if imp else None,
        "cpc": round(sp / lc, 2) if lc else None,
        "cpm": round(sp / imp * 1000, 2) if imp else None,
        "conv": round(ld / lc * 100, 2) if lc else None,
    }
    if dias: m["leads_dia"] = round(ld / dias, 2)
    return m

def empreendimento(camp):
    """[LV] [JOTA] [IG/FB] ... → Jota (2º colchete do nome da campanha)."""
    tags = re.findall(r"\[([^\]]+)\]", camp)
    return (tags[1] if len(tags) > 1 else camp).title()

def baixar_thumb(url, nome):
    """Salva a miniatura em imgs/ com nome fixo; se o link assinado expirar, mantém a última."""
    fp = Path("imgs") / f"resumo_{nome}.jpg"
    if url:
        try:
            r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
            data = r.content
            if r.status_code == 200 and len(data) > 500:
                fp.parent.mkdir(exist_ok=True); fp.write_bytes(data)
        except Exception as e:
            print(f"  aviso: miniatura {nome} não baixada ({e})")
    return f"{fp.as_posix()}?v={date.today():%Y%m%d}" if fp.exists() else ""

def melhores_criativos(rows):
    """Melhor anúncio de cada empreendimento (mais leads; empate → menor CPL), somando todos os conjuntos."""
    ads = defaultdict(list)
    for r in rows: ads[(empreendimento(r["camp"]), r["ad"])].append(r)
    por_emp = defaultdict(list)
    for (emp, ad), rs in ads.items():
        m = metricas(somar(rs))
        m.update(ad=ad, thumb=next((r["thumb"] for r in rs if r["thumb"]), ""))
        por_emp[emp].append(m)
    out = []
    for emp, lst in sorted(por_emp.items()):
        if emp not in CRIATIVO_EMPREENDIMENTOS: continue
        tot_emp = sum(a["leads"] for a in lst)
        b = max(lst, key=lambda a: (a["leads"], -(a["cpl"] or 1e9)))
        b["emp"] = emp
        b["share"] = round(b["leads"] / tot_emp * 100) if tot_emp else None
        b["n_ads"] = len(lst)
        b["img"] = baixar_thumb(b.pop("thumb"), re.sub(r"\W+", "_", emp.lower()))
        out.append(b)
    return out

def gerar():
    rows = carregar()
    if not rows: sys.exit("Sem dados na aba meta-ads")
    ini = min(r["d"] for r in rows)
    fim = max(r["d"] for r in rows)
    # último dia com investimento relevante (a extração às vezes traz centavos residuais)
    ult = max((r["d"] for r in rows if r["spend"] >= 1), default=fim)

    total = metricas(somar(rows), (ult - ini).days + 1)

    # Semanas de segunda a domingo
    sem = defaultdict(list)
    for r in rows: sem[r["d"] - timedelta(days=r["d"].weekday())].append(r)
    semanas = []
    for s in sorted(sem):
        e = s + timedelta(days=6)
        m = metricas(somar(sem[s]))
        m["label"] = f"{s:%d/%m}–{e:%d/%m}"
        m["parcial"] = s < ini or e > ult
        semanas.append(m)

    mes = defaultdict(list)
    for r in rows: mes[(r["d"].year, r["d"].month)].append(r)
    meses = []
    for (a, mm) in sorted(mes):
        dias_mes = sorted({r["d"] for r in mes[(a, mm)]})
        m = metricas(somar(mes[(a, mm)]))
        m["label"] = f"{MESES[mm]}/{str(a)[2:]}"
        m["dias"] = len(dias_mes)
        meses.append(m)

    dia = defaultdict(list)
    for r in rows: dia[r["d"]].append(r)
    diario = [{"d": f"{d:%d/%m}", **metricas(somar(dia[d]))} for d in sorted(dia)]

    melhor = max((s for s in semanas if not s["parcial"]), key=lambda s: s["leads"], default=None)

    data = {
        "periodo": f"{ini:%d/%m/%Y} a {fim:%d/%m/%Y}",
        "ultimo_invest": f"{ult:%d/%m/%Y}",
        "atualizado": datetime.now(timezone(timedelta(hours=-3))).strftime("%d/%m/%Y %H:%M"),
        "total": total, "semanas": semanas, "meses": meses, "diario": diario,
        "melhor": melhor,
        "criativos": melhores_criativos(rows),
    }
    html = TEMPLATE.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False))
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f: f.write(html)
    print(f"✓ {OUTPUT_FILE}: {total['leads']} leads, R$ {total['spend']:.2f}, {len(semanas)} semanas")

TEMPLATE = r"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lindenberg Vendas · Resumo</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%23192638'/%3E%3Ctext x='16' y='22' font-family='Arial' font-weight='800' font-size='17' fill='%23E07832' text-anchor='middle'%3EG%3C/text%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root{
  --bg:#f6f5f3;--card:#ffffff;--ink:#1c1a19;--muted:#6f6a66;--line:#e7e3df;
  --accent:#8B0000;--accent-soft:#f3e3e1;--series2:#c9a227;--good:#1f7a4d;--grid:#eeeae6;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --bg:#141211;--card:#1d1b1a;--ink:#f1edea;--muted:#a59f9a;--line:#2e2a28;
  --accent:#e0675e;--accent-soft:#3a201e;--series2:#e3bf4a;--good:#4fc58a;--grid:#2a2624;
}}
:root[data-theme="dark"]{
  --bg:#141211;--card:#1d1b1a;--ink:#f1edea;--muted:#a59f9a;--line:#2e2a28;
  --accent:#e0675e;--accent-soft:#3a201e;--series2:#e3bf4a;--good:#4fc58a;--grid:#2a2624;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--ink);font-family:'DM Sans',system-ui,sans-serif;font-size:14px;line-height:1.45}
.wrap{max-width:1180px;margin:0 auto;padding:28px 16px 40px}
header{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;flex-wrap:wrap;margin-bottom:22px}
.eyebrow{font-size:11px;letter-spacing:1.6px;text-transform:uppercase;color:var(--accent);font-weight:600}
h1{font-size:26px;font-weight:700;letter-spacing:-.4px;margin-top:4px}
.sub{color:var(--muted);margin-top:4px}
.meta{display:flex;align-items:center;gap:8px;color:var(--muted);font-size:12px;text-align:right}
.meta img{height:18px}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}
.kpi .l{font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--muted);font-weight:600}
.kpi .v{font-size:26px;font-weight:700;margin-top:6px;font-variant-numeric:tabular-nums;letter-spacing:-.5px}
.kpi .h{font-size:12px;color:var(--muted);margin-top:2px}
.kpi.main{border-color:var(--accent);background:linear-gradient(0deg,var(--card),var(--card)) padding-box}
.kpi.main .v{color:var(--accent)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;margin-bottom:16px}
.card h2{font-size:15px;font-weight:700}
.card .cap{color:var(--muted);font-size:12px;margin-top:2px}
.card-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap;margin-bottom:14px}
.legend{display:flex;gap:14px;font-size:12px;color:var(--muted)}
.legend span::before{content:"";display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px;background:var(--c)}
.legend .ln::before{height:3px;border-radius:2px;vertical-align:3px}
.chart{position:relative;height:300px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.tbl{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th{font-size:11px;text-transform:uppercase;letter-spacing:.8px;color:var(--muted);font-weight:600;text-align:right;padding:8px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
td{text-align:right;padding:9px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
th:first-child,td:first-child{text-align:left}
tr:last-child td{border-bottom:none}
tfoot td{font-weight:700;border-top:2px solid var(--line)}
.bar{display:inline-block;height:6px;border-radius:3px;background:var(--accent);vertical-align:middle;margin-right:8px;opacity:.85}
.tag{font-size:10px;color:var(--muted);border:1px solid var(--line);border-radius:4px;padding:0 4px;margin-left:6px}
.crs{display:grid;grid-template-columns:1fr;gap:16px}
.cr{display:flex;gap:16px;align-items:flex-start}
.cr img{width:200px;height:200px;object-fit:cover;border-radius:10px;border:1px solid var(--line);flex-shrink:0;background:var(--bg)}
.cr .emp{font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--accent);font-weight:600}
.cr .nm{font-size:17px;font-weight:700;margin:2px 0 10px}
.cr dl{display:grid;grid-template-columns:auto auto;gap:4px 18px;font-size:13px}
.cr dt{color:var(--muted)}
.cr dd{font-weight:600;font-variant-numeric:tabular-nums;text-align:right}
.note{font-size:12px;color:var(--muted);margin-top:10px}
footer{display:flex;justify-content:center;align-items:center;gap:8px;color:var(--muted);font-size:12px;margin-top:24px}
.gm{font-size:11px;font-weight:700;letter-spacing:.28em;text-transform:uppercase;color:#E07832}
.gm span{color:var(--ink);font-weight:400}
@media (max-width:860px){.kpis{grid-template-columns:repeat(2,1fr)}.grid2,.crs{grid-template-columns:1fr}}
@media (max-width:520px){.cr{flex-direction:column}.cr img{width:100%;height:auto;aspect-ratio:1}}
@media (max-width:420px){.kpi .v{font-size:21px}h1{font-size:22px}.chart{height:250px}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <div class="eyebrow">Meta Ads · Resumo geral</div>
      <h1>Lindenberg Vendas</h1>
      <div class="sub" id="periodo"></div>
    </div>
    <div class="meta"><div id="atualizado"></div></div>
  </header>

  <section class="kpis" id="kpis"></section>

  <section class="card">
    <div class="card-head">
      <div><h2>Leads por semana</h2><div class="cap">Semanas de segunda a domingo · CPL na linha</div></div>
      <div class="legend"><span style="--c:var(--accent)">Leads</span><span class="ln" style="--c:var(--series2)">CPL</span></div>
    </div>
    <div class="chart"><canvas id="cSemana"></canvas></div>
  </section>

  <section class="card" id="secCr">
    <div class="card-head"><div><h2>Melhor criativo</h2><div class="cap">Anúncio com mais leads, somando todos os conjuntos em que rodou</div></div></div>
    <div class="crs" id="crs"></div>
  </section>

  <section class="card">
    <div class="card-head"><div><h2>Semana a semana</h2><div class="cap" id="capSem"></div></div></div>
    <div class="tbl"><table id="tSem"></table></div>
  </section>

  <div class="grid2">
    <section class="card">
      <div class="card-head"><div><h2>Por mês</h2><div class="cap">Totais mensais do período</div></div></div>
      <div class="tbl"><table id="tMes"></table></div>
    </section>
    <section class="card">
      <div class="card-head">
        <div><h2>Investimento diário</h2><div class="cap">Valor investido por dia</div></div>
      </div>
      <div class="chart" style="height:240px"><canvas id="cDia"></canvas></div>
    </section>
  </div>

  <footer>Desenvolvido por <span class="gm">Grigoletti <span>Mídias</span></span></footer>
</div>

<script>
const D = /*__DATA__*/null;
const brl = v => v==null ? '—' : v.toLocaleString('pt-BR',{style:'currency',currency:'BRL'});
const brl0 = v => v==null ? '—' : v.toLocaleString('pt-BR',{style:'currency',currency:'BRL',maximumFractionDigits:0});
const int = v => v==null ? '—' : Math.round(v).toLocaleString('pt-BR');
const pct = v => v==null ? '—' : v.toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2})+'%';
const dec = v => v==null ? '—' : v.toLocaleString('pt-BR',{minimumFractionDigits:1,maximumFractionDigits:1});

document.getElementById('periodo').textContent = 'Período: ' + D.periodo;
document.getElementById('atualizado').textContent = 'Atualizado em ' + D.atualizado;

const T = D.total;
const kpis = [
  ['Leads totais', int(T.leads), dec(T.leads_dia)+' leads/dia em média', true],
  ['CPL médio', brl(T.cpl), 'custo por lead', true],
  ['Investimento', brl0(T.spend), 'último dia com verba: '+D.ultimo_invest],
  ['Média de leads por semana', int(T.leads / D.semanas.filter(s=>!s.parcial).length || 0), D.melhor ? 'melhor semana: '+D.melhor.leads+' leads ('+D.melhor.label+')' : 'semanas completas'],
  ['Impressões', int(T.imp), 'CPM '+brl(T.cpm)],
  ['Cliques no link', int(T.lc), 'CPC '+brl(T.cpc)],
  ['CTR', pct(T.ctr), 'cliques no link ÷ impressões'],
  ['Clique → lead', pct(T.conv), 'leads ÷ cliques no link'],
];
document.getElementById('kpis').innerHTML = kpis.map(([l,v,h,m]) =>
  `<div class="kpi${m?' main':''}"><div class="l">${l}</div><div class="v">${v}</div><div class="h">${h}</div></div>`).join('');

// Melhores criativos
if (!D.criativos || !D.criativos.length) document.getElementById('secCr').style.display = 'none';
else document.getElementById('crs').innerHTML = D.criativos.map(c => `<div class="cr">
  ${c.img ? `<img src="${c.img}" alt="${c.ad}" loading="lazy">` : ''}
  <div><div class="emp">${c.emp}</div><div class="nm">${c.ad}</div>
  <dl><dt>Leads</dt><dd>${int(c.leads)}${c.share!=null?` <span style="color:var(--muted);font-weight:400">(${c.share}% do empreend.)</span>`:''}</dd>
  <dt>CPL</dt><dd>${brl(c.cpl)}</dd><dt>Investimento</dt><dd>${brl0(c.spend)}</dd>
  <dt>Impressões</dt><dd>${int(c.imp)}</dd><dt>CTR</dt><dd>${pct(c.ctr)}</dd><dt>Clique → lead</dt><dd>${pct(c.conv)}</dd></dl></div></div>`).join('');

// Tabelas
const maxLeads = Math.max(...D.semanas.map(s=>s.leads), 1);
document.getElementById('capSem').textContent = D.semanas.length + ' semanas · semanas incompletas marcadas';
const sumRow = (lbl, t) => `<tfoot><tr><td>${lbl}</td><td>${brl(t.spend)}</td><td>${int(t.leads)}</td><td>${brl(t.cpl)}</td><td>${int(t.imp)}</td><td>${int(t.lc)}</td><td>${pct(t.ctr)}</td><td>${pct(t.conv)}</td></tr></tfoot>`;
document.getElementById('tSem').innerHTML =
  `<thead><tr><th>Semana</th><th>Investimento</th><th>Leads</th><th>CPL</th><th>Impressões</th><th>Cliques</th><th>CTR</th><th>Clique→lead</th></tr></thead><tbody>` +
  D.semanas.map(s => `<tr><td>${s.label}${s.parcial?'<span class="tag">parcial</span>':''}</td><td>${brl(s.spend)}</td>
    <td><span class="bar" style="width:${Math.round(s.leads/maxLeads*48)}px"></span>${int(s.leads)}</td>
    <td>${brl(s.cpl)}</td><td>${int(s.imp)}</td><td>${int(s.lc)}</td><td>${pct(s.ctr)}</td><td>${pct(s.conv)}</td></tr>`).join('') +
  '</tbody>' + sumRow('Total', T);
document.getElementById('tMes').innerHTML =
  `<thead><tr><th>Mês</th><th>Dias</th><th>Investimento</th><th>Leads</th><th>CPL</th></tr></thead><tbody>` +
  D.meses.map(m => `<tr><td>${m.label}</td><td>${m.dias}</td><td>${brl0(m.spend)}</td><td>${int(m.leads)}</td><td>${brl(m.cpl)}</td></tr>`).join('') +
  `</tbody><tfoot><tr><td>Total</td><td></td><td>${brl0(T.spend)}</td><td>${int(T.leads)}</td><td>${brl(T.cpl)}</td></tr></tfoot>`;

// Gráficos
let charts = [];
// Rótulos de dados: leads dentro do topo da barra, CPL acima do ponto da linha
const rotulos = {id:'rotulos', afterDatasetsDraw(chart){
  const {ctx} = chart;
  ctx.save(); ctx.textAlign = 'center'; ctx.font = "600 11px 'DM Sans', system-ui, sans-serif";
  chart.data.datasets.forEach((ds, i) => {
    const meta = chart.getDatasetMeta(i);
    if (meta.hidden) return;
    meta.data.forEach((el, j) => {
      const v = ds.data[j]; if (v == null) return;
      if (ds.type === 'bar') {
        ctx.fillStyle = '#fff'; ctx.textBaseline = 'top';
        ctx.fillText(v, el.x, el.y + 5);
      } else {
        const t = 'R$ ' + Math.round(v);
        ctx.textBaseline = 'bottom';
        ctx.lineWidth = 3; ctx.strokeStyle = css('--card'); ctx.strokeText(t, el.x, el.y - 6);
        ctx.fillStyle = css('--ink'); ctx.fillText(t, el.x, el.y - 6);
      }
    });
  });
  ctx.restore();
}};
function css(n){ return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }
function draw(){
  charts.forEach(c=>c.destroy()); charts = [];
  const acc = css('--accent'), s2 = css('--series2'), mut = css('--muted'), grid = css('--grid'), card = css('--card'), ink = css('--ink');
  Chart.defaults.font.family = "'DM Sans', system-ui, sans-serif";
  Chart.defaults.color = mut;
  const maxCpl = Math.max(...D.semanas.map(s=>s.cpl||0), 1);
  const tip = {backgroundColor:card, titleColor:ink, bodyColor:ink, borderColor:grid, borderWidth:1, padding:10};
  charts.push(new Chart(document.getElementById('cSemana'), {
    plugins:[rotulos],
    data:{labels:D.semanas.map(s=>s.label + (s.parcial?'*':'')), datasets:[
      {type:'bar', label:'Leads', data:D.semanas.map(s=>s.leads), backgroundColor:acc, borderRadius:4, maxBarThickness:42, yAxisID:'y', order:2},
      {type:'line', label:'CPL', data:D.semanas.map(s=>s.cpl), borderColor:s2, backgroundColor:s2, borderWidth:2, pointRadius:3, tension:.3, yAxisID:'y1', order:1, spanGaps:true},
    ]},
    options:{responsive:true, maintainAspectRatio:false, interaction:{mode:'index',intersect:false},
      plugins:{legend:{display:false}, tooltip:{...tip, callbacks:{label:c=>c.dataset.label==='CPL' ? ' CPL: '+brl(c.raw) : ' Leads: '+c.raw}}},
      scales:{x:{grid:{display:false}, ticks:{maxRotation:0, autoSkip:true}},
        // barras na metade de baixo, linha do CPL na faixa de cima (rótulos não se sobrepõem)
        y:{beginAtZero:true, max:maxLeads*1.9, display:false},
        y1:{min:-maxCpl*1.25, max:maxCpl*1.18, display:false}}}
  }));
  charts.push(new Chart(document.getElementById('cDia'), {
    type:'bar',
    data:{labels:D.diario.map(d=>d.d), datasets:[{label:'Investimento', data:D.diario.map(d=>d.spend), backgroundColor:acc, borderRadius:2}]},
    options:{responsive:true, maintainAspectRatio:false,
      plugins:{legend:{display:false}, tooltip:{...tip, callbacks:{label:c=>' '+brl(c.raw)+' · '+D.diario[c.dataIndex].leads+' leads'}}},
      scales:{x:{grid:{display:false}, ticks:{maxRotation:0, autoSkip:true, maxTicksLimit:8}}, y:{beginAtZero:true, grid:{color:grid}, ticks:{callback:v=>'R$ '+v}}}}
  }));
}
draw();
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', draw);
</script>
</body>
</html>
"""

if __name__ == "__main__":
    gerar()
