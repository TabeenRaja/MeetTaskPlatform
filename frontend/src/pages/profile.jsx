import { useState } from "react";
import { Check, LogOut, Pencil, X } from "lucide-react";
import { api, errMsg } from "../api";
import { useAuth } from "../auth";
import {
  Avatar,
  Badge,
  Btn,
  Card,
  ErrorBox,
  Notice,
  PageHeader,
  inputCls,
} from "../components/ui";
import { DEPARTMENTS, OTHER, PHONE_LENGTH, cleanPhone } from "../constants";
import { PasswordChecklist, passwordError } from "../passwordRules";
import { fmtDate } from "../utils";



const L = ({ children }) => (
  <label className="mb-1 block text-sm font-medium text-slate-700">
    {children}
  </label>
);

// A read-only row (cannot be changed by the user)
function Row({ label, children }) {
  return (
    <div className="flex items-center justify-between gap-4 py-3 text-sm">
      <span className="text-slate-500">{label}</span>
      <span className="text-right text-slate-800">{children}</span>
    </div>
  );
}

// A row with a pencil icon: click it to edit just this field, then save with the tick
function EditableRow({ label, field, user, kind = "text" }) {
  const current = user[field] || "";
  const listed = !current || DEPARTMENTS.includes(current);
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(
    kind === "department" ? (listed ? current : OTHER) : current,
  );
  const [other, setOther] = useState(
    kind === "department" && !listed ? current : "",
  );
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const cancel = () => {
    setEditing(false);
    setErr("");
    setVal(kind === "department" ? (listed ? current : OTHER) : current);
    setOther(kind === "department" && !listed ? current : "");
  };

  const save = async () => {
    setErr("");
    const v =
      kind === "department" ? (val === OTHER ? other.trim() : val) : val.trim();
    if ((field === "first_name" || field === "last_name") && !v)
      return setErr("This field is required.");
    if (kind === "department" && !v)
      return setErr("Please select a department.");
    if (kind === "phone" && v && v.length !== PHONE_LENGTH)
      return setErr(`Phone number must be exactly ${PHONE_LENGTH} digits.`);
    if (v === current) return cancel();
    setBusy(true);
    try {
      await api.patch("/auth/me/", { [field]: v });
      // Reload so the whole app (header, greeting, etc.) shows the saved details
      window.location.reload();
    } catch (ex) {
      setErr(errMsg(ex));
      setBusy(false);
    }
  };

  const onKey = (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      save();
    }
    if (e.key === "Escape") cancel();
  };

  return (
    <div className="py-3 text-sm">
      <div className="flex items-center justify-between gap-4">
        <span className="w-28 shrink-0 text-slate-500">{label}</span>

        {editing ? (
          <div className="flex min-w-0 flex-1 items-center justify-end gap-2">
            <div className="flex w-full max-w-xs flex-col gap-2">
              {kind === "department" ? (
                <>
                  <select
                    className={inputCls}
                    value={val}
                    onChange={(e) => setVal(e.target.value)}
                    autoFocus
                  >
                    <option value="">Select department…</option>
                    {DEPARTMENTS.map((d) => (
                      <option key={d} value={d}>
                        {d}
                      </option>
                    ))}
                    <option value={OTHER}>Other…</option>
                  </select>
                  {val === OTHER && (
                    <input
                      className={inputCls}
                      value={other}
                      onChange={(e) => setOther(e.target.value)}
                      onKeyDown={onKey}
                      placeholder="Enter department"
                    />
                  )}
                </>
              ) : kind === "phone" ? (
                <input
                  className={inputCls}
                  type="tel"
                  inputMode="numeric"
                  value={val}
                  maxLength={PHONE_LENGTH}
                  onChange={(e) => setVal(cleanPhone(e.target.value))}
                  onKeyDown={onKey}
                  placeholder="03001234567"
                  autoFocus
                />
              ) : (
                <input
                  className={inputCls}
                  value={val}
                  onChange={(e) => setVal(e.target.value)}
                  onKeyDown={onKey}
                  autoFocus
                />
              )}
            </div>
            <button
              type="button"
              onClick={save}
              disabled={busy}
              title="Save"
              className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-brand text-white transition hover:bg-brand-dark disabled:opacity-60"
            >
              <Check size={16} />
            </button>
            <button
              type="button"
              onClick={cancel}
              disabled={busy}
              title="Cancel"
              className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-slate-200 text-slate-500 transition hover:bg-slate-50"
            >
              <X size={16} />
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-2 text-right text-slate-800">
            <span>{current || "—"}</span>
            <button
              type="button"
              onClick={() => setEditing(true)}
              title={`Edit ${label.toLowerCase()}`}
              aria-label={`Edit ${label.toLowerCase()}`}
              className="grid h-7 w-7 place-items-center rounded-md text-slate-400 transition hover:bg-brand/10 hover:text-brand"
            >
              <Pencil size={14} />
            </button>
          </div>
        )}
      </div>
      {err && <p className="mt-1 text-right text-xs text-red-600">{err}</p>}
    </div>
  );
}

