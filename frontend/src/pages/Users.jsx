import { useCallback, useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Plus, Search } from "lucide-react";
import { api, errMsg } from "../api";
import {
  Badge,
  Btn,
  Confirm,
  Empty,
  ErrorBox,
  Loading,
  Notice,
  PageHeader,
  Pager,
  TABLE,
  TH,
  inputCls,
} from "../components/ui";

export default function Users() {
  const nav = useNavigate();
  const location = useLocation();
  const [data, setData] = useState(null);
  const [q, setQ] = useState("");
  const [roleId, setRoleId] = useState("");
  const [roles, setRoles] = useState([]);
  const [page, setPage] = useState(1);
  const [err, setErr] = useState("");
  const [notice] = useState(location.state?.notice || null);
  const [toggle, setToggle] = useState(null);
  const [busy, setBusy] = useState(false);

  // Clear the router state so the notice doesn't reappear on refresh
  useEffect(() => {
    if (location.state?.notice) window.history.replaceState({}, "");
  }, [location.state]);

  const load = useCallback(() => {
    setErr("");
    return api
      .get("/users/", {
        params: { q: q || undefined, role_id: roleId || undefined, page },
      })
      .then((r) => setData(r.data))
      .catch((e) => setErr(errMsg(e)));
  }, [q, roleId, page]);

  useEffect(() => {
    api
      .get("/roles/")
      .then((r) => setRoles(r.data))
      .catch(() => {});
  }, []);

  useEffect(() => {
    const t = setTimeout(load, 250);
    return () => clearTimeout(t);
  }, [load]);

  const doToggle = async () => {
    setBusy(true);
    try {
      await api.patch(`/users/${toggle.id}/`, { is_active: !toggle.is_active });
      setToggle(null);
      await load();
    } catch (e) {
      setErr(errMsg(e));
      setToggle(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader
        title="Users"
        subtitle="Create accounts, assign roles and activate or deactivate access."
      >
        <Btn onClick={() => nav("/users/new")}>
          <Plus size={16} /> Create user
        </Btn>
      </PageHeader>

      <div className="flex flex-wrap gap-3">
        <div className="relative w-full sm:w-64">
          <Search
            size={16}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"
          />
          <input
            className={`${inputCls} pl-9`}
            placeholder="Search users"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(1);
            }}
          />
        </div>
        <select
          className={`${inputCls} w-auto`}
          value={roleId}
          onChange={(e) => {
            setRoleId(e.target.value);
            setPage(1);
          }}
        >
          <option value="">All roles</option>
          {roles.map((r) => (
            <option key={r.id} value={r.id}>
              {r.name}
            </option>
          ))}
        </select>
      </div>

      {notice && <Notice tone={notice.tone} msg={notice.msg} />}
      <ErrorBox msg={err} />
      {!data && !err && <Loading />}
      {data && data.results.length === 0 && <Empty text="No users found." />}
      {data && data.results.length > 0 && (
        <div className={TABLE}>
          <table className="w-full text-sm">
            <thead className="border-b border-slate-100 bg-slate-50">
              <tr>
                <th className={TH}>User</th>
                <th className={TH}>Email</th>
                <th className={TH}>Department</th>
                <th className={TH}>Role</th>
                <th className={TH}>Access</th>
                <th className={TH}>Status</th>
                <th className={TH}></th>
              </tr>
            </thead>
            <tbody>
              {data.results.map((u) => (
                <tr key={u.id} className="border-t border-slate-100">
                  <td className="px-4 py-3">
                    <div className="font-medium text-navy-900">{u.name}</div>
                    <div className="text-xs text-slate-500">@{u.username}</div>
                  </td>
                  <td className="px-4 py-3 text-slate-500">{u.email || "—"}</td>
                  <td className="px-4 py-3 text-slate-500">
                    {u.department || "—"}
                  </td>
                  <td className="px-4 py-3">
                    {u.role_name && u.role_name.toUpperCase() !== u.role ? (
                      <span className="inline-flex rounded-full bg-brand-soft px-2.5 py-0.5 text-xs font-medium text-brand">
                        {u.role_name}
                      </span>
                    ) : (
                      <Badge value={u.role} />
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {u.role === "ADMIN" ? (
                      <span className="text-xs text-slate-400">Full</span>
                    ) : (
                      <div className="flex items-center gap-1.5 text-xs text-slate-500">
                        {u.permissions.length} permission
                        {u.permissions.length === 1 ? "" : "s"}
                        {Object.keys(u.permission_overrides || {}).length >
                          0 && (
                          <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-700">
                            Custom
                          </span>
                        )}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <Badge value={u.is_active ? "ACTIVE" : "INACTIVE"} />
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-right">
                    {u.role === "ADMIN" ? (
                      <span className="text-xs text-slate-400">Protected</span>
                    ) : (
                      <>
                        <Btn
                          variant="ghost"
                          className="h-8 px-3"
                          onClick={() => nav(`/users/${u.id}/edit`)}
                        >
                          Edit
                        </Btn>
                        <Btn
                          variant="ghost"
                          className="h-8 px-3"
                          onClick={() => setToggle(u)}
                        >
                          {u.is_active ? "Deactivate" : "Activate"}
                        </Btn>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Pager data={data} page={page} setPage={setPage} noun="users" />

      {toggle && (
        <Confirm
          title={toggle.is_active ? "Deactivate account?" : "Activate account?"}
          text={
            toggle.is_active
              ? `${toggle.username} will no longer be able to sign in.`
              : `${toggle.username} will be able to sign in again.`
          }
          confirmLabel={toggle.is_active ? "Deactivate" : "Activate"}
          danger={toggle.is_active}
          busy={busy}
          onConfirm={doToggle}
          onClose={() => setToggle(null)}
        />
      )}
    </>
  );
}
