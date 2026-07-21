/**
 * "Hello widget" — the smallest possible widget, used by the preview
 * harness + tests to prove the SDK + canvas wiring is intact.
 *
 * Real widgets (#529-#577) each register in their own module and are
 * imported side-effectfully from ``../widgets/index.ts``.
 */

import type React from "react";
import { registerWidget, type WidgetProps } from "../sdk";

function HelloWidget({ id, fixture }: WidgetProps): React.ReactElement {
	return (
		<div data-testid={`hello-${id}`} className="text-sm text-gray-700">
			<div>Hello from the widget SDK smoke widget.</div>
			<div className="mt-2 text-xs font-mono">
				fixture-mode: {String(Boolean(fixture))}
			</div>
		</div>
	);
}

registerWidget(
	{
		id: "hello",
		title: "Hello (SDK smoke)",
		widthCells: 4,
		heightCells: 1,
	},
	HelloWidget,
);
