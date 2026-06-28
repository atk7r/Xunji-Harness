---
id: rich-text-editors
product: Rich text editor and file manager fingerprint patterns
vendor: cross-product
aliases: [CKEditor, Kindeditor, TinyMCE, UEditor, FCKeditor, 富文本编辑器, 编辑器上传]
category: weakness-recognition
last_reviewed: 2026-06-28
maturity: seed
signatures: ["/ckeditor/", "/kindeditor/", "/tinymce/", "/ueditor/", "/fckeditor/", "/editor/"]
---

<!--
PUBLIC grounding tier. Generic recognition of rich text editors and their
file upload/browse endpoints — cross-product, covers CKEditor, Kindeditor,
TinyMCE, UEditor, FCKeditor. Source: hamastar run (CKEditor 4.9.1), sxtbu
run (Kindeditor on cwc sub-station), cqytxy run.
-->

## Recognition (identification only)

- Signature (CKEditor): `/ckeditor/`, `/ckeditor/samples/`,
  `/ckeditor/CHANGES.md` (version disclosure), `/ckeditor/plugins/image/`,
  `CKEDITOR` in page JS. `/ckfinder/` (CKFinder file manager, commercial).
- Signature (Kindeditor): `/kindeditor/`, `/admin/kindeditor/`,
  `kindeditor.js`, `KindEditor.ready(function` in page source. Common in
  Chinese PHP/ASP.NET CMS (博达 VSB, 大汉 JCMS, etc.).
- Signature (TinyMCE): `/tinymce/`, `/js/tinymce/`,
  `tinymce.init({` in page source. `/tinymce/plugins/`.
- Signature (UEditor / Baidu Editor): `/ueditor/`, `/ueditor/dialogs/`,
  `UE.getEditor(` in page source, `/ueditor/php/controller.php`. Common
  in Chinese sites.
- Signature (FCKeditor): `/fckeditor/`, `/FCKeditor/`, `/fckeditor/editor/`,
  `/fckeditor/editor/filemanager/browser/default/browser.html`. Predecessor
  to CKEditor; still found on legacy Chinese ASP/PHP sites.
- Signature (generic): `/editor/`, `/upload/`, `/filemanager/`,
  `/admin/upload/`, `/attachments/` — not specific to one editor, but
  often exposed when an editor file browser is misconfigured.
- Distinguishing notes: the editor JS file itself is normally public —
  that's not a finding. The upload handler, file browser, or connector
  script reachable WITHOUT authentication is the attack surface.

## Weak-Point Anchors

- Anchor: unauthenticated file upload via editor connector
  - Affected: CKEditor ≤4.9.x (CVE-2018-17960, image uploader plugin);
    Kindeditor ≤4.1.11 (file_manager_json.php unauth upload, CNVD-C-2019-48316);
    UEditor (controller.php upload, CVE-2018-18071 class).
  - Mechanism: the upload handler (`upload.php`, `file_manager_json.php`,
    `controller.php?action=uploadfile`) is reachable without session and
    accepts arbitrary file types or fails to verify the extension. Results
    in webshell placement.
  - Reference: CVE-2018-17960 (CKEditor), CNVD-C-2019-48316 (Kindeditor),
    CVE-2018-18071 (UEditor)
  - source: external-cited
- Anchor: file browser / directory listing without auth
  - Affected: FCKeditor browser, CKFinder without auth, generic `/filemanager/`.
  - Mechanism: the file browser lists all uploaded files, server directories,
    and sometimes allows file deletion/renaming — server-side file manipulation
    without authentication.
  - Reference: CWE-306
  - source: external-cited
- Anchor: version disclosure via changelog / sample files
  - Affected: CKEditor `CHANGES.md`, UEditor `ueditor/README.md`, Kindeditor
    `kindeditor/CHANGELOG.md`.
  - Mechanism: exact version enables CVE matching; CKEditor 4.9.1 in
    hamastar → CVE-2018-17960, CVE-2023-28439 (requires authenticated
    editing context). The editor samples directory often exposes the version
    and capabilities.
  - Reference: CWE-200
  - source: run-observation (hamastar E-004 CKEditor 4.9.1;
    sxtbu cwc Kindeditor /admin/kindeditor/ 403 protected)

## Verification Principle

- Existence proof: fingerprint the editor by its JS path + version file.
  Confirm the editor is present. For upload endpoints: check if the handler
  is reachable WITHOUT credentials (GET or OPTIONS on the upload path). If
  auth-gated (403/redirect to login), the surface is NOT exploitable.
- Hard stops: fingerprint the editor and check auth on the upload handler.
  Do NOT upload files (even harmless proof files) autonomously — file upload
  crosses into data creation, which is a guard-managed action. If an upload
  endpoint is reachable unauthenticated, record as a HIGH candidate and let
  operator decide on proof-level upload test.

## False-Positive / Confounders

- The editor JS file loading in browser is NORMAL — not a finding. The
  attack surface is the upload handler, file browser, or connector.
- `/kindeditor/` returning 403 is a positive security signal (admin only).
- Some editors are deeply integrated into the CMS; their upload handler
  inherits CMS authentication. Do not assume "editor present = upload
  vulnerable."
- An upload handler returning "no file" or "invalid request" on a GET is
  normal (expects POST with multipart). Test the handler's auth by
  checking if POST without session returns 401/403 vs 200.

## References

- CVE-2018-17960 (CKEditor image uploader)
- CNVD: Kindeditor file_manager_json.php unauth upload
- This repo's run-observation: hamastar E-004 (CKEditor 4.9.1);
  sxtbu (Kindeditor on cwc sub-station, /admin/kindeditor/ 403)
- Related: [[backup-config-discovery]]
