import { useEffect, useState } from "react";
import { Search } from "lucide-react";
import { api, errMsg } from "../api";
import {
  Empty,
  ErrorBox,
  Loading,
  PageHeader,
  Pager,
  TABLE,
  TH,
  inputCls,
} from "../components/ui";
import { fmtDateTime } from "../utils";

const processingActions = new Set([
  "AUDIO_TRANSCRIBED",
  "TRANSCRIPT_NORMALIZED",
  "TASKS_EXTRACTED",
]);

function actionLabel(action) {
  const label = (action || "").replaceAll("_", " ").toLowerCase();
  return label ? label.charAt(0).toUpperCase() + label.slice(1) : "—";
}

export default function Audit() {
  const [data, setData] = useState(null);
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    setData(null);
    setErr("");
    api
      .get("/audit/", { params: { page } })
      .then((r) => setData(r.data))
      .catch((e) => setErr(errMsg(e)));
  }, [page]);

  const query = q.trim().toLowerCase();
  const userEvents = (data?.results ?? []).filter((event) => {
    const actor = (event.actor_name ?? "").trim().toLowerCase();
    return (
      actor &&
      actor !== "system" &&
      !processingActions.has((event.action ?? "").toUpperCase())
    );
  });

  const rows = userEvents.filter((event) =>
    [
      event.actor_name,
      actionLabel(event.action),
      event.action,
      event.target_type,
      event.target_id,
    ]
      .join(" ")
      .toLowerCase()
      .includes(query),
  );

  return (
    <>
      <PageHeader title="Audit logs" />

      <div className="relative w-full sm:w-72">
        <Search
          size={16}
          aria-hidden="true"
          className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"
        />
        <input
          className={`${inputCls} pl-9`}
          aria-label="Filter user activity on this page"
          placeholder="Filter this page"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>

      <ErrorBox msg={err} />

      {!data && !err && <Loading />}

      {data && rows.length === 0 && (
        <Empty
          text={
            userEvents.length > 0
              ? "No user actions match your search on this page."
              : "No user actions on this page."
          }
        />
      )}

      {rows.length > 0 && (
        <div className={TABLE}>
          <table className="w-full text-sm">
            <thead className="border-b border-slate-100 bg-slate-50">
              <tr>
                <th scope="col" className={TH}>When</th>
                <th scope="col" className={TH}>Who</th>
                <th scope="col" className={TH}>Action</th>
                <th scope="col" className={TH}>Target</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((event) => (
                <tr key={event.id} className="border-t border-slate-100">
                  <td className="whitespace-nowrap px-4 py-3 text-slate-500">
                    {fmtDateTime(event.created_at)}
                  </td>
                  <td className="px-4 py-3">{event.actor_name}</td>
                  <td className="px-4 py-3 font-medium text-navy-900">
                    {actionLabel(event.action)}
                  </td>
                  <td className="px-4 py-3 text-slate-500">
                    {[event.target_type, event.target_id]
                      .filter((value) => value != null && value !== "")
                      .join(" ") || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Pager data={data} page={page} setPage={setPage} noun="events" />
    </>
  );
}
