import { useRef, useEffect } from "react";
import LightsaberIndicator from "./LightsaberIndicator";

export default function StreamingBubble({ text }: { text: string }) {
  const cursorRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    cursorRef.current?.scrollIntoView({ block: "nearest" });
  }, [text]);

  return (
    <div className="group animate-fade-in">
      <div className="prose max-w-none text-sm text-text-primary">
        <pre className="whitespace-pre-wrap break-words bg-transparent p-0 font-sans text-sm leading-relaxed text-text-primary">
          {text}
          <span ref={cursorRef}>
            <LightsaberIndicator className="ml-1" />
          </span>
        </pre>
      </div>
      <div className="mt-1.5 text-[10px] text-text-muted animate-pulse">
        Streaming...
      </div>
    </div>
  );
}
