const pptxgen = require("pptxgenjs");
const { applyTheme } = require("./apply_theme.js");

const THEME = { name: "Orbital Risk", headFontFace: "Cambria", bodyFontFace: "Calibri",
  colors: { dk1: "161616", lt1: "FFFFFF", dk2: "3A3A3A", lt2: "F3F3F3",
    accent1: "C8102E", accent2: "161616", accent3: "8C8C8C", accent4: "D9D9D9",
    accent5: "5A5A5A", accent6: "B5B5B5", hlink: "C8102E", folHlink: "8C8C8C" } };
const HEX = { ink: "161616", red: "C8102E", grey: "8C8C8C", rule: "D9D9D9", mid: "5A5A5A", soft: "F3F3F3" };

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "Pricing Orbital Risk"; pres.author = "Iseul";
const C = pres.SchemeColor;

// ---------- layouts ----------
pres.defineSlideMaster({ title: "TITLE_DARK", background: { color: C.text1 },
  objects: [
    { placeholder: { options: { name: "kicker", type: "body", x: 0.6, y: 0.6, w: 6, h: 0.3, fontSize: 10, bold: true, color: C.accent1, charSpacing: 3, margin: 0 }, text: "" } },
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 1.55, w: 6.2, h: 1.5, fontFace: "Cambria", fontSize: 44, color: C.background1, valign: "top", align: "left", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: 0.6, y: 3.1, w: 5.6, h: 0.9, fontSize: 16, color: C.accent6, valign: "top", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "byline", type: "body", x: 0.6, y: 4.75, w: 6, h: 0.3, fontSize: 11, color: C.accent3, margin: 0 }, text: "" } },
  ] });
pres.defineSlideMaster({ title: "CONTENT", background: { color: C.background1 },
  objects: [
    { placeholder: { options: { name: "kicker", type: "body", x: 0.5, y: 0.35, w: 7, h: 0.28, fontSize: 10, bold: true, color: C.accent1, charSpacing: 3, margin: 0 }, text: "" } },
    { placeholder: { options: { name: "title", type: "title", x: 0.5, y: 0.65, w: 9, h: 0.7, fontFace: "Cambria", fontSize: 30, color: C.text1, valign: "top", align: "left", margin: 0 }, text: "" } },
    { text: { text: "Pricing Orbital Risk", options: { x: 0.5, y: 5.2, w: 4, h: 0.25, fontSize: 9, color: C.accent3, margin: 0 } } },
  ],
  slideNumber: { x: 9.0, y: 5.2, w: 0.5, h: 0.25, fontSize: 9, color: C.accent3, align: "right", margin: 0 } });
pres.defineSlideMaster({ title: "CLOSING_DARK", background: { color: C.text1 },
  objects: [
    { placeholder: { options: { name: "kicker", type: "body", x: 0.5, y: 0.35, w: 7, h: 0.28, fontSize: 10, bold: true, color: C.accent1, charSpacing: 3, margin: 0 }, text: "" } },
    { placeholder: { options: { name: "title", type: "title", x: 0.5, y: 0.65, w: 9, h: 0.7, fontFace: "Cambria", fontSize: 30, color: C.background1, valign: "top", align: "left", margin: 0 }, text: "" } },
  ] });

const T = (s, text, o) => s.addText(text, Object.assign({ isTextBox: true, margin: 0, fontSize: 14, color: C.text1, valign: "top" }, o));
const axis = () => ({ catAxisLabelColor: HEX.mid, valAxisLabelColor: HEX.mid, catAxisLabelFontSize: 9, valAxisLabelFontSize: 9,
  catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt", valGridLine: { color: HEX.rule, size: 0.5 }, catGridLine: { style: "none" },
  catAxisLineColor: HEX.rule, valAxisLineShow: false });

// ---------- 1. title ----------
pres.addSection({ title: "Opening" });
let s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: "Opening" });
s.addText("FOUNDATIONS OF DATA SCIENCE  ·  BITS PILANI DUBAI", { placeholder: "kicker" });
s.addText("Pricing Orbital Risk", { placeholder: "title" });
s.addText("A survival model of satellite failure in low Earth orbit, tested against the insurance market’s flat rate", { placeholder: "body" });
s.addText("Iseul  ·  November 2026", { placeholder: "byline" });
// orbit motif: concentric rings off the right edge, one red satellite
[[7.2, 0.4, 4.8], [7.75, 0.95, 3.7], [8.3, 1.5, 2.6]].forEach(([x, y, d], i) =>
  s.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, line: { color: "3A3A3A", width: 0.75 }, fill: { type: "none" }, objectName: "orbit-" + i }));
