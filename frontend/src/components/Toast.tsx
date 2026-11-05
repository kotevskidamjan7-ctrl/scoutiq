import { useEffect } from "react";

export default function Toast({ text, onDone }: { text: string | null; onDone: () => void }) {
  useEffect(() => {
    if (!text) return;
    const t = setTimeout(onDone, 3500);
    return () => clearTimeout(t);
  }, [text, onDone]);
  if (!text) return null;
  return (
    <div role="status" className="fixed bottom-5 left-1/2 z-50 -translate-x-1/2 rounded-md bg-board px-4 py-2 text-chalk shadow-lg">
      {text}
    </div>
  );
}
