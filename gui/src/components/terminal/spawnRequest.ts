export interface SpawnRequest {
  cwd?: string;
  shell?: string;
  initialCommand?: string;
}

type Listener = (req: SpawnRequest) => void;

const listeners = new Set<Listener>();

export function requestTerminal(req: SpawnRequest) {
  for (const l of listeners) l(req);
}

export function onSpawnRequest(l: Listener): () => void {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
}