s.addShape(pres.shapes.OVAL, { x: 9.53, y: 0.99, w: 0.16, h: 0.16, fill: { color: C.accent1 }, line: { type: "none" }, objectName: "satellite" });
s.addShape(pres.shapes.OVAL, { x: 9.43, y: 2.73, w: 0.14, h: 0.14, fill: { color: C.background1 }, line: { type: "none" }, objectName: "earth-dot" });
s.addNotes("Satellite insurance charges a flat five to twelve percent a year, whatever orbit a satellite flies in. This project asks whether public orbital data can measure that risk, and how far the flat rate sits from what the orbital environment implies.");

// ---------- 2. problem ----------
pres.addSection({ title: "Problem" });
s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Problem" });
s.addText("01 — THE PROBLEM", { placeholder: "kicker" });
s.addText("Insurers charge one rate for every orbit", { placeholder: "title" });
const stats = [
  ["5–12%", "flat annual premium, as a share of insured value — set with almost no adjustment for altitude"],
  ["14×", "spread in tracked debris density between the emptiest and densest shells studied"],
  ["<1%", "of ~10,000 active LEO satellites carry in-orbit insurance — about 300"],
  ["180%", "market loss ratio in 2023: $995M paid in claims against $557M of premiums"],
];
stats.forEach(([big, small], i) => {
  const x = 0.5 + i * 2.3;
  T(s, big, { x, y: 1.75, w: 2.05, h: 0.9, fontFace: "Cambria", fontSize: 44, color: i === 1 ? C.accent1 : C.text1, objectName: "stat-" + i });
  s.addShape(pres.shapes.LINE, { x, y: 2.75, w: 1.9, h: 0, line: { color: HEX.rule, width: 0.75 }, objectName: "stat-rule-" + i });
  T(s, small, { x, y: 2.9, w: 1.95, h: 1.2, fontSize: 13, color: C.text2 });
});
s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: 4.3, w: 9, h: 0.65, fill: { color: C.background2 }, line: { type: "none" }, objectName: "question-panel" });
T(s, [{ text: "Question  ", options: { bold: true, color: C.accent1 } },
      { text: "Can the risk be measured from public data alone — and how far is the flat rate from what the orbit implies?" }],
  { x: 0.7, y: 4.3, w: 8.6, h: 0.65, fontSize: 14, valign: "middle" });
s.addNotes("Debris density differs fourteen-fold between shells in my own data, yet the premium barely moves. Fewer than one percent of LEO satellites are insured, and in 2023 the market paid out almost twice what it took in. If the risk could be measured, the price could follow it.");

// ---------- 3. pipeline ----------
pres.addSection({ title: "Method" });
s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Method" });
s.addText("02 — DATA AND PIPELINE", { placeholder: "kicker" });
s.addText("Five public sources, one survival panel", { placeholder: "title" });
const steps = [
  ["Sample", "535 satellites from Space-Track gp_history, stratified by altitude shell"],
  ["Label", "Detect end of orbit maintenance from manoeuvre frequency"],
  ["Environment", "KDE debris density per shell per quarter, plus F10.7 solar flux"],
  ["Panel", "12,793 satellite-quarters · 264 satellites · 83 events"],
  ["Model & price", "Cox, Weibull and logistic baseline → premium per shell"],
];
steps.forEach(([h, b], i) => {
  const x = 0.5 + i * 1.84;
  s.addShape(pres.shapes.OVAL, { x, y: 1.75, w: 0.46, h: 0.46, fill: { color: i === 1 ? C.accent1 : C.text1 }, line: { type: "none" }, objectName: "step-dot-" + i });
  T(s, String(i + 1), { x, y: 1.75, w: 0.46, h: 0.46, fontSize: 14, bold: true, color: C.background1, align: "center", valign: "middle" });
  if (i < 4) s.addShape(pres.shapes.LINE, { x: x + 0.56, y: 1.98, w: 1.18, h: 0, line: { color: HEX.rule, width: 1, endArrowType: "triangle" }, objectName: "step-arrow-" + i });
  T(s, h, { x, y: 2.4, w: 1.65, h: 0.35, fontSize: 15, bold: true });
  T(s, b, { x, y: 2.78, w: 1.65, h: 1.2, fontSize: 12, color: C.text2 });
});
T(s, "SOURCES", { x: 0.5, y: 4.25, w: 2, h: 0.25, fontSize: 9, bold: true, color: C.accent3, charSpacing: 3 });
T(s, "Space-Track.org (US Space Force catalogue)  ·  CelesTrak  ·  NOAA SWPC solar flux  ·  ESA Space Environment Report  ·  Aon / Gallagher market reports",
  { x: 0.5, y: 4.5, w: 9, h: 0.5, fontSize: 12, color: C.text2 });
