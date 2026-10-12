/** "Synthia", drawn from the --wordmark-* CSS variables (see tokens.css).
 *  `size` is the font size in px: about 34 in the top bar, 44 under the orb. */
export function Wordmark({ size = 34, className = "" }: { size?: number; className?: string }) {
  return (
    <span className={`wordmark ${className}`.trim()} style={{ fontSize: size }}>
      Synthia
    </span>
  );
}
