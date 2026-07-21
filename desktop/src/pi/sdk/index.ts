/**
 * Widget SDK public entry point (#982).
 *
 * Widgets import from ``@/pi/sdk`` (or the relative path); canvas +
 * preview both do the same. Keeping surface small on purpose: adding
 * new exports here is the coordination point between widget authors
 * and the SDK.
 */

export { registerWidget, getWidget, allWidgetIds, _resetRegistryForTests } from "./registry";
export type { WidgetProps, WidgetMeta, RegisteredWidget } from "./registry";

export { BackendError, get, post } from "./client";

export { PAPERBadge } from "./PAPERBadge";
export type { PAPERBadgeProps } from "./PAPERBadge";