s.addNotes("Everything is public. Failure labels are not taken from registries, which cover mainly large insured Western spacecraft. They are derived from orbital behaviour, which applies to every object equally. Registries become the validation set instead of the training target.");

// ---------- 4. detector ----------
s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Method" });
s.addText("03 — LABELLING FAILURE FROM THE ORBIT", { placeholder: "kicker" });
s.addText("A failure is a step; a retirement is a ramp", { placeholder: "title" });
const env = [["2010 Q1",0.4],["2010 Q2",0.2418],["2010 Q3",0.2174],["2010 Q4",0.2391],["2011 Q1",0.1889],["2011 Q2",0.2857],["2011 Q3",0.2391],["2011 Q4",0.337],["2012 Q1",0.2637],["2012 Q2",0.044],["2012 Q3",0.0217],["2012 Q4",0.0543],["2013 Q1",0.0667],["2013 Q2",0.046],["2013 Q3",0.0326],["2013 Q4",0.0114]];
const ter = [["2018 Q1",0.3333],["2018 Q2",0.2967],["2018 Q3",0.3043],["2018 Q4",0.4505],["2019 Q1",0.4111],["2019 Q2",0.2637],["2019 Q3",0.2065],["2019 Q4",0.2065],["2020 Q1",0.1889],["2020 Q2",0.1319],["2020 Q3",0.1739],["2020 Q4",0.0361],["2021 Q1",0.0111],["2021 Q2",0.022],["2021 Q3",0.0217],["2021 Q4",0.0435],["2022 Q1",0.0333],["2022 Q2",0.0449],["2022 Q3",0.0109],["2022 Q4",0.0],["2023 Q1",0.0],["2023 Q2",0.011],["2023 Q3",0.0111],["2023 Q4",0.0]];
const lab = a => a.map(([q]) => q.endsWith("Q1") ? q.slice(0, 4) : "");
const lineOpts = (title, color) => Object.assign(axis(), { showTitle: true, title, titleFontSize: 12, titleColor: HEX.ink, titleFontFace: "+mn-lt", titleAlign: "left",
  chartColors: [color], lineSize: 2, lineDataSymbol: "circle", lineDataSymbolSize: 4, showLegend: false,
  valAxisMinVal: 0, valAxisMaxVal: 0.5, valAxisMajorUnit: 0.1, valAxisLabelFormatCode: "0.0", catAxisLabelFrequency: 1 });
s.addChart(pres.charts.LINE, [{ name: "Envisat", labels: lab(env), values: env.map(r => r[1]) }],
  Object.assign({ x: 0.4, y: 1.45, w: 4.5, h: 2.45, objectName: "chart-envisat" }, lineOpts("Envisat — share of days the orbit was raised", HEX.red)));
s.addChart(pres.charts.LINE, [{ name: "Terra", labels: lab(ter), values: ter.map(r => r[1]) }],
  Object.assign({ x: 5.1, y: 1.45, w: 4.5, h: 2.45, objectName: "chart-terra" }, lineOpts("Terra — share of days the orbit was raised", HEX.ink)));
T(s, [{ text: "Step. ", options: { bold: true, color: C.accent1 } }, { text: "Contact lost 8 Apr 2012; manoeuvres collapse 0.26 → 0.04 in one quarter. Detector dates it 1 Apr — 7 days early." }],
  { x: 0.5, y: 4.05, w: 4.3, h: 0.75, fontSize: 12 });
T(s, [{ text: "Ramp. ", options: { bold: true } }, { text: "Still operating in 2026, but maintenance wound down over 8 quarters. Labelled a retirement, not a failure." }],
  { x: 5.2, y: 4.05, w: 4.3, h: 0.75, fontSize: 12 });
T(s, "4 of 4 documented satellites classified correctly. The first detector used a 0.3 km burn threshold — real burns are ~0.016 km/day, 20× smaller.",
  { x: 0.5, y: 4.8, w: 9, h: 0.3, fontSize: 10, italic: true, color: C.accent5 });
