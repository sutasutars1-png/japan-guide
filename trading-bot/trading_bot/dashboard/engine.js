// Browser port of trading_bot's backtest engine, strategies, walk-forward
// optimizer, promotion gate and replay. It must stay in lockstep with the
// Python code: tests/test_dashboard.py replays both and compares every cycle.
const SIL = (function () {
  "use strict";
  const NEG_INF = -Infinity;
  const PERIODS_PER_YEAR = 365 * 24;

  // ---------- strategies (trading_bot/strategy) ----------
  function product(grid, keep) {
    const keys = Object.keys(grid);
    let out = [{}];
    keys.forEach(k => { const next = []; out.forEach(o => grid[k].forEach(v => next.push(Object.assign({}, o, { [k]: v })))); out = next; });
    return out.filter(keep);
  }
  function sma(x, w) {
    const n = x.length, out = new Array(n).fill(null);
    let sum = 0;
    for (let i = 0; i < n; i++) {
      sum += x[i];
      if (i >= w) sum -= x[i - w];
      if (i >= w - 1) out[i] = sum / w;
    }
    return out;
  }
  function priorExtreme(x, w, pickMax) { // extreme of the w bars before i (excludes bar i)
    const n = x.length, out = new Array(n).fill(null);
    for (let i = w; i < n; i++) {
      let m = x[i - w];
      for (let j = i - w + 1; j < i; j++) m = pickMax ? Math.max(m, x[j]) : Math.min(m, x[j]);
      out[i] = m;
    }
    return out;
  }
  function holdBetween(enter, exit) { // 1 from an entry bar until an exit bar; exit wins a tie
    const out = new Array(enter.length);
    let s = 0;
    for (let i = 0; i < enter.length; i++) {
      if (enter[i]) s = 1;
      if (exit[i]) s = 0;
      out[i] = s;
    }
    return out;
  }
  function rsi(c, period) { // Cutler's RSI: simple rolling means of gains and losses
    const n = c.length, out = new Array(n).fill(null);
    for (let i = period; i < n; i++) {
      let g = 0, l = 0;
      for (let j = i - period + 1; j <= i; j++) { const d = c[j] - c[j - 1]; if (d > 0) g += d; else l -= d; }
      const ag = g / period, al = l / period;
      out[i] = al === 0 ? (ag === 0 ? null : 100) : 100 - 100 / (1 + ag / al);
    }
    return out;
  }

  const STRATEGIES = {
    sma_crossover: {
      label: p => "SMA " + p.fast_window + "/" + p.slow_window,
      grid: () => product({ fast_window: [5, 10, 20, 30], slow_window: [30, 50, 100, 200] }, p => p.fast_window < p.slow_window),
      defaults: { fast_window: 10, slow_window: 50 },
      positions(b, p) {
        const f = sma(b.c, p.fast_window), s = sma(b.c, p.slow_window);
        return b.c.map((_, i) => (s[i] == null ? 0 : f[i] > s[i] ? 1 : 0));
      },
      overlays: (b, p) => [
        { label: "Fast SMA " + p.fast_window, values: sma(b.c, p.fast_window) },
        { label: "Slow SMA " + p.slow_window, values: sma(b.c, p.slow_window) },
      ],
    },
    donchian_breakout: {
      label: p => "Donchian " + p.entry_window + "/" + p.exit_window,
      grid: () => product({ entry_window: [24, 48, 96, 168], exit_window: [12, 24, 48] }, p => p.exit_window <= p.entry_window),
      defaults: { entry_window: 48, exit_window: 24 },
      positions(b, p) {
        const hi = priorExtreme(b.h, p.entry_window, true), lo = priorExtreme(b.l, p.exit_window, false);
        return holdBetween(b.c.map((c, i) => hi[i] != null && c > hi[i]), b.c.map((c, i) => lo[i] != null && c < lo[i]));
      },
      overlays: (b, p) => [
        { label: "過去" + p.entry_window + "本の高値", values: priorExtreme(b.h, p.entry_window, true) },
        { label: "過去" + p.exit_window + "本の安値", values: priorExtreme(b.l, p.exit_window, false) },
      ],
    },
    rsi_reversion: {
      label: p => "RSI" + p.period + " " + p.lower + "→" + p.upper,
      grid: () => product({ period: [14], lower: [25, 30, 35], upper: [50, 60, 70] }, p => p.lower < p.upper),
      defaults: { period: 14, lower: 30, upper: 60 },
      positions(b, p) {
        const r = rsi(b.c, p.period);
        return holdBetween(r.map(v => v != null && v < p.lower), r.map(v => v != null && v > p.upper));
      },
      overlays: () => [],
    },
  };
  // Long/short variants (margin): -1 short, 0 flat, 1 long (strategy/more.py).
  const pct = v => (v * 100).toFixed(1).replace(/\.0$/, "") + "%";
  STRATEGIES.sma_crossover_ls = {
    label: p => "SMA " + p.fast_window + "/" + p.slow_window + (p.band ? " ±" + pct(p.band) : "") + " 売買",
    grid: () => product({ fast_window: [5, 10, 20, 30], slow_window: [30, 50, 100, 200], band: [0, 0.005, 0.01] }, p => p.fast_window < p.slow_window),
    defaults: { fast_window: 10, slow_window: 50, band: 0 },
    positions(b, p) {
      const f = sma(b.c, p.fast_window), s = sma(b.c, p.slow_window);
      return b.c.map((_, i) => (s[i] == null ? 0 : (f[i] > s[i] * (1 + p.band) ? 1 : 0) - (f[i] < s[i] * (1 - p.band) ? 1 : 0)));
    },
    overlays: STRATEGIES.sma_crossover.overlays,
  };
  STRATEGIES.donchian_breakout_ls = {
    label: p => "Donchian " + p.entry_window + "/" + p.exit_window + " 売買",
    grid: STRATEGIES.donchian_breakout.grid,
    defaults: STRATEGIES.donchian_breakout.defaults,
    positions(b, p) {
      const hiE = priorExtreme(b.h, p.entry_window, true), loE = priorExtreme(b.l, p.entry_window, false);
      const hiX = priorExtreme(b.h, p.exit_window, true), loX = priorExtreme(b.l, p.exit_window, false);
      const above = (x, i) => x[i] != null && b.c[i] > x[i], below = (x, i) => x[i] != null && b.c[i] < x[i];
      const long_ = holdBetween(b.c.map((_, i) => above(hiE, i)), b.c.map((_, i) => below(loX, i)));
      const short = holdBetween(b.c.map((_, i) => below(loE, i)), b.c.map((_, i) => above(hiX, i)));
      return long_.map((v, i) => v - short[i]);
    },
    overlays: (b, p) => [
      { label: "過去" + p.entry_window + "本の高値", values: priorExtreme(b.h, p.entry_window, true) },
      { label: "過去" + p.entry_window + "本の安値", values: priorExtreme(b.l, p.entry_window, false) },
    ],
  };
  STRATEGIES.rsi_reversion_ls = {
    label: p => "RSI" + p.period + " " + p.lower + "/" + (100 - p.lower) + " 売買",
    grid: STRATEGIES.rsi_reversion.grid,
    defaults: STRATEGIES.rsi_reversion.defaults,
    positions(b, p) {
      const r = rsi(b.c, p.period);
      const long_ = holdBetween(r.map(v => v != null && v < p.lower), r.map(v => v != null && v > p.upper));
      const short = holdBetween(r.map(v => v != null && v > 100 - p.lower), r.map(v => v != null && v < 100 - p.upper));
      return long_.map((v, i) => v - short[i]);
    },
    overlays: () => [],
  };
  function multi(members) {
    const first = members[0];
    return {
      members,
      label: p => STRATEGIES[p.strategy].label(p),
      grid: () => [].concat(...members.map(m => STRATEGIES[m].grid().map(p => Object.assign({ strategy: m }, p)))),
      defaults: Object.assign({ strategy: first }, STRATEGIES[first].defaults),
      positions: (b, p) => STRATEGIES[p.strategy].positions(b, p),
      overlays: (b, p) => STRATEGIES[p.strategy].overlays(b, p),
    };
  }
  STRATEGIES.multi = multi(["sma_crossover", "donchian_breakout", "rsi_reversion"]);
  STRATEGIES.multi_ls = multi(["sma_crossover_ls", "donchian_breakout_ls", "rsi_reversion_ls"]);

  function sameParams(a, b) {
    if (!a || !b) return false;
    const ka = Object.keys(a), kb = Object.keys(b);
    return ka.length === kb.length && ka.every(k => a[k] === b[k]);
  }

  // ---------- backtest engine (trading_bot/backtest) ----------
  function mean(a) { let s = 0; for (const v of a) s += v; return s / a.length; }
  function sampleStd(a) {
    if (a.length < 2) return 0;
    const m = mean(a); let ss = 0;
    for (const v of a) ss += (v - m) * (v - m);
    return Math.sqrt(ss / (a.length - 1));
  }
  // Position held during each bar, from targets decided at each close (engine.py `execute`).
  function execute(b, raw, orderType) {
    const n = raw.length, out = new Array(n).fill(0);
    if (orderType !== "limit") { for (let t = 1; t < n; t++) out[t] = raw[t - 1]; return out; }
    let cur = 0;
    for (let t = 0; t < n - 1; t++) {
      const target = raw[t];
      if (target > cur) { if (b.l[t + 1] < b.c[t]) cur = target; }       // buy limit: next bar must trade below it
      else if (target < cur) { if (b.h[t + 1] > b.c[t]) cur = target; }  // sell limit: next bar must trade above it
      out[t + 1] = cur;
    }
    return out;
  }
  // Margin account in money (engine.py `account_equity`): a fill commits the whole
  // equity at the previous close and that quantity is held until the next fill.
  function accountEquity(held, c, cash, cost, carryPerBar) {
    const out = new Array(held.length);
    let qty = 0, entry = 0, prev = 0;
    for (let t = 0; t < held.length; t++) {
      const pos = held[t];
      if (pos !== prev) {
        const price = c[t - 1];
        if (qty) { cash += qty * (price - entry) - Math.abs(qty) * price * cost; qty = 0; }
        if (pos) { const fee = cash * cost; cash -= fee; qty = pos * cash / price; entry = price; }
        prev = pos;
      }
      if (qty) { cash -= Math.abs(qty) * c[t] * carryPerBar; out[t] = cash + qty * (c[t] - entry); }
      else out[t] = cash;
    }
    return out;
  }
  // cfg: {cost (per side, fraction), cash, orderType, carryPerDay}
  function runPositions(b, rawPos, cfg) {
    const closes = b.c, n = closes.length, cost = cfg.cost;
    const carryPerBar = (cfg.carryPerDay || 0) * 365 / PERIODS_PER_YEAR;
    const exec = execute(b, rawPos, cfg.orderType);
    const equity = accountEquity(exec, closes, cfg.cash, cost, carryPerBar);
    const net = equity.map((e, i) => { const p = i === 0 ? cfg.cash : equity[i - 1]; return (e - p) / p; });
    const trades = [];
    let open = null, openedAt = 0;
    for (let t = 1; t < n; t++) { // a position held from bar t was filled at bar t-1's close
      if (exec[t] === exec[t - 1]) continue;
      if (open) {
        open.exitIdx = t - 1; open.exitPrice = closes[t - 1];
        open.pnl = open.side * (open.exitPrice / open.entryPrice - 1) - 2 * cost - carryPerBar * (t - openedAt);
        trades.push(open); open = null;
      }
      if (exec[t] !== 0) { open = { side: Math.sign(exec[t]), entryIdx: t - 1, entryPrice: closes[t - 1], exitIdx: null, exitPrice: null, pnl: null }; openedAt = t; }
    }
    if (open) { open.exitIdx = n - 1; open.exitPrice = closes[n - 1]; trades.push(open); }
    const years = (n - 1) / PERIODS_PER_YEAR;
    let cagr = 0;
    if (n >= 2 && equity[0] > 0 && years > 0) { const t = equity[n - 1] / equity[0]; cagr = t <= 0 ? -1 : Math.pow(t, 1 / years) - 1; }
    const sd = sampleStd(net);
    let peak = -Infinity, mdd = 0;
    for (const e of equity) { peak = Math.max(peak, e); mdd = Math.min(mdd, e / peak - 1); }
    const closed = trades.filter(t => t.pnl !== null);
    return {
      exec, net, equity, trades,
      metrics: {
        total_return: equity[0] === 0 ? 0 : equity[n - 1] / equity[0] - 1, cagr,
        sharpe: sd === 0 || Number.isNaN(sd) ? 0 : (mean(net) / sd) * Math.sqrt(PERIODS_PER_YEAR),
        ann_return: n ? mean(net) * PERIODS_PER_YEAR : 0,
        max_drawdown: mdd,
        win_rate: closed.length ? closed.filter(t => t.pnl > 0).length / closed.length : 0,
        num_trades: closed.length, final_equity: equity[n - 1],
      },
    };
  }
  function slice(b, s, e) { return { c: b.c.slice(s, e), h: b.h.slice(s, e), l: b.l.slice(s, e), t: b.t.slice(s, e) }; }

  // ---------- optimizer + gate (trading_bot/optimize, self_improve/loop.py) ----------
  function score(m, cfg) { // optimizer.py default_score: annualized Sharpe or annualized mean return
    return m.num_trades < cfg.minTrades ? NEG_INF : cfg.score === "return" ? m.ann_return : m.sharpe;
  }
  function gridSearch(b, strat, grid, cfg) {
    const board = grid.map(p => ({ params: p, score: score(runPositions(b, strat.positions(b, p), cfg).metrics, cfg) }));
    board.sort((x, y) => (x.score === y.score ? 0 : x.score > y.score ? -1 : 1)); // stable, like Python's sort
    if (!board.length || board[0].score === NEG_INF) return { best: null, bestScore: NEG_INF, board };
    return { best: board[0].params, bestScore: board[0].score, board };
  }
  function foldBounds(n, k) { const step = Math.floor(n / k), b = []; for (let i = 0; i < k; i++) b.push(i * step); b.push(n); return b; }
  function runFold(b, strat, p, start, end, cfg) { // indicators warmed up on bars before `start`
    const pos = strat.positions(slice(b, 0, end), p).slice(start, end);
    return runPositions(slice(b, start, end), pos, cfg);
  }
  function optimize(b, strat, grid, cfg) {
    const n = b.c.length, bounds = foldBounds(n, cfg.nSplits), tests = [];
    for (let i = 1; i < cfg.nSplits; i++) {
      const start = bounds[i], end = bounds[i + 1];
      if (end - start < 5 || start < 10) continue;
      const chosen = gridSearch(slice(b, 0, start), strat, grid, cfg).best;
      if (!chosen) continue;
      tests.push(score(runFold(b, strat, chosen, start, end, cfg).metrics, cfg));
    }
    const finite = tests.filter(s => s !== NEG_INF);
    const g = gridSearch(b, strat, grid, cfg);
    return { finalParams: g.best, finalScore: g.bestScore, walkForwardScore: finite.length ? mean(finite) : NEG_INF, leaderboard: g.board, nCandidates: g.board.length };
  }
  function evaluateParams(b, strat, p, cfg) {
    const bounds = foldBounds(b.c.length, cfg.nSplits), scores = [];
    for (let i = 1; i < cfg.nSplits; i++) {
      const start = bounds[i], end = bounds[i + 1];
      if (end - start < 5 || start < 10) continue;
      const s = score(runFold(b, strat, p, start, end, cfg).metrics, cfg);
      if (s !== NEG_INF) scores.push(s);
    }
    return scores.length ? mean(scores) : NEG_INF;
  }
  function marginFor(cfg, nCandidates) {
    const base = cfg.candidateBaseline || 15;
    return cfg.margin * (nCandidates ? Math.max(1, Math.sqrt(nCandidates / base)) : 1);
  }
  function decide(res, incumbent, incScore, cfg) {
    const wf = res.walkForwardScore;
    if (!res.finalParams || wf === NEG_INF) return { promoted: false, code: "no_viable" };
    if (wf < cfg.minWf) return { promoted: false, code: "below_floor" };
    if (sameParams(res.finalParams, incumbent)) return { promoted: false, code: "same_as_active" };
    if (wf < incScore + marginFor(cfg, res.nCandidates)) return { promoted: false, code: "insufficient_margin" };
    return { promoted: true, code: "promoted" };
  }

  // ---------- replay (trading_bot/self_improve/replay.py) ----------
  // bars: {c, h, l, t}; cfg: {strategy, initialParams, history, every, nSplits, minTrades, score, minWf, margin,
  //   cost, cash, orderType, carryPerDay, evalStart}
  function replay(bars, cfg) {
    const strat = STRATEGIES[cfg.strategy], grid = strat.grid(), n = bars.c.length;
    const paramsList = [cfg.initialParams];
    let active = 0;
    const activeByBar = new Array(n), cycles = [], first = cfg.history - 1;
    for (let t = 0; t < n; t++) {
      if (t >= first && (t - first) % cfg.every === 0) {
        const w = slice(bars, t + 1 - cfg.history, t + 1), incumbent = paramsList[active];
        const res = optimize(w, strat, grid, cfg), incScore = evaluateParams(w, strat, incumbent, cfg);
        const d = decide(res, incumbent, incScore, cfg);
        if (d.promoted) {
          let idx = paramsList.findIndex(p => sameParams(p, res.finalParams));
          if (idx < 0) { paramsList.push(res.finalParams); idx = paramsList.length - 1; }
          active = idx;
        }
        cycles.push({ barIndex: t, time: bars.t[t], incumbent, incumbentScore: incScore, candidate: res.finalParams,
          candidateWf: res.walkForwardScore, promoted: d.promoted, code: d.code, activeAfter: paramsList[active],
          leaderboard: res.leaderboard, margin: marginFor(cfg, res.nCandidates) });
      }
      activeByBar[t] = active;
    }
    const posByParams = paramsList.map(p => strat.positions(bars, p));
    const systemPos = activeByBar.map((a, t) => posByParams[a][t]);
    // Score only bars from evalStart on; cycles before it still learn from them.
    const e0 = cfg.evalStart || 0, scored = slice(bars, e0, n);
    return {
      paramsList, activeByBar, cycles, systemPos, evalStart: e0,
      runs: {
        self_improving: runPositions(scored, systemPos.slice(e0), cfg),
        static: runPositions(scored, posByParams[0].slice(e0), cfg),
        // The benchmark is holding spot BTC: no margin, so no carry.
        buy_hold: runPositions(scored, new Array(n - e0).fill(1), Object.assign({}, cfg, { carryPerDay: 0 })),
      },
    };
  }

  return { replay, runPositions, STRATEGIES, sameParams, NEG_INF };
})();
if (typeof module !== "undefined") module.exports = SIL;