function ChangePasswordCard() {
  const [f, setF] = useState({ current: "", next: "", confirm: "" });
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    setOk("");
    const pe = passwordError(f.next);
    if (pe) return setErr(pe);
    if (f.next !== f.confirm) return setErr("New passwords do not match.");
    if (f.next === f.current)
      return setErr("New password must be different from the current one.");
    setBusy(true);
    try {
      await api.post("/auth/change-password/", {
        current_password: f.current,
        new_password: f.next,
      });
      setF({ current: "", next: "", confirm: "" });
      setOk(
        "Password updated. Use your new password the next time you sign in.",
      );
    } catch (ex) {
      setErr(errMsg(ex));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Change password">
      <form onSubmit={submit} className="space-y-4">
        <ErrorBox msg={err} />
        <Notice msg={ok} />
        <div>
          <L>Current password</L>
          <input
            type="password"
            className={inputCls}
            value={f.current}
            onChange={set("current")}
            autoComplete="current-password"
            required
          />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <L>New password</L>
            <input
              type="password"
              className={inputCls}
              value={f.next}
              onChange={set("next")}
              autoComplete="new-password"
              required
            />
          </div>
          <div>
            <L>Confirm new password</L>
            <input
              type="password"
              className={inputCls}
              value={f.confirm}
              onChange={set("confirm")}
              autoComplete="new-password"
              required
            />
          </div>
        </div>
        <PasswordChecklist value={f.next} />
        <Btn type="submit" disabled={busy}>
          {busy ? "Saving..." : "Update password"}
        </Btn>
      </form>
    </Card>
  );
}

export default function Profile() {
  const { user, logout } = useAuth();

  return (
    <div className="mx-auto w-full max-w-6xl space-y-5">
      <PageHeader title="Profile" />

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex min-w-0 items-center gap-4">
            <div className="shrink-0">
              <Avatar name={user.name} size={52} />
            </div>
            <div className="min-w-0">
              <h2 className="break-words text-lg font-semibold text-navy-900">
                {user.name}
              </h2>
              <p className="break-all text-sm text-slate-500">
                @{user.username}
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Badge value={user.role} />
            <Badge value={user.is_active ? "ACTIVE" : "INACTIVE"} />
          </div>
        </div>
      </Card>

      <div className="grid items-start gap-5 xl:grid-cols-2">
        <Card title="Account details">
          <div className="divide-y divide-slate-100">
            <EditableRow label="First name" field="first_name" user={user} />
            <EditableRow label="Last name" field="last_name" user={user} />
            <Row label="Email">
              <span className="break-all">{user.email || "—"}</span>
            </Row>
            <EditableRow
              label="Phone"
              field="phone"
              user={user}
              kind="phone"
            />
            <EditableRow
              label="Department"
              field="department"
              user={user}
              kind="department"
            />
            <Row label="Member since">{fmtDate(user.date_joined)}</Row>
          </div>
        </Card>

        <ChangePasswordCard />
      </div>

      <div className="flex justify-end">
        <Btn variant="secondary" onClick={logout}>
          <LogOut size={16} aria-hidden="true" /> Log out
        </Btn>
      </div>
    </div>
  );
}
