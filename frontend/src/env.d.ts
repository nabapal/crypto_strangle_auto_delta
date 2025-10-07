declare interface ImportMetaEnv {
	readonly MODE: string;
	readonly VITE_API_BASE_URL?: string;
	readonly VITE_ENABLE_API_DEBUG?: string;
	readonly VITE_DELTA_WEBSOCKET_URL?: string;
	readonly VITE_ENABLE_REMOTE_LOGS?: string;
	readonly VITE_LOG_ENDPOINT?: string;
	readonly VITE_LOG_API_KEY?: string;
	readonly VITE_APP_VERSION?: string;
	readonly VITE_LOG_DEDUP_WINDOW?: string;
	readonly VITE_LOG_DEDUP_THRESHOLD?: string;
}

declare interface ImportMeta {
	readonly env: ImportMetaEnv;
}
