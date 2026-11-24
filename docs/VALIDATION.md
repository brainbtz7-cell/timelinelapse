# Alpha validation

Verified locally on macOS with Python 3.14 and FFmpeg 8.0.1:

- All 10 standard-library tests pass.
- Actual H.264 export is checked for native, landscape, and portrait geometry, limited-range YUV 4:2:0, duration, silent audio behavior, and final-frame retention.
- API tests cover capture persistence, chronological validation, rejected non-JPEG data, read-only demo, token and origin restrictions, Host restrictions, partial-content serving, and ZIP backup.
- Browser UI: demo replay and MP4 export succeeded.
- Synthetic-window browser fixture: selected a crop, started interval recording, paused/resumed, finished with eight persisted frames, exported an MP4, reloaded the page, and reopened the saved session.
- No console warnings/errors were reported in those browser runs.

The synthetic fixture exercises the same app UI and capture pipeline while substituting the screen-sharing source. It does **not** validate OS window-sharing permissions or a live DaVinci Resolve window. That first live recording remains a user validation step. The bundled demo is simulated and labeled accordingly.
