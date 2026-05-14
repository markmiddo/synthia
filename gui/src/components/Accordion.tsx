import { useState, type ReactNode } from "react";
import "./Accordion.css";

type AccordionProps = {
  title: string;
  defaultOpen?: boolean;
  badge?: string;
  children: ReactNode;
};

export function Accordion({ title, defaultOpen = false, badge, children }: AccordionProps) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={`accordion${open ? " open" : ""}`}>
      <button
        type="button"
        className="accordion-header"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="accordion-chevron">{open ? "▾" : "▸"}</span>
        <span className="accordion-title">{title}</span>
        {badge && <span className="accordion-badge">{badge}</span>}
      </button>
      {open && <div className="accordion-body">{children}</div>}
    </div>
  );
}
