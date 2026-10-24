import { reactive } from "vue";
import {
  ApiError,
  clearSession,
  post,
  request,
  setSession,
  token,
} from "./api";

export interface Course {
  id: string;
  name: string;
  term: string;
  role: "TEACHER" | "STUDENT";
}
export interface User {
  id: string;
  login_name: string;
  full_name: string;
  must_change_password?: boolean;
}
export interface SessionInfo {
  user: User;
  must_change_password: boolean;
  server_time: string;
  expires_at: string;
  absolute_expires_at: string;
}

const USER_KEY = "algoclass.user";
const COURSE_PREFIX = "algoclass.course.";

function storedUser(): User | null {
  try {
    return JSON.parse(sessionStorage.getItem(USER_KEY) || "null");
  } catch {
    return null;
  }
}
function courseKey(userId: string) {
  return `${COURSE_PREFIX}${userId}`;
}

export const session = reactive({
  user: storedUser() as User | null,
  courses: [] as Course[],
  courseId: "" as string,
  mustChangePassword: false,
  expiresAt: "" as string,
  absoluteExpiresAt: "" as string,
  serverTime: "" as string,
  ready: false,
  coursesLoaded: false,
});

export function currentCourse(): Course | undefined {
  return session.courses.find((course) => course.id === session.courseId);
}

function applySession(info: SessionInfo) {
  session.user = info.user;
  session.mustChangePassword = info.must_change_password;
  session.expiresAt = info.expires_at;
  session.absoluteExpiresAt = info.absolute_expires_at;
  session.serverTime = info.server_time;
  sessionStorage.setItem(USER_KEY, JSON.stringify(info.user));
  // Course context is scoped per account: a new login never inherits the previous one.
  if (!info.must_change_password) {
    const remembered = sessionStorage.getItem(courseKey(info.user.id)) || "";
    session.courseId = remembered;
  } else {
    session.courseId = "";
    session.courses = [];
  }
}

export async function loadSession() {
  const info = await request<SessionInfo>("/auth/session");
  applySession(info);
  return info;
}

export async function loadCourses() {
  const result = await request<{ items: Course[] }>("/courses");
  session.courses = result.items;
  if (!result.items.some((course) => course.id === session.courseId)) {
    session.courseId = "";
  }
  session.ready = true;
  session.coursesLoaded = true;
  return result.items;
}

export function selectCourse(id: string) {
  session.courseId = id;
  if (session.user) sessionStorage.setItem(courseKey(session.user.id), id);
}

export function clearCourse() {
  session.courseId = "";
  if (session.user) sessionStorage.removeItem(courseKey(session.user.id));
}

export async function login(login_name: string, password: string) {
  const data = await post<{
    access_token: string;
    user: User;
    must_change_password: boolean;
    expires_at: string;
    absolute_expires_at: string;
    server_time: string;
  }>("/auth/login", { login_name, password });
  setSession(data.access_token, data.user);
  applySession({
    user: data.user,
    must_change_password: data.must_change_password,
    server_time: data.server_time,
    expires_at: data.expires_at,
    absolute_expires_at: data.absolute_expires_at,
  });
  return data;
}

export async function changePassword(
  current_password: string,
  new_password: string,
) {
  const data = await post<{
    access_token: string;
    user: User;
    must_change_password: boolean;
    expires_at: string;
    absolute_expires_at: string;
    server_time: string;
  }>("/auth/change-password", { current_password, new_password });
  setSession(data.access_token, data.user);
  applySession({
    user: data.user,
    must_change_password: data.must_change_password,
    server_time: data.server_time,
    expires_at: data.expires_at,
    absolute_expires_at: data.absolute_expires_at,
  });
  return data;
}

export async function renewSession() {
  const data = await post<{
    server_time: string;
    expires_at: string;
    absolute_expires_at: string;
    must_change_password: boolean;
  }>("/auth/renew");
  session.expiresAt = data.expires_at;
  session.absoluteExpiresAt = data.absolute_expires_at;
  session.serverTime = data.server_time;
  return data;
}

export async function logout() {
  try {
    if (token()) await post("/auth/logout");
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 401) throw error;
  } finally {
    clearSession();
    session.user = null;
    session.courses = [];
    session.courseId = "";
    session.mustChangePassword = false;
    session.ready = false;
    session.coursesLoaded = false;
  }
}

export function resetLocalSession() {
  clearSession();
  session.user = null;
  session.courses = [];
  session.courseId = "";
  session.mustChangePassword = false;
  session.ready = false;
  session.coursesLoaded = false;
}
