import axios from "axios";

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? "/api").replace(/\/$/, "");
const enableDebug = String(import.meta.env.VITE_ENABLE_API_DEBUG ?? "false").toLowerCase() === "true";

const client = axios.create({
  baseURL: apiBaseUrl,
  timeout: 10000
});

if (enableDebug) {
  const formatPayload = (payload: unknown) => {
    if (payload === undefined || payload === null) return payload;
    if (typeof payload === "string") return payload;
    try {
      return JSON.parse(JSON.stringify(payload));
    } catch (error) {
      console.warn("[API Debug] Failed to serialise payload", error);
      return payload;
    }
  };

  client.interceptors.request.use((config) => {
    const method = (config.method ?? "get").toUpperCase();
    const url = `${config.baseURL ?? ""}${config.url ?? ""}`;
    console.groupCollapsed(`[API ➡️] ${method} ${url}`);
    console.log("Headers", config.headers);
    if (config.params) console.log("Query", config.params);
    if (config.data) console.log("Body", formatPayload(config.data));
    console.groupEnd();
    return config;
  });

  client.interceptors.response.use(
    (response) => {
      const method = (response.config.method ?? "get").toUpperCase();
      const url = `${response.config.baseURL ?? ""}${response.config.url ?? ""}`;
      console.groupCollapsed(`[API ⬅️] ${method} ${url} (${response.status})`);
      console.log("Headers", response.headers);
      if (response.data !== undefined) console.log("Data", formatPayload(response.data));
      console.groupEnd();
      return response;
    },
    (error) => {
      const config = error.config ?? {};
      const method = (config.method ?? "unknown").toUpperCase();
      const url = `${config.baseURL ?? ""}${config.url ?? ""}`;
      console.groupCollapsed(`[API ⬅️] ${method} ${url} (error)`);
      if (error.response) {
        console.log("Status", error.response.status);
        console.log("Headers", error.response.headers);
        console.log("Data", formatPayload(error.response.data));
      } else {
        console.log("Message", error.message);
      }
      console.groupEnd();
      return Promise.reject(error);
    }
  );
}

export default client;
