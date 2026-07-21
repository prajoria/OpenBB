/**
 * Portfolio-Intel widget SDK (#982).
 *
 * Public API for widget authors:
 *
 * - {@link registerWidget}   register a component under a stable id
 * - {@link getWidget}        look up a registered widget by id
 * - {@link allWidgetIds}     list every registered id
 * - {@link WidgetProps}      standard prop shape every widget must accept
 * - {@link PAPERBadge}       shared visual affordance for paper-account
 *                            widgets (matches #555 UX ask)
 *
 * The registry is a plain module-scoped Map so preview + canvas + tests
 * all resolve widgets identically. Widget files register on import via
 * their side-effectful module load in {@link ./widgets/index.ts}.
 */

import type { ComponentType } from "react";

/** Shape every widget component must accept. */
export interface WidgetProps {
	/** Widget instance id (unique within a canvas). */
	id: string;
	/** Optional caller-supplied config passed through canvas → widget. */
	config?: Record<string, unknown>;
	/**
	 * If true, the widget must render with fixture data instead of
	 * hitting the live openbb backend. Set by the preview harness and
	 * by unit tests. Widgets that ignore this WILL fail CI.
	 */
	fixture?: boolean;
}

export interface WidgetMeta {
	id: string;
	title: string;
	/** Grid span in "canvas cells" (12-col grid). Default 4. */
	widthCells?: number;
	heightCells?: number;
	/**
	 * If true, canvas wraps the render with a PAPER badge. Set on
	 * paper-account widgets (Order Ticket, Blotter, Performance).
	 */
	isPaper?: boolean;
}

export interface RegisteredWidget {
	meta: WidgetMeta;
	Component: ComponentType<WidgetProps>;
}

const _registry = new Map<string, RegisteredWidget>();

/**
 * Register a widget under a stable id. Duplicate ids throw — protects
 * against copy-paste bugs where two widgets try to claim the same slot.
 */
export function registerWidget(
	meta: WidgetMeta,
	Component: ComponentType<WidgetProps>,
): void {
	if (_registry.has(meta.id)) {
		throw new Error(
			`registerWidget: id "${meta.id}" already registered; ids must be unique`,
		);
	}
	_registry.set(meta.id, { meta, Component });
}

/** Look up a registered widget by id. Returns undefined if not found. */
export function getWidget(id: string): RegisteredWidget | undefined {
	return _registry.get(id);
}

/** All registered widget ids, sorted alphabetically. */
export function allWidgetIds(): string[] {
	return [...(_registry.keys())].sort();
}

/**
 * Test-only helper — clear the registry. Never call outside tests;
 * canvas + preview both hold references to registered widgets at
 * runtime and clearing mid-app would crash them.
 */
export function _resetRegistryForTests(): void {
	_registry.clear();
}
