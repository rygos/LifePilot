"use client";

import { useEffect, useRef, useState, type ClipboardEvent as ReactClipboardEvent, type PointerEvent } from "react";

const canvasSize = 512;
type Offset = { x: number; y: number };

function constrainOffset(image: ImageBitmap, zoom: number, rotation: number, offset: Offset): Offset {
  const radians = rotation * Math.PI / 180;
  const extent = (Math.abs(Math.cos(radians)) + Math.abs(Math.sin(radians)));
  const scale = canvasSize * extent / Math.min(image.width, image.height) * zoom;
  const maxX = Math.max(0, (image.width * scale - canvasSize * extent) / 2);
  const maxY = Math.max(0, (image.height * scale - canvasSize * extent) / 2);
  const localX = offset.x * Math.cos(radians) + offset.y * Math.sin(radians);
  const localY = -offset.x * Math.sin(radians) + offset.y * Math.cos(radians);
  const boundedX = Math.max(-maxX, Math.min(maxX, localX));
  const boundedY = Math.max(-maxY, Math.min(maxY, localY));
  return {
    x: boundedX * Math.cos(radians) - boundedY * Math.sin(radians),
    y: boundedX * Math.sin(radians) + boundedY * Math.cos(radians),
  };
}

function drawCrop(canvas: HTMLCanvasElement, image: ImageBitmap, zoom: number, rotation: number, offset: Offset) {
  const context = canvas.getContext("2d");
  if (!context) return;
  const radians = rotation * Math.PI / 180;
  const extent = Math.abs(Math.cos(radians)) + Math.abs(Math.sin(radians));
  const scale = canvasSize * extent / Math.min(image.width, image.height) * zoom;
  const bounded = constrainOffset(image, zoom, rotation, offset);
  context.clearRect(0, 0, canvasSize, canvasSize);
  context.save();
  context.translate(canvasSize / 2 + bounded.x, canvasSize / 2 + bounded.y);
  context.rotate(radians);
  context.drawImage(image, -image.width * scale / 2, -image.height * scale / 2, image.width * scale, image.height * scale);
  context.restore();
}