s.addNotes("An operating satellite keeps raising its orbit against drag. The statistic is simply the share of days on which altitude rose. Envisat drops off a cliff in the quarter it died. Terra is still working, but NASA wound its maintenance down gradually; on frequency alone it looks dead, so the detector tests abruptness. Magnitude failed: my first threshold was twenty times too large and found zero manoeuvres on Envisat.");

// ---------- 5. model ----------
s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Method" });
s.addText("04 — THE MODEL", { placeholder: "kicker" });
s.addText("68.6% of the satellites haven’t failed yet", { placeholder: "title" });
// lifeline diagram
const L0 = 0.7, L1 = 4.3, top = 1.75;
s.addShape(pres.shapes.LINE, { x: L1, y: top - 0.15, w: 0, h: 2.35, line: { color: HEX.grey, width: 0.75, dashType: "dash" }, objectName: "study-end" });
T(s, "time →", { x: L0, y: 3.95, w: 1.2, h: 0.25, fontSize: 10, color: C.accent3 });
T(s, "study end", { x: L1 - 0.6, y: 3.95, w: 1.2, h: 0.25, fontSize: 10, color: C.accent3, align: "center" });
const lives = [[0.0, 2.1, 1], [0.4, 1.0, 0], [0.9, 1.0, 0], [0.2, 2.9, 1], [1.4, 1.0, 0], [0.6, 1.0, 0]];
lives.forEach(([st, en, ev], i) => {
  const y = top + i * 0.38, xa = L0 + st, xb = ev ? L0 + en : L1;
  s.addShape(pres.shapes.LINE, { x: xa, y, w: xb - xa, h: 0, line: { color: ev ? HEX.red : HEX.ink, width: 1.5 }, objectName: "life-" + i });
  s.addShape(pres.shapes.OVAL, { x: xb - 0.08, y: y - 0.08, w: 0.16, h: 0.16, fill: ev ? { color: C.accent1 } : { color: C.background1 },
    line: { color: ev ? HEX.red : HEX.ink, width: 1.25 }, objectName: "life-end-" + i });
});
T(s, [{ text: "● ", options: { color: C.accent1 } }, { text: "maintenance stopped (event)   " }, { text: "○ ", options: { color: C.text1 } }, { text: "still flying (censored)" }],
  { x: 0.5, y: 4.3, w: 4.4, h: 0.3, fontSize: 11, color: C.text2 });
T(s, "Each survivor counts as “lasted at least this long” — neither dropped nor called a success.",
  { x: 0.5, y: 4.6, w: 4.4, h: 0.5, fontSize: 11, color: C.accent5, italic: true });
// model table
const hdr = (t) => ({ text: t, options: { bold: true, fontSize: 11, color: C.accent3 } });
const rows = [
  [hdr("MODEL"), hdr("ROLE"), hdr("C-INDEX")],
  ["Cox PH, time-varying", "Primary — debris density changes every quarter", "0.676 fit\n0.562 test"],
  ["Logistic regression", "Baseline to beat", "0.696"],
  ["Weibull AFT", "Remaining-life forecast — 2–7× off, kept out of pricing", "—"],
];
s.addTable(rows.map((r, i) => r.map(c => typeof c === "string" ? { text: c, options: { fontSize: 12, color: i === 2 ? C.accent1 : C.text1, bold: i === 2 && false } } : c)),
  { x: 5.2, y: 1.6, w: 4.3, colW: [1.35, 2.05, 0.9], border: { type: "solid", pt: 0.5, color: HEX.rule }, fill: { color: C.background1 },
    margin: [0.06, 0.08, 0.06, 0.08], valign: "middle", objectName: "model-table" });
T(s, [{ text: "Cox loses to the baseline on ranking. ", options: { bold: true } }, { text: "Reported, not hidden. The proportional-hazards assumption also fails for solar flux." }],
  { x: 5.2, y: 4.35, w: 4.3, h: 0.7, fontSize: 12, color: C.text2 });
s.addNotes("Most satellites are still flying, so their failure times are unknown — right-censoring. Cox proportional hazards handles that and lets debris density vary quarter by quarter. I benchmarked it against plain logistic regression, and on ranking the logistic model wins, 0.696 against 0.676. Survival analysis still earns its place for censoring, but I report the loss.");

