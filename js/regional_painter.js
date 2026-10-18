// RegionalPainter frontend: a paint dialog that writes the region map (base64 PNG)
// into the node's paint_data widget. Colors must match RegionalPrompter.py.
import { app } from "../../scripts/app.js";

const { ComfyDialog } = window.comfyAPI.ui;

const REGION_COLORS = [
  "#2196F3", "#4CAF50", "#F44336", "#FFEB3B",
  "#E040FB", "#00BCD4", "#FF9800", "#9C27B0",
  "#CDDC39", "#FF80AB",
];

const MAX_REGIONS = REGION_COLORS.length;
const WIDGET_HEIGHT = 280;
const BG_COLOR = [26, 26, 26];
const LABEL_STYLE = "color:#ccc;font-family:sans-serif;font-size:13px;";

function hexToRgb(hex) {
  const v = parseInt(hex.slice(1), 16);
  return [(v >> 16) & 255, (v >> 8) & 255, v & 255];
}

function clampInt(v, lo, hi) {
  const n = Math.round(Number(v));
  if (!Number.isFinite(n)) return lo;
  return Math.max(lo, Math.min(hi, n));
}

// Reads a node widget's value.
function widgetValue(node, name) {
  const w = node?.widgets?.find((w) => w.name === name);
  return w ? w.value : undefined;
}

// Best-effort value of the primitive feeding a connected widget input.
function linkedIntValue(node, inputName) {
  const inp = node?.inputs?.find((i) => i.name === inputName);
  if (!inp || inp.link == null || !node.graph) return undefined;
  const links = node.graph.links;
  const link = typeof links.get === "function" ? links.get(inp.link) : links?.[inp.link];
  if (!link) return undefined;
  const src = node.graph.getNodeById(link.origin_id);
  const out = src?.outputs?.[link.origin_slot];
  const numeric = src?.widgets?.filter((w) => typeof w.value === "number") ?? [];
  // Pick the widget behind the linked output; a lone number widget (primitives) is unambiguous.
  const w = numeric.find((w) => w.name === out?.name) ?? (numeric.length === 1 ? numeric[0] : undefined);
  return w ? w.value : undefined;
}

// Effective INT for width/height/regions: a connected input wins over the widget.
function inputIntValue(node, name) {
  const inp = node?.inputs?.find((i) => i.name === name);
  if (inp && inp.link != null) return linkedIntValue(node, name) ?? widgetValue(node, name);
  return widgetValue(node, name);
}

// Canvas size for painting: the target width/height (widget or linked) when known,
// otherwise the painted map's own size, otherwise 1024. This keeps the preview and
// the paint dialog matching the generation resolution when width/height are driven
// from other nodes.
function painterSize(node, img) {
  const w = Number(inputIntValue(node, "width"));
  const h = Number(inputIntValue(node, "height"));
  if (Number.isFinite(w) && Number.isFinite(h)) {
    return [clampInt(w, 64, 2048), clampInt(h, 64, 2048)];
  }
  if (img && img.naturalWidth && img.naturalHeight) return [img.naturalWidth, img.naturalHeight];
  return [1024, 1024];
}

function setWidgetValue(node, name, value) {
  const w = node?.widgets?.find((w) => w.name === name);
  if (w) {
    w.value = value;
    w.callback?.(value);
  }
}

// Encodes the canvas as a PNG data URL.
function canvasDataURL(canvas) {
  if (canvas.toDataURL) return canvas.toDataURL("image/png", 1);
  return canvas.toDataURL("image/png");
}

// Only one paint dialog at a time, so Save/Cancel can't stack dialog instances.
let activeDialog = null;

function openPaintDialog(node) {
  if (activeDialog) return;
  activeDialog = new RegionalPaintDialog(node);
  activeDialog.show();
}

class RegionalPaintDialog extends ComfyDialog {
  constructor(node) {
    super();
    this.node = node;
    this.widget = node.widgets?.find((w) => w.name === "paint_data");
    const [canvasW, canvasH] = painterSize(node, this.widget?._img);
    this.width = canvasW;
    this.height = canvasH;
    this.numRegions = clampInt(inputIntValue(node, "regions"), 2, MAX_REGIONS);
    this.currentRegion = clampInt(this.widget?._activeRegion, 1, this.numRegions);
    this.brushSize = clampInt(this.widget?._lastBrush, 2, 512);
    this.painting = false;
    this.erase = false;
    this.last = null;
    this.mousePos = null;
    this.legendEls = [];

    this.canvas = document.createElement("canvas");
    this.canvas.width = this.width;
    this.canvas.height = this.height;
    this.ctx = this.canvas.getContext("2d", { willReadFrequently: true });
    // A rescaled map must keep exact palette colors.
    this.ctx.imageSmoothingEnabled = false;
    this.image = this.ctx.createImageData(this.width, this.height);
    this._fillBg(this.image.data);

    this._buildLayout();

    // Load the existing map (if any) as the starting point.
    const data = this.widget?.value;
    if (data) {
      const img = new Image();
      img.onload = () => {
        this.ctx.drawImage(img, 0, 0, this.width, this.height);
        this._capture();
      };
      img.onerror = () => {};
      img.src = data;
    } else {
      this.ctx.putImageData(this.image, 0, 0);
    }
  }

