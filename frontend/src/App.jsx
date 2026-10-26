import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import { AuthProvider, useAuth } from "./auth";
import { can } from "./access";
import Layout from "./components/Layout";
import { Loading } from "./components/ui";
import Analytics from "./pages/Analytics";
import Audit from "./pages/Audit";
import Dashboard from "./pages/Dashboard";
import Login from "./pages/Login";
import MeetingDetail from "./pages/MeetingDetail";
import MeetingNew from "./pages/MeetingNew";
import Meetings from "./pages/Meetings";
import Notifications from "./pages/Notifications";
import Planner from "./pages/Planner";
import Profile from "./pages/profile";
import ProjectDetail from "./pages/ProjectDetail";
import Projects from "./pages/Projects";
import Review from "./pages/Review";
import TaskDetail from "./pages/TaskDetail";
import Tasks from "./pages/Tasks";
import Users from "./pages/Users";
import UserForm from "./pages/Userform";
import Roles from "./pages/Roles";
import RoleForm from "./pages/RoleForm";
import ChangePassword from "./pages/Changepassword";
import ForgotPassword from "./pages/ForgotPassword";
import ResetPassword from "./pages/ResetPassword";

function Guard({ children }) {
  const { user, loading } = useAuth();
  const loc = useLocation();
  if (loading) return <Loading />;
  if (!user) return <Navigate to="/login" replace />;
  // Users with a temporary password must set a new one before using the app
  if (user.must_change_password && loc.pathname !== "/change-password") {
    return <Navigate to="/change-password" replace />;
  }
  return children;
}

// UX only. The backend enforces the real permissions.
// `perm` (optional): also require this permission, so an admin can allow or block a single
// action for a role or a person (e.g. an employee who may create meetings).
function Role({ allow, perm, children }) {
  const { user } = useAuth();
  const ok = perm
    ? user.role !== "ADMIN" && can(user, perm)
    : allow.includes(user.role);
  return ok ? children : <Navigate to="/" replace />;
}

const WORK = ["MANAGER", "EMPLOYEE"];

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/forgot-password" element={<ForgotPassword />} />
          <Route
            path="/reset-password/:uid/:token"
            element={<ResetPassword />}
          />

          {/* Full-screen page (no sidebar), but still requires sign-in */}
          <Route
            path="/change-password"
            element={
              <Guard>
                <ChangePassword />
              </Guard>
            }
          />

          <Route
            element={
              <Guard>
                <Layout />
              </Guard>
            }
          >
            <Route index element={<Dashboard />} />
            <Route
              path="meetings"
              element={
                <Role allow={WORK}>
                  <Meetings />
                </Role>
              }
            />
            <Route
              path="meetings/new"
              element={
                <Role allow={["MANAGER"]} perm="meetings.create">
                  <MeetingNew />
                </Role>
              }
            />
            <Route
              path="meetings/:id"
              element={
                <Role allow={WORK}>
                  <MeetingDetail />
                </Role>
              }
            />
            <Route
              path="meetings/:id/review"
              element={
                <Role allow={["MANAGER"]} perm="meetings.review">
                  <Review />
                </Role>
              }
            />
            <Route
              path="tasks"
              element={
                <Role allow={WORK}>
                  <Tasks />
                </Role>
              }
            />
            <Route
              path="tasks/:id"
              element={
                <Role allow={WORK}>
                  <TaskDetail />
                </Role>
              }
            />
            <Route
              path="projects"
              element={
                <Role allow={["MANAGER"]} perm="projects.manage">
                  <Projects />
                </Role>
              }
            />
            <Route
              path="projects/:id"
              element={
                <Role allow={["MANAGER"]} perm="projects.manage">
                  <ProjectDetail />
                </Role>
              }
            />
            <Route
              path="planner"
              element={
                <Role allow={WORK}>
                  <Planner />
                </Role>
              }
            />
            <Route
              path="analytics"
              element={
                <Role allow={["MANAGER"]} perm="analytics.view">
                  <Analytics />
                </Role>
              }
            />
            <Route path="notifications" element={<Notifications />} />
            <Route path="profile" element={<Profile />} />
            <Route
              path="users"
              element={
                <Role allow={["ADMIN"]}>
                  <Users />
                </Role>
              }
            />
            <Route
              path="users/new"
              element={
                <Role allow={["ADMIN"]}>
                  <UserForm />
                </Role>
              }
            />
            <Route
              path="users/:id/edit"
              element={
                <Role allow={["ADMIN"]}>
                  <UserForm />
                </Role>
              }
            />
            <Route
              path="roles"
              element={
                <Role allow={["ADMIN"]}>
                  <Roles />
                </Role>
              }
            />
            <Route
              path="roles/new"
              element={
                <Role allow={["ADMIN"]}>
                  <RoleForm />
                </Role>
              }
            />
            <Route
              path="roles/:id/edit"
              element={
                <Role allow={["ADMIN"]}>
                  <RoleForm />
                </Role>
              }
            />
            <Route
              path="audit"
              element={
                <Role allow={["ADMIN"]}>
                  <Audit />
                </Role>
              }
            />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
