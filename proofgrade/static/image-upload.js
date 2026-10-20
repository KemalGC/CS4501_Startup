'use strict';

// The server accepts only bounded RGB pixels and builds a fresh PNG itself.
// It never needs to import Pillow or decode this original image file.
window.ProofGradeImages = (() => {
  const maxBytes = 8 * 1024 * 1024, maxSourcePixels = 20_000_000;
  const maxSide = 2400, maxPixels = 3_000_000;

  async function fileKind(file) {
    if (!file.size || file.size > maxBytes) throw new Error('Choose a nonempty file of at most 8 MiB.');
    const header = new Uint8Array(await file.slice(0, 8).arrayBuffer());
    if ([137, 80, 78, 71, 13, 10, 26, 10].every((n, i) => header[i] === n)) return 'image';
    if (header[0] === 255 && header[1] === 216 && header[2] === 255) return 'image';
    if ([37, 80, 68, 70, 45].every((n, i) => header[i] === n)) return 'pdf';
    throw new Error('Use a JPG or PNG photo. Convert HEIC or other formats to JPG first.');
  }

  function base64(bytes) {
    const chunks = [];
    for (let start = 0; start < bytes.length; start += 0x8000) {
      chunks.push(String.fromCharCode(...bytes.subarray(start, start + 0x8000)));
    }
    return btoa(chunks.join(''));
  }

  async function prepare(file) {
    if (await fileKind(file) !== 'image') throw new Error('Choose a JPG or PNG photo.');
    if (typeof createImageBitmap !== 'function') throw new Error('Photo preparation needs a current browser such as Edge, Chrome, Firefox, or Safari.');
    let bitmap;
    try { bitmap = await createImageBitmap(file, {imageOrientation: 'from-image'}); }
    catch { throw new Error('Could not read this photo. Save it as a JPG or PNG and try again.'); }
    const canvas = document.createElement('canvas');
    try {
      if (!bitmap.width || !bitmap.height || bitmap.width * bitmap.height > maxSourcePixels) {
        throw new Error('Choose a photo of at most 20 megapixels.');
      }
      const scale = Math.min(1, maxSide / bitmap.width, maxSide / bitmap.height,
        Math.sqrt(maxPixels / (bitmap.width * bitmap.height)));
      canvas.width = Math.max(1, Math.floor(bitmap.width * scale));
      canvas.height = Math.max(1, Math.floor(bitmap.height * scale));
      const context = canvas.getContext('2d', {alpha: false, willReadFrequently: true});
      if (!context) throw new Error('This browser could not prepare the photo. Try a current browser.');
      context.fillStyle = '#fff';
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.imageSmoothingEnabled = true;
      context.imageSmoothingQuality = 'high';
      context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      const rgba = context.getImageData(0, 0, canvas.width, canvas.height).data;
      const rgb = new Uint8Array(canvas.width * canvas.height * 3);
      for (let source = 0, target = 0; source < rgba.length; source += 4) {
        rgb[target++] = rgba[source]; rgb[target++] = rgba[source + 1]; rgb[target++] = rgba[source + 2];
      }
      return {width: canvas.width, height: canvas.height, pixels_base64: base64(rgb)};
    } finally {
      bitmap.close(); canvas.width = canvas.height = 0;
    }
  }

  return Object.freeze({fileKind, prepare, base64});
})();
