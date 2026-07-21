/**
 * PAPER-account badge (part of #982; also satisfies #555 ask).
 *
 * Visual affordance that tags a widget as operating against a paper
 * account. Renders inline (no absolute positioning) so it composes
 * naturally next to a title inside the widget's header. Canvas
 * automatically injects it when a widget's meta declares
 * ``isPaper: true`` — widget authors should NOT hand-place this in
 * their own render.
 */

import type React from "react";

export interface PAPERBadgeProps {
	/** Optional extra class names for consumers with custom layout. */
	className?: string;
}

export function PAPERBadge({ className = "" }: PAPERBadgeProps): React.ReactElement {
	// Yellow/black is the classic "not real money" convention.
	// Matches the PAPER convention already agreed in #532 / #555.
	return (
		<span
			data-testid="paper-badge"
			className={
				"inline-flex items-center px-2 py-0.5 text-xs font-semibold " +
				"uppercase tracking-wider rounded bg-yellow-400 text-black " +
				className
			}
			title="Paper account — no real orders are placed"
		>
			Paper
		</span>
	);
}
