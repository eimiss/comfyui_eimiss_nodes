// RegionalPrompter: grey out `strength` when there is no base prompt, because it
// only blends the base back in and does nothing without one.
const { app } = window.comfyAPI.app;

app.registerExtension({
  name: "Eimiss.RegionalPrompter",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== "RegionalPrompter") return;

    const syncStrength = (node) => {
      const base = node.widgets?.find((w) => w.name === "prepend_base_to_regions");
      const strength = node.widgets?.find((w) => w.name === "strength");
      if (!base || !strength) return;
      strength.disabled = !(base.value === true || base.value === "true");
      node.graph?.setDirtyCanvas(true, true);
    };

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
      syncStrength(this);
      return r;
    };

    // Loading a workflow sets widget values directly, without callbacks.
    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      const r = onConfigure ? onConfigure.apply(this, arguments) : undefined;
      syncStrength(this);
      return r;
    };

    const onWidgetChanged = nodeType.prototype.onWidgetChanged;
    nodeType.prototype.onWidgetChanged = function (name, value, prevValue, widget) {
      const r = onWidgetChanged ? onWidgetChanged.apply(this, arguments) : undefined;
      if (name === "prepend_base_to_regions") syncStrength(this);
      return r;
    };
  },
});
