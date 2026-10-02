/**
 * 数字/时间/价格格式化 —— 全站唯一实现
 * 原则：金融数字一律 tabular-nums；涨跌必带符号与方向箭头（不依赖颜色）。
 */

export function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '--';
  return Number(v).toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/** 带符号数字（盈亏类）：+15.85 / -3.20 */
export function fmtSigned(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '--';
  const n = Number(v);
  const s = fmtNum(Math.abs(n), digits);
  if (n > 0) return `+${s}`;
  if (n < 0) return `-${s}`;
  return s;
}

export function fmtUsdt(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '--';
  return `${fmtSigned(v, digits)} USDT`;
}

export function fmtPct(v: number | null | undefined, digits = 2, signed = true): string {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '--';
  const n = Number(v);
  return `${signed && n > 0 ? '+' : ''}${n.toFixed(digits)}%`;
}

/** 价格自适应精度：大数 2 位、小币 4~6 位
 *
 * 批 20：**0 视为「无值」→ `--`**。
 * 旧实现把 0 当普通数字，`abs < 0.01` 落到 6 位精度，于是台账/持仓/矩阵里
 * 缺数据的行渲染成 `0.000000` —— 既占位又像真值（实测 34 笔台账里有多行如此）。
 * 加密资产不存在价格恰为 0 的标的，故 0 与 null / NaN 同档处理。
 * 精度档保持不变：≥1000→2 / ≥10→3 / ≥1→4 / ≥0.01→5 / 其余→6。
 * 该规则由 `tests/format.test.mjs` 钉住。
 */
export function fmtPrice(v: number | string | null | undefined): string {
  const n = Number(v);
  if (!Number.isFinite(n) || n === 0) return '--';
  const abs = Math.abs(n);
  const digits = abs >= 1000 ? 2 : abs >= 10 ? 3 : abs >= 1 ? 4 : abs >= 0.01 ? 5 : 6;
  return fmtNum(n, digits);
}

/** 大数缩写：1.2M / 345K */
export function fmtCompact(v: number | null | undefined, digits = 1): string {
  const n = Number(v);
  if (!Number.isFinite(n)) return '--';
  const abs = Math.abs(n);
  if (abs >= 1e9) return `${(n / 1e9).toFixed(digits)}B`;
  if (abs >= 1e6) return `${(n / 1e6).toFixed(digits)}M`;
  if (abs >= 1e3) return `${(n / 1e3).toFixed(digits)}K`;
  return fmtNum(n, abs >= 100 ? 0 : 2);
}

/** 涨跌方向语义类（配合 .up/.down 与 ▲▼） */
export function dirClass(v: number | null | undefined): string {
  const n = Number(v);
  if (!Number.isFinite(n) || n === 0) return '';
  return n > 0 ? 'up' : 'down';
}

export function arrow(v: number | null | undefined): string {
  const n = Number(v);
  if (!Number.isFinite(n) || n === 0) return '—';
  return n > 0 ? '▲' : '▼';
}

/* —— 时间 —— */

/** Display zone is a product contract, never the browser/OS default. */
export const DISPLAY_TIME_ZONE = 'Asia/Shanghai';
export type TimeInput = Date | string | number | null | undefined;

/** Legacy business strings are Beijing wall time; explicitly UTC fields opt in.
 * Epoch values retain their instant (seconds and milliseconds are both accepted).
 * An existing Z/offset always wins: never append a second timezone or add 8h twice.
 */
export function parseTime(input: TimeInput, naiveZone: 'beijing' | 'utc' = 'beijing'): Date {
  if (input instanceof Date) return new Date(input.getTime());
  if (input === null || input === undefined || input === '') return new Date(NaN);
  if (typeof input === 'number' || /^-?\d+(?:\.\d+)?$/.test(String(input).trim())) {
    const n = Number(input);
    return new Date(Math.abs(n) < 1e11 ? n * 1000 : n);
  }
  let text = String(input).trim().replace(/\s+UTC$/i, 'Z').replace(/\s*(?:\(北京时间\)|北京时间)$/, '+08:00').replace(' ', 'T');
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) text += 'T00:00:00';
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/.test(text)) {
    text += naiveZone === 'utc' ? 'Z' : '+08:00';
  }
  // Reject ambiguous locale dates instead of silently using the browser timezone.
  if (!/(?:Z|[+-]\d{2}:?\d{2})$/i.test(text)) return new Date(NaN);
  return new Date(text);
}

function beijingParts(input: TimeInput): Record<string, string> | null {
  const d = parseTime(input);
  if (Number.isNaN(d.getTime())) return null;
  return Object.fromEntries(new Intl.DateTimeFormat('en-GB', {
    timeZone: DISPLAY_TIME_ZONE, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  }).formatToParts(d).map(p => [p.type, p.value]));
}

export function fmtClock(input: TimeInput): string {
  const p = beijingParts(input);
  return p ? `${p.hour}:${p.minute}:${p.second}` : '--';
}

export function fmtDate(input: TimeInput): string {
  const p = beijingParts(input);
  return p ? `${p.year}-${p.month}-${p.day}` : '--';
}

export function fmtDateTime(input: TimeInput): string {
  if (!beijingParts(input)) return '--';
  return `${fmtDate(input)} ${fmtClock(input)}`;
}

export function fmtHM(input: TimeInput): string {
  const p = beijingParts(input);
  return p ? `${p.hour}:${p.minute}` : '--';
}

/**
 * 置信度 → 档位（未校准概率不展示裸数字，悬停/详情给原值）。
 *
 * 批 76：原先还返回一个中文 `label`（高/中/低），**全站无人使用** ——
 * `ConfBadge` 一直用 `t('common.conf.<tier>')` 自己取词。
 * 这个死字段是一颗隐雷：将来谁读了它就会在英文界面渲染出中文，故删掉。
 */
export function confTier(v: number | null | undefined): { tier: 'high' | 'mid' | 'low' } | null {
  const n = Number(v);
  if (!Number.isFinite(n) || n <= 0) return null;
  if (n >= 80) return { tier: 'high' };
  if (n >= 65) return { tier: 'mid' };
  return { tier: 'low' };
}

/** 去掉文本前导装饰性 emoji 与技术后缀 */
export function cleanReason(v: string | null | undefined): string {
  if (!v) return '--'
  return v
    .replace(/^[\p{Extended_Pictographic}\uFE0F\u200D\s]+/u, '')
    .replace(/[\(（]未匹配平仓单[\)）]/g, '')
    .trim() || '--'
}

/** Explicitly UTC legacy feed fields; offset-aware inputs preserve their instant. */
export function utcStrToBj(v: TimeInput, withDate = false): string {
  const d = parseTime(v, 'utc');
  if (Number.isNaN(d.getTime())) return '--';
  return withDate ? fmtDateTime(d) : fmtClock(d);
}
