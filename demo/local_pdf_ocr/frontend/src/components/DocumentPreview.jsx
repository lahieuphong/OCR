import {useEffect, useState} from "react";

// Chromium's PDF viewer says "loaded" after about 15 ms, then shows a dark empty frame until the first page is
// drawn: measured about 100 ms for 0.3 MB and 900 ms for a 13 MB scan. Nothing tells the page when that happens,
// so these leave a margin, checked frame by frame with every CPU core busy. Too short only brings back the brief
// dark frame; too long makes switching feel slow.
const PDF_PAINT_BASE_MS = 200, PDF_PAINT_PER_MB_MS = 90;
const LOAD_LIMIT_MS = 5000, FADE_MS = 120;
export const paintDelay = ({isPDF, size}) => isPDF ? PDF_PAINT_BASE_MS + PDF_PAINT_PER_MB_MS * size / 1048576 : 0;

// A new document loads underneath the one on screen and only replaces it once drawn, so switching never
// shows an empty frame. The first document waits behind an empty cover in the same way.
// New layers go last and finished ones are removed: moving an iframe in the page would reload it.
export default function DocumentPreview({url, isPDF, size = 0}) {
  const [layers, setLayers] = useState([{url:"", state:"shown"}]);
  const [loadedUrl, setLoadedUrl] = useState("");
  useEffect(() => {
    // A newer choice replaces a document still loading. isPDF and size belong to url: both change together.
    setLayers(list => list.some(layer => layer.url === url) ? list
      : [...list.filter(layer => layer.state !== "loading"), {url, isPDF, size, state:"loading"}]);
  }, [url]);

  const loading = layers.find(layer => layer.state === "loading");
  const wait = !loading ? null : loadedUrl === loading.url ? paintDelay(loading) : LOAD_LIMIT_MS;
  useEffect(() => {
    if (!loading) return;
    const timer = window.setTimeout(() => setLayers(list => list.map(layer => layer.url === loading.url ? {...layer, state:"shown"}
      : layer.state === "shown" ? {...layer, state:"leaving"} : layer)), wait);
    return () => window.clearTimeout(timer);
  }, [loading?.url, wait]);

  const leaving = layers.some(layer => layer.state === "leaving");
  useEffect(() => {
    if (!leaving) return;
    const timer = window.setTimeout(() => setLayers(list => list.filter(layer => layer.state !== "leaving")), FADE_MS);
    return () => window.clearTimeout(timer);
  }, [leaving]);

  return <div className="preview-stage">
    {layers.map(layer => <div key={layer.url || "cover"} className={"preview-layer " + layer.state} inert={layer.state !== "shown"}>
      {!layer.url ? null : layer.isPDF
        ? <iframe className="pdf-view" src={layer.url + "#toolbar=0"} title="Bản xem trước PDF" onLoad={() => setLoadedUrl(layer.url)}/>
        : <div className="image-view"><img src={layer.url} alt="Bản xem trước tài liệu" onLoad={() => setLoadedUrl(layer.url)} onError={() => setLoadedUrl(layer.url)}/></div>}
    </div>)}
    {loading && <div className="preview-loading" aria-hidden="true"/>}
  </div>;
}
