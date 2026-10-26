// Check what the signed-in user may do. Admins can do everything.
//   import { can } from "../access";
//   {can(user, "projects.manage") && <Btn>New project</Btn>}
// The server is still the real gatekeeper: also protect the API view with HasPerm("<code>").
export const can = (user, code) =>
  !!user && (user.role === "ADMIN" || (user.permissions || []).includes(code));
