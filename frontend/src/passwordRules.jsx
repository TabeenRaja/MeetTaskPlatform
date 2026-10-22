import { Check, Circle } from "lucide-react";

export const RULES = [
  ["At least 8 characters", (p) => p.length >= 8],
  ["One uppercase letter (A-Z)", (p) => /[A-Z]/.test(p)],
  ["One lowercase letter (a-z)", (p) => /[a-z]/.test(p)],
  ["One number (0-9)", (p) => /\d/.test(p)],
  ["One special character (! @ # $ % ...)", (p) => /[^A-Za-z0-9]/.test(p)],
];

// Returns '' when the password is strong enough, otherwise a message for the first missing rule
export function passwordError(p) {
  const bad = RULES.find(([, test]) => !test(p));
  return bad ? `Password needs: ${bad[0].toLowerCase()}.` : "";
}

export function PasswordChecklist({ value }) {
  return (
    <ul className="mt-2 grid gap-1 text-xs sm:grid-cols-2">
      {RULES.map(([label, test]) => {
        const ok = test(value || "");
        return (
          <li
            key={label}
            className={`flex items-center gap-1.5 ${ok ? "text-emerald-600" : "text-slate-400"}`}
          >
            {ok ? <Check size={13} /> : <Circle size={11} />}
            {label}
          </li>
        );
      })}
    </ul>
  );
}
