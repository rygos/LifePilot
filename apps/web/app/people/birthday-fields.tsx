"use client";

import { useState } from "react";

export type BirthdayPrecision = "exact" | "month_day" | "approximate" | "unknown";

type Props = {
  precision?: BirthdayPrecision;
  birthday?: string | null;
  month?: number | null;
  day?: number | null;
  approximateAge?: number | null;
};

function monthDayValue(month?: number | null, day?: number | null): string {
  if (!month || !day) return "";
  return `2000-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

function birthdayPrecision(value: string): BirthdayPrecision {
  if (value === "exact" || value === "month_day" || value === "approximate") return value;
  return "unknown";
}

export function BirthdayFields({ precision = "unknown", birthday, month, day, approximateAge }: Props) {
  const [selected, setSelected] = useState<BirthdayPrecision>(precision);
  return <fieldset className="birthday-fields">
    <legend>Geburtstag</legend>
    <label>Wie genau ist das Datum?
      <select name="birthday_precision" value={selected} onChange={event => setSelected(birthdayPrecision(event.target.value))}>
        <option value="unknown">Unbekannt</option>
        <option value="approximate">Ungefähres Alter</option>
        <option value="month_day">Tag und Monat</option>
        <option value="exact">Genaues Datum</option>
      </select>
    </label>
    {selected === "exact" && <label>Geburtsdatum<input type="date" name="birthday" defaultValue={birthday ?? ""} required /></label>}
    {selected === "month_day" && <label>Tag und Monat<input type="date" name="birthday_month_day" min="2000-01-01" max="2000-12-31" defaultValue={monthDayValue(month, day)} required /><small>Das Jahr wird nicht gespeichert.</small></label>}
    {selected === "approximate" && <label>Ungefähres Alter<input type="number" name="birthday_approximate_age" min="0" max="130" defaultValue={approximateAge ?? ""} required /></label>}
  </fieldset>;
}
