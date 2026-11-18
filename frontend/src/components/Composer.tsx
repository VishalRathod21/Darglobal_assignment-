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
    <div className="border-t border-line bg-paper px-4 pb-4 pt-3">
      <div className="mx-auto max-w-3xl">
        <div className="flex items-end gap-2 rounded-2xl border border-line bg-white p-2 shadow-sm transition-colors focus-within:border-ink">
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
            placeholder="Ask about a project or a listing"
            aria-label="Your question"
            className="max-h-40 flex-1 resize-none bg-transparent px-2 py-1.5 text-[15px] leading-6 outline-none placeholder:text-stone-400"
          />
          <button
            type="button"
            onClick={submit}
            disabled={disabled || !value.trim()}
            aria-label="Send question"
            className="flex h-9 w-9 flex-none items-center justify-center rounded-xl bg-ink text-white transition-opacity disabled:opacity-25"
          >
            <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
              <path d="M10 16V4M4.5 9.5 10 4l5.5 5.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        </div>
        <div className="mt-1.5 flex justify-between px-1 text-[11px] text-stone-400">
          <span>Enter to send · Shift + Enter for a new line</span>
          {value.length > MAX_LENGTH - 100 && <span>{value.length}/{MAX_LENGTH}</span>}
        </div>
      </div>
    </div>
  );
}