  _fillBg(data) {
    for (let i = 0; i < data.length; i += 4) {
      data[i] = BG_COLOR[0];
      data[i + 1] = BG_COLOR[1];
      data[i + 2] = BG_COLOR[2];
      data[i + 3] = 255;
    }
  }

  _capture() {
    this.image = this.ctx.getImageData(0, 0, this.width, this.height);
  }

  show() {
    this.element.style.display = "flex";
  }

  close() {
    super.close();
    if (activeDialog === this) activeDialog = null;
  }

  _buildLayout() {
    // Paint canvas, scaled to fit the window.
    const canvasWrap = document.createElement("div");
    canvasWrap.style.cssText = "position:relative;margin:10px auto;text-align:center;";
    const scale = Math.min((window.innerWidth * 0.8) / this.width, (window.innerHeight * 0.55) / this.height);
    this.canvas.style.width = Math.max(1, Math.round(this.width * scale)) + "px";
    this.canvas.style.height = Math.max(1, Math.round(this.height * scale)) + "px";
    this.canvas.style.border = "1px solid #555";
    this.canvas.style.background = "#0e0e0e";
    this.canvas.style.cursor = "none";
    canvasWrap.appendChild(this.canvas);

    // Hint line.
    const hint = document.createElement("div");
    hint.style.cssText = "color:#999;font-family:sans-serif;font-size:13px;text-align:center;padding:2px 0;";
    hint.textContent = "left-drag paints the selected region, right-drag erases";

    const controls = document.createElement("div");
    controls.style.cssText = "display:flex;align-items:center;gap:10px;flex-wrap:wrap;justify-content:center;padding:6px 10px;";

    // Region label.
    const legendLabel = document.createElement("span");
    legendLabel.style.cssText = LABEL_STYLE;
    legendLabel.textContent = "Regions:";
    controls.appendChild(legendLabel);

    // One color swatch button per region; click selects it.
    for (let i = 1; i <= this.numRegions; i++) {
      const sw = document.createElement("button");
      sw.type = "button";
      sw.style.cssText = `width:26px;height:26px;background:${REGION_COLORS[i - 1]};border:2px solid #333;border-radius:4px;cursor:pointer;color:#111;font-size:11px;font-weight:bold;display:flex;align-items:center;justify-content:center;`;
      sw.textContent = String(i);
      sw.addEventListener("click", () => {
        this.currentRegion = i;
        this._updateLegend();
        this._updateRegionLabel();
      });
      controls.appendChild(sw);
      this.legendEls.push(sw);
    }

    // Shows the active region number and color.
    this.regionLabel = document.createElement("span");
    this.regionLabel.style.cssText = "color:#eee;font-family:sans-serif;font-size:13px;";
    controls.appendChild(this.regionLabel);

    // Brush label.
    const brushLabel = document.createElement("span");
    brushLabel.style.cssText = LABEL_STYLE;
    brushLabel.textContent = "Brush:";
    controls.appendChild(brushLabel);

    // Brush size slider.
    this.brushInput = document.createElement("input");
    this.brushInput.type = "range";
    this.brushInput.min = "2";
    this.brushInput.max = "512";
    this.brushInput.step = "2";
    this.brushInput.value = String(this.brushSize);
    this.brushInput.addEventListener("input", () => {
      this.brushSize = clampInt(Number(this.brushInput.value), 2, 512);
      this.brushValLabel.textContent = String(this.brushSize);
    });
    controls.appendChild(this.brushInput);

    // Brush size value readout.
    this.brushValLabel = document.createElement("span");
    this.brushValLabel.style.cssText = "color:#eee;font-family:sans-serif;font-size:13px;";
    this.brushValLabel.textContent = String(this.brushSize);
    controls.appendChild(this.brushValLabel);

    // Clear
    const clearBtn = document.createElement("button");
    clearBtn.type = "button";
    clearBtn.textContent = "Clear";
    clearBtn.style.cssText = "padding:4px 12px;cursor:pointer;";
    clearBtn.addEventListener("click", () => this._clear());
    controls.appendChild(clearBtn);

    // Save
    const saveBtn = document.createElement("button");
    saveBtn.type = "button";
    saveBtn.textContent = "Save";
    saveBtn.style.cssText = "padding:4px 12px;cursor:pointer;font-weight:bold;";
    saveBtn.addEventListener("click", () => this._save());
    controls.appendChild(saveBtn);

    // Cancel
    const cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.textContent = "Cancel";
    cancelBtn.style.cssText = "padding:4px 12px;cursor:pointer;";
    cancelBtn.addEventListener("click", () => this.close());
    controls.appendChild(cancelBtn);

    // hint on top, canvas in the middle, controls below.
    const content = document.createElement("div");
    content.className = "comfy-modal-content";
    content.style.cssText = "padding:10px;";
    content.appendChild(hint);
    content.appendChild(canvasWrap);
    content.appendChild(controls);

    this.element.replaceChildren(content);
    this._updateLegend();
    this._updateRegionLabel();

    this.canvas.addEventListener("pointerdown", (e) => this._onPointerDown(e));
    this.canvas.addEventListener("pointermove", (e) => this._onPointerMove(e));
    this.canvas.addEventListener("pointerup", () => this._onPointerUp());
    this.canvas.addEventListener("pointercancel", () => this._onPointerUp());
    this.canvas.addEventListener("pointerleave", () => this._onPointerLeave());
    this.canvas.addEventListener("contextmenu", (e) => e.preventDefault());
  }

