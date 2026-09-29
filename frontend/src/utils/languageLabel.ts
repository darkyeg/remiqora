/** Show a language's own name alongside its name in the current interface. */
export function languageLabel(code: string, nativeName: string, displayLocale: string): string {
  const translated = new Intl.DisplayNames([displayLocale], { type: 'language' }).of(code)
  if (!translated || translated === code || translated.toLocaleLowerCase(displayLocale) === nativeName.toLocaleLowerCase(displayLocale)) {
    return nativeName
  }
  return `${nativeName} (${translated})`
}
