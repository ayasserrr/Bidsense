// Null renders as nothing, never a placeholder like "—" or "Not stated".
export function formatAmount(value: number | null): string {
  if (value === null) return ""
  return new Intl.NumberFormat("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 2 }).format(value)
}

/** Amount + currency in one string, for contexts with no separate currency column. */
export function formatMoney(value: number | null, currency: string | null): string {
  const formatted = formatAmount(value)
  if (!formatted) return ""
  return currency ? `${formatted} ${currency}` : formatted
}

export function formatDate(iso: string | null): string {
  if (!iso) return ""
  try {
    return new Intl.DateTimeFormat("en-US", { year: "numeric", month: "long", day: "numeric" }).format(new Date(iso))
  } catch {
    return iso
  }
}

export function formatBoolean(value: boolean | null, whenTrue: string, whenFalse: string): string | null {
  if (value === null) return null
  return value ? whenTrue : whenFalse
}

/** The dashboard/compare/rates screens carry money as exact-decimal STRINGS
 * (see schema/rates.py's own note: a float would stop re-adding to the same
 * number a converted grand total was computed from). `Number()` is fine for
 * DISPLAY here - nothing downstream recomputes from this string - but it must
 * never be sent back to the server as a number. */
export function formatDecimalString(value: string | null | undefined): string {
  if (value === null || value === undefined) return ""
  const n = Number(value)
  if (Number.isNaN(n)) return ""
  return formatAmount(n)
}

/** A `ConvertedMoney` shape: the original figure in its own currency, plus
 * the converted one where a rate exists. Shows both - never just the
 * converted number standing in for the original. */
export function formatConvertedMoney(money: {
  original_amount: string | null
  original_currency: string | null
  converted_amount: string | null
  base_currency: string
  unconvertible_reason: string | null
}): { original: string; converted: string | null; note: string | null } {
  const original = formatMoney(
    money.original_amount === null ? null : Number(money.original_amount),
    money.original_currency,
  )
  if (money.converted_amount === null) {
    return { original, converted: null, note: money.unconvertible_reason }
  }
  const converted = formatMoney(Number(money.converted_amount), money.base_currency)
  return { original, converted, note: null }
}

// Some values already end with the unit (e.g. "19mm" + unit "mm") - don't double it up.
export function formatSpecValue(value: string, unit: string | null): string {
  if (!unit) return value
  if (value.trim().toLowerCase().endsWith(unit.trim().toLowerCase())) return value
  return `${value} ${unit}`
}
