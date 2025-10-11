# Delta Strangle Control Plane – Frontend

Enterprise dashboard to supervise the BTC/ETH short strangle automation.

## Highlights

- Strategy configuration form with delta, schedule, risk, and trailing SL controls.
- Trading command center to start/stop/restart the engine and monitor live sessions.
- Advanced analytics with KPI tiles and PnL trend charts.
- Light/Dark appearance toggle with stored user preference and Ant Design theming.
- Always-on UTC/IST clock in the header for quick operational awareness.
- React + Ant Design + React Query for responsive UX.

## Getting Started

```bash
cd frontend
cp .env.example .env  # configure VITE_API_BASE_URL
npm install
npm run dev
```

By default the `.env.example` file points to `http://localhost:8001/api`. Update `VITE_API_BASE_URL` if your API is hosted elsewhere (include the `/api` suffix). The React Query hooks will automatically use this value for all requests.

### Debugging API Traffic

When you need to inspect the REST traffic end-to-end, set `VITE_ENABLE_API_DEBUG=true` in `.env`. Axios interceptors will dump request and response metadata (plus JSON payloads) to the browser console using collapsed groups so you can expand only what you need.

# Frontend Documentation

Setup and usage guidance has been consolidated into the repository root [`README.md`](../README.md).
