/**
 * ``/pi/preview/$widgetId`` — single-widget preview harness (#982).
 *
 * Renders one registered widget in isolation with ``fixture=true`` so
 * reviewers can see it without a live openbb backend. Enables the
 * "widget PR reviewable in a screenshot" workflow the SDK ask calls
 * out.
 *
 * URL example: ``/pi/preview/hello``
 */

import { createFileRoute } from "@tanstack/react-router";
import { WidgetCanvas } from "../../../pi/canvas/WidgetCanvas";
import { allWidgetIds } from "../../../pi/sdk";
import "../../../pi/widgets"; // side-effect: registers widgets

export const Route = createFileRoute("/pi/preview/$widgetId")({
	component: PreviewOne,
});

function PreviewOne() {
	const { widgetId } = Route.useParams();
	return (
		<div className="flex flex-col h-full">
			<header className="p-3 border-b bg-white flex items-center justify-between">
				<div>
					<h1 className="text-lg font-semibold">
						Preview: <span className="font-mono">{widgetId}</span>
					</h1>
					<p className="text-xs text-gray-500 mt-0.5">
						Rendering with <code>fixture=true</code>. No backend call.
					</p>
				</div>
				<div className="text-xs text-gray-500">
					{allWidgetIds().length} widget{allWidgetIds().length === 1 ? "" : "s"}{" "}
					registered
				</div>
			</header>
			<div className="flex-1 overflow-auto bg-gray-100">
				<WidgetCanvas slots={[{ widgetId }]} fixture={true} />
			</div>
		</div>
	);
}
