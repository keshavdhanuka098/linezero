import { describe, expect, it } from 'vitest'
import { toCsv } from '../exporters'
import { nameValid, numberIn } from '../validate'

describe('validate', () => {
  it('numberIn checks presence, type, integer and range', () => {
    expect(numberIn('', 1, 5, 'X')).toMatch(/required/)
    expect(numberIn('a', 1, 5, 'X')).toMatch(/number/)
    expect(numberIn('1.5', 1, 5, 'X', true)).toMatch(/whole/)
    expect(numberIn('9', 1, 5, 'X')).toMatch(/between/)
    expect(numberIn('3', 1, 5, 'X')).toBeUndefined()
  })
  it('nameValid rejects blanks and duplicates (case-insensitive)', () => {
    expect(nameValid(' ', [])).toMatch(/required/)
    expect(nameValid('Billing', ['billing'])).toMatch(/exists/)
    expect(nameValid('New', ['Billing'])).toBeUndefined()
  })
})

describe('toCsv', () => {
  it('quotes commas, quotes and newlines and unions columns', () => {
    expect(toCsv([{ a: 'x,y', b: 1 }, { a: 'say "hi"', c: 2 }])).toBe('a,b,c\r\n"x,y",1,\r\n"say ""hi""",,2')
  })
  it('returns an empty string for no rows', () => {
    expect(toCsv([])).toBe('')
  })
})
