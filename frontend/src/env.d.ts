declare interface ImportMetaEnv {
	readonly VITE_API_BASE_URL?: string;
	readonly VITE_ENABLE_API_DEBUG?: string;
	readonly VITE_DELTA_WEBSOCKET_URL?: string;
}

declare interface ImportMeta {
	readonly env: ImportMetaEnv;
}
