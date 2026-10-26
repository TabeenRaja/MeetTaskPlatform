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

const L = ({ children, required }) => (
  <label className="mb-1 block text-sm font-medium text-slate-700">
    {children}
    {required && <span className="ml-0.5 text-red-500">*</span>}
  </label>
);

export default function RoleForm() {
  const { id } = useParams();
  const edit = !!id;
  const nav = useNavigate();
  const [f, setF] = useState({
    name: "",
    description: "",
    permissions: [],
  });
  const [catalog, setCatalog] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const calls = [api.get("/permissions/")];
    if (edit) calls.push(api.get(`/roles/${id}/`));
    Promise.all(calls)
      .then(([p, r]) => {
        setCatalog(p.data);
        if (r) {
          if (r.data.base === "ADMIN") {
            nav("/roles", { replace: true });
            return;
          }
          setF({
            name: r.data.name,
            description: r.data.description || "",
            permissions: r.data.permissions,
          });
        }
      })
      .catch((e) => setErr(errMsg(e)))
      .finally(() => setLoading(false));
  }, [id, edit, nav]);

  const groups = useMemo(() => {
    const out = {};
    catalog.forEach((p) => (out[p.group] ||= []).push(p));
    return Object.entries(out);
  }, [catalog]);

  const has = (code) => f.permissions.includes(code);
  const toggle = (code) =>
    setF({
      ...f,
      permissions: has(code)
        ? f.permissions.filter((c) => c !== code)
        : [...f.permissions, code],
    });
  const toggleGroup = (items) => {
    const codes = items.map((p) => p.code);
    const all = codes.every(has);
    setF({
      ...f,
      permissions: all
        ? f.permissions.filter((c) => !codes.includes(c))
        : [...new Set([...f.permissions, ...codes])],
    });
  };

  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    if (!f.name.trim()) return setErr("Give the role a name.");
    setBusy(true);
    try {
      const body = {
        name: f.name.trim(),
        description: f.description.trim(),
        permissions: f.permissions,
      };
      if (edit) await api.patch(`/roles/${id}/`, body);
      else await api.post("/roles/", body);
      nav("/roles", {
        state: { notice: { msg: edit ? "Role updated." : "Role created." } },
      });
    } catch (ex) {
      setErr(errMsg(ex));
      setBusy(false);
    }
  };

  if (loading) return <Loading />;

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <Link to="/roles" className="text-sm text-brand hover:underline">
        ← Back to roles
      </Link>
      <PageHeader
        title={edit ? `Edit role: ${f.name}` : "Create role"}
        subtitle="Name the role, then choose what everyone with this role can do. To make an exception for one person, edit that user."
      />

      <form onSubmit={submit} className="space-y-6">
        <ErrorBox msg={err} />

        <Card title="Role details">
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <L required>Role name</L>
              <input
                className={inputCls}
                value={f.name}
                onChange={(e) => setF({ ...f, name: e.target.value })}
                placeholder="e.g. Senior manager, CEO, Student"
                maxLength={60}
                autoFocus={!edit}
              />
            </div>
            <div>
              <L>Description</L>
              <input
                className={inputCls}
                value={f.description}
                onChange={(e) => setF({ ...f, description: e.target.value })}
                placeholder="What is this role for?"
                maxLength={255}
              />
            </div>
          </div>
          <p className="mt-3 text-xs text-slate-400">
            The workspace follows the permissions: a role with review, task
            assignment, project or analytics permissions gets the manager
            screens; any other role gets the employee screens. Each person's
            dashboard shows only what their permissions allow.
          </p>
        </Card>

        {groups.map(([group, items]) => {
          const all = items.every((p) => has(p.code));
          return (
            <Card
              key={group}
              title={group}
              action={
                <button
                  type="button"
                  onClick={() => toggleGroup(items)}
                  className="text-xs font-medium text-brand hover:underline"
                >
                  {all ? "Clear all" : "Select all"}
                </button>
              }
            >
              <div className="space-y-5">
                {items.map((p) => (
                  <div key={p.code}>
                    <label className="flex cursor-pointer items-start gap-3 text-sm text-slate-700">
                      <input
                        type="checkbox"
                        className="mt-0.5"
                        checked={has(p.code)}
                        onChange={() => toggle(p.code)}
                      />
                      <span>
                        <span className="font-medium">
                          {p.label}
                          <span className="ml-2 font-normal text-slate-400">
                            {has(p.code)
                              ? "· everyone with this role"
                              : "· not allowed for this role"}
                          </span>
                        </span>
                        <span className="mt-0.5 block text-xs text-slate-500">
                          {p.description}
                        </span>
                      </span>
                    </label>
                  </div>
                ))}
              </div>
            </Card>
          );
        })}

        <div className="flex justify-end gap-3">
          <Btn
            variant="secondary"
            type="button"
            onClick={() => nav("/roles")}
            disabled={busy}
          >
            Cancel
          </Btn>
          <Btn type="submit" disabled={busy}>
            {busy ? "Saving..." : edit ? "Save changes" : "Create role"}
          </Btn>
        </div>
      </form>
    </div>
  );
}
