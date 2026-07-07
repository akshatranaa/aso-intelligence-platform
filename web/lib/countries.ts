/** App Store storefronts offered in country pickers (mirrors the backend list). */
export const COUNTRIES: { code: string; label: string; flag: string }[] = [
  { code: "in", label: "India", flag: "🇮🇳" },
  { code: "us", label: "United States", flag: "🇺🇸" },
  { code: "gb", label: "United Kingdom", flag: "🇬🇧" },
  { code: "ca", label: "Canada", flag: "🇨🇦" },
  { code: "au", label: "Australia", flag: "🇦🇺" },
  { code: "de", label: "Germany", flag: "🇩🇪" },
  { code: "fr", label: "France", flag: "🇫🇷" },
  { code: "es", label: "Spain", flag: "🇪🇸" },
  { code: "it", label: "Italy", flag: "🇮🇹" },
  { code: "nl", label: "Netherlands", flag: "🇳🇱" },
  { code: "br", label: "Brazil", flag: "🇧🇷" },
  { code: "mx", label: "Mexico", flag: "🇲🇽" },
  { code: "jp", label: "Japan", flag: "🇯🇵" },
  { code: "kr", label: "South Korea", flag: "🇰🇷" },
  { code: "sg", label: "Singapore", flag: "🇸🇬" },
  { code: "ae", label: "United Arab Emirates", flag: "🇦🇪" },
];

export function countryLabel(code: string | null | undefined): string {
  if (!code) return "—";
  const c = COUNTRIES.find((c) => c.code === code.toLowerCase());
  return c ? `${c.flag} ${c.label}` : code.toUpperCase();
}
