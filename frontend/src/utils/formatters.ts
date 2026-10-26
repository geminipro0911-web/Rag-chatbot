/**
 * Utility formatters for enterprise dates, file sizes, and Vietnamese locale numbers.
 */

export function formatBytes(bytes: number, decimals = 1): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`;
}

export function formatDate(dateStr?: string | null): string {
  if (!dateStr) return '';
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return dateStr;
    return d.toLocaleString('vi-VN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return dateStr;
  }
}

export function formatScorePct(score?: number | null): string {
  if (score === null || score === undefined) return '';
  const pct = Math.round(score * 1000) / 10;
  return `${pct.toFixed(1)}%`;
}

/**
 * Strictly parses a string/number as a numeric value without falsely classifying dates (e.g. 15/03/2026),
 * identifiers starting with digits (e.g. 2026-Q1, 101_SP), or IDs with leading zeroes (e.g. "00123").
 */
export function parseStrictNumber(val: any): number | null {
  if (val === null || val === undefined) return null;
  if (typeof val === 'number') {
    return isNaN(val) ? null : val;
  }

  const str = String(val).trim();
  if (!str) return null;

  // Reject strings containing slashes, letters, or underscores
  if (/[a-zA-Z\/_]/.test(str)) return null;

  // Leading zero check: e.g. "00123" or "0123" is an ID or phone number, not a plain number
  if (/^0\d+/.test(str)) return null;

  // Handle Vietnamese format (1.234.567,89) or international format (1,234,567.89)
  let normalized = str;

  if (str.includes(',') && str.includes('.')) {
    // Determine which is thousand separator and which is decimal
    if (str.lastIndexOf(',') > str.lastIndexOf('.')) {
      // VN format: 1.234.567,89
      normalized = str.replace(/\./g, '').replace(',', '.');
    } else {
      // US format: 1,234,567.89
      normalized = str.replace(/,/g, '');
    }
  } else if (str.includes(',')) {
    // Either VN decimal (123,45) or US thousands (1,234)
    const parts = str.split(',');
    if (parts.length === 2 && parts[1].length <= 4) {
      // Decimal: 123,45 -> 123.45
      normalized = str.replace(',', '.');
    } else {
      // Thousands: 1,234,567 -> 1234567
      normalized = str.replace(/,/g, '');
    }
  } else if (str.includes('.')) {
    const parts = str.split('.');
    if (parts.length > 2) {
      // Multiple dots -> VN thousands: 1.234.567 -> 1234567
      normalized = str.replace(/\./g, '');
    } else if (parts.length === 2 && parts[1].length === 3 && parts[0].length >= 1) {
      // Could be VN thousand (1.000) or US decimal (1.234)
      // If it looks like integer thousand
      if (/^\d{1,3}\.\d{3}$/.test(str)) {
        normalized = str.replace(/\./g, '');
      }
    }
  }

  // Must match strict numeric regex: optional minus, followed by digits, optional dot and decimals
  if (!/^-?(?:0|[1-9]\d*)(?:\.\d+)?$/.test(normalized)) {
    return null;
  }

  const num = Number(normalized);
  return isNaN(num) ? null : num;
}

/**
 * Parses Vietnamese date strings (dd/mm/yyyy or dd-mm-yyyy) and standard ISO dates (yyyy-mm-dd)
 * to a millisecond timestamp for correct chronological sorting.
 */
export function parseViDateTimestamp(val: any): number | null {
  if (!val) return null;
  const str = String(val).trim();

  // Match dd/mm/yyyy or dd-mm-yyyy
  const dmyMatch = /^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})$/.exec(str);
  if (dmyMatch) {
    const day = parseInt(dmyMatch[1], 10);
    const month = parseInt(dmyMatch[2], 10) - 1;
    const year = parseInt(dmyMatch[3], 10);
    const d = new Date(year, month, day);
    if (!isNaN(d.getTime())) return d.getTime();
  }

  // Match ISO yyyy-mm-dd
  const ymdMatch = /^(\d{4})[\/\-](\d{1,2})[\/\-](\d{1,2})/.exec(str);
  if (ymdMatch) {
    const d = new Date(str);
    if (!isNaN(d.getTime())) return d.getTime();
  }

  return null;
}

/**
 * Formats a value as Vietnamese currency/number if applicable, preserving codes and dates.
 */
export function formatViNumber(val: any): string {
  if (val === null || val === undefined) return '';
  const num = parseStrictNumber(val);
  if (num !== null) {
    return num.toLocaleString('vi-VN');
  }
  return String(val);
}
