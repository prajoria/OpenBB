/**
 * Widget canvas — mounts registered widgets into a 12-col grid (#981).
 *
 * Consumes ``WidgetSlot[]`` (a list of ``{id, config?}`` tuples the
 * caller wants rendered) and returns a grid of widgets. Handles:
 *
 * - Unknown widget id → renders a visible error card (loud failure;
 *   silent skip would mask a broken slot config).
 * - ``isPaper`` meta → wraps the widget header with a PAPER badge
 *   automatically. Widget authors do NOT hand-place the badge.
 * - React error boundary per slot so one broken widget doesn't blank
 *   the whole canvas.
 */

import type React from "react";
import { Component, type ErrorInfo, type ReactNode } from "react";
import { getWidget, PAPERBadge } from "../sdk";

export interface WidgetSlot {
	/** Registered widget id (from the SDK registry). */
	widgetId: string;
	/** Optional per-instance override; defaults to registered meta.title. */
	title?: string;
	/** Optional caller-supplied config, passed through to the widget. */
	config?: Record<string, unknown>;
}

export interface WidgetCanvasProps {
	slots: WidgetSlot[];
	/**
	 * If true, canvas asks every widget to render with fixture data.
	 * Used by preview harness + tests.
	 */
	fixture?: boolean;
}

class SlotBoundary extends Component<
	{ children: ReactNode; slotId: string },
	{ err?: Error }
> {
	state: { err?: Error } = {};

	static getDerivedStateFromError(err: Error): { err: Error } {
		return { err };
	}

	componentDidCatch(err: Error, info: ErrorInfo): void {
		// Log so the desktop backend-logs page picks it up; do NOT
		// swallow silently — the whole canvas would look "empty" otherwise.
		// biome-ignore lint/suspicious/noConsole: intentional
		console.error(`[widget-canvas] slot ${this.props.slotId} threw`, err, info);
	}

	render(): ReactNode {
		if (this.state.err) {
			return (
				<div
					data-testid="widget-error-boundary"
					className="p-3 border border-red-500 rounded bg-red-50 text-red-900 text-sm"
				>
					<div className="font-semibold">Widget failed: {this.props.slotId}</div>
					<div className="mt-1 font-mono text-xs break-all">
						{this.state.err.message}
					</div>
				</div>
			);
		}
		return this.props.children;
	}
}

export function WidgetCanvas({ slots, fixture }: WidgetCanvasProps): React.ReactElement {
	return (
		<div
			data-testid="widget-canvas"
			className="grid grid-cols-12 gap-4 p-4"
		>
			{slots.map((slot, idx) => {
				const reg = getWidget(slot.widgetId);
				const slotKey = `${slot.widgetId}-${idx}`;
				if (!reg) {
					// Unknown id → visible error card (loud, not silent).
					return (
						<div
							key={slotKey}
							data-testid="widget-unknown"
							className="col-span-4 p-3 border border-yellow-500 rounded bg-yellow-50 text-yellow-900 text-sm"
						>
							<div className="font-semibold">Unknown widget</div>
							<div className="mt-1 font-mono text-xs">{slot.widgetId}</div>
						</div>
					);
				}
				const { meta, Component: Widget } = reg;
				const width = meta.widthCells ?? 4;
				const height = meta.heightCells ?? 1;
				return (
					<div
						key={slotKey}
						data-testid="widget-slot"
						data-widget-id={meta.id}
						className={
							`col-span-${width} row-span-${height} ` +
							"border rounded shadow-sm bg-white flex flex-col"
						}
						style={{ minHeight: `${height * 200}px` }}
					>
						<div className="flex items-center justify-between p-2 border-b bg-gray-50">
							<h3 className="text-sm font-semibold">{slot.title ?? meta.title}</h3>
							{meta.isPaper ? <PAPERBadge /> : null}
						</div>
						<div className="flex-1 p-3 overflow-auto">
							<SlotBoundary slotId={meta.id}>
								<Widget id={slotKey} config={slot.config} fixture={fixture} />
							</SlotBoundary>
						</div>
					</div>
				);
			})}
		</div>
	);
}
