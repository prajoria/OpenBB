/**
 * Widget SDK + canvas tests (#981, #982).
 *
 * Discriminators:
 * - registry rejects duplicate id (protects against copy-paste bugs)
 * - canvas renders a visible error card for unknown widget ids
 *   (loud, not silent — matches CLAUDE.md's "loud empties" rule)
 * - canvas auto-injects PAPER badge for paper widgets
 *   (widget authors do NOT hand-place it, per #555 UX)
 * - preview harness passes fixture=true through to widget render
 * - error boundary catches widget throws without blanking the canvas
 */

import { describe, expect, test, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import {
	registerWidget,
	getWidget,
	allWidgetIds,
	_resetRegistryForTests,
	type WidgetProps,
} from "../pi/sdk";
import { WidgetCanvas } from "../pi/canvas/WidgetCanvas";

beforeEach(() => {
	_resetRegistryForTests();
});

describe("registry", () => {
	test("registerWidget + getWidget round-trip", () => {
		const Widget = () => <div>ok</div>;
		registerWidget({ id: "w1", title: "W1" }, Widget);
		expect(getWidget("w1")?.meta.title).toBe("W1");
	});

	test("registerWidget rejects duplicate id (copy-paste guard)", () => {
		const Widget = () => <div>ok</div>;
		registerWidget({ id: "dupe", title: "A" }, Widget);
		expect(() => registerWidget({ id: "dupe", title: "B" }, Widget)).toThrow(
			/already registered/,
		);
	});

	test("allWidgetIds returns sorted ids", () => {
		const Widget = () => <div>ok</div>;
		registerWidget({ id: "b", title: "B" }, Widget);
		registerWidget({ id: "a", title: "A" }, Widget);
		expect(allWidgetIds()).toEqual(["a", "b"]);
	});
});

describe("canvas", () => {
	test("renders registered widget inside a slot", () => {
		const Widget = (p: WidgetProps) => (
			<div data-testid={`x-${p.id}`}>hello</div>
		);
		registerWidget({ id: "w", title: "W" }, Widget);
		render(<WidgetCanvas slots={[{ widgetId: "w" }]} />);
		expect(screen.getByTestId("widget-slot")).toBeInTheDocument();
		expect(screen.getByText("hello")).toBeInTheDocument();
	});

	test("unknown widget id renders visible error card, NOT silent skip", () => {
		render(<WidgetCanvas slots={[{ widgetId: "does-not-exist" }]} />);
		const unknown = screen.getByTestId("widget-unknown");
		expect(unknown).toBeInTheDocument();
		expect(unknown.textContent).toContain("does-not-exist");
	});

	test("paper widget gets PAPER badge auto-injected by canvas", () => {
		const Widget = () => <div>paper content</div>;
		registerWidget({ id: "p", title: "Paper W", isPaper: true }, Widget);
		render(<WidgetCanvas slots={[{ widgetId: "p" }]} />);
		expect(screen.getByTestId("paper-badge")).toBeInTheDocument();
	});

	test("non-paper widget has NO paper badge (guardrail against always-render)", () => {
		const Widget = () => <div>ok</div>;
		registerWidget({ id: "np", title: "Not Paper" }, Widget);
		render(<WidgetCanvas slots={[{ widgetId: "np" }]} />);
		expect(screen.queryByTestId("paper-badge")).toBeNull();
	});

	test("fixture=true is passed through to widget as prop", () => {
		const Widget = (p: WidgetProps) => (
			<div data-testid="fixture-marker">{String(p.fixture ?? false)}</div>
		);
		registerWidget({ id: "f", title: "F" }, Widget);
		render(<WidgetCanvas slots={[{ widgetId: "f" }]} fixture={true} />);
		expect(screen.getByTestId("fixture-marker").textContent).toBe("true");
	});

	test("widget that throws is caught by error boundary; other widgets keep rendering", () => {
		const Boom = () => {
			throw new Error("boom!");
		};
		const OK = () => <div data-testid="ok-widget">still here</div>;
		registerWidget({ id: "boom", title: "Boom" }, Boom);
		registerWidget({ id: "ok", title: "OK" }, OK);

		// Silence React's error-boundary console noise in this test only.
		const origError = console.error;
		console.error = () => undefined;
		try {
			render(<WidgetCanvas slots={[{ widgetId: "boom" }, { widgetId: "ok" }]} />);
		} finally {
			console.error = origError;
		}
		expect(screen.getByTestId("widget-error-boundary").textContent).toContain(
			"boom!",
		);
		expect(screen.getByTestId("ok-widget")).toBeInTheDocument();
	});

	test("empty slot list renders empty canvas (no throw)", () => {
		render(<WidgetCanvas slots={[]} />);
		expect(screen.getByTestId("widget-canvas")).toBeInTheDocument();
		expect(screen.queryByTestId("widget-slot")).toBeNull();
	});
});
