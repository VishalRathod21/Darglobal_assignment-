import { useEffect, useRef, useState } from "react";

const MAX_LENGTH = 600;

interface Props {
  disabled: boolean;
  onSend: (question: string) => void;
}

export function Composer({ disabled, onSend }: Props) {
  const [value, setValue] = useState("");
  const textarea = useRef<HTMLTextAreaElement>(null);

  // Grow with the content up to a limit, then scroll.
  useEffect(() => {
    const element = textarea.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, 160)}px`;
  }, [value]);

  useEffect(() => {
    if (!disabled) textarea.current?.focus();
  }, [disabled]);

  const submit = () => {
    const question = value.trim();
    if (!question || disabled) return;
    onSend(question);
    setValue("");
  };

  return (
    <div className="relative border-t border-slate-200/80 bg-gradient-to-t from-slate-100/90 via-slate-50/60 to-transparent px-4 pb-5 pt-3">
      <div className="mx-auto max-w-3xl">
        {/* Floating Input Dock */}
        <div className="flex items-end gap-2.5 rounded-2xl border border-slate-200/90 bg-white/95 p-2 shadow-lg shadow-slate-200/40 backdrop-blur-md transition-all duration-200 focus-within:border-amber-600 focus-within:ring-2 focus-within:ring-amber-500/15">
          <textarea
            ref={textarea}
            rows={1}
            value={value}
            maxLength={MAX_LENGTH}
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                submit();
              }
            }}
            placeholder="Ask about luxury developments, amenities, pricing, or KSA listings..."
            aria-label="Your question"
            className="max-h-40 flex-1 resize-none bg-transparent px-3 py-2 text-[15px] leading-6 text-slate-900 outline-none placeholder:text-slate-400 font-sans"
          />
          <button
            type="button"
            onClick={submit}
            disabled={disabled || !value.trim()}
            aria-label="Send question"
            className="flex h-10 w-10 flex-none items-center justify-center rounded-xl bg-gradient-to-br from-amber-600 via-amber-700 to-slate-900 text-white shadow-sm transition-all duration-150 hover:shadow-md hover:brightness-105 active:scale-95 disabled:opacity-25 disabled:cursor-not-allowed"
          >
            <svg
              viewBox="0 0 20 20"
              className="h-4 w-4"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              aria-hidden
            >
              <path d="M10 16V4M4.5 9.5 10 4l5.5 5.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        </div>

        {/* Footer shortcuts & count */}
        <div className="mt-2 flex items-center justify-between px-2 text-[11px] text-slate-400">
          <span className="flex items-center gap-1.5">
            <kbd className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.2 font-mono text-[10px] text-slate-500">
              Enter
            </kbd>
            <span>to send</span>
            <span className="text-slate-300">·</span>
            <kbd className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.2 font-mono text-[10px] text-slate-500">
              Shift + Enter
            </kbd>
            <span>new line</span>
          </span>
          <span className="font-mono text-[10px]">
            {value.length > 0 && (
              <span className={value.length > MAX_LENGTH - 60 ? "text-amber-600 font-semibold" : "text-slate-400"}>
                {value.length}/{MAX_LENGTH}
              </span>
            )}
          </span>
        </div>
      </div>
    </div>
  );
}
