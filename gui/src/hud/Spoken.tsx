import type { BrainView } from "./brain";

export function Spoken({ spoken, link }: { spoken: BrainView["spoken"]; link: BrainView["link"] }) {
  const text =
    spoken.text ||
    (link === "online" ? "Hold Right Alt and ask me what's going on." : "");
  if (!text) return null;
  return (
    <p className="says" aria-live="polite">
      {text}
    </p>
  );
}