export function PersonPhotoCropDialog({ file, onCancel, onFilePaste, onSave }: {
  file: File | null;
  onCancel: () => void;
  onFilePaste: (file: File) => void;
  onSave: (image: Blob) => Promise<boolean>;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imageRef = useRef<ImageBitmap | null>(null);
  const offsetRef = useRef<Offset>({ x: 0, y: 0 });
  const dragRef = useRef<{ pointerId: number; x: number; y: number; origin: Offset } | null>(null);
  const [image, setImage] = useState<ImageBitmap | null>(null);
  const [zoom, setZoom] = useState(1);
  const [rotation, setRotation] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    let decoded: ImageBitmap | null = null;
    setImage(null);
    imageRef.current = null;
    offsetRef.current = { x: 0, y: 0 };
    setZoom(1);
    setRotation(0);
    setError("");
    if (!file) return () => { cancelled = true; };
    if (typeof createImageBitmap !== "function") {
      setError("Dieser Browser unterstützt die Bildbearbeitung nicht. Bitte verwende einen aktuellen Browser.");
      return () => { cancelled = true; };
    }
    void createImageBitmap(file).then(bitmap => {
      decoded = bitmap;
      if (cancelled) { bitmap.close(); return; }
      if (bitmap.width * bitmap.height > 40_000_000) {
        bitmap.close();
        setError("Das Bild ist zu groß. Bitte wähle ein Bild unter 40 Megapixeln.");
        return;
      }
      imageRef.current = bitmap;
      setImage(bitmap);
    }).catch(() => { if (!cancelled) setError("Das Bild konnte nicht geöffnet werden. Bitte wähle ein JPEG-, PNG- oder WebP-Bild."); });
    return () => { cancelled = true; decoded?.close(); imageRef.current = null; };
  }, [file]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (canvas && image) drawCrop(canvas, image, zoom, rotation, offsetRef.current);
  }, [image, zoom, rotation]);

  useEffect(() => {
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape" && !busy) onCancel();
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [busy, onCancel]);

  useEffect(() => {
    function pasteImage(event: globalThis.ClipboardEvent) {
      const image = Array.from(event.clipboardData?.items ?? []).find(item => item.type.startsWith("image/"))?.getAsFile();
      if (!image || busy) return;
      event.preventDefault();
      if (!["image/jpeg", "image/png", "image/webp"].includes(image.type)) {
        setError("Bitte füge ein JPEG-, PNG- oder WebP-Bild ein.");
        return;
      }
      onFilePaste(new File([image], image.name || "Zwischenablagebild", { type: image.type }));
    }
    window.addEventListener("paste", pasteImage);
    return () => window.removeEventListener("paste", pasteImage);
  }, [busy, onFilePaste]);

  function pasteField(event: ReactClipboardEvent<HTMLTextAreaElement>) {
    if (!Array.from(event.clipboardData.items).some(item => item.type.startsWith("image/"))) {
      event.preventDefault();
      setError("In der Zwischenablage wurde kein Bild gefunden.");
    }
  }

  function redraw() {
    if (canvasRef.current && imageRef.current) drawCrop(canvasRef.current, imageRef.current, zoom, rotation, offsetRef.current);
  }

  function pan(event: PointerEvent<HTMLCanvasElement>) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId || !imageRef.current) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const ratio = canvasSize / bounds.width;
    offsetRef.current = constrainOffset(imageRef.current, zoom, rotation, {
      x: drag.origin.x + (event.clientX - drag.x) * ratio,
      y: drag.origin.y + (event.clientY - drag.y) * ratio,
    });
    redraw();
  }

  function nudge(direction: "left" | "right" | "up" | "down") {
    if (!imageRef.current) return;
    const movement = { left: [-12, 0], right: [12, 0], up: [0, -12], down: [0, 12] }[direction];
    offsetRef.current = constrainOffset(imageRef.current, zoom, rotation, { x: offsetRef.current.x + movement[0], y: offsetRef.current.y + movement[1] });
    redraw();
  }

  async function saveCrop() {
    const canvas = canvasRef.current;
    if (!canvas || busy) return;
    setBusy(true);
    setError("");
    canvas.toBlob(async blob => {
      if (!blob) { setError("Der Bildausschnitt konnte nicht erstellt werden."); setBusy(false); return; }
      try {
        if (!await onSave(blob)) {
          setError("Das Profilbild konnte nicht gespeichert werden. Bitte prüfe die Verbindung und versuche es erneut.");
          setBusy(false);
        }
      }
      catch { setError("Das Profilbild konnte nicht gespeichert werden."); setBusy(false); }
    }, "image/jpeg", 0.92);
  }

  return <div className="dialog-backdrop profile-dialog-backdrop photo-crop-backdrop" onMouseDown={event => { if (event.target === event.currentTarget && !busy) onCancel(); }}>
    <section className="card photo-crop-dialog" role="dialog" aria-modal="true" aria-labelledby="photo-crop-title">
      <div className="panel-head"><div><span className="eyebrow">PERSONENPROFIL</span><h2 id="photo-crop-title">Profilbild zuschneiden</h2></div><button type="button" className="quiet" onClick={onCancel} disabled={busy} aria-label="Dialog schließen">×</button></div>
      {!file && <div className="photo-paste-prompt"><p className="muted">Füge ein kopiertes Bild aus der Zwischenablage ein. Der Datei-Dialog ist dafür nicht nötig.</p><label>Bild aus Zwischenablage einfügen<textarea autoFocus aria-label="Bild aus Zwischenablage einfügen" className="photo-paste-field" rows={2} placeholder="Hier klicken und Strg+V (Mac: ⌘+V) drücken oder per Rechtsklick einfügen" onPaste={pasteField} /></label></div>}
      {file && <><p className="muted">Ziehe das Bild im Kreis an die passende Stelle. Der Bereich außerhalb des Kreises wird nicht angezeigt. Du kannst auch ein anderes Bild mit Strg+V einfügen.</p><div className="photo-crop-window">
        <canvas ref={canvasRef} width={canvasSize} height={canvasSize} aria-label="Bild im Zuschnitt verschieben" tabIndex={0}
          onPointerDown={event => { event.currentTarget.setPointerCapture(event.pointerId); dragRef.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, origin: offsetRef.current }; }}
          onPointerMove={pan} onPointerUp={() => { dragRef.current = null; }} onPointerCancel={() => { dragRef.current = null; }}
          onKeyDown={event => { const directions = { ArrowLeft: "left", ArrowRight: "right", ArrowUp: "up", ArrowDown: "down" } as const; const direction = directions[event.key as keyof typeof directions]; if (direction) { event.preventDefault(); nudge(direction); } }} />
        {!image && !error && <span className="photo-crop-loading">Bild wird vorbereitet …</span>}
      </div>
      <div className="photo-crop-controls">
        <label className="photo-crop-zoom">Zoom <output>{zoom.toFixed(1)}×</output><input id="photo-crop-zoom" type="range" min="1" max="3" step="0.05" value={zoom} onChange={event => setZoom(Number(event.target.value))} /></label>
        <div className="photo-crop-rotation"><span>Drehung · {rotation}°</span><div><button type="button" className="quiet" aria-label="45 Grad nach links drehen" onClick={() => setRotation(value => (value + 315) % 360)}>−45°</button><button type="button" className="quiet" aria-label="45 Grad nach rechts drehen" onClick={() => setRotation(value => (value + 45) % 360)}>+45°</button></div></div>
      </div></>}
      {error && <p className="photo-crop-error" role="alert">{error}</p>}
      <div className="dialog-actions"><button type="button" className="quiet" onClick={onCancel} disabled={busy}>Abbrechen</button><button type="button" onClick={() => void saveCrop()} disabled={!image || busy}>{busy ? "Wird gespeichert …" : "Bild übernehmen"}</button></div>
    </section>
  </div>;
}
