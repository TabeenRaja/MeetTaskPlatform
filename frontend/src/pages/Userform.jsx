import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, errMsg } from "../api";
import {
  Btn,
  Card,
  ErrorBox,
  Loading,
  PageHeader,
  inputCls,
} from "../components/ui";
import { DEPARTMENTS, OTHER, PHONE_LENGTH, cleanPhone } from "../constants";

const L = ({ children, required }) => (
  <label className="mb-1 block text-sm font-medium text-slate-700">
    {children}
    {required && <span className="ml-0.5 text-red-500">*</span>}
  </label>
);

const empty = {
  username: "",
  first_name: "",
  last_name: "",
  email: "",
  phone: "",
  role_id: "",
  base: "", // access level of the user being edited (EMPLOYEE or MANAGER)
  department: "",
  department_other: "",
  is_active: true,
};

export default function UserForm() {
  const { id } = useParams();
  const edit = !!id;
  const nav = useNavigate();
  const [f, setF] = useState(empty);
  const [roles, setRoles] = useState([]);
  const [catalog, setCatalog] = useState([]);
  // Per-person exceptions to the role: { code: true | false }. Empty = exactly what the role gives.
  const [overrides, setOverrides] = useState({});
  const [preview, setPreview] = useState("");
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const calls = [api.get("/roles/", { params: { assignable: 1 } })];
    if (edit) calls.push(api.get(`/users/${id}/`), api.get("/permissions/"));
    Promise.all(calls)
      .then(([r, uu, pc]) => {
        setRoles(r.data);
        if (pc) setCatalog(pc.data);
        if (uu) {
          const u = uu.data;
          if (u.role === "ADMIN") {
            nav("/users", { replace: true });
            return;
          }
          const listed = !u.department || DEPARTMENTS.includes(u.department);
          setF({
            username: u.username,
            first_name: u.first_name || "",
            last_name: u.last_name || "",
            email: u.email || "",
            phone: u.phone || "",
            role_id: u.role_id,
            base: u.role,
            department: listed ? u.department || "" : OTHER,
            department_other: listed ? "" : u.department,
            is_active: u.is_active,
          });
          setOverrides(u.permission_overrides || {});
        } else {
          // new user: start on the first employee-level role
          const def = r.data.find((x) => x.base === "EMPLOYEE") || r.data[0];
          if (def) setF((prev) => ({ ...prev, role_id: def.id }));
        }
      })
      .catch((e) => setErr(errMsg(e)))
      .finally(() => setLoading(false));
  }, [id, edit, nav]);

  // Live username preview while creating (the server generates the final one)
  useEffect(() => {
    if (edit) return;
    if (!f.first_name.trim() || !f.last_name.trim()) {
      setPreview("");
      return;
    }
    const t = setTimeout(() => {
      api
        .get("/users/next-username/", {
          params: { first_name: f.first_name, last_name: f.last_name },
        })
        .then((r) => setPreview(r.data.username || ""))
        .catch(() => setPreview(""));
    }, 300);
    return () => clearTimeout(t);
  }, [edit, f.first_name, f.last_name]);

  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  // What the chosen role gives, and what this person ends up with after their exceptions
  const rolePerms = useMemo(
    () => roles.find((r) => r.id === Number(f.role_id))?.permissions || [],
    [roles, f.role_id],
  );
  const roleHas = (code) => rolePerms.includes(code);
  const allowed = (code) =>
    code in overrides ? overrides[code] : roleHas(code);
  const setAllowed = (code, on) => {
    const next = { ...overrides };
    if (on === roleHas(code))
      delete next[code]; // same as the role, so no exception needed
    else next[code] = on;
    setOverrides(next);
  };
  const groups = useMemo(() => {
    const out = {};
    catalog.forEach((p) => (out[p.group] ||= []).push(p));
    return Object.entries(out);
  }, [catalog]);
  const customCount = Object.keys(overrides).filter(
    (c) => overrides[c] !== roleHas(c),
  ).length;
  const department =
    f.department === OTHER ? f.department_other.trim() : f.department;

  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    if (!f.first_name.trim() || !f.last_name.trim())
      return setErr("First and last name are required.");
    if (!f.email.trim())
      return setErr(
        "Work email is required. The login details are sent there.",
      );
    if (f.phone && f.phone.length !== PHONE_LENGTH)
      return setErr(`Phone number must be exactly ${PHONE_LENGTH} digits.`);
    if (!department) return setErr("Please select a department.");
    if (!f.role_id) return setErr("Please select a role.");

    const body = {
      first_name: f.first_name.trim(),
      last_name: f.last_name.trim(),
      email: f.email.trim(),
      phone: f.phone,
      department,
      role_id: Number(f.role_id),
    };

    setBusy(true);
    try {
      if (edit) {
        // keep only real exceptions (ones that differ from the role)
        const exceptions = Object.fromEntries(
          Object.entries(overrides).filter(([c, v]) => v !== roleHas(c)),
        );
        await api.patch(`/users/${id}/`, {
          ...body,
          is_active: f.is_active,
          permission_overrides: exceptions,
        });
        nav("/users", { state: { notice: { msg: "User updated." } } });
      } else {
        const { data } = await api.post("/users/", body);
        nav("/users", {
          state: {
            notice: data.email_sent
              ? {
                  msg: `User created with username "${data.username}". Login details were emailed to ${data.email}.`,
                }
              : {
                  tone: "amber",
                  msg: `User created with username "${data.username}", but the email could not be sent to ${data.email}. Once email is working, the user can use "Forgot password?" on the sign-in page to get access.`,
                },
          },
        });
      }
    } catch (ex) {
      setErr(errMsg(ex));
      setBusy(false);
    }
  };

  if (loading) return <Loading />;

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <Link to="/users" className="text-sm text-brand hover:underline">
        ← Back to users
      </Link>
      <PageHeader
        title={edit ? "Edit user" : "Create new user"}
        subtitle={
          edit
            ? `Update details for @${f.username}.`
            : "Fill in the details below to create an account."
        }
      />

      <form onSubmit={submit} className="space-y-6">
        <ErrorBox msg={err} />

        <Card title="Personal details">
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <L required>First name</L>
              <input
                className={inputCls}
                value={f.first_name}
                onChange={set("first_name")}
              />
            </div>
            <div>
              <L required>Last name</L>
              <input
                className={inputCls}
                value={f.last_name}
                onChange={set("last_name")}
              />
            </div>
            <div>
              <L required>Work email</L>
              <input
                type="email"
                className={inputCls}
                value={f.email}
                onChange={set("email")}
                placeholder="name@company.com"
              />
            </div>
            <div>
              <L>Phone</L>
              <input
                type="tel"
                inputMode="numeric"
                className={inputCls}
                value={f.phone}
                onChange={(e) =>
                  setF({ ...f, phone: cleanPhone(e.target.value) })
                }
                maxLength={PHONE_LENGTH}
                placeholder="03001234567"
              />
              <p className="mt-1 text-xs text-slate-400">
                Digits only · {f.phone.length}/{PHONE_LENGTH}
              </p>
            </div>
          </div>
        </Card>

        <Card title="Work details">
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <L required>Department</L>
              <select
                className={inputCls}
                value={f.department}
                onChange={set("department")}
              >
                <option value="">Select department…</option>
                {DEPARTMENTS.map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
                <option value={OTHER}>Other…</option>
              </select>
            </div>
            <div>
              <L required>Role</L>
              <select
                className={inputCls}
                value={f.role_id}
                onChange={(e) =>
                  setF({ ...f, role_id: Number(e.target.value) })
                }
              >
                {roles
                  .filter((r) => !edit || !f.base || r.base === f.base)
                  .map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name}
                    </option>
                  ))}
              </select>
              <p className="mt-1 text-xs text-slate-400">
                <Link to="/roles" className="text-brand hover:underline">
                  Manage roles
                </Link>{" "}
                to add new ones.
              </p>
            </div>
            {f.department === OTHER && (
              <div className="sm:col-span-2">
                <L required>Department name</L>
                <input
                  className={inputCls}
                  value={f.department_other}
                  onChange={set("department_other")}
                  placeholder="Enter department"
                />
              </div>
            )}
          </div>
        </Card>

        <Card title="Account">
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <L>Username</L>
              <input
                className={`${inputCls} bg-slate-50 font-mono`}
                value={edit ? f.username : preview}
                placeholder={edit ? "" : "Appears once you enter the name"}
                disabled
                readOnly
              />
            </div>
            {edit && (
              <label className="flex items-center gap-2 self-end pb-2 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={f.is_active}
                  onChange={(e) => setF({ ...f, is_active: e.target.checked })}
                />
                Account active
              </label>
            )}
          </div>
        </Card>

        {edit && (
          <Card
            title="Permissions"
            action={
              customCount > 0 && (
                <button
                  type="button"
                  onClick={() => setOverrides({})}
                  className="text-xs font-medium text-brand hover:underline"
                >
                  Reset to role defaults
                </button>
              )
            }
          >
            <p className="mb-4 text-xs text-slate-500">
              Ticked items are what this person can do. They start from the
              selected role; change a box to make an exception for this person
              only. The role itself is not affected.
            </p>
            <div className="space-y-5">
              {groups.map(([group, items]) => (
                <div key={group}>
                  <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
                    {group}
                  </div>
                  <div className="space-y-3">
                    {items.map((p) => {
                      const on = allowed(p.code);
                      const custom = on !== roleHas(p.code);
                      return (
                        <label
                          key={p.code}
                          className="flex cursor-pointer items-start gap-3 text-sm text-slate-700"
                        >
                          <input
                            type="checkbox"
                            className="mt-0.5"
                            checked={on}
                            onChange={(e) =>
                              setAllowed(p.code, e.target.checked)
                            }
                          />
                          <span>
                            <span className="font-medium">
                              {p.label}
                              {custom && (
                                <span className="ml-2 rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-700">
                                  {on
                                    ? "Extra for this person"
                                    : "Removed for this person"}
                                </span>
                              )}
                            </span>
                            <span className="mt-0.5 block text-xs text-slate-500">
                              {p.description}
                            </span>
                          </span>
                        </label>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          </Card>
        )}

        <div className="flex justify-end gap-3">
          <Btn
            variant="secondary"
            type="button"
            onClick={() => nav("/users")}
            disabled={busy}
          >
            Cancel
          </Btn>
          <Btn type="submit" disabled={busy}>
            {busy
              ? "Saving..."
              : edit
                ? "Save changes"
                : "Create user & send login"}
          </Btn>
        </div>
      </form>
    </div>
  );
}