// ---------- 6. result ----------
pres.addSection({ title: "Results" });
s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Results" });
s.addText("05 — THE RESULT", { placeholder: "kicker" });
s.addText("Debris density does not predict failure", { placeholder: "title" });
T(s, "1.0026", { x: 0.5, y: 1.55, w: 3.6, h: 1.0, fontFace: "Cambria", fontSize: 60, color: C.accent1 });
T(s, "hazard ratio per extra object/km of debris density — p = 0.49", { x: 0.5, y: 2.6, w: 3.4, h: 0.55, fontSize: 13, color: C.text2 });
const cox = [[hdr("COVARIATE"), hdr("HR"), hdr("p")],
  ["Debris density", "1.003", "0.49"], ["Solar flux F10.7", "1.002", "0.20"], ["Age (years)", "0.998", "0.45"], ["Altitude (km)", "1.000", "0.45"]];
s.addTable(cox.map(r => r.map(c => typeof c === "string" ? { text: c, options: { fontSize: 12, color: C.text1 } } : c)),
  { x: 0.5, y: 3.3, w: 3.4, colW: [1.8, 0.8, 0.8], border: { type: "solid", pt: 0.5, color: HEX.rule }, fill: { color: C.background1 },
    margin: [0.04, 0.08, 0.04, 0.08], objectName: "cox-table" });
const sens = [["Baseline, 10 shells",0.530],["Coarse, 5 shells",0.469],["Fine, 50 km",0.530],["Shells +50 km",0.432],["Shells −50 km",0.380],
  ["Start 2008",0.473],["Start 2012",0.459],["Start 2016",0.774],["Launched ≥1995",0.733],["Launched ≥2005",0.959],
  ["≤1000 km",0.702],["500–1000 km",0.692],["Large only",0.799],["Excl. wind-downs",0.360]];
s.addChart(pres.charts.BAR, [{ name: "p-value", labels: sens.map(r => r[0]), values: sens.map(r => r[1]) }],
  Object.assign(axis(), { x: 4.4, y: 1.45, w: 5.2, h: 3.6, barDir: "bar", chartColors: [HEX.grey], showLegend: false,
    showTitle: true, title: "p-value for density in 14 re-fits (significant needs < 0.05)", titleFontSize: 11, titleColor: HEX.ink, titleFontFace: "+mn-lt",
    showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 9, dataLabelColor: HEX.mid, dataLabelFormatCode: "0.00", dataLabelFontFace: "+mn-lt",
    valAxisMinVal: 0, valAxisMaxVal: 1, valAxisMajorUnit: 0.25, valAxisLabelFormatCode: "0.00", catAxisOrientation: "maxMin", barGapWidthPct: 45, objectName: "chart-sensitivity" }));
s.addNotes("This is the headline, and it is a null. A hazard ratio of 1.0026 per object per kilometre, p of 0.49. The obvious attack on a null is that different bins would have found something, so I refitted sixteen ways: shell boundaries, study windows, population subsets. The hazard ratio never leaves the third decimal place and the smallest p-value anywhere is 0.36. This is a real null, not low power — 83 events, about 21 per covariate.");

// ---------- 7. pricing ----------
s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Results" });
s.addText("06 — PRICING", { placeholder: "kicker" });
s.addText("Every shell prices below the market’s 8.5%", { placeholder: "title" });
const shells = [["500–600",0.0643],["600–700",0.0734],["700–800",0.0351],["800–900",0.0475],["900–1000",0.0285],["1000–1200",0.0555],["1200–1500",0.0161]];
s.addChart([
  { type: pres.charts.BAR, data: [{ name: "Risk-loaded premium", labels: shells.map(r => r[0]), values: shells.map(r => r[1]) }],
    options: { chartColors: [HEX.ink], barGapWidthPct: 55, showValue: true } },
  { type: pres.charts.LINE, data: [{ name: "Market midpoint 8.5%", labels: shells.map(r => r[0]), values: shells.map(() => 0.085) }],
    options: { chartColors: [HEX.red], lineSize: 2, lineDataSymbol: "none", lineDash: "dash", showValue: false } },
], Object.assign(axis(), { x: 0.4, y: 1.45, w: 5.8, h: 3.55, showLegend: true, legendPos: "b", legendFontSize: 10, legendColor: HEX.mid, legendFontFace: "+mn-lt",
  valAxisMinVal: 0, valAxisMaxVal: 0.1, valAxisMajorUnit: 0.02, valAxisLabelFormatCode: "0%",
  showCatAxisTitle: true, catAxisTitle: "Altitude shell (km)", catAxisTitleFontSize: 10, catAxisTitleColor: HEX.mid, dataLabelPosition: "outEnd", dataLabelFormatCode: "0.0%", dataLabelFontSize: 9, dataLabelColor: HEX.mid, dataLabelFontFace: "+mn-lt", objectName: "chart-pricing" }));
