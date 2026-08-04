
    class EventEmitter {
      constructor() { this._listeners = []; }
      get event() {
        return (fn) => { this._listeners.push(fn); return { dispose: () => {} }; };
      }
      fire(v) { for (const fn of this._listeners) fn(v); }
    }
    class TreeItem {
      constructor(label, collapsibleState) {
        this.label = label;
        this.collapsibleState = collapsibleState;
      }
    }
    class ThemeIcon { constructor(id) { this.id = id; } }
    class DataTransferItem { constructor(value) { this.value = value; } }
    module.exports = {
      EventEmitter,
      TreeItem,
      TreeItemCollapsibleState: { None: 0, Collapsed: 1, Expanded: 2 },
      ThemeIcon,
      DataTransferItem,
      window: {
        createTreeView(_id, _opts) {
          return { dispose() {} };
        },
      },
    };
    