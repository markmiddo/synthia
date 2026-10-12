import { lastSevenDays } from "./format";

export function DayPicker({
  selected,
  onSelect,
}: {
  selected: string;
  onSelect: (date: string) => void;
}) {
  const days = lastSevenDays(new Date());
  return (
    <div className="days" role="group" aria-label="Day">
      {days.map((d) => (
        <button
          type="button"
          key={d.date}
          className={d.date === selected ? "on" : undefined}
          aria-pressed={d.date === selected}
          onClick={() => onSelect(d.date)}
        >
          {d.label}
        </button>
      ))}
    </div>
  );
}
