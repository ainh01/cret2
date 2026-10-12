// Cret2 attachment intake: file picking, paste detection and the local attachment list.
// Pure helpers only -- no DOM, no network. Nothing leaves the browser before "Học".

var ATTACHMENT_MAX_TOTAL = 20;
var ATTACHMENT_MAX_IMAGES = 10;
var ATTACHMENT_IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp', 'image/gif'];
var ATTACHMENT_IMAGE_MAX_BYTES = 20 * 1024 * 1024;
var ATTACHMENT_AUDIO_TYPES = ['audio/wav', 'audio/x-wav', 'audio/wave', 'audio/mpeg', 'audio/mp3'];
var ATTACHMENT_AUDIO_EXTENSIONS = /\.(wav|mp3)$/i;

// Kept in sync with YOUTUBE_PATTERNS in app.py: /watch?v=, youtu.be/, /shorts/ and /embed/.
var YOUTUBE_PATTERNS = [
  /^https?:\/\/(?:www\.|m\.)?youtube\.com\/watch\/?\?(?:[^#]*&)?v=[A-Za-z0-9_-]{5,}(?:&[^#]*)?(?:#.*)?$/i,
  /^https?:\/\/(?:www\.|m\.)?youtu\.be\/[A-Za-z0-9_-]{5,}(?:\?[^#]*)?(?:#.*)?$/i,
  /^https?:\/\/(?:www\.|m\.)?youtube\.com\/(?:shorts|embed)\/[A-Za-z0-9_-]{5,}(?:[?#].*)?$/i
];

var YOUTUBE_LABEL = 'YouTube';
var ATTACHMENT_LABELS = { image: 'Hình ảnh', audio: 'Âm thanh', document: 'Tài liệu', youtube: YOUTUBE_LABEL };

// The trimmed text, when it is EXACTLY one supported YouTube link; otherwise null.
function isYouTubeUrl(value) {
  var raw = String(value == null ? '' : value).trim();
  if (!raw || /\s/.test(raw)) return null;
  for (var i = 0; i < YOUTUBE_PATTERNS.length; i++) {
    if (YOUTUBE_PATTERNS[i].test(raw)) return raw;
  }
  return null;
}

function detectTextPaste(value) {
  var url = isYouTubeUrl(value);
  return url ? { kind: 'youtube', url: url } : { kind: 'text' };
}

// What Ctrl+V should do. `targetId` is the id of the focused element, `files` the
// clipboard files and `text` the clipboard text. Anything but an image or a lone
// YouTube link falls through to the normal text paste.
function planPaste(targetId, files, text) {
  if (targetId === 'reference') return { action: 'text' };
  var list = files || [];
  for (var i = 0; i < list.length; i++) {
    if (String((list[i] && list[i].type) || '').indexOf('image/') === 0) {
      return { action: 'image', index: i };
    }
  }
  var detected = detectTextPaste(text);
  return detected.kind === 'youtube' ? { action: 'youtube', url: detected.url } : { action: 'text' };
}

function attachmentKind(file) {
  var type = String((file && file.type) || '').toLowerCase();
  var name = String((file && file.name) || '');
  if (ATTACHMENT_IMAGE_TYPES.indexOf(type) !== -1) return 'image';
  if (ATTACHMENT_AUDIO_TYPES.indexOf(type) !== -1 || ATTACHMENT_AUDIO_EXTENSIONS.test(name)) return 'audio';
  return 'document';
}

function attachmentTypeLabel(item) {
  return ATTACHMENT_LABELS[item && item.kind] || ATTACHMENT_LABELS.document;
}

function formatAttachmentSize(bytes) {
  var size = Number(bytes) || 0;
  if (size < 1024) return size + ' B';
  if (size < 1024 * 1024) return (size / 1024).toFixed(1) + ' KB';
  return (size / (1024 * 1024)).toFixed(1) + ' MB';
}

// YouTube links carry no size: the list shows the video label instead.
function attachmentSizeLabel(item) {
  if (!item || item.kind === 'youtube') return YOUTUBE_LABEL;
  return formatAttachmentSize(item.size);
}

function newAttachmentStore() {
  return { items: [], nextId: 1 };
}

// Local validation only (caps, image types, image size). Returns a Vietnamese error
// string, or null when the item may be added.
function attachmentError(store, item) {
  if (store.items.length >= ATTACHMENT_MAX_TOTAL) {
    return 'Tối đa ' + ATTACHMENT_MAX_TOTAL + ' tệp đính kèm.';
  }
  if (item && item.kind === 'image') {
    if (ATTACHMENT_IMAGE_TYPES.indexOf(String(item.mime || '').toLowerCase()) === -1) {
      return 'Ảnh không hợp lệ (chỉ chấp nhận PNG, JPEG, WebP, GIF).';
    }
    if ((Number(item.size) || 0) > ATTACHMENT_IMAGE_MAX_BYTES) {
      return 'Ảnh quá lớn (tối đa 20 MiB).';
    }
    var images = 0;
    for (var i = 0; i < store.items.length; i++) {
      if (store.items[i].kind === 'image') images++;
    }
    if (images >= ATTACHMENT_MAX_IMAGES) {
      return 'Tối đa ' + ATTACHMENT_MAX_IMAGES + ' ảnh.';
    }
  }
  return null;
}

function addAttachment(store, item) {
  var error = attachmentError(store, item);
  if (error) return { error: error };
  item.id = store.nextId++;
  store.items.push(item);
  return { item: item };
}

// Removes one item locally and instantly; no server call is involved.
function removeAttachment(store, id) {
  var target = Number(id);
  for (var i = 0; i < store.items.length; i++) {
    if (store.items[i].id === target) {
      store.items.splice(i, 1);
      return true;
    }
  }
  return false;
}

// Ordered list of attachments to send when "Học" is clicked (removed ones are gone).
function submissionPlan(store) {
  return store.items.slice();
}
