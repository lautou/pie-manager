/** Pure date-conversion helpers for FrDatePicker — exported for testability. */

export const dateFormat = (date: Date): string =>
  date.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' })

export const dateParse = (val: string): Date => {
  const parts = val.split('/')
  if (parts.length === 3 && parts[2].length === 4) {
    const day = +parts[0]
    const month = +parts[1]
    const year = +parts[2]
    // Reject partial/invalid values (day=0 would give last day of prev month,
    // month=0 would give December of prev year — both wrong intermediate states)
    if (day < 1 || day > 31 || month < 1 || month > 12 || year < 1900) {
      return new Date('invalid')
    }
    // Parse at noon to avoid timezone shifts
    return new Date(year, month - 1, day, 12, 0, 0)
  }
  return new Date('invalid')
}

export const isoToDisplay = (iso: string): string => {
  if (!iso || iso.length < 10) return ''
  // Parse as noon to avoid UTC shift issues
  const d = new Date(iso + 'T12:00:00')
  return isNaN(d.getTime()) ? '' : dateFormat(d)
}

export const dateToISO = (date: Date): string => {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}
