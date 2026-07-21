/**
 * Typed openbb backend client for portfolio-intel widgets (#982).
 *
 * Thin wrapper over ``fetch`` that:
 * - reads the backend base URL from Vite env (``VITE_OPENBB_API_BASE``,
 *   defaults to ``http://127.0.0.1:8000``, matching ``./openbb.sh api``)
 * - always sends ``application/json``
 * - throws {@link BackendError} on any non-2xx (never returns silently
 *   partial data — matches the "loud empties" rule in CLAUDE.md)
 * - accepts a per-call ``AbortSignal`` so widget cleanups can cancel
 *
 * The typed client per endpoint is generated from OpenBB's OpenAPI
 * schema in a follow-up (tracked under #982 acceptance). For now
 * widgets call {@link get} / {@link post} with a route string and cast
 * to their expected type — the SDK still gives them the shared error
 * shape + fixture switch.
 */

export class BackendError extends Error {
	constructor(
		public readonly status: number,
		public readonly route: string,
		message: string,
	) {
		super(`[backend ${status} ${route}] ${message}`);
		this.name = "BackendError";
	}
}

const _defaultBase = "http://127.0.0.1:8000";

function _base(): string {
	// import.meta.env is Vite-injected; guard for test env.
	const env = (import.meta as unknown as { env?: Record<string, string> })?.env ?? {};
	return env.VITE_OPENBB_API_BASE ?? _defaultBase;
}

async function _request<T>(
	route: string,
	init: RequestInit,
): Promise<T> {
	const url = `${_base()}${route.startsWith("/") ? route : `/${route}`}`;
	let resp: Response;
	try {
		resp = await fetch(url, {
			...init,
			headers: {
				"Content-Type": "application/json",
				...(init.headers ?? {}),
			},
		});
	} catch (err) {
		// Network-level failure — surface with full route context so the
		// widget's error boundary shows something actionable.
		throw new BackendError(
			0,
			route,
			`network error: ${(err as Error).message}`,
		);
	}
	if (!resp.ok) {
		// Try to read a body for the message; ignore parse failures — a
		// non-JSON error page still tells us the status.
		let detail = "";
		try {
			detail = await resp.text();
		} catch {
			// noop
		}
		throw new BackendError(resp.status, route, detail.slice(0, 500));
	}
	return (await resp.json()) as T;
}

export function get<T>(
	route: string,
	options: { signal?: AbortSignal } = {},
): Promise<T> {
	return _request<T>(route, { method: "GET", signal: options.signal });
}

export function post<T>(
	route: string,
	body: unknown,
	options: { signal?: AbortSignal } = {},
): Promise<T> {
	return _request<T>(route, {
		method: "POST",
		body: JSON.stringify(body),
		signal: options.signal,
	});
}
