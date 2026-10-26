/**
 * CSV and Clipboard Export Utilities.
 * Uses UTF-8 with BOM (\uFEFF) to guarantee Microsoft Excel renders Vietnamese characters correctly without mojibake.
 */

export function exportTableToCsv(
  fileName: string,
  headers: string[],
  rows: (string | number | null | undefined)[][]
): void {
  const sanitize = (val: any): string => {
    if (val === null || val === undefined) return '""';
    let s = String(val);
    // Sanitize CSV Formula Injection (DDE) triggers: =, +, -, @, tab, carriage return
    if (/^[=+\-@\t\r]/.test(s)) {
      s = `'${s}`;
    }
    s = s.replace(/"/g, '""');
    return `"${s}"`;
  };

  const csvRows: string[] = [];
  csvRows.push(headers.map(sanitize).join(','));

  for (const row of rows) {
    csvRows.push(row.map(sanitize).join(','));
  }

  // Prepend UTF-8 BOM
  const csvContent = '\uFEFF' + csvRows.join('\r\n');
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);

  const safeName = (fileName || 'export').endsWith('.csv')
    ? fileName
    : `${fileName || 'export'}.csv`;

  const link = document.createElement('a');
  link.setAttribute('href', url);
  link.setAttribute('download', safeName);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

export async function copyTableToClipboard(
  headers: string[],
  rows: (string | number | null | undefined)[][]
): Promise<boolean> {
  try {
    const headerLine = headers.join('\t');
    const rowLines = rows.map((r) => r.map((c) => (c === null || c === undefined ? '' : String(c))).join('\t'));
    const tsvContent = [headerLine, ...rowLines].join('\n');
    await navigator.clipboard.writeText(tsvContent);
    return true;
  } catch (err) {
    console.error('Failed to copy table to clipboard:', err);
    return false;
  }
}