T(s, "2.59%", { x: 6.6, y: 1.5, w: 3, h: 0.8, fontFace: "Cambria", fontSize: 44, color: C.accent1 });
T(s, "pooled cessation rate per satellite-year — inside the 1–3% band of published in-orbit loss rates, with no insurance data anywhere in the pipeline", { x: 6.6, y: 2.35, w: 2.9, h: 1.2, fontSize: 12, color: C.text2 });
s.addShape(pres.shapes.LINE, { x: 6.6, y: 3.65, w: 2.9, h: 0, line: { color: HEX.rule, width: 0.75 }, objectName: "pricing-rule" });
T(s, "The densest shell, 700–800 km at 24.1 objects/km, prices near the bottom. The null shows up in the rates.", { x: 6.6, y: 3.8, w: 2.9, h: 0.8, fontSize: 12 });
T(s, "Premium = empirical shell rate × 1.4 load. 400–500 km (3 satellites) and 1500–2000 km (0 events) omitted as too thin.", { x: 6.6, y: 4.65, w: 2.9, h: 0.5, fontSize: 9, italic: true, color: C.accent3 });
s.addNotes("Pricing each shell from its empirical cessation rate with a forty percent load, every shell comes in below the market midpoint. I expected crowded orbits to be under-charged; the data says the market is conservative. And the pooled rate, 2.59 percent a year, lands inside the published one-to-three percent loss band — a check the model passed without ever seeing insurance data.");

// ---------- 8. close ----------
pres.addSection({ title: "Close" });
s = pres.addSlide({ masterName: "CLOSING_DARK", sectionTitle: "Close" });
s.addText("07 — CONCLUSION", { placeholder: "kicker" });
s.addText("The market is conservative, not blunt", { placeholder: "title" });
const cols = [
  ["What held", ["Behaviour-based labels: 4 of 4 validated, Envisat to 7 days", "Empirical rate 2.59%/yr matches market loss data"]],
  ["What didn’t", ["Density predicts nothing — 16 specifications, smallest p 0.36", "Cox loses to logistic on ranking, 0.676 vs 0.696"]],
  ["Next", ["Test a rarer event: fragmentation and anomaly records", "Year-by-year market check, fix the Weibull time origin"]],
];
cols.forEach(([h, items], i) => {
  const x = 0.5 + i * 3.05;
  T(s, h, { x, y: 1.75, w: 2.75, h: 0.4, fontFace: "Cambria", fontSize: 20, color: i === 0 ? C.background1 : (i === 1 ? C.accent1 : C.accent6) });
  T(s, items.map((t, j) => ({ text: t, options: { bullet: true, breakLine: j < items.length - 1, paraSpaceAfter: 8 } })),
    { x, y: 2.25, w: 2.75, h: 1.6, fontSize: 13, color: C.accent4 });
});
s.addShape(pres.shapes.LINE, { x: 0.5, y: 4.25, w: 9, h: 0, line: { color: "3A3A3A", width: 0.75 }, objectName: "close-rule" });
T(s, [{ text: "Run it on any satellite   ", options: { color: C.accent3 } },
      { text: "python scripts/analyse_satellite.py <NORAD ID>", options: { fontFace: "Courier New", color: C.background1 } }],
  { x: 0.5, y: 4.45, w: 9, h: 0.3, fontSize: 12 });
T(s, "github.com/aQuantVortex/orbital-risk", { x: 0.5, y: 4.85, w: 9, h: 0.3, fontSize: 11, color: C.accent3 });
s.addNotes("The hypothesis wasn't supported, and I tried sixteen ways to break that null. But the method validated itself another way: the failure rate it produces lands inside published insurance loss rates. The honest finding is that the flat rate is conservative rather than coarse — the opposite of what I set out to show. I can run the pipeline live on any satellite you choose.");

(async () => {
  await pres.writeFile({ fileName: "Pricing_Orbital_Risk.pptx" });
  await applyTheme("Pricing_Orbital_Risk.pptx", THEME);
  console.log("written");
})();
