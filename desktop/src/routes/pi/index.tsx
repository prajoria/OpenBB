/**
 * ``/pi`` route — Portfolio-Intel widget canvas landing page (#981).
 *
 * Renders the full dashboard grid. The slot list here is a static
 * default; when the widget backlog lands (#529-#577), individual
 * dashboards (X-Ray, Paper, What-If, Attribution) will each get their
 * own route consuming ``<WidgetCanvas slots={...} />``.
 */

import { createFileRoute } from "@tanstack/react-router";
import { WidgetCanvas } from "../../pi/canvas/WidgetCanvas";
import "../../pi/widgets"; // side-effect: registers all widgets

export const Route = createFileRoute("/pi/")({
	component: PortfolioIntelIndex,
});

function PortfolioIntelIndex() {
	return (
		<div className="flex flex-col h-full">
			<header className="p-4 border-b bg-white">
				<h1 className="text-xl font-semibold">Portfolio Intelligence</h1>
				<p className="text-xs text-gray-500 mt-1">
					Widget canvas host (#981). The individual widgets (#529-#577)
					land here as they ship.
				</p>
			</header>
			<div className="flex-1 overflow-auto bg-gray-100">
				<WidgetCanvas
					slots={[
						{ widgetId: "hello" },
					]}
				/>
			</div>
		</div>
	);
}
