import { useCallback, useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Lock, Plus } from "lucide-react";
import { api, errMsg } from "../api";
import {
  Btn,
  Empty,
  ErrorBox,
  Loading,
  Notice,
  PageHeader,
  TABLE,
  TH,
} from "../components/ui";

export default function Roles() {
  const nav = useNavigate();
  const location = useLocation();
  const [roles, setRoles] = useState(null);
  const [catalog, setCatalog] = useState([]);
  const [err, setErr] = useState("");
  const [notice] = useState(location.state?.notice || null);
  const [del, setDel] = useState(null);
  const [moveTo, setMoveTo] = useState("");
  const [busy, setBusy] = useState(false);

  // Clear the router state so the notice doesn't reappear on refresh
  useEffect(() => {
    if (location.state?.notice) window.history.replaceState({}, "");
  }, [location.state]);

  const load = useCallback(() => {
    setErr("");
    return Promise.all([api.get("/roles/"), api.get("/permissions/")])
      .then(([r, p]) => {
        setRoles(r.data);
        setCatalog(p.data);
      })
      .catch((e) => setErr(errMsg(e)));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const label = Object.fromEntries(catalog.map((p) => [p.code, p.label]));
  const others = (roles || []).filter((r) => r.base !== "ADMIN" && r.id !== del?.id);

  const openDelete = (r) => {
    setMoveTo("");
    setDel(r);
  };

  const doDelete = async () => {
    if (del.user_count > 0 && !moveTo) return;
    setBusy(true);
    try {
      await api.delete(`/roles/${del.id}/`, {
        params: del.user_count > 0 ? { move_to: moveTo } : undefined,
      });
      setDel(null);
      await load();
    } catch (e) {
      setErr(errMsg(e));
      setDel(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader
        title="Roles & access"
        subtitle="Create roles and choose what each one is allowed to do. You can still make exceptions for individual people on their user page."
      >
        <Btn onClick={() => nav("/roles/new")}>
          <Plus size={16} /> Create role
        </Btn>
      </PageHeader>

      {notice && <Notice tone={notice.tone} msg={notice.msg} />}
      <ErrorBox msg={err} />
      {!roles && !err && <Loading />}
      {roles && roles.length === 0 && <Empty text="No roles yet." />}
      {roles && roles.length > 0 && (
        <div className={TABLE}>
          <table className="w-full text-sm">
            <thead className="border-b border-slate-100 bg-slate-50">
              <tr>
                <th className={TH}>Role</th>
                <th className={TH}>Permissions</th>
                <th className={TH}>Users</th>
                <th className={TH}></th>
              </tr>
            </thead>
            <tbody>
              {roles.map((r) => {
                const locked = r.base === "ADMIN";
                const shown = r.permissions.slice(0, 3);
                const more = r.permissions.length - shown.length;
                return (
                  <tr key={r.id} className="border-t border-slate-100 align-top">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2 font-medium text-navy-900">
                        {r.name}
                        {r.is_system && (
                          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-slate-500">
                            Built-in
                          </span>
                        )}
                      </div>
                      {r.description && (
                        <div className="mt-0.5 max-w-xs text-xs text-slate-500">
                          {r.description}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {locked ? (
                        <span className="text-xs text-slate-500">
                          Everything
                        </span>
                      ) : r.permissions.length === 0 ? (
                        <span className="text-xs text-slate-400">
                          No extra permissions
                        </span>
                      ) : (
                        <div className="flex max-w-md flex-wrap gap-1.5">
                          {shown.map((c) => (
                            <span
                              key={c}
                              className="rounded-full bg-brand-soft px-2.5 py-0.5 text-xs font-medium text-brand"
                            >
                              {label[c] || c}
                            </span>
                          ))}
                          {more > 0 && (
                            <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs text-slate-500">
                              +{more} more
                            </span>
                          )}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3 tabular-nums text-slate-600">
                      {r.user_count}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-right">
                      {locked ? (
                        <span className="inline-flex items-center gap-1 text-xs text-slate-400">
                          <Lock size={12} /> Protected
                        </span>
                      ) : (
                        <>
                          <Btn
                            variant="ghost"
                            className="h-8 px-3"
                            onClick={() => nav(`/roles/${r.id}/edit`)}
                          >
                            Edit
                          </Btn>
                          <Btn
                            variant="ghost"
                            className="h-8 px-3"
                            onClick={() => openDelete(r)}
                          >
                            Delete
                          </Btn>
                        </>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {del && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-navy-900/40 p-4">
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl">
            <h3 className="text-lg font-semibold text-navy-900">
              Delete "{del.name}"?
            </h3>
            {del.user_count > 0 ? (
              <>
                <p className="mt-2 text-sm text-slate-600">
                  {del.user_count} user{del.user_count === 1 ? " has" : "s have"}{" "}
                  this role. Choose the role they should be moved to.
                </p>
                <select
                  className="mt-4 h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm"
                  value={moveTo}
                  onChange={(e) => setMoveTo(e.target.value)}
                  autoFocus
                >
                  <option value="">Select a role…</option>
                  {others.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name}
                    </option>
                  ))}
                </select>
              </>
            ) : (
              <p className="mt-2 text-sm text-slate-600">
                No one has this role. It will be permanently removed.
              </p>
            )}
            <div className="mt-6 flex justify-end gap-3">
              <Btn
                variant="secondary"
                onClick={() => setDel(null)}
                disabled={busy}
              >
                Cancel
              </Btn>
              <Btn
                onClick={doDelete}
                disabled={busy || (del.user_count > 0 && !moveTo)}
              >
                {busy
                  ? "Deleting..."
                  : del.user_count > 0
                    ? "Move users & delete"
                    : "Delete role"}
              </Btn>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