  _updateLegend() {
    for (const sw of this.legendEls) {
      const selected = Number(sw.textContent) === this.currentRegion;
      sw.style.borderColor = selected ? "#ffffff" : "#333333";
      sw.style.boxShadow = selected ? "0 0 4px #fff" : "none";
    }
  }

  _updateRegionLabel() {
    this.regionLabel.textContent = `Painting region ${this.currentRegion} (${REGION_COLORS[this.currentRegion - 1]})`;
  }

  _canvasPos(e) {
    const rect = this.canvas.getBoundingClientRect();
    return [
      Math.floor((e.clientX - rect.left) * (this.canvas.width / rect.width)),
      Math.floor((e.clientY - rect.top) * (this.canvas.height / rect.height)),
    ];
  }

  // Paints a round brush stamp into the ImageData buffer.
  _stamp(cx, cy, r) {
    const data = this.image.data;
    const color = this.erase ? BG_COLOR : hexToRgb(REGION_COLORS[this.currentRegion - 1]);
    const r2 = r * r;
    const x0 = Math.max(0, cx - r);
    const x1 = Math.min(this.width - 1, cx + r);
    const y0 = Math.max(0, cy - r);
    const y1 = Math.min(this.height - 1, cy + r);
    for (let y = y0; y <= y1; y++) {
      for (let x = x0; x <= x1; x++) {
        const dx = x - cx;
        const dy = y - cy;
        if (dx * dx + dy * dy > r2) continue;
        const i = (y * this.width + x) * 4;
        data[i] = color[0];
        data[i + 1] = color[1];
        data[i + 2] = color[2];
        data[i + 3] = 255;
      }
    }
  }

  // Interpolates the stroke so fast drags don't leave gaps.
  _line(x0, y0, x1, y1, r) {
    const dist = Math.hypot(x1 - x0, y1 - y0);
    const steps = Math.max(1, Math.ceil(dist / Math.max(1, r * 0.5)));
    for (let s = 1; s < steps; s++) {
      this._stamp(Math.round(x0 + (x1 - x0) * s / steps), Math.round(y0 + (y1 - y0) * s / steps), r);
    }
  }

  _paintAt(x, y) {
    if (x < 0 || y < 0 || x >= this.width || y >= this.height) return;
    const r = Math.max(1, this.brushSize / 2);
    if (this.last) this._line(this.last[0], this.last[1], x, y, r);
    this._stamp(x, y, r);
    this.last = [x, y];
    this._render();
  }

  // Redraws the canvas plus the brush-size outline at the cursor.
  _render() {
    this.ctx.putImageData(this.image, 0, 0);
    if (!this.mousePos) return;
    const [mx, my] = this.mousePos;
    const r = this.brushSize / 2;
    this.ctx.beginPath();
    this.ctx.arc(mx, my, r, 0, 2 * Math.PI);
    this.ctx.strokeStyle = "rgba(0,0,0,0.7)";
    this.ctx.lineWidth = 4;
    this.ctx.stroke();
    this.ctx.strokeStyle = this.erase ? "rgba(255,120,120,0.95)" : "rgba(255,255,255,0.95)";
    this.ctx.lineWidth = 2;
    this.ctx.stroke();
  }

  _clear() {
    this._fillBg(this.image.data);
    this._render();
  }

