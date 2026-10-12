import type { BrainView } from "./brain";

export function Spoken({
  spoken,
  link,
  talkKey,
}: {
  spoken: BrainView["spoken"];
  link: BrainView["link"];
  talkKey: string;
}) {
  const text =
    spoken.text ||
    (link === "online" ? `Hold ${talkKey} and ask me what's going on.` : "");
  if (!text) return null;
  return (
    <p className="says" aria-live="polite">
      {text}
    </p>
  );
}