  // Writes the painted map into the node widget and closes.
  _save() {
    const url = canvasDataURL(this.canvas);
    if (this.widget) {
      this.widget._activeRegion = this.currentRegion;
      this.widget._lastBrush = this.brushSize;
    }
    setWidgetValue(this.node, "paint_data", url);
    this.close();
  }

  _onPointerDown(e) {
    e.preventDefault();
    e.stopPropagation();
    const [x, y] = this._canvasPos(e);
    this.mousePos = [x, y];
    this.painting = true;
    this.erase = e.button === 2;
    this.last = null;
    this._paintAt(x, y);
    try {
      this.canvas.setPointerCapture(e.pointerId);
    } catch (_) {}
  }

  _onPointerMove(e) {
    const [x, y] = this._canvasPos(e);
    this.mousePos = [x, y];
    if (this.painting) this._paintAt(x, y);
    else this._render();
  }

  _onPointerUp() {
    if (!this.painting) return;
    this.painting = false;
    this.last = null;
    this._render();
  }

  _onPointerLeave() {
    this.mousePos = null;
    this.ctx.putImageData(this.image, 0, 0);
  }
}

// Widget preview: legend with the region colors + the current map.
function makePaintWidget(node) {
  const widget = {
    type: "custom",
    name: "paint_data",
    parent: node,
    _value: "",
    _img: null,
    _imgKey: "",
    _activeRegion: 1,
    _lastBrush: 32,

    get value() {
      return this._value;
    },
    set value(v) {
      this._value = v || "";
      this._imgKey = "";
      this._img = null;
      if (this.parent?.graph) this.parent.graph.setDirtyCanvas(true, true);
    },

    computeLayoutSize() {
      return { minHeight: 180, maxHeight: 560 };
    },

    mouse(e, pos, node) {
      // Only open on press; the same click's release must not open a second dialog.
      if (String(e?.type || "").includes("down")) {
        openPaintDialog(node);
        return true;
      }
      return false;
    },

    _loadImg() {
      const v = this._value;
      this._imgKey = v;
      if (!v) {
        this._img = null;
        return;
      }
      const img = new Image();
      img.onload = () => {
        if (this._imgKey !== v) return;
        this._img = img;
        if (this.parent?.graph) this.parent.graph.setDirtyCanvas(true, true);
      };
      img.onerror = () => {
        if (this._imgKey === v) this._img = null;
      };
      img.src = v;
    },

    // Preview: the current map, scaled to fit the widget and clamped to the node.
    draw(ctx, node, width, y) {
      if (this._imgKey !== this._value) this._loadImg();

      // Stay inside the node even if it was resized smaller than the layout expects.
      const nodeH = node.size?.[1] ?? y + WIDGET_HEIGHT;
      const top = Math.min(y, Math.max(0, nodeH - 80));
      const height = Math.max(80, Math.min(this.computedHeight ?? WIDGET_HEIGHT, nodeH - top - 4));

      const margin = 8;
      const availW = Math.max(40, width - margin * 2);
      const availH = Math.max(40, height - margin);
      const [w, h] = painterSize(node, this._img);
      const scale = Math.min(availW / w, availH / h);
      const cw = w * scale;
      const ch = h * scale;
      const x = margin + (availW - cw) / 2;
      const cy = top + (availH - ch) / 2;

      ctx.fillStyle = "#151515";
      ctx.fillRect(x - 2, cy - 2, cw + 4, ch + 4);
      ctx.fillStyle = "#0e0e0e";
      ctx.fillRect(x, cy, cw, ch);
      if (this._img) {
        ctx.drawImage(this._img, x, cy, cw, ch);
      }

      ctx.strokeStyle = "#3a3a3a";
      ctx.lineWidth = 1;
      ctx.strokeRect(x - 1, cy - 1, cw + 2, ch + 2);
    },
  };
  return widget;
}

app.registerExtension({
  name: "Eimiss.RegionalPainter",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== "RegionalPainter") return;

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
      this.serialize_widgets = true;
      // Replace the plain text widget with our custom canvas preview.
      const idx = this.widgets?.findIndex((w) => w.name === "paint_data") ?? -1;
      if (idx >= 0) this.widgets.splice(idx, 1);
      this.addCustomWidget(makePaintWidget(this));
      // paint_data is internal state, so drop its link socket.
      const slot = this.inputs?.findIndex((i) => i.name === "paint_data") ?? -1;
      if (slot >= 0) this.removeInput(slot);
      return r;
    };

    const getOpts = nodeType.prototype.getExtraMenuOptions;
    nodeType.prototype.getExtraMenuOptions = function (_, options) {
      const r = getOpts ? getOpts.apply(this, arguments) : undefined;
      options.unshift({
        content: "Paint Region Map",
        callback: () => openPaintDialog(this),
      });
      return r;
    };
  },
});